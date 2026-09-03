"""
======================================================================
STAGE 6 D축 — 거시 결합 방식 Ablation (실거시 데이터)
======================================================================
기준서: eda_pipeline/output/validation/D_AXIS_SUCCESS_CRITERIA.md (개정 R1)
선행:   eda_pipeline/step33_macro_gate1.py  — 게이트 1 8/8 통과 필수

설계 원칙
--------
  - D0~D5 는 **거시 컬럼만** 다르다. 기업 고유 피처(노출도 포함)는 전 시나리오 동일.
    노출도(exp_*)는 거시가 아니라 기업 재무 비율이므로 D0 에도 넣는다.
    그래야 D1~D5 의 차이가 순수하게 거시 컬럼의 기여가 된다.
  - 학습 파라미터는 step30 A축과 동일한 것을 import 해서 쓴다 (REG_VARIANTS['R2']).
    자체 사본을 두면 A/B/C 축과 비교가 어긋난다.
  - scale_pos_weight 는 시나리오별 Train 부분집합에서 매번 재계산한다.
  - early stopping 은 Dev(202310~202312) 로만 한다. Valid 는 최종 1회 평가 전용.
  - 시드 3회(42/7/2024). |ΔAUC| < 0.003 은 노이즈로 본다.

★ 확률 보정 (기준서 게이트 3)
  scale_pos_weight 로 학습하면 예측 PD 가 실제 부도율보다 과대추정된다.
  캘리브레이션 지표(G3-2~G3-5) 산출 전에 반드시 보정한다.
  네 가지를 전부 산출해 JSON 에 남기고, 결과표에 쓸 주보정은 --calib 로 고른다.
  주보정 선택은 D0(기준선) 근거로만 하고, 고른 뒤에는 D0~D5 에 동일 적용한다.

  raw          보정 없음. 얼마나 부풀어 있는지 보여주는 대조군.
  prior        prior correction (해석적). 가중 학습이 부풀린 양성 오즈의 역변환.
                   odds_corr = odds_model / spw
                   p_corr    = p / (p + (1 - p) * spw)
               적합 파라미터가 없어 과적합이 불가능하다. 다만 강한 규제(R2)로
               트리 확률이 수축돼 있으면 과소보정된다 — D0 실측에서 확인된다.
  platt_train  Platt scaling. Train 구간(~202309) 예측 로짓에 로지스틱 1개 적합.
               기준서 "보정은 Train 구간에서만 학습해 Valid 에 적용" 을 문자
               그대로 만족하는 방식이다.
  platt_dev    Platt scaling. Dev 구간(202310~202312) 적합. Dev 도 SPLIT=='TRAIN'
               안이지만 Valid 와 시기가 인접해 기저율이 비슷하므로, 절편이
               Valid 기저율을 대신 알려 주는 효과가 있다. 그러면 거시가 없어도
               캘리브레이션이 좋아 보여 D축 판정이 무뎌진다. 참고용으로만 남긴다.

  어느 방식을 쓰든 D0~D5 에 동일하게 적용되므로 시나리오 간 비교는 공정하다.
  보정 전후 평균 PD 는 네 방식 모두 기록한다.

Usage
-----
    python -m eda_pipeline.step34_d_axis --list
    python -m eda_pipeline.step34_d_axis --run-all
    python -m eda_pipeline.step34_d_axis --run D0 D3 --seeds 42
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
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

from eda_pipeline import config, split_spec
from eda_pipeline.leaky_cols import feature_columns
from eda_pipeline.step6_macro_integration import INTERACTIONS
from eda_pipeline.step30_stage6_ablation import (
    ACTIVE_REG, EARLY_STOPPING_ROUNDS, PARAMS, REG_PROBE_N_ESTIMATORS,
    REG_VARIANTS, calculate_ks, calculate_psi, evaluate,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("daxis")

TARGET = "IS_BUDO_12M"
OUT_DIR = config.VALIDATION_DIR / "d_axis"
RESULT_JSON = OUT_DIR / "d_axis_results.json"
DEFAULT_SEEDS = (42, 7, 2024)

INTERACTION_8 = [n for n, _, _ in INTERACTIONS if not n.endswith("_hybrid")]
INTERACTION_HYBRID = [n for n, _, _ in INTERACTIONS if n.endswith("_hybrid")]
# D4 에서 실측 수출비중 기반 2종을 하이브리드 2종으로 갈아끼운다.
FX_ACTUAL = ["fx_shock_x_export", "eur_shock_x_export"]

# ══════════════════════════════════════════════════════════════════════
# D6 — 선별 상호작용 3종 + 단조 제약 (2026-09-02 확정)
# ══════════════════════════════════════════════════════════════════════
# D2/D3 의 상호작용 8종은 gain 이 0 에 가까운 항이 다수였다. D6 은 경로가
# 명확하고 부호를 사전에 정할 수 있는 3종만 남기고, 그 부호를 **단조 제약으로
# 강제**한다. 외삽 구간(스트레스 시나리오)에서 방향이 뒤집히지 않게 하는 것이
# 목적이다 — D축 §5 에서 거시 차분 지표의 부호가 Train/Valid 사이에 뒤집힌
# 문제에 대한 처방이다.
#
#   (name, 거시항, 노출도, 단조부호)
#   bsi_x_industry        BSI 업황이 좋아지면 제조업 부도는 줄어든다        -> -1
#   credit_spread_lv_x_lev 신용스프레드가 벌어지고 차입 의존이 크면 늘어난다 -> +1
#   fx_shock_x_export     환율 충격은 수출기업에 양방향이라 부호를 못 정한다 ->  0
#
# ★ credit_spread 는 **수준**을 쓴다 (지시서 명세). 패널의 기존
#   `credit_spread_x_lev` 는 `credit_spread_diff12` 기반이므로 이름을 나눴다.
#   수준 계열은 Phase 6 산출물 `model_input_monthly_level.csv` 의
#   `LV_credit_spread` 다 (Group A, 시차 0, 롤링 없음).
#
# ★ CPI_core 는 제외한다. 누적 지수의 단조 증가와 부도율의 단조 증가가 겹친
#   **공통 추세**이며 인과가 아니다. 단조 제약을 걸면 외삽 시 발산한다.
#   (E0 진단에서 CPI_core 수준의 Train/Valid 상관이 +0.978/+0.910 으로
#    강해진 것도 추세 동행의 결과로 읽는 것이 맞다.)
D6_LEVEL_INTERACTION = "credit_spread_lv_x_lev"
D6_LEVEL_MACRO = "LV_credit_spread"
D6_TERMS: list[tuple[str, int]] = [
    ("bsi_x_industry", -1),
    (D6_LEVEL_INTERACTION, +1),
    ("fx_shock_x_export", 0),
]
D6_NAMES = [n for n, _ in D6_TERMS]
D6_MONO = dict(D6_TERMS)

# ══════════════════════════════════════════════════════════════════════
# D7 — D6 에서 fx_shock_x_export 를 뺀 2종 (2026-09-02 결정)
# ══════════════════════════════════════════════════════════════════════
# `fx_shock_x_export` 는 D6 · D6m 양쪽에서 **gain 0.000 / 159위(최하위)** 였다.
# 트리가 한 번도 이 변수로 분기하지 않았다. D축 초판(상호작용 8종)에서도
# gain 0.000 / 255위였으므로 재현된 결과다.
#
# 원인은 노출도 쪽으로 본다 — `exp_fx` 는 AA17(생산판매) 파생이고 obv 스파인에서
# 결측 89.51% 다. 즉 90%의 행에서 이 항이 NaN 이므로 분기 재료가 되지 못한다.
# 충격 정의(USD_KRW 월간 로그수익률)의 문제인지 노출도의 문제인지는 이 실행으로
# 갈리지 않는다. `export_price_index_KOR x exp_fx` 와의 대조는 E2 후보로 남긴다.
#
# 제약 부호는 D6 과 같다. 항을 하나 뺀 것 외에 바뀐 것이 없다.
D7_NAMES = [n for n in D6_NAMES if n != "fx_shock_x_export"]
D7_MONO = {k: v for k, v in D6_MONO.items() if k in D7_NAMES}

# ══════════════════════════════════════════════════════════════════════
# E축 4단계 — D8 (거시 상호작용 14개) / 2026-09-02
# ══════════════════════════════════════════════════════════════════════
# 명세는 `step37_macro_interactions` 가 만든 JSON 을 **정본으로 읽는다.**
# 여기에 목록을 복제하면 두 곳이 갈라진다 (AC12 리네임 사고와 같은 형태).
#
# ★ 기반(base)이 D0/D6m 과 다르다. D8 은 **C1 기반**이다 — `STD_INDS_MID2` 를
#   제거한 구성이다. C축에서 C1(0.8595)이 A0(0.8434)보다 높았고 최종 구성으로
#   확정됐기 때문이다.
#   그래서 D8 을 D6m 과 바로 비교하면 **두 가지가 동시에 바뀐다**
#   (MID2 제거 + 거시 14개). 거시 효과만 분리하려면 같은 기반의 대조가 필요하다.
#   -> `D6mc` (C1 기반 + D6m 의 3종)를 함께 둔다. 이것이 D8 의 정당한 기준선이고,
#      동시에 "최종 구성 = C1 + 거시 3종 + 제약" 을 처음으로 실측하는 것이기도 하다
#      (D6m 은 MID2 를 포함한 기반에서 측정됐다).
C1_DROP_BASE = ["STD_INDS_MID2"]
E14_SPEC_JSON = config.VALIDATION_DIR / "macro_interaction_candidates.json"


def load_e14_spec() -> list[dict]:
    """step37 이 만든 상호작용 명세. 이 파일이 정본이다."""
    if not E14_SPEC_JSON.exists():
        raise FileNotFoundError(
            f"{E14_SPEC_JSON} 없음. 먼저 실행:\n"
            f"  python -m eda_pipeline.step37_macro_interactions")
    return json.loads(E14_SPEC_JSON.read_text(encoding="utf-8"))["final"]


def add_e14_interactions(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str], dict]:
    """D8 상호작용 14개를 메모리에서 만든다. 패널을 다시 만들지 않는다."""
    from eda_pipeline.step35_macro_level_diagnosis import build_extra_candidates
    from eda_pipeline.step37_macro_interactions import (
        YOUNG_AGE_YEARS, load_macro,
    )

    spec = load_e14_spec()
    macro = load_macro()

    out = df
    # 파생 노출도 — exp_young 은 패널에 없다 (BUSINESS_AGE 는 연 단위다)
    if any(r["exposure"] == "exp_young" for r in spec) and "exp_young" not in out.columns:
        assert "BUSINESS_AGE" in out.columns, "BUSINESS_AGE 가 패널에 없다"
        age = pd.to_numeric(out["BUSINESS_AGE"], errors="coerce")
        out = out.copy()
        out["exp_young"] = (age <= YOUNG_AGE_YEARS).astype(float).mask(age.isna())
        log.info("  D8 exp_young 생성 (BUSINESS_AGE <= %d년) — 1 비율 %.2f%%",
                 YOUNG_AGE_YEARS, out["exp_young"].mean() * 100)

    names, mono = [], {}
    made = {}
    for r in spec:
        m, e, t = r["macro"], r["exposure"], r["term"]
        if m not in macro.columns:
            raise KeyError(f"거시 원천에 {m} 없음")
        assert e in out.columns, f"노출도 {e} 가 패널에 없다"
        mv = pd.to_numeric(macro[m], errors="coerce")
        made[t] = (out["BASE_YM"].map(mv).astype(float)
                   * pd.to_numeric(out[e], errors="coerce")).astype("float32")
        names.append(t)
        mono[t] = int(r["monotone"])
    out = pd.concat([out, pd.DataFrame(made, index=out.index)], axis=1)
    log.info("  D8 상호작용 %d개 생성 — 제약 %s",
             len(names), {k: v for k, v in mono.items() if v})
    return out, names, mono


#: D8 실행 시 채워진다 (명세 JSON 에서 읽으므로 임포트 시점에 고정하지 않는다)
E14_NAMES: list[str] = []
E14_MONO: dict[str, int] = {}
E14_TOP_NAMES: list[str] = []
E14_TOP_MAX = 15


def e14_surviving_terms(names: list[str]) -> list[str]:
    """D8 결과에서 **gain 이 0 이 아닌** 항만 남긴다 (D8s).

    "gain 상위 15개만 유지" 의 실질은 **쓰이지 않은 항을 버리는 것**이다.
    상호작용이 14개뿐이므로 상위 15 는 전부와 같다 — 의미가 생기는 기준은
    "트리가 한 번이라도 이 변수로 분기했는가" 다. 개수를 지키려고 gain 0 인
    항을 남기지 않는다.
    """
    if not RESULT_JSON.exists():
        raise FileNotFoundError(
            f"{RESULT_JSON} 없음. D8 을 먼저 실행할 것")
    rows = [r for r in json.loads(RESULT_JSON.read_text(encoding="utf-8"))
            if r["scenario"] == "D8"]
    if not rows:
        raise SystemExit("D8 결과가 없다. D8 을 먼저 실행할 것")
    acc: dict[str, list[float]] = {n: [] for n in names}
    for r in rows:
        for e in r.get("interaction_gain", []):
            if e["feature"] in acc:
                acc[e["feature"]].append(float(e["gain_pct"]))
    mean = {n: (sum(v) / len(v) if v else 0.0) for n, v in acc.items()}
    keep = [n for n in names if mean.get(n, 0.0) > 0.0]
    keep.sort(key=lambda n: -mean[n])
    dropped = [n for n in names if n not in keep]
    if dropped:
        log.info("  D8s 제외 (gain 0.000): %s", dropped)
    return keep[:E14_TOP_MAX]

SCENARIOS = {
    "D0": dict(desc="기준선. 거시·상호작용 전부 제외 (기업 고유 + 노출도만)",
               macro="none", inter="none"),
    "D1": dict(desc="D0 + 거시 원본만 (상호작용 없음) — 시점 더미 팔",
               macro="reduced", inter="none"),
    "D2": dict(desc="D0 + 상호작용 8종만 (거시 원본 없음) — STAGE 5 설계 팔",
               macro="none", inter="core8"),
    "D3": dict(desc="D0 + 거시 원본 + 상호작용 8종 (완전형)",
               macro="reduced", inter="core8"),
    "D4": dict(desc="D3 에서 수출 노출도 실측 -> 하이브리드 (fx actual vs hybrid)",
               macro="reduced", inter="hybrid8"),
    "D5": dict(desc="D3 에서 거시 축소 해제 (91 -> 178 전부)",
               macro="full", inter="core8"),
    "D6": dict(desc="D0 + 선별 상호작용 3종 (단조 제약 없음)",
               macro="none", inter="d6three", mono=False),
    "D6m": dict(desc="D6 + 단조 제약 (BSI -1 / 신용스프레드 +1 / FX 0)",
                macro="none", inter="d6three", mono=True),
    "D7": dict(desc="D6 − fx_shock_x_export (거시 2종, 제약 없음)",
               macro="none", inter="d7two", mono=False),
    "D7m": dict(desc="D7 + 단조 제약 (BSI -1 / 신용스프레드 +1) — 최종 후보",
                macro="none", inter="d7two", mono=True),
    # ── E축 4단계 ──────────────────────────────────────────────
    "D6mc": dict(desc="C1 기반 + 거시 3종 + 단조 제약 (D8 의 정당한 기준선)",
                 macro="none", inter="d6three", mono=True,
                 drop_base=C1_DROP_BASE),
    "D8": dict(desc="C1 기반 + 거시 상호작용 14종 + 단조 제약",
               macro="none", inter="e14", mono=True, drop_base=C1_DROP_BASE),
    "D8s": dict(desc="D8 의 gain 상위 15개만 유지 (별도 실행 필요)",
                macro="none", inter="e14_top", mono=True,
                drop_base=C1_DROP_BASE),
}


# ══════════════════════════════════════════════════════════════════════
# 피처 구성
# ══════════════════════════════════════════════════════════════════════

def panel_path(tag: str = "real") -> Path:
    suffix = f"_{tag}" if tag else ""
    p = config.OUTPUT_DIR / f"nh_panel_macro_12m_obv_none{suffix}.parquet"
    if not p.exists():
        raise FileNotFoundError(
            f"{p} 없음. 먼저 실행:\n"
            f"  python -m eda_pipeline.step6_macro_integration --tag {tag}")
    return p


def macro_source_columns() -> list[str]:
    """거시 원천 CSV 의 컬럼(=거시 지표 전체 178개)."""
    m = pd.read_csv(config.macro_input_path(), nrows=1)
    return [c for c in m.columns if c != "BASE_YM"]


def build_pools(cols: list[str], macro_all: set[str]) -> tuple[list, list, dict]:
    """패널 컬럼을 (기업고유, 거시원본) 으로 가른다. 상호작용은 별도 목록."""
    feats = feature_columns(pd.DataFrame(columns=cols), target=TARGET,
                            include_suspect=False, extra_exclude=["V_BRANCH_CODE"])
    inter_all = set(n for n, _, _ in INTERACTIONS)
    macro_pure = [c for c in feats if c in macro_all]
    base = [c for c in feats if c not in macro_all and c not in inter_all]
    info = dict(panel_cols=len(cols), all_features=len(feats),
                n_macro_pure=len(macro_pure), n_base=len(base),
                n_interaction_in_panel=len([c for c in cols if c in inter_all]))
    return base, macro_pure, info


def resolve_features(sc: str, base: list[str], macro_reduced: list[str],
                     macro_extra: list[str]) -> list[str]:
    spec = SCENARIOS[sc]
    feats = [c for c in base if c not in set(spec.get("drop_base") or ())]
    if spec["macro"] == "reduced":
        feats += macro_reduced
    elif spec["macro"] == "full":
        feats += macro_reduced + macro_extra
    if spec["inter"] == "core8":
        feats += INTERACTION_8
    elif spec["inter"] == "hybrid8":
        feats += [c for c in INTERACTION_8 if c not in FX_ACTUAL] + INTERACTION_HYBRID
    elif spec["inter"] == "d6three":
        feats += D6_NAMES
    elif spec["inter"] == "d7two":
        feats += D7_NAMES
    elif spec["inter"] == "e14":
        feats += E14_NAMES
    elif spec["inter"] == "e14_top":
        feats += E14_TOP_NAMES
    return feats


def macro_feature_set(feats: list[str], macro_all: set[str]) -> set[str]:
    """거시 gain 비중 계산에 쓸 '거시 계열' = 거시 원본 + 상호작용."""
    inter_all = (set(n for n, _, _ in INTERACTIONS) | set(D6_NAMES)
                 | set(D7_NAMES) | set(E14_NAMES))
    return {c for c in feats if c in macro_all or c in inter_all}


def macro_level_path() -> Path:
    """Phase 6 수준·누적 계열 CSV. cleaned 와 같은 디렉터리에 있다."""
    return config.macro_input_path().with_name("model_input_monthly_level.csv")


def add_level_interaction(df: pd.DataFrame) -> pd.DataFrame:
    """D6 전용 — `LV_credit_spread x exp_rate` 를 메모리에서 만든다.

    패널을 다시 만들지 않는다. 수준 계열은 Phase 6 산출물에만 있고 D6 하나만
    쓰므로, step6 에 넣어 172개 산출물을 흔들 이유가 없다.
    """
    if D6_LEVEL_INTERACTION in df.columns:
        return df
    p = macro_level_path()
    if not p.exists():
        raise FileNotFoundError(
            f"{p} 없음. Phase 6 산출물이 필요하다:\n"
            f"  python -m api_data_processing.impute_data")
    assert "exp_rate" in df.columns, "exp_rate 가 패널에 없다 (노출도 미생성)"
    n0 = len(df)
    lv = pd.read_csv(p, dtype={"BASE_YM": str},
                     usecols=["BASE_YM", D6_LEVEL_MACRO])
    lv["BASE_YM"] = lv["BASE_YM"].astype(str).str.strip()
    # step6 는 거시 CSV 에 MACRO_LAG_MONTHS 를 추가로 걸 수 있다. 수준 계열은
    # 그 경로를 타지 않으므로 여기서 같은 시차를 직접 맞춘다. 맞추지 않으면
    # D6 의 이 항만 다른 시차를 쓰게 된다.
    from eda_pipeline.step6_macro_integration import MACRO_LAG_MONTHS as _mlag
    if _mlag:
        lv = lv.sort_values("BASE_YM")
        lv[D6_LEVEL_MACRO] = lv[D6_LEVEL_MACRO].shift(_mlag)
        lv = lv.dropna(subset=[D6_LEVEL_MACRO])
        log.info("  D6 수준 계열에 step6 추가 시차 %d개월 동일 적용", _mlag)
    assert not lv.duplicated("BASE_YM").any(), "Phase 6 수준 계열에 BASE_YM 중복"
    out = df.merge(lv, on="BASE_YM", how="left")
    assert len(out) == n0, f"수준 계열 조인에서 행수 변동: {n0} -> {len(out)}"
    miss = int(out[D6_LEVEL_MACRO].isna().sum())
    if miss:
        # ffill/bfill 로 메우지 않는다 — bfill 은 미래를 과거로 끌어온다.
        bad = (out.loc[out[D6_LEVEL_MACRO].isna(), "BASE_YM"]
                  .astype(str).drop_duplicates().sort_values().tolist())
        raise ValueError(
            f"{D6_LEVEL_MACRO} 결측 {miss}개 — BASE_YM {len(bad)}개월: {bad[:24]}\n"
            f"  수준 계열 범위: {lv['BASE_YM'].min()} ~ {lv['BASE_YM'].max()}")
    out[D6_LEVEL_INTERACTION] = (out[D6_LEVEL_MACRO].astype(float)
                                 * out["exp_rate"].astype(float))
    out = out.drop(columns=[D6_LEVEL_MACRO])
    v = out[D6_LEVEL_INTERACTION]
    log.info("  D6 %s 생성 — 결측 %.2f%% / 중앙값 %.6f",
             D6_LEVEL_INTERACTION, v.isna().mean() * 100, float(v.median()))
    return out


def monotone_vector(sc: str, feats: list[str]) -> list[int] | None:
    """시나리오의 단조 제약 벡터. 제약이 없으면 None.

    LightGBM 의 monotone_constraints 는 **피처 순서와 1:1 로 맞는 리스트**다.
    이름으로 지정할 수 없으므로 여기서 feats 순서대로 만든다.
    """
    if not SCENARIOS[sc].get("mono"):
        return None
    mono_map = dict(D6_MONO)
    mono_map.update(D7_MONO)                 # 두 맵은 같은 부호를 공유한다
    mono_map.update(E14_MONO)
    vec = [int(mono_map.get(f, 0)) for f in feats]
    named = {f: v for f, v in zip(feats, vec) if v}
    if not named:
        log.warning("  %s: 단조 제약 대상이 없다 — 제약 없이 학습한다", sc)
        return None
    log.info("  단조 제약 %d개: %s", len(named), named)
    return vec


# ══════════════════════════════════════════════════════════════════════
# 적재
# ══════════════════════════════════════════════════════════════════════

def load_panel(path: Path, cols: list[str]) -> pd.DataFrame:
    con = duckdb.connect()
    try:
        types = {r[0]: r[1] for r in
                 con.execute(
                     f"DESCRIBE SELECT * FROM read_parquet('{path.as_posix()}')").fetchall()}
        parts = ["V_BZNO", "BASE_YM", TARGET]
        for c in cols:
            parts.append(f'"{c}"' if types.get(c) == "VARCHAR"
                         else f'CAST("{c}" AS FLOAT) AS "{c}"')
        df = con.execute(
            f'SELECT {", ".join(parts)} FROM read_parquet(\'{path.as_posix()}\')').df()
    finally:
        con.close()
    for c in cols:
        if not pd.api.types.is_numeric_dtype(df[c]):
            df[c] = df[c].astype("category")
    df[TARGET] = df[TARGET].astype("int8")
    df["BASE_YM"] = df["BASE_YM"].astype(str)
    return df


def join_macro_extra(df: pd.DataFrame, extra: list[str]) -> pd.DataFrame:
    """거시 축소로 빠진 컬럼을 원천 CSV 에서 BASE_YM 조인으로 되붙인다.

    D5(축소 해제) 전용. 패널을 다시 만들지 않고 메모리에서만 붙인다.
    """
    want = [c for c in extra if c not in df.columns]
    if not want:
        return df
    n0 = len(df)
    m = pd.read_csv(config.macro_input_path(), dtype={"BASE_YM": str},
                    usecols=["BASE_YM"] + want)
    m["BASE_YM"] = m["BASE_YM"].astype(str).str.strip()
    assert not m.duplicated("BASE_YM").any(), "거시 원천에 BASE_YM 중복"
    out = df.merge(m, on="BASE_YM", how="left")
    assert len(out) == n0, f"거시 추가 조인에서 행수 변동: {n0} -> {len(out)}"
    miss = int(out[want].isna().sum().sum())
    assert miss == 0, f"거시 추가 조인 후 결측 {miss}개 — 원천 기간이 패널을 못 덮는다"
    for c in want:
        out[c] = out[c].astype("float32")
    log.info("  거시 추가 %d개 조인 — 행수 %s 유지", len(want), f"{n0:,}")
    return out


# ══════════════════════════════════════════════════════════════════════
# 확률 보정
# ══════════════════════════════════════════════════════════════════════

def prior_correction(p: np.ndarray, spw: float) -> np.ndarray:
    """가중 학습이 부풀린 양성 오즈를 되돌린다. 적합 파라미터 없음."""
    p = np.clip(np.asarray(p, dtype=float), 1e-12, 1 - 1e-12)
    odds = p / (1 - p) / spw
    return odds / (1 + odds)


def fit_platt(logit_dev: np.ndarray, y_dev: np.ndarray) -> LogisticRegression:
    lr = LogisticRegression(C=1e6, solver="lbfgs", max_iter=1000)
    lr.fit(logit_dev.reshape(-1, 1), y_dev)
    return lr


def _logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(np.asarray(p, dtype=float), 1e-12, 1 - 1e-12)
    return np.log(p / (1 - p))


# ══════════════════════════════════════════════════════════════════════
# 캘리브레이션 지표
# ══════════════════════════════════════════════════════════════════════

def brier(y: np.ndarray, p: np.ndarray) -> float:
    return float(np.mean((np.asarray(p, dtype=float) - np.asarray(y, dtype=float)) ** 2))


def monthly_calibration(ym: pd.Series, y: np.ndarray, p: np.ndarray) -> dict:
    """G3-2 월별 예측평균PD vs 실제부도율 상관 / G3-3 시점별 건수 MAPE."""
    d = pd.DataFrame({"ym": np.asarray(ym), "y": np.asarray(y, dtype=float),
                      "p": np.asarray(p, dtype=float)})
    g = d.groupby("ym").agg(n=("y", "size"), actual_cnt=("y", "sum"),
                            actual_rate=("y", "mean"), pred_mean=("p", "mean"))
    g["pred_cnt"] = g["pred_mean"] * g["n"]
    ok = g["actual_cnt"] > 0
    mape = float(np.mean(np.abs(g.loc[ok, "pred_cnt"] - g.loc[ok, "actual_cnt"])
                         / g.loc[ok, "actual_cnt"]) * 100)
    corr = float(g["pred_mean"].corr(g["actual_rate"])) if len(g) > 2 else float("nan")
    return {"corr_pd_rate": corr, "count_mape_pct": mape,
            "monthly": [{"ym": str(i), "n": int(r.n),
                         "actual_cnt": int(r.actual_cnt),
                         "actual_rate": float(r.actual_rate),
                         "pred_mean_pd": float(r.pred_mean),
                         "pred_cnt": float(r.pred_cnt)} for i, r in g.iterrows()]}


def decile_calibration(y: np.ndarray, p: np.ndarray, bins: int = 10) -> dict:
    """G3-5 예측PD 10분위별 실제부도율. 대각선과의 거리(ECE/MCE)를 함께 낸다."""
    p = np.asarray(p, dtype=float)
    y = np.asarray(y, dtype=float)
    edges = np.quantile(p, np.linspace(0, 1, bins + 1))
    edges[0], edges[-1] = -np.inf, np.inf
    rows, ece, mce = [], 0.0, 0.0
    for i in range(bins):
        m = (p >= edges[i]) & (p < edges[i + 1])
        if not m.any():
            continue
        pm, am, w = float(p[m].mean()), float(y[m].mean()), float(m.mean())
        rows.append({"decile": i + 1, "n": int(m.sum()),
                     "pred_mean": pm, "actual_rate": am, "gap": am - pm})
        ece += w * abs(am - pm)
        mce = max(mce, abs(am - pm))
    return {"ece": float(ece), "mce": float(mce), "deciles": rows}


# ══════════════════════════════════════════════════════════════════════
# 1회 학습
# ══════════════════════════════════════════════════════════════════════

def active_params(seed: int) -> dict:
    p = dict(PARAMS)
    p.update(REG_VARIANTS[ACTIVE_REG])
    if ACTIVE_REG != "R0":
        p["n_estimators"] = REG_PROBE_N_ESTIMATORS
    p["random_state"] = seed
    return p


def run_one(sc: str, df: pd.DataFrame, feats: list[str], macro_set: set[str],
            seed: int, panel_name: str = "") -> dict:
    prm = active_params(seed)
    mono = monotone_vector(sc, feats)
    if mono is not None:
        prm["monotone_constraints"] = mono
    ym = df["BASE_YM"]
    tr = ym < split_spec.DEV_START
    dv = (ym >= split_spec.DEV_START) & (ym <= split_spec.DEV_END)
    va = ym >= split_spec.VALID_START

    X, y = df[feats], df[TARGET].astype(int)
    ytr, ydv, yva = y[tr].values, y[dv].values, y[va].values
    n_pos = int(ytr.sum())
    spw = (len(ytr) - n_pos) / max(n_pos, 1)

    log.info("  [%s seed=%d] 피처 %d / Train %s (양성 %s) / Dev %s / Valid %s / spw=%.2f",
             sc, seed, len(feats), f"{int(tr.sum()):,}", f"{n_pos:,}",
             f"{int(dv.sum()):,}", f"{int(va.sum()):,}", spw)

    t0 = time.time()
    model = lgb.LGBMClassifier(scale_pos_weight=spw, **prm)
    model.fit(X[tr], ytr, eval_set=[(X[dv], ydv)], eval_metric="auc",
              callbacks=[lgb.early_stopping(EARLY_STOPPING_ROUNDS, verbose=False)])
    elapsed = time.time() - t0

    p_tr = model.predict_proba(X[tr])[:, 1]
    p_dv = model.predict_proba(X[dv])[:, 1]
    p_va = model.predict_proba(X[va])[:, 1]

    # ── 확률 보정 ────────────────────────────────────────────────
    # 세 방식을 전부 산출한다. 주보정은 D0 에서 근거를 보고 고르며,
    # 고른 뒤에는 D0~D5 전부에 같은 것을 적용한다 (--calib).
    lg_va = _logit(p_va)
    pc_va = prior_correction(p_va, spw)
    platt_tr = fit_platt(_logit(p_tr), ytr)      # 기준서 문구 그대로: Train 구간 적합
    platt_dv = fit_platt(_logit(p_dv), ydv)      # Dev 적합 (SPLIT=='TRAIN' 내부)
    pt_va = platt_tr.predict_proba(lg_va.reshape(-1, 1))[:, 1]
    pd_va = platt_dv.predict_proba(lg_va.reshape(-1, 1))[:, 1]

    ym_va = ym[va]
    cal = {"raw": (p_va, monthly_calibration(ym_va, yva, p_va)),
           "prior": (pc_va, monthly_calibration(ym_va, yva, pc_va)),
           "platt_train": (pt_va, monthly_calibration(ym_va, yva, pt_va)),
           "platt_dev": (pd_va, monthly_calibration(ym_va, yva, pd_va))}

    res = {
        "scenario": sc, "desc": SCENARIOS[sc]["desc"], "seed": seed,
        "panel": panel_name,
        "n_features": len(feats),
        "n_macro_features": len(macro_set),
        "best_iteration": int(model.best_iteration_ or prm["n_estimators"]),
        "monotone_constraints": ({f: int(v) for f, v in zip(feats, mono) if v}
                                 if mono is not None else None),
        "hit_cap": bool((model.best_iteration_ or 0) >= prm["n_estimators"]),
        "reg_variant": ACTIVE_REG, "scale_pos_weight": round(spw, 4),
        "n_train": int(tr.sum()), "n_dev": int(dv.sum()), "n_valid": int(va.sum()),
        "pos_train": n_pos, "pos_dev": int(ydv.sum()), "pos_valid": int(yva.sum()),
        "rate_valid": float(yva.mean()),
        "train": evaluate(ytr, p_tr), "dev": evaluate(ydv, p_dv),
        "valid": evaluate(yva, p_va),
        "psi_train_valid": calculate_psi(p_tr, p_va),
        "calibration": {
            "spw_used": round(spw, 4),
            "actual_rate_valid": float(yva.mean()),
            "mean_pd": {k: float(v[0].mean()) for k, v in cal.items()},
            "platt_train_coef": float(platt_tr.coef_[0][0]),
            "platt_train_intercept": float(platt_tr.intercept_[0]),
            "platt_dev_coef": float(platt_dv.coef_[0][0]),
            "platt_dev_intercept": float(platt_dv.intercept_[0]),
            **{k: {"brier": brier(yva, v[0]),
                   **{kk: vv for kk, vv in v[1].items() if kk != "monthly"},
                   **decile_calibration(yva, v[0])} for k, v in cal.items()},
            "monthly": {k: v[1]["monthly"] for k, v in cal.items()},
        },
        "elapsed_sec": round(elapsed, 1),
    }

    gain = dict(zip(feats, model.booster_.feature_importance("gain")))
    total = sum(gain.values()) or 1.0
    res["macro_gain_pct"] = round(100 * sum(v for k, v in gain.items()
                                            if k in macro_set) / total, 3)
    order = sorted(gain.items(), key=lambda x: -x[1])
    rank = {f: i + 1 for i, (f, _) in enumerate(order)}
    res["gain_top20"] = [{"rank": i + 1, "feature": f, "gain_pct": round(100 * g / total, 3),
                          "is_macro": f in macro_set} for i, (f, g) in enumerate(order[:20])]
    res["macro_gain_top10"] = [{"feature": f, "gain_pct": round(100 * g / total, 3),
                                "rank": rank[f]}
                               for f, g in order if f in macro_set][:10]
    # ★ [2026-09-02] 상호작용 집합에 D6/D7/E14 를 포함시킨다.
    #   초판은 `INTERACTION_8 | INTERACTION_HYBRID` 만 봤다. 그래서 D8 의 14개
    #   항이 전부 빈 목록으로 나와 "gain 0.000" 으로 오독됐다 (거시gain 0.93% 와
    #   모순됐다). 새 항을 추가할 때마다 이 집합을 갱신하지 않으면 같은 일이 반복된다.
    _inter_set = (set(INTERACTION_8) | set(INTERACTION_HYBRID)
                  | set(D6_NAMES) | set(D7_NAMES) | set(E14_NAMES))
    res["interaction_gain"] = [{"feature": f, "gain_pct": round(100 * gain.get(f, 0) / total, 3),
                                "rank": rank.get(f)}
                               for f in feats if f in _inter_set]
    res["n_interaction_in_top30"] = sum(
        1 for f in feats if f in _inter_set and rank.get(f, 999) <= 30)

    mp = res["calibration"]["mean_pd"]
    log.info("  [%s seed=%d] Valid AUC %.4f | 거시gain %.2f%% | best_iter %d (%.0fs)",
             sc, seed, res["valid"]["auc"], res["macro_gain_pct"],
             res["best_iteration"], res["elapsed_sec"])
    log.info("      평균PD  실제 %.4f%% | raw %.4f%% | prior %.4f%% | "
             "platt_train %.4f%% | platt_dev %.4f%%",
             res["calibration"]["actual_rate_valid"] * 100,
             mp["raw"] * 100, mp["prior"] * 100,
             mp["platt_train"] * 100, mp["platt_dev"] * 100)
    for m in ("prior", "platt_train", "platt_dev"):
        c = res["calibration"][m]
        log.info("      %-11s 상관 %+.4f | 건수MAPE %7.2f%% | Brier %.6f | ECE %.6f",
                 m, c["corr_pd_rate"], c["count_mape_pct"], c["brier"], c["ece"])
    return res


# ══════════════════════════════════════════════════════════════════════
# 집계
# ══════════════════════════════════════════════════════════════════════

def _agg(rows: list[dict], path: list[str]) -> tuple[float, float]:
    vals = []
    for r in rows:
        v = r
        for k in path:
            v = v[k]
        vals.append(float(v))
    return float(np.mean(vals)), (float(np.std(vals, ddof=1)) if len(vals) > 1 else 0.0)


def summarize(results: list[dict], calib: str = "platt_train") -> list[dict]:
    by_sc: dict[str, list[dict]] = {}
    for r in results:
        by_sc.setdefault(r["scenario"], []).append(r)

    base = by_sc.get("D0")
    base_auc = _agg(base, ["valid", "auc"])[0] if base else float("nan")

    out = []
    for sc in SCENARIOS:
        rows = by_sc.get(sc)
        if not rows:
            continue
        auc, auc_sd = _agg(rows, ["valid", "auc"])
        corr, corr_sd = _agg(rows, ["calibration", calib, "corr_pd_rate"])
        mape, mape_sd = _agg(rows, ["calibration", calib, "count_mape_pct"])
        bri, bri_sd = _agg(rows, ["calibration", calib, "brier"])
        ece, ece_sd = _agg(rows, ["calibration", calib, "ece"])
        mg, mg_sd = _agg(rows, ["macro_gain_pct"])
        out.append({
            "scenario": sc, "desc": SCENARIOS[sc]["desc"], "calib_method": calib,
            "n_seeds": len(rows), "n_features": rows[0]["n_features"],
            "n_macro_features": rows[0]["n_macro_features"],
            "valid_auc": auc, "valid_auc_sd": auc_sd, "delta_auc": auc - base_auc,
            "macro_gain_pct": mg, "macro_gain_pct_sd": mg_sd,
            "corr_pd_rate": corr, "corr_pd_rate_sd": corr_sd,
            "count_mape_pct": mape, "count_mape_pct_sd": mape_sd,
            "brier": bri, "brier_sd": bri_sd, "ece": ece, "ece_sd": ece_sd,
            "n_interaction_in_top30": int(np.mean([r["n_interaction_in_top30"] for r in rows])),
            "mean_pd": {k: float(np.mean([r["calibration"]["mean_pd"][k] for r in rows]))
                        for k in ("raw", "prior", "platt_train", "platt_dev")},
            "actual_rate_valid": rows[0]["calibration"]["actual_rate_valid"],
            "best_iteration_mean": float(np.mean([r["best_iteration"] for r in rows])),
        })
    return out


def print_table(summary: list[dict]) -> None:
    base = next((s for s in summary if s["scenario"] == "D0"), None)
    print()
    print("=" * 132)
    print("D축 결과 — AUC 는 판정 기준이 아니다. 그 옆 캘리브레이션 컬럼이 거시의 가치다.")
    print("=" * 132)
    hdr = (f"{'ID':4s} {'구성':46s} {'피처':>5s} {'ValidAUC(σ)':>16s} {'ΔAUC':>8s} "
           f"{'거시gain%':>9s} {'PD-부도율상관':>13s} {'건수MAPE%':>10s} {'Brier':>9s}")
    print(hdr)
    print("-" * 132)
    for s in summary:
        d = s["desc"][:44]
        print(f"{s['scenario']:4s} {d:46s} {s['n_features']:5d} "
              f"{s['valid_auc']:.4f}({s['valid_auc_sd']:.4f}) "
              f"{s['delta_auc']:+8.4f} {s['macro_gain_pct']:9.2f} "
              f"{s['corr_pd_rate']:13.4f} {s['count_mape_pct']:10.2f} {s['brier']:9.6f}")
    print("-" * 132)
    if base:
        print(f"기준선 D0: Valid AUC {base['valid_auc']:.4f} / "
              f"PD-부도율상관 {base['corr_pd_rate']:.4f} / "
              f"건수MAPE {base['count_mape_pct']:.2f}% / Brier {base['brier']:.6f}")
    m = summary[0]["calib_method"] if summary else "?"
    print(f"주: 캘리브레이션 지표는 보정 방식 '{m}' 적용 후 값이다. "
          "AUC 는 단조변환에 불변이라 보정과 무관하다.")


# ══════════════════════════════════════════════════════════════════════

def _merge(path: Path, new: list[dict]) -> list[dict]:
    old = []
    if path.exists():
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            old = []
    by_key = {(r["scenario"], r["seed"]): r for r in old}
    for r in new:
        by_key[(r["scenario"], r["seed"])] = r
    order = list(SCENARIOS)
    return sorted(by_key.values(),
                  key=lambda r: (order.index(r["scenario"])
                                 if r["scenario"] in order else 999, r["seed"]))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--run", nargs="*", default=None)
    ap.add_argument("--run-all", action="store_true")
    ap.add_argument("--seeds", default=",".join(str(s) for s in DEFAULT_SEEDS))
    ap.add_argument("--panel-tag", default="real")
    ap.add_argument("--summarize-only", action="store_true")
    ap.add_argument("--calib", default="platt_train",
                    choices=["raw", "prior", "platt_train", "platt_dev"],
                    help="결과표에 쓸 확률 보정 방식")
    a = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    if a.list:
        for k, v in SCENARIOS.items():
            print(f"  {k}  {v['desc']}")
        return

    if a.summarize_only:
        results = json.loads(RESULT_JSON.read_text(encoding="utf-8"))
        summary = summarize(results, a.calib)
        (OUT_DIR / "d_axis_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print_table(summary)
        return

    targets = list(SCENARIOS) if a.run_all else (a.run or [])
    if not targets:
        ap.error("--run 또는 --run-all 이 필요하다")
    seeds = [int(x) for x in a.seeds.split(",")]

    p = panel_path(a.panel_tag)
    macro_all = set(macro_source_columns())
    con = duckdb.connect()
    try:
        cols = con.execute(
            f"SELECT * FROM read_parquet('{p.as_posix()}') LIMIT 0").df().columns.tolist()
    finally:
        con.close()

    base, macro_reduced, info = build_pools(cols, macro_all)
    macro_extra = sorted(macro_all - set(macro_reduced))
    log.info("패널 %s", p.name)
    log.info("  피처 후보 %d = 기업고유 %d + 거시원본 %d (+ 상호작용 %d)",
             info["all_features"], info["n_base"], info["n_macro_pure"],
             info["n_interaction_in_panel"])
    log.info("  거시 축소 해제 시 추가되는 컬럼 %d개 (D5 전용)", len(macro_extra))

    need_extra = any(SCENARIOS[t]["macro"] == "full" for t in targets)
    load_cols = sorted(set(base) | set(macro_reduced)
                       | {n for n, _, _ in INTERACTIONS if n in set(cols)})
    log.info("패널 로딩 (%d컬럼)...", len(load_cols))
    df = load_panel(p, load_cols)
    log.info("  shape=%s  메모리 %.2fGB", df.shape,
             df.memory_usage(deep=False).sum() / 1e9)
    if need_extra:
        df = join_macro_extra(df, macro_extra)
        log.info("  D5 대비 확장 후 메모리 %.2fGB",
                 df.memory_usage(deep=False).sum() / 1e9)
    if any(SCENARIOS[t]["inter"] in ("d6three", "d7two") for t in targets):
        df = add_level_interaction(df)
    if any(SCENARIOS[t]["inter"] in ("e14", "e14_top") for t in targets):
        global E14_NAMES, E14_MONO, E14_TOP_NAMES
        df, E14_NAMES, E14_MONO = add_e14_interactions(df)
        if "D8s" in targets:
            E14_TOP_NAMES = e14_surviving_terms(E14_NAMES)
            log.info("  D8s 유지 항 %d/%d — %s",
                     len(E14_TOP_NAMES), len(E14_NAMES), E14_TOP_NAMES)

    results: list[dict] = []
    for t in targets:
        feats = resolve_features(t, base, macro_reduced, macro_extra)
        missing = [c for c in feats if c not in df.columns]
        assert not missing, f"{t}: 패널에 없는 피처 {missing[:10]}"
        mset = macro_feature_set(feats, macro_all)
        for sd in seeds:
            results.append(run_one(t, df, feats, mset, sd, panel_name=p.name))
            merged = _merge(RESULT_JSON, results)
            RESULT_JSON.write_text(json.dumps(merged, ensure_ascii=False, indent=2),
                                   encoding="utf-8")

    all_results = _merge(RESULT_JSON, results)
    summary = summarize(all_results, a.calib)
    (OUT_DIR / "d_axis_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print_table(summary)
    log.info("저장: %s / %s", RESULT_JSON.name, "d_axis_summary.json")


if __name__ == "__main__":
    main()
