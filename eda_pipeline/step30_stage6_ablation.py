"""
======================================================================
STAGE 6 Ablation 러너 — A축 (피처 토글)
======================================================================
계획서: eda_pipeline/output/validation/step30_scenario_plan.md
선행확인: eda_pipeline/step30_stage6_preflight.py

설계 원칙
--------
  - DB 는 읽기 전용으로만 연다 (config.connect_db).
  - 학습 파라미터는 전 시나리오 동일 고정 (PARAMS). 바꾸는 것은 피처 집합뿐이다.
  - scale_pos_weight 는 시나리오별 Train 부분집합에서 매번 재계산한다.
    상수 리터럴을 쓰지 않는다 (preflight 가 AST 로 검사한다).
  - early stopping 은 Dev 로만 한다. Valid 는 최종 1회 평가에서만 본다.
  - 조인 뒤에는 예외 없이 `assert len(df) == n_before`.
    이 프로젝트에서 행 폭증이 두 번 있었다 (CRIF +50,214행 / 타겟 생성).

Usage
-----
    python -m eda_pipeline.step30_stage6_ablation --list
    python -m eda_pipeline.step30_stage6_ablation --run A0 A1 A2
    python -m eda_pipeline.step30_stage6_ablation --run-all
    python -m eda_pipeline.step30_stage6_ablation --dev-window-probe   # 확인 3
"""

from __future__ import annotations

import argparse
import json
import logging
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
from scipy.stats import ks_2samp
from sklearn.metrics import roc_auc_score

from eda_pipeline import config, split_spec
from eda_pipeline.leaky_cols import feature_columns

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("ablation")

TARGET = "IS_BUDO_12M"
OUT_DIR = config.ABLATION_DIR

# step5 이전 산출물. LEAK_CONFIRMED 집계 컬럼이 여기 살아 있다.
PRE_STEP5_PANEL = config.OUTPUT_DIR / "nh_panel_full_obv.parquet"
# 원천 CRIF. 해제일/해제사유 2개는 패널로 넘어오지 않았다.
RAW_CRIF = config.INPUT_DIR / "가상사업자_VH_CRIF_신용불량v.txt"

# ── 누수 변수군 ──────────────────────────────────────────────────────
LEAK_OPNP = ["COPR_OPNP_C"]
LEAK_CRIF_AGG = ["CRIF_EVENT_CNT", "CRIF_RSN_AM_SUM", "CRIF_OVD_AM_SUM", "CRIF_WORST_RSNC"]
LEAK_CRIF_RLS = ["CRIF_RLS_OCU_DT", "CRIF_RLS_RSNC"]     # 원천에서만 복원 가능
CG01_FAMILY = ["CG01_KIS_SCORE", "CG01_MISSING_YN"]   # 둘 다 연 단위 = 누수
C302_LEAK = ["C302_IS_D_YN"]                          # 부도 등급 그 자체
# 아래 2개는 STAGE 6 에서 시점 정합이 실증되어 A0 기준선에 편입됐다.
#   C302_MISSING_YN : (기업,연도) 내 월별 변동 21,040건
#   C302_CRI_ORD    : 유효기간 as-of. LEAK_SUSPECT 해제
C302_CLEAN = ["C302_MISSING_YN", "C302_CRI_ORD"]
INDUSTRY = ["STD_INDS_SECTION", "STD_INDS_MID2"]

# ── 학습 파라미터 (전 시나리오 고정) ─────────────────────────────────
# metric='auc' 를 반드시 명시한다. 생략하면 LightGBM 이 binary_logloss 를 함께
# 평가하고, early_stopping(first_metric_only=False) 은 "어느 한 지표라도" 개선이
# 멈추면 정지한다. scale_pos_weight=108 로 가중된 목적함수는 가중 없는 Dev
# binary_logloss 를 1회차부터 악화시키므로(0.172 -> 0.261), AUC 가 0.78 -> 0.94 로
# 계속 오르는 중인데도 best_iteration=1 로 멈춰 버린다. 실측으로 확인했다.
PARAMS = dict(
    metric="auc",
    n_estimators=2000,
    learning_rate=0.05,
    num_leaves=63,
    max_depth=8,
    min_child_samples=100,
    subsample=0.8,
    subsample_freq=1,
    colsample_bytree=0.8,
    reg_lambda=1.0,
    random_state=42,
    n_jobs=-1,
    verbose=-1,
)
EARLY_STOPPING_ROUNDS = 100


