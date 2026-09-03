import os
import sys

import duckdb
import lightgbm as lgb
import pandas as pd

from backend.database import DB_PATH, dedup_panel_sql

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from eda_pipeline import config as _cfg  # noqa: E402

# ── [2026-09-03] 서빙 모델을 lean_macro 로 교체 ───────────────────────────
#   종전 `lgbm_12m_model.txt` 는 구 누수 모델(230피처)로, CG01_KIS_SCORE /
#   CRIF_* / COPR_OPNP_C 같은 사후 정보가 들어 있어 SHAP 설명이 성립하지 않았다.
#   채택 모델은 `lgbm_v2_lean_macro.txt` (63피처, D8 상호작용 ix_* 14개 포함).
#   경로에 한글이 있어 `lgb.Booster(model_file=...)` 는 LightGBM C++ IO 에서
#   열지 못한다 — `config.load_booster()` 가 model_str 로 우회한다.
MODEL_PATH = str(_cfg.OUTPUT_DIR / 'lgbm_v2_lean_macro.txt')

_model = None
_baseline_df = None
_shap_explainer = None

# 학습 프레임에서 category dtype 이었던 피처. LightGBM 의
# `model.pandas_categorical` 은 "학습 DataFrame 컬럼 순서" 기준 리스트의 리스트라,
# 모델 피처 순서대로 짝지어야 인코딩이 맞는다 (예전에는 무조건 [0] 을
# OBV_ELYWRN_OBV_GRD_DSC 에 붙였는데, lean_macro 는 [0]=STD_INDS_SECTION,
# [1]=OBV_... 이므로 그대로 두면 업종 코드를 등급 축으로 인코딩해 값이 망가진다).
_CATEGORICAL_FEATURES = ('STD_INDS_SECTION', 'OBV_ELYWRN_OBV_GRD_DSC')


def get_model() -> lgb.Booster:
    global _model
    if _model is None:
        _model = _cfg.load_booster(MODEL_PATH)
    return _model


def _apply_categorical(df: pd.DataFrame, model: lgb.Booster) -> pd.DataFrame:
    """Restores the training-time pandas category dtype/order on the model's
    categorical features so LightGBM's integer codes line up."""
    if not model.pandas_categorical:
        return df
    cat_cols = [c for c in model.feature_name() if c in _CATEGORICAL_FEATURES]
    if len(cat_cols) != len(model.pandas_categorical):
        raise RuntimeError(
            f"categorical 피처 {len(cat_cols)}개 vs pandas_categorical "
            f"{len(model.pandas_categorical)}개 — _CATEGORICAL_FEATURES 갱신 필요")
    for col, categories in zip(cat_cols, model.pandas_categorical):
        if col in df.columns:
            df[col] = pd.Categorical(df[col].astype(str), categories=categories)
    return df


def get_baseline() -> pd.DataFrame:
    """Snapshot of the latest available month, used as the population the
    macro-shock simulation is re-scored against."""
    global _baseline_df
    if _baseline_df is None:
        model = get_model()
        features = model.feature_name()
        conn = duckdb.connect(DB_PATH, read_only=True)
        cols = ', '.join(f'"{c}"' for c in features)
        panel = dedup_panel_sql("WHERE BASE_YM = (SELECT MAX(BASE_YM) FROM corporate_panel)")
        df = conn.execute(f"""
            SELECT {cols}, BASE_YM
            FROM {panel}
        """).df()
        conn.close()
        _baseline_df = _apply_categorical(df, model)
    return _baseline_df


def get_shap_explainer():
    """TreeExplainer over the trained LightGBM model, cached at module scope
    since building it is the expensive part (~3s); per-row shap_values()
    calls are fast (<0.5s) once built."""
    global _shap_explainer
    if _shap_explainer is None:
        import shap
        _shap_explainer = shap.TreeExplainer(get_model())
    return _shap_explainer


