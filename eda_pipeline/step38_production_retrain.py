"""
======================================================================
프로덕션 모형 재학습 — D8 최종 구성
======================================================================
  Full        D8 구성 169 피처              -> lgbm_v2_full.txt
  Lean(gain)  gain 누적 95% 지점까지        -> lgbm_v2_lean.txt
  Lean(macro) 위 + 거시 14개 강제 포함      -> lgbm_v2_lean_macro.txt

★ Lean 을 두 버전 만드는 이유: 거시 14개는 gain 이 낮아(0.011~0.659%) 순수 gain
  기준 Lean 에서 잘려 나갈 수 있다. 그러면 "거시경제지표 참조 모형" 이라는 이름과
  어긋난다. 강제 포함본과 순수 gain 본의 AUC 차이를 실측해 비용을 밝힌다.

★ 기존 `lgbm_12m_model.txt` / `lgbm_12m_lean_model.txt` 는 **읽지도 쓰지도 않는다.**
  작업 전후 md5 를 로그에 남겨 불변을 증명한다 (`--verify-protected`).

★ 모델 저장은 반드시 `config.save_booster()` 를 쓴다. 프로젝트 경로에 한글이 있어
  LightGBM 의 C++ 파일 IO 가 직접 경로로는 실패한다.

Usage
-----
    python -m eda_pipeline.step38_production_retrain
    python -m eda_pipeline.step38_production_retrain --seeds 42,7,2024
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import statistics as st
import sys
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import duckdb
import lightgbm as lgb
import numpy as np
import pandas as pd

from eda_pipeline import config, split_spec
from eda_pipeline.step30_stage6_ablation import (
    EARLY_STOPPING_ROUNDS, calculate_ks, calculate_psi, evaluate,
)
from eda_pipeline.step34_d_axis import (
    SCENARIOS, active_params, add_e14_interactions, add_level_interaction,
    build_pools, macro_source_columns, monotone_vector, panel_path,
    resolve_features,
)
import eda_pipeline.step34_d_axis as d34

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("retrain")

TARGET = "IS_BUDO_12M"
OUT_DIR = config.OUTPUT_DIR
RESULT_JSON = config.VALIDATION_DIR / "step38_production_retrain.json"

PROTECTED = ["lgbm_12m_model.txt", "lgbm_12m_lean_model.txt"]
PROTECTED_MD5 = {
    "lgbm_12m_model.txt": "4e02cd3738dfae657da84edd906b9359",
    "lgbm_12m_lean_model.txt": "25d1cc5bfe091c4549fd78fe4549fec7",
}
LEAN_CUM_GAIN = 0.95           # gain 누적 95% 지점


def md5_of(p: Path) -> str:
    h = hashlib.md5()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def check_protected(tag: str) -> dict:
    out = {}
    for name in PROTECTED:
        p = OUT_DIR / name
        if not p.exists():
            out[name] = "(없음)"
            log.warning("  보호 파일 없음: %s", name)
            continue
        d = md5_of(p)
        out[name] = d
        ok = d == PROTECTED_MD5.get(name)
        log.info("  [%s] %s  md5=%s  %s", tag, name, d,
                 "기대값 일치" if ok else "★★ 기대값 불일치 — 중단 조건")
        if not ok:
            raise SystemExit(
                f"중단: 보호 파일 {name} 의 md5 가 기대값과 다르다.\n"
                f"  기대 {PROTECTED_MD5.get(name)}\n  실측 {d}")
    return out


# ══════════════════════════════════════════════════════════════════════

def load_d8_frame() -> tuple[pd.DataFrame, list[str], dict]:
    """D8 학습 프레임과 피처 목록·단조 벡터."""
    p = panel_path("real")
    macro_all = set(macro_source_columns())
    con = duckdb.connect()
    try:
        cols = con.execute(
            f"SELECT * FROM read_parquet('{p.as_posix()}') LIMIT 0").df().columns.tolist()
    finally:
        con.close()
    base, macro_reduced, info = build_pools(cols, macro_all)
    load_cols = sorted(set(base) | set(macro_reduced))
    log.info("패널 로딩 (%d컬럼)...", len(load_cols))
    df = d34.load_panel(p, load_cols)
    df = add_level_interaction(df)                     # D6 계열 재료 (미사용이나 무해)
    df, names, mono = add_e14_interactions(df)
    d34.E14_NAMES, d34.E14_MONO = names, mono
    feats = resolve_features("D8", base, macro_reduced, [])
    missing = [c for c in feats if c not in df.columns]
    assert not missing, f"패널에 없는 피처 {missing[:10]}"
    log.info("  D8 피처 %d개 / 거시 상호작용 %d개", len(feats), len(names))
    return df, feats, {"e14": names, "mono": mono, "info": info}


def fit_one(df: pd.DataFrame, feats: list[str], seed: int,
            mono: list[int] | None, tag: str, save_path: Path | None):
    prm = active_params(seed)
    if mono is not None:
        prm["monotone_constraints"] = mono
    ym = df["BASE_YM"]
    tr = ym < split_spec.DEV_START
    dv = (ym >= split_spec.DEV_START) & (ym <= split_spec.DEV_END)
    va = ym >= split_spec.VALID_START
    y = df[TARGET].astype(int)
    ytr, ydv, yva = y[tr].values, y[dv].values, y[va].values
    n_pos = int(ytr.sum())
    spw = (len(ytr) - n_pos) / max(n_pos, 1)

    t0 = time.time()
    m = lgb.LGBMClassifier(scale_pos_weight=spw, **prm)
    m.fit(df.loc[tr, feats], ytr, eval_set=[(df.loc[dv, feats], ydv)],
          eval_metric="auc",
          callbacks=[lgb.early_stopping(EARLY_STOPPING_ROUNDS, verbose=False)])
    p_tr = m.predict_proba(df.loc[tr, feats])[:, 1]
    p_va = m.predict_proba(df.loc[va, feats])[:, 1]
    res = {
        "tag": tag, "seed": seed, "n_features": len(feats),
        "best_iteration": int(m.best_iteration_ or prm["n_estimators"]),
        "scale_pos_weight": round(spw, 4),
        "train": evaluate(ytr, p_tr),
        "dev": evaluate(ydv, m.predict_proba(df.loc[dv, feats])[:, 1]),
        "valid": evaluate(yva, p_va),
        "psi_train_valid": calculate_psi(p_tr, p_va),
        "elapsed_sec": round(time.time() - t0, 1),
    }
    log.info("  [%s seed=%d] 피처 %d / Valid AUC %.4f / KS %.4f / PSI %.4f / "
             "best_iter %d (%.0fs)", tag, seed, len(feats), res["valid"]["auc"],
             res["valid"]["ks"], res["psi_train_valid"], res["best_iteration"],
             res["elapsed_sec"])
    if save_path is not None:
        saved = config.save_booster(m.booster_, save_path)
        res["model_path"] = str(Path(saved).relative_to(_PROJECT_ROOT))
        log.info("  [%s] 모델 저장: %s", tag, res["model_path"])
    gain = dict(zip(feats, m.booster_.feature_importance("gain")))
    return res, gain


def lean_features(gain: dict, e14: list[str], force_macro: bool) -> tuple[list[str], int]:
    """gain 누적 95% 지점까지. force_macro 면 거시 14개를 강제 포함한다."""
    total = sum(gain.values()) or 1.0
    order = sorted(gain.items(), key=lambda x: -x[1])
    keep, acc = [], 0.0
    for f, g in order:
        keep.append(f)
        acc += g / total
        if acc >= LEAN_CUM_GAIN:
            break
    n_pure = len(keep)
    if force_macro:
        for f in e14:
            if f not in keep:
                keep.append(f)
    return keep, n_pure


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", default="42,7,2024")
    ap.add_argument("--model-seed", type=int, default=42,
                    help="모델 파일로 저장할 시드")
    a = ap.parse_args()
    seeds = [int(x) for x in a.seeds.split(",") if x.strip()]

    log.info("=" * 70)
    log.info("보호 파일 md5 — 작업 전")
    md5_before = check_protected("before")

    df, feats, meta = load_d8_frame()
    mono = monotone_vector("D8", feats)
    log.info("  단조 제약 %s", "없음" if mono is None else
             f"{sum(1 for v in mono if v)}개")

    out = {"config": {"scenario": "D8", "seeds": seeds,
                      "lean_cum_gain": LEAN_CUM_GAIN,
                      "n_features_full": len(feats),
                      "e14": meta["e14"], "monotone": meta["mono"]},
           "md5_before": md5_before, "runs": []}

    # ── Full ────────────────────────────────────────────────────
    log.info("=" * 70)
    log.info("[Full] D8 구성 %d 피처", len(feats))
    gain42 = None
    for sd in seeds:
        save = (OUT_DIR / "lgbm_v2_full.txt") if sd == a.model_seed else None
        r, g = fit_one(df, feats, sd, mono, "Full", save)
        out["runs"].append(r)
        if sd == a.model_seed:
            gain42 = g

    assert gain42 is not None, f"model-seed {a.model_seed} 가 seeds 에 없다"

    # ── Lean 두 버전 ────────────────────────────────────────────
    lean_pure, n_pure = lean_features(gain42, meta["e14"], force_macro=False)
    lean_macro, _ = lean_features(gain42, meta["e14"], force_macro=True)
    e14_in_pure = [f for f in meta["e14"] if f in lean_pure]
    log.info("=" * 70)
    log.info("[Lean] gain 누적 %.0f%% 지점 N = %d", LEAN_CUM_GAIN * 100, n_pure)
    log.info("  순수 gain Lean: %d 피처 / 그중 거시 %d/%d",
             len(lean_pure), len(e14_in_pure), len(meta["e14"]))
    log.info("  거시 강제 Lean: %d 피처 (거시 %d개 전부 포함)",
             len(lean_macro), len(meta["e14"]))
    out["config"]["lean_n_at_95pct"] = n_pure
    out["config"]["lean_pure_features"] = lean_pure
    out["config"]["lean_macro_features"] = lean_macro
    out["config"]["e14_in_pure_lean"] = e14_in_pure

    for tag, fs, fname in (("Lean_pure", lean_pure, "lgbm_v2_lean.txt"),
                           ("Lean_macro", lean_macro, "lgbm_v2_lean_macro.txt")):
        mv = monotone_vector("D8", fs)
        for sd in seeds:
            save = (OUT_DIR / fname) if sd == a.model_seed else None
            r, _ = fit_one(df, fs, sd, mv, tag, save)
            out["runs"].append(r)

    # ── 요약 ────────────────────────────────────────────────────
    log.info("=" * 70)
    print()
    print("=" * 92)
    print("프로덕션 재학습 결과 — 시드 %d회 평균" % len(seeds))
    print("=" * 92)
    print(f"  {'구성':12s} {'피처':>5s} {'ValidAUC(σ)':>17s} {'KS':>8s} "
          f"{'PSI':>8s} {'best_iter':>10s}")
    summary = {}
    for tag in ("Full", "Lean_pure", "Lean_macro"):
        rs = [r for r in out["runs"] if r["tag"] == tag]
        if not rs:
            continue
        auc = [r["valid"]["auc"] for r in rs]
        ks = [r["valid"]["ks"] for r in rs]
        psi = [r["psi_train_valid"] for r in rs]
        it = [r["best_iteration"] for r in rs]
        summary[tag] = {
            "n_features": rs[0]["n_features"],
            "valid_auc": float(np.mean(auc)),
            "valid_auc_sd": float(st.stdev(auc)) if len(auc) > 1 else 0.0,
            "valid_ks": float(np.mean(ks)), "psi": float(np.mean(psi)),
            "best_iteration_mean": float(np.mean(it)),
        }
        s = summary[tag]
        print(f"  {tag:12s} {s['n_features']:5d} "
              f"{s['valid_auc']:.4f}({s['valid_auc_sd']:.4f}) "
              f"{s['valid_ks']:8.4f} {s['psi']:8.4f} {s['best_iteration_mean']:10.0f}")
    if "Lean_pure" in summary and "Lean_macro" in summary:
        d = summary["Lean_macro"]["valid_auc"] - summary["Lean_pure"]["valid_auc"]
        print()
        print(f"  ★ 거시 강제 포함의 대가: ΔAUC {d:+.4f} "
              f"(Lean_macro − Lean_pure). 노이즈대 0.003 "
              f"{'이내' if abs(d) < 0.003 else '초과'}")
        print(f"  ★ 순수 gain Lean 에 남은 거시: {len(e14_in_pure)}/{len(meta['e14'])}개")
        if e14_in_pure:
            print(f"     {e14_in_pure}")
    if "Full" in summary:
        for tag in ("Lean_pure", "Lean_macro"):
            if tag in summary:
                print(f"  {tag} vs Full: ΔAUC "
                      f"{summary[tag]['valid_auc'] - summary['Full']['valid_auc']:+.4f}")
    out["summary"] = summary

    log.info("보호 파일 md5 — 작업 후")
    out["md5_after"] = check_protected("after")
    assert out["md5_before"] == out["md5_after"], "보호 파일이 변경됐다"
    log.info("  보호 파일 불변 확인 완료")

    RESULT_JSON.parent.mkdir(parents=True, exist_ok=True)
    RESULT_JSON.write_text(json.dumps(out, ensure_ascii=False, indent=2),
                           encoding="utf-8")
    print()
    print(f"저장: {RESULT_JSON.relative_to(_PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