# ── 규제 변형 (A0 프로브용) ──────────────────────────────────────────
# Train AUC 가 0.999~1.000 이고 Dev-Valid 격차가 0.19 였다. 과적합 상태에서는
# 시나리오 간 미세 차이(A8 의 +0.0083 등)가 규제 여지 차이로 뒤바뀔 수 있다.
# n_estimators 는 세 변형 모두 5000 으로 둔다. R2 는 lr=0.02 라 2000 이면
# 상한에 붙어 비교가 불공정해진다. R0 는 632 회에서 조기종료했으므로 상한을
# 올려도 결과가 바뀌지 않는다 (동일성 확인 완료).
REG_VARIANTS = {
    "R0": {},                       # 현재 설정 = 기존 A0
    "R1": dict(num_leaves=7, min_child_samples=500,
               colsample_bytree=0.6, subsample=0.8, subsample_freq=1),
    "R2": dict(num_leaves=7, min_child_samples=500,
               colsample_bytree=0.6, subsample=0.8, subsample_freq=1,
               reg_alpha=5.0, reg_lambda=5.0, learning_rate=0.02),
}
REG_PROBE_N_ESTIMATORS = 10000

# A0~A9 본실행에 쓸 규제 설정.
# 프로브 결과 R2 가 Train-Valid 격차(0.2416 -> 0.2142)와 Valid AUC(0.7583 -> 0.7836)
# 양쪽에서 우세했다. 상한 15000 으로 풀어 실제 수렴점이 6,454 회임을 확인했고
# (Valid 0.7826, 절단분 0.7836 과 차이 없음) 상한 10000 이면 구속되지 않는다.
ACTIVE_REG = "R2"


def active_params() -> dict:
    p = dict(PARAMS)
    p.update(REG_VARIANTS[ACTIVE_REG])
    if ACTIVE_REG != "R0":
        p["n_estimators"] = REG_PROBE_N_ESTIMATORS
    return p


# ══════════════════════════════════════════════════════════════════════
# 시나리오 정의
# ══════════════════════════════════════════════════════════════════════
# add    : A0 기준선에 되넣을 컬럼
# drop   : A0 에서 추가로 뺄 컬럼 (접미사 규칙은 resolve 에서 처리)
SCENARIOS = {
    # ── 기준선 ────────────────────────────────────────────────────
    # A0 는 "시점 정합성이 확인된 피처 전부". C302_MISSING_YN / C302_CRI_ORD 가
    # STAGE 6 에서 정합 판정을 받아 편입됐다. 모든 ΔAUC 의 기준이다.
    "A0":  dict(desc="기준선. 시점 정합 피처 전부 (C302 정합분 편입)", add=[], drop=[]),
    "A0c": dict(desc="보수 기준선. A0 − C302 정합분 (= STAGE 6 초판 A0)",
                add=[], drop=C302_CLEAN),

    # ── 누수 되넣기 ───────────────────────────────────────────────
    "A1": dict(desc="A0 + COPR_OPNP_C (폐업코드)", add=LEAK_OPNP, drop=[]),
    "A2": dict(desc="A0 + CRIF 집계 4개 (연 단위 조인 = 시점 누수 잔존)",
               add=LEAK_CRIF_AGG, drop=[]),
    "A3": dict(desc="A0 + CG01 점수 + 이력플래그 (둘 다 연 단위 누수)",
               add=CG01_FAMILY, drop=[]),
    "A4": dict(desc="A0 + CG01_MISSING_YN 만 (연 단위 누수)",
               add=["CG01_MISSING_YN"], drop=[]),
    "A7": dict(desc="누수 상한. 누수 변수 전부 되넣음",
               add=LEAK_OPNP + LEAK_CRIF_AGG + LEAK_CRIF_RLS + CG01_FAMILY + C302_LEAK,
               drop=[]),

    # ── 한계 기여 분해 (A0 에서 하나씩 뺀다) ──────────────────────
    "A5": dict(desc="A0 − C302_CRI_ORD (등급 서열의 한계 기여)",
               add=[], drop=["C302_CRI_ORD"]),
    "A6": dict(desc="A0 − C302_MISSING_YN (이력 유무의 한계 기여)",
               add=[], drop=["C302_MISSING_YN"]),
    "A8": dict(desc="A0 − JEMU sentinel 파생 36개", add=[], drop=["__SENTINEL__"]),

    # ── C축: 업종 피처 구성 ───────────────────────────────────────
    # A0 gain 1위가 STD_INDS_MID2 (23.79%) 였다. 업종 하나가 압도적이면
    # 업종별 부도율을 외우고 있을 수 있다. 중분류는 고유값이 많아 위험이 크다.
    "C0": dict(desc="A0 − 업종 피처 전부 (업종 없이 얼마가 나오는가)",
               add=[], drop=INDUSTRY),
    "C1": dict(desc="업종 대분류(SECTION) 만", add=[], drop=["STD_INDS_MID2"]),
    "C2": dict(desc="업종 중분류(MID2) 만", add=[], drop=["STD_INDS_SECTION"]),
    "C3": dict(desc="업종 둘 다 (= A0)", add=[], drop=[]),

    # ── 최적 조합 ─────────────────────────────────────────────────
    # C1(대분류만) 0.8595 > C0(업종없음) 0.8509 > C3(둘다) 0.8434 ≈ C2(중분류만) 0.8431
    #   -> STD_INDS_MID2(고유값 71)는 업종별 부도율을 외운다. 빼면 오른다.
    # A6(CRI_ORD만) 0.8465 > A0(둘다) 0.8434 > A5(MISSING_YN만) 0.8336
    #   -> C302_CRI_ORD 의 NaN 이 이미 "이력 없음"을 담고 있어 MISSING_YN 은 중복.
    "C4": dict(desc="최적 조합. 업종 대분류만 + C302_CRI_ORD만",
               add=[], drop=["STD_INDS_MID2", "C302_MISSING_YN"]),
    "C5": dict(desc="Lean. C4 − JEMU sentinel 파생 36개",
               add=[], drop=["STD_INDS_MID2", "C302_MISSING_YN", "__SENTINEL__"]),
}