def get_feature_row(bzno: str, base_ym: str | None) -> pd.DataFrame:
    """Single borrower's feature row (all model features) for SHAP scoring."""
    model = get_model()
    features = model.feature_name()
    conn = duckdb.connect(DB_PATH, read_only=True)
    cols = ', '.join(f'"{c}"' for c in features)
    where = "WHERE V_BZNO = ?"
    params = [bzno]
    if base_ym:
        panel = dedup_panel_sql(f"{where} AND CAST(BASE_YM AS VARCHAR) = ?")
        params.append(str(base_ym))
        order = ""
    else:
        panel = dedup_panel_sql(where)
        order = "ORDER BY BASE_YM DESC"
    df = conn.execute(f"SELECT {cols} FROM {panel} {order} LIMIT 1", params).df()
    conn.close()
    if df.empty:
        return df
    return _apply_categorical(df, model)


def get_industry_name(code) -> str:
    try:
        division = int(str(int(float(code))).zfill(5)[:2])
    except (ValueError, TypeError):
        return '분류불명'

    if 1 <= division <= 3:
        return '농업, 임업 및 어업'
    if 5 <= division <= 8:
        return '광업'
    if 10 <= division <= 34:
        return '제조업'
    if division == 35:
        return '전기, 가스 공급업'
    if 36 <= division <= 39:
        return '수도, 하수, 폐기물 처리업'
    if 41 <= division <= 42:
        return '건설업'
    if 45 <= division <= 47:
        return '도매 및 소매업'
    if 49 <= division <= 52:
        return '운수 및 창고업'
    if 55 <= division <= 56:
        return '숙박 및 음식점업'
    if 58 <= division <= 63:
        return '정보통신업'
    if 64 <= division <= 66:
        return '금융 및 보험업'
    if division == 68:
        return '부동산업'
    if 70 <= division <= 73:
        return '전문, 과학 및 기술'
    if 74 <= division <= 76:
        return '사업시설 관리 지원업'
    if division == 84:
        return '공공 행정 및 국방'
    if division == 85:
        return '교육 서비스업'
    if 86 <= division <= 87:
        return '보건업 및 사회복지 서비스업'
    if 90 <= division <= 91:
        return '예술, 스포츠 서비스업'
    if 94 <= division <= 96:
        return '협회 및 개인 서비스업'
    if 97 <= division <= 98:
        return '가구 내 고용활동'
    if division == 99:
        return '국제 기관'
    return '기타 업종'


# Domestic short/long rate curve columns shifted by a base-rate move (bp), and
# their 3-month moving-average counterparts (damped, since they smooth shocks).
_RATE_COLS = [
    'call_rate_overnight_diff12', 'call_rate_overnight_brokered_diff12',
    'corporate_bond_3y_AA_diff12', 'KORIBOR_12m_diff12', 'KORIBOR_3m_diff12',
    'KORIBOR_6m_diff12', 'treasury_bond_10y_diff12', 'treasury_bond_1y_diff12',
    'treasury_bond_3y_diff12', 'treasury_bond_5y_diff12', 'base_rate_diff12',
    'CD_rate_91d_diff12', 'treasury_bond_1y_monthly_diff12',
    'credit_spread_diff12', 'liquidity_spread_diff12',
]
_RATE_COLS_MA3M = [c + '_ma3m' for c in _RATE_COLS if (c + '_ma3m')]

_CPI_COLS = ['CPI_core_yoy', 'CPI_core_excl_food_energy_yoy', 'CPI_food_nonalcohol_yoy']
_CPI_COLS_MA3M = [c + '_ma3m' for c in _CPI_COLS]

_OIL_COLS = ['brent_crude_oil_log_ret', 'WTI_crude_oil_log_ret']
_OIL_COLS_MA3M = [c + '_ma3m' for c in _OIL_COLS]

