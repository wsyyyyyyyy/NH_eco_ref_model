"""
======================================================================
확률 보정 3종 비교 — 하위 분위 PD 가 0 이 되는 문제의 원인 규명
======================================================================
D6m 의 하위 6분위 예측 PD 가 0.0000%, 월별 건수 오차 −51.6% → −66% 였다.
포털이 PD 를 화면에 표시하므로 그대로 쓸 수 없다. **원인을 가른다.**

두 가설
------
  (H1) 구간 기저율 차이
       Platt 을 Train(기저율 0.9116%)에서 적합해 Valid(1.2269%)에 적용한다.
       절편이 낮은 기저율에 맞춰져 있어 **구조적으로 과소추정**한다.
       -> 이 경우 Dev(1.2424%)에서 적합한 `platt_dev` 는 수준이 맞아야 한다.

  (H2) Platt 자체의 극단 압축
       R2 규제(num_leaves=7, reg_alpha=5, reg_lambda=5)로 트리 확률이 수축돼
       로짓 범위가 좁고, 거기에 로지스틱을 한 번 더 씌워 하위가 0 으로 뭉갠다.
       -> 이 경우 `platt_dev` 도 하위가 0 이고, 해석적 역보정만 살아난다.

  `prior` = scale_pos_weight 역보정. 가중 학습이 부풀린 양성 오즈를 되돌린다
      odds_corr = odds / spw          (= 로그오즈에서 ln(spw) 차감)
      p_corr    = p / (p + (1-p)·spw)
  적합 파라미터가 없어 과적합이 불가능하다. spw=108.70 을 썼으므로 예측 오즈가
  그만큼 부풀려져 있고, 이를 역보정하면 절대 수준이 맞을 수 있다.

★ 재학습하지 않는다. `step34_d_axis` 가 네 방식 전부를 이미 저장한다.

★ Z-Score 등급 컷오프는 **로그오즈 기준이므로 보정과 무관**하다.
  보정은 모두 로짓의 단조 변환이라 순위를 바꾸지 않는다.
  포털에 **표시하는 PD** 만 보정된 값을 써야 한다. 이 구분을 혼동하지 말 것.

Usage
-----
    python -m eda_pipeline.step36_calibration_compare
    python -m eda_pipeline.step36_calibration_compare --scenario D6m
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
METHODS = ["raw", "prior", "platt_train", "platt_dev"]
ZERO_EPS = 5e-7          # 0.00005% 미만이면 "화면에 0 으로 보인다" 로 본다


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default="D6m")
    a = ap.parse_args()

    rows = [r for r in json.loads(SRC.read_text(encoding="utf-8"))
            if r["scenario"] == a.scenario]
    if not rows:
        raise SystemExit(f"{a.scenario} 결과가 없다")
    rows.sort(key=lambda r: r["seed"])
    seeds = [r["seed"] for r in rows]
    actual = rows[0]["calibration"]["actual_rate_valid"]
    spw = rows[0]["calibration"]["spw_used"]
    rate_tr = rows[0]["pos_train"] / rows[0]["n_train"]
    rate_dv = rows[0]["pos_dev"] / rows[0]["n_dev"]

    print("=" * 100)
    print(f"확률 보정 3종 비교 — [{a.scenario}] 시드 {len(seeds)}회")
    print("=" * 100)
    print(f"  기저율   Train {rate_tr * 100:.4f}%  /  Dev {rate_dv * 100:.4f}%  "
          f"/  Valid(실제) {actual * 100:.4f}%")
    print(f"  scale_pos_weight = {spw}   (ln(spw) = {np.log(spw):.4f})")

    def agg(method: str, path: list[str]) -> tuple[float, float]:
        vals = []
        for r in rows:
            v = r["calibration"]
            for k in path:
                v = v[method] if k == "@m" else v[k]
            vals.append(float(v))
        return float(np.mean(vals)), (st.stdev(vals) if len(vals) > 1 else 0.0)

    print()
    print("=" * 100)
    print("1) 절대 수준 — 보정 후 평균 PD 가 실제 부도율에 얼마나 가까운가")
    print("=" * 100)
    print(f"  {'보정':13s} {'평균PD%':>10s} {'σ':>8s} {'실제 대비':>10s} "
          f"{'배수':>7s}  판정")
    lvl = {}
    for m in METHODS:
        mean, sd = agg(m, ["mean_pd", "@m"])
        ratio = mean / actual
        lvl[m] = {"mean_pd": mean, "sd": sd, "ratio_vs_actual": ratio}
        if 0.8 <= ratio <= 1.25:
            v = "수준 일치"
        elif ratio < 0.8:
            v = f"과소추정 ({(1 - ratio) * 100:.0f}% 낮다)"
        else:
            v = f"과대추정 ({(ratio - 1) * 100:.0f}% 높다)"
        print(f"  {m:13s} {mean * 100:10.4f} {sd * 100:8.4f} "
              f"{(mean - actual) * 100:+10.4f} {ratio:7.3f}  {v}")

    print()
    print("=" * 100)
    print("2) 월별 건수 MAPE / PD-부도율 상관 / Brier / ECE")
    print("=" * 100)
    print(f"  {'보정':13s} {'MAPE%':>9s} {'σ':>7s} {'상관':>9s} "
          f"{'Brier':>10s} {'ECE':>10s}")
    for m in METHODS:
        mape, mape_sd = agg(m, ["@m", "count_mape_pct"])
        corr, _ = agg(m, ["@m", "corr_pd_rate"])
        br, _ = agg(m, ["@m", "brier"])
        ece, _ = agg(m, ["@m", "ece"])
        lvl[m].update({"count_mape_pct": mape, "count_mape_sd": mape_sd,
                       "corr_pd_rate": corr, "brier": br, "ece": ece})
        print(f"  {m:13s} {mape:9.2f} {mape_sd:7.2f} {corr:+9.4f} "
              f"{br:10.6f} {ece:10.6f}")

    print()
    print("=" * 100)
    print("3) ★ 하위 분위 PD 가 0 인가 — 화면 표시 가능성의 핵심")
    print("=" * 100)
    print(f"  {'보정':13s} {'0 인 분위 수':>12s}  분위별 예측 평균 PD% (1→10, 시드 평균)")
    for m in METHODS:
        n_bins = min(len(r["calibration"][m]["deciles"]) for r in rows)
        pm = [float(np.mean([r["calibration"][m]["deciles"][i]["pred_mean"]
                             for r in rows])) for i in range(n_bins)]
        n_zero = sum(1 for v in pm if v < ZERO_EPS)
        lvl[m]["decile_pred_mean"] = pm
        lvl[m]["n_decile_below_eps"] = n_zero
        cells = " ".join(f"{v * 100:7.4f}" for v in pm)
        print(f"  {m:13s} {n_zero:12d}  {cells}")
    print()
    print(f"  · 기준: 예측 PD < {ZERO_EPS * 100:.5f}% 면 화면에서 0.0000% 로 보인다")

    # ── 원인 판정 ────────────────────────────────────────────
    print()
    print("=" * 100)
    print("4) 원인 판정")
    print("=" * 100)
    pt, pd_, pr = lvl["platt_train"], lvl["platt_dev"], lvl["prior"]
    print(f"  platt_train  평균PD {pt['mean_pd'] * 100:.4f}%  "
          f"0 분위 {pt['n_decile_below_eps']}개")
    print(f"  platt_dev    평균PD {pd_['mean_pd'] * 100:.4f}%  "
          f"0 분위 {pd_['n_decile_below_eps']}개")
    print(f"  prior        평균PD {pr['mean_pd'] * 100:.4f}%  "
          f"0 분위 {pr['n_decile_below_eps']}개")
    print()
    if pd_["n_decile_below_eps"] < pt["n_decile_below_eps"] - 1:
        verdict = ("H1 우세 — 구간 기저율 차이가 주된 원인이다. Dev 적합으로 "
                   "옮기면 하위 분위의 0 문제가 완화된다.")
    elif pd_["n_decile_below_eps"] >= pt["n_decile_below_eps"]:
        verdict = ("H2 우세 — Platt 자체가 확률을 극단 압축한다. 적합 구간을 "
                   "바꿔도 하위 분위는 0 으로 남는다.")
    else:
        verdict = "두 원인이 섞여 있다 — 어느 쪽도 단독 설명이 되지 않는다."
    print(f"  판정: {verdict}")
    if pr["n_decile_below_eps"] == 0:
        print("  ★ prior(해석적 역보정)는 하위 분위에서도 0 이 아니다. "
              "화면 표시용으로 쓸 수 있다.")
    best_level = min(METHODS, key=lambda m: abs(lvl[m]["ratio_vs_actual"] - 1))
    best_mape = min(METHODS, key=lambda m: lvl[m]["count_mape_pct"])
    print(f"  절대 수준이 실제에 가장 가까운 보정: **{best_level}** "
          f"(배수 {lvl[best_level]['ratio_vs_actual']:.3f})")
    print(f"  월별 건수 MAPE 가 가장 낮은 보정: **{best_mape}** "
          f"({lvl[best_mape]['count_mape_pct']:.2f}%)")
    print()
    print("  ※ 네 보정은 모두 로짓의 단조 변환이므로 **순위·AUC·등급 컷오프는")
    print("    동일하다.** Z-Score 등급은 로그오즈 기준이라 보정과 무관하다.")
    print("    보정이 바꾸는 것은 **화면에 표시하는 PD 값**뿐이다.")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fp = OUT_DIR / f"calibration_compare_{a.scenario}.json"
    fp.write_text(json.dumps(
        {"scenario": a.scenario, "seeds": seeds, "spw": spw,
         "rate_train": rate_tr, "rate_dev": rate_dv, "rate_valid": actual,
         "zero_eps": ZERO_EPS, "methods": lvl, "verdict": verdict,
         "best_level": best_level, "best_mape": best_mape,
         "note": "step34 저장 원자료에서 산출. 재학습하지 않았다."},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print(f"저장: {fp.relative_to(_PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
