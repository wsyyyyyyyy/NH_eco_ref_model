"""
======================================================================
Step 2 — 월별 패널 데이터 통합 (순수 Pandas 버전)
======================================================================
step1_load.py의 frames 딕셔너리를 받아
「V_BZNO × BASE_YM」 패널 구조의 통합 데이터셋을 생성합니다.

구조:
  - Skeleton: UPCHE(32,135사) × 월 캘린더(2021-01~2026-06)
  - 시간축 정렬: 각 테이블 → 해당 월에 가장 적합한 값을 as-of join
  - Target: IS_BUDO_YN (해당 월에 부도 발생 & 미정상화 = 1)
  - 분리: TRAIN (≤2023-12), VALID (≥2024-01)

사용법:
    from eda_pipeline.step2_integrate import PanelBuilder
    builder = PanelBuilder(frames, output_dir="eda_pipeline/output")
    panel = builder.build()
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

TRAIN_END = "202312"   # 학습 기간 마지막 월 (포함)
VALID_START = "202401" # 검증 기간 시작 월 (포함)
PANEL_START = "202101" # 전체 패널 시작
PANEL_END   = "202606" # 전체 패널 종료 (현재 기준)


def _make_calendar(start: str, end: str) -> pd.DataFrame:
    """YYYYMM 형식 월 캘린더 생성."""
    months = pd.date_range(
        start=f"{start[:4]}-{start[4:]}",
        end=f"{end[:4]}-{end[4:]}",
        freq="MS",
    )
    return pd.DataFrame({"BASE_YM": months.strftime("%Y%m")})


class PanelBuilder:
    """
    11개 전처리된 테이블 → 월별 패널 통합 데이터셋 생성기.
    """

    def __init__(
        self,
        frames: Dict[str, pd.DataFrame],
        output_dir: str | Path = "eda_pipeline/output",
    ) -> None:
        self.frames = frames
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    # ================================================================
    # Public
    # ================================================================

    def build(self) -> pd.DataFrame:
        """통합 패널 데이터셋을 빌드하고 CSV로 저장 후 반환합니다."""
        log.info("=" * 60)
        log.info("[INTEGRATE] 패널 데이터 통합 시작")
        log.info("  기간: %s ~ %s", PANEL_START, PANEL_END)
        log.info("=" * 60)

        # 1. 기반 Skeleton 생성
        panel = self._build_skeleton()
        log.info("  Skeleton: %d rows (기업 × 월)", len(panel))

        # 2. 각 테이블 LEFT JOIN
        panel = self._join_obv(panel)
        panel = self._join_jemu(panel)
        panel = self._join_grd_his(panel)
        panel = self._join_cg01(panel)
        panel = self._join_c302(panel)
        panel = self._join_ac12(panel)
        panel = self._join_aa17(panel)
        panel = self._join_aa10(panel)
        panel = self._join_crif(panel)

        # 3. Target 생성
        panel = self._attach_target(panel)

        # 4. 분리 플래그
        panel["SPLIT"] = np.where(panel["BASE_YM"] <= TRAIN_END, "TRAIN", "VALID")

        # 5. 컬럼 정렬 (키 → Target → 피처)
        panel = self._reorder_columns(panel)

        # 6. 저장
        self._save(panel)

        log.info("[INTEGRATE] 완료 — Shape: %s", panel.shape)
        log.info("  Train rows: %d  |  Valid rows: %d",
                 (panel["SPLIT"] == "TRAIN").sum(),
                 (panel["SPLIT"] == "VALID").sum())
        log.info("  Target 부도율(Train): %.4f%%",
                 panel.loc[panel["SPLIT"] == "TRAIN", "IS_BUDO_YN"].mean() * 100)

        return panel

    # ================================================================
    # Step 1: Skeleton
    # ================================================================

    def _build_skeleton(self) -> pd.DataFrame:
        """UPCHE 기업 마스터 × 월 캘린더 크로스 조인."""
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
        panel = master.merge(calendar, how="cross")

        # 설립일 숫자형 변환
        if "ETB_DT" in panel.columns:
            panel["ETB_DT"] = pd.to_numeric(panel["ETB_DT"], errors="coerce")

        panel = panel.sort_values(["V_BZNO", "BASE_YM"]).reset_index(drop=True)
        return panel

    # ================================================================
    # Step 2: 개별 테이블 JOIN 메서드
    # ================================================================

    def _join_obv(self, panel: pd.DataFrame) -> pd.DataFrame:
        """
        관찰세부등급(obv): V_BZNO + BAS_YM Exact Match.
        월별 여신한도, 잔액, PD, LGD, 관찰등급 등.
        """
        if "obv" not in self.frames:
            return panel
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
        return panel

    def _join_jemu(self, panel: pd.DataFrame) -> pd.DataFrame:
        """
        재무데이터(jemu): V_BZNO + 연도 as-of join.
        해당 월의 연도(YYYY)에 해당하는 최신 결산 재무 데이터를 붙입니다.
        Look-Ahead Bias 방지: 결산년도가 현재 월보다 미래면 제외.
        """
        if "jemu" not in self.frames:
            return panel
        jemu = self.frames["jemu"].copy()
        jemu["V_BZNO"] = jemu["V_BZNO"].astype(str).str.strip()

        # 결산기(FNA_CLS_YM) → 연도 + 유효월 생성
        jemu["FNA_CLS_YM"] = jemu["FNA_CLS_YM"].astype(str).str.strip().str.zfill(6)

        # 동일 사업자 × 결산연도 중 최신 결산기 1건만 유지
        jemu_dedup = (jemu.sort_values("FNA_CLS_YM", ascending=False)
                         .drop_duplicates(subset=["V_BZNO", "FNA_YEAR"], keep="first"))

        # panel의 연도 추출
        panel["_YEAR"] = panel["BASE_YM"].str[:4]

        # as-of join: 해당 연도의 재무 데이터 (Look-Ahead: 해당 월 ≥ FNA_CLS_YM)
        jemu_dedup = jemu_dedup.rename(columns={"FNA_YEAR": "_YEAR"})
        meta_cols = ["V_BZNO", "_YEAR", "AUD_OPI_DSC", "FNA_CLS_YM"]
        feat_cols = [c for c in jemu_dedup.columns if c not in meta_cols]
        rename = {c: f"JEMU_{c}" for c in feat_cols}
        jemu_dedup = jemu_dedup[meta_cols + feat_cols].rename(columns=rename)

        panel = panel.merge(jemu_dedup, on=["V_BZNO", "_YEAR"], how="left")

        # Look-Ahead Bias 제거: 결산기가 해당 월보다 미래면 제거
        if "FNA_CLS_YM" in panel.columns:
            mask_future = (panel["FNA_CLS_YM"].notna() &
                           (panel["FNA_CLS_YM"] > panel["BASE_YM"]))
            jemu_feat_cols = [c for c in panel.columns if c.startswith("JEMU_")]
            panel.loc[mask_future, jemu_feat_cols] = np.nan
            panel = panel.drop(columns=["FNA_CLS_YM", "AUD_OPI_DSC"], errors="ignore")

        panel = panel.drop(columns=["_YEAR"], errors="ignore")
        log.info("  Joined JEMU   - %%: %.1f%%",
                 (panel[[c for c in panel.columns if c.startswith("JEMU_")][0]].notna().mean() * 100
                  if any(c.startswith("JEMU_") for c in panel.columns) else 0))
        return panel

    def _join_grd_his(self, panel: pd.DataFrame) -> pd.DataFrame:
        """당행등급이력(grd_his): 연도별 as-of join."""
        if "grd_his" not in self.frames:
            return panel
        grd = self.frames["grd_his"].copy()
        grd["V_BZNO"] = grd["V_BZNO"].astype(str).str.strip()
        grd["_YEAR"] = grd["BASE_YEAR"].astype(str).str.strip()
        grd = grd.drop(columns=["BASE_YEAR"])
        rename = {c: f"GRD_{c}" for c in ["CRDEVL_PTTP_DSC", "LS_NICS_GRDC"]}
        grd = grd.rename(columns=rename)

        panel["_YEAR"] = panel["BASE_YM"].str[:4]
        panel = panel.merge(grd, on=["V_BZNO", "_YEAR"], how="left")
        panel = panel.drop(columns=["_YEAR"], errors="ignore")
        log.info("  Joined GRD_HIS - %%: %.1f%%",
                 panel["GRD_LS_NICS_GRDC"].notna().mean() * 100)
        return panel

    def _join_cg01(self, panel: pd.DataFrame) -> pd.DataFrame:
        """나이스신용평점(cg01): 연도별 as-of join."""
        if "cg01" not in self.frames:
            return panel
        cg01 = self.frames["cg01"].copy()
        cg01["V_BZNO"] = cg01["V_BZNO"].astype(str).str.strip()
        cg01["_YEAR"] = cg01["BASE_YEAR"].astype(str).str.strip()
        cg01 = cg01.drop(columns=["BASE_YEAR"])
        cg01 = cg01.rename(columns={"KIS_LS_FNA_MKS": "CG01_KIS_SCORE"})

        panel["_YEAR"] = panel["BASE_YM"].str[:4]
        panel = panel.merge(cg01, on=["V_BZNO", "_YEAR"], how="left")
        panel = panel.drop(columns=["_YEAR"], errors="ignore")
        log.info("  Joined CG01   - %%: %.1f%%",
                 panel["CG01_KIS_SCORE"].notna().mean() * 100)
        return panel

    def _join_c302(self, panel: pd.DataFrame) -> pd.DataFrame:
        """
        나이스CRI등급(c302): 유효기간 기반 as-of join.
        해당 BASE_YM이 [ST_DT, ED_DT) 구간 안에 있는 등급을 선택합니다.
        """
        if "c302" not in self.frames:
            return panel
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

        panel = panel.merge(valid, on=["V_BZNO", "BASE_YM"], how="left")
        log.info("  Joined C302   - %%: %.1f%%",
                 panel["C302_CRI_GRD"].notna().mean() * 100)
        return panel

    def _join_ac12(self, panel: pd.DataFrame) -> pd.DataFrame:
        """외화부채(ac12): 연도별 as-of join."""
        if "ac12" not in self.frames:
            return panel
        ac12 = self.frames["ac12"].copy()
        ac12["V_BZNO"] = ac12["V_BZNO"].astype(str).str.strip()
        ac12["BAS_YM"] = ac12["BAS_YM"].astype(str).str.replace(r"\.0$", "", regex=True).str.strip()
        ac12["_YEAR"] = ac12["BAS_YM"].str[:4]

        # 동일 사업자×연도에서 최신 레코드 유지
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
        return panel

    def _join_aa17(self, panel: pd.DataFrame) -> pd.DataFrame:
        """생산판매(aa17): 분기별 → 월 백필 (분기 종료월에 맞춤)."""
        if "aa17" not in self.frames:
            return panel
        aa17 = self.frames["aa17"].copy()
        aa17["V_BZNO"] = aa17["V_BZNO"].astype(str).str.strip()

        # BAS_QQ → 분기 종료 월 (Q1→03, Q2→06, Q3→09, Q4→12)
        quarter_to_end_month = {"1": "03", "2": "06", "3": "09", "4": "12"}
        def qq_to_ym(qq: str) -> str:
            yr, q = qq[:4], qq[-1]
            return f"{yr}{quarter_to_end_month.get(q, '12')}"

        aa17["TARGET_YM"] = aa17["BAS_QQ"].apply(qq_to_ym)

        feat_cols = [c for c in aa17.columns if c not in ("V_BZNO", "BAS_QQ", "TARGET_YM")]
        rename = {c: f"AA17_{c}" for c in feat_cols}
        aa17 = aa17.rename(columns=rename)

        # panel 월을 분기 종료 월로 매핑
        def month_to_q_end(ym: str) -> str:
            m = int(ym[4:6])
            qe = ((m - 1) // 3 + 1) * 3
            return f"{ym[:4]}{qe:02d}"

        panel["_QE_YM"] = panel["BASE_YM"].apply(month_to_q_end)
        panel = panel.merge(aa17[["V_BZNO", "TARGET_YM"] + list(rename.values())],
                            left_on=["V_BZNO", "_QE_YM"],
                            right_on=["V_BZNO", "TARGET_YM"], how="left")
        panel = panel.drop(columns=["_QE_YM", "TARGET_YM"], errors="ignore")
        log.info("  Joined AA17   - %%: %.1f%%",
                 panel["AA17_TOT_SEL_AM"].notna().mean() * 100)
        return panel

    def _join_aa10(self, panel: pd.DataFrame) -> pd.DataFrame:
        """
        종업원수(aa10): as-of join (해당 월 이전 가장 최근 측정값).
        """
        if "aa10" not in self.frames:
            return panel
        aa10 = self.frames["aa10"].copy()
        aa10["V_BZNO"] = aa10["V_BZNO"].astype(str).str.strip()
        aa10 = aa10.dropna(subset=["BAS_DT"])
        aa10["BAS_YM"] = aa10["BAS_DT"].dt.strftime("%Y%m")
        aa10 = aa10.rename(columns={"PERS_CNT": "AA10_PERS_CNT"})

        # panel에 merge 후 해당 월 이전 최신값 선택 (as-of)
        panel_key = panel[["V_BZNO", "BASE_YM"]].copy()
        merged = panel_key.merge(aa10[["V_BZNO", "BAS_YM", "AA10_PERS_CNT"]],
                                 on="V_BZNO", how="left")
        # 해당 월 이전(≤)인 것만
        merged = merged[merged["BAS_YM"] <= merged["BASE_YM"]]
        # 가장 최근 값 선택
        latest = (merged.sort_values("BAS_YM", ascending=False)
                        .drop_duplicates(subset=["V_BZNO", "BASE_YM"], keep="first"))
        latest = latest[["V_BZNO", "BASE_YM", "AA10_PERS_CNT"]]
        panel = panel.merge(latest, on=["V_BZNO", "BASE_YM"], how="left")
        log.info("  Joined AA10   - %%: %.1f%%",
                 panel["AA10_PERS_CNT"].notna().mean() * 100)
        return panel

    def _join_crif(self, panel: pd.DataFrame) -> pd.DataFrame:
        """CB 신용불량(crif): 연도별 as-of join."""
        if "crif" not in self.frames:
            return panel
        crif = self.frames["crif"].copy()
        crif["V_BZNO"] = crif["V_BZNO"].astype(str).str.strip()

        if "CRDBD_OCU_YY" in crif.columns:
            crif["_YEAR"] = crif["CRDBD_OCU_YY"].astype(str).str[:4]
        else:
            return panel

        feat_cols = [c for c in crif.columns if c not in ("V_BZNO", "CRDBD_OCU_YY", "_YEAR",
                                                            "CRINF_RLR_DSC")]
        rename = {c: f"CRIF_{c}" for c in feat_cols}
        crif = crif.rename(columns=rename)

        panel["_YEAR"] = panel["BASE_YM"].str[:4]
        panel = panel.merge(crif[["V_BZNO", "_YEAR"] + list(rename.values())],
                            on=["V_BZNO", "_YEAR"], how="left")
        panel = panel.drop(columns=["_YEAR"], errors="ignore")
        log.info("  Joined CRIF   - %%: %.1f%%",
                 panel.get(list(rename.values())[0], pd.Series()).notna().mean() * 100
                 if rename else 0)
        return panel

    # ================================================================
    # Step 3: Target 생성
    # ================================================================

    def _attach_target(self, panel: pd.DataFrame) -> pd.DataFrame:
        """
        IS_BUDO_YN 생성 규칙:
          - 해당 BASE_YM == 부도 발생 월(DEFAULT_YM)
          - 정상화되지 않은 경우(IS_RECOVERED == 0) 또는 NMLZ_YN이 없는 경우
        
        모델 타임라인:
          - T: 예측 시점 (BASE_YM)
          - Y=1: T 시점에 부도 발생
        """
        budo = self.frames.get("budo", pd.DataFrame())
        if budo.empty:
            panel["IS_BUDO_YN"] = 0
            return panel

        budo = budo.copy()
        budo["V_BZNO"] = budo["V_BZNO"].astype(str).str.strip()

        # 부도 발생 사업자의 부도 월 추출
        default_events = budo[budo["IS_DEFAULT"] == 1][["V_BZNO", "DEFAULT_YM", "IS_RECOVERED"]].copy()
        default_events = default_events.rename(columns={
            "DEFAULT_YM": "BASE_YM",
            "IS_RECOVERED": "_IS_RECOVERED",
        })
        default_events["_IS_DEFAULT_EVENT"] = 1

        panel = panel.merge(default_events, on=["V_BZNO", "BASE_YM"], how="left")
        panel["_IS_DEFAULT_EVENT"] = panel["_IS_DEFAULT_EVENT"].fillna(0).astype(int)
        panel["_IS_RECOVERED"] = panel["_IS_RECOVERED"].fillna(0).astype(int)

        # IS_BUDO_YN = 부도 발생 & 미정상화
        panel["IS_BUDO_YN"] = (
            (panel["_IS_DEFAULT_EVENT"] == 1) &
            (panel["_IS_RECOVERED"] == 0)
        ).astype(int)

        panel = panel.drop(columns=["_IS_DEFAULT_EVENT", "_IS_RECOVERED"], errors="ignore")

        budo_cnt = panel["IS_BUDO_YN"].sum()
        log.info("  Target IS_BUDO_YN=1: %d건 (%.4f%%)", budo_cnt,
                 budo_cnt / len(panel) * 100)
        return panel

    # ================================================================
    # Step 4: 컬럼 정렬 & 저장
    # ================================================================

    def _reorder_columns(self, panel: pd.DataFrame) -> pd.DataFrame:
        """키 → 메타 → Target → 피처 순 정렬."""
        priority = ["V_BZNO", "BASE_YM", "SPLIT", "IS_BUDO_YN",
                    "CONM", "ETB_DT", "COPR_OPNP_C", "BZSCAL_C", "STD_INDS_CFC"]
        ordered = [c for c in priority if c in panel.columns]
        rest = [c for c in panel.columns if c not in ordered]
        return panel[ordered + rest]

    def _save(self, panel: pd.DataFrame) -> None:
        out = self.output_dir / "nh_panel_full.csv"
        panel.to_csv(out, index=False, encoding="utf-8-sig")
        log.info("  저장: %s  (%d rows × %d cols)", out, len(panel), len(panel.columns))

        # TRAIN / VALID 분리 저장
        train = panel[panel["SPLIT"] == "TRAIN"]
        valid = panel[panel["SPLIT"] == "VALID"]
        train.to_csv(self.output_dir / "nh_panel_train.csv", index=False, encoding="utf-8-sig")
        valid.to_csv(self.output_dir / "nh_panel_valid.csv", index=False, encoding="utf-8-sig")
        log.info("  저장: nh_panel_train.csv (%d rows) / nh_panel_valid.csv (%d rows)",
                 len(train), len(valid))
