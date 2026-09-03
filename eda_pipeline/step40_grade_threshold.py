"""
======================================================================
등급 체계 · 비용기반 임계값 재산출 — D8 Full 기준
======================================================================
기존 파라미터는 전부 무효다. 양성이 63,531 → 9,814 로 바뀌었고 피처 구성도 바뀌었다.
  기존 Z-Score  mu=-3.9652 / sigma=2.6536   -> 재산출
  기존 임계값    0.3797                      -> 재산출

산출 로직은 기존 스크립트를 그대로 따르고 **데이터만 갱신**한다.
  Z-Score      `step11_compare_internal` 과 동일 — Valid 로그오즈의 mu/sigma
  G1~G5        Z 컷오프 -1 / 0 / 1 / 2 (동일)
  16단계 등급  `backend/grade_mapping.py` 와 동일 — 예측 PD 분위 컷오프

★ 등급은 **로그오즈 기준**이므로 확률 보정과 무관하다. 네 보정은 모두 로짓의
  단조 변환이라 Z-Score 순위와 컷오프가 바뀌지 않는다. 보정이 바꾸는 것은
  화면에 표시하는 PD 값뿐이다.

★ 기존 파일을 덮어쓰지 않는다. `_v2` 접미사로 신규 생성한다.

Usage
-----
    python -m eda_pipeline.step40_grade_threshold
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import numpy as np
import pandas as pd

from eda_pipeline import config, split_spec

OUT_GRADE = config.OUTPUT_DIR / "grade_mapping_v2.json"
OUT_THRESH = config.OUTPUT_DIR / "threshold_v2.json"
SCORES = config.OUTPUT_DIR / "d8_valid_scores.parquet"

TARGET = "IS_BUDO_12M"
EPS = 1e-15

#: G1~G5 Z 컷오프 — 기존 방식 유지 (step11_compare_internal)
Z_CUTOFFS = [-1.0, 0.0, 1.0, 2.0]
G_LABELS = ["G1", "G2", "G3", "G4", "G5"]

#: 16단계 등급 라벨 — 기존 backend/grade_mapping.py 와 동일
GRADE_LABELS_16 = [
    "AAA", "AA+", "AA0", "AA-", "A+", "A0", "A-",
    "BBB+", "BBB0", "BBB-", "BB+", "BB0", "BB-", "B+", "B0", "CCC",
]
#: 기존과 같은 분위 지점 (40th ~ 99.9th)
Q16 = [0.40, 0.50, 0.575, 0.65, 0.715, 0.77, 0.82,
       0.865, 0.90, 0.928, 0.95, 0.967, 0.98, 0.989, 0.996]

COST_RATIOS = [5, 10, 20]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("grade")


# ══════════════════════════════════════════════════════════════════════

def build_scores() -> pd.DataFrame:
    """D8 Full 모델로 Valid 구간을 채점한다 (시드 42 모델 파일 재사용)."""
    if SCORES.exists():
        import duckdb
        log.info("기존 점수 재사용: %s", SCORES.name)
        return duckdb.connect().execute(
            f"SELECT * FROM read_parquet('{SCORES.as_posix()}')").df()

    import lightgbm as lgb
    from eda_pipeline.step38_production_retrain import load_d8_frame

    model_path = config.OUTPUT_DIR / "lgbm_v2_full.txt"
    if not model_path.exists():
        raise FileNotFoundError(
            f"{model_path} 없음. 먼저 실행:\n"
            f"  python -m eda_pipeline.step38_production_retrain")
    log.info("모델 로딩: %s", model_path.name)
    booster = config.load_booster(model_path)

    df, feats, _ = load_d8_frame()
    order = list(booster.feature_name())
    missing = [c for c in order if c not in df.columns]
    assert not missing, f"모델 피처가 패널에 없다: {missing[:5]}"
    va = df["BASE_YM"] >= split_spec.VALID_START
    log.info("Valid 채점 %s행 / 피처 %d", f"{int(va.sum()):,}", len(order))
    p = booster.predict(df.loc[va, order])
    out = pd.DataFrame({
        "V_BZNO": df.loc[va, "V_BZNO"].astype(str).values,
        "BASE_YM": df.loc[va, "BASE_YM"].astype(str).values,
        TARGET: df.loc[va, TARGET].astype(int).values,
        "PRED_PROB": np.asarray(p, dtype=float),
    })
    out["LOG_ODDS"] = np.log(out["PRED_PROB"] / (1 - out["PRED_PROB"] + EPS))
    import duckdb
    con = duckdb.connect()
    try:
        con.register("t", out)
        con.execute(f"COPY t TO '{SCORES.as_posix()}' (FORMAT PARQUET)")
    finally:
        con.close()
    log.info("저장: %s", SCORES.name)
    return out


# ══════════════════════════════════════════════════════════════════════
# 2-1 Z-Score · 등급
# ══════════════════════════════════════════════════════════════════════

def grade_table(df: pd.DataFrame, col: str, labels: list[str]) -> pd.DataFrame:
    g = df.groupby(col, observed=True).agg(
        n=(TARGET, "size"), n_budo=(TARGET, "sum"))
    g["rate_pct"] = g["n_budo"] / g["n"] * 100
    base = df[TARGET].mean() * 100
    g["lift"] = g["rate_pct"] / base
    g = g.reindex([l for l in labels if l in g.index])
    return g


def recompute_grades(df: pd.DataFrame) -> dict:
    mu = float(df["LOG_ODDS"].mean())
    sd = float(df["LOG_ODDS"].std())
    df["Z_SCORE"] = (df["LOG_ODDS"] - mu) / sd
    log.info("[2-1] Z-Score 재산출 — mu=%.4f / sigma=%.4f "
             "(기존 mu=-3.9652 / sigma=2.6536 은 무효)", mu, sd)

    cuts = list(Z_CUTOFFS)
    adjusted, adj_note = False, ""
    for attempt in range(4):
        df["GRADE"] = pd.cut(df["Z_SCORE"],
                             bins=[-np.inf] + cuts + [np.inf],
                             labels=G_LABELS, right=True)
        t = grade_table(df, "GRADE", G_LABELS)
        rates = t["rate_pct"].tolist()
        mono = all(rates[i] <= rates[i + 1] for i in range(len(rates) - 1))
        if mono:
            break
        # 단조성이 깨지면 컷오프를 Z 분위로 대체한다 (등폭 -> 등빈도)
        adjusted = True
        qs = [0.20, 0.50, 0.80, 0.95]
        cuts = [float(df["Z_SCORE"].quantile(q)) for q in qs]
        adj_note = (f"등폭 컷오프({Z_CUTOFFS})에서 등급별 부도율 단조성이 깨져 "
                    f"Z 분위 {qs} 기준으로 대체했다 -> {[round(c, 4) for c in cuts]}")
        log.warning("  ★ 단조성 실패 — 컷오프를 조정한다: %s", adj_note)
    else:
        raise SystemExit(
            "중단 조건 2: 등급별 부도율 단조성이 컷오프 조정으로도 확보되지 않았다")

    log.info("  G1~G5 컷오프 %s%s", [round(c, 4) for c in cuts],
             " (조정됨)" if adjusted else " (기존 방식 유지)")
    log.info("  %-4s %10s %8s %9s %8s", "등급", "관측치", "부도건수", "부도율%", "Lift")
    for gname, r in t.iterrows():
        log.info("  %-4s %10s %8s %9.4f %8.2f", gname, f"{int(r.n):,}",
                 f"{int(r.n_budo):,}", r.rate_pct, r.lift)
    log.info("  단조성: %s", "확보" if mono else "실패")

    # 16단계 — 예측 PD 분위 (기존 방식)
    p16 = [float(df["PRED_PROB"].quantile(q)) for q in Q16]
    df["GRADE16"] = pd.cut(df["PRED_PROB"], bins=[-np.inf] + p16 + [np.inf],
                           labels=GRADE_LABELS_16, right=True)
    t16 = grade_table(df, "GRADE16", GRADE_LABELS_16)
    r16 = t16["rate_pct"].tolist()
    mono16 = all(r16[i] <= r16[i + 1] for i in range(len(r16) - 1))
    log.info("")
    log.info("  16단계 등급 (예측 PD 분위) — 단조성 %s",
             "확보" if mono16 else "★ 일부 구간 비단조")
    for gname, r in t16.iterrows():
        log.info("    %-5s %9s %7s %9.4f%%  lift %6.2f", gname,
                 f"{int(r.n):,}", f"{int(r.n_budo):,}", r.rate_pct, r.lift)

    return {
        "z_mu": mu, "z_sigma": sd,
        "z_cutoffs": cuts, "z_cutoffs_original": Z_CUTOFFS,
        "z_cutoffs_adjusted": adjusted, "adjust_note": adj_note,
        "grade_labels": G_LABELS,
        "monotone_g5": bool(mono),
        "grade_table": [
            {"grade": str(g), "n": int(r.n), "n_budo": int(r.n_budo),
             "rate_pct": float(r.rate_pct), "lift": float(r.lift)}
            for g, r in t.iterrows()],
        "grade16_labels": GRADE_LABELS_16,
        "grade16_quantiles": Q16,
        "grade16_prob_cutoffs": p16,
        "monotone_g16": bool(mono16),
        "grade16_table": [
            {"grade": str(g), "n": int(r.n), "n_budo": int(r.n_budo),
             "rate_pct": float(r.rate_pct), "lift": float(r.lift)}
            for g, r in t16.iterrows()],
        "note": ("등급은 로그오즈 기준이므로 확률 보정과 무관하다. "
                 "네 보정은 모두 로짓의 단조 변환이다."),
    }


# ══════════════════════════════════════════════════════════════════════
# 2-2 비용기반 임계값
# ══════════════════════════════════════════════════════════════════════

def recompute_thresholds(df: pd.DataFrame) -> dict:
    y = df[TARGET].values.astype(int)
    p = df["PRED_PROB"].values
    grid = np.unique(np.quantile(p, np.linspace(0.50, 0.9999, 2000)))
    n_pos = int(y.sum())

    def metrics(th: float) -> dict:
        pred = p >= th
        tp = int((pred & (y == 1)).sum())
        fp = int((pred & (y == 0)).sum())
        fn = n_pos - tp
        prec = tp / max(tp + fp, 1)
        rec = tp / max(n_pos, 1)
        f2 = (5 * prec * rec / (4 * prec + rec)) if (prec + rec) > 0 else 0.0
        return {"threshold": float(th), "tp": tp, "fp": fp, "fn": fn,
                "precision": prec, "recall": rec, "f2": f2,
                "n_alert": int(pred.sum()),
                "alert_rate_pct": float(pred.mean() * 100)}

    log.info("[2-2] 비용기반 임계값 재산출 (기존 0.3797 은 무효)")
    rows = [metrics(t) for t in grid]

    best_f2 = max(rows, key=lambda r: r["f2"])
    out = {"n_valid": int(len(y)), "n_pos": n_pos,
           "base_rate_pct": float(y.mean() * 100),
           "f2_optimal": best_f2, "cost_optimal": {}}
    log.info("  F2 최적  th=%.6f  P=%.4f R=%.4f F2=%.4f  "
             "포착 %s/%s  경보 %s (%.2f%%)",
             best_f2["threshold"], best_f2["precision"], best_f2["recall"],
             best_f2["f2"], f"{best_f2['tp']:,}", f"{n_pos:,}",
             f"{best_f2['n_alert']:,}", best_f2["alert_rate_pct"])

    for ratio in COST_RATIOS:
        # 총비용 = ratio * FN + 1 * FP  -> 최소화
        best = min(rows, key=lambda r: ratio * r["fn"] + r["fp"])
        best = dict(best)
        best["cost_ratio"] = ratio
        best["total_cost"] = ratio * best["fn"] + best["fp"]
        out["cost_optimal"][str(ratio)] = best
        log.info("  미탐:오탐 %2d:1  th=%.6f  P=%.4f R=%.4f  "
                 "포착 %s/%s  경보 %s (%.2f%%)  총비용 %s",
                 ratio, best["threshold"], best["precision"], best["recall"],
                 f"{best['tp']:,}", f"{n_pos:,}", f"{best['n_alert']:,}",
                 best["alert_rate_pct"], f"{best['total_cost']:,}")
    out["note"] = ("임계값은 raw 예측 확률 기준이다. 확률 보정을 적용하면 "
                   "임계값도 같은 변환을 거쳐야 한다 — 보정은 단조 변환이라 "
                   "포착/경보 건수는 동일하다.")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.parse_args()

    df = build_scores()
    log.info("Valid %s행 / 양성 %s (%.4f%%)", f"{len(df):,}",
             f"{int(df[TARGET].sum()):,}", df[TARGET].mean() * 100)

    g = recompute_grades(df)
    t = recompute_thresholds(df)

    for p, payload, label in ((OUT_GRADE, g, "등급"),
                              (OUT_THRESH, t, "임계값")):
        if p.exists():
            log.warning("  %s 가 이미 있다 — 덮어쓴다 (v2 신규 파일이므로 허용)",
                        p.name)
        p.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                     encoding="utf-8")
        log.info("저장(%s): %s", label, p.relative_to(_PROJECT_ROOT))


if __name__ == "__main__":
    main()
