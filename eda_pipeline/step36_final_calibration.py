"""
======================================================================
최종 구성(D6m) 캘리브레이션 자료 — 05·06 문서 그림 근거
======================================================================
★ 재학습하지 않는다. `step34_d_axis` 가 시나리오·시드별로 10분위 캘리브레이션과
  월별 예측 PD 를 이미 `d_axis_results.json` 에 저장한다. 같은 것을 다시 학습하면
  같은 값이 나오고 시간만 든다 — 저장된 원자료에서 시드 평균만 낸다.

산출
----
  1) 예측 PD 10분위별 실제 부도율 (캘리브레이션 곡선용)
  2) 월별 예측 평균 PD vs 실제 부도율 (시계열 그래프용)
  3) 시드별 요약 (평균 PD · AUC · best_iteration)

Usage
-----
    python -m eda_pipeline.step36_final_calibration
    python -m eda_pipeline.step36_final_calibration --scenario D6m --calib platt_train
"""

from __future__ import annotations

import argparse
import json
import statistics as st
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import numpy as np

from eda_pipeline import config

SRC = config.VALIDATION_DIR / "d_axis" / "d_axis_results.json"
OUT_DIR = config.VALIDATION_DIR / "stage7_report_inputs"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default="D6m")
    ap.add_argument("--calib", default="platt_train",
                    choices=["raw", "prior", "platt_train", "platt_dev"])
    a = ap.parse_args()

    if not SRC.exists():
        raise FileNotFoundError(f"{SRC} 없음. step34_d_axis 를 먼저 실행할 것")
    rows = [r for r in json.loads(SRC.read_text(encoding="utf-8"))
            if r["scenario"] == a.scenario]
    if not rows:
        raise SystemExit(f"{a.scenario} 결과가 없다")
    rows.sort(key=lambda r: r["seed"])
    seeds = [r["seed"] for r in rows]
    actual = rows[0]["calibration"]["actual_rate_valid"]

    print("=" * 96)
    print(f"최종 구성 [{a.scenario}] 캘리브레이션 — 보정 {a.calib} / 시드 {len(seeds)}회")
    print(f"  시드: {seeds}")
    print(f"  Valid 실제 부도율 {actual * 100:.4f}%")
    print("=" * 96)

    # ── 시드별 요약 ──────────────────────────────────────────
    print()
    print(f"  {'시드':>6s} {'ValidAUC':>9s} {'평균PD%':>9s} {'상관':>9s} "
          f"{'MAPE%':>8s} {'Brier':>10s} {'ECE':>10s} {'best_it':>8s}")
    per_seed = []
    for r in rows:
        c = r["calibration"][a.calib]
        mp = r["calibration"]["mean_pd"][a.calib]
        per_seed.append({
            "seed": r["seed"], "valid_auc": r["valid"]["auc"],
            "mean_pd_pct": mp * 100, "corr_pd_rate": c["corr_pd_rate"],
            "count_mape_pct": c["count_mape_pct"], "brier": c["brier"],
            "ece": c["ece"], "best_iteration": r["best_iteration"],
        })
        print(f"  {r['seed']:6d} {r['valid']['auc']:9.4f} {mp * 100:9.4f} "
              f"{c['corr_pd_rate']:+9.4f} {c['count_mape_pct']:8.2f} "
              f"{c['brier']:10.6f} {c['ece']:10.6f} {r['best_iteration']:8,d}")

    # ── 10분위 (시드 평균) ───────────────────────────────────
    n_bins = min(len(r["calibration"][a.calib]["deciles"]) for r in rows)
    dec = []
    for i in range(n_bins):
        pm = [r["calibration"][a.calib]["deciles"][i]["pred_mean"] for r in rows]
        am = [r["calibration"][a.calib]["deciles"][i]["actual_rate"] for r in rows]
        nn = [r["calibration"][a.calib]["deciles"][i]["n"] for r in rows]
        dec.append({"decile": i + 1, "n_mean": float(np.mean(nn)),
                    "pred_mean": float(np.mean(pm)),
                    "pred_sd": float(st.stdev(pm)) if len(pm) > 1 else 0.0,
                    "actual_rate": float(np.mean(am)),
                    "actual_sd": float(st.stdev(am)) if len(am) > 1 else 0.0,
                    "gap": float(np.mean(am)) - float(np.mean(pm))})
    print()
    print("=" * 96)
    print(f"1) 예측 PD 10분위별 실제 부도율  (시드 {len(seeds)}회 평균)")
    print("=" * 96)
    print(f"  {'분위':>4s} {'행수':>9s} {'예측 평균PD%':>13s} {'실제 부도율%':>13s} "
          f"{'격차%p':>9s} {'실제 σ%p':>10s}")
    for d in dec:
        print(f"  {d['decile']:4d} {d['n_mean']:9,.0f} {d['pred_mean'] * 100:13.4f} "
              f"{d['actual_rate'] * 100:13.4f} {d['gap'] * 100:+9.4f} "
              f"{d['actual_sd'] * 100:10.4f}")
    mono = all(dec[i]["actual_rate"] <= dec[i + 1]["actual_rate"]
               for i in range(len(dec) - 1))
    print()
    print(f"  · 실제 부도율의 분위 단조성: {'단조 증가' if mono else '★ 비단조 구간 있음'}")
    print(f"  · 최상위 분위 실제 부도율 {dec[-1]['actual_rate'] * 100:.4f}% / "
          f"최하위 {dec[0]['actual_rate'] * 100:.4f}% "
          f"= {dec[-1]['actual_rate'] / max(dec[0]['actual_rate'], 1e-12):.1f}배")

    # ── 월별 (시드 평균) ────────────────────────────────────
    months = [m["ym"] for m in rows[0]["calibration"]["monthly"][a.calib]]
    mon = []
    for j, mm in enumerate(months):
        base = rows[0]["calibration"]["monthly"][a.calib][j]
        pm = [r["calibration"]["monthly"][a.calib][j]["pred_mean_pd"] for r in rows]
        pc = [r["calibration"]["monthly"][a.calib][j]["pred_cnt"] for r in rows]
        mon.append({"ym": mm, "n": base["n"], "actual_cnt": base["actual_cnt"],
                    "actual_rate": base["actual_rate"],
                    "pred_mean_pd": float(np.mean(pm)),
                    "pred_mean_pd_sd": float(st.stdev(pm)) if len(pm) > 1 else 0.0,
                    "pred_cnt": float(np.mean(pc))})
    print()
    print("=" * 96)
    print(f"2) 월별 예측 평균 PD vs 실제 부도율  (Valid, 시드 {len(seeds)}회 평균)")
    print("=" * 96)
    print(f"  {'BASE_YM':8s} {'행수':>8s} {'실제건수':>8s} {'실제%':>8s} "
          f"{'예측PD%':>8s} {'예측건수':>9s} {'건수오차%':>10s}")
    for m in mon:
        err = ((m["pred_cnt"] - m["actual_cnt"]) / m["actual_cnt"] * 100
               if m["actual_cnt"] else float("nan"))
        print(f"  {m['ym']:8s} {m['n']:8,d} {m['actual_cnt']:8,d} "
              f"{m['actual_rate'] * 100:8.4f} {m['pred_mean_pd'] * 100:8.4f} "
              f"{m['pred_cnt']:9.1f} {err:+10.1f}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fp = OUT_DIR / f"calibration_{a.scenario}.json"
    fp.write_text(json.dumps(
        {"scenario": a.scenario, "calib": a.calib, "seeds": seeds,
         "actual_rate_valid": actual, "per_seed": per_seed,
         "decile_mean": dec, "monthly_mean": mon,
         "note": ("step34_d_axis 가 저장한 원자료에서 시드 평균만 산출했다. "
                  "재학습하지 않았다.")},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print(f"저장: {fp.relative_to(_PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
