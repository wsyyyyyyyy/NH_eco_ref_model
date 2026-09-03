"""
======================================================================
벤 다이어그램 준비 — 내부 EWS 대조 · 거시 구간 · 재무 양호 그룹
======================================================================
**분석은 하지 않는다.** 내일 방향을 정한 뒤 수행할 준비만 한다.

  [4-1] 내부 EWS 부도율(`OBV_RZVL_POD`) 을 평가 전용 테이블로 분리
        ★ 피처로 다시 넣지 않는다. 내부 모형 복제를 막기 위해 제외한 변수다.
          평가·비교 용도로만 쓴다.
  [4-2] 거시 스트레스 구간 플래그 — 경계는 `base_rate` 실제 궤적으로 검증한다
  [4-3] 재무 양호 그룹 후보별 해당 기업 수만 집계 (기준값 확정하지 않는다)

Usage
-----
    python -m eda_pipeline.step39_venn_prep
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

import duckdb
import numpy as np
import pandas as pd

from eda_pipeline import config, split_spec

LEGACY_PANEL = config.OUTPUT_DIR / "nh_panel_full_obv.parquet"
FINAL_PANEL = config.OUTPUT_DIR / "nh_panel_macro_12m_obv_none_real.parquet"
RAW_OBV = config.INPUT_DIR / "가상사업자_VH_OBV_DTL_관찰세부등급v.txt"

OUT_POD = config.OUTPUT_DIR / "internal_ews_pod.parquet"
OUT_JSON = config.VALIDATION_DIR / "step39_venn_prep.json"

TARGET = "IS_BUDO_12M"

#: 거시 스트레스 구간 (지시서 정의. base_rate 궤적으로 검증한다)
STRESS_WINDOWS = [
    ("고스트레스", "202206", "202312", "base_rate 급등 및 고점 유지"),
    ("저스트레스", "202101", "202205", "저금리"),
    ("완화기", "202401", "202505", "인하 국면"),
]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("venn_prep")


# ══════════════════════════════════════════════════════════════════════
# 4-1 — 내부 EWS 부도율 분리
# ══════════════════════════════════════════════════════════════════════

def prep_internal_pod() -> dict:
    con = duckdb.connect()
    try:
        cols = [r[0] for r in con.execute(
            f"DESCRIBE SELECT * FROM read_parquet('{LEGACY_PANEL.as_posix()}')"
        ).fetchall()]
        if "OBV_RZVL_POD" not in cols:
            return {"found": False,
                    "note": f"{LEGACY_PANEL.name} 에 OBV_RZVL_POD 없음"}
        log.info("[4-1] %s 에서 OBV_RZVL_POD 추출", LEGACY_PANEL.name)
        df = con.execute(f"""
            SELECT V_BZNO, BASE_YM, OBV_RZVL_POD, OBV_BZL_RZVL_ASP_ELGD
            FROM read_parquet('{LEGACY_PANEL.as_posix()}')
        """).df()
        # 최종 패널의 (V_BZNO, BASE_YM) 과 타겟
        fin = con.execute(f"""
            SELECT V_BZNO, BASE_YM, {TARGET}, SPLIT
            FROM read_parquet('{FINAL_PANEL.as_posix()}')
        """).df()
    finally:
        con.close()

    for d in (df, fin):
        d["V_BZNO"] = d["V_BZNO"].astype(str)
        d["BASE_YM"] = d["BASE_YM"].astype(str)

    n0 = len(fin)
    m = fin.merge(df, on=["V_BZNO", "BASE_YM"], how="left")
    assert len(m) == n0, f"조인에서 행수 변동: {n0} -> {len(m)}"
    pod = pd.to_numeric(m["OBV_RZVL_POD"], errors="coerce")
    m["OBV_RZVL_POD"] = pod

    budo = m[m[TARGET] == 1]
    firms_budo = budo["V_BZNO"].nunique()
    firms_budo_pod = budo.loc[pod[budo.index].notna(), "V_BZNO"].nunique()

    res = {
        "found": True,
        "source": LEGACY_PANEL.name,
        "n_rows": int(len(m)),
        "missing_rate": float(pod.isna().mean()),
        "nonnull_rows": int(pod.notna().sum()),
        "pod_min": float(pod.min()) if pod.notna().any() else None,
        "pod_median": float(pod.median()) if pod.notna().any() else None,
        "pod_max": float(pod.max()) if pod.notna().any() else None,
        "n_firms_total": int(m["V_BZNO"].nunique()),
        "n_firms_with_pod": int(m.loc[pod.notna(), "V_BZNO"].nunique()),
        "n_firms_budo": int(firms_budo),
        "n_firms_budo_with_pod": int(firms_budo_pod),
        "budo_pod_coverage": (float(firms_budo_pod / firms_budo)
                              if firms_budo else None),
    }
    log.info("  결측률 %.2f%% / 비결측 %s행", res["missing_rate"] * 100,
             f"{res['nonnull_rows']:,}")
    log.info("  POD 분포 min %.6f / 중앙 %.6f / max %.6f",
             res["pod_min"] or 0, res["pod_median"] or 0, res["pod_max"] or 0)
    log.info("  부도 기업 %s사 중 POD 값 보유 %s사 (%.1f%%)",
             f"{firms_budo:,}", f"{firms_budo_pod:,}",
             (res["budo_pod_coverage"] or 0) * 100)

    keep = m[["V_BZNO", "BASE_YM", TARGET, "SPLIT",
              "OBV_RZVL_POD", "OBV_BZL_RZVL_ASP_ELGD"]]
    con = duckdb.connect()
    try:
        con.register("t", keep)
        con.execute(
            f"COPY t TO '{OUT_POD.as_posix()}' (FORMAT PARQUET)")
    finally:
        con.close()
    log.info("  저장: %s (%s행)", OUT_POD.name, f"{len(keep):,}")
    res["out_path"] = str(OUT_POD.relative_to(_PROJECT_ROOT))
    return res


# ══════════════════════════════════════════════════════════════════════
# 4-2 — 거시 스트레스 구간
# ══════════════════════════════════════════════════════════════════════

def prep_stress_windows() -> dict:
    raw = pd.read_csv(_PROJECT_ROOT / "api_data_processing" / "output"
                      / "model_input" / "model_input_monthly.csv")
    raw["BASE_YM"] = pd.to_datetime(raw["date"]).dt.strftime("%Y%m")
    br = raw.set_index("BASE_YM")["base_rate"].astype(float)

    log.info("[4-2] base_rate 궤적으로 구간 경계 검증")
    log.info("  월별 base_rate (분기별 표본)")
    for ym in sorted(br.index):
        if ym[4:] in ("01", "04", "07", "10"):
            log.info("    %s  %.2f%%", ym, br[ym])

    rows = []
    for name, lo, hi, why in STRESS_WINDOWS:
        sub = br.loc[(br.index >= lo) & (br.index <= hi)]
        rows.append({"window": name, "start": lo, "end": hi, "rationale": why,
                     "n_months": int(len(sub)),
                     "base_rate_mean": float(sub.mean()),
                     "base_rate_min": float(sub.min()),
                     "base_rate_max": float(sub.max()),
                     "base_rate_start": float(sub.iloc[0]),
                     "base_rate_end": float(sub.iloc[-1])})
    log.info("")
    log.info("  %-12s %-16s %6s %8s %8s %8s", "구간", "기간", "개월",
             "평균", "최소", "최대")
    for r in rows:
        log.info("  %-12s %s~%s %6d %8.2f %8.2f %8.2f", r["window"],
                 r["start"], r["end"], r["n_months"], r["base_rate_mean"],
                 r["base_rate_min"], r["base_rate_max"])

    # 검증 — 고스트레스 평균이 저스트레스보다 높고, 완화기 끝이 시작보다 낮아야 한다
    by = {r["window"]: r for r in rows}
    checks = {
        "고스트레스 평균 > 저스트레스 평균":
            by["고스트레스"]["base_rate_mean"] > by["저스트레스"]["base_rate_mean"],
        "완화기 종료값 <= 완화기 시작값":
            by["완화기"]["base_rate_end"] <= by["완화기"]["base_rate_start"],
        "저스트레스 최대 <= 고스트레스 최소 + 여유":
            by["저스트레스"]["base_rate_max"] <= by["고스트레스"]["base_rate_max"],
    }
    log.info("")
    for k, v in checks.items():
        log.info("  검증: %-40s %s", k, "통과" if v else "★ 실패")
    return {"windows": rows, "checks": {k: bool(v) for k, v in checks.items()},
            "base_rate_by_month": {k: float(v) for k, v in br.items()}}


# ══════════════════════════════════════════════════════════════════════
# 4-3 — 재무 양호 그룹 후보 (집계만)
# ══════════════════════════════════════════════════════════════════════

def prep_healthy_candidates() -> dict:
    con = duckdb.connect()
    try:
        df = con.execute(f"""
            SELECT V_BZNO, BASE_YM, {TARGET}, SPLIT,
                   C302_CRI_ORD, JEMU_debt_ratio, JEMU_115000,
                   JEMU_191310_val
            FROM read_parquet('{FINAL_PANEL.as_posix()}')
        """).df()
    finally:
        con.close()
    df["BASE_YM"] = df["BASE_YM"].astype(str)
    budo = df[df[TARGET] == 1]
    log.info("[4-3] 재무 양호 그룹 후보 — 기준값을 확정하지 않고 개수만 센다")
    log.info("  전체 %s행 / 부도(12M) %s행 / 부도 기업 %s사",
             f"{len(df):,}", f"{len(budo):,}", f"{budo['V_BZNO'].nunique():,}")

    out = []
    for name, col, better_low in (
            ("C302_CRI_ORD 상위 50% (등급 서열)", "C302_CRI_ORD", True),
            ("JEMU_debt_ratio 하위 50% (부채비율 낮음)", "JEMU_debt_ratio", True),
            ("JEMU_191310_val 상위 50% (EBITDA이자보상배율)", "JEMU_191310_val", False)):
        v = pd.to_numeric(df[col], errors="coerce")
        ok = v.notna()
        if not ok.any():
            out.append({"candidate": name, "column": col, "note": "전부 결측"})
            continue
        med = float(v[ok].median())
        good = (v <= med) if better_low else (v >= med)
        good = good & ok
        bg = df[good & (df[TARGET] == 1)]
        out.append({
            "candidate": name, "column": col, "median": med,
            "better_is_low": better_low,
            "missing_rate": float(v.isna().mean()),
            "n_rows_good": int(good.sum()),
            "n_firms_good": int(df.loc[good, "V_BZNO"].nunique()),
            "n_rows_good_and_budo": int(len(bg)),
            "n_firms_good_and_budo": int(bg["V_BZNO"].nunique()),
            "budo_rate_in_good": float(
                df.loc[good, TARGET].mean()) if good.any() else None,
        })
        r = out[-1]
        log.info("  %-42s 중앙 %-10.4f 결측 %5.2f%%  양호 %s사 / "
                 "그중 부도 %s사 (부도율 %.4f%%)", name, med,
                 r["missing_rate"] * 100, f"{r['n_firms_good']:,}",
                 f"{r['n_firms_good_and_budo']:,}",
                 (r["budo_rate_in_good"] or 0) * 100)
    return {"total_rows": int(len(df)),
            "budo_rows": int(len(budo)),
            "budo_firms": int(budo["V_BZNO"].nunique()),
            "candidates": out}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.parse_args()
    out = {}
    log.info("=" * 70)
    out["internal_pod"] = prep_internal_pod()
    log.info("=" * 70)
    out["stress_windows"] = prep_stress_windows()
    log.info("=" * 70)
    out["healthy_candidates"] = prep_healthy_candidates()

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(out, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    log.info("=" * 70)
    log.info("저장: %s", OUT_JSON.relative_to(_PROJECT_ROOT))


if __name__ == "__main__":
    main()
