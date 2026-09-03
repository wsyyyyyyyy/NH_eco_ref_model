"""
======================================================================
STAGE 7 문서 작업용 산출물 — gain 표 · 캘리브레이션 · 구간 지표
======================================================================
04·05·06 문서가 직접 인용할 자료를 한 곳에서 뽑는다. 리포트 본문에 수치를
손으로 옮기지 않기 위한 스크립트다 — 하드코딩된 수치가 서술과 어긋나는 사고를
이미 여러 번 겪었다 (`docs/07_한계와_향후과제.md` §4-4).

산출
----
  1) gain 상위 15  — 시나리오별, 한글 라벨 병기 (`backend.feature_labels`)
  2) 구간별 부도율 · PSI · 조기중단 시점
  3) 캘리브레이션 (`--calibrate`) — 예측 PD 10분위별 실제 부도율 +
     월별 예측 평균 PD vs 실제 부도율. 학습을 1회 수행하므로 시간이 걸린다.

Usage
-----
    python -m eda_pipeline.step36_report_inputs
    python -m eda_pipeline.step36_report_inputs --scenarios C1 A0 A2 A3 A7
    python -m eda_pipeline.step36_report_inputs --calibrate C1 --seeds 42,7,2024
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import numpy as np

from eda_pipeline import config

RESULTS = config.ABLATION_DIR / "ablation_A_results_R2.json"
OUT_DIR = config.VALIDATION_DIR / "stage7_report_inputs"

#: 04 문서가 "누수가 사라진 자리를 무엇이 채웠나" 로 확인할 변수군
WATCH_PREFIX = ("OBV_",)
WATCH_EXACT = ("JEMU_118900", "JEMU_STALE_MONTHS", "roe_first_fy_YN")


def label_of(code: str) -> str:
    try:
        from backend.feature_labels import get_feature_label
        lab = get_feature_label(code)
    except Exception:                                             # noqa: BLE001
        return ""
    # 라벨이 없으면 코드를 그대로 돌려주는 구현이라 그 경우는 빈칸으로 둔다
    return "" if lab == code else lab


def load_results() -> dict:
    if not RESULTS.exists():
        raise FileNotFoundError(
            f"{RESULTS} 없음. 먼저 실행:\n"
            f"  python -m eda_pipeline.step30_stage6_ablation --run-all")
    return {r["scenario"]: r
            for r in json.loads(RESULTS.read_text(encoding="utf-8"))}


# ══════════════════════════════════════════════════════════════════════
# 1) gain 상위 15
# ══════════════════════════════════════════════════════════════════════

def print_gain(rs: dict, scenarios: list[str]) -> dict:
    dump: dict[str, list] = {}
    for sc in scenarios:
        r = rs.get(sc)
        if r is None:
            print(f"\n[{sc}] 결과에 없음 — 건너뜀")
            continue
        top = r.get("gain_top15") or r.get("gain_top20") or []
        rows = [{"rank": i + 1, "feature": e["feature"],
                 "gain_pct": e["gain_pct"], "label": label_of(e["feature"])}
                for i, e in enumerate(top[:15])]
        dump[sc] = rows
        print()
        print("=" * 92)
        print(f"[{sc}] {r.get('desc', '')}")
        print(f"  피처 {r['n_features']} / Valid AUC {r['valid']['auc']:.4f} / "
              f"best_iter {r['best_iteration']:,}")
        print("=" * 92)
        print(f"  {'순위':>4s} {'변수':34s} {'gain%':>8s}  한글 라벨")
        for e in rows:
            print(f"  {e['rank']:4d} {e['feature']:34s} {e['gain_pct']:8.3f}  {e['label']}")
        # 관심 변수가 상위 15 안에 있는지
        names = {e["feature"] for e in rows}
        hit = sorted(n for n in names
                     if n.startswith(WATCH_PREFIX) or n in WATCH_EXACT)
        miss = [n for n in WATCH_EXACT if n not in names]
        print(f"  · 관심 변수 상위 15 진입: {hit if hit else '없음'}")
        print(f"  · 상위 15 밖: {miss if miss else '없음'}")
    return dump


# ══════════════════════════════════════════════════════════════════════
# 2) 구간별 부도율 · PSI
# ══════════════════════════════════════════════════════════════════════

def print_splits(rs: dict, scenarios: list[str]) -> dict:
    print()
    print("=" * 92)
    print("구간별 부도율 · PSI · 조기중단 — 확정판(R2) 복원 원자료 기준")
    print("=" * 92)
    print(f"  {'ID':5s} {'Train n':>9s} {'Train%':>8s} {'Dev n':>8s} {'Dev%':>8s} "
          f"{'Valid n':>9s} {'Valid%':>8s} {'PSI':>7s} {'best_it':>8s}")
    out = {}
    for sc in scenarios:
        r = rs.get(sc)
        if r is None:
            continue
        out[sc] = {
            "n_train": r["n_train"], "n_dev": r["n_dev"], "n_valid": r["n_valid"],
            "pos_train": r["pos_train"], "pos_dev": r["pos_dev"],
            "pos_valid": r["pos_valid"],
            "rate_train_pct": r["rate_train"] * 100,
            "rate_dev_pct": r["rate_dev"] * 100,
            "rate_valid_pct": r["rate_valid"] * 100,
            "psi_train_valid": r["psi_train_valid"],
            "best_iteration": r["best_iteration"],
            "scale_pos_weight": r["scale_pos_weight"],
        }
        print(f"  {sc:5s} {r['n_train']:9,d} {r['rate_train']*100:8.4f} "
              f"{r['n_dev']:8,d} {r['rate_dev']*100:8.4f} "
              f"{r['n_valid']:9,d} {r['rate_valid']*100:8.4f} "
              f"{r['psi_train_valid']:7.4f} {r['best_iteration']:8,d}")
    print()
    print("  · 부도율은 12개월 선행 타겟(IS_BUDO_12M) 기준이다.")
    print("  · Dev(202310~202312)는 SPLIT=='TRAIN' 내부이며 조기중단에만 쓴다.")
    print("  · PSI 는 Train 예측분포 대비 Valid 예측분포다 (0.1 미만이면 안정).")
    return out


# ══════════════════════════════════════════════════════════════════════
# 3) 캘리브레이션 — 학습 1회 필요
# ══════════════════════════════════════════════════════════════════════

def run_calibration(scenario: str, seeds: list[int]) -> dict:
    """지정 시나리오를 학습해 10분위·월별 캘리브레이션을 낸다."""
    from eda_pipeline import split_spec
    from eda_pipeline import step30_stage6_ablation as ab
    from eda_pipeline.step34_d_axis import (
        _logit, brier, decile_calibration, fit_platt, monthly_calibration,
        prior_correction,
    )

    a0, info, addable = ab.base_feature_pool()
    df = ab.load_base(a0, addable)
    feats = ab.resolve_features(scenario, a0, list(df.columns))
    ym = df["BASE_YM"].astype(str)
    tr = ym < split_spec.DEV_START
    dv = (ym >= split_spec.DEV_START) & (ym <= split_spec.DEV_END)
    va = ym >= split_spec.VALID_START
    y = df[ab.TARGET].astype(int)
    ytr, ydv, yva = y[tr].values, y[dv].values, y[va].values

    import lightgbm as lgb
    per_seed = []
    for sd in seeds:
        prm = ab.active_params()
        prm["random_state"] = sd
        n_pos = int(ytr.sum())
        spw = (len(ytr) - n_pos) / max(n_pos, 1)
        m = lgb.LGBMClassifier(scale_pos_weight=spw, **prm)
        m.fit(df.loc[tr, feats], ytr,
              eval_set=[(df.loc[dv, feats], ydv)], eval_metric="auc",
              callbacks=[lgb.early_stopping(ab.EARLY_STOPPING_ROUNDS, verbose=False)])
        p_tr = m.predict_proba(df.loc[tr, feats])[:, 1]
        p_va = m.predict_proba(df.loc[va, feats])[:, 1]
        platt = fit_platt(_logit(p_tr), ytr)
        pc = platt.predict_proba(_logit(p_va).reshape(-1, 1))[:, 1]
        per_seed.append({
            "seed": sd,
            "best_iteration": int(m.best_iteration_ or prm["n_estimators"]),
            "valid": ab.evaluate(yva, p_va),
            "mean_pd_platt_train": float(pc.mean()),
            "actual_rate_valid": float(yva.mean()),
            "brier": brier(yva, pc),
            **decile_calibration(yva, pc),
            **monthly_calibration(ym[va], yva, pc),
        })
        print(f"  [{scenario} seed={sd}] Valid AUC {per_seed[-1]['valid']['auc']:.4f} "
              f"/ 평균PD {pc.mean()*100:.4f}% / 실제 {yva.mean()*100:.4f}% "
              f"/ best_iter {per_seed[-1]['best_iteration']:,}")

    # 시드 평균 10분위
    n_bins = min(len(s["deciles"]) for s in per_seed)
    dec_mean = []
    for i in range(n_bins):
        pm = float(np.mean([s["deciles"][i]["pred_mean"] for s in per_seed]))
        am = float(np.mean([s["deciles"][i]["actual_rate"] for s in per_seed]))
        dec_mean.append({"decile": i + 1, "pred_mean": pm, "actual_rate": am,
                         "gap": am - pm})
    # 시드 평균 월별
    months = [m["ym"] for m in per_seed[0]["monthly"]]
    mon_mean = []
    for j, mm in enumerate(months):
        mon_mean.append({
            "ym": mm,
            "n": per_seed[0]["monthly"][j]["n"],
            "actual_cnt": per_seed[0]["monthly"][j]["actual_cnt"],
            "actual_rate": per_seed[0]["monthly"][j]["actual_rate"],
            "pred_mean_pd": float(np.mean([s["monthly"][j]["pred_mean_pd"]
                                           for s in per_seed])),
            "pred_cnt": float(np.mean([s["monthly"][j]["pred_cnt"]
                                       for s in per_seed])),
        })

    print()
    print("=" * 92)
    print(f"[{scenario}] 예측 PD 10분위별 실제 부도율 (시드 {len(seeds)}회 평균, platt_train)")
    print("=" * 92)
    print(f"  {'분위':>4s} {'예측 평균 PD%':>13s} {'실제 부도율%':>13s} {'격차%p':>9s}")
    for d in dec_mean:
        print(f"  {d['decile']:4d} {d['pred_mean']*100:13.4f} "
              f"{d['actual_rate']*100:13.4f} {d['gap']*100:+9.4f}")
    print()
    print("=" * 92)
    print(f"[{scenario}] 월별 예측 평균 PD vs 실제 부도율 (Valid)")
    print("=" * 92)
    print(f"  {'BASE_YM':8s} {'행수':>8s} {'실제건수':>8s} {'실제%':>8s} "
          f"{'예측PD%':>8s} {'예측건수':>9s} {'오차%':>8s}")
    for m in mon_mean:
        err = ((m["pred_cnt"] - m["actual_cnt"]) / m["actual_cnt"] * 100
               if m["actual_cnt"] else float("nan"))
        print(f"  {m['ym']:8s} {m['n']:8,d} {m['actual_cnt']:8,d} "
              f"{m['actual_rate']*100:8.4f} {m['pred_mean_pd']*100:8.4f} "
              f"{m['pred_cnt']:9.1f} {err:+8.1f}")
    return {"scenario": scenario, "seeds": seeds,
            "per_seed": per_seed, "decile_mean": dec_mean, "monthly_mean": mon_mean}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenarios", nargs="*",
                    default=["C1", "A0", "A2", "A3", "A7", "A0c"])
    ap.add_argument("--calibrate", default=None,
                    help="이 시나리오를 학습해 캘리브레이션을 산출한다 (예: C1)")
    ap.add_argument("--seeds", default="42,7,2024")
    a = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rs = load_results()

    gain = print_gain(rs, a.scenarios)
    splits = print_splits(rs, a.scenarios)
    (OUT_DIR / "gain_top15_labeled.json").write_text(
        json.dumps(gain, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT_DIR / "split_metrics.json").write_text(
        json.dumps(splits, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print(f"저장: {(OUT_DIR / 'gain_top15_labeled.json').relative_to(_PROJECT_ROOT)}")
    print(f"저장: {(OUT_DIR / 'split_metrics.json').relative_to(_PROJECT_ROOT)}")

    if a.calibrate:
        seeds = [int(x) for x in a.seeds.split(",") if x.strip()]
        cal = run_calibration(a.calibrate, seeds)
        fp = OUT_DIR / f"calibration_{a.calibrate}.json"
        fp.write_text(json.dumps(cal, ensure_ascii=False, indent=2), encoding="utf-8")
        print()
        print(f"저장: {fp.relative_to(_PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
