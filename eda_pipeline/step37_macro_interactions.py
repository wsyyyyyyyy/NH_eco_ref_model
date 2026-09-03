"""
======================================================================
E축 3단계 — 거시 × 노출도 상호작용 생성 및 압축
======================================================================
1단계(전수 부호 검사)를 통과한 거시 계열에 경제 채널이 맞는 노출도를 짝지어
상호작용항을 만들고, 압축 규칙으로 걸러 25개 이하로 줄인다.

설계 원칙
--------
  - **전체 조합을 만들지 않는다.** 경제 채널이 맞는 짝만 만든다.
    거시 실질 표본이 53개월이므로 항이 많아지면 그 한 번의 사이클에 과적합된다.
  - **단조 제약 부호는 경제 이론으로 사전 지정한다.** Valid 상관을 보고 정하지
    않는다 — 그것은 홀드아웃 오염이다. 방향이 불명확하면 0(제약 없음)으로 둔다.
  - 노출도 `exp_fx` 는 쓰지 않는다. obv 스파인에서 결측 89.51% 라
    `fx_shock_x_export` 가 gain 0.000 / 최하위가 된 원인이다.
    대신 `exp_fx_hybrid`(결측 11.04%)와 `is_manufacturing`(결측 0%)을 쓴다.

압축 규칙 (순서대로)
------------------
  R1  결측률 80% 초과 제거
  R2  충격(거시항) 0 인 달 비율 40% 초과 제거
      — `rate_shock_x_leverage` 가 Valid 53.14% 에서 0 이었던 문제 방지
  R3  충격 0 인 달을 제외하고도 BASE_YM 내 기업 간 분산이 0 이면 제거
  R4  상호작용항 간 상관 0.95 이상 그룹은 대표 1개만 (Train 상관 절댓값 큰 쪽)
  R5  25개 초과면 Train 상관 절댓값 상위 25개. 단 **각 계열 최소 1개는 남긴다**
      — 한 계열이 상한을 독점하지 않게 한다

Usage
-----
    python -m eda_pipeline.step37_macro_interactions
    python -m eda_pipeline.step37_macro_interactions --max-terms 25
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import duckdb
import numpy as np
import pandas as pd

from eda_pipeline import config, split_spec

PANEL = config.OUTPUT_DIR / "nh_panel_macro_12m_obv_none_real.parquet"
OUT_JSON = config.VALIDATION_DIR / "macro_interaction_candidates.json"

TARGET = "IS_BUDO_12M"

# ── 압축 임계 ───────────────────────────────────────────────────────
MISS_MAX = 0.80             # R1
ZERO_SHOCK_MAX = 0.40       # R2
CORR_DUP = 0.95             # R4
MAX_TERMS_DEFAULT = 25      # R5

# ══════════════════════════════════════════════════════════════════════
# 명세 — (거시항, 노출도, 계열, 단조부호, 부호 근거)
# ══════════════════════════════════════════════════════════════════════
# 부호: +1 = 값이 오르면 PD 상승 / -1 = 값이 오르면 PD 하락 / 0 = 제약 없음
SPEC: list[tuple[str, str, str, int, str]] = [
    # ── 심리 3종 (1단계 통과) ─────────────────────────────────────
    ("BSI_mfg_biz_yoy", "is_manufacturing", "심리", -1,
     "제조업 업황 개선은 제조기업의 부도를 줄인다"),
    ("BSI_mfg_biz_yoy", "exp_young", "심리", -1,
     "업황 개선의 혜택은 신생기업에도 같은 방향으로 작용한다"),
    ("BSI_mfg_domestic_yoy", "is_manufacturing", "심리", -1,
     "내수 업황 개선은 제조기업의 부도를 줄인다"),
    ("BSI_mfg_domestic_yoy", "exp_young", "심리", -1,
     "내수 개선은 업력이 짧아 완충이 얇은 기업에 더 크게 작용한다"),
    ("CSI_composite_yoy", "is_manufacturing", "심리", -1,
     "소비자심리 개선은 최종수요를 늘려 부도를 줄인다"),
    ("CSI_composite_yoy", "exp_young", "심리", -1,
     "소비 회복은 신생기업의 매출 기반을 넓힌다"),

    # ── 환율 3종 — exp_fx 대신 hybrid / is_manufacturing ──────────
    ("CNY_KRW_vol_m", "is_manufacturing", "환율", +1,
     "환율 변동성 확대는 불확실성이며 제조기업의 위험을 키운다"),
    ("CNY_KRW_vol_m", "exp_fx_hybrid", "환율", +1,
     "수출 노출이 큰 기업일수록 환변동성 위험이 크다"),
    ("EUR_KRW_vol_m", "is_manufacturing", "환율", +1,
     "동일 — 통화만 다르다"),
    ("EUR_KRW_vol_m", "exp_fx_hybrid", "환율", +1,
     "동일 — 통화만 다르다"),
    ("CNY_KRW_log_ret", "is_manufacturing", "환율", 0,
     "원화 절하는 수출에 유리·수입에 불리로 양방향이다. 부호를 정하지 않는다"),
    ("CNY_KRW_log_ret", "exp_fx_hybrid", "환율", 0,
     "동일 — 방향 불명확"),

    # ── 무역·국제수지 2종 ────────────────────────────────────────
    ("export_index_yoy", "is_manufacturing", "무역", -1,
     "수출 증가는 제조기업의 매출을 늘려 부도를 줄인다"),
    ("current_account_quarterly_yoy", "is_manufacturing", "무역", -1,
     "경상수지 개선은 대외 부문 호조이며 제조기업에 유리하다"),

    # ── 원자재 ──────────────────────────────────────────────────
    ("soybean_vol_m", "exp_inv", "원자재", 0,
     "대두 가격 변동성과 국내 중소기업 부도의 방향을 이론으로 정할 수 없다"),

    # ── 부동산·건설 ─────────────────────────────────────────────
    ("unsold_housing_yoy", "is_manufacturing", "부동산", +1,
     "미분양 증가는 건설·연관 제조 수요 위축이며 부도를 늘린다"),

    # ── 금리 (1단계 완화 통과, 4구간 부호 일치) ───────────────────
    # ★ [2026-09-02] 제약 +1 -> 0 으로 조정.
    #   KORIBOR 3M − 기준금리는 **양방향으로 해석되는 지표**다.
    #   자금경색이면 조달 스프레드가 벌어져 오르지만, 경기가 좋아 금리 인상이
    #   예상될 때도 KORIBOR 가 기준금리보다 먼저 오른다. 스트레스 신호일 수도,
    #   호황 신호일 수도 있다. 경제적 해석이 하나로 정해지지 않으므로
    #   제약을 걸 근거가 없다 — "데이터가 반대라서 뺀 것이 아니다."
    ("NEW_KORIBOR_spread_diff12", "exp_rate", "금리", 0,
     "KORIBOR−기준금리는 자금경색과 인상 기대를 함께 반영해 방향이 양방향이다"),
    ("NEW_KORIBOR_spread_diff12", "exp_liq", "금리", 0,
     "동일 — 지표의 경제적 해석이 양방향이라 제약 근거가 없다"),

    # ── 예비 4종 (약한 후보. 부호 일치는 확보) ───────────────────
    # 제약 +1 -> 0. 식료품 물가는 원가 압박(PD 상승)과 명목 매출 증가(PD 하락)를
    # 함께 일으켜 순방향이 정해지지 않는다.
    ("CPI_food_nonalcohol_yoy", "exp_rate", "물가", 0,
     "식료품 물가는 원가 압박과 명목 매출 증가가 상쇄되어 방향이 불명확하다"),
    ("JPY_KRW_log_ret", "is_manufacturing", "환율", 0,
     "방향 불명확 — 예비 후보"),
    ("gold_log_ret", "exp_inv", "원자재", 0,
     "금값은 안전자산 선호의 지표로 방향이 불명확하다 — 예비 후보"),
    # 제약 -1 -> 0. 중국 주가는 대중 수출 여건과 중국발 경쟁 심화를 함께 반영한다.
    ("Shanghai_Composite_log_ret", "is_manufacturing", "주가", 0,
     "중국 주가는 수출 여건 개선과 경쟁 심화를 함께 반영해 방향이 불명확하다 — 예비 후보"),
]

#: 예비(약한) 후보로 표기할 거시항
WEAK_MACRO = {"CPI_food_nonalcohol_yoy", "JPY_KRW_log_ret", "gold_log_ret",
              "Shanghai_Composite_log_ret"}


def term_name(macro: str, expo: str) -> str:
    m = macro.replace("NEW_", "").replace("_yoy", "").replace("_log_ret", "_ret")
    m = m.replace("_vol_m", "_vol").replace("_diff12", "_d12")
    e = expo.replace("is_manufacturing", "mfg").replace("exp_", "")
    return f"ix_{m}__{e}"


# ══════════════════════════════════════════════════════════════════════
# 적재
# ══════════════════════════════════════════════════════════════════════

def load_macro() -> pd.DataFrame:
    """cleaned + 신규 스프레드. 신규분은 시차 적용 레벨에서 만든다."""
    from eda_pipeline.step35_macro_level_diagnosis import build_extra_candidates
    m = pd.read_csv(config.macro_input_path(), dtype={"BASE_YM": str})
    m["BASE_YM"] = m["BASE_YM"].astype(str).str.strip()
    m = m.sort_values("BASE_YM").set_index("BASE_YM")
    ex = build_extra_candidates()
    if not ex.empty:
        m = m.join(ex, how="left")
    return m


#: 2단계 신규 노출도. 패널에 없으므로 여기서 파생한다.
#   ★ BUSINESS_AGE 는 **연 단위**다 (실측: p25 7.62 / 중앙 13.0 / p75 20.91).
#     개월로 오인해 `<= 60` 을 쓰면 99.43% 가 1 이 되어 분산이 사라진다.
#     "업력 5년 이하" 는 `<= 5` 이고 실측 12.63% 다.
YOUNG_AGE_YEARS = 5
DERIVED_EXPOSURE = {"exp_young": "BUSINESS_AGE"}


def load_panel_exposures(exposures: list[str]) -> pd.DataFrame:
    need_src = {DERIVED_EXPOSURE[e] for e in exposures if e in DERIVED_EXPOSURE}
    base = [e for e in exposures if e not in DERIVED_EXPOSURE]
    cols = ["V_BZNO", "BASE_YM", TARGET] + base + sorted(need_src)
    sel = ", ".join(f'"{c}"' for c in dict.fromkeys(cols))
    con = duckdb.connect()
    try:
        df = con.execute(
            f"SELECT {sel} FROM read_parquet('{PANEL.as_posix()}')").df()
    finally:
        con.close()
    df["BASE_YM"] = df["BASE_YM"].astype(str)
    if "exp_young" in exposures:
        age = pd.to_numeric(df["BUSINESS_AGE"], errors="coerce")
        df["exp_young"] = (age <= YOUNG_AGE_YEARS).astype(float).mask(age.isna())
        print(f"  [2단계] exp_young = (BUSINESS_AGE <= {YOUNG_AGE_YEARS}년) 생성 — "
              f"1 인 비율 {df['exp_young'].mean() * 100:.2f}% / "
              f"결측 {df['exp_young'].isna().mean() * 100:.2f}%")
    return df


def default_rate_by_month(df: pd.DataFrame) -> pd.Series:
    return df.groupby("BASE_YM")[TARGET].mean() * 100


# ══════════════════════════════════════════════════════════════════════
# 생성 + 압축
# ══════════════════════════════════════════════════════════════════════

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-terms", type=int, default=MAX_TERMS_DEFAULT)
    a = ap.parse_args()

    macro = load_macro()
    exposures = sorted({e for _, e, _, _, _ in SPEC})
    missing_macro = sorted({m for m, _, _, _, _ in SPEC if m not in macro.columns})
    if missing_macro:
        raise SystemExit(f"거시 원천에 없는 항: {missing_macro}")

    df = load_panel_exposures(exposures)
    rate = default_rate_by_month(df)
    months = sorted(df["BASE_YM"].unique())
    tr_months = [x for x in months if x < split_spec.DEV_START]

    print("=" * 104)
    print(f"E축 3단계 — 상호작용 생성 및 압축   후보 {len(SPEC)}개")
    print("=" * 104)
    print(f"  패널 {len(df):,}행 / 월 {len(months)}개 (Train {len(tr_months)}개월)")
    print(f"  노출도 {exposures}")
    print()

    rows = []
    for macro_col, expo, channel, mono, why in SPEC:
        name = term_name(macro_col, expo)
        mvals = pd.to_numeric(macro[macro_col], errors="coerce")
        mser = df["BASE_YM"].map(mvals)
        vals = mser.astype(float) * pd.to_numeric(df[expo], errors="coerce")

        miss = float(vals.isna().mean())
        # 충격 0 인 달 (거시항이 정확히 0)
        zero_months = [x for x in months
                       if pd.notna(mvals.get(x)) and float(mvals.get(x)) == 0.0]
        zero_rate = float(df["BASE_YM"].isin(zero_months).mean())
        # 충격 0 인 달 제외 후 BASE_YM 내 기업 간 분산
        sub = pd.DataFrame({"ym": df["BASE_YM"], "v": vals})
        sub = sub[~sub["ym"].isin(zero_months)]
        nun = sub.groupby("ym")["v"].nunique(dropna=True)
        n_novar = int((nun <= 1).sum())
        # Train 구간 월별 평균과 부도율의 상관 (R5 순위용)
        mon_mean = pd.DataFrame({"ym": df["BASE_YM"], "v": vals}) \
            .groupby("ym")["v"].mean()
        idx = [x for x in tr_months if x in mon_mean.index
               and pd.notna(mon_mean[x]) and pd.notna(rate.get(x))]
        corr_tr = (float(np.corrcoef(mon_mean.loc[idx], rate.loc[idx])[0, 1])
                   if len(idx) > 3 and mon_mean.loc[idx].nunique() > 1
                   else float("nan"))
        rows.append({
            "term": name, "macro": macro_col, "exposure": expo,
            "channel": channel, "monotone": mono, "sign_rationale": why,
            "weak": macro_col in WEAK_MACRO,
            "missing_rate": miss, "zero_shock_month_n": len(zero_months),
            "zero_shock_row_rate": zero_rate,
            "n_month_no_variance": n_novar,
            "corr_train": corr_tr,
        })

    # ── 압축 ────────────────────────────────────────────────────
    print(f"  {'항':44s} {'계열':6s} {'제약':>4s} {'결측%':>7s} {'충격0%':>7s} "
          f"{'무분산월':>8s} {'Tr상관':>8s}")
    for r in rows:
        print(f"  {r['term']:44s} {r['channel']:6s} {r['monotone']:+4d} "
              f"{r['missing_rate']*100:7.2f} {r['zero_shock_row_rate']*100:7.2f} "
              f"{r['n_month_no_variance']:8d} "
              f"{r['corr_train'] if np.isfinite(r['corr_train']) else float('nan'):+8.3f}")

    dropped: dict[str, list[str]] = {}

    def _drop(rule: str, pred) -> None:
        nonlocal rows
        out = [r for r in rows if pred(r)]
        gone = [r["term"] for r in rows if not pred(r)]
        if gone:
            dropped[rule] = gone
        rows = out

    _drop(f"R1 결측률 > {MISS_MAX:.0%}", lambda r: r["missing_rate"] <= MISS_MAX)
    _drop(f"R2 충격 0 인 달 비율 > {ZERO_SHOCK_MAX:.0%}",
          lambda r: r["zero_shock_row_rate"] <= ZERO_SHOCK_MAX)
    _drop("R3 충격 0 제외 후에도 월내 무분산", lambda r: r["n_month_no_variance"] == 0)
    _drop("R3b Train 상관 측정 불가", lambda r: np.isfinite(r["corr_train"]))

    # R4 — 항 간 상관 0.95 이상 중복 제거 (월별 평균 기준)
    if len(rows) > 1:
        mm = {}
        for r in rows:
            mvals = pd.to_numeric(macro[r["macro"]], errors="coerce")
            v = df["BASE_YM"].map(mvals).astype(float) * \
                pd.to_numeric(df[r["exposure"]], errors="coerce")
            mm[r["term"]] = pd.DataFrame({"ym": df["BASE_YM"], "v": v}) \
                .groupby("ym")["v"].mean()
        M = pd.DataFrame(mm).loc[tr_months]
        cm = M.corr().abs()
        order = sorted(rows, key=lambda r: -abs(r["corr_train"]))
        keep, removed = [], []
        for r in order:
            if any(cm.loc[r["term"], k["term"]] >= CORR_DUP for k in keep):
                removed.append(r["term"])
            else:
                keep.append(r)
        if removed:
            dropped[f"R4 항 간 상관 >= {CORR_DUP} 중복"] = removed
        rows = keep

    # R5 — 상한. 계열 다양성 보장
    if len(rows) > a.max_terms:
        by_ch: dict[str, list] = {}
        for r in rows:
            by_ch.setdefault(r["channel"], []).append(r)
        keep = []
        for ch, rs in by_ch.items():                     # 계열별 최소 1개
            keep.append(max(rs, key=lambda r: abs(r["corr_train"])))
        rest = [r for r in rows if r not in keep]
        rest.sort(key=lambda r: -abs(r["corr_train"]))
        keep += rest[: max(a.max_terms - len(keep), 0)]
        dropped[f"R5 상한 {a.max_terms} 초과"] = [r["term"] for r in rows
                                                  if r not in keep]
        rows = keep

    print()
    print("=" * 104)
    print("압축 결과")
    print("=" * 104)
    for rule, terms in dropped.items():
        print(f"  [{rule}] {len(terms)}개 제거")
        for t in terms:
            print(f"      - {t}")
    if not dropped:
        print("  제거 없음")

    rows.sort(key=lambda r: (r["channel"], -abs(r["corr_train"])))
    print()
    print(f"★ 최종 {len(rows)}개")
    print(f"  {'항':44s} {'계열':6s} {'제약':>4s} {'Tr상관':>8s} {'결측%':>7s} 비고")
    from collections import Counter
    for r in rows:
        print(f"  {r['term']:44s} {r['channel']:6s} {r['monotone']:+4d} "
              f"{r['corr_train']:+8.3f} {r['missing_rate']*100:7.2f} "
              f"{'약한 후보' if r['weak'] else ''}")
    print()
    print("  계열 분포: " + " / ".join(
        f"{k} {v}" for k, v in sorted(Counter(r["channel"] for r in rows).items())))
    print("  제약 분포: " + " / ".join(
        f"{k:+d} → {v}개" for k, v in sorted(Counter(r["monotone"] for r in rows).items())))
    print(f"  약한 후보 {sum(1 for r in rows if r['weak'])}개")

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(
        {"n_spec": len(SPEC), "n_final": len(rows),
         "thresholds": {"missing_max": MISS_MAX,
                        "zero_shock_max": ZERO_SHOCK_MAX,
                        "corr_dup": CORR_DUP, "max_terms": a.max_terms},
         "dropped": dropped, "final": rows},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print(f"저장: {OUT_JSON.relative_to(_PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