SENTINEL_SUFFIX = ("_undef", "_capped", "_turn_neg", "_cont_neg", "_turn_pos")


# ══════════════════════════════════════════════════════════════════════
# 데이터 적재
# ══════════════════════════════════════════════════════════════════════

def _onedrive_notice() -> None:
    if "OneDrive" in str(_PROJECT_ROOT):
        log.warning("프로젝트가 OneDrive 동기화 폴더 안에 있다. "
                    "대용량 산출물 쓰기 중 동기화가 겹치면 파일 잠금/손상이 날 수 있다. "
                    "작업 중 OneDrive 동기화 일시중지를 권고한다.")


def _verify_written(path: Path, min_bytes: int = 1) -> None:
    """OneDrive 동기화 중 쓰기가 깨지지 않았는지 확인한다."""
    if not path.exists():
        raise IOError(f"쓰기 실패: {path} 가 생성되지 않았다.")
    size = path.stat().st_size
    if size < min_bytes:
        raise IOError(f"쓰기 이상: {path.name} 크기 {size}B (< {min_bytes}B)")
    try:
        with open(path, "rb") as f:
            f.read(1024)
    except Exception as e:
        raise IOError(f"쓰기 후 재읽기 실패: {path.name} — {e}") from e


def base_feature_pool() -> tuple[list[str], dict]:
    """A0 기준선 피처와 제외 내역을 만든다."""
    meta = json.loads((config.OUTPUT_DIR / "macro_columns_v2.json").read_text(encoding="utf-8"))
    con = config.connect_db("v2")
    try:
        cols = con.execute(
            f"SELECT * FROM {config.PANEL_TABLE} LIMIT 0").df().columns.tolist()
    finally:
        con.close()

    drop_macro = set(meta["pure_macro"]) | set(meta["interaction"])
    drop_const = set(meta["constant_zero_variance"])
    # CG01 2개는 leaky_cols 의 LEAK_CONFIRMED/LEAK_SUSPECT 가, C302_IS_NR/R_YN 은
    # DEGENERATE 가 이미 제외한다. 여기서 추가로 뺄 것은 없다.
    drop_cg_c302 = set()

    feats = feature_columns(pd.DataFrame(columns=cols), target=TARGET,
                            include_suspect=False, extra_exclude=["V_BRANCH_CODE"])
    a0 = [c for c in feats if c not in drop_macro | drop_const | drop_cg_c302]

    # A0 에서 뺐지만 시나리오가 되넣을 수 있는 컬럼은 DB 에서 함께 읽어 둬야 한다.
    # 읽지 않으면 df.columns 에 없어서 resolve_features 가 조용히 건너뛰고
    # A3~A6 이 A0 와 똑같아진다 (실제로 한 번 그렇게 나왔다).
    addable = sorted({c for sc in SCENARIOS.values() for c in sc["add"]} & set(cols)
                     - set(a0))
    info = dict(db_cols=len(cols), all_features=len(feats),
                n_macro=len(meta["pure_macro"]), n_interaction=len(meta["interaction"]),
                n_constant=len(drop_const), n_cg_c302=len(drop_cg_c302),
                n_a0=len(a0), n_addable=len(addable))
    return a0, info, addable