_GROWTH_COLS = [
    'BSI_mfg_biz_yoy', 'BSI_mfg_export_yoy', 'BSI_mfg_domestic_yoy',
    'BSI_nonmfg_biz_yoy', 'CSI_composite_yoy', 'CSI_living_prospect_yoy',
    'export_index_yoy', 'import_index_yoy', 'trade_total_yoy',
    'current_account_yoy',
]
_GROWTH_COLS_MA3M = [c + '_ma3m' for c in _GROWTH_COLS]

# 국내 증시(코스피) 관련 컬럼 -- 전역 SHAP 중요도 1위(KOSPI_log_ret)를 포함하지만
# 기존 5개 슬라이더 어디에도 연동되어 있지 않았음.
_KOSPI_COLS = ['KOSPI_log_ret', 'KOSPI_vol_m', 'KOSDAQ_vol_m_ma3m']

# 글로벌 리스크(위험회피) 관련 컬럼 -- VIX 및 해외 증시.
_GLOBAL_RISK_COLS = ['VIX_vol_m', 'DowJones_log_ret', 'NASDAQ_vol_m', 'Shanghai_Composite_log_ret_ma3m']

# 원자재(유가 외 확장) -- 귀금속/농산물/천연가스/비철금속.
_COMMODITY_EXT_COLS = [
    'gold_log_ret_ma3m', 'corn_log_ret_ma3m', 'corn_vol_m', 'soybean_log_ret_ma3m',
    'soybean_vol_m_ma3m', 'natural_gas_vol_m', 'natural_gas_vol_m_ma3m',
    'copper_vol_m_ma3m', 'silver_vol_m_ma3m',
]

USD_KRW_REF_LEVEL = 1350.0  # approx won/dollar level, used to convert a won delta into a log-return shock
EUR_KRW_REF_LEVEL = 1450.0  # approx won/euro level, used to convert a won delta into a log-return shock
OIL_REF_LEVEL = 80.0        # approx USD/barrel level, used to convert a $ delta into a log-return shock


