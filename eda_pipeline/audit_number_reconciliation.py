"""
======================================================================
작업 A-2 — 수치 불일치 규명 (읽기 전용 감사)
======================================================================
규명 대상 2건
  (1) 기업 수 27,147 (README) vs 27,150 (eda_report.html)  → 3사 차이
  (2) 양성   9,814 (실측)     vs 9,985 (지시서 기대치)     → 171건 차이

이 스크립트는 **아무것도 쓰지 않는다** (산출물 JSON/MD 만 새로 쓴다).
DuckDB 는 read_only=True 로만 붙고, parquet 은 duckdb 로 읽는다
(이 환경에 pyarrow/fastparquet 이 없다).

실행:
    C:/Users/scudy/.venvs/nh_eco/Scripts/python.exe -m eda_pipeline.audit_number_reconciliation
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import duckdb
import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from eda_pipeline import config  # noqa: E402

OUT = config.VALIDATION_DIR
LOG_PATH = _ROOT / "logs" / "A2_number_reconciliation.log"
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8", mode="a"),
              logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("A2")


def q(sql: str) -> pd.DataFrame:
    """인메모리 duckdb 로 쿼리. 실행한 SQL 을 로그에 남긴다."""
    log.info("SQL: %s", " ".join(sql.split()))
    con = duckdb.connect()
    try:
        return con.execute(sql).df()
    finally:
        con.close()


def lit(p: Path | str) -> str:
    return "'" + str(p).replace("'", "''") + "'"


# ── 단계별 산출물 ────────────────────────────────────────────────────
# (라벨, 경로, 설명)
STAGES = [
    ("step2_obv_panel",  config.OUTPUT_DIR / "nh_panel_full_obv.parquet",
     "step2 통합 패널 (obv 스파인)"),
    ("step5_prep",       config.OUTPUT_DIR / "nh_panel_prep_obv_none.parquet",
     "step5 전처리 + 12M 타겟 + 부도구간제외 + 우측절단"),
    ("step6_macro",      config.OUTPUT_DIR / "nh_panel_macro_12m_obv_none.parquet",
     "step6 거시 결합 (합성 거시)"),
    ("step6_macro_real", config.OUTPUT_DIR / "nh_panel_macro_12m_obv_none_real.parquet",
     "D축 실거시 최종 패널 (채점본 원천)"),
]


def has_col(path: Path, col: str) -> bool:
    df = q(f"SELECT * FROM read_parquet({lit(path)}) LIMIT 0")
    return col in df.columns


def stage_table() -> list[dict]:
    rows = []
    for label, path, desc in STAGES:
        if not path.exists():
            log.warning("없음: %s", path)
            continue
        cols = q(f"SELECT * FROM read_parquet({lit(path)}) LIMIT 0").columns.tolist()
        sel = ["COUNT(*) AS n_rows",
               "COUNT(DISTINCT V_BZNO) AS n_firms",
               "MIN(BASE_YM) AS ym_min",
               "MAX(BASE_YM) AS ym_max",
               "COUNT(DISTINCT BASE_YM) AS n_months"]
        if "IS_BUDO_12M" in cols:
            sel += ["SUM(IS_BUDO_12M) AS pos",
                    "COUNT(DISTINCT CASE WHEN IS_BUDO_12M=1 THEN V_BZNO END) AS pos_firms"]
        if "SPLIT" in cols:
            sel += ["SUM(CASE WHEN SPLIT='TRAIN' THEN 1 ELSE 0 END) AS n_train",
                    "SUM(CASE WHEN SPLIT='VALID' THEN 1 ELSE 0 END) AS n_valid"]
        r = q(f"SELECT {', '.join(sel)} FROM read_parquet({lit(path)})").iloc[0].to_dict()
        r = {k: (int(v) if isinstance(v, (int, float)) and pd.notna(v) and k != "ym_min"
                 and k != "ym_max" else v) for k, v in r.items()}
        r.update(stage=label, desc=desc, n_cols=len(cols), path=str(path))
        rows.append(r)
        log.info("[STAGE] %s -> %s", label, r)
    return rows


def db_table() -> dict:
    p = config.DB_PATH_V2
    if not p.exists():
        return {}
    log.info("SQL(duckdb portal_v2, read_only): corporate_panel 집계")
    con = duckdb.connect(str(p), read_only=True)
    try:
        r = con.execute("""
            SELECT COUNT(*) n_rows,
                   COUNT(DISTINCT V_BZNO) n_firms,
                   SUM(IS_BUDO_12M) pos,
                   COUNT(DISTINCT CASE WHEN IS_BUDO_12M=1 THEN V_BZNO END) pos_firms,
                   MIN(BASE_YM) ym_min, MAX(BASE_YM) ym_max,
                   SUM(CASE WHEN SPLIT='TRAIN' THEN 1 ELSE 0 END) n_train,
                   SUM(CASE WHEN SPLIT='VALID' THEN 1 ELSE 0 END) n_valid
            FROM corporate_panel
        """).df().iloc[0].to_dict()
        ncol = con.execute("SELECT COUNT(*) FROM (DESCRIBE corporate_panel)").fetchone()[0]
    finally:
        con.close()
    out = {k: (int(v) if k not in ("ym_min", "ym_max") else v) for k, v in r.items()}
    out.update(stage="portal_v2.duckdb", desc="채점본 DB", n_cols=int(ncol), path=str(p))
    log.info("[STAGE] portal_v2.duckdb -> %s", out)
    return out


def firm_diff() -> dict:
    """앞 단계 − 뒤 단계 V_BZNO 집합 차집합으로 빠진 기업을 특정한다."""
    res = {}
    pairs = [(STAGES[0], STAGES[1]), (STAGES[1], STAGES[2]), (STAGES[2], STAGES[3])]
    for (la, pa, _), (lb, pb, _) in pairs:
        if not (pa.exists() and pb.exists()):
            continue
        sql = f"""
            SELECT a.V_BZNO FROM
              (SELECT DISTINCT CAST(V_BZNO AS VARCHAR) V_BZNO FROM read_parquet({lit(pa)})) a
            ANTI JOIN
              (SELECT DISTINCT CAST(V_BZNO AS VARCHAR) V_BZNO FROM read_parquet({lit(pb)})) b
            USING (V_BZNO)
            ORDER BY 1
        """
        miss = q(sql)["V_BZNO"].tolist()
        res[f"{la}__minus__{lb}"] = miss
        log.info("[DIFF] %s - %s = %d사 %s", la, lb, len(miss), miss[:20])
    return res


def budo_check(bznos: list[str]) -> list[dict]:
    """빠진 기업이 부도 기업인지 budo_events.csv / 원천 TXT 로 대조."""
    if not bznos:
        return []
    ev = pd.read_csv(config.budo_events_path(), dtype=str)
    ev.columns = [c.replace("\ufeff", "") for c in ev.columns]
    ev["V_BZNO"] = ev["V_BZNO"].astype(str).str.strip()

    src = config.budo_source_path()
    raw = None
    if src is not None:
        for enc in ("utf-8", "cp949"):
            try:
                raw = pd.read_csv(src, sep="|", encoding=enc, dtype=str,
                                  skipinitialspace=True)
                break
            except (UnicodeDecodeError, UnicodeError):
                continue
        if raw is not None:
            raw = raw.iloc[1:].reset_index(drop=True)
            raw = raw.loc[:, ~raw.columns.str.startswith("Unnamed")]
            raw["V_BZNO"] = raw["V_BZNO"].astype(str).str.strip()

    out = []
    for b in bznos:
        e = ev[ev["V_BZNO"] == b]
        r = raw[raw["V_BZNO"] == b] if raw is not None else pd.DataFrame()
        out.append({
            "V_BZNO": b,
            "in_budo_events": bool(len(e)),
            "budo_events_rows": e.to_dict("records"),
            "in_raw_budo_txt": bool(len(r)),
            "raw_budo_rows": r.to_dict("records"),
        })
        log.info("[BUDO] %s: events=%d raw=%d", b, len(e), len(r))
    return out


def missing_firm_spine_detail(bznos: list[str]) -> list[dict]:
    """빠진 기업의 step2 스파인 관측월 범위. 부도월과 비교하면 전량 제거 이유가 보인다."""
    if not bznos:
        return []
    p = STAGES[0][1]
    inlist = ", ".join(lit(b) for b in bznos)
    df = q(f"""SELECT CAST(V_BZNO AS VARCHAR) V_BZNO, COUNT(*) n_rows,
                      MIN(BASE_YM) ym_min, MAX(BASE_YM) ym_max
               FROM read_parquet({lit(p)})
               WHERE CAST(V_BZNO AS VARCHAR) IN ({inlist})
               GROUP BY 1 ORDER BY 1""")
    log.info("[SPINE-DETAIL]\n%s", df.to_string())
    return df.to_dict("records")


def positives_detail() -> dict:
    """양성 수를 step5 전/후로 재현한다.

    step5 는 (a) 타겟 생성 -> (b) 부도진행중구간 제외 -> (c) 우측절단 순서다.
    (a) 직후 양성은 산출물에 남지 않으므로, 최종 패널 + budo_events 로 재계산한다.
    """
    from eda_pipeline.step5_panel_prep import (HORIZON_MONTHS, CENSOR_END,
                                               EXCLUDE_DEFAULT_MONTH)
    p2 = STAGES[0][1]           # step2 obv 패널 = 부도구간 제외 이전 스파인
    ev = pd.read_csv(config.budo_events_path(), dtype=str)
    ev.columns = [c.replace("\ufeff", "") for c in ev.columns]

    def ym(s):
        s = pd.to_numeric(s, errors="coerce")
        return (s // 100).astype("float64") * 12 + (s % 100)

    spine = q(f"SELECT CAST(V_BZNO AS VARCHAR) V_BZNO, CAST(BASE_YM AS VARCHAR) BASE_YM "
              f"FROM read_parquet({lit(p2)})")
    spine["_B"] = ym(spine["BASE_YM"])

    e = ev[["V_BZNO", "DEFAULT_YM", "IS_RECOVERED", "RECOVER_YM"]].copy()
    e["V_BZNO"] = e["V_BZNO"].astype(str).str.strip()
    e["_EV"] = ym(e["DEFAULT_YM"])

    left = spine[["V_BZNO", "_B"]].copy()
    left["_row"] = range(len(left))
    left = left.sort_values("_B", kind="mergesort")
    ee = (e[["V_BZNO", "_EV"]].drop_duplicates().sort_values("_EV", kind="mergesort"))
    m = pd.merge_asof(left, ee, left_on="_B", right_on="_EV", by="V_BZNO",
                      direction="forward", allow_exact_matches=False)
    m = m.sort_values("_row", kind="mergesort")
    gap = m["_EV"].values - m["_B"].values
    spine["IS_BUDO_12M"] = ((gap > 0) & (gap <= HORIZON_MONTHS)).astype(int)

    pos_a = int(spine["IS_BUDO_12M"].sum())

    # (b) 부도 진행 중 구간 제외
    import numpy as np
    e["_D"] = e["_EV"]
    rec = pd.to_numeric(e["RECOVER_YM"], errors="coerce")
    e["_R"] = np.where(pd.to_numeric(e["IS_RECOVERED"], errors="coerce").fillna(0) == 1,
                       (rec // 100) * 12 + (rec % 100), np.iinfo(np.int32).max)
    e.loc[e["_R"] < e["_D"], "_R"] = np.iinfo(np.int32).max
    lo_off = 0 if EXCLUDE_DEFAULT_MONTH else 1
    groups = spine.groupby("V_BZNO", sort=False).indices
    drop = np.zeros(len(spine), dtype=bool)
    idx = spine["_B"].values
    for v, d, r in zip(e["V_BZNO"].values, e["_D"].values, e["_R"].values):
        pos = groups.get(v)
        if pos is None:
            continue
        hit = (idx[pos] >= d + lo_off) & (idx[pos] <= r)
        if hit.any():
            drop[pos[hit]] = True
    s2 = spine.loc[~drop]
    pos_b, rows_b = int(s2["IS_BUDO_12M"].sum()), len(s2)

    # (c) 우측절단
    limit = int(CENSOR_END[:4]) * 12 + int(CENSOR_END[4:6])
    s3 = s2.loc[(s2["_B"] + HORIZON_MONTHS) <= limit]
    pos_c, rows_c = int(s3["IS_BUDO_12M"].sum()), len(s3)

    # (b) 에서 사라진 양성 171건의 정체
    lost = spine.loc[drop & (spine["IS_BUDO_12M"] == 1)]
    out = {
        "EXCLUDE_DEFAULT_MONTH": EXCLUDE_DEFAULT_MONTH,
        "CENSOR_END": CENSOR_END,
        "HORIZON_MONTHS": HORIZON_MONTHS,
        "a_after_target": {"rows": len(spine), "pos": pos_a},
        "b_after_drop_in_default": {"rows": rows_b, "pos": pos_b},
        "c_after_censoring": {"rows": rows_c, "pos": pos_c},
        "lost_positives": {
            "n_rows": int(len(lost)),
            "n_firms": int(lost["V_BZNO"].nunique()),
            "ym_min": str(lost["BASE_YM"].min()) if len(lost) else None,
            "ym_max": str(lost["BASE_YM"].max()) if len(lost) else None,
            "note": "부도 진행 중(부도월~정상화월) 이면서 12개월 내 다음 부도가 또 있는 행. "
                    "재부도 기업의 부도 진행 구간이므로 학습에서 빼야 한다.",
        },
        "rows_dropped_in_default": int(len(spine) - rows_b),
        "rows_dropped_censoring": int(rows_b - rows_c),
    }
    log.info("[POS] %s", out)
    return out


def split_positives() -> dict:
    p = STAGES[3][1]
    if not p.exists():
        return {}
    df = q(f"""SELECT SPLIT, COUNT(*) n, SUM(IS_BUDO_12M) pos
               FROM read_parquet({lit(p)}) GROUP BY 1 ORDER BY 1""")
    from eda_pipeline.split_spec import DEV_START, DEV_END
    three = q(f"""
        SELECT CASE WHEN CAST(BASE_YM AS VARCHAR) < '{DEV_START}' THEN '1_TRAIN_core'
                    WHEN CAST(BASE_YM AS VARCHAR) <= '{DEV_END}'  THEN '2_DEV'
                    ELSE '3_VALID' END g,
               COUNT(*) n, SUM(IS_BUDO_12M) pos,
               COUNT(*) - SUM(IS_BUDO_12M) neg,
               (COUNT(*) - SUM(IS_BUDO_12M)) / SUM(IS_BUDO_12M) neg_per_pos
        FROM read_parquet({lit(p)}) GROUP BY 1 ORDER BY 1""")
    d8 = config.OUTPUT_DIR / "d8_valid_scores.parquet"
    out = {"final_panel_by_split": df.to_dict("records"),
           "final_panel_three_way": three.to_dict("records")}

    # step38 이 기록한 scale_pos_weight 와 대조 — 어느 라벨로 학습했는지의 증거
    s38 = config.VALIDATION_DIR / "step38_production_retrain.json"
    if s38.exists():
        spw = json.loads(s38.read_text(encoding="utf-8"))["runs"][0]["scale_pos_weight"]
        core = three.loc[three["g"] == "1_TRAIN_core"].iloc[0]
        out["scale_pos_weight_crosscheck"] = {
            "step38_recorded": spw,
            "panel_train_core_neg_per_pos": float(core["neg_per_pos"]),
            "match": abs(spw - float(core["neg_per_pos"])) < 1e-3,
        }
    if d8.exists():
        cols = q(f"SELECT * FROM read_parquet({lit(d8)}) LIMIT 0").columns.tolist()
        tgt = "IS_BUDO_12M" if "IS_BUDO_12M" in cols else (
            "y" if "y" in cols else ("y_true" if "y_true" in cols else None))
        sel = "COUNT(*) n" + (f", SUM({tgt}) pos" if tgt else "")
        out["d8_valid_scores"] = q(
            f"SELECT {sel} FROM read_parquet({lit(d8)})").iloc[0].to_dict()
        out["d8_valid_scores_cols"] = cols
    log.info("[SPLIT] %s", out)
    return out


def main():
    log.info("=" * 70)
    log.info("A-2 수치 불일치 감사 시작")
    log.info("=" * 70)

    stages = stage_table()
    db = db_table()
    if db:
        stages.append(db)
    diffs = firm_diff()
    missing = diffs.get("step2_obv_panel__minus__step5_prep", [])
    # 3사 후보를 모든 차집합에서 모은다
    all_missing = sorted({b for v in diffs.values() for b in v})
    budo = budo_check(all_missing)
    spine_detail = missing_firm_spine_detail(all_missing)
    pos = positives_detail()
    spl = split_positives()

    result = {
        "generated_at": pd.Timestamp.now().isoformat(timespec="seconds"),
        "stage_table": stages,
        "firm_set_diffs": {k: v for k, v in diffs.items()},
        "missing_firms_spine_detail": spine_detail,
        "missing_firms_budo_check": budo,
        "positives_reconstruction": pos,
        "positives_by_split": spl,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "A2_number_reconciliation.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    log.info("저장: %s", OUT / "A2_number_reconciliation.json")
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str)[:8000])
    return result


if __name__ == "__main__":
    main()
