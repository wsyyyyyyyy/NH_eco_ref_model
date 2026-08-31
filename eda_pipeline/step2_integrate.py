"""
======================================================================
Step 2 — 월별 패널 데이터 통합 (순수 Pandas 버전)
======================================================================
step1_load.py의 frames 딕셔너리를 받아
「V_BZNO × BASE_YM」 패널 구조의 통합 데이터셋을 생성합니다.

구조:
  - Skeleton: spine_mode 에 따라 결정
      'obv'  : VH_OBV_DTL 레코드가 존재하는 (기업, 월)만 = 당행 여신 보유 차주
      'full' : UPCHE 전체 × 월 캘린더 크로스조인 (기존 동작)
  - 시간축 정렬: 각 테이블 → 해당 월에 가장 적합한 값을 as-of join
  - Target: IS_BUDO_IN_SPINE_YN (스파인 내 부도월 표시. 전체 부도 이벤트가 아님)
  - 분리: TRAIN (≤2023-12), VALID (≥2024-01)

불변식:
  9개 조인 메서드(_join_*)는 패널 행수를 절대 바꾸지 않습니다 (assert 로 강제).

사용법:
    from eda_pipeline.step2_integrate import PanelBuilder
    builder = PanelBuilder(frames, output_dir="eda_pipeline/output")
    panel = builder.build()                    # config.SPINE_MODE 사용
    panel = builder.build(spine_mode="full")   # 명시 지정
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict

import numpy as np
import pandas as pd

from eda_pipeline import config
from eda_pipeline.jemu_sentinel import decode_jemu

log = logging.getLogger(__name__)

TRAIN_END = "202312"   # 학습 기간 마지막 월 (포함)
VALID_START = "202401" # 검증 기간 시작 월 (포함)
PANEL_START = "202101" # 전체 패널 시작
# 전체 패널 종료.
#   - VH_OBV_DTL 이 202506 에 사실상 종료 (202506=18,189행 -> 202507=93행).
#   - 부도 데이터가 202605 까지이므로 12개월 관측창을 온전히 확보할 수 있는
#     마지막 기준월이 202505 이다.
PANEL_END   = "202505"

# 공시지연(개월). eda_pipeline/config.py 에서 관리하며 환경변수로 조정 가능하다.
#   PUB_LAG_MONTHS : 재무(JEMU). FNA_CLS_YM + LAG 이후에야 입수 가능하다고 본다.
#   AA17_PUB_LAG   : 생산판매(AA17). 분기 종료월 + LAG 이후에야 확정된다고 본다.
PUB_LAG_MONTHS = config.PUB_LAG_MONTHS
AA17_PUB_LAG = config.AA17_PUB_LAG


def _make_calendar(start: str, end: str) -> pd.DataFrame:
    """YYYYMM 형식 월 캘린더 생성."""
    months = pd.date_range(
        start=f"{start[:4]}-{start[4:]}",
        end=f"{end[:4]}-{end[4:]}",
        freq="MS",
    )
    return pd.DataFrame({"BASE_YM": months.strftime("%Y%m")})


def _ym_to_idx(s: pd.Series) -> pd.Series:
    """YYYYMM 문자열 -> 월 일련번호(정수). 월 단위 산술/as-of 비교용."""
    s = s.astype(str).str.strip()
    return s.str[:4].astype("int64") * 12 + s.str[4:6].astype("int64")


def aggregate_budo_events(budo: pd.DataFrame) -> pd.DataFrame:
    """부도 이벤트를 (V_BZNO, DEFAULT_YM) 단위 1행으로 집계한다.

    같은 달에 여러 부도 사유가 발생하는 경우가 있다(원천 5쌍). 임의의 한 행만
    남기면 정상화 정보가 손상된다.
      - 한 행은 정상화(1), 다른 행은 미정상화(0)인 경우가 있다. 미정상화 행을
        버리면 아직 해소되지 않은 부도가 정상 관측치로 복귀한다.
      - 정상화일이 서로 다른 경우, 이른 날짜를 남기면 부도 구간이 실제보다 짧아진다.

    동시에 발생한 여러 사유는 그 중 마지막 사유가 해소되어야 부도 상태가 끝난다.
    따라서 아래 규칙으로 집계한다.

      IS_RECOVERED : 그룹의 모든 이벤트가 정상화된 경우에만 1 (min)
      RECOVER_DT   : IS_RECOVERED=1 이면 그룹 내 정상화일의 MAX, 아니면 NaT
      DEFAULT_DT   : 그룹 내 최초 부도일 (MIN)
      DSH_RSN_DSC  : 그룹 내 사유코드를 정렬해 '|' 로 결합 (정보를 버리지 않는다)
      DSH_RSN_CNT  : 그룹 내 사유 건수
    """
    d = budo[budo["IS_DEFAULT"] == 1].copy()
    d["V_BZNO"] = d["V_BZNO"].astype(str).str.strip()
    if "RECOVER_DT" not in d.columns:
        d["RECOVER_DT"] = pd.NaT
    if "DSH_RSN_DSC" not in d.columns:
        d["DSH_RSN_DSC"] = pd.NA

    agg = (d.groupby(["V_BZNO", "DEFAULT_YM"], as_index=False)
             .agg(IS_RECOVERED=("IS_RECOVERED", "min"),
                  RECOVER_DT=("RECOVER_DT", "max"),
                  DEFAULT_DT=("DSH_DT", "min"),
                  DSH_RSN_CNT=("DSH_RSN_DSC", "size"),
                  DSH_RSN_DSC=("DSH_RSN_DSC",
                               lambda s: "|".join(sorted(set(s.dropna().astype(str)))))))

    # 하나라도 미정상화면 부도 상태가 끝나지 않았으므로 정상화일도 없다.
    agg.loc[agg["IS_RECOVERED"] != 1, "RECOVER_DT"] = pd.NaT
    agg["RECOVER_YM"] = agg["RECOVER_DT"].apply(
        lambda x: x.strftime("%Y%m") if pd.notna(x) else None)

    n_multi = int((agg["DSH_RSN_CNT"] > 1).sum())
    if n_multi:
        log.info("  부도 이벤트 집계: %d행 -> %d건 (동월 복수사유 %d건)",
                 len(d), len(agg), n_multi)
    return agg.sort_values(["V_BZNO", "DEFAULT_YM"]).reset_index(drop=True)


class PanelBuilder:
    """
    11개 전처리된 테이블 -> 월별 패널 통합 데이터셋 생성기.
    """

    def __init__(
        self,
        frames: Dict[str, pd.DataFrame],
        output_dir: str | Path | None = None,
    ) -> None:
        self.frames = frames
        self.output_dir = Path(output_dir) if output_dir is not None else config.OUTPUT_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)

    # ================================================================
    # Public
    # ================================================================

    def build(self, spine_mode: str | None = None, save: bool = True) -> pd.DataFrame:
        """통합 패널 데이터셋을 빌드하고 CSV로 저장 후 반환합니다."""
        mode = spine_mode or config.SPINE_MODE
        if save:
            config.assert_writable(mode)   # legacy 모드면 여기서 예외

        log.info("=" * 60)
        log.info("[INTEGRATE] 패널 데이터 통합 시작")
        log.info("  기간: %s ~ %s  (%d개월)", PANEL_START, PANEL_END,
                 _make_calendar(PANEL_START, PANEL_END)["BASE_YM"].nunique())
        log.info("  spine_mode: %s", mode)
        log.info("=" * 60)

        # 1. 기반 Skeleton 생성
        panel = self._build_skeleton(spine_mode=mode)
        n_skeleton = len(panel)
        log.info("  Skeleton: %d rows (기업 x 월)", n_skeleton)

        # 2. 각 테이블 LEFT JOIN (행수 불변)
        panel = self._join_obv(panel)
        panel = self._join_jemu(panel)
        panel = self._join_grd_his(panel)
        panel = self._join_cg01(panel)
        panel = self._join_c302(panel)
        panel = self._join_ac12(panel)
        panel = self._join_aa17(panel)
        panel = self._join_aa10(panel)
        panel = self._join_crif(panel)

        assert len(panel) == n_skeleton, (
            f"조인 구간에서 행수 변동: {n_skeleton} -> {len(panel)}")

        # 3. Target 생성
        panel = self._attach_target(panel)

        # 4. 분리 플래그
        panel["SPLIT"] = np.where(panel["BASE_YM"] <= TRAIN_END, "TRAIN", "VALID")

        # 5. 컬럼 정렬 (키 -> Target -> 피처)
        panel = self._reorder_columns(panel)

        # 6. 저장
        if save:
            self._save(panel, mode)

        log.info("[INTEGRATE] 완료 — Shape: %s", panel.shape)
        log.info("  Train rows: %d  |  Valid rows: %d",
                 (panel["SPLIT"] == "TRAIN").sum(),
                 (panel["SPLIT"] == "VALID").sum())
        log.info("  Target 부도율(Train): %.4f%%",
                 panel.loc[panel["SPLIT"] == "TRAIN", "IS_BUDO_IN_SPINE_YN"].mean() * 100)

        return panel

    def compare_spine_modes(self) -> pd.DataFrame:
        """
        spine_mode='obv' / 'full' 두 모드의 행수·부도율을 비교해 로그로 출력합니다.
        (조인 없이 스켈레톤 + 타겟만으로 비교하므로 가볍습니다.)
        """
        rows = []
        for mode in ("full", "obv"):
            sk = self._build_skeleton(spine_mode=mode)
            sk = self._attach_target(sk)
            rows.append({
                "spine_mode": mode,
                "rows": len(sk),
                "기업수": sk["V_BZNO"].nunique(),
                "부도건수": int(sk["IS_BUDO_IN_SPINE_YN"].sum()),
                "부도율%": round(sk["IS_BUDO_IN_SPINE_YN"].mean() * 100, 4),
            })
        cmp = pd.DataFrame(rows)
        log.info("[SPINE 비교] %s ~ %s", PANEL_START, PANEL_END)
        for line in cmp.to_string(index=False).splitlines():
            log.info("  %s", line)
        return cmp

    # ================================================================
    # Step 1: Skeleton
    # ================================================================

    def _build_skeleton(self, spine_mode: str = "obv") -> pd.DataFrame:
        """
        패널 스파인(모수) 생성.

        spine_mode='obv'  : 해당 월에 VH_OBV_DTL 레코드가 존재하는 (기업, 월)만 포함.
                            = 당행 여신 보유 차주. 부도기업 1,192사 중 1,095사(91.9%) 커버.
        spine_mode='full' : UPCHE 전체 x 캘린더 크로스조인 (기존 동작 보존).
        """
        if spine_mode not in ("obv", "full", "legacy"):
            raise ValueError(f"알 수 없는 spine_mode: {spine_mode!r}")

        upche = self.frames.get("upche", pd.DataFrame())
        if upche.empty:
            raise ValueError("upche 데이터프레임이 없습니다.")

        # 필요 컬럼만 유지 (EMPCN은 AA10에서 별도 관리)
        keep_cols = [c for c in ["V_BZNO", "CONM", "ETB_DT",
                                  "COPR_OPNP_C", "BZSCAL_C", "STD_INDS_CFC"]
                     if c in upche.columns]
        master = upche[keep_cols].drop_duplicates("V_BZNO").copy()
        master["V_BZNO"] = master["V_BZNO"].astype(str).str.strip()

        calendar = _make_calendar(PANEL_START, PANEL_END)

        if spine_mode == "obv":
            obv = self.frames.get("obv", pd.DataFrame())
            if obv.empty:
                raise ValueError("spine_mode=obv 인데 obv 데이터프레임이 없습니다.")
            keys = obv[["V_BZNO", "BAS_YM"]].copy()
            keys["V_BZNO"] = keys["V_BZNO"].astype(str).str.strip()
            keys["BASE_YM"] = keys["BAS_YM"].astype(str).str.strip()
            keys = keys[["V_BZNO", "BASE_YM"]].drop_duplicates()
            # 패널 기간 밖 / 마스터에 없는 기업 제외
            keys = keys[keys["BASE_YM"].isin(set(calendar["BASE_YM"]))]
            panel = master.merge(keys, on="V_BZNO", how="inner")
        else:
            panel = master.merge(calendar, how="cross")

        # 설립일 숫자형 변환
        if "ETB_DT" in panel.columns:
            panel["ETB_DT"] = pd.to_numeric(panel["ETB_DT"], errors="coerce")

        panel = panel.sort_values(["V_BZNO", "BASE_YM"]).reset_index(drop=True)

        dup = int(panel.duplicated(["V_BZNO", "BASE_YM"]).sum())
        assert dup == 0, f"skeleton 에 (V_BZNO, BASE_YM) 중복 {dup}건"
        return panel

    # ================================================================
    # Step 2: 개별 테이블 JOIN 메서드 (모두 행수 불변)
    # ================================================================

    def _join_obv(self, panel: pd.DataFrame) -> pd.DataFrame:
        """
        관찰세부등급(obv): V_BZNO + BAS_YM Exact Match.
        월별 여신한도, 잔액, PD, LGD, 관찰등급 등.
        """
        if "obv" not in self.frames:
            return panel
        n_before = len(panel)
        obv = self.frames["obv"].copy()
        obv["V_BZNO"] = obv["V_BZNO"].astype(str).str.strip()
        obv["BAS_YM"] = obv["BAS_YM"].astype(str).str.strip()

        # 동일 월에 복수 행이면 잔액(LN_BAC) 기준 최신 유지
        obv = (obv.sort_values("LN_BAC", ascending=False, na_position="last")
                  .drop_duplicates(subset=["V_BZNO", "BAS_YM"], keep="first"))

        rename = {c: f"OBV_{c}" for c in obv.columns if c not in ("V_BZNO", "BAS_YM")}
        obv = obv.rename(columns=rename)
        panel = panel.merge(obv, left_on=["V_BZNO", "BASE_YM"],
                            right_on=["V_BZNO", "BAS_YM"], how="left")
        panel = panel.drop(columns=["BAS_YM"], errors="ignore")
        log.info("  Joined OBV    - %%: %.1f%%",
                 panel["OBV_LN_BAC"].notna().mean() * 100)
        assert len(panel) == n_before, f"_join_obv에서 행 폭증: {n_before} -> {len(panel)}"
        return panel

    def _join_jemu(self, panel: pd.DataFrame) -> pd.DataFrame:
        """
        재무데이터(jemu): 진짜 as-of backward join.

        각 재무 레코드의 입수가능시점을 AVAIL_YM = FNA_CLS_YM + PUB_LAG_MONTHS 로 두고,
        각 (V_BZNO, BASE_YM) 에 대해 AVAIL_YM <= BASE_YM 인 재무 중
        FNA_CLS_YM 이 가장 최근인 1건을 선택합니다 (pandas.merge_asof, backward).

        파생: JEMU_STALE_MONTHS = BASE_YM - FNA_CLS_YM (개월).
              재무가 오래 갱신되지 않은 것 자체가 리스크 신호이므로 피처로 사용합니다.
        """
        if "jemu" not in self.frames:
            return panel
        n_before = len(panel)
        jemu = self.frames["jemu"].copy()
        jemu["V_BZNO"] = jemu["V_BZNO"].astype(str).str.strip()
        jemu["FNA_CLS_YM"] = jemu["FNA_CLS_YM"].astype(str).str.strip().str.zfill(6)

        # 동일 사업자 x 결산기 중복 방지
        jemu = jemu.drop_duplicates(subset=["V_BZNO", "FNA_CLS_YM"], keep="last")

        # 입수가능시점
        jemu["_FNA_IDX"] = _ym_to_idx(jemu["FNA_CLS_YM"])
        jemu["_AVAIL_IDX"] = jemu["_FNA_IDX"] + PUB_LAG_MONTHS

        # ── sentinel 해독 & 재무비율 재계산 ──────────────────────────
        # 조인 전(jemu 프레임 단계)에 수행한다. consec_loss_years / pl_turn_dir 이
        # 연속 결산 시계열을 필요로 하는데, 패널 단계에서는 as-of 조인으로 같은 결산이
        # 여러 달에 반복 등장해 계산이 왜곡되기 때문이다.
        # 여기서 파생하면 아래 as-of 조인(PUB_LAG_MONTHS)이 그대로 적용되어
        # 시점 정합성이 자동 보장된다.
        # 상수 판정은 Train 구간(입수가능시점 <= TRAIN_END)에서만 수행한다.
        train_mask = jemu["_AVAIL_IDX"] <= _ym_to_idx(pd.Series([TRAIN_END])).iloc[0]
        jemu = decode_jemu(
            jemu, group_col="V_BZNO", order_col="FNA_CLS_YM",
            train_mask=train_mask,
            constant_cols_path=config.jemu_constant_cols_path(),
        )
        assert not jemu.duplicated(["V_BZNO", "FNA_CLS_YM"]).any(), \
            "decode_jemu 이후 (V_BZNO, FNA_CLS_YM) 중복이 발생했습니다."

        # AUD_OPI_DSC(감사의견)는 재무제표와 함께 공시되므로 같은 as-of 조인을 탄다.
        # 별도 시점 처리를 하지 않고 피처로 넘긴다.
        meta_cols = ["V_BZNO", "FNA_CLS_YM", "FNA_YEAR",
                     "_FNA_IDX", "_AVAIL_IDX"]
        feat_cols = [c for c in jemu.columns if c not in meta_cols]
        rename = {c: f"JEMU_{c}" for c in feat_cols}
        right = jemu[["V_BZNO", "_AVAIL_IDX", "_FNA_IDX"] + feat_cols].rename(columns=rename)

        left = panel[["V_BZNO", "BASE_YM"]].copy()
        left["_BASE_IDX"] = _ym_to_idx(left["BASE_YM"])
        left["_row"] = np.arange(len(left))

        # merge_asof 는 정렬 필수
        left = left.sort_values("_BASE_IDX")
        right = right.sort_values("_AVAIL_IDX")

        merged = pd.merge_asof(
            left, right,
            left_on="_BASE_IDX", right_on="_AVAIL_IDX",
            by="V_BZNO", direction="backward",
        )
        merged["JEMU_STALE_MONTHS"] = merged["_BASE_IDX"] - merged["_FNA_IDX"]
        merged = (merged.sort_values("_row")
                        .drop(columns=["_BASE_IDX", "_AVAIL_IDX", "_FNA_IDX",
                                       "V_BZNO", "BASE_YM", "_row"]))
        merged.index = panel.index
        panel = pd.concat([panel, merged], axis=1)

        # ── 감사의견 파생 ────────────────────────────────────────
        if "JEMU_AUD_OPI_DSC" in panel.columns:
            _raw = panel["JEMU_AUD_OPI_DSC"]
            _a = _raw.astype(str).str.strip().str.zfill(2)
            _has = _raw.notna()
            # 비적정 의견(한정/부적정/의견거절)은 강한 부실 신호다.
            _adverse = ["20", "21", "22", "30", "31", "32", "40", "41", "42", "43"]
            panel["JEMU_AUD_ADVERSE_YN"] = np.where(_has, _a.isin(_adverse), np.nan)
            # 00(자료없음) / 50(감사미필)은 비외감이라 감사의견이 "미해당"인 것이다.
            # 결측이 아니므로 별도 범주로 둔다 (전체의 약 74%가 00).
            panel["JEMU_AUD_NONE_YN"] = np.where(_has, _a.isin(["00", "50"]), np.nan)
            # 43 = 의견거절(계속기업 존속 의문). 특히 강한 신호이므로 단독 플래그.
            panel["JEMU_AUD_GC_DOUBT_YN"] = np.where(_has, _a == "43", np.nan)
            panel["JEMU_AUD_OPI_DSC"] = _a.where(_has)
            log.info("     감사의견: 비적정 %d행 / 미해당 %d행 / 43(계속기업의문) %d행",
                     int(panel["JEMU_AUD_ADVERSE_YN"].fillna(0).sum()),
                     int(panel["JEMU_AUD_NONE_YN"].fillna(0).sum()),
                     int(panel["JEMU_AUD_GC_DOUBT_YN"].fillna(0).sum()))

        jemu_feats = [c for c in panel.columns if c.startswith("JEMU_")]
        log.info("  Joined JEMU   - %%: %.1f%%  (as-of, 공시지연 %d개월)",
                 panel[jemu_feats[0]].notna().mean() * 100 if jemu_feats else 0,
                 PUB_LAG_MONTHS)
        assert len(panel) == n_before, f"_join_jemu에서 행 폭증: {n_before} -> {len(panel)}"
        return panel

    def _join_grd_his(self, panel: pd.DataFrame) -> pd.DataFrame:
        """당행등급이력(grd_his): 연도별 as-of join."""
        if "grd_his" not in self.frames:
            return panel
        n_before = len(panel)
        grd = self.frames["grd_his"].copy()
        grd["V_BZNO"] = grd["V_BZNO"].astype(str).str.strip()
        grd["_YEAR"] = grd["BASE_YEAR"].astype(str).str.strip()
        grd = grd.drop(columns=["BASE_YEAR"])
        grd = grd.drop_duplicates(subset=["V_BZNO", "_YEAR"], keep="first")
        rename = {c: f"GRD_{c}" for c in ["CRDEVL_PTTP_DSC", "LS_NICS_GRDC"]}
        grd = grd.rename(columns=rename)

        panel["_YEAR"] = panel["BASE_YM"].str[:4]
        panel = panel.merge(grd, on=["V_BZNO", "_YEAR"], how="left")
        panel = panel.drop(columns=["_YEAR"], errors="ignore")
        log.info("  Joined GRD_HIS - %%: %.1f%%",
                 panel["GRD_LS_NICS_GRDC"].notna().mean() * 100)
        assert len(panel) == n_before, f"_join_grd_his에서 행 폭증: {n_before} -> {len(panel)}"
        return panel

    def _join_cg01(self, panel: pd.DataFrame) -> pd.DataFrame:
        """나이스신용평점(cg01): 연도별 as-of join."""
        if "cg01" not in self.frames:
            return panel
        n_before = len(panel)
        cg01 = self.frames["cg01"].copy()
        cg01["V_BZNO"] = cg01["V_BZNO"].astype(str).str.strip()
        cg01["_YEAR"] = cg01["BASE_YEAR"].astype(str).str.strip()
        cg01 = cg01.drop(columns=["BASE_YEAR"])
        cg01 = cg01.drop_duplicates(subset=["V_BZNO", "_YEAR"], keep="first")
        cg01 = cg01.rename(columns={"KIS_LS_FNA_MKS": "CG01_KIS_SCORE"})

        panel["_YEAR"] = panel["BASE_YM"].str[:4]
        panel = panel.merge(cg01, on=["V_BZNO", "_YEAR"], how="left")
        panel = panel.drop(columns=["_YEAR"], errors="ignore")
        log.info("  Joined CG01   - %%: %.1f%%",
                 panel["CG01_KIS_SCORE"].notna().mean() * 100)
        assert len(panel) == n_before, f"_join_cg01에서 행 폭증: {n_before} -> {len(panel)}"
        return panel

    def _join_c302(self, panel: pd.DataFrame) -> pd.DataFrame:
        """
        나이스CRI등급(c302): 유효기간 기반 as-of join.
        해당 BASE_YM이 [ST_DT, ED_DT) 구간 안에 있는 등급을 선택합니다.
        """
        if "c302" not in self.frames:
            return panel
        n_before = len(panel)
        c302 = self.frames["c302"].copy()
        c302["V_BZNO"] = c302["V_BZNO"].astype(str).str.strip()

        # 날짜 정형화
        c302["ST_DT"] = c302["ST_DT"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(8)
        c302["ED_DT"] = c302["ED_DT"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(8)

        # 월 단위로 변환 (YYYYMM)
        c302["ST_YM"] = c302["ST_DT"].str[:6]
        c302["ED_YM"] = c302["ED_DT"].str[:6]

        # panel의 각 (V_BZNO, BASE_YM)에 대해 유효 등급 매칭
        panel_key = panel[["V_BZNO", "BASE_YM"]].copy()
        merged = panel_key.merge(
            c302[["V_BZNO", "ST_YM", "ED_YM", "CRI_GRD", "CRI_GRD_ORD"]],
            on="V_BZNO", how="left"
        )
        valid = merged[(merged["BASE_YM"] >= merged["ST_YM"]) &
                       (merged["BASE_YM"] < merged["ED_YM"])]

        # 동일 (V_BZNO, BASE_YM)에 여러 등급이면 종료일 늦은 것 선택
        valid = (valid.sort_values("ED_YM", ascending=False)
                      .drop_duplicates(subset=["V_BZNO", "BASE_YM"], keep="first"))
        valid = valid[["V_BZNO", "BASE_YM", "CRI_GRD", "CRI_GRD_ORD"]].rename(
            columns={"CRI_GRD": "C302_CRI_GRD", "CRI_GRD_ORD": "C302_CRI_ORD"})

        # D / R / NR 은 신용도 서열이 아니라 상태 표시다.
        # 특히 D 는 부도 등급 그 자체(12사 중 8사가 당행 부도, 66.7%)이므로
        # 서열값 C302_CRI_ORD 에서 제외하고 별도 플래그로 분리한다.
        # (step1_load.py 의 CRI_ORDINAL 매핑 자체는 다른 소비처를 위해 건드리지 않는다.)
        _g = valid["C302_CRI_GRD"].astype(str).str.strip().str.upper()
        valid["C302_IS_D_YN"] = (_g == "D").astype(int)
        valid["C302_IS_NR_YN"] = (_g == "NR").astype(int)
        valid["C302_IS_R_YN"] = (_g == "R").astype(int)
        valid.loc[_g.isin(["D", "R", "NR"]), "C302_CRI_ORD"] = np.nan

        panel = panel.merge(valid, on=["V_BZNO", "BASE_YM"], how="left")
        log.info("  Joined C302   - %%: %.1f%%  (ORD 유효 %.1f%%)",
                 panel["C302_CRI_GRD"].notna().mean() * 100,
                 panel["C302_CRI_ORD"].notna().mean() * 100)
        log.info("     D/NR/R 플래그 =1 행수: D=%d NR=%d R=%d",
                 int(panel["C302_IS_D_YN"].sum()), int(panel["C302_IS_NR_YN"].sum()),
                 int(panel["C302_IS_R_YN"].sum()))
        assert len(panel) == n_before, f"_join_c302에서 행 폭증: {n_before} -> {len(panel)}"
        return panel

    def _join_ac12(self, panel: pd.DataFrame) -> pd.DataFrame:
        """외화부채(ac12): 연도별 as-of join. 금액 단위는 원(KRW)."""
        if "ac12" not in self.frames:
            return panel
        n_before = len(panel)
        ac12 = self.frames["ac12"].copy()
        ac12["V_BZNO"] = ac12["V_BZNO"].astype(str).str.strip()
        ac12["BAS_YM"] = ac12["BAS_YM"].astype(str).str.replace(r"\.0$", "", regex=True).str.strip()
        ac12["_YEAR"] = ac12["BAS_YM"].str[:4]

        # 동일 사업자x연도에서 최신 레코드 유지
        ac12_dedup = (ac12.sort_values("BAS_YM", ascending=False)
                         .drop_duplicates(subset=["V_BZNO", "_YEAR"], keep="first"))
        feat_cols = [c for c in ac12_dedup.columns if c not in ("V_BZNO", "BAS_YM", "_YEAR")]
        rename = {c: f"AC12_{c}" for c in feat_cols}
        ac12_dedup = ac12_dedup[["V_BZNO", "_YEAR"] + feat_cols].rename(columns=rename)

        panel["_YEAR"] = panel["BASE_YM"].str[:4]
        panel = panel.merge(ac12_dedup, on=["V_BZNO", "_YEAR"], how="left")
        panel = panel.drop(columns=["_YEAR"], errors="ignore")
        log.info("  Joined AC12   - %%: %.1f%%",
                 panel["AC12_TOTAL_KRW_AM"].notna().mean() * 100)
        assert len(panel) == n_before, f"_join_ac12에서 행 폭증: {n_before} -> {len(panel)}"
        return panel

    def _join_aa17(self, panel: pd.DataFrame) -> pd.DataFrame:
        """
        생산판매(aa17): 연내 누적(YTD) 전제의 as-of backward join.

        AA17 값은 분기 독립값이 아니라 연내 누적치다 (연내 단조증가 96.4~97.6%,
        Q4 / JEMU 연매출 중앙값 ~ 1.0, 4분기합 / 연매출 ~ 2.78).
        따라서 아래 3종을 만든다.

          1) AA17_YTD_*   (주력, 수준값) — 관측시점 기준 이미 확정된 가장 최근 분기의
                          누계값을 변환 없이 사용. AA17_YTD_Q 로 몇 분기 누계인지 표시.
          2) AA17_YOY_*   (주력, 증감률) — 전년 동일 분기 YTD 대비. 같은 누계 구간끼리
                          비교하므로 왜곡이 없고 Q4 단독 그룹도 계산 가능.
          3) AA17_QTR_*   (보조, 분기 단독값) — 같은 연도 직전 분기(q-1)가 있을 때만 차분.
                          Q1은 그 자체가 단독값. 비인접 차분(Q3-Q1 등)은 하지 않는다.

        단위 주의: AA17은 천원 단위, JEMU / AC12는 원 단위다.
                   두 테이블을 함께 쓰는 파생변수(STAGE 5의 exp_fx 등)를 만들 때는
                   AA17 값에 1,000을 곱해 원 단위로 맞춰야 한다.
        """
        if "aa17" not in self.frames:
            return panel
        n_before = len(panel)

        aa = self.frames["aa17"].copy()
        aa["V_BZNO"] = aa["V_BZNO"].astype(str).str.strip()
        aa["_Y"] = aa["BAS_QQ"].str[:4].astype(int)
        aa["_Q"] = aa["BAS_QQ"].str[-1].astype(int)
        aa = aa.drop_duplicates(subset=["V_BZNO", "_Y", "_Q"], keep="last")

        AMT = {"LA_XPO_AM": "XPO", "DME_AM": "DME", "TOT_SEL_AM": "TOT"}
        TAGS = list(AMT.values())

        # --- 1) YTD 수준값 (원본 그대로) ---
        for src, tag in AMT.items():
            aa[f"AA17_YTD_{tag}"] = pd.to_numeric(aa[src], errors="coerce")
        aa["AA17_YTD_Q"] = aa["_Q"]

        # --- 3) QTR 분기 단독값: 같은 연도 직전 분기와만 차분 ---
        prev_q = aa[["V_BZNO", "_Y", "_Q"] + [f"AA17_YTD_{t}" for t in TAGS]].copy()
        prev_q["_Q"] = prev_q["_Q"] + 1
        prev_q = prev_q.rename(columns={f"AA17_YTD_{t}": f"_PQ_{t}" for t in TAGS})
        aa = aa.merge(prev_q, on=["V_BZNO", "_Y", "_Q"], how="left")

        diff_invalid = (aa["_Q"] != 1) & aa["_PQ_TOT"].isna()
        diff_neg = pd.Series(False, index=aa.index)
        for tag in TAGS:
            q = pd.Series(
                np.where(aa["_Q"] == 1, aa[f"AA17_YTD_{tag}"],
                         aa[f"AA17_YTD_{tag}"] - aa[f"_PQ_{tag}"]),
                index=aa.index)
            q[diff_invalid] = np.nan
            diff_neg |= (q < 0)
            aa[f"AA17_QTR_{tag}"] = q.mask(q < 0)
        aa["AA17_DIFF_INVALID_YN"] = diff_invalid.astype(int)
        aa["AA17_DIFF_NEG_YN"] = diff_neg.astype(int)

        # --- 2) YOY: 전년 동일 분기 YTD 대비 ---
        prev_y = aa[["V_BZNO", "_Y", "_Q"] + [f"AA17_YTD_{t}" for t in TAGS]].copy()
        prev_y["_Y"] = prev_y["_Y"] + 1
        prev_y = prev_y.rename(columns={f"AA17_YTD_{t}": f"_PY_{t}" for t in TAGS})
        aa = aa.merge(prev_y, on=["V_BZNO", "_Y", "_Q"], how="left")

        yoy_na = pd.Series(False, index=aa.index)
        for tag in TAGS:
            base = aa[f"_PY_{tag}"]
            aa[f"AA17_YOY_{tag}"] = aa[f"AA17_YTD_{tag}"] / base.where(base != 0) - 1
            yoy_na |= aa[f"AA17_YOY_{tag}"].isna()
        aa["AA17_YOY_NA_YN"] = yoy_na.astype(int)

        # --- 수출비중: 같은 YTD 기준끼리 계산 ---
        tot = aa["AA17_YTD_TOT"]
        aa["AA17_EXPORT_RATIO"] = aa["AA17_YTD_XPO"] / tot.where(tot != 0)

        # --- as-of backward join: 이미 확정된(분기 종료된) 가장 최근 분기 ---
        # 분기 종료 월 + 공시지연. 분기 마지막 날 실적이 그 달 안에 확정될 수 없다.
        aa["_AVAIL_IDX"] = aa["_Y"] * 12 + aa["_Q"] * 3 + AA17_PUB_LAG

        out_cols = ([f"AA17_YTD_{t}" for t in TAGS]
                    + [f"AA17_QTR_{t}" for t in TAGS]
                    + [f"AA17_YOY_{t}" for t in TAGS]
                    + ["AA17_YTD_Q", "AA17_EXPORT_RATIO",
                       "AA17_DIFF_INVALID_YN", "AA17_DIFF_NEG_YN", "AA17_YOY_NA_YN"])
        if "EXT_PROD_RECORD_YN" in aa.columns:
            aa = aa.rename(columns={"EXT_PROD_RECORD_YN": "AA17_EXT_PROD_RECORD_YN"})
            out_cols.append("AA17_EXT_PROD_RECORD_YN")

        right = aa[["V_BZNO", "_AVAIL_IDX"] + out_cols].sort_values("_AVAIL_IDX")

        left = panel[["V_BZNO", "BASE_YM"]].copy()
        left["_BASE_IDX"] = _ym_to_idx(left["BASE_YM"])
        left["_row"] = np.arange(len(left))
        left = left.sort_values("_BASE_IDX")

        merged = pd.merge_asof(
            left, right,
            left_on="_BASE_IDX", right_on="_AVAIL_IDX",
            by="V_BZNO", direction="backward",
        )
        merged = (merged.sort_values("_row")
                        .drop(columns=["_BASE_IDX", "_AVAIL_IDX", "V_BZNO", "BASE_YM", "_row"]))
        merged.index = panel.index
        panel = pd.concat([panel, merged], axis=1)

        cov = panel["AA17_YTD_TOT"].notna()
        log.info("  Joined AA17   - %%: %.1f%%  (YTD 수준값, 공시지연 %d개월)",
                 cov.mean() * 100, AA17_PUB_LAG)
        log.info("     AA17_YOY_TOT 계산가능: 전체 %.1f%% / AA17보유행 %.1f%%",
                 panel["AA17_YOY_TOT"].notna().mean() * 100,
                 panel.loc[cov, "AA17_YOY_TOT"].notna().mean() * 100 if cov.any() else 0)
        log.info("     AA17_QTR_TOT 계산가능: 전체 %.1f%% / AA17보유행 %.1f%%",
                 panel["AA17_QTR_TOT"].notna().mean() * 100,
                 panel.loc[cov, "AA17_QTR_TOT"].notna().mean() * 100 if cov.any() else 0)
        assert len(panel) == n_before, f"_join_aa17에서 행 폭증: {n_before} -> {len(panel)}"
        return panel

    def _join_aa10(self, panel: pd.DataFrame) -> pd.DataFrame:
        """
        종업원수(aa10): as-of join (해당 월 이전 가장 최근 측정값).
        """
        if "aa10" not in self.frames:
            return panel
        n_before = len(panel)
        aa10 = self.frames["aa10"].copy()
        aa10["V_BZNO"] = aa10["V_BZNO"].astype(str).str.strip()
        aa10 = aa10.dropna(subset=["BAS_DT"])
        aa10["BAS_YM"] = aa10["BAS_DT"].dt.strftime("%Y%m")
        aa10 = aa10.rename(columns={"PERS_CNT": "AA10_PERS_CNT"})

        # panel에 merge 후 해당 월 이전 최신값 선택 (as-of)
        panel_key = panel[["V_BZNO", "BASE_YM"]].copy()
        merged = panel_key.merge(aa10[["V_BZNO", "BAS_YM", "AA10_PERS_CNT"]],
                                 on="V_BZNO", how="left")
        # 해당 월 이전(<=)인 것만
        merged = merged[merged["BAS_YM"] <= merged["BASE_YM"]]
        # 가장 최근 값 선택
        latest = (merged.sort_values("BAS_YM", ascending=False)
                        .drop_duplicates(subset=["V_BZNO", "BASE_YM"], keep="first"))
        latest = latest[["V_BZNO", "BASE_YM", "AA10_PERS_CNT"]]
        panel = panel.merge(latest, on=["V_BZNO", "BASE_YM"], how="left")
        log.info("  Joined AA10   - %%: %.1f%%",
                 panel["AA10_PERS_CNT"].notna().mean() * 100)
        assert len(panel) == n_before, f"_join_aa10에서 행 폭증: {n_before} -> {len(panel)}"
        return panel

    def _join_crif(self, panel: pd.DataFrame) -> pd.DataFrame:
        """
        CB 신용불량(crif): 연도별 as-of join.

        한 기업이 같은 해에 신용불량 사유가 여러 건이면 조인이 패널 행을 복제한다
        (수정 전 실측 +50,214행). 따라서 조인 전에 (V_BZNO, 연도) 단위로 1행이 되도록
        집계한 뒤 조인한다.

          CRIF_EVENT_CNT   = 건수
          CRIF_RSN_AM_SUM  = SUM(CRDBD_RSN_AM)   <- 원천 컬럼명이 이미 SUM(...) 형태
          CRIF_OVD_AM_SUM  = SUM(CRDBD_OVD_AM)
          CRIF_WORST_RSNC  = 사유코드 중 최소값(가장 심각한 코드) 1개

        해제일 MAX(CRDBD_RLS_OCU_DT) / 해제사유 MAX(CRDBD_RLS_RSNC) 는 패널로 넘기지
        않는다. 부도기업 182건 전부(100%)가 부도 이후 해제이고 값의 92.3%가 결측인
        추출시점 스냅샷이라 사후 결과를 피처로 쓰는 셈이 된다.
        원천 프레임에는 남겨두므로 STAGE 6 S3b에서 시점 정합적으로 재구성할 수 있다.
        """
        if "crif" not in self.frames:
            return panel
        n_before = len(panel)
        crif = self.frames["crif"].copy()
        crif["V_BZNO"] = crif["V_BZNO"].astype(str).str.strip()

        if "CRDBD_OCU_YY" not in crif.columns:
            return panel
        crif["_YEAR"] = crif["CRDBD_OCU_YY"].astype(str).str[:4]

        rsn_am = "SUM(CRDBD_RSN_AM)"
        ovd_am = "SUM(CRDBD_OVD_AM)"
        for c in (rsn_am, ovd_am):
            if c in crif.columns:
                crif[c] = pd.to_numeric(crif[c], errors="coerce")

        agg_spec = {}
        if rsn_am in crif.columns:
            agg_spec["CRIF_RSN_AM_SUM"] = (rsn_am, "sum")
        if ovd_am in crif.columns:
            agg_spec["CRIF_OVD_AM_SUM"] = (ovd_am, "sum")
        if "CRDBD_RSNC" in crif.columns:
            agg_spec["CRIF_WORST_RSNC"] = ("CRDBD_RSNC", "min")

        agg = (crif.groupby(["V_BZNO", "_YEAR"], dropna=False)
                   .agg(CRIF_EVENT_CNT=("V_BZNO", "size"), **agg_spec)
                   .reset_index())

        log.info("  CRIF 집계: %d행 -> %d행 (중복 %d행 축약)",
                 len(crif), len(agg), len(crif) - len(agg))

        assert not agg.duplicated(["V_BZNO", "_YEAR"]).any(), \
            "CRIF 집계 후에도 (V_BZNO, _YEAR) 중복이 남아 있습니다."

        panel["_YEAR"] = panel["BASE_YM"].str[:4]
        panel = panel.merge(agg, on=["V_BZNO", "_YEAR"], how="left")
        panel = panel.drop(columns=["_YEAR"], errors="ignore")
        log.info("  Joined CRIF   - %%: %.1f%%",
                 panel["CRIF_EVENT_CNT"].notna().mean() * 100)
        assert len(panel) == n_before, f"_join_crif에서 행 폭증: {n_before} -> {len(panel)}"
        return panel

    # ================================================================
    # Step 3: Target 생성
    # ================================================================

    def _attach_target(self, panel: pd.DataFrame) -> pd.DataFrame:
        """
        IS_BUDO_IN_SPINE_YN 생성 규칙:
          - 해당 BASE_YM == 부도 발생 월(DEFAULT_YM) 이면 1

        ※ 이름 그대로 '스파인 내 부도만' 표시한다. 전체 부도 이벤트가 아니다.
          부도가 나면 여신이 정리되어 VH_OBV_DTL 레코드가 사라지므로, 부도월 자체가
          스파인 밖인 경우가 전체의 약 49%다. 12개월 라벨(IS_BUDO_12M)은 이 컬럼이
          아니라 budo_events.csv 의 전체 이벤트로 만들어야 한다.
          EDA / 명세서 표시 전용이며 모델 피처가 아니다 (leaky_cols.NON_FEATURE 등재).

        정상화 여부는 '부도 발생' 사실을 지우지 않는다. 부도는 그대로 1이고,
        정상화 정보(IS_RECOVERED / RECOVER_YM)는 패널에 함께 실어 두어
        STAGE 3의 '부도 진행 중 구간 제외'에서 종료 시점을 정하는 데만 쓴다.

        (구 정의는 `부도발생 AND 미정상화` 였으나, step1의 NMLZ_YN 파싱 버그로
         IS_RECOVERED 가 항상 0이어서 사실상 `부도발생` 과 동일하게 동작했다.
         파싱을 고치면서 정의를 명시적으로 분리한다.)

        모델 타임라인:
          - T: 예측 시점 (BASE_YM)
          - Y=1: T 시점에 부도 발생
        """
        budo = self.frames.get("budo", pd.DataFrame())
        if budo.empty:
            panel["IS_BUDO_IN_SPINE_YN"] = 0
            return panel

        n_before = len(panel)
        budo = budo.copy()
        budo["V_BZNO"] = budo["V_BZNO"].astype(str).str.strip()

        # 부도 발생 사업자의 부도 월 추출
        # 동월 복수사유는 aggregate_budo_events 가 1건으로 집계한다.
        default_events = aggregate_budo_events(budo)[
            ["V_BZNO", "DEFAULT_YM", "IS_RECOVERED", "RECOVER_YM"]].rename(columns={
                "DEFAULT_YM": "BASE_YM",
                "IS_RECOVERED": "_IS_RECOVERED",
            })
        assert not default_events.duplicated(["V_BZNO", "BASE_YM"]).any(), \
            "집계 후에도 (V_BZNO, BASE_YM) 중복이 남아 있습니다."

        default_events["_IS_DEFAULT_EVENT"] = 1

        panel = panel.merge(default_events, on=["V_BZNO", "BASE_YM"], how="left")
        panel["_IS_DEFAULT_EVENT"] = panel["_IS_DEFAULT_EVENT"].fillna(0).astype(int)
        panel["_IS_RECOVERED"] = panel["_IS_RECOVERED"].fillna(0).astype(int)

        # IS_BUDO_IN_SPINE_YN = 해당 월에 부도 발생. 정상화 여부는 반영하지 않는다.
        panel["IS_BUDO_IN_SPINE_YN"] = (panel["_IS_DEFAULT_EVENT"] == 1).astype(int)

        # 정상화 정보는 STAGE 3(부도 진행 중 구간 제외)에서 쓰도록 패널에 싣는다.
        # 둘 다 관측시점 이후 정보이므로 피처가 아니다 (leaky_cols.NON_FEATURE 등재).
        panel["IS_RECOVERED"] = np.where(panel["IS_BUDO_IN_SPINE_YN"] == 1,
                                         panel["_IS_RECOVERED"], np.nan)
        if "RECOVER_YM" not in panel.columns:
            panel["RECOVER_YM"] = np.nan
        panel.loc[panel["IS_BUDO_IN_SPINE_YN"] == 0, "RECOVER_YM"] = np.nan

        panel = panel.drop(columns=["_IS_DEFAULT_EVENT", "_IS_RECOVERED"], errors="ignore")

        assert len(panel) == n_before, \
            f"_attach_target에서 행 폭증: {n_before} -> {len(panel)}"

        budo_cnt = int(panel["IS_BUDO_IN_SPINE_YN"].sum())
        rec_cnt = int((panel["IS_RECOVERED"] == 1).sum())
        log.info("  Target IS_BUDO_IN_SPINE_YN=1: %d건 (%.4f%%)  |  그 중 정상화 %d건",
                 budo_cnt, budo_cnt / len(panel) * 100, rec_cnt)
        return panel

    # ================================================================
    # Step 4: 컬럼 정렬 & 저장
    # ================================================================

    def _reorder_columns(self, panel: pd.DataFrame) -> pd.DataFrame:
        """키 -> 메타 -> Target -> 피처 순 정렬."""
        priority = ["V_BZNO", "BASE_YM", "SPLIT", "IS_BUDO_IN_SPINE_YN",
                    "IS_RECOVERED", "RECOVER_YM",
                    "CONM", "ETB_DT", "COPR_OPNP_C", "BZSCAL_C", "STD_INDS_CFC"]
        ordered = [c for c in priority if c in panel.columns]
        rest = [c for c in panel.columns if c not in ordered]
        return panel[ordered + rest]

    def _save_budo_events(self) -> None:
        """부도 이벤트 원천을 별도 CSV로 남긴다.

        스파인에 없는 부도월(전체의 약 49%)까지 포함한다. 부도가 나면 여신이 정리되어
        VH_OBV_DTL 레코드가 사라지므로 부도월이 스파인 밖인 것이 오히려 다수다.
        STAGE 3의 12개월 라벨은 이 전체 이벤트를 써야 한다.
        """
        budo = self.frames.get("budo", pd.DataFrame())
        if budo.empty:
            return
        ev = aggregate_budo_events(budo)
        out = config.budo_events_path()
        ev.to_csv(out, index=False, encoding="utf-8-sig")
        log.info("  저장: %s (%d건, 정상화 %d건) — 스파인과 무관한 전체 부도 이벤트",
                 out.name, len(ev), int(ev["IS_RECOVERED"].sum()))

        # 스테일 감지용 메타. step5 가 원천 mtime 을 대조해 불일치하면 중단한다.
        from datetime import datetime
        src = config.budo_source_path()
        meta = {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "source_file": src.name if src else None,
            "source_mtime": round(src.stat().st_mtime, 3) if src else None,
            "source_size": src.stat().st_size if src else None,
            "n_events": len(ev),
            "n_recovered": int(ev["IS_RECOVERED"].sum()),
        }
        config.budo_events_meta_path().write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        log.info("  저장: %s (원천 mtime %s)",
                 config.budo_events_meta_path().name, meta["source_mtime"])

    def _save(self, panel: pd.DataFrame, mode: str) -> None:
        config.assert_writable(mode)
        self._save_budo_events()
        out = config.save_panel(panel, self.output_dir / config.PANEL_FILE[mode])
        log.info("  저장: %s  (%d rows x %d cols)", out.name, len(panel), len(panel.columns))

        # TRAIN / VALID 분리 저장
        train_p, valid_p = config.split_paths(mode)
        train = panel[panel["SPLIT"] == "TRAIN"]
        valid = panel[panel["SPLIT"] == "VALID"]
        tp = config.save_panel(train, train_p, sample=False)
        vp = config.save_panel(valid, valid_p, sample=False)
        log.info("  저장: %s (%d rows) / %s (%d rows)",
                 tp.name, len(train), vp.name, len(valid))