def load_base(a0: list[str], addable: list[str] | None = None) -> pd.DataFrame:
    """A0 피처 + 되넣기 후보 + 키/타겟을 DB 에서 읽는다.

    addable 은 A0 에 들어가지 않지만 시나리오가 되넣을 수 있는 컬럼이다.
    """
    load_cols = list(a0) + [c for c in (addable or []) if c not in a0]
    con = config.connect_db("v2")
    try:
        types = {r[0]: r[1] for r in
                 con.execute(f"DESCRIBE {config.PANEL_TABLE}").fetchall()}
        parts = ["V_BZNO", "BASE_YM", TARGET]
        for c in load_cols:
            parts.append(f'"{c}"' if types.get(c) == "VARCHAR"
                         else f'CAST("{c}" AS FLOAT) AS "{c}"')
        df = con.execute(
            f'SELECT {", ".join(parts)} FROM {config.PANEL_TABLE}').df()
    finally:
        con.close()
    # DuckDB 는 VARCHAR 를 pandas 'str'(arrow-backed) 로 돌려준다. object 검사만으로는
    # 놓쳐서 LightGBM 이 "bad pandas dtypes" 로 죽는다. 수치형이 아니면 전부 category 로.
    for c in load_cols:
        if not pd.api.types.is_numeric_dtype(df[c]):
            df[c] = df[c].astype("category")
    df[TARGET] = df[TARGET].astype("int8")
    return df


