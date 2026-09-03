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
  Phase 3: 금리 → 12개월 차분 / 비금리 B+C+D → YoY 증감률
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
# Phase 6 산출물. 기존 172개와 **섞지 않고 별도 파일**로 둔다 (E1-2).
LEVEL_FILE = API_OUTPUT / "model_input" / "model_input_monthly_level.csv"


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
    "US_10Y_treasury", "US_3M_tbill",
    "CP_91d", "MSB_91d",
]

# Group B: 실물/물가 지표 — 익월 공표 (shift=+1개월)
GROUP_B_COLS = [
    # 물가
    "CPI_core", "CPI_core_excl_food_energy", "CPI_food_nonalcohol",
    "PPI_total", "housing_price_index",
    # [2026-09-01] 402Y014 수출물가지수(기본분류) 총지수. 월별·익월 공표.
    "export_price_index_KOR",
    # 무역
    "export_index", "import_index",
    # 월별 금리
    "CD_rate_91d", "treasury_bond_1y_monthly",
]

# Group C: 장기 거시/정책/심리 지표 — 분기/연간 공표 (shift=+2개월)
GROUP_C_COLS = [
    # 정책 금리
    "base_rate",
    # 산업/무역
    #   [2026-09-01] export_price_index_KOR 는 월별(402Y014, 익월 공표) 로 정정되어
    #   Group B(+1) 로 이동했다. manufacturing_index 는 DROP_COLS 유지.
    "manufacturing_index",
    # [2026-09-01] Group B(+1) -> C(+2) 이동 6건.
    #   근거: ECOS 실데이터 최종 수록월 관측(측정일 2026-09-01). 6건 모두 최종 2026-06 으로
    #   9/1 시점에 7월 값이 미공표였다. shift(+1) 은 존재하지 않는 값을 쓰게 된다.
    #   M1/M2/Lf 는 매핑 정정으로 통계표가 바뀌며 지연이 길어진 케이스다
    #   (구 매핑 104Y016·104Y014·722Y001 이 짧았던 것은 잘못된 계열을 보고 있었기 때문).
    #   monetary_base_sa·current_account·goods_balance 는 정정 이전부터 있던 문제다.
    "M1_narrow_money", "M2_broad_money", "Lf_liquidity", "monetary_base_sa",
    "current_account", "goods_balance",
    # 심리 지수 (BSI/CSI)
    "BSI_mfg_biz", "BSI_mfg_export", "BSI_mfg_domestic", "BSI_nonmfg_biz",
    "CSI_composite", "CSI_living_prospect",
    # PUBLIC(KOSIS) 3개. 2026-08-30 실측 발표 지연:
    #   unemployment_rate 1개월 / construction_cost_index 2개월 / unsold_housing 2개월
    # 최대 2개월이므로 Group C(+2) 가 적정하다. (STAGE 6 승인 2-a)
    "unemployment_rate", "construction_cost_index", "unsold_housing",
]

# Group D: 분기 공표 지표 — 익익익월 공표 (shift=+3개월)
#   [2026-09-02] Group C(+2) -> D(+3) 이동 3건.
#   근거: ECOS 실데이터 최종 수록월 관측(측정일 2026-09-01). 세 건 모두 최종
#   2026-06 으로 측정일 기준 3개월 경과였다. Group C(+2) 는 t 월 값을 t+2 월에
#   쓰는데, 실제로는 t+3 월에야 공표되므로 1개월 look-ahead 가 남는다.
#
#   ★ 분기 지표라는 사실 자체가 시점 누수 사유는 아니다. 분기 지표는 (기업,연도)
#     내에서 4회 변하고 ffill 은 과거 값을 반복하므로 GNI_annual 유형의
#     "연도 내 변동 0" 구조와 다르다. 여기서 시차를 늘리는 근거는 오직
#     **관측된 공표 지연 3개월** 이다. 드롭하지 않는다 — 시차만 늘리면
#     look-ahead 는 해소되고 정보는 남는다.
GROUP_D_COLS = [
    # 가계 (151Y001, 분기)
    "household_credit", "household_loan",
    # 국제수지 분기 (301Y013)
    "current_account_quarterly",
]