def apply_macro_shock(df: pd.DataFrame, interest_rate: float, exchange_rate: float,
                       inflation: float, oil_price: float, gdp_growth: float,
                       kospi_shock: float = 0.0, global_risk_shock: float = 0.0,
                       commodity_shock: float = 0.0, eur_shock: float = 0.0) -> pd.DataFrame:
    """Returns a copy of df with macro feature columns shifted according to
    the requested scenario. Only columns present in df are touched."""
    shocked = df.copy()

    def shift(cols, delta, damp=1.0):
        for c in cols:
            if c in shocked.columns:
                shocked[c] = shocked[c] + delta * damp

    # interest_rate는 UI상 "bp" 단위(예: +100bp)지만 _RATE_COLS는 %p 단위 컬럼(예:
    # base_rate_diff12 실측값 -0.23)이라, 100을 그대로 더하면 100%p라는 현실에
    # 존재할 수 없는 충격이 가해짐 -- bp -> %p로 나눠서 변환한다.
    interest_rate_pp = interest_rate / 100.0
    shift(_RATE_COLS, interest_rate_pp)
    shift(_RATE_COLS_MA3M, interest_rate_pp, damp=0.6)

    fx_log_ret = exchange_rate / USD_KRW_REF_LEVEL
    shift(['USD_KRW_log_ret'], fx_log_ret)
    shift(['USD_KRW_log_ret_ma3m'], fx_log_ret, damp=0.6)
    shift(['DXY_dollar_index_log_ret'], fx_log_ret, damp=0.5)
    if 'USD_KRW_vol_m' in shocked.columns:
        shocked['USD_KRW_vol_m'] = shocked['USD_KRW_vol_m'] + abs(fx_log_ret) * 0.5

    # EUR_KRW_vol_m은 전역 SHAP 중요도 2위(KOSPI_log_ret 다음)인 만큼 원/달러와는
    # 별도로 직접 조작 가능한 전용 슬라이더를 둔다.
    eur_log_ret = eur_shock / EUR_KRW_REF_LEVEL
    shift(['EUR_KRW_log_ret'], eur_log_ret)
    shift(['EUR_KRW_log_ret_ma3m'], eur_log_ret, damp=0.6)
    if 'EUR_KRW_vol_m' in shocked.columns:
        shocked['EUR_KRW_vol_m'] = shocked['EUR_KRW_vol_m'] + abs(eur_log_ret) * 30.0

    shift(_CPI_COLS, inflation)
    shift(_CPI_COLS_MA3M, inflation, damp=0.6)
    if 'PPI_total_yoy' in shocked.columns:
        shocked['PPI_total_yoy'] = shocked['PPI_total_yoy'] + inflation * 0.5

    oil_log_ret = oil_price / OIL_REF_LEVEL
    shift(_OIL_COLS, oil_log_ret)
    shift(_OIL_COLS_MA3M, oil_log_ret, damp=0.6)

    shift(_GROWTH_COLS, gdp_growth)
    shift(_GROWTH_COLS_MA3M, gdp_growth, damp=0.6)

    # kospi_shock: 코스피 등락률(%) -- 예: -10 = 코스피 -10%
    kospi_log_ret = kospi_shock / 100.0
    shift(['KOSPI_log_ret'], kospi_log_ret)
    if 'KOSPI_vol_m' in shocked.columns:
        shocked['KOSPI_vol_m'] = shocked['KOSPI_vol_m'] + abs(kospi_log_ret) * 50.0
    if 'KOSDAQ_vol_m_ma3m' in shocked.columns:
        shocked['KOSDAQ_vol_m_ma3m'] = shocked['KOSDAQ_vol_m_ma3m'] + abs(kospi_log_ret) * 60.0

    # global_risk_shock: VIX 포인트 변화 -- 예: +20 = VIX 20pt 급등(위험회피 국면)
    if 'VIX_vol_m' in shocked.columns:
        shocked['VIX_vol_m'] = shocked['VIX_vol_m'] + global_risk_shock
    shift(['DowJones_log_ret'], -global_risk_shock * 0.005)
    if 'NASDAQ_vol_m' in shocked.columns:
        shocked['NASDAQ_vol_m'] = shocked['NASDAQ_vol_m'] + global_risk_shock * 0.3
    shift(['Shanghai_Composite_log_ret_ma3m'], -global_risk_shock * 0.003)

    # commodity_shock: 원자재 가격 등락률(%) -- 금·농산물·천연가스·비철금속에 함께 반영
    commodity_log_ret = commodity_shock / 100.0
    shift(['gold_log_ret_ma3m'], commodity_log_ret, damp=0.6)
    shift(['corn_log_ret_ma3m'], commodity_log_ret, damp=0.6)
    shift(['soybean_log_ret_ma3m'], commodity_log_ret, damp=0.6)
    if 'corn_vol_m' in shocked.columns:
        shocked['corn_vol_m'] = shocked['corn_vol_m'] + abs(commodity_log_ret) * 30.0
    if 'soybean_vol_m_ma3m' in shocked.columns:
        shocked['soybean_vol_m_ma3m'] = shocked['soybean_vol_m_ma3m'] + abs(commodity_log_ret) * 30.0
    if 'natural_gas_vol_m' in shocked.columns:
        shocked['natural_gas_vol_m'] = shocked['natural_gas_vol_m'] + abs(commodity_log_ret) * 30.0
    if 'natural_gas_vol_m_ma3m' in shocked.columns:
        shocked['natural_gas_vol_m_ma3m'] = shocked['natural_gas_vol_m_ma3m'] + abs(commodity_log_ret) * 20.0
    if 'copper_vol_m_ma3m' in shocked.columns:
        shocked['copper_vol_m_ma3m'] = shocked['copper_vol_m_ma3m'] + abs(commodity_log_ret) * 20.0
    if 'silver_vol_m_ma3m' in shocked.columns:
        shocked['silver_vol_m_ma3m'] = shocked['silver_vol_m_ma3m'] + abs(commodity_log_ret) * 20.0

    return shocked
