"""
======================================================================
portal_v2 재빌드 + D8 재채점
======================================================================
  1) `nh_panel_macro_12m_obv_none_real.parquet` + D8 상호작용 14개로 채점 테이블 생성
  2) 예측 PD 3종(raw / platt_train / platt_dev) · Z-Score · 등급(G1~G5, 16단계) ·
     경보 여부를 컬럼으로 저장
  3) `database/build_portal_v2.py` 의 회전 규칙을 그대로 따른다 —
     기존 `portal_v2.duckdb` 는 삭제하지 않고 타임스탬프 접미사로 옮긴다.
  4) 재빌드 후 검증: 행수 948,214 / (V_BZNO, BASE_YM) 중복 0 / 등급 분포 /
     등급별 부도율 단조성

★ `portal.duckdb`(legacy)는 건드리지 않는다. `config.assert_db_writable("v2")` 가
  물리적으로 차단한다.

Usage
-----
    python -m database.rescore_v2_d8
    python -m database.rescore_v2_d8 --no-branch
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import shutil
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import duckdb
import numpy as np
import pandas as pd

from eda_pipeline import config, split_spec

TARGET = "IS_BUDO_12M"
EPS = 1e-15
EXPECTED_ROWS = 948_214

GRADE_JSON = config.OUTPUT_DIR / "grade_mapping_v2.json"
THRESH_JSON = config.OUTPUT_DIR / "threshold_v2.json"
MODEL = config.OUTPUT_DIR / "lgbm_v2_full.txt"
#: 백엔드 서빙 모델. 채점(PROB_RAW/등급)은 계속 D8 Full 로 하지만, 이 모델의
#: `ix_*` 피처가 DB 에 전부 남는지 여기서 검증한다 (/shap · /simulation 이 쓴다).
SERVE_MODEL = config.OUTPUT_DIR / "lgbm_v2_lean_macro.txt"
N_IX_EXPECTED = 14

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("rescore")


def _lit(p: Path) -> str:
    return "'" + str(p).replace("'", "''") + "'"


def rotate_existing(target: Path) -> Path | None:
    """기존 DB 를 삭제하지 않고 타임스탬프 접미사로 옮긴다 (build_portal_v2 규칙)."""
    if not target.exists():
        return None
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    moved = target.with_name(f"{target.stem}_{stamp}{target.suffix}")
    shutil.move(str(target), str(moved))
    return moved


def score_all() -> pd.DataFrame:
    """전 구간 948,214행을 D8 Full 로 채점하고 보정 3종을 붙인다."""
    import lightgbm as lgb
    from sklearn.linear_model import LogisticRegression

    from eda_pipeline.step38_production_retrain import load_d8_frame

    if not MODEL.exists():
        raise FileNotFoundError(
            f"{MODEL} 없음. 먼저 실행:\n"
            f"  python -m eda_pipeline.step38_production_retrain")
    booster = config.load_booster(MODEL)
    order = list(booster.feature_name())
    log.info("모델 %s / 피처 %d", MODEL.name, len(order))

    df, _, d8meta = load_d8_frame()
    missing = [c for c in order if c not in df.columns]
    assert not missing, f"모델 피처가 패널에 없다: {missing[:5]}"

    # ── D8 상호작용 14개를 DB 에 영구 저장한다 ──────────────────────────
    #   `load_d8_frame()` 이 `add_e14_interactions()` 로 메모리에서 만들지만,
    #   지금까지 `out` 에 실리지 않아 DB 에는 남지 않았다. 그래서 백엔드가
    #   lean_macro 모델(63피처)을 서빙할 수 없었다 — 여기서 실어 보낸다.
    ix_cols = [c for c in d8meta["e14"] if c.startswith("ix_")]
    assert len(ix_cols) == N_IX_EXPECTED, (
        f"D8 상호작용이 {N_IX_EXPECTED}개가 아니다 ({len(ix_cols)}개): {ix_cols}")
    ix_missing = [c for c in ix_cols if c not in df.columns]
    assert not ix_missing, f"상호작용 컬럼이 프레임에 없다: {ix_missing}"
    if SERVE_MODEL.exists():
        serve_ix = [c for c in config.load_booster(SERVE_MODEL).feature_name()
                    if c.startswith("ix_")]
        not_persisted = [c for c in serve_ix if c not in ix_cols]
        assert not not_persisted, (
            f"서빙 모델({SERVE_MODEL.name})의 상호작용이 저장 대상에 없다: "
            f"{not_persisted}")
        log.info("  서빙 모델 %s 의 ix_* %d개 모두 저장 대상", SERVE_MODEL.name,
                 len(serve_ix))
    log.info("  D8 상호작용 %d개를 DB 에 저장한다: %s", len(ix_cols), ix_cols)

    n = len(df)
    assert n == EXPECTED_ROWS, (
        f"중단 조건 3: 패널 행수가 {EXPECTED_ROWS:,} 가 아니다 ({n:,})")

    log.info("전 구간 채점 %s행...", f"{n:,}")
    p_raw = np.asarray(booster.predict(df[order]), dtype=float)
    logit = np.log(p_raw / (1 - p_raw + EPS))

    ym = df["BASE_YM"].astype(str)
    y = df[TARGET].astype(int).values
    tr = (ym < split_spec.DEV_START).values
    dv = ((ym >= split_spec.DEV_START) & (ym <= split_spec.DEV_END)).values

    def platt(mask: str, m: np.ndarray) -> np.ndarray:
        lr = LogisticRegression(C=1e6, solver="lbfgs", max_iter=1000)
        lr.fit(logit[m].reshape(-1, 1), y[m])
        log.info("  Platt(%s) coef=%.4f intercept=%.4f", mask,
                 lr.coef_[0][0], lr.intercept_[0])
        return lr.predict_proba(logit.reshape(-1, 1))[:, 1]

    out = pd.DataFrame({
        "V_BZNO": df["V_BZNO"].astype(str).values,
        "BASE_YM": ym.values,
        TARGET: y,
        "PROB_RAW": p_raw,
        "LOG_ODDS": logit,
        "PROB_PLATT_TRAIN": platt("train", tr),
        "PROB_PLATT_DEV": platt("dev", dv),
    })
    if "SPLIT" in df.columns:
        out["SPLIT"] = df["SPLIT"].astype(str).values
    # 상호작용 14개 — 기존 컬럼은 그대로 두고 추가만 한다.
    for c in ix_cols:
        out[c] = df[c].astype("float32").values
    log.info("  평균 PD  raw %.4f%% / platt_train %.4f%% / platt_dev %.4f%%",
             out["PROB_RAW"].mean() * 100,
             out["PROB_PLATT_TRAIN"].mean() * 100,
             out["PROB_PLATT_DEV"].mean() * 100)
    return out


def apply_grades(out: pd.DataFrame) -> dict:
    """grade_mapping_v2.json / threshold_v2.json 을 적용한다."""
    if not GRADE_JSON.exists() or not THRESH_JSON.exists():
        raise FileNotFoundError(
            f"{GRADE_JSON.name} / {THRESH_JSON.name} 없음. 먼저 실행:\n"
            f"  python -m eda_pipeline.step40_grade_threshold")
    g = json.loads(GRADE_JSON.read_text(encoding="utf-8"))
    t = json.loads(THRESH_JSON.read_text(encoding="utf-8"))

    out["Z_SCORE"] = (out["LOG_ODDS"] - g["z_mu"]) / g["z_sigma"]
    out["GRADE"] = pd.cut(out["Z_SCORE"],
                          bins=[-np.inf] + list(g["z_cutoffs"]) + [np.inf],
                          labels=g["grade_labels"], right=True).astype(str)
    out["GRADE16"] = pd.cut(out["PROB_RAW"],
                            bins=[-np.inf] + list(g["grade16_prob_cutoffs"]) + [np.inf],
                            labels=g["grade16_labels"], right=True).astype(str)
    th_f2 = float(t["f2_optimal"]["threshold"])
    out["ALERT_F2"] = (out["PROB_RAW"] >= th_f2).astype(int)
    used = {"f2": th_f2}
    for ratio, best in t["cost_optimal"].items():
        col = f"ALERT_COST{ratio}"
        out[col] = (out["PROB_RAW"] >= float(best["threshold"])).astype(int)
        used[f"cost{ratio}"] = float(best["threshold"])
    log.info("  임계값 적용: %s", {k: round(v, 6) for k, v in used.items()})
    return {"grade_meta": g, "thresholds_used": used}


def verify(con, meta: dict) -> dict:
    t = config.PANEL_TABLE
    rows = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    dup = con.execute(
        f"SELECT COUNT(*) FROM (SELECT V_BZNO, BASE_YM FROM {t} "
        f"GROUP BY 1,2 HAVING COUNT(*) > 1)").fetchone()[0]
    log.info("[검증] 행수 %s (기대 %s) / (V_BZNO,BASE_YM) 중복 %s",
             f"{rows:,}", f"{EXPECTED_ROWS:,}", f"{dup:,}")
    if rows != EXPECTED_ROWS:
        raise SystemExit(f"중단 조건 3: 행수 {rows:,} != {EXPECTED_ROWS:,}")
    if dup:
        raise SystemExit(f"중단: (V_BZNO, BASE_YM) 중복 {dup:,}건")

    gd = con.execute(f"""
        SELECT GRADE, COUNT(*) AS n, SUM({TARGET}) AS n_budo,
               ROUND(AVG({TARGET}) * 100, 4) AS rate_pct
        FROM {t} GROUP BY 1 ORDER BY 1""").df()
    base = con.execute(f"SELECT AVG({TARGET}) * 100 FROM {t}").fetchone()[0]
    gd["lift"] = gd["rate_pct"] / base
    log.info("[검증] 등급 분포와 부도율")
    for _, r in gd.iterrows():
        log.info("   %-4s %10s %8s %9.4f%%  lift %6.2f", r.GRADE,
                 f"{int(r.n):,}", f"{int(r.n_budo):,}", r.rate_pct, r.lift)
    rates = gd["rate_pct"].tolist()
    mono = all(rates[i] <= rates[i + 1] for i in range(len(rates) - 1))
    log.info("[검증] 등급별 부도율 단조성: %s", "확보" if mono else "★ 실패")
    if not mono:
        raise SystemExit(
            "중단 조건 2: 등급별 부도율 단조성 실패. "
            "step40_grade_threshold 의 컷오프 조정 로직을 확인할 것")
    return {"rows": int(rows), "dup": int(dup), "monotone": bool(mono),
            "grade_dist": gd.to_dict(orient="records")}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-branch", action="store_true")
    a = ap.parse_args()

    target = config.assert_db_writable("v2")
    log.info("=" * 78)
    log.info("portal_v2 재빌드 + D8 재채점")
    log.info("  대상: %s", target)
    log.info("  legacy DB: %s exists=%s — 건드리지 않음",
             config.DB_PATH_LEGACY.name, config.DB_PATH_LEGACY.exists())

    out = score_all()
    meta = apply_grades(out)

    # ── 백엔드 호환 별칭 ────────────────────────────────────────────────
    #   현행 portal_v2.duckdb 에 존재하는 PROB_FULL / PROB_DISPLAY / Z_GRADE 는
    #   이 스크립트가 만들지 않아 재빌드하면 사라졌다 (backend 의
    #   `dedup_panel_sql` 이 PROB_FULL 로 정렬하므로 전 엔드포인트가 죽는다).
    #   같은 정의(= PROB_RAW / PROB_PLATT_DEV / GRADE)로 재현해 둔다.
    out["PROB_FULL"] = out["PROB_RAW"]
    out["PROB_DISPLAY"] = out["PROB_PLATT_DEV"]
    out["Z_GRADE"] = out["GRADE"]

    src = config.OUTPUT_DIR / "nh_panel_macro_12m_obv_none_real.parquet"
    moved = rotate_existing(Path(target))
    if moved:
        log.info("  기존 DB 를 삭제하지 않고 옮김 -> %s", moved.name)

    con = duckdb.connect(str(target))
    try:
        log.info("패널 테이블 생성...")
        con.execute(f"CREATE TABLE {config.PANEL_TABLE} AS "
                    f"SELECT * FROM read_parquet({_lit(src)})")
        con.register("scores", out)
        # 채점 컬럼을 조인해 붙인다 (행수 불변을 검증한다)
        score_cols = [c for c in out.columns
                      if c not in ("V_BZNO", "BASE_YM", TARGET, "SPLIT")]
        sel = ", ".join(f"s.{c}" for c in score_cols)
        con.execute(f"""
            CREATE TABLE _joined AS
            SELECT p.*, {sel}
            FROM {config.PANEL_TABLE} p
            JOIN scores s USING (V_BZNO, BASE_YM)""")
        n_j = con.execute("SELECT COUNT(*) FROM _joined").fetchone()[0]
        assert n_j == EXPECTED_ROWS, f"채점 조인에서 행수 변동: {n_j:,}"
        con.execute(f"DROP TABLE {config.PANEL_TABLE}")
        con.execute(f"ALTER TABLE _joined RENAME TO {config.PANEL_TABLE}")

        if not a.no_branch:
            con.execute(f"ALTER TABLE {config.PANEL_TABLE} "
                        f"ADD COLUMN V_BRANCH_CODE VARCHAR")
            con.execute(f"UPDATE {config.PANEL_TABLE} SET V_BRANCH_CODE = "
                        f"'VB00' || ((hash(V_BZNO::VARCHAR) % 5) + 1)::VARCHAR")
        for col, idx in (("V_BZNO", "idx_v2_bzno"), ("BASE_YM", "idx_v2_baseym"),
                         (TARGET, "idx_v2_budo"), ("GRADE", "idx_v2_grade")):
            con.execute(f"CREATE INDEX {idx} ON {config.PANEL_TABLE}({col})")
        res = verify(con, meta)
    finally:
        con.close()

    rep = config.VALIDATION_DIR / "portal_v2_rescore_report.json"
    rep.write_text(json.dumps(
        {"target": str(Path(target).relative_to(_PROJECT_ROOT)),
         "rotated_to": (moved.name if moved else None),
         "model": MODEL.name, "source_panel": src.name,
         "thresholds_used": meta["thresholds_used"],
         "z_mu": meta["grade_meta"]["z_mu"],
         "z_sigma": meta["grade_meta"]["z_sigma"],
         "verification": res},
        ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("=" * 78)
    log.info("저장: %s", rep.relative_to(_PROJECT_ROOT))


if __name__ == "__main__":
    main()