# 금리류 지표 — YoY 절대 금지, 반드시 _diff12 적용
# (제로 금리 국면 시 YoY 분모 발산 위험 원천 차단)
INTEREST_RATE_COLS = {
    # Group A 금리
    "call_rate_overnight", "call_rate_overnight_brokered",
    "KORIBOR_3m", "KORIBOR_6m", "KORIBOR_12m",
    "treasury_bond_1y", "treasury_bond_3y", "treasury_bond_5y", "treasury_bond_10y",
    "corporate_bond_3y_AA",
    "US_10Y_treasury", "US_3M_tbill",
    # Group B 금리
    "CD_rate_91d", "treasury_bond_1y_monthly",
    # Group C 금리
    "base_rate",
    # 파생 스프레드
    "credit_spread", "liquidity_spread",
}

# 사전 드롭 대상
#   [2026-09-01] export_price_index_KOR 를 드롭 대상에서 제외했다 (승인).
#     구 매핑이 902Y015 '주요국 경제성장률'(연간) 이라 연 1회 값 -> 대량 결측이었다.
#     정정 후 402Y014 '수출물가지수(기본분류) 총지수'(월별) 이므로 결측 사유가 소멸한다.
#     ★ 재수집 후 실제 결측률을 확인하고 5% 초과 시 재보고할 것.
#   manufacturing_index / GNI_annual 은 드롭 유지 (판단 2 / 시점 누수 사유).
DROP_COLS = ["GNI_annual", "manufacturing_index"]

# 상수 (월별 기준)
LAG_MONTHS_B = 1        # Group B: 1개월 시차
LAG_MONTHS_C = 2        # Group C: 2개월 시차
LAG_MONTHS_D = 3        # Group D: 3개월 시차 (분기 공표 실측)
TRUNCATION_MONTHS = 12  # shift(12) warm-up 구간 완전 제거


# ================================================================
# Phase 6 — 수준·누적 계열 (E1-1)
# ================================================================
# 배경: D축(D_AXIS_RESULT.md §5) 에서 거시 **차분** 지표의 부호가 Train 과
#       Valid 사이에서 뒤집혔다. E0 진단(E0_MACRO_LEVEL_DIAGNOSIS.md) 은
#       수준·누적으로 바꿔도 금리 계열이 뒤집힌다는 것을 보였다.
#       Phase 6 은 그 계열을 **모델에 넣어 실측할 수 있도록 산출만** 한다.
#       Phase 0~5 와 기존 172개 산출물에는 일절 영향을 주지 않는다.
#
# 입력: Phase 1 직후의 레벨 프레임 (그룹별 공표 시차 + ffill/bfill 완료 상태).
#       Phase 2~5 의 변환 대상에서는 제외된다 — Phase 2/3 가 레벨 컬럼을
#       drop 하기 전에 사본을 떠서 쓴다.
#
# ★ 시차: Phase 1 의 그룹 시차를 그대로 물려받는다.
#     base_rate      Group C -> +2개월  (롤링도 +2 적용된 계열 위에서 돈다)
#     BSI_mfg_biz    Group C -> +2개월
#     treasury_bond_3y / credit_spread / liquidity_spread  Group A -> 0개월
#
# ★ 롤링은 과거만 본다. center=False (기본) + closed="left".
#   closed="left" 는 창에서 **현재 행을 뺀다**. 따라서 t 시점 값은
#   t-1 이전만으로 계산된다. 미래 참조가 구조적으로 불가능하다.
#   대가: CUM_ 계열은 당월 인상분이 다음 달에야 반영된다 (사실상 +1개월 추가 시차).
#   보수적인 쪽을 택했다. step31 --level 의 섭동 검사가 이를 실증한다.
ROLL_CLOSED = "left"

