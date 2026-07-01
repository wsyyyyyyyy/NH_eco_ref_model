import duckdb
import lightgbm as lgb
import pandas as pd

from backend.database import DB_PATH

MODEL_PATH = 'eda_pipeline/output/lgbm_12m_model.txt'

_model = None
_baseline_df = None


def get_model() -> lgb.Booster:
    global _model
    if _model is None:
        _model = lgb.Booster(model_file=MODEL_PATH)
    return _model


def get_baseline() -> pd.DataFrame:
    """Snapshot of the latest available month, used as the population the
    macro-shock simulation is re-scored against."""
    global _baseline_df
    if _baseline_df is None:
        model = get_model()
        features = model.feature_name()
        conn = duckdb.connect(DB_PATH, read_only=True)
        cols = ', '.join(f'"{c}"' for c in features)
        df = conn.execute(f"""
            SELECT {cols}, BASE_YM
            FROM corporate_panel
            WHERE BASE_YM = (SELECT MAX(BASE_YM) FROM corporate_panel)
        """).df()
        conn.close()

        # LightGBM trained with OBV_ELYWRN_OBV_GRD_DSC as the sole categorical
        # feature (categories '-1'/'A'/'B'); the exact category order must
        # match model.pandas_categorical for encoding to line up.
        cat_col = 'OBV_ELYWRN_OBV_GRD_DSC'
        if cat_col in df.columns and model.pandas_categorical:
            categories = model.pandas_categorical[0]
            df[cat_col] = pd.Categorical(df[cat_col].astype(str), categories=categories)

        _baseline_df = df
    return _baseline_df


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

USD_KRW_REF_LEVEL = 1350.0  # approx won/dollar level, used to convert a won delta into a log-return shock
OIL_REF_LEVEL = 80.0        # approx USD/barrel level, used to convert a $ delta into a log-return shock


def apply_macro_shock(df: pd.DataFrame, interest_rate: float, exchange_rate: float,
                       inflation: float, oil_price: float, gdp_growth: float) -> pd.DataFrame:
    """Returns a copy of df with macro feature columns shifted according to
    the requested scenario. Only columns present in df are touched."""
    shocked = df.copy()

    def shift(cols, delta, damp=1.0):
        for c in cols:
            if c in shocked.columns:
                shocked[c] = shocked[c] + delta * damp

    shift(_RATE_COLS, interest_rate)
    shift(_RATE_COLS_MA3M, interest_rate, damp=0.6)

    fx_log_ret = exchange_rate / USD_KRW_REF_LEVEL
    shift(['USD_KRW_log_ret'], fx_log_ret)
    shift(['USD_KRW_log_ret_ma3m'], fx_log_ret, damp=0.6)
    shift(['DXY_dollar_index_log_ret'], fx_log_ret, damp=0.5)
    if 'USD_KRW_vol_m' in shocked.columns:
        shocked['USD_KRW_vol_m'] = shocked['USD_KRW_vol_m'] + abs(fx_log_ret) * 0.5

    shift(_CPI_COLS, inflation)
    shift(_CPI_COLS_MA3M, inflation, damp=0.6)
    if 'PPI_total_yoy' in shocked.columns:
        shocked['PPI_total_yoy'] = shocked['PPI_total_yoy'] + inflation * 0.5

    oil_log_ret = oil_price / OIL_REF_LEVEL
    shift(_OIL_COLS, oil_log_ret)
    shift(_OIL_COLS_MA3M, oil_log_ret, damp=0.6)

    shift(_GROWTH_COLS, gdp_growth)
    shift(_GROWTH_COLS_MA3M, gdp_growth, damp=0.6)

    return shocked
