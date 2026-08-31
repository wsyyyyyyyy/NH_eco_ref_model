"""
======================================================================
누수(leakage) 변수 정의 — 피처 선택 공통 모듈
======================================================================
step5 / step7 / step23 이 공통으로 import 합니다.
step2(패널 생성)에는 정의하지 않습니다. step2는 패널 생성 책임만 갖고,
피처 선택 책임은 모델링 단계에 둡니다.

사용법:
    from eda_pipeline.leaky_cols import LEAK_CONFIRMED, NON_FEATURE, feature_columns
    features = feature_columns(df, target="IS_BUDO_12M")
"""

from __future__ import annotations

from typing import Iterable, List

import pandas as pd

# ── 1등급: 확정 누수. 기본 제외. ──────────────────────────────────────
LEAK_CONFIRMED: List[str] = [
    # 2026년 추출 시점 스냅샷. 폐업(92) 1,022사 부도율 34.8% (전체 3.7%의 9.4배).
    "COPR_OPNP_C",

    # --- CRIF (legacy 패널 컬럼명) ---
    # 부도의 결과. 사유발생~부도 gap 중앙값 -2개월, 부도가 먼저인 비율 75.9%.
    "CRIF_CRDBD_RSNC",
    "CRIF_SUM(CRDBD_RSN_AM)",
    "CRIF_SUM(CRDBD_OVD_AM)",
    # 해제사유. 04(손실처리) 부도율 55.6%.
    "CRIF_MAX(CRDBD_RLS_RSNC)",
    # 해제일. 부도 대비 중앙값 +35개월, 부도기업 182건 전부(100%) 사후 해제.
    "CRIF_MAX(CRDBD_RLS_OCU_DT)",

    # --- CRIF (STAGE 1 이후 집계 패널 컬럼명) ---
    # 위 원천 컬럼을 (V_BZNO, 연도) 단위로 집계한 것이므로 누수 성격이 동일하다.
    # STAGE 6 S3b에서 "관측시점 이전에 이미 해제된 건수" 형태로 재구성할 때 재검토한다.
    "CRIF_EVENT_CNT",
    "CRIF_RSN_AM_SUM",
    "CRIF_OVD_AM_SUM",
    "CRIF_WORST_RSNC",

    # --- STAGE 6 A9 검증에서 확정 (2026-08-30) ---
    # 원천이 KIS_LS_FNA_MKS_2021~_2025 연도별 wide 포맷이라 날짜가 아예 없다.
    # step2._join_cg01 이 panel["BASE_YM"].str[:4] 로 연 단위 merge 하므로
    # 2021년 1월 행이 "2021년 한 해에 평가 이력이 있었는가"를 본다.
    # 실측: (V_BZNO, 연도) 그룹 안에서 값이 변하는 경우 0건.
    # 원천에 월 정보가 없어 시점 정합 재구성이 불가능하다.
    # 1년 시차(2021년 행에 2020년 값) 적용만이 정합 처리이며 STAGE 6 B5 과제다.
    "CG01_MISSING_YN",
]

# ── 2등급: 의심. STAGE 6에서 켜고 끄며 실측 후 판단. ──────────────────
LEAK_SUSPECT: List[str] = [
    # 최종재무평점_2021이 2021년 1월에 붙는다 (연 단위 조인, 시점 부정합).
    "CG01_KIS_SCORE",
    # (해제됨) "C302_CRI_ORD" — STAGE 6 A5/A6 에서 해제 확정 (2026-08-30).
    #   등재 사유였던 "D 등급 포함"은 step2._join_c302 가 D/R/NR 을 별도 플래그로
    #   분리하고 CRI_ORD 를 NaN 처리하면서 이미 해소됐다.
    #   조인도 유효기간 기반 월 단위(ST_YM <= BASE_YM < ED_YM)라 시점 정합이다.
    #   다만 한계 기여가 +0.0086 에 그쳐 Lean 구성에서는 제외 후보로 둔다.
    # D 등급은 사실상 부도 통보다. 12사 중 8사가 당행 부도 (66.7%).
    "C302_IS_D_YN",
]

# ── 사실상 무분산. 학습에 기여하지 않으므로 제외한다. ────────────────
# STAGE 6 실측 (948,214행 기준): =1 인 행이 각각 20행 / 290행 / 7행뿐이다.
# C302_IS_D_YN 은 부도 등급 그 자체라 무분산 여부와 무관하게 제외 대상이다.
DEGENERATE: List[str] = [
    "C302_IS_NR_YN",   # =1 20행
    "C302_IS_R_YN",    # =1 290행
]


# ── 누수는 아니지만 피처가 아닌 메타/키/타겟 컬럼 ───────────────────
NON_FEATURE: List[str] = [
    "V_BZNO", "BASE_YM", "SPLIT",
    "IS_BUDO_12M", "IS_BUDO_IN_SPINE_YN",
    # 정상화 정보는 관측시점 이후에야 알 수 있는 미래 정보다.
    # STAGE 3의 '부도 진행 중 구간 제외' 전용이며 피처로 쓰지 않는다.
    "IS_RECOVERED", "RECOVER_YM",
    "CONM", "ETB_DT", "BZSCAL_C", "EMPCN",
    # 원본 업종코드는 고유값 1,147개라 그대로 쓰면 트리가 개별 업종을 외운다.
    # 대분류(STD_INDS_SECTION) / 중분류(STD_INDS_MID2) 파생을 대신 쓴다.
    "STD_INDS_CFC",
]


def feature_columns(
    df: pd.DataFrame,
    target: str = "IS_BUDO_12M",
    include_suspect: bool = False,
    extra_exclude: Iterable[str] = (),
) -> List[str]:
    """
    데이터프레임에서 모델 피처로 쓸 컬럼 목록을 반환합니다.

    include_suspect=True 이면 LEAK_SUSPECT를 피처에 포함합니다
    (STAGE 6의 on/off 실험용).
    """
    excluded = (set(NON_FEATURE) | set(LEAK_CONFIRMED) | set(DEGENERATE)
                | {target} | set(extra_exclude))
    if not include_suspect:
        excluded |= set(LEAK_SUSPECT)
    return [c for c in df.columns if c not in excluded]