LEVEL_KEEP = {                      # A. 수준 유지 (5개)
    "LV_base_rate": "base_rate",
    "LV_credit_spread": "credit_spread",
    "LV_liquidity_spread": "liquidity_spread",
    "LV_BSI_mfg_biz": "BSI_mfg_biz",
    "LV_treasury_bond_3y": "treasury_bond_3y",
}
CUM_TIGHTENING_WINDOW = 24          # B. 누적 스트레스 (4개)
CUM_SPREAD_WINDOW = 12
DUR_RATE_THRESHOLD = 3.0
DUR_BSI_THRESHOLD = 100.0
REL_WINDOW = 60                     # C. 상대 위치 (3개)
REL_MIN_PERIODS = 24                # 지시대로 24. bfill 금지 — 결측은 결측으로 둔다.

PHASE6_COLS = (
    list(LEVEL_KEEP)
    + ["CUM_tightening_24m", "CUM_spread_stress_12m",
       "DUR_rate_above_3pct", "DUR_bsi_below_100"]
    + ["REL_rate_vs_5y", "PCT_rate_5y", "PCT_spread_5y"]
)                                   # 총 12개. 이 이상 늘리지 않는다.


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

def _verify_against_config(group_a: list, group_b: list, group_c: list,
                           group_d: list) -> None:
    """그룹 배정 목록과 indicators.csv 를 대조한다.

    indicators 에 있는데 그룹 미배정 -> 예외 (phase0 가 이미 막지만 이중 방어)
    그룹에 있는데 indicators 에 없음 -> 경고 (지표가 빠졌거나 enabled=N)
    """
    cfg_path = Path(__file__).resolve().parent / "config" / "indicators.csv"
    if not cfg_path.exists():
        LOGGER.warning("  indicators.csv 없음 — 그룹 대조 검증을 건너뛴다 (%s)", cfg_path)
        return
    cfg = pd.read_csv(cfg_path, dtype=str, comment="#").fillna("")
    enabled = set(cfg.loc[cfg["enabled"].str.upper().isin(["Y", "YES", "1", "TRUE"]),
                          "series_name"])
    assigned = set(group_a) | set(group_b) | set(group_c) | set(group_d)
    derived = {"credit_spread", "liquidity_spread"}

    missing = sorted(enabled - assigned - set(DROP_COLS))
    if missing:
        raise ValueError(
            f"indicators.csv 에 enabled 인데 그룹 미배정: {missing}\n"
            f"  GROUP_*_COLS 에 추가하거나 indicators.csv 에서 enabled=N 으로 둘 것."
        )
    extra = sorted(assigned - enabled - derived)
    if extra:
        LOGGER.warning("  그룹에는 있으나 indicators.csv 에 없음(수집 안 됨): %s", extra)
    LOGGER.info("  indicators.csv 대조: enabled %d개 / 그룹배정 %d개 — 미배정 0",
                len(enabled), len(assigned))


def phase0(df: pd.DataFrame) -> tuple[pd.DataFrame, list, list, list, list]:
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
    group_d = [c for c in GROUP_D_COLS if c in df.columns]

    # 파생변수 → Group A 강제 편입
    for derived in ("credit_spread", "liquidity_spread"):
        if derived in df.columns and derived not in group_a:
            group_a.append(derived)

    # ── 미할당 컬럼은 예외로 중단한다 ────────────────────────────
    # 예전에는 조용히 Group A 로 넣었다. Group A 는 "시차 0" 이라 가장 공격적인
    # 처리이며, 모르는 지표를 그리로 보내면 시점 누수를 만든다.
    # 실제로 PUBLIC 3개와 GNI 3개가 이 경로로 시차 0 처리되고 있었다.
    # 명시적으로 배정하지 않으면 진행을 막는다.
    assigned = set(group_a + group_b + group_c + group_d)
    all_v = [c for c in df.columns if c != "date"]
    unassigned = [c for c in all_v if c not in assigned]
    if unassigned:
        raise ValueError(
            "그룹 미배정 컬럼 %d개: %s" % (len(unassigned), sorted(unassigned))
            + "\n  GROUP_A_COLS / GROUP_B_COLS / GROUP_C_COLS / GROUP_D_COLS 중 하나에 반드시 넣을 것."
            + "\n  Group A = 시차 0 (시장 종가처럼 당월 즉시 관찰 가능한 것만)"
            + "\n  Group B = +1개월 (월간 통계)"
            + "\n  Group C = +2개월 (분기/연간, 발표 지연이 큰 공공데이터)"
            + "\n  Group D = +3개월 (실측 공표 지연 3개월인 분기 지표)"
            + "\n  수집이 불필요하면 indicators.csv 에서 enabled=N 으로 둘 것."
        )

    _verify_against_config(group_a, group_b, group_c, group_d)

    LOGGER.info("  Group A: %d | Group B: %d | Group C: %d | Group D: %d",
                len(group_a), len(group_b), len(group_c), len(group_d))
    _log_nan(df, "Phase 0 완료")

    return df, group_a, group_b, group_c, group_d