def _coerce_dtypes(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """조인으로 붙은 컬럼을 LightGBM 이 받는 dtype 으로 맞춘다.

    수치로 해석되면 float32, 아니면 category. DuckDB/CSV 왕복에서 문자열로
    돌아오는 컬럼이 섞이면 LightGBM 이 "bad pandas dtypes" 로 죽는다.
    """
    for c in cols:
        if c not in df.columns or pd.api.types.is_numeric_dtype(df[c]):
            continue
        num = pd.to_numeric(df[c], errors="coerce")
        # 원래 값이 있던 자리가 전부 NaN 이 되면 수치가 아니다 -> category
        if num.notna().sum() >= df[c].notna().sum() * 0.99:
            df[c] = num.astype("float32")
        else:
            df[c] = df[c].astype("category")
    return df


def join_leak_from_pre_step5(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """step5 가 떨어뜨린 누수 컬럼을 step5 이전 패널에서 되붙인다.

    DB 는 읽기 전용이므로 portal_v2.duckdb 를 수정하지 않고 메모리에서만 붙인다.
    """
    want = [c for c in cols if c not in df.columns]
    if not want:
        return df
    if not PRE_STEP5_PANEL.exists():
        raise FileNotFoundError(f"{PRE_STEP5_PANEL} 없음. A1/A2/A7 을 실행할 수 없다.")
    n_before = len(df)
    con = duckdb.connect()
    try:
        sel = ", ".join(f'"{c}"' for c in ["V_BZNO", "BASE_YM"] + want)
        src = con.execute(
            f"SELECT {sel} FROM read_parquet('{PRE_STEP5_PANEL.as_posix()}')").df()
    finally:
        con.close()
    dup = src.duplicated(["V_BZNO", "BASE_YM"]).sum()
    assert dup == 0, f"원천에 (V_BZNO, BASE_YM) 중복 {dup}건"
    src["V_BZNO"] = src["V_BZNO"].astype(str)
    src["BASE_YM"] = src["BASE_YM"].astype(str)
    out = df.merge(src, on=["V_BZNO", "BASE_YM"], how="left")
    assert len(out) == n_before, f"누수 컬럼 조인에서 행 폭증: {n_before} -> {len(out)}"
    out = _coerce_dtypes(out, want)
    log.info(f"    누수 컬럼 조인 {want} — 행수 {n_before:,} 유지")
    return out


def join_crif_release_from_raw(df: pd.DataFrame) -> pd.DataFrame:
    """해제일/해제사유 2개를 원천에서 (V_BZNO, 연도) 집계로 붙인다.

    step2 가 패널로 넘기지 않은 컬럼이다 (부도기업 182건 전부가 부도 이후 해제).
    A7(누수 상한)에서만 쓴다. step2 와 같은 연 단위 조인 규칙을 그대로 따른다.
    """
    if all(c in df.columns for c in LEAK_CRIF_RLS):
        return df
    if not RAW_CRIF.exists():
        log.warning(f"    {RAW_CRIF.name} 없음 — 해제 2개는 A7 에서 제외한다.")
        return df
    n_before = len(df)
    raw = pd.read_csv(RAW_CRIF, sep="|", dtype=str, skiprows=[1],
                      encoding="utf-8", engine="python")
    raw = raw.loc[:, [c for c in raw.columns if not c.startswith("Unnamed")]]
    raw["V_BZNO"] = raw["V_BZNO"].astype(str).str.strip()
    raw["_YEAR"] = raw["CRDBD_OCU_YY"].astype(str).str[:4]
    for src, dst in (("MAX(CRDBD_RLS_OCU_DT)", "CRIF_RLS_OCU_DT"),
                     ("MAX(CRDBD_RLS_RSNC)", "CRIF_RLS_RSNC")):
        raw[dst] = pd.to_numeric(raw[src], errors="coerce")
    agg = (raw.groupby(["V_BZNO", "_YEAR"], dropna=False)[LEAK_CRIF_RLS]
              .max().reset_index())
    assert not agg.duplicated(["V_BZNO", "_YEAR"]).any()
    df = df.copy()
    df["_YEAR"] = df["BASE_YM"].astype(str).str[:4]
    out = df.merge(agg, on=["V_BZNO", "_YEAR"], how="left").drop(columns=["_YEAR"])
    assert len(out) == n_before, f"CRIF 해제 조인에서 행 폭증: {n_before} -> {len(out)}"
    out = _coerce_dtypes(out, LEAK_CRIF_RLS)
    log.info(f"    CRIF 해제 2개 원천 조인 — 행수 {n_before:,} 유지")
    return out


def resolve_features(scenario: str, a0: list[str], available: list[str],
                     strict: bool = True) -> list[str]:
    """시나리오의 피처 목록. 되넣기 컬럼이 패널에 없으면 **중단한다.**

    ★ [2026-09-02] `strict` 를 기본 True 로 넣었다.
      초판은 없는 컬럼을 조용히 건너뛰었다. 그러면 "A0 + 누수 4개" 를 재려는
      시나리오가 A0 와 완전히 같은 피처로 돌아가면서 ΔAUC 0 을 내고,
      그것이 '누수 기여가 없다' 는 결론으로 오독될 수 있다.
      측정하려던 것을 측정하지 못했으면 결과가 아니라 오류다.
    """
    spec = SCENARIOS[scenario]
    feats = list(a0)
    for d in spec["drop"]:
        if d == "__SENTINEL__":
            feats = [c for c in feats if not c.endswith(SENTINEL_SUFFIX)]
        else:
            feats = [c for c in feats if c != d]
    missing = [a for a in spec["add"] if a not in available]
    if missing and strict:
        raise ValueError(
            f"{scenario}: 되넣기 컬럼 {len(missing)}개가 패널에 없다 — {missing}\n"
            f"  이 상태로 돌리면 A0 와 같은 피처가 되어 측정 자체가 무의미하다.\n"
            f"  --run / --seed-probe 에 이 시나리오를 넣어 조인 단계를 태울 것.")
    for a in spec["add"]:
        if a in available and a not in feats:
            feats.append(a)
    return feats


# ══════════════════════════════════════════════════════════════════════
# 지표
# ══════════════════════════════════════════════════════════════════════

def calculate_ks(y_true, y_prob) -> float:
    y_true, y_prob = np.asarray(y_true), np.asarray(y_prob)
    return float(ks_2samp(y_prob[y_true == 0], y_prob[y_true == 1]).statistic)


def calculate_psi(expected, actual, bins: int = 10) -> float:
    expected, actual = np.asarray(expected), np.asarray(actual)
    edges = np.quantile(expected, np.linspace(0, 1, bins + 1))
    edges[0], edges[-1] = -np.inf, np.inf
    eps = 1e-4
    out = 0.0
    for i in range(bins):
        e = max(np.mean((expected >= edges[i]) & (expected < edges[i + 1])), eps)
        a = max(np.mean((actual >= edges[i]) & (actual < edges[i + 1])), eps)
        out += (a - e) * np.log(a / e)
    return float(out)


def evaluate(y, p) -> dict:
    auc = roc_auc_score(y, p)
    return {"auc": float(auc), "gini": float(2 * auc - 1), "ks": calculate_ks(y, p)}


# ══════════════════════════════════════════════════════════════════════
# 실행
# ══════════════════════════════════════════════════════════════════════

def run_one(scenario: str, df: pd.DataFrame, feats: list[str],
            dev_start: str | None = None, save_model: bool = True,
            params: dict | None = None, tag: str = '') -> dict:
    prm = params if params is not None else active_params()
    ds = dev_start or split_spec.DEV_START
    ym = df["BASE_YM"].astype(str)
    tr = ym < ds
    dv = (ym >= ds) & (ym <= split_spec.DEV_END)
    va = ym >= split_spec.VALID_START

    X, y = df[feats], df[TARGET].astype(int)
    ytr, ydv, yva = y[tr], y[dv], y[va]

    # scale_pos_weight — 이 시나리오의 Train 실측 비율. 상수 아님.
    n_pos = int(ytr.sum())
    n_neg = int(len(ytr) - n_pos)
    spw = n_neg / max(n_pos, 1)

    log.info(f"  [{scenario}] 피처 {len(feats)} / Train {int(tr.sum()):,} "
             f"(양성 {n_pos:,}, {n_pos/int(tr.sum()):.4%}) / Dev {int(dv.sum()):,} "
             f"(양성 {int(ydv.sum()):,}) / Valid {int(va.sum()):,} "
             f"(양성 {int(yva.sum()):,}) / spw={spw:.2f}")

    t0 = time.time()
    model = lgb.LGBMClassifier(scale_pos_weight=spw, **prm)
    model.fit(X[tr], ytr,
              eval_set=[(X[dv], ydv)],          # Dev 전용. Valid 는 넣지 않는다.
              eval_metric="auc",
              callbacks=[lgb.early_stopping(EARLY_STOPPING_ROUNDS, verbose=False)])
    elapsed = time.time() - t0

    p_tr = model.predict_proba(X[tr])[:, 1]
    p_dv = model.predict_proba(X[dv])[:, 1]
    p_va = model.predict_proba(X[va])[:, 1]

    res = {
        "scenario": scenario,
        "desc": SCENARIOS[scenario]["desc"] if scenario in SCENARIOS else "",
        "n_features": len(feats),
        "best_iteration": int(model.best_iteration_ or prm["n_estimators"]),
        "n_estimators_cap": prm["n_estimators"],
        "hit_cap": bool((model.best_iteration_ or 0) >= prm["n_estimators"]),
        "reg_variant": tag or ACTIVE_REG,
        "scale_pos_weight": round(spw, 4),
        "dev_start": ds,
        "n_train": int(tr.sum()), "n_dev": int(dv.sum()), "n_valid": int(va.sum()),
        "pos_train": n_pos, "pos_dev": int(ydv.sum()), "pos_valid": int(yva.sum()),
        "rate_train": float(ytr.mean()), "rate_dev": float(ydv.mean()),
        "rate_valid": float(yva.mean()),
        "train": evaluate(ytr, p_tr),
        "dev": evaluate(ydv, p_dv),
        "valid": evaluate(yva, p_va),
        "psi_train_valid": calculate_psi(p_tr, p_va),
        "elapsed_sec": round(elapsed, 1),
    }
    gain = sorted(zip(feats, model.booster_.feature_importance("gain")),
                  key=lambda x: -x[1])
    total = sum(g for _, g in gain) or 1.0
    res["gain_top15"] = [{"feature": f, "gain_pct": round(100 * g / total, 3)}
                         for f, g in gain[:15]]

    log.info(f"  [{scenario}] Valid AUC {res['valid']['auc']:.4f} "
             f"KS {res['valid']['ks']:.4f} PSI {res['psi_train_valid']:.4f} "
             f"best_iter {res['best_iteration']} ({elapsed:.0f}s)")

    if save_model:
        mp = config.OUTPUT_DIR / f"lgbm_v2_{scenario}{('_' + tag) if tag else ''}.txt"
        config.save_booster(model, mp)          # legacy 2건 가드 통과 필수
        _verify_written(mp, min_bytes=10_000)
    return res


def _merge_results(path: Path, new: list[dict]) -> list[dict]:
    """부분 실행이 기존 결과를 덮어쓰지 않도록 시나리오 단위로 병합한다.

    --run C4 C5 처럼 일부만 돌리면 예전 구현은 파일 전체를 [C4, C5] 로 교체해
    앞서 돌린 14종을 지워 버렸다 (실제로 한 번 발생했다).
    같은 시나리오는 새 결과로 갈아끼우고 나머지는 보존한다.
    """
    old = []
    if path.exists():
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            old = []
    by_id = {r["scenario"]: r for r in old}
    for r in new:
        by_id[r["scenario"]] = r
    order = list(SCENARIOS)
    return sorted(by_id.values(),
                  key=lambda r: order.index(r["scenario"])
                  if r["scenario"] in order else 999)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--run", nargs="*", default=None)
    ap.add_argument("--run-all", action="store_true")
    ap.add_argument("--seed-probe", nargs="*", default=None,
                    help="지정 시나리오를 여러 시드로 돌려 노이즈 폭을 잰다")
    ap.add_argument("--seeds", default="42,7,2024",
                    help="--seed-probe 에 쓸 random_state 목록")
    ap.add_argument("--reg-probe", action="store_true",
                    help="A0 에 대해 R0/R1/R2 규제 변형 비교")
    ap.add_argument("--reg", default=None, choices=list(REG_VARIANTS),
                    help="본실행에 쓸 규제 설정 (기본 ACTIVE_REG)")
    ap.add_argument("--dev-window-probe", action="store_true",
                    help="확인 3: A0 에 한해 Dev 3개월 vs 6개월 best_iteration 비교")
    a = ap.parse_args()

    global ACTIVE_REG
    if a.reg:
        ACTIVE_REG = a.reg
    _onedrive_notice()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    a0, info, addable = base_feature_pool()
    log.info(f"A0 기준선 피처 {info['n_a0']}개 "
             f"(전체 {info['all_features']} − 거시 {info['n_macro']} "
             f"− 상호작용 {info['n_interaction']} − 무분산 {info['n_constant']} "
             f"− CG01/C302 {info['n_cg_c302']}) / 되넣기 후보 {info['n_addable']}개 함께 로딩")

    if a.list:
        for k, v in SCENARIOS.items():
            print(f"  {k}  {v['desc']}")
        return

    targets = list(SCENARIOS) if a.run_all else (a.run or [])
    # ★ [2026-09-02] --seed-probe / --reg-probe 시나리오를 targets 에 합친다.
    #   합치지 않으면 아래 need_pre5 가 비어 CRIF·폐업 컬럼을 조인하지 않고,
    #   resolve_features 의 `if a in available` 이 그 컬럼을 조용히 건너뛴다.
    #   결과: `--seed-probe A2` 가 피처 152개(=A0)로 돌아가면서 라벨만 A2 였다.
    #   AUC 가 A0 와 완전히 동일하게 나오는 것으로 발견했다 (2026-09-02).
    targets = list(dict.fromkeys(
        targets + list(a.seed_probe or []) + (["A0"] if a.reg_probe else [])))
    if a.dev_window_probe:
        targets = targets or ["A0"]

    log.info("패널 로딩...")
    df = load_base(a0, addable)
    log.info(f"  shape={df.shape}  메모리 {df.memory_usage(deep=False).sum()/1e9:.2f}GB")

    need_pre5 = {c for t in targets for c in SCENARIOS[t]["add"]
                 if c in LEAK_OPNP + LEAK_CRIF_AGG}
    if need_pre5:
        df = join_leak_from_pre_step5(df, sorted(need_pre5))
    if any(c in SCENARIOS[t]["add"] for t in targets for c in LEAK_CRIF_RLS):
        df = join_crif_release_from_raw(df)
    available = list(df.columns)

    if a.seed_probe:
        seeds = [int(x) for x in a.seeds.split(",")]
        out = []
        for sc in a.seed_probe:
            feats = resolve_features(sc, a0, available)
            for sd in seeds:
                prm = active_params(); prm["random_state"] = sd
                r = run_one(sc, df, feats, save_model=False, params=prm, tag=f"seed{sd}")
                r["seed"] = sd
                out.append(r)
        # ★ [2026-09-02] 덮어쓰지 않고 (시나리오, 시드) 키로 병합한다.
        #   초판은 매 실행이 파일을 통째로 갈아엎어, A2 를 재면 직전에 잰 A0
        #   기준선이 사라졌다. 기준선이 없으면 ΔAUC 를 계산할 수 없다.
        p = OUT_DIR / "seed_variance_probe.json"
        prev = []
        if p.exists():
            try:
                prev = json.loads(p.read_text(encoding="utf-8"))
            except Exception:                                     # noqa: BLE001
                prev = []
        merged = {(r.get("scenario"), r.get("seed")): r for r in prev}
        for r in out:
            merged[(r["scenario"], r["seed"])] = r
        p.write_text(json.dumps(sorted(merged.values(),
                                       key=lambda r: (r["scenario"], r["seed"])),
                                ensure_ascii=False, indent=2), encoding="utf-8")
        _verify_written(p, 100)
        print()
        print(f"{'시나리오':8s} {'시드':>6s} {'best':>6s} {'Valid AUC':>10s}")
        print("-" * 36)
        for r in out:
            print(f"{r['scenario']:8s} {r['seed']:6d} {r['best_iteration']:6d} "
                  f"{r['valid']['auc']:10.4f}")
        import statistics as st
        print()
        for sc in a.seed_probe:
            v = [r["valid"]["auc"] for r in out if r["scenario"] == sc]
            sd = st.stdev(v) if len(v) > 1 else 0.0
            print(f"  {sc:6s} 평균 {st.mean(v):.4f}  표준편차 {sd:.4f}  "
                  f"범위 {min(v):.4f}~{max(v):.4f}  폭 {max(v)-min(v):.4f}")
        return

    if a.reg_probe:
        feats = resolve_features("A0", a0, available)
        out = []
        for tag, over in REG_VARIANTS.items():
            prm = dict(PARAMS); prm.update(over)
            if tag != "R0":
                prm["n_estimators"] = REG_PROBE_N_ESTIMATORS
            log.info(f"[규제 프로브] {tag}: {over or '(현재 설정)'}")
            r = run_one("A0", df, feats, save_model=False, params=prm, tag=tag)
            r["overrides"] = over
            out.append(r)
        p = OUT_DIR / "A0_reg_probe.json"
        p.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        _verify_written(p, 100)
        print()
        print(f"{'변형':5s} {'best':>6s} {'cap':>5s} {'Train':>8s} {'Dev':>8s} {'Valid':>8s} "
              f"{'Tr-Va격차':>10s} {'Dev-Va':>8s} {'K-S':>7s} {'PSI':>7s}")
        print("-" * 82)
        for r in out:
            print(f"{r['reg_variant']:5s} {r['best_iteration']:6d} "
                  f"{('예' if r['hit_cap'] else '아니오'):>5s} "
                  f"{r['train']['auc']:8.4f} {r['dev']['auc']:8.4f} {r['valid']['auc']:8.4f} "
                  f"{r['train']['auc']-r['valid']['auc']:10.4f} "
                  f"{r['dev']['auc']-r['valid']['auc']:8.4f} "
                  f"{r['valid']['ks']:7.4f} {r['psi_train_valid']:7.4f}")
        return

    if a.dev_window_probe:
        feats = resolve_features("A0", a0, available)
        out = []
        for ds, label in ((split_spec.DEV_START, "Dev 3개월"), ("202307", "Dev 6개월")):
            log.info(f"[Dev 창 비교] {label} (dev_start={ds})")
            r = run_one("A0", df, feats, dev_start=ds, save_model=False)
            r["label"] = label
            out.append(r)
        p = OUT_DIR / "A0_dev_window_probe.json"
        p.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        _verify_written(p, 100)
        print(f"\n{'창':10s} {'best_iter':>10s} {'Dev AUC':>10s} {'Valid AUC':>11s} {'Dev 양성':>9s}")
        for r in out:
            print(f"{r['label']:10s} {r['best_iteration']:10d} {r['dev']['auc']:10.4f} "
                  f"{r['valid']['auc']:11.4f} {r['pos_dev']:9,d}")
        return

    results = []
    for t in targets:
        feats = resolve_features(t, a0, available)
        results.append(run_one(t, df, feats))
        p = OUT_DIR / f"ablation_A_results_{ACTIVE_REG}.json"
        merged = _merge_results(p, results)
        p.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
        _verify_written(p, 100)

    # 이번 실행에 A0 가 없으면 저장된 결과에서 가져온다 (부분 실행 대응).
    pool = _merge_results(OUT_DIR / f"ablation_A_results_{ACTIVE_REG}.json", results)
    base = next((r for r in pool if r["scenario"] == "A0"), None)
    results = pool
    print(f"\n{'ID':4s} {'피처':>5s} {'best':>5s} {'Train':>7s} {'Dev':>7s} "
          f"{'Valid':>7s} {'ΔAUC':>8s} {'Gini':>7s} {'K-S':>7s} {'PSI':>7s}")
    print("-" * 78)
    for r in results:
        d = (r["valid"]["auc"] - base["valid"]["auc"]) if base else float("nan")
        print(f"{r['scenario']:4s} {r['n_features']:5d} {r['best_iteration']:5d} "
              f"{r['train']['auc']:7.4f} {r['dev']['auc']:7.4f} {r['valid']['auc']:7.4f} "
              f"{d:+8.4f} {r['valid']['gini']:7.4f} {r['valid']['ks']:7.4f} "
              f"{r['psi_train_valid']:7.4f}")


if __name__ == "__main__":
    main()
