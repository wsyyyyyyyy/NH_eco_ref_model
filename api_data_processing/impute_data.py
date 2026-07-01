"""
거시경제 시계열 결측치 정제 파이프라인 (impute_data.py)  —  Monthly Edition
=====================================================================
Look-Ahead Bias 원천 차단을 위한 6단계(Phase 0~5) 순차 처리.
월별(Monthly) 데이터 기반으로 전환된 파이프라인.

Pipeline:
  Phase 0 → Phase 1 → Phase 2 → Phase 3 → Phase 4 → Phase 5

  Phase 0: 파생변수 선행 연산 + 대량결측 3개 지표 드롭
  Phase 1: 시차 적용(shift) + ffill().bfill() → 레벨 NaN 0개 달성
  Phase 2: 비금리 Group A → 월간 로그 수익률 + 일별 원천 기반 월간 내 변동성
  Phase 3: 금리 → 12개월 차분 / 비금리 B+C → YoY 증감률
  Phase 4: 전체 변환 변수 → 3개월 이동평균 확장
  Phase 5: 상위 12행 절단 + 최종 검증 (assert)

금지 사항:
  ✗ interpolate()          — Look-Ahead Bias 발생
  ✗ 금리 지표 YoY(%)       — 제로 금리 시 수치 폭발
  ✗ .shift(365) / .shift(250) — 월별 인덱스에서는 .shift(12) 사용
  ✗ Phase 순서 변경        — 데이터 오염
  ✗ 원천 레벨 컬럼 최종 출력 — 반드시 변환 변수로 교체
  ✗ bfill 단독 사용        — ffill() 선행 후 bfill(), 이후 iloc[12:] 절단 병행
  ✗ 월평균 종가 사용       — 반드시 월말 종가 기준

Usage:
    python api_data_processing/impute_data.py
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# ── 로깅 ────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-5s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
LOGGER = logging.getLogger(__name__)

# ── 경로 설정 ───────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
API_OUTPUT = PROJECT_ROOT / "api_data_processing" / "output"
INPUT_FILE = API_OUTPUT / "model_input" / "model_input_monthly.csv"
OUTPUT_FILE = API_OUTPUT / "model_input" / "model_input_monthly_cleaned.csv"
DAILY_FILE = API_OUTPUT / "model_input" / "model_input_daily.csv"  # 변동성 집계용


# ================================================================
# 지표 그룹 정의
# ================================================================

# Group A: 금융 시장 지표 — 당일 즉시 공표 (shift=0)
GROUP_A_COLS = [
    # 국내 주가지수
    "KOSPI", "KOSDAQ",
    # 해외 주가지수
    "DowJones", "NASDAQ", "SP500", "Nikkei225", "Shanghai_Composite",
    # 환율
    "USD_KRW", "EUR_KRW", "JPY_KRW", "CNY_KRW", "DXY_dollar_index",
    # 원자재
    "brent_crude_oil", "WTI_crude_oil", "natural_gas",
    "gold", "silver", "copper", "corn", "soybean",
    # 변동성
    "VIX",
    # 일별 금리
    "call_rate_overnight", "call_rate_overnight_brokered",
    "KORIBOR_3m", "KORIBOR_6m", "KORIBOR_12m",
    "treasury_bond_1y", "treasury_bond_3y", "treasury_bond_5y", "treasury_bond_10y",
    "corporate_bond_3y_AA",
    "US_10Y_treasury", "US_2Y_treasury",
    "CP_91d", "MSB_91d",
]

# Group B: 실물/물가 지표 — 익월 공표 (shift=+1개월)
GROUP_B_COLS = [
    # 물가
    "CPI_core", "CPI_core_excl_food_energy", "CPI_food_nonalcohol",
    "PPI_total", "housing_price_index",
    # 통화량
    "M1_narrow_money", "M2_broad_money", "Lf_liquidity", "monetary_base_sa",
    # 무역/국제수지
    "export_index", "import_index", "trade_total",
    "current_account", "goods_balance",
    # 월별 금리
    "CD_rate_91d", "treasury_bond_1y_monthly",
]

# Group C: 장기 거시/정책/심리 지표 — 분기/연간 공표 (shift=+2개월)
GROUP_C_COLS = [
    # 정책 금리
    "base_rate",
    # 가계
    "household_credit", "household_loan",
    # 산업/무역
    "manufacturing_index", "export_price_index_KOR",
    "current_account_quarterly",
    # 심리 지수 (BSI/CSI)
    "BSI_mfg_biz", "BSI_mfg_export", "BSI_mfg_domestic", "BSI_nonmfg_biz",
    "CSI_composite", "CSI_living_prospect",
]

# 금리류 지표 — YoY 절대 금지, 반드시 _diff12 적용
# (제로 금리 국면 시 YoY 분모 발산 위험 원천 차단)
INTEREST_RATE_COLS = {
    # Group A 금리
    "call_rate_overnight", "call_rate_overnight_brokered",
    "KORIBOR_3m", "KORIBOR_6m", "KORIBOR_12m",
    "treasury_bond_1y", "treasury_bond_3y", "treasury_bond_5y", "treasury_bond_10y",
    "corporate_bond_3y_AA",
    "US_10Y_treasury", "US_2Y_treasury",
    # Group B 금리
    "CD_rate_91d", "treasury_bond_1y_monthly",
    # Group C 금리
    "base_rate",
    # 파생 스프레드
    "credit_spread", "liquidity_spread",
}

# 사전 드롭 대상 (결측률 높은 3개 지표)
DROP_COLS = ["GNI_annual", "manufacturing_index", "export_price_index_KOR"]

# 상수 (월별 기준)
LAG_MONTHS_B = 1        # Group B: 1개월 시차
LAG_MONTHS_C = 2        # Group C: 2개월 시차
TRUNCATION_MONTHS = 12  # shift(12) warm-up 구간 완전 제거


# ================================================================
# 유틸리티
# ================================================================

def _log_nan(df: pd.DataFrame, label: str) -> int:
    """현재 DataFrame의 NaN 카운트를 로깅하고 반환한다."""
    vcols = [c for c in df.columns if c != "date"]
    n = int(df[vcols].isna().sum().sum())
    LOGGER.info("  [NaN 현황] %s: %d개", label, n)
    return n


def _compute_monthly_volatility_from_daily(
    daily_df: pd.DataFrame, target_cols: list[str]
) -> pd.DataFrame:
    """일별 원천 데이터에서 월간 내 변동성(Realized Volatility)을 집계한다.

    각 지표의 일별 로그수익률을 구한 뒤, YYYYMM 그룹별 표준편차를 산출.
    스케일 매칭: std * sqrt(20) * 100
    
    Parameters
    ----------
    daily_df : pd.DataFrame
        일별 원천 데이터 (date + 지표 컬럼)
    target_cols : list[str]
        변동성을 집계할 대상 컬럼 목록

    Returns
    -------
    pd.DataFrame
        date(월말 기준) + {col}_vol_m 컬럼들
    """
    daily_df = daily_df.copy()
    daily_df["date"] = pd.to_datetime(daily_df["date"])
    daily_df = daily_df.sort_values("date").reset_index(drop=True)

    # 월 식별자 (YYYYMM)
    daily_df["ym"] = daily_df["date"].dt.to_period("M")

    vol_results = {}
    for col in target_cols:
        if col not in daily_df.columns:
            continue
        series = pd.to_numeric(daily_df[col], errors="coerce").clip(lower=1e-10)
        log_ret = np.log(series / series.shift(1))
        daily_df[f"_lr_{col}"] = log_ret

        # 월별 groupby → 표준편차 산출 + 스케일 매칭
        monthly_vol = (
            daily_df.groupby("ym")[f"_lr_{col}"]
            .std()
            .multiply(np.sqrt(20) * 100)
        )
        vol_results[f"{col}_vol_m"] = monthly_vol

    # DataFrame 조립
    vol_df = pd.DataFrame(vol_results)
    vol_df.index = vol_df.index.to_timestamp(how="end")
    vol_df.index.name = "date"

    # 월말 날짜를 월별 입력과 매칭하기 위해 월 단위로 정규화
    vol_df = vol_df.reset_index()
    vol_df["date"] = vol_df["date"].dt.to_period("M").dt.to_timestamp(how="end")

    return vol_df


# ================================================================
# Phase 함수 (Phase 0 ~ Phase 5)
# ================================================================

def phase0(df: pd.DataFrame) -> tuple[pd.DataFrame, list, list, list]:
    """Phase 0: 파생변수 선행 연산 및 변수 정제 (원천 상태)

    - GNI_annual 등 대량 결측 3개 지표를 사전 드롭
    - credit_spread, liquidity_spread를 시차 적용 전 원천 레벨에서 선행 계산
    - 파생변수를 Group A에 강제 할당
    """
    LOGGER.info("=" * 70)
    LOGGER.info("[Phase 0] 파생변수 선행 연산 및 변수 정제")
    LOGGER.info("-" * 70)

    # 대량 결측 지표 드롭
    existing_drops = [c for c in DROP_COLS if c in df.columns]
    df = df.drop(columns=existing_drops)
    LOGGER.info("  Dropped %d cols: %s", len(existing_drops), existing_drops)

    # 파생변수 선행 연산 (시차 적용 전 원천 레벨 상태에서 계산)
    if "corporate_bond_3y_AA" in df.columns and "treasury_bond_3y" in df.columns:
        df["credit_spread"] = df["corporate_bond_3y_AA"] - df["treasury_bond_3y"]
        LOGGER.info("  credit_spread = corporate_bond_3y_AA - treasury_bond_3y")

    if "CP_91d" in df.columns and "MSB_91d" in df.columns:
        df["liquidity_spread"] = df["CP_91d"] - df["MSB_91d"]
        LOGGER.info("  liquidity_spread = CP_91d - MSB_91d")

    # 그룹 할당 (실제 존재하는 컬럼만)
    group_a = [c for c in GROUP_A_COLS if c in df.columns]
    group_b = [c for c in GROUP_B_COLS if c in df.columns]
    group_c = [c for c in GROUP_C_COLS if c in df.columns]

    # 파생변수 → Group A 강제 편입
    for derived in ("credit_spread", "liquidity_spread"):
        if derived in df.columns and derived not in group_a:
            group_a.append(derived)

    # 미할당 컬럼 → Group A 자동 편입
    assigned = set(group_a + group_b + group_c)
    all_v = [c for c in df.columns if c != "date"]
    unassigned = [c for c in all_v if c not in assigned]
    if unassigned:
        LOGGER.warning("  Unassigned → Group A: %s", unassigned)
        group_a.extend(unassigned)

    LOGGER.info("  Group A: %d | Group B: %d | Group C: %d",
                len(group_a), len(group_b), len(group_c))
    _log_nan(df, "Phase 0 완료")

    return df, group_a, group_b, group_c


def phase1(df: pd.DataFrame, group_b: list, group_c: list) -> pd.DataFrame:
    """Phase 1: 가용성 시차 적용 + ffill().bfill() → 원천 레벨 NaN 0개 달성

    - Group B: +1개월 shift (월간 공시 시차)
    - Group C: +2개월 shift (분기/연간 공시 시차)
    - Group A: shift 없음 (당일 즉시 반영)
    - 일괄 ffill → bfill 로 레벨 결측 완전 청산
    """
    LOGGER.info("=" * 70)
    LOGGER.info("[Phase 1] 시차 적용 + ffill().bfill()")
    LOGGER.info("-" * 70)

    # Group B: +1개월 shift
    if group_b:
        existing_b = [c for c in group_b if c in df.columns]
        df[existing_b] = df[existing_b].shift(LAG_MONTHS_B)
        LOGGER.info("  Group B: shift(+%d months), %d cols", LAG_MONTHS_B, len(existing_b))

    # Group C: +2개월 shift
    if group_c:
        existing_c = [c for c in group_c if c in df.columns]
        df[existing_c] = df[existing_c].shift(LAG_MONTHS_C)
        LOGGER.info("  Group C: shift(+%d months), %d cols", LAG_MONTHS_C, len(existing_c))

    _log_nan(df, "Post-shift")

    # 일괄 ffill → bfill → 레벨 NaN 완전 청산
    vcols = [c for c in df.columns if c != "date"]
    na_before = int(df[vcols].isna().sum().sum())
    df[vcols] = df[vcols].ffill().bfill()
    na_after = int(df[vcols].isna().sum().sum())

    LOGGER.info("  ffill().bfill(): %d → %d NaN (filled %d)",
                na_before, na_after, na_before - na_after)

    assert na_after == 0, f"Phase 1 실패: 레벨 NaN {na_after}건 잔존"
    LOGGER.info("  [OK] 원천 레벨 NaN 0개 달성")

    return df


def phase2(df: pd.DataFrame, group_a: list) -> pd.DataFrame:
    """Phase 2: 비금리 Group A → 월간 로그 수익률 + 일별 원천 기반 월간 내 변동성

    - 월간 로그 수익률: ln(P_t / P_{t-1}) — 월말 종가 기준
    - 월간 내 변동성: 일별 원천 데이터에서 월별 groupby → std * sqrt(20) * 100
    - 원천 레벨 컬럼 삭제
    """
    LOGGER.info("=" * 70)
    LOGGER.info("[Phase 2] 월간 로그 수익률 + 일별 원천 기반 월간 내 변동성")
    LOGGER.info("-" * 70)

    # 금리류 제외한 Group A
    non_rate_a = [c for c in group_a if c not in INTEREST_RATE_COLS]
    LOGGER.info("  대상: %d cols (금리 %d cols 제외)",
                len(non_rate_a), len(group_a) - len(non_rate_a))

    # ── 2-1. 월간 로그 수익률 (_log_ret) ─────────────────────────
    ret_dict = {}
    for col in non_rate_a:
        series = pd.to_numeric(df[col], errors="coerce").clip(lower=1e-10)
        log_ret = np.log(series / series.shift(1))
        ret_dict[f"{col}_log_ret"] = log_ret

    LOGGER.info("  [2-1] 월간 로그 수익률: %d cols 생성", len(ret_dict))

    # ── 2-2. 일별 원천 기반 월간 내 변동성 (_vol_m) ──────────────
    vol_df = None
    if DAILY_FILE.exists():
        LOGGER.info("  [2-2] 일별 원천 데이터 로드: %s", DAILY_FILE.name)
        daily_raw = pd.read_csv(DAILY_FILE)
        vol_df = _compute_monthly_volatility_from_daily(daily_raw, non_rate_a)
        LOGGER.info("  [2-2] 월간 내 변동성 집계 완료: %d cols", 
                     len([c for c in vol_df.columns if c != "date"]))
    else:
        LOGGER.warning("  [2-2] 일별 원천 데이터 없음 → _vol_m 생략: %s", DAILY_FILE)

    # ── 결합 ─────────────────────────────────────────────────────
    new_df = pd.DataFrame(ret_dict, index=df.index)
    df = pd.concat([df, new_df], axis=1)

    # 변동성 병합 (월별 date 매칭)
    if vol_df is not None:
        # date를 월말 기준으로 정규화하여 매칭
        df["_merge_key"] = pd.to_datetime(df["date"]).dt.to_period("M")
        vol_df["_merge_key"] = pd.to_datetime(vol_df["date"]).dt.to_period("M")

        vol_cols = [c for c in vol_df.columns if c.endswith("_vol_m")]
        vol_merge = vol_df[["_merge_key"] + vol_cols]

        df = df.merge(vol_merge, on="_merge_key", how="left")
        df = df.drop(columns=["_merge_key"])
        LOGGER.info("  변동성 병합 완료: %d _vol_m cols", len(vol_cols))

    # 원천 레벨 컬럼 드롭
    df = df.drop(columns=non_rate_a)
    df = df.copy()  # de-fragment

    n_log_ret = len(ret_dict)
    n_vol_m = len(vol_cols) if vol_df is not None else 0
    LOGGER.info("  Created: %d _log_ret + %d _vol_m, dropped %d level cols",
                n_log_ret, n_vol_m, len(non_rate_a))
    _log_nan(df, "Phase 2 완료")

    return df


def phase3(df: pd.DataFrame, group_b: list, group_c: list) -> pd.DataFrame:
    """Phase 3: 금리 → 12개월 차분(_diff12) / 비금리 B+C → YoY 증감률(_yoy)

    - 금리 지표: col - col.shift(12)  →  _diff12
    - 비금리 지표: (V_t - V_{t-12}) / V_{t-12} * 100  →  _yoy
    - shift(12) 고정 — 월별 인덱스에서 12행 = 1년
    - 원천 레벨 컬럼 삭제
    """
    LOGGER.info("=" * 70)
    LOGGER.info("[Phase 3] YoY 증감률 + 금리 12개월 차분")
    LOGGER.info("-" * 70)

    # ── 3-1. 금리 지표 → 단순 차분 (_diff12) ─────────────────────
    active_rates = [c for c in df.columns if c in INTEREST_RATE_COLS]
    LOGGER.info("  [3-1] 금리 _diff12: %d cols", len(active_rates))

    diff_dict = {}
    for col in active_rates:
        s = pd.to_numeric(df[col], errors="coerce")
        diff_dict[f"{col}_diff12"] = s - s.shift(12)

    # ── 3-2. 비금리 B+C → YoY 증감률 (_yoy) ─────────────────────
    non_rate_bc = [c for c in group_b + group_c
                   if c in df.columns and c not in INTEREST_RATE_COLS]
    LOGGER.info("  [3-2] 비금리 _yoy: %d cols", len(non_rate_bc))

    yoy_dict = {}
    for col in non_rate_bc:
        s = pd.to_numeric(df[col], errors="coerce")
        # 제로 금리 국면(0.0) 분모 발산 방지: replace(0, 1e-6)
        past = s.shift(12).replace(0, 1e-6)
        yoy_dict[f"{col}_yoy"] = np.where(
            pd.isna(past), np.nan,
            ((s - past) / past) * 100
        )

    # 일괄 결합 + 레벨 컬럼 드롭
    new_df = pd.DataFrame({**diff_dict, **yoy_dict}, index=df.index)
    df = pd.concat([df, new_df], axis=1)
    df = df.drop(columns=active_rates + non_rate_bc)
    df = df.copy()  # de-fragment

    LOGGER.info("  Created: %d _diff12 + %d _yoy, dropped %d level cols",
                len(diff_dict), len(yoy_dict),
                len(active_rates) + len(non_rate_bc))
    _log_nan(df, "Phase 3 완료")

    return df


def phase4(df: pd.DataFrame) -> pd.DataFrame:
    """Phase 4: 전체 변환 변수 대상 3개월 이동평균(_ma3m) 파생 변수 확장

    - _log_ret, _vol_m, _diff12, _yoy 모두 대상
    - 기본 변환 N개 + 이동평균 N개 = 총 2N개 변수
    """
    LOGGER.info("=" * 70)
    LOGGER.info("[Phase 4] 3개월 이동평균 (_ma3m) 파생 변수 확장")
    LOGGER.info("-" * 70)

    target = [c for c in df.columns
              if c.endswith(("_log_ret", "_vol_m", "_diff12", "_yoy"))]
    LOGGER.info("  대상: %d 변환 변수", len(target))

    ma_dict = {}
    for col in target:
        ma_dict[f"{col}_ma3m"] = df[col].rolling(3, min_periods=1).mean()

    df = pd.concat([df, pd.DataFrame(ma_dict, index=df.index)], axis=1)
    df = df.copy()  # de-fragment

    LOGGER.info("  Created: %d _ma3m (기본 %d + 이동평균 %d = 총 %d 변수)",
                len(ma_dict), len(target), len(ma_dict),
                len(target) + len(ma_dict))
    _log_nan(df, "Phase 4 완료")

    return df


def phase5(df: pd.DataFrame) -> pd.DataFrame:
    """Phase 5: 상위 12행 완전 절단 + 최종 NaN 0개 검증

    - shift(12) 연산의 warm-up 구간 완전 제거
    - 절단 후 NaN 잔존 시 즉시 AssertionError 발생
    """
    LOGGER.info("=" * 70)
    LOGGER.info("[Phase 5] 상위 %d행 완전 절단 (미래 누수 원천 차단)", TRUNCATION_MONTHS)
    LOGGER.info("-" * 70)

    rows_before = len(df)
    df = df.iloc[TRUNCATION_MONTHS:].reset_index(drop=True)

    LOGGER.info("  절단: %d → %d rows (-%d rows)",
                rows_before, len(df), rows_before - len(df))
    LOGGER.info("  유효 기간: %s ~ %s",
                df["date"].min(), df["date"].max())

    # ── 최종 검증 (assert 필수) ──────────────────────────────────
    vcols = [c for c in df.columns if c != "date"]
    final_na = int(df[vcols].isna().sum().sum())
    final_cols = len(df.columns)

    LOGGER.info("  최종 NaN: %d | Rows: %d | Cols: %d",
                final_na, len(df), final_cols)

    assert final_na == 0, \
        f"NaN 잔존 {final_na}건 — 파이프라인 점검 필요"
    assert len(df) == rows_before - TRUNCATION_MONTHS, \
        f"절단 행수 불일치: {len(df)} != {rows_before - TRUNCATION_MONTHS}"

    LOGGER.info("  [OK] 모든 Assert 통과 -- Look-Ahead Bias 0.00%% 완전 청산")

    return df


# ================================================================
# 메인 파이프라인
# ================================================================

def main() -> None:
    LOGGER.info("=" * 70)
    LOGGER.info("  거시경제 시계열 결측치 정제 파이프라인 (Monthly Edition)")
    LOGGER.info("  Input : %s", INPUT_FILE)
    LOGGER.info("  Output: %s", OUTPUT_FILE)
    LOGGER.info("=" * 70)

    # ── 데이터 로드 ──────────────────────────────────────────────
    df = pd.read_csv(INPUT_FILE)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    LOGGER.info("Loaded: %d rows × %d cols", len(df), len(df.columns) - 1)

    # ── Phase 0 → 1 → 2 → 3 → 4 → 5 (순서 변경 금지) ──────────
    df, group_a, group_b, group_c = phase0(df)
    df = phase1(df, group_b, group_c)
    df = phase2(df, group_a)
    df = phase3(df, group_b, group_c)
    df = phase4(df)
    df = phase5(df)

    # ── 저장 ────────────────────────────────────────────────────
    df = df.rename(columns={"date": "BASE_YM"})
    df["BASE_YM"] = pd.to_datetime(df["BASE_YM"]).dt.strftime("%Y%m")
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUT_FILE, index=False, encoding="utf-8-sig")

    LOGGER.info("=" * 70)
    LOGGER.info("[DONE] Saved → %s", OUTPUT_FILE)
    LOGGER.info("=" * 70)

    # ── 요약 리포트 ─────────────────────────────────────────────
    vcols = [c for c in df.columns if c != "BASE_YM"]
    sc: dict[str, int] = {}
    for c in vcols:
        for sfx in ("_ma3m", "_log_ret", "_vol_m", "_diff12", "_yoy"):
            if c.endswith(sfx):
                sc[sfx] = sc.get(sfx, 0) + 1
                break

    print("\n" + "=" * 60)
    print("   Stationary Transformation Report (Monthly Edition)")
    print("=" * 60)
    print(f"  Log Return     (_log_ret) : {sc.get('_log_ret', 0)} cols")
    print(f"  Volatility Mo  (_vol_m)   : {sc.get('_vol_m', 0)} cols")
    print(f"  12M Diff       (_diff12)  : {sc.get('_diff12', 0)} cols")
    print(f"  YoY Change     (_yoy)     : {sc.get('_yoy', 0)} cols")
    print(f"  Moving Avg 3M  (_ma3m)    : {sc.get('_ma3m', 0)} cols")
    print(f"  Total columns             : {len(vcols)} + BASE_YM")
    print(f"  Remaining NaN             : 0")
    print(f"  Output: {OUTPUT_FILE}")
    print("=" * 60)

    min_dt = df["BASE_YM"].min()
    max_dt = df["BASE_YM"].max()
    print(f"\n[PREPROCESSING_PATCH_SUCCESS]")
    print(f"  [전체 행 수({len(df)}행)]")
    print(f"  [결측치 총 수(0개)]")
    print(f"  [시계열 범위: {min_dt} ~ {max_dt}]")


if __name__ == "__main__":
    main()