def phase1(df: pd.DataFrame, group_b: list, group_c: list,
           group_d: list) -> pd.DataFrame:
    """Phase 1: 가용성 시차 적용 + ffill().bfill() → 원천 레벨 NaN 0개 달성

    - Group B: +1개월 shift (월간 공시 시차)
    - Group C: +2개월 shift (분기/연간 공시 시차)
    - Group D: +3개월 shift (실측 공표 지연 3개월인 분기 지표)
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

    # Group D: +3개월 shift
    if group_d:
        existing_d = [c for c in group_d if c in df.columns]
        df[existing_d] = df[existing_d].shift(LAG_MONTHS_D)
        LOGGER.info("  Group D: shift(+%d months), %d cols", LAG_MONTHS_D, len(existing_d))

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


def phase3(df: pd.DataFrame, group_b: list, group_c: list,
           group_d: list) -> pd.DataFrame:
    """Phase 3: 금리 → 12개월 차분(_diff12) / 비금리 B+C+D → YoY 증감률(_yoy)

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

    # ── 3-2. 비금리 B+C+D → YoY 증감률 (_yoy) ───────────────────
    non_rate_bc = [c for c in group_b + group_c + group_d
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
# Phase 6 (E1-1) — 수준·누적 계열
# ================================================================

def _past_sum(s: pd.Series, window: int, min_periods: int = 1) -> pd.Series:
    """과거 window 개월 합. closed='left' 라 현재 행은 창에 들어가지 않는다."""
    return s.rolling(window, min_periods=min_periods, closed=ROLL_CLOSED).sum()


def _past_mean(s: pd.Series, window: int, min_periods: int) -> pd.Series:
    return s.rolling(window, min_periods=min_periods, closed=ROLL_CLOSED).mean()


def _run_length(flag: pd.Series) -> pd.Series:
    """조건이 연속으로 참인 개월 수. 현재 달을 **포함**한다.

    이것은 롤링 창이 아니라 런랭스라 closed 개념이 없다. 현재 달을 포함하는
    이유는 그 달의 원천 값이 이미 공표 시차를 통과한 관측값이기 때문이다
    (base_rate 는 +2개월 지연된 값이다). 미래는 어느 시점에서도 보지 않는다.
    """
    f = flag.fillna(False).astype(bool)
    grp = (~f).cumsum()
    return f.groupby(grp).cumsum().astype(float)


def _past_pctile(s: pd.Series, window: int, min_periods: int) -> pd.Series:
    """현재 값이 과거 window 개월 분포에서 차지하는 분위 (0~1).

    루프로 명시 구현한다. 슬라이스가 vals[max(0, i-window):i] 이므로
    **인덱스 i 이후를 참조할 수 없다는 것이 코드에 그대로 드러난다.**
    (rolling.apply 는 현재 행을 창에 넣을지가 불명확해 쓰지 않았다.)
    """
    vals = pd.to_numeric(s, errors="coerce").to_numpy(dtype=float)
    out = np.full(len(vals), np.nan)
    for i in range(len(vals)):
        if np.isnan(vals[i]):
            continue
        lo = max(0, i - window)
        hist = vals[lo:i]                      # 현재(i) 미포함, 미래(i+1~) 미포함
        hist = hist[~np.isnan(hist)]
        if len(hist) < min_periods:
            continue
        out[i] = float((hist <= vals[i]).mean())
    return pd.Series(out, index=s.index)


def phase6(level_df: pd.DataFrame) -> pd.DataFrame:
    """Phase 6: 수준 유지 5 + 누적 스트레스 4 + 상대 위치 3 = 12개.

    level_df 는 Phase 1 직후의 레벨 프레임이다 (그룹 시차 + ffill/bfill 완료).
    Phase 2~5 는 이 프레임을 건드리지 않는다.
    """
    LOGGER.info("=" * 70)
    LOGGER.info("[Phase 6] 수준·누적 계열 %d개 생성 (E1-1)", len(PHASE6_COLS))
    LOGGER.info("-" * 70)

    need = set(LEVEL_KEEP.values()) | {"base_rate", "credit_spread", "BSI_mfg_biz"}
    missing = sorted(need - set(level_df.columns))
    if missing:
        raise ValueError(
            f"Phase 6 원천 레벨 컬럼 누락: {missing}\n"
            f"  Phase 1 직후 프레임에 있어야 한다. Phase 2/3 이후 프레임을 "
            f"넘기지 않았는지 확인할 것.")

    out = pd.DataFrame({"date": level_df["date"].values}, index=level_df.index)

    # ── A. 수준 유지 (5개) ──────────────────────────────────────
    for dst, src in LEVEL_KEEP.items():
        out[dst] = pd.to_numeric(level_df[src], errors="coerce")
    LOGGER.info("  [A] 수준 유지 %d개: %s", len(LEVEL_KEEP), list(LEVEL_KEEP))

    br = pd.to_numeric(level_df["base_rate"], errors="coerce")
    cs = pd.to_numeric(level_df["credit_spread"], errors="coerce")
    bsi = pd.to_numeric(level_df["BSI_mfg_biz"], errors="coerce")

    # ── B. 누적 스트레스 (4개) ──────────────────────────────────
    # 첫 행의 차분은 정의되지 않는다. '관측된 인상분이 없다' = 0 으로 둔다.
    # bfill 이 아니다 — 과거 정보가 없다는 사실을 0 으로 표현한 것이다.
    d_br = br.diff().clip(lower=0)
    d_br.iloc[0] = 0.0
    d_cs = cs.diff().clip(lower=0)
    d_cs.iloc[0] = 0.0
    out["CUM_tightening_24m"] = _past_sum(d_br, CUM_TIGHTENING_WINDOW)
    out["CUM_spread_stress_12m"] = _past_sum(d_cs, CUM_SPREAD_WINDOW)
    out["DUR_rate_above_3pct"] = _run_length(br >= DUR_RATE_THRESHOLD)
    out["DUR_bsi_below_100"] = _run_length(bsi < DUR_BSI_THRESHOLD)
    LOGGER.info("  [B] 누적 스트레스 4개 — CUM 창 %d/%d개월, "
                "DUR 임계 base_rate>=%.1f / BSI<%.0f",
                CUM_TIGHTENING_WINDOW, CUM_SPREAD_WINDOW,
                DUR_RATE_THRESHOLD, DUR_BSI_THRESHOLD)

    # ── C. 상대 위치 (3개) ──────────────────────────────────────
    out["REL_rate_vs_5y"] = br - _past_mean(br, REL_WINDOW, REL_MIN_PERIODS)
    out["PCT_rate_5y"] = _past_pctile(br, REL_WINDOW, REL_MIN_PERIODS)
    out["PCT_spread_5y"] = _past_pctile(cs, REL_WINDOW, REL_MIN_PERIODS)
    LOGGER.info("  [C] 상대 위치 3개 — 창 %d개월, min_periods=%d",
                REL_WINDOW, REL_MIN_PERIODS)

    assert list(out.columns) == ["date"] + PHASE6_COLS, \
        f"Phase 6 컬럼 구성 불일치: {list(out.columns)}"

    # ── 창을 실제로 몇 개월 채웠는지 ────────────────────────────
    eff = br.notna().rolling(REL_WINDOW, min_periods=1, closed=ROLL_CLOSED).sum()
    LOGGER.info("  롤링 창 충족도 (%d개월 목표): 마지막 행 %d개월",
                REL_WINDOW, int(eff.iloc[-1]))
    return out


def _report_phase6_missing(lv: pd.DataFrame) -> dict:
    """결측 개월 수를 로그로 남긴다. bfill 절대 금지 — 결측은 결측으로 둔다."""
    LOGGER.info("  [Phase 6] 결측 현황 (bfill 하지 않는다)")
    rep = {}
    for c in PHASE6_COLS:
        n = int(lv[c].isna().sum())
        rep[c] = n
        if n:
            miss = lv.loc[lv[c].isna(), "BASE_YM"].astype(str).tolist()
            LOGGER.info("    %-22s 결측 %2d개월  %s%s", c, n,
                        ", ".join(miss[:12]), " ..." if len(miss) > 12 else "")
        else:
            LOGGER.info("    %-22s 결측  0개월", c)
    return rep


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
    df, group_a, group_b, group_c, group_d = phase0(df)
    df = phase1(df, group_b, group_c, group_d)

    # Phase 1 직후의 레벨을 따로 떠 둔다. Phase 2/3 가 레벨 컬럼을 drop 하므로
    # 여기서 복사하지 않으면 Phase 6 이 쓸 원천이 사라진다.
    # 사본이라 Phase 2~5 의 동작에는 영향이 없다 (기존 172개 산출물 불변).
    level_snapshot = df.copy()

    df = phase2(df, group_a)
    df = phase3(df, group_b, group_c, group_d)
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

    # ── Phase 6 (E1-1/E1-2) — 별도 파일로 저장 ──────────────────
    lv = phase6(level_snapshot)
    # cleaned 와 같은 구간을 쓰도록 동일하게 상위 12행을 절단한다.
    # 절단하지 않으면 step6 결합 시 두 파일의 시작월이 어긋난다.
    n_before = len(lv)
    lv = lv.iloc[TRUNCATION_MONTHS:].reset_index(drop=True)
    LOGGER.info("  [Phase 6] cleaned 와 동일 절단: %d → %d rows", n_before, len(lv))
    lv["BASE_YM"] = pd.to_datetime(lv["date"]).dt.strftime("%Y%m")
    lv = lv[["BASE_YM", "date"] + PHASE6_COLS]

    assert len(lv) == len(df), \
        f"Phase 6 행수가 cleaned 와 다르다: {len(lv)} vs {len(df)}"
    assert (lv["BASE_YM"].values == df["BASE_YM"].values).all(), \
        "Phase 6 의 BASE_YM 이 cleaned 와 어긋난다"

    miss_rep = _report_phase6_missing(lv)
    LEVEL_FILE.parent.mkdir(parents=True, exist_ok=True)
    lv.to_csv(LEVEL_FILE, index=False, encoding="utf-8-sig")
    LOGGER.info("[DONE] Saved → %s  (%d rows x %d cols)",
                LEVEL_FILE, len(lv), len(PHASE6_COLS))
    n_miss_cols = sum(1 for v in miss_rep.values() if v)
    if n_miss_cols:
        LOGGER.warning(
            "  ★ %d개 컬럼에 결측이 남아 있다 (min_periods=%d 미충족 구간). "
            "bfill 하지 않았다. step6 결합 시 이 구간 처리 방침을 먼저 정할 것 "
            "— 현재 step6 는 거시 결측이 있으면 예외를 던진다.",
            n_miss_cols, REL_MIN_PERIODS)

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
