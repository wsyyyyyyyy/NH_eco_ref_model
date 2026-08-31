"""
======================================================================
Step 6 — 거시경제 지표 결합 & 기업별 노출도/상호작용 생성
======================================================================
문제: 기존 조인은 BASE_YM 하나로만 이루어져 같은 달의 모든 기업이 동일한 거시 값을
      갖는다. 트리 모델에서 이것은 사실상 '시점 더미'이며 기업 간 변별에 기여할 수 없다.
      실측(lgbm_12m_model.txt gain 파싱): 기업 고유 58개 94.81% vs 거시 172개 5.19%,
      거시 172개 중 85개(49.4%)는 단 한 번도 분기에 쓰이지 않았다.

해법: 거시 충격이 기업마다 다르게 작용하는 경로를 노출도(exposure)로 명시하고,
      거시지표 x 노출도 상호작용항을 만든다. 이러면 같은 달 안에서도 기업별로
      값이 달라져 시점 더미로 퇴화하지 않는다.

실행:
    python eda_pipeline/step6_macro_integration.py
    python eda_pipeline/step6_macro_integration.py --ma3m keep_base --segment none
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from eda_pipeline import config

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
log = logging.getLogger(__name__)

# ── 상수 ────────────────────────────────────────────────────────────
# 거시 시차. step6 에서 "추가로" 거는 개월 수다.
#
# 0 인 이유 — 공표 시차는 이미 상류(api_data_processing/impute_data.py Phase 1)에서
# 지표군별로 걸려 있다.
#     Group A (시장 종가·환율·원자재·일별 금리) shift 0  — 당월 말 관찰 가능
#     Group B (물가·통화량·무역 등 월간 통계)   shift +1 — 익월 공표
#     Group C (정책금리·BSI/CSI·분기 공공데이터) shift +2 — 발표 지연 큼
# 여기서 전 컬럼에 일괄 shift(1) 을 더 걸면 A=1 / B=2 / C=3 이 되어
# 의도한 공표 시차보다 한 달씩 낡은 값을 보게 된다. 이중 시차다.
#
# 또한 구 구현은 shift 뒤 `.bfill()` 을 불러 첫 행(202101)이 자기 자신의
# 미시차 값으로 되메워졌다. 시차를 걸고 다시 푸는 셈이라 첫 달에 한해
# 미래 참조가 남았다. 시차를 걸지 않으므로 이 bfill 도 함께 없앴다.
#
# 1 이상으로 두면 구 동작(전 컬럼 추가 시차)을 그대로 재현한다. D축 G1-7 참조.
MACRO_LAG_MONTHS = 0

# _ma3m 중복 정리 모드. 대부분의 거시변수가 원본과 3개월 이동평균을 함께 갖고 있어
# 상관이 매우 높다 (step28-⑦에서 VIF 무한대 3개 식별).
MA3M_MODES = ("keep_both", "keep_base", "keep_ma3m")

# 노출도 윈저라이징 (하한, 상한) 분위. None 이면 적용하지 않는다.
# 노출도는 '비중' 이므로 대부분 0~1 범위여야 하는데 exp_liq max 310,011 처럼
# 5자릿수가 나오는 것은 분모가 극단적으로 작은 케이스다.
# 트리 모델 단독으로는 단조변환에 불변이지만, 상호작용항은 곱셈이라 그대로 증폭된다
# (liq_spread_x_shortdebt |max| 543,794).
# 경계는 반드시 Train 구간에서만 산출해 Valid 에 그대로 적용한다.
EXPOSURE_CLIP_Q: tuple[float, float] | None = (0.01, 0.99)

# 업종 분류 단위. 'hier' = 중분류 우선 + 대분류 폴백 (권장),
# 'mid2' = 중분류만, 'section' = 대분류만.
#   중분류만 쓰면 변별력은 좋지만 추정 불가가 25.62%,
#   대분류만 쓰면 추정 불가는 11.53% 로 줄지만 제조업 전체가 한 값이 된다.
#   계층적 방식은 표본이 충분한 20개 중분류는 중분류 평균을, 나머지는 대분류 평균을 쓴다.
INDUSTRY_LEVEL = "hier"
INDUSTRY_RATIO_FILE = "industry_export_ratio_v2.json"

# 범주형으로 다룰 문자열 피처. pandas category dtype 으로 지정하고
# 카테고리 순서를 Train 기준으로 고정한다.
# 정수 매핑(0/1/2)은 순서가 있는 것처럼 학습될 수 있어 쓰지 않는다.
# LightGBM 은 category dtype 을 명목형으로 보고 최적 분할을 찾는다.
# 값 목록을 None 으로 두면 Train 구간에서 관측된 값을 정렬해 자동으로 고정한다.
CATEGORICAL_COLS = {
    "exp_fx_industry_level": ["mid2", "section", "none"],
    "exp_fx_source": ["actual", "industry", "unknown"],
    "OBV_ELYWRN_OBV_GRD_DSC": None,
    "JEMU_AUD_OPI_DSC": None,
    "STD_INDS_SECTION": None,
    "STD_INDS_MID2": None,
}
# STD_INDS_CFC 원본(고유값 1,147)은 category 로 만들지 않는다.
# 표본이 한 자릿수인 업종이 다수라 트리가 개별 업종을 외우고,
# Train 에만 있는 업종은 Valid 에서 미지 카테고리가 되어 불안정하다.
# 대신 대분류 / 중분류 파생을 쓰고 원본은 NON_FEATURE 로 남긴다.
CATEGORY_MAX_LEVELS = 50   # 이보다 많으면 경고하고 피처에서 빼도록 표시한다

# Valid 에만 있는(=Train 에 없는) 카테고리 레벨 허용 상한. 넘으면 예외를 던진다.
# Train 기준으로 레벨을 고정하므로 미지 레벨은 NaN 이 되는데, 그 비율이 커지면
# 조용히 정보를 버리게 된다. '__OTHER__' 레벨은 만들지 않는다 —
# Train 에 학습 사례가 없어 실익이 불분명하기 때문이다.
UNSEEN_LEVEL_MAX_RATIO = 0.001   # 0.1%

# 업종 피처 조합. STAGE 6 의 S9a / S9b / S9c 비교용.
#   'section' = 대분류만 / 'mid2' = 중분류만 / 'both' = 둘 다
# 중분류가 대분류를 결정하므로 정보가 포함관계다. 둘 다 넣으면 트리가 같은 분할을
# 두 번 학습할 수 있어 STAGE 6 에서 실측으로 고른다.
INDUSTRY_FEATURE_MODE = "both"
CATEGORY_MAP_FILE = "categorical_levels_v2.json"

# 거시 변수 축소. True 면 기존 모델에서 gain>0 인 87개만 유지한다.
# ※ 판정 기준이 된 lgbm_12m_model.txt 는 누수 포함 모델이므로 이 축소는 잠정이다.
#   STAGE 6 에서 축소 전(172) / 후(87) 두 버전을 비교한다.
MACRO_REDUCE = True
MACRO_DROPPED_FILE = "macro_dropped_v2.json"
REFERENCE_MODEL = "lgbm_12m_model.txt"

# 수출 노출도 모드. 하이브리드가 실측을 완전히 포함하므로 동시 투입은 VIF 문제를 만든다.
# 두 컬럼은 모두 생성해 두되 학습에는 하나만 쓴다 (STAGE 6 의 S7a / S7b).
MACRO_FX_MODE = "actual"   # actual | hybrid

# 제조업 KSIC-10 대분류 2자리 코드 범위
MANUFACTURING_DIV = range(10, 34)

# 업종별 수출집약도 추정 시 필요한 최소 기업 수. 미만이면 전체 평균으로 대체한다.
INDUSTRY_MIN_FIRMS = 30


# KSIC-10 대분류 구간 (중분류 2자리 -> 대분류 문자)
KSIC_SECTIONS = [(1, 3, "A"), (5, 8, "B"), (10, 34, "C"), (35, 35, "D"), (36, 39, "E"),
                 (41, 42, "F"), (45, 47, "G"), (49, 52, "H"), (55, 56, "I"), (58, 63, "J"),
                 (64, 66, "K"), (68, 68, "L"), (70, 73, "M"), (74, 76, "N"), (84, 84, "O"),
                 (85, 85, "P"), (86, 87, "Q"), (90, 91, "R"), (94, 96, "S"), (97, 98, "T"),
                 (99, 99, "U")]


def industry_code(s: pd.Series, level: str = "mid2") -> pd.Series:
    """STD_INDS_CFC 에서 업종 코드를 뽑는다.

    주의: STD_INDS_CFC 는 자릿수가 균일하지 않다 (5자리 904,381 / 4자리 43,020 /
    2자리 779 / 1자리 34, 그리고 step5 의 결측 대체값 '-1').
    4자리는 앞의 0 이 잘린 5자리이므로 zfill(5) 후 앞 2자리를 취해야 한다.
    (정수 나눗셈 //1000 을 쓰면 4자리에서 앞 1자리만 남아 4.3만행이 오분류된다.)
    4~5자리가 아닌 값은 유효 업종코드로 보지 않고 NaN 으로 둔다.
    """
    x = s.astype(str).str.replace(r"\.0$", "", regex=True).str.strip()
    x = x.where(x.str.fullmatch(r"\d{4,5}"))
    mid = x.str.zfill(5).str[:2]
    if level == "mid2":
        return mid
    n = pd.to_numeric(mid, errors="coerce")
    out = pd.Series(pd.NA, index=s.index, dtype="object")
    for lo, hi, name in KSIC_SECTIONS:
        out[(n >= lo) & (n <= hi)] = name
    return out


def _div(num: pd.Series, den: pd.Series) -> pd.Series:
    """0 나눗셈과 inf 를 NaN 으로."""
    d = den.where((den != 0) & den.notna())
    return (num / d).replace([np.inf, -np.inf], np.nan)


# ====================================================================
# 5-1 기업별 거시 노출도
# ====================================================================

def build_exposures(df: pd.DataFrame) -> pd.DataFrame:
    """거시 충격의 기업별 전달 경로를 노출도로 만든다.

        exp_fx      수출비중       AA17_YTD_XPO / AA17_YTD_TOT
        exp_fx_dbt  외화부채비중   AC12_TOTAL_KRW_AM / JEMU_115000
        exp_rate    차입금의존도   JEMU_118000 / JEMU_115000
        exp_liq     단기부채비중   JEMU_116000 / JEMU_118000
        exp_inv     재고부담       1 / JEMU_191505_val (재고자산회전율의 역수)

    단위: AA17 은 천원, JEMU / AC12 는 원이다 (config.AA17_UNIT_SCALE=1000).
    위 5종은 모두 같은 테이블 안에서 비율을 만들므로 단위 보정이 필요 없다.
    AA17 과 JEMU 를 함께 쓰는 파생을 새로 만들 때는 AA17 값에 AA17_UNIT_SCALE 을
    곱해 원 단위로 맞춰야 한다.

    exp_inv 는 재고자산 계정이 원천 15개에 없어 회전율의 역수로 대리한다.
    1/회전율 = 평균재고/매출액 이므로 '매출 대비 재고 부담' 으로 해석된다.
    실측 5분위 부도배수 0.76 -> 0.89 -> 0.94 -> 1.08 -> 1.65 로 단조증가한다.
      191505_val > 0        -> 1 / val
      191505 undef(재고없음) -> 0      재고가 없으면 유가 충격 노출도 없다 (배수 0.66)
      191505_val <= 0       -> NaN + exp_inv_invalid_YN   (회전율 음수는 무의미)
      191505 결측            -> NaN + exp_inv_missing_YN
    AA17 수출비중의 0(수출 안 함) vs NaN(미보고) 구분과 동일한 논리다.
    """
    out = df.copy()

    def col(c):
        return pd.to_numeric(out[c], errors="coerce") if c in out.columns \
            else pd.Series(np.nan, index=out.index)

    out["exp_fx"] = _div(col("AA17_YTD_XPO"), col("AA17_YTD_TOT"))
    # 수출액이 음수인 행은 비중으로서 의미가 없다.
    neg_fx = out["exp_fx"] < 0
    out["exp_fx_invalid_YN"] = neg_fx.astype(float).mask(out["exp_fx"].isna())
    out.loc[neg_fx, "exp_fx"] = np.nan

    out["exp_fx_dbt"] = _div(col("AC12_TOTAL_KRW_AM"), col("JEMU_115000"))
    out["exp_rate"] = _div(col("JEMU_118000"), col("JEMU_115000"))
    out["exp_liq"] = _div(col("JEMU_116000"), col("JEMU_118000"))

    v = col("JEMU_191505_val")
    free = col("JEMU_191505_undef") == 1
    inv = pd.Series(np.nan, index=out.index)
    inv[v > 0] = 1.0 / v[v > 0]
    inv[free] = 0.0
    out["exp_inv"] = inv
    out["exp_inv_invalid_YN"] = ((v <= 0) & v.notna()).astype(float)
    out["exp_inv_missing_YN"] = (v.isna() & ~free).astype(float)

    # 제조업 여부 (BSI 상호작용용)
    mid = pd.to_numeric(industry_code(out["STD_INDS_CFC"], "mid2"), errors="coerce")
    out["is_manufacturing"] = mid.isin(list(MANUFACTURING_DIV)).astype(float).mask(mid.isna())

    if EXPOSURE_CLIP_Q is not None:
        lo_q, hi_q = EXPOSURE_CLIP_Q
        train = out["SPLIT"] == "TRAIN" if "SPLIT" in out.columns else slice(None)
        if not isinstance(train, slice):
            log.info("  윈저라이징 경계 산출 범위: Train %d행 / 전체 %d행",
                     int(train.sum()), len(out))
        else:
            log.warning("  SPLIT 없음 — 전체 구간으로 경계 산출 (누수 위험)")
        for c in EXPOSURE_COLS:
            ref = out.loc[train, c] if not isinstance(train, slice) else out[c]
            lo, hi = ref.quantile(lo_q), ref.quantile(hi_q)
            n = int(((out[c] < lo) | (out[c] > hi)).sum())
            out[f"{c}_clipped_YN"] = (((out[c] < lo) | (out[c] > hi))
                                      .astype(float).mask(out[c].isna()))
            out[c] = out[c].clip(lo, hi)
            log.info("    %-11s p%.0f=%.6f p%.0f=%.6f  절단 %d행 (%.3f%%)",
                     c, lo_q * 100, lo, hi_q * 100, hi, n, n / len(out) * 100)

    for c in EXPOSURE_COLS:
        s = out[c]
        log.info("  %-11s 결측 %5.2f%%  p1 %9.4f  p50 %9.4f  p99 %9.4f  max %12.2f",
                 c, s.isna().mean() * 100, s.quantile(.01), s.median(),
                 s.quantile(.99), s.max())
    log.info("  is_manufacturing=1 %.2f%%", out["is_manufacturing"].mean() * 100)
    return out


EXPOSURE_COLS = ["exp_fx", "exp_fx_dbt", "exp_rate", "exp_liq", "exp_inv"]


def add_industry_export_proxy(df: pd.DataFrame) -> pd.DataFrame:
    """AA17 미보고 기업에 업종 평균 수출비중을 대리값으로 부여한다.

    AA17 원천에는 4,919사만 있어 obv 스파인 27,150사의 18% 에 불과하다.
    STAGE 5 의 핵심 주장이 '환율 충격 x 수출 노출' 인데 그 채널만 결측 89.51% 라
    상호작용항이 사실상 표본의 10% 에서만 작동한다.

    추정 방식:
      1) Train 구간의 AA17 보유 행에서 기업별 평균 exp_fx 를 구한다.
         (기업별로 먼저 평균을 내야 관측 개월수가 많은 기업에 가중되지 않는다)
      2) STD_INDS_CFC 대분류(앞 2자리)별로 그 평균들의 평균을 낸다.
      3) 중분류 표본이 INDUSTRY_MIN_FIRMS 미만이면 상위 대분류(KSIC-10 A~U)로
         폴백해 대분류 평균을 쓴다. 대분류도 미달이면 추정하지 않고 NaN 으로 둔다.
         어느 레벨이 적용됐는지 exp_fx_industry_level 에 기록한다 (mid2/section/none).
         전체 평균으로 대체하지 않는다.
         전체 평균으로 대체하면 표본의 25.62% 가 동일 상수가 되어, 그 행들의
         상호작용항이 '거시지표 x 상수' = 시점 더미로 퇴화한다.
         STAGE 5 가 해결하려던 문제를 그대로 재생산하는 것이다.
         모르는 것은 모른다고 두고 LightGBM 의 NaN 네이티브 처리에 맡긴다.

    반드시 Train 구간에서만 계수를 산출한다. Valid 로 만들면 누수다.

    산출물:
      exp_fx_industry   업종 평균 수출비중 (추정치, 표본 부족 업종은 NaN)
      exp_fx_hybrid     실측이 있으면 실측, 없으면 업종 추정
      exp_fx_source     'actual' / 'industry' / 'unknown'  (범주형 피처)
                        모델이 실측과 추정을 구분할 수 있어야 한다.
    """
    import json

    out = df.copy()
    mid = industry_code(out["STD_INDS_CFC"], "mid2")
    sec = industry_code(out["STD_INDS_CFC"], "section")

    if "SPLIT" in out.columns:
        train = out["SPLIT"] == "TRAIN"
    else:
        log.warning("  SPLIT 컬럼이 없어 전체 구간으로 업종 계수를 산출합니다 (누수 위험).")
        train = pd.Series(True, index=out.index)

    base = pd.DataFrame({"firm": out["V_BZNO"].astype(str), "mid": mid, "sec": sec,
                         "fx": out["exp_fx"]})
    tr = base[train & base["fx"].notna()]

    def level_table(key):
        pf = tr[tr[key].notna()].groupby([key, "firm"])["fx"].mean().reset_index()
        g = pf.groupby(key)["fx"].agg(mean_fx="mean", n_firms="size")
        return g[g["n_firms"] >= INDUSTRY_MIN_FIRMS]

    mid_tab = level_table("mid")
    sec_tab = level_table("sec")

    if INDUSTRY_LEVEL == "mid2":
        sec_tab = sec_tab.iloc[0:0]
    elif INDUSTRY_LEVEL == "section":
        mid_tab = mid_tab.iloc[0:0]

    est = mid.map(mid_tab["mean_fx"]).astype("float64")
    lvl = pd.Series(np.where(est.notna(), "mid2", None), index=out.index, dtype="object")
    fb = est.isna()
    est_sec = sec.map(sec_tab["mean_fx"]).astype("float64")
    est = est.where(~fb, est_sec)
    lvl = lvl.where(~(fb & est.notna()), "section")
    lvl = lvl.where(est.notna(), "none")

    out["exp_fx_industry"] = est
    out["exp_fx_industry_level"] = lvl

    log.info("  업종별 수출집약도 (level=%s, Train %d행, 기업 %d사)",
             INDUSTRY_LEVEL, int(train.sum()), tr["firm"].nunique())
    log.info("    표본 %d사 이상 — 중분류 %d개 / 대분류 %d개",
             INDUSTRY_MIN_FIRMS, len(mid_tab), len(sec_tab))
    for _, r in mid_tab.sort_values("n_firms", ascending=False).head(8).iterrows():
        log.info("      [중분류] %-4s 기업 %4d사  평균 수출비중 %.4f",
                 str(r.name), int(r["n_firms"]), r["mean_fx"])
    for _, r in sec_tab.sort_values("n_firms", ascending=False).iterrows():
        log.info("      [대분류] %-4s 기업 %4d사  평균 수출비중 %.4f",
                 str(r.name), int(r["n_firms"]), r["mean_fx"])

    (config.OUTPUT_DIR / INDUSTRY_RATIO_FILE).write_text(json.dumps({
        "level": INDUSTRY_LEVEL, "min_firms": INDUSTRY_MIN_FIRMS,
        "note": "Train 구간에서만 산출. 기업별 평균 -> 업종별 평균. "
                "표본 부족 업종은 상위 레벨로 폴백하고, 대분류도 부족하면 추정하지 않는다.",
        "mid2": {str(k): {"mean_fx": float(v["mean_fx"]), "n_firms": int(v["n_firms"])}
                 for k, v in mid_tab.iterrows()},
        "section": {str(k): {"mean_fx": float(v["mean_fx"]), "n_firms": int(v["n_firms"])}
                    for k, v in sec_tab.iterrows()},
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("    업종 계수 테이블 저장: %s", INDUSTRY_RATIO_FILE)

    actual = out["exp_fx"].notna()
    out["exp_fx_hybrid"] = out["exp_fx"].where(actual, out["exp_fx_industry"])
    out["exp_fx_source"] = np.where(actual, "actual",
                                    np.where(out["exp_fx_industry"].notna(),
                                             "industry", "unknown"))
    log.info("    exp_fx_industry_level: %s",
             {k: int(v) for k, v in lvl.value_counts().items()})
    log.info("    exp_fx_source: %s",
             {k: int(v) for k, v in pd.Series(out["exp_fx_source"]).value_counts().items()})
    log.info("    exp_fx 결측 %.2f%% -> exp_fx_hybrid 결측 %.2f%%",
             out["exp_fx"].isna().mean() * 100, out["exp_fx_hybrid"].isna().mean() * 100)
    return out


# ====================================================================
# 5-2 상호작용항
# ====================================================================
# (신규 컬럼명, 거시 컬럼, 노출도 컬럼). 확장하려면 이 리스트에 추가하면 된다.
INTERACTIONS: list[tuple[str, str, str]] = [
    ("fx_shock_x_export",      "USD_KRW_log_ret",         "exp_fx"),
    ("fx_vol_x_fxdebt",        "USD_KRW_vol_m",           "exp_fx_dbt"),
    ("eur_shock_x_export",     "EUR_KRW_log_ret",         "exp_fx"),
    ("rate_shock_x_leverage",  "base_rate_diff12",        "exp_rate"),
    ("credit_spread_x_lev",    "credit_spread_diff12",    "exp_rate"),
    ("liq_spread_x_shortdebt", "liquidity_spread_diff12", "exp_liq"),
    ("oil_shock_x_inv",        "WTI_crude_oil_log_ret",   "exp_inv"),
    ("bsi_x_industry",         "BSI_mfg_biz_yoy",         "is_manufacturing"),
    # 하이브리드 버전: 실측 + 업종추정. STAGE 6 에서 실측 전용 버전과 기여도를 비교한다.
    ("fx_shock_x_export_hybrid",  "USD_KRW_log_ret", "exp_fx_hybrid"),
    ("eur_shock_x_export_hybrid", "EUR_KRW_log_ret", "exp_fx_hybrid"),
]


def add_interactions(df: pd.DataFrame) -> pd.DataFrame:
    """거시지표 x 노출도. 노출도가 NaN 이면 결과도 NaN 이어야 한다 (0 으로 채우지 않는다)."""
    out = df.copy()
    made, skipped = [], []
    for name, macro, expo in INTERACTIONS:
        if macro not in out.columns or expo not in out.columns:
            skipped.append((name, macro if macro not in out.columns else expo))
            continue
        out[name] = pd.to_numeric(out[macro], errors="coerce") * out[expo]
        made.append(name)
    if skipped:
        for n, miss in skipped:
            log.warning("  상호작용 %s 생략 — %s 없음", n, miss)
    log.info("  상호작용항 %d개 생성 / %d개 생략", len(made), len(skipped))
    return out


# ====================================================================
# 5-4 _ma3m 중복 정리
# ====================================================================

def resolve_ma3m(macro: pd.DataFrame, mode: str = "keep_both") -> pd.DataFrame:
    """원본과 _ma3m 이동평균 중 한쪽만 남기는 옵션.

    어느 쪽이 나은지는 STAGE 6 에서 실측한다. 기본값은 기존 동작(둘 다 유지)이다.
    """
    if mode not in MA3M_MODES:
        raise ValueError(f"알 수 없는 ma3m_mode: {mode!r} (가능: {MA3M_MODES})")
    if mode == "keep_both":
        log.info("  _ma3m 정리: keep_both (기존 동작)")
        return macro

    ma3m = [c for c in macro.columns if c.endswith("_ma3m")]
    base = [c[:-5] for c in ma3m]
    paired = [(b, m) for b, m in zip(base, ma3m) if b in macro.columns]
    drop = [m for _, m in paired] if mode == "keep_base" else [b for b, _ in paired]
    out = macro.drop(columns=drop)
    log.info("  _ma3m 정리: %s — 쌍 %d개 중 %d개 컬럼 제거 (%d -> %d)",
             mode, len(paired), len(drop), len(macro.columns), len(out.columns))
    return out


# ====================================================================
# 거시 시차
# ====================================================================

def reduce_macro(macro: pd.DataFrame, enable: bool = MACRO_REDUCE) -> pd.DataFrame:
    """기존 모델에서 gain>0 인 거시 변수만 유지한다 (172 -> 87, gain 보존 100%).

    172개 중 85개(49.4%)는 단 한 번도 분기에 쓰이지 않았다.
    제거 목록은 macro_dropped_v2.json 으로 남긴다.

    ※ 판정 기준이 된 lgbm_12m_model.txt 는 누수 포함 모델이다. 누수 제거 후에는
      중요도 순위가 달라질 수 있으므로 이 축소는 잠정이며, STAGE 6 에서
      MACRO_REDUCE=False 로 축소 전 버전과 비교한다.
    """
    if not enable:
        log.info("  거시 축소: 비활성 (MACRO_REDUCE=False) — %d개 유지", len(macro.columns) - 1)
        return macro

    import json
    import re
    model = config.OUTPUT_DIR / REFERENCE_MODEL
    if not model.exists():
        log.warning("  %s 없음 — 거시 축소를 건너뜁니다.", REFERENCE_MODEL)
        return macro

    txt = model.read_text(encoding="utf-8")
    feats = re.search(r"^feature_names=(.+)$", txt, re.M).group(1).split()
    gain = np.zeros(len(feats))
    for a, b in zip(re.findall(r"^split_feature=(.*)$", txt, re.M),
                    re.findall(r"^split_gain=(.*)$", txt, re.M)):
        if not a.strip():
            continue
        for i, g in zip((int(x) for x in a.split()), (float(x) for x in b.split())):
            gain[i] += g
    used = {f for f, g in zip(feats, gain) if g > 0}

    # 상호작용항 재료는 gain 과 무관하게 반드시 남긴다.
    # 축소가 STAGE 5 의 핵심 산출물을 없애면 본말전도다.
    required = {m for _, m, _ in INTERACTIONS}
    cols = [c for c in macro.columns if c != "BASE_YM"]
    keep = [c for c in cols if c in used or c in required]
    drop = [c for c in cols if c not in used and c not in required]
    forced = sorted(required & set(cols) - used)
    if forced:
        log.info("  거시 축소: gain=0 이지만 상호작용 재료라 보존 = %s", forced)
    if not keep:
        log.warning("  기준 모델과 겹치는 거시 변수가 없어 축소를 건너뜁니다.")
        return macro

    (config.OUTPUT_DIR / MACRO_DROPPED_FILE).write_text(
        json.dumps({"reference_model": REFERENCE_MODEL,
                    "criterion": "gain > 0 in reference model",
                    "note": "기준 모델은 누수 포함 모델이므로 이 축소는 잠정이다. "
                            "STAGE 6에서 MACRO_REDUCE=False 버전과 비교할 것.",
                    "kept_for_interactions": forced,
                    "n_before": len(cols), "n_after": len(keep),
                    "dropped": sorted(drop)}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    log.info("  거시 축소: %d -> %d개 (gain>0 기준, 제거 %d개) — %s 저장",
             len(cols), len(keep), len(drop), MACRO_DROPPED_FILE)
    return macro[["BASE_YM"] + keep]


def apply_categorical(df: pd.DataFrame) -> pd.DataFrame:
    """문자열 피처를 category dtype 으로 고정한다.

    카테고리 순서가 Train / Valid 에서 달라지면 조용히 잘못 학습되므로
    CATEGORICAL_COLS 에 적은 순서로 고정하고 매핑을 JSON 으로 남긴다.
    DuckDB 의 Parquet 왕복은 category 를 VARCHAR 로 되돌리므로,
    config.read_panel() 이 이 JSON 을 읽어 dtype 을 복원한다.
    """
    import json
    out = df.copy()
    # 업종 파생 2종 (원본 STD_INDS_CFC 는 피처로 쓰지 않는다)
    if "STD_INDS_CFC" in out.columns:
        out["STD_INDS_SECTION"] = industry_code(out["STD_INDS_CFC"], "section")
        out["STD_INDS_MID2"] = industry_code(out["STD_INDS_CFC"], "mid2")

    train = out["SPLIT"] == "TRAIN" if "SPLIT" in out.columns else slice(None)
    saved, oversized = {}, []
    for c, cats in CATEGORICAL_COLS.items():
        if c not in out.columns:
            continue
        if cats is None:
            # Train 구간에서 관측된 값만 카테고리로 고정한다.
            ref = out.loc[train, c] if not isinstance(train, slice) else out[c]
            full = sorted(str(v) for v in ref.dropna().unique())
            unseen = sorted(set(out[c].dropna().astype(str)) - set(full))
            if unseen:
                n_rows = int(out[c].astype(str).isin(unseen).sum())
                ratio = n_rows / len(out)
                log.warning("  %s: Train 에 없는 레벨 %d개 / %d행 (%.4f%%) -> NaN 처리 %s",
                            c, len(unseen), n_rows, ratio * 100, unseen[:5])
                if ratio > UNSEEN_LEVEL_MAX_RATIO:
                    raise ValueError(
                        f"{c}: Train 에 없는 카테고리 레벨이 {n_rows:,}행 "
                        f"({ratio*100:.4f}%) 로 상한 {UNSEEN_LEVEL_MAX_RATIO*100:.2f}% 를 "
                        f"넘습니다. 레벨: {unseen[:20]}\n"
                        f"  세그먼트 모드나 기간을 바꾸면 미지 업종이 늘어날 수 있습니다. "
                        f"UNSEEN_LEVEL_MAX_RATIO 를 조정하거나 업종 단위를 상위로 "
                        f"올리세요 (INDUSTRY_FEATURE_MODE='section').")
            out[c] = pd.Categorical(out[c].astype("object").where(out[c].notna()),
                                    categories=full)
        else:
            seen = set(out[c].dropna().unique())
            extra = sorted(seen - set(cats))
            if extra:
                log.warning("  %s 에 사전 정의되지 않은 값 %s — 뒤에 붙입니다.", c, extra)
            full = list(cats) + extra
            out[c] = pd.Categorical(out[c], categories=full)
        saved[c] = full
        mark = "  ★ 고유값 과다" if len(full) > CATEGORY_MAX_LEVELS else ""
        if mark:
            oversized.append(c)
        log.info("  category: %-24s 레벨 %3d개%s", c, len(full), mark)

    # 업종 피처 조합 선택 (STAGE 6 S9a/S9b/S9c). 미사용 컬럼은 NON_FEATURE 처럼 남기되
    # 학습에서 빠지도록 목록에 기록한다.
    drop_ind = {"section": ["STD_INDS_MID2"], "mid2": ["STD_INDS_SECTION"],
                "both": []}.get(INDUSTRY_FEATURE_MODE)
    if drop_ind is None:
        raise ValueError(f"알 수 없는 INDUSTRY_FEATURE_MODE: {INDUSTRY_FEATURE_MODE!r}")
    if drop_ind:
        log.info("  INDUSTRY_FEATURE_MODE=%s -> 학습 제외 대상 %s",
                 INDUSTRY_FEATURE_MODE, drop_ind)

    other = [c for c in out.columns
             if out[c].dtype == object and c not in CATEGORICAL_COLS]
    if other:
        log.info("  [점검] 아직 object dtype 인 컬럼 %d개: %s", len(other), other)
    if saved:
        (config.OUTPUT_DIR / CATEGORY_MAP_FILE).write_text(
            json.dumps({"note": "카테고리 순서는 Train 구간 기준으로 고정. Valid 동일 적용. "
                                "STD_INDS_CFC 원본은 고유값 1,147개라 category 로 만들지 않고 "
                                "NON_FEATURE 로 두며, 대분류/중분류 파생만 쓴다.",
                        "max_levels": CATEGORY_MAX_LEVELS,
                        "industry_feature_mode": INDUSTRY_FEATURE_MODE,
                        "industry_excluded_from_training": drop_ind,
                        "unseen_level_max_ratio": UNSEEN_LEVEL_MAX_RATIO,
                        "oversized": oversized,
                        "levels": {k: v for k, v in saved.items()},
                        "n_levels": {k: len(v) for k, v in saved.items()},
                        "remaining_object_cols": other},
                       ensure_ascii=False, indent=2), encoding="utf-8")
        log.info("  카테고리 매핑 저장: %s", CATEGORY_MAP_FILE)
    return out


def apply_macro_lag(macro_df: pd.DataFrame, months: int = MACRO_LAG_MONTHS) -> pd.DataFrame:
    """거시지표에 추가 시차를 적용한다.

    months=0 이면 아무것도 하지 않는다. 공표 시차는 상류 impute_data 가 지표군별로
    이미 걸었다 (MACRO_LAG_MONTHS 주석 참조). 여기서 더 거는 것은 이중 시차다.

    months>=1 은 구 동작 재현용이다. 이 경로에서도 bfill 은 쓰지 않는다.
    shift 로 비게 된 앞쪽 months 개월은 NaN 으로 두고, 조인 뒤 무결성 검사가
    잡도록 한다. bfill 로 되메우면 시차를 걸고 그 자리에서 푸는 셈이 된다.
    """
    if months <= 0:
        log.info("  거시 추가 시차: 없음 (공표 시차는 impute_data 가 지표군별로 적용)")
        return macro_df.sort_values('BASE_YM').copy()
    macro_df = macro_df.sort_values('BASE_YM').copy()
    features = [c for c in macro_df.columns if c != 'BASE_YM']
    macro_df[features] = macro_df[features].shift(months)
    log.warning("  거시 추가 시차 %d개월 — 상류 공표 시차와 합쳐져 이중 시차가 된다.", months)
    return macro_df


# ====================================================================
# 파이프라인
# ====================================================================

def main(spine_mode: str | None = None, segment_mode: str = "none",
         ma3m_mode: str = "keep_both", macro_path: str | Path | None = None,
         save: bool = True, tag: str = "") -> pd.DataFrame:
    spine = spine_mode or config.SPINE_MODE
    panel_path = config.OUTPUT_DIR / f"nh_panel_prep_{spine}_{segment_mode}.csv"
    panel_path = config._swap_ext(panel_path) if config._swap_ext(panel_path).exists() \
        else panel_path
    macro_path = Path(macro_path) if macro_path else config.macro_input_path()
    # tag 는 산출물 덮어쓰기 방지용이다. 합성 거시로 만든 기존 패널
    # (portal_v2.duckdb 의 원천) 을 지우지 않고 실거시 패널을 따로 남긴다.
    suffix = f"_{tag}" if tag else ""
    out_stem = config.OUTPUT_DIR / f"nh_panel_macro_12m_{spine}_{segment_mode}{suffix}.csv"

    if not panel_path.exists():
        raise FileNotFoundError(
            f"{panel_path} 가 없습니다. step5 를 먼저 실행하세요:\n"
            f"  python eda_pipeline/step5_panel_prep.py --spine {spine} --segment {segment_mode}")
    if not macro_path.exists():
        raise FileNotFoundError(
            f"{macro_path} 가 없습니다.\n"
            f"  거시 데이터는 .gitignore(*.csv)로 제외되어 이 체크아웃에 없습니다.\n"
            f"  --macro 로 경로를 지정하거나 거시 수집 파이프라인을 먼저 실행하세요.")

    log.info(f"패널 로딩: {panel_path.name}")
    panel = config.read_panel(panel_path, dtype={'BASE_YM': str})
    panel['BASE_YM'] = panel['BASE_YM'].astype(str).str.replace(r'\.0$', '', regex=True)
    n0 = len(panel)
    log.info(f"거시 데이터 로딩: {macro_path.name}")
    macro = pd.read_csv(macro_path)

    macro = reduce_macro(macro)
    macro = resolve_ma3m(macro, ma3m_mode)
    macro = apply_macro_lag(macro, MACRO_LAG_MONTHS)

    log.info("[5-1] 기업별 거시 노출도 생성")
    panel = build_exposures(panel)
    log.info("[5-1b] 업종 기반 수출 노출도 대리변수")
    panel = add_industry_export_proxy(panel)

    panel['BASE_YM'] = panel['BASE_YM'].astype(str).str.replace(r'\.0$', '', regex=True)
    macro['BASE_YM'] = macro['BASE_YM'].astype(str)
    merged = panel.merge(macro, on='BASE_YM', how='left')
    assert len(merged) == n0, f"거시 조인에서 행수 변동: {n0} -> {len(merged)}"

    macro_features = [c for c in macro.columns if c != 'BASE_YM']
    miss = merged[macro_features].isnull().sum().sum()
    if miss:
        # 조용히 ffill/bfill 로 메우지 않는다. bfill 은 미래 값을 과거로 끌어오므로
        # 결측을 메우는 순간 그 구간이 통째로 누수가 된다 (D축 G1-4).
        # 거시 원천이 패널 기간을 덮지 못한다는 뜻이므로 원천을 고쳐야 한다.
        bad = (merged.loc[merged[macro_features].isnull().any(axis=1), 'BASE_YM']
               .astype(str).drop_duplicates().sort_values().tolist())
        raise ValueError(
            f"거시 결합 후 결측 {miss}개 — 결측 BASE_YM {len(bad)}개월: {bad[:24]}\n"
            f"  거시 원천({macro_path.name}) 범위: "
            f"{macro['BASE_YM'].min()} ~ {macro['BASE_YM'].max()}\n"
            f"  패널 범위: {panel['BASE_YM'].min()} ~ {panel['BASE_YM'].max()}\n"
            f"  ffill/bfill 로 메우지 않는다. 원천 수집 구간을 넓히거나 "
            f"패널 시작월을 늦출 것.")

    merged = apply_categorical(merged)

    log.info("[5-2] 상호작용항 생성")
    merged = add_interactions(merged)
    assert len(merged) == n0, f"상호작용 생성에서 행수 변동: {n0} -> {len(merged)}"

    log.info(f"결합 완료 — {merged.shape}")
    if save:
        saved = config.save_panel(merged, out_stem)
        log.info(f"저장: {saved.name}")
    return merged


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--spine', default=None, choices=['obv', 'full', 'legacy'])
    ap.add_argument('--segment', default='none', choices=['none', 'bzscal', 'sales'])
    ap.add_argument('--ma3m', default='keep_both', choices=list(MA3M_MODES))
    ap.add_argument('--macro', default=None, help='거시 CSV 경로 (기본: config)')
    ap.add_argument('--no-reduce', action='store_true', help='거시 축소 비활성 (172개 유지)')
    ap.add_argument('--industry', default=None, choices=['section', 'mid2', 'both'],
                    help='업종 피처 조합 (S9a/S9b/S9c)')
    ap.add_argument('--tag', default='', help='산출물 파일명 접미사 (덮어쓰기 방지)')
    ap.add_argument('--lag', type=int, default=None,
                    help='거시 추가 시차(개월). 기본 0. 구 동작 재현은 1')
    a = ap.parse_args()
    if a.lag is not None:
        globals()['MACRO_LAG_MONTHS'] = a.lag
    if a.no_reduce:
        globals()['MACRO_REDUCE'] = False
    if a.industry:
        globals()['INDUSTRY_FEATURE_MODE'] = a.industry
    main(spine_mode=a.spine, segment_mode=a.segment,
         ma3m_mode=a.ma3m, macro_path=a.macro, tag=a.tag)
