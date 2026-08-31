"""
======================================================================
JEMU sentinel 해독 & 재무비율 재계산
======================================================================
JEMU 재무데이터의 증가율/비율 컬럼에는 연속값이 아닌 sentinel 코드가 섞여 있다.
그대로 모델에 넣으면 10001 이 "증가율 10001%" 로 학습된다.

  10001 = 흑자 -> 적자 전환   (전기 + / 당기 -)
  10002 = 적자 지속           (전기 - / 당기 -)
  10003 = 적자 -> 흑자 전환   (전기 - / 당기 +)
  10000 = 산출불가 (분모 0)
  ±9999.99 = 상하한 캡 (실제값이 ±10000 을 넘음)

★ 10000 은 결측이 아니라 실체가 있다.
  - 이자보상배율(191207)=10000 → 이자비용 0 = 무차입 기업 (실측 부도배수 0.82배, 건전 신호)
  - 재고자산회전율(191505)=10000 → 재고자산 0 = 서비스/용역업 (업종 특성)
  -1 이나 결측으로 뭉개면 무차입 우량기업과 재무 미제출 기업이 같은 값이 된다.

★ 예외: 매출액증가율(191104)의 10001~10003 은 부호패턴이 맞지 않는다.
  매출액은 음수가 거의 없어 흑/적자 코드가 성립할 수 없다(실측 일치율 2~13%).
  소스 산출 오류로 보고 결측 처리한다. 단 191104 의 10000(전기매출=0)은 유효하다(98%).

★ 원본 비율 해독 현황 — 전수 그리드 서치(분자 17 x 분모 26 = 442조합) 결과.
  판정 기준은 '원본 - 재계산' 절대오차 < 0.01 비율이다.
  (Pearson 은 극단치에 무너져 판별력이 없다. 191210 은 Pearson 0.17 이지만 일치율 98.77% 다.)

  [재현 성공 4건] — 재계산본으로 대체 가능
    191204 매출액영업이익율 = 125000 / 121000        (기말)   98.96%
    191208 자기자본순이익율 = 129000 / 평균 118900             97.71%
    191210 총자본순이익율   = 129000 / 평균 115000             98.77%
    191506 총자본회전율     = 121000 / 평균 115000            100.00%
  => "총자본" 은 총자산(115000)을 뜻하고, 수익성·회전율은 평균잔액 기준이다.

  ★ [재현 불가 5건] — STAGE 6 에서 제거 후보로 올리지 말 것. 원본 의존이 불가피하다.
    191207 이자보상배율        최선 18.29%  이자비용 계정이 원천에 없음
                              (126000 은 영업외비용 총액이라 이자비용만 분리 불가)
    191310 EBITDA이자보상배율   최선  3.59%  동일 사유. 191207 과 10000 이 99.80% 동일 행
    191502 매출채권회전율       최선  0.35%  매출채권 계정이 원천에 없음
    191503 영업자산회전율       최선  2.04%  영업자산 계정이 원천에 없음
    191505 재고자산회전율       최선  2.11%  재고자산 계정이 원천에 없음
      ※ 191505 의 undef(=10000)은 35,291건(20.5%)으로 '재고자산 0 = 서비스/용역업'
        식별자 역할을 한다. is_inventory_free 와 함께 보존 가치가 크다.
  실측 예측력(191207_val, 부도기업비율 배수):
    < 0 (영업적자) 1.50 / 0~1 1.32 / 1~3 1.14 / >=3 0.71 / 무차입 0.82
  단조성이 뚜렷하므로 LEAK_SUSPECT 나 드롭 후보에 넣지 않는다.

배선 위치는 step2 의 _join_jemu 직전, 즉 jemu 프레임 단계다.
consec_loss_years / pl_turn_dir 이 연속 결산 시계열을 필요로 하는데, 패널 단계에서는
as-of 조인으로 같은 결산이 여러 달에 반복 등장해 계산이 왜곡되기 때문이다.

사용법:
    from eda_pipeline.jemu_sentinel import decode_jemu
    jemu = decode_jemu(jemu, train_mask=mask)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

# ── sentinel 코드 ───────────────────────────────────────────────────
TURN_NEG = 10001   # 흑자 -> 적자
CONT_NEG = 10002   # 적자 지속
TURN_POS = 10003   # 적자 -> 흑자
UNDEF = 10000      # 분모 0 -> 산출불가
CAP_ABS = 9999.99  # 상하한 캡
VAL_LIMIT = 9999   # 연속값으로 인정하는 절대값 상한

# ── 대상 컬럼 ───────────────────────────────────────────────────────
GROWTH_COLS: Sequence[str] = ("191104", "191105", "191108", "191110")
RATIO_COLS: Sequence[str] = ("191204", "191207", "191208", "191210", "191310",
                             "191502", "191503", "191505", "191506")
RAW_SENTINEL_COLS: Sequence[str] = tuple(GROWTH_COLS) + tuple(RATIO_COLS)

# 흑/적자 전환 코드가 성립하지 않는 컬럼. 해당 코드는 결측 처리한다.
NO_TURN_CODE_COLS = frozenset({"191104"})

# 원본 sentinel 컬럼 유지 여부. False 면 _val 로 대체하고 원본을 드롭한다.
# 같은 정보를 두 형태로 두면 sentinel 이 섞인 원본이 그대로 학습에 들어갈 위험이 있다.
# STAGE 6 의 S6 시나리오("디코딩 전 vs 후")에서만 True 로 둔다.
KEEP_RAW_SENTINEL_COLS = False

# 결산기 간격 상한. YYYYMM 차분 기준으로 적는다 (100 = 1년, 200 = 2년).
#
# CONSEC_MAX_GAP : 연속 적자를 세는 간격 상한. 100(1년)을 쓴다.
#   실측상 100 과 200 의 부도배수 차이가 없고(1년 1.52/1.46/1.26 vs 2년 1.51/1.47/1.25),
#   "연속 적자 N년"이라는 변수 의미를 지키려면 매년 연속이어야 하므로 100 으로 둔다.
#
# PL_TURN_MAX_GAP : 손익 전환을 인정하는 간격 상한. 200(2년)을 쓴다.
#   실측 흑->적 전환 부도배수: 1년 1.52 / 2년 1.85 / 3년 이상 0.00.
#   3년 이상 건너뛴 결산과 비교한 "전환"은 그 사이 변동을 놓쳐 신호가 없다.
CONSEC_MAX_GAP = 100
PL_TURN_MAX_GAP = 200

# 재계산 비율의 상한. 원본 비율이 ±9999.99(%) 로 캡되어 있으므로 동일하게 맞춘다.
# 재계산본은 분수(0.0413 = 4.13%)이므로 내부적으로 100 으로 나눠 적용한다.
RATIO_CLIP = 9999.99


def _gap_to_months(yyyymm_gap: int) -> int:
    """YYYYMM 차분(100=1년)을 개월 수로 변환한다."""
    return (yyyymm_gap // 100) * 12 + (yyyymm_gap % 100)

# ── 원계정 ──────────────────────────────────────────────────────────
CUR_ASSET = "112000"   # 유동자산(계)
TOT_ASSET = "115000"   # 자산총계
CUR_LIAB = "116000"    # 유동부채(계)
TOT_LIAB = "118000"    # 부채총계
TOT_EQUITY = "118900"  # 자본총계
SALES = "121000"       # 매출액
OP_INCOME = "125000"   # 영업이익(손실)
NET_INCOME = "129000"  # 당기순이익(손실)


def _num(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series(np.nan, index=df.index, dtype="float64")
    return pd.to_numeric(df[col], errors="coerce")


def _safe_div(num: pd.Series, den: pd.Series,
              invalid: pd.Series | None = None) -> pd.Series:
    """0 나눗셈과 inf 를 NaN 으로. invalid 가 True 인 곳도 NaN."""
    d = den.where((den != 0) & den.notna())
    out = (num / d).replace([np.inf, -np.inf], np.nan)
    if invalid is not None:
        out = out.mask(invalid.fillna(False))
    return out


def _ym_idx(s: pd.Series) -> pd.Series:
    s = s.astype(str).str.strip().str.zfill(6)
    return s.str[:4].astype("int64") * 12 + s.str[4:6].astype("int64")


# ====================================================================
# 4-1 증가율 컬럼 분해
# ====================================================================

def decode_growth(df: pd.DataFrame,
                  cols: Iterable[str] = GROWTH_COLS,
                  prefix: str = "") -> pd.DataFrame:
    """증가율 컬럼을 연속값 + sentinel 플래그 6종으로 분해한다.

        <c>_val       연속값 (|x| < 9999 인 것만, 나머지 NaN)
        <c>_turn_neg  10001  흑자 -> 적자
        <c>_cont_neg  10002  적자 지속
        <c>_turn_pos  10003  적자 -> 흑자
        <c>_undef     10000  산출불가
        <c>_capped    |x| == 9999.99  상하한 캡

    NO_TURN_CODE_COLS(191104)의 전환 코드는 _val 과 전환 플래그 3종을 모두 NaN 으로
    둔다. 값이 틀렸다는 사실만 남기고 0(전환 없음)으로 단정하지 않는다.
    """
    out = df.copy()
    for c in cols:
        src = f"{prefix}{c}"
        if src not in out.columns:
            log.warning("decode_growth: %s 없음 — 건너뜀", src)
            continue
        v = _num(out, src)

        out[f"{src}_val"] = v.where(v.abs() < VAL_LIMIT)
        out[f"{src}_undef"] = (v == UNDEF).astype("float64")
        out[f"{src}_capped"] = (v.abs() == CAP_ABS).astype("float64")

        bogus = (v.isin([TURN_NEG, CONT_NEG, TURN_POS])
                 if c in NO_TURN_CODE_COLS else pd.Series(False, index=out.index))
        for name, code in (("turn_neg", TURN_NEG), ("cont_neg", CONT_NEG),
                           ("turn_pos", TURN_POS)):
            out[f"{src}_{name}"] = (v == code).astype("float64").mask(bogus)
        if c in NO_TURN_CODE_COLS and int(bogus.sum()):
            log.info("    %s: 성립하지 않는 전환코드 %d건 -> 결측 처리",
                     src, int(bogus.sum()))
    return out


# ====================================================================
# 4-2 비율 컬럼 분해
# ====================================================================

def decode_ratio(df: pd.DataFrame,
                 cols: Iterable[str] = RATIO_COLS,
                 prefix: str = "") -> pd.DataFrame:
    """비율 컬럼을 연속값 + undef/capped 로 분해한다."""
    out = df.copy()
    for c in cols:
        src = f"{prefix}{c}"
        if src not in out.columns:
            log.warning("decode_ratio: %s 없음 — 건너뜀", src)
            continue
        v = _num(out, src)
        out[f"{src}_val"] = v.where(v.abs() < VAL_LIMIT)
        out[f"{src}_undef"] = (v == UNDEF).astype("float64")
        out[f"{src}_capped"] = (v.abs() == CAP_ABS).astype("float64")
    return out


# ====================================================================
# 4-3 구조 플래그 (10000 의 실체 보존)
# ====================================================================

def add_structure_flags(df: pd.DataFrame, prefix: str = "") -> pd.DataFrame:
    """10000 이 뜻하는 기업 구조를 명시적 플래그로 남긴다.

        is_debt_free      191207 == 10000  이자비용 0 -> 무차입
        is_inventory_free 191505 == 10000  재고자산 0 -> 서비스/용역업
        is_no_prev_sales  191104 == 10000  전기 매출 0 -> 휴면 / 신설
    """
    out = df.copy()
    for flag, src in ((f"{prefix}is_debt_free", f"{prefix}191207"),
                      (f"{prefix}is_inventory_free", f"{prefix}191505"),
                      (f"{prefix}is_no_prev_sales", f"{prefix}191104")):
        if src not in out.columns:
            log.warning("add_structure_flags: %s 없음 — %s 생략", src, flag)
            continue
        out[flag] = (_num(out, src) == UNDEF).astype("float64")
    return out


# ====================================================================
# 4-4 원계정 직접 재계산 (sentinel 없는 클린 버전)
# ====================================================================

def _prev_balance(df: pd.DataFrame, col: str, group_col: str,
                  order_col: str, max_gap_months: int) -> pd.Series:
    """직전 결산의 잔액. 결산 간격이 상한을 넘으면 NaN (3년 전 잔액과 평균내지 않는다)."""
    order = df.sort_values([group_col, order_col], kind="mergesort").index
    s = _num(df, col).loc[order]
    g = df.loc[order, group_col]
    idx = _ym_idx(df.loc[order, order_col])
    gap = (idx - idx.shift(1)).where(g == g.shift(1))
    prev = s.groupby(g, sort=False).shift(1)
    prev = prev.where((gap > 0) & (gap <= max_gap_months))
    return prev.reindex(df.index)


def compute_clean_ratios(df: pd.DataFrame, prefix: str = "",
                         group_col: str = "V_BZNO",
                         order_col: str = "FNA_CLS_YM") -> pd.DataFrame:
    """원계정에서 재무비율을 직접 계산한다. sentinel 이 섞이지 않는다.

        debt_ratio        부채총계 / 자본총계     (자본잠식이면 NaN)
        debt_dependency   부채총계 / 자산총계
        op_margin         영업이익 / 매출액       (매출 0 이면 NaN)
        roa_end           당기순이익 / 기말 자산총계
        roa_avg           당기순이익 / 평균 자산총계
        asset_turnover_end  매출액 / 기말 자산총계
        asset_turnover_avg  매출액 / 평균 자산총계
                            191506(총자본회전율)이 이 산식으로 100.00% 해독되었다.
        roe_end           당기순이익 / 기말 자본총계   (자본잠식이면 NaN)
        roe_avg           당기순이익 / 평균 자본총계
        current_ratio     유동자산 / 유동부채

    기말/평균 두 버전을 모두 만드는 이유:
      원본 비율의 산식을 절대오차로 검정한 결과, 제공자는 평균잔액 기준을 쓴다.
        191208 자기자본순이익율 = 129000 / 평균자본총계  (오차<0.01 비율 97.71%)
        191210 총자본순이익율   = 129000 / 평균자산총계  (오차<0.01 비율 98.77%)
      그러나 평균 기준만 쓰면 첫 결산(전기 없음) 행이 통째로 NaN 이 된다.
      이 행들은 신설·신규편입 기업으로 부도기업비율이 3.71% (전체 2.63% 대비 1.41배)인
      고위험군이므로 버릴 수 없다. 따라서 두 버전을 병행하고 STAGE 6에서 비교한다.

    분모 이상 / 커버리지는 플래그로 남긴다.
        capital_impaired  자본총계 <= 0 (실측 2.55%, 부도배수 2.55배)
        no_sales          매출액 == 0   (실측 1.31%)
        capital_impaired_avg  평균자본총계 <= 0 (roe_avg 의 분모 이상)
        roe_first_fy_YN   전기 결산이 없어 평균 기준 계산 불가.
                          = 신설 / 신규편입 기업. 커버리지 보정용이 아니라
                          독립 신호다 (부도기업비율 3.71% vs 전체 2.63%, 1.41배).
    """
    out = df.copy()
    p = prefix
    max_gap = _gap_to_months(PL_TURN_MAX_GAP)
    eq = _num(out, f"{p}{TOT_EQUITY}")
    asset = _num(out, f"{p}{TOT_ASSET}")
    sales = _num(out, f"{p}{SALES}")
    ni = _num(out, f"{p}{NET_INCOME}")

    impaired = eq <= 0
    no_sales = sales == 0
    out[f"{p}capital_impaired"] = impaired.astype("float64")
    out[f"{p}no_sales"] = no_sales.astype("float64")

    if group_col in out.columns and order_col in out.columns:
        prev_eq = _prev_balance(out, f"{p}{TOT_EQUITY}", group_col, order_col, max_gap)
        prev_as = _prev_balance(out, f"{p}{TOT_ASSET}", group_col, order_col, max_gap)
    else:
        log.warning("compute_clean_ratios: %s / %s 없음 — 평균잔액 계산 생략",
                    group_col, order_col)
        prev_eq = pd.Series(np.nan, index=out.index)
        prev_as = pd.Series(np.nan, index=out.index)

    avg_eq = (eq + prev_eq) / 2
    avg_as = (asset + prev_as) / 2
    # 평균자본이 0 이하면 ROE 부호가 뒤집혀 "부채비율이 낮은 우량기업"으로 오해된다.
    # 기말 기준(impaired)과 별개로 평균 기준 분모도 따로 막는다.
    impaired_avg = avg_eq <= 0
    out[f"{p}capital_impaired_avg"] = impaired_avg.astype("float64").mask(avg_eq.isna())
    out[f"{p}roe_first_fy_YN"] = prev_eq.isna().astype("float64")

    out[f"{p}debt_ratio"] = _safe_div(_num(out, f"{p}{TOT_LIAB}"), eq, impaired)
    out[f"{p}debt_dependency"] = _safe_div(_num(out, f"{p}{TOT_LIAB}"), asset)
    out[f"{p}op_margin"] = _safe_div(_num(out, f"{p}{OP_INCOME}"), sales, no_sales)
    out[f"{p}roa_end"] = _safe_div(ni, asset)
    out[f"{p}roa_avg"] = _safe_div(ni, avg_as, avg_as <= 0)
    out[f"{p}roe_end"] = _safe_div(ni, eq, impaired)
    out[f"{p}roe_avg"] = _safe_div(ni, avg_eq, impaired_avg)
    out[f"{p}current_ratio"] = _safe_div(_num(out, f"{p}{CUR_ASSET}"),
                                         _num(out, f"{p}{CUR_LIAB}"))
    # 191506 총자본회전율이 121000 / 평균115000 으로 100.00% 해독되었다.
    out[f"{p}asset_turnover_end"] = _safe_div(sales, asset)
    out[f"{p}asset_turnover_avg"] = _safe_div(sales, avg_as, avg_as <= 0)

    ratios = ["debt_ratio", "debt_dependency", "op_margin",
              "roa_end", "roa_avg", "roe_end", "roe_avg", "current_ratio",
              "asset_turnover_end", "asset_turnover_avg"]
    _clip_ratios(out, [f"{p}{c}" for c in ratios])
    return out


def _clip_ratios(df: pd.DataFrame, cols: Sequence[str]) -> None:
    """재계산 비율을 원본과 같은 ±RATIO_CLIP(%) 상한으로 자른다.

    재계산본은 분수이므로 RATIO_CLIP/100 을 상한으로 쓴다.
    자른 행은 <col>_capped 로 표시하고, 자르기 전 분포를 로그로 남긴다.
    극단치가 특정 기업군에 몰려 있으면 그 자체가 데이터 품질 신호다.
    """
    lim = RATIO_CLIP / 100.0
    for c in cols:
        if c not in df.columns:
            continue
        v = df[c]
        over = v.abs() > lim
        n = int(over.sum())
        df[f"{c}_capped"] = over.astype("float64").mask(v.isna())
        if n:
            log.info(f"    {c}: 클리핑 {n}건 ({over.mean()*100:.3f}%)  자르기 전 "
                     f"min {v.min():,.1f} / p1 {v.quantile(.01):,.2f} / "
                     f"중앙 {v.median():,.4f} / p99 {v.quantile(.99):,.2f} / "
                     f"max {v.max():,.1f}")
        df[c] = v.clip(-lim, lim)


# ====================================================================
# 4-5 상위 파생 2종
# ====================================================================

def add_derived_signals(df: pd.DataFrame,
                        group_col: str = "V_BZNO",
                        order_col: str = "FNA_CLS_YM",
                        prefix: str = "") -> pd.DataFrame:
    """결산 시계열 기반 파생.

        consec_loss_years   당기순이익 < 0 인 연속 결산 횟수 (당기 포함)
                            결산기 간격이 CONSEC_MAX_GAP(1년)을 넘으면
                            연속으로 세지 않고 1 부터 다시 센다.
        pl_turn_dir         -1 흑자->적자 / 0 유지 / +1 적자->흑자
                            직전 결산과의 간격이 PL_TURN_MAX_GAP(2년)을 넘으면
                            NaN. 3년 이상 건너뛴 전환은 실측 부도배수가 0.00 으로
                            신호가 없다 (그 사이의 변동을 놓치기 때문).
        pl_turn_gap_months  전환 판정에 쓴 직전 결산과의 실제 간격(개월).
                            제약을 벗어난 경우에도 값을 남긴다.

    op_ni_sign_mismatch(영업+/순이익-)는 만들지 않는다. 실측 부도배수가 1.00 으로
    신호가 없고, 진짜 신호인 '동시 적자'는 191105_cont_neg / 191108_cont_neg 가
    이미 담고 있다.
    """
    out = df.copy()
    p = prefix
    ni = _num(out, f"{p}{NET_INCOME}")

    if group_col not in out.columns or order_col not in out.columns:
        log.warning("add_derived_signals: %s / %s 없음 — 시계열 파생 생략",
                    group_col, order_col)
        out[f"{p}consec_loss_years"] = np.nan
        out[f"{p}pl_turn_dir"] = np.nan
        return out

    order = out.sort_values([group_col, order_col], kind="mergesort").index
    ni_s = ni.loc[order]
    g = out.loc[order, group_col]
    idx = _ym_idx(out.loc[order, order_col])

    same_firm = g == g.shift(1)
    gap_m = (idx - idx.shift(1)).where(same_firm)
    consec_lim = _gap_to_months(CONSEC_MAX_GAP)
    turn_lim = _gap_to_months(PL_TURN_MAX_GAP)

    adjacent = same_firm & (gap_m > 0) & (gap_m <= consec_lim)
    loss = ni_s < 0

    # 흑자(또는 결측)이거나, 직전 결산과의 간격이 상한을 넘으면 연속이 끊긴다.
    reset = (~loss) | (~adjacent)
    consec = loss.groupby(reset.cumsum()).cumsum().where(loss, 0.0)
    consec = consec.mask(ni_s.isna())

    prev_ni = ni_s.groupby(g, sort=False).shift(1)
    turn = pd.Series(0.0, index=order)
    turn = turn.mask((prev_ni > 0) & (ni_s < 0), -1.0)
    turn = turn.mask((prev_ni < 0) & (ni_s > 0), 1.0)
    turn = turn.mask(prev_ni.isna() | ni_s.isna())
    # 간격이 상한을 넘으면 전환 판정 자체를 하지 않는다.
    turn = turn.mask(gap_m.isna() | (gap_m > turn_lim))

    out[f"{p}consec_loss_years"] = consec.reindex(out.index).astype("float64")
    out[f"{p}pl_turn_dir"] = turn.reindex(out.index).astype("float64")
    out[f"{p}pl_turn_gap_months"] = gap_m.reindex(out.index).astype("float64")

    n_reset = int((same_firm & ~adjacent).sum())
    n_turn_drop = int((same_firm & (gap_m > turn_lim)).sum())
    log.info("    결산 간격 상한: consec %d개월 / turn %d개월", consec_lim, turn_lim)
    log.info("      연속 카운트 리셋 페어 %d건 / 전환 판정 제외 페어 %d건",
             n_reset, n_turn_drop)
    return out


# ====================================================================
# 상수 컬럼 제거 (Train 구간 기준)
# ====================================================================

STATIC_REASONS = {
    "191110_turn_neg": "재고자산증가율에 전환코드 자체가 없음",
    "191110_cont_neg": "재고자산증가율에 전환코드 자체가 없음",
    "191110_turn_pos": "재고자산증가율에 전환코드 자체가 없음",
    "191506_undef": "총자본회전율에 sentinel 없음",
    "191506_capped": "총자본회전율에 sentinel 없음",
    "191104_turn_neg": "매출액증가율의 전환코드는 설계상 무효(부호패턴 불일치)",
    "191104_cont_neg": "매출액증가율의 전환코드는 설계상 무효(부호패턴 불일치)",
    "191104_turn_pos": "매출액증가율의 전환코드는 설계상 무효(부호패턴 불일치)",
}


def drop_constant_columns(df: pd.DataFrame,
                          candidates: Sequence[str],
                          train_mask: pd.Series | None = None,
                          save_path: str | Path | None = None,
                          prefix: str = "") -> pd.DataFrame:
    """Train 구간에서 상수인 컬럼을 제거한다.

    상수 판정을 전체 데이터로 하면 Valid 구간 정보를 보는 것이 되므로
    반드시 Train 구간에서만 판정하고, 그 목록을 JSON 으로 저장해 Valid 에 동일 적용한다.
    조용히 지우지 않고 제거된 컬럼명과 사유를 로그로 남긴다.
    """
    if train_mask is None:
        log.warning("drop_constant_columns: train_mask 가 없어 전체 데이터로 판정합니다. "
                    "Valid 정보가 새어들 수 있습니다.")
        scope = df
    else:
        scope = df.loc[train_mask.fillna(False)]
        log.info("    상수 판정 범위: Train %d행 / 전체 %d행", len(scope), len(df))

    dropped = {}
    for c in candidates:
        if c not in df.columns:
            continue
        s = scope[c]
        if s.notna().sum() == 0:
            dropped[c] = "Train 구간에서 전부 결측"
        elif s.nunique(dropna=True) <= 1:
            val = s.dropna().iloc[0] if s.notna().any() else None
            base = STATIC_REASONS.get(c.replace(prefix, "", 1),
                                      f"Train 구간에서 상수 (값 {val})")
            dropped[c] = base

    if dropped:
        log.info("    상수 컬럼 %d개 제거:", len(dropped))
        for c, why in dropped.items():
            log.info("       - %-24s %s", c, why)
        df = df.drop(columns=list(dropped))
    else:
        log.info("    상수 컬럼 없음")

    if save_path is not None:
        Path(save_path).write_text(
            json.dumps({"dropped": dropped,
                        "n_train_rows": int(len(scope)),
                        "n_candidates": len(list(candidates))},
                       ensure_ascii=False, indent=2),
            encoding="utf-8")
        log.info("    상수 컬럼 목록 저장: %s", Path(save_path).name)
    return df


# ====================================================================
# 오케스트레이터
# ====================================================================

def decode_jemu(df: pd.DataFrame,
                prefix: str = "",
                group_col: str = "V_BZNO",
                order_col: str = "FNA_CLS_YM",
                train_mask: pd.Series | None = None,
                drop_constant: bool = True,
                keep_raw: bool | None = None,
                constant_cols_path: str | Path | None = None) -> pd.DataFrame:
    """4-1 ~ 4-5 를 한 번에 적용한다. 입력 행수를 바꾸지 않는다."""
    n = len(df)
    before = set(df.columns)

    out = decode_growth(df, prefix=prefix)
    out = decode_ratio(out, prefix=prefix)
    out = add_structure_flags(out, prefix=prefix)
    out = compute_clean_ratios(out, prefix=prefix,
                               group_col=group_col, order_col=order_col)
    out = add_derived_signals(out, group_col=group_col,
                              order_col=order_col, prefix=prefix)

    new_cols = [c for c in out.columns if c not in before]
    if drop_constant:
        out = drop_constant_columns(out, new_cols, train_mask=train_mask,
                                    save_path=constant_cols_path, prefix=prefix)

    keep = KEEP_RAW_SENTINEL_COLS if keep_raw is None else keep_raw
    if not keep:
        raw = [f"{prefix}{c}" for c in RAW_SENTINEL_COLS if f"{prefix}{c}" in out.columns]
        out = out.drop(columns=raw)
        log.info("    원본 sentinel 컬럼 %d개 드롭 (_val 로 대체). "
                 "KEEP_RAW_SENTINEL_COLS=True 로 두면 유지된다.", len(raw))

    assert len(out) == n, f"decode_jemu 에서 행수 변동: {n} -> {len(out)}"
    log.info("  decode_jemu: %d행 유지, 컬럼 %d -> %d (%+d)",
             n, len(df.columns), len(out.columns), len(out.columns) - len(df.columns))
    return out
