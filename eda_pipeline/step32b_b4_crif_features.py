"""
======================================================================
B4f — 시점 정합 CRIF 를 **피처로 넣어** 측정한다
======================================================================
B46 학습(step32 `--variant B46 --train`)은 A0 피처 152개만 쓴다.
A0 에는 CRIF 계열이 아예 없으므로, B46 의 ΔAUC 는 사실상 **B6(AC12) 효과만**
잰 것이고 B4(CRIF 재구성)는 학습에 반영되지 않았다.

이 스크립트는 그 공백을 메운다.

  A2  (기존) = A0 + CRIF 4개 — **연 단위 조인**, 시점 누수 있음. ΔAUC +0.0679
  B4f (여기) = A0 + CRIF 4개 — **월 단위 as-of**, BASE_YM 이전 발생분만

  A2 의 +0.0679 가 신호였다면 B4f 도 오른다.
  누수였다면 B4f 는 A0 와 같아진다. 그 차이가 곧 누수분이다.

사용 피처 (지시서 명세)
  CRIF_CNT_12M        최근 12개월 내 발생 건수
  CRIF_MONTHS_SINCE   마지막 발생 이후 경과 개월 (이력 없으면 NaN)
  CRIF_WORST_RSNC     가장 심각한 사유코드 (min)
  ※ 해제일 / 해제사유는 쓰지 않는다 — 부도 대비 +35개월로 100% 사후 정보다.

Usage
-----
    python -m eda_pipeline.step32b_b4_crif_features --seeds 42,7,2024
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

import pandas as pd

from eda_pipeline import config
from eda_pipeline import step30_stage6_ablation as ab

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
log = logging.getLogger(__name__)

PANEL = config.OUTPUT_DIR / "nh_panel_B46_asof.parquet"

#: 금액 합계(RSN/OVD)는 넣지 않는다 — 건수·경과·심각도와 달리 금액은
#: 규모 효과가 섞여 해석이 흐려진다.
#: [2026-09-02] CRIF_CNT_EVER 제거 (승인). CRIF_CNT_12M 과 비영 비율이 동일하고
#:   값이 다른 행이 3개뿐이라 정보가 겹친다. 지시서 명세 4종 -> 3종.
CRIF_FEATS = ["CRIF_CNT_12M", "CRIF_MONTHS_SINCE", "CRIF_WORST_RSNC"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", default="42,7,2024")
    ap.add_argument("--tag", default="B4f")
    a = ap.parse_args()
    seeds = [int(x) for x in a.seeds.split(",") if x.strip()]

    if not PANEL.exists():
        raise FileNotFoundError(
            f"{PANEL} 가 없다. 먼저 실행할 것:\n"
            f"  python -m eda_pipeline.step32_panel_variants --variant B46")

    # pandas 의 parquet 엔진(pyarrow/fastparquet)이 이 환경에 없다.
    # step32 도 duckdb 로 쓰므로 읽기도 duckdb 로 맞춘다.
    import duckdb
    df = duckdb.connect().execute(
        f"SELECT * FROM read_parquet('{PANEL.as_posix()}')").df()
    a0, _, _ = ab.base_feature_pool()

    have = [c for c in CRIF_FEATS if c in df.columns]
    miss = [c for c in CRIF_FEATS if c not in df.columns]
    if miss:
        log.warning("패널에 없는 CRIF 피처 %s — 빼고 진행한다", miss)
    overlap = [c for c in have if c in a0]
    if overlap:
        log.warning("A0 에 이미 있는 컬럼 %s — 중복 추가하지 않는다", overlap)
    feats = list(a0) + [c for c in have if c not in a0]

    log.info("[%s] A0 %d + CRIF %d = 피처 %d개",
             a.tag, len(a0), len(feats) - len(a0), len(feats))
    for c in have:
        s = pd.to_numeric(df[c], errors="coerce")
        log.info("    %-20s 비결측 %6.3f%%  비영 %6.3f%%  중앙값 %s",
                 c, s.notna().mean() * 100,
                 float((s.fillna(0) != 0).mean()) * 100,
                 f"{s.median():.1f}" if s.notna().any() else "—")

    df = df.copy()
    df["BASE_YM"] = df["BASE_YM"].astype(str)
    df[ab.TARGET] = df[ab.TARGET].astype("int8")
    for c in feats:
        if c in df.columns and not pd.api.types.is_numeric_dtype(df[c]):
            df[c] = df[c].astype("category")

    out = []
    for sd in seeds:
        prm = ab.active_params()
        prm["random_state"] = sd
        r = ab.run_one(a.tag, df, feats, save_model=False, params=prm,
                       tag=f"{a.tag}_seed{sd}")
        r["seed"] = sd
        r["variant"] = a.tag
        out.append(r)

    fp = ab.OUT_DIR / "ablation_B_results.json"
    prev = json.loads(fp.read_text(encoding="utf-8")) if fp.exists() else []
    keep = [r for r in prev
            if not (r.get("variant") == a.tag and r.get("seed") in {x["seed"] for x in out})]
    fp.write_text(json.dumps(keep + out, ensure_ascii=False, indent=2), encoding="utf-8")

    aucs = [r["valid"]["auc"] for r in out]
    log.info("[%s] Valid AUC %s  평균 %.4f", a.tag,
             [round(x, 4) for x in aucs], sum(aucs) / len(aucs))
    log.info("[%s] 결과 저장: %s", a.tag, fp.name)


if __name__ == "__main__":
    main()
