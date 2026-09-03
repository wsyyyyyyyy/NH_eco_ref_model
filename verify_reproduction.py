"""
verify_reproduction.py — 재현 결과가 확정본과 맞는지 한 번에 판정한다.

    python verify_reproduction.py

run_all.py 로 만든 산출물(패널·D8 모델·등급 컷오프)을 읽어 아래를 대조한다.
전부 PASS 면 재현 성공이다. 하나라도 FAIL 이면 기대값과 실측값을 함께 출력한다.

출력 위치는 환경변수 NH_OUTPUT_DIR 을 따른다 (run_all.py 와 동일).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="backslashreplace")
    except (AttributeError, ValueError):
        pass

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
from sklearn.metrics import roc_auc_score

from eda_pipeline import config, split_spec

TARGET = "IS_BUDO_12M"

EXPECT = {
    "panel_rows": 948_214,
    "panel_pos": 9_814,
    "panel_firms": 27_147,
    "d8_valid_auc": 0.8578,
    "d8_valid_auc_tol": 0.003,
}

_results: list[tuple[bool, str]] = []


def _check(name: str, ok: bool, detail: str) -> None:
    _results.append((ok, name))
    print(f"  [{'PASS' if ok else 'FAIL'}]  {name}")
    if not ok:
        print(f"         {detail}")


def main() -> int:
    print(f"[verify] 출력 위치 : {config.OUTPUT_DIR}")

    try:
        from eda_pipeline import step38_production_retrain as s38
        df, feats, _meta = s38.load_d8_frame()
    except Exception as e:  # noqa: BLE001
        print(f"[verify] 패널·피처 로딩 실패: {type(e).__name__}: {e}")
        print("         run_all.py 를 먼저 완주시키십시오.")
        return 2

    # 1) 패널 규모
    n_rows = len(df)
    n_pos = int(df[TARGET].astype(int).sum())
    n_firms = int(df["V_BZNO"].nunique())
    _check("패널 행수 948,214", n_rows == EXPECT["panel_rows"],
           f"기대 {EXPECT['panel_rows']:,} / 실측 {n_rows:,}")
    _check("양성 행수 9,814", n_pos == EXPECT["panel_pos"],
           f"기대 {EXPECT['panel_pos']:,} / 실측 {n_pos:,}")
    _check("기업 수 27,147", n_firms == EXPECT["panel_firms"],
           f"기대 {EXPECT['panel_firms']:,} / 실측 {n_firms:,}")

    # 2) D8 Valid AUC
    va = df["BASE_YM"].astype(str) >= split_spec.VALID_START
    yva = df.loc[va, TARGET].astype(int).values
    try:
        booster = config.load_booster(str(config.MODEL_PATH_V2_FULL))
        p_va = np.asarray(booster.predict(df.loc[va, feats]))
        auc = roc_auc_score(yva, p_va)
        lo, hi = EXPECT["d8_valid_auc"] - EXPECT["d8_valid_auc_tol"], EXPECT["d8_valid_auc"] + EXPECT["d8_valid_auc_tol"]
        _check(f"D8 Valid AUC {EXPECT['d8_valid_auc']} ± {EXPECT['d8_valid_auc_tol']}",
               lo <= auc <= hi,
               f"기대 [{lo:.4f}, {hi:.4f}] / 실측 {auc:.4f} (Valid {int(va.sum()):,}행)")
    except Exception as e:  # noqa: BLE001
        _check("D8 Valid AUC", False, f"채점 실패: {type(e).__name__}: {e}")
        p_va = None

    # 3) 등급 G1~G5 부도율 단조성 (Z-Score 컷오프)
    gm_path = config.OUTPUT_DIR / "grade_mapping_v2.json"
    if p_va is not None and gm_path.is_file():
        gm = json.loads(gm_path.read_text(encoding="utf-8"))
        mu, sigma = gm["z_mu"], gm["z_sigma"]
        cuts = gm["z_cutoffs"]                          # [-1, 0, 1, 2]
        eps = 1e-12
        logodds = np.log(np.clip(p_va, eps, 1 - eps) / np.clip(1 - p_va, eps, 1 - eps))
        z = (logodds - mu) / sigma
        grade = np.digitize(z, cuts)                    # 0..4 -> G1..G5
        rates = []
        for g in range(5):
            m = grade == g
            rates.append(float(yva[m].mean()) if m.any() else float("nan"))
        mono = all(a < b for a, b in zip(rates, rates[1:]) if not (np.isnan(a) or np.isnan(b)))
        _check("등급 G1~G5 부도율 단조 증가", mono,
               "실측 부도율 " + " → ".join(f"G{i+1} {r*100:.4f}%" for i, r in enumerate(rates)))
    elif not gm_path.is_file():
        _check("등급 G1~G5 부도율 단조성", False, f"{gm_path} 없음 — step40_grade_threshold 필요")

    n_fail = sum(1 for ok, _ in _results if not ok)
    print(f"\n[verify] {len(_results) - n_fail} PASS / {n_fail} FAIL")
    if n_fail == 0:
        print("[verify] 재현 성공 — 확정본과 일치합니다.")
    else:
        print("[verify] 재현 실패 — 위 FAIL 항목을 확인하십시오.")
        print("         거시 수집은 API 응답 시점에 따라 값이 미세하게 다를 수 있습니다. "
              "행수·컬럼수가 맞고 AUC 가 허용범위면 통과로 봅니다.")
    return 1 if n_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
