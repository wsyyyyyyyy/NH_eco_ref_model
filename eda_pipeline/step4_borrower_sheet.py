"""
======================================================================
Step 4 — 차주별(V_BZNO) 통합 시트 생성
======================================================================
11개 원천 테이블을 차주(V_BZNO) 1건 = 1행으로 집약합니다.
TRAIN/VALID 분리 이전의 전체 차주 기준 통합 뷰입니다.

집계 철학:
  - 월별/분기별 시계열 → 요약 통계 (최신값, 평균, 추세, 변화량)
  - 등급 이력 → 연도별 Wide + 방향성 파생변수
  - 부도 정보 → Target 그대로 보존

사용법:
    from eda_pipeline.step4_borrower_sheet import BorrowerSheetBuilder
    builder = BorrowerSheetBuilder(frames, output_dir="eda_pipeline/output")
    sheet = builder.build()
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

# ── JEMU 계정코드 → 한글명 매핑 ────────────────────────────────────
# ※ 아래 매핑은 input/가상사업자_JEMU_재무데이터v.txt 0행(한글 논리명)을 직접 대조해
#   정정한 것이다. 과거 매핑은 118100 부터 한 칸씩 밀려 28개 중 21개가 틀려 있었다.
#   (예: 191204 를 'ROE' 로, 191208 을 '매출채권회전율' 로 표기)
#   표시 라벨만 바로잡았으며 계산 로직은 원천 헤더와 이미 일치하므로 손대지 않았다.
JEMU_COL_MAP: Dict[str, str] = {
    "112000": "유동자산(계)",
    "114000": "비유동자산(계)",
    "115000": "자산총계",
    "116000": "유동부채(계)",
    "117000": "비유동부채(계)",
    "118000": "부채총계",
    "118100": "자본금",
    "118900": "자본총계",
    "121000": "매출액",
    "123000": "매출총이익(손실)",
    "125000": "영업이익(손실)",
    "125100": "영업외수익",
    "126000": "영업외비용",
    "128000": "법인세비용차감전계속사업이익(손실)",
    "129000": "당기순이익(손실)",
    "191104": "매출액증가율",
    "191105": "순이익증가율",
    "191108": "영업이익증가율",
    "191110": "재고자산증가율",
    "191204": "매출액영업이익율",
    "191207": "이자보상배율(배)",
    "191208": "자기자본순이익율",
    "191210": "총자본순이익율",
    "191310": "EBITDA이자보상배율(배)",
    "191502": "매출채권회전율",
    "191503": "영업자산회전율",
    "191505": "재고자산회전율",
    "191506": "총자본회전율",
}


class BorrowerSheetBuilder:
    """
    차주별 통합 시트 생성기.
    step1_load.py의 frames를 받아 V_BZNO 1행짜리 시트를 반환합니다.
    """

    def __init__(
        self,
        frames: Dict[str, pd.DataFrame],
        output_dir: str | Path = "eda_pipeline/output",
        write_kr: bool = False,
    ) -> None:
        self.frames = frames
        self.write_kr = write_kr
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    # ================================================================
    # Public
    # ================================================================

    def build(self) -> pd.DataFrame:
        """전체 통합 시트 빌드 → CSV 저장 후 반환."""
        log.info("=" * 60)
        log.info("[BORROWER SHEET] 차주별 통합 시트 생성 시작")
        log.info("=" * 60)

        # 1. UPCHE 기업 기본정보 (행 기준 = 마스터)
        sheet = self._build_upche_base()
        log.info("  Base: %d rows", len(sheet))

        # 2. Target (부도정보)
        sheet = self._attach_target(sheet)

        # 3. OBV 관찰세부등급 (월별 요약)
        sheet = self._attach_obv(sheet)

        # 4. JEMU 재무데이터 (최신 + YoY)
        sheet = self._attach_jemu(sheet)

        # 5. GRD_HIS 당행 내부등급 이력
        sheet = self._attach_grd_his(sheet)

        # 6. CG01 나이스 신용평점
        sheet = self._attach_cg01(sheet)

        # 7. C302 나이스 CRI 등급
        sheet = self._attach_c302(sheet)

        # 8. AC12 외화부채
        sheet = self._attach_ac12(sheet)

        # 9. AA17 생산판매 (분기 → 연도)
        sheet = self._attach_aa17(sheet)

        # 10. AA10 종업원수
        sheet = self._attach_aa10(sheet)

        # 11. CRIF 신용불량 이력
        sheet = self._attach_crif(sheet)

        # 12. 컬럼 정렬 (Target 앞으로)
        sheet = self._reorder_columns(sheet)

        # 13. 저장
        self._save(sheet)

        log.info("[BORROWER SHEET] 완료 - Shape: %s", sheet.shape)
        log.info("  부도 차주: %d / 전체: %d (%.4f%%)",
                 sheet["IS_DEFAULT"].sum(), len(sheet),
                 sheet["IS_DEFAULT"].mean() * 100)
        return sheet

    # ================================================================
    # 1. UPCHE 기업 기본정보
    # ================================================================

    def _build_upche_base(self) -> pd.DataFrame:
        upche = self.frames.get("upche", pd.DataFrame()).copy()
        upche["V_BZNO"] = upche["V_BZNO"].astype(str).str.strip()
        
        # BZSCAL_C 변환 및 4.0 필터링 적용
        if "BZSCAL_C" in upche.columns:
            upche["BZSCAL_C"] = pd.to_numeric(upche["BZSCAL_C"], errors="coerce")
            log.info("  [FILTER] 기업규모(BZSCAL_C) == 4.0 인 데이터만 추출합니다.")
            upche = upche[upche["BZSCAL_C"] == 4.0]
            
        upche = upche.drop_duplicates("V_BZNO")

        # 설립연도 파생
        if "ETB_DT" in upche.columns:
            upche["ETB_DT"] = upche["ETB_DT"].astype(str).str.replace(r"\.0$", "", regex=True)
            upche["ETB_YEAR"] = pd.to_numeric(
                upche["ETB_DT"].str[:4], errors="coerce"
            )
            upche["COMPANY_AGE"] = 2025 - upche["ETB_YEAR"]

        # 종업원수 (UPCHE의 EMPCN: 단일 시점 참조용으로 유지)
        if "EMPCN" in upche.columns:
            upche["EMPCN"] = pd.to_numeric(upche["EMPCN"], errors="coerce")

        keep = [c for c in ["V_BZNO", "CONM", "ETB_DT", "ETB_YEAR", "COMPANY_AGE",
                             "COPR_OPNP_C", "BZSCAL_C", "STD_INDS_CFC", "EMPCN"]
                if c in upche.columns]
        return upche[keep].reset_index(drop=True)

    # ================================================================
    # 2. Target (부도정보)
    # ================================================================

    def _attach_target(self, sheet: pd.DataFrame) -> pd.DataFrame:
        budo = self.frames.get("budo", pd.DataFrame()).copy()
        if budo.empty:
            sheet["IS_DEFAULT"] = 0
            sheet["DEFAULT_CNT"] = 0
            return sheet

        budo["V_BZNO"] = budo["V_BZNO"].astype(str).str.strip()

        # DSH_DT → 문자열 YYYYMM
        if "DSH_DT" in budo.columns:
            budo["DSH_DT_DT"] = pd.to_datetime(budo["DSH_DT"], errors="coerce")
            budo["DEFAULT_YM"] = budo["DSH_DT_DT"].dt.strftime("%Y%m")
            budo["DEFAULT_YEAR"] = budo["DSH_DT_DT"].dt.year
            budo["IS_DEFAULT"] = budo["DSH_DT_DT"].notna().astype(int)

        if "NMLZ_YN" in budo.columns:
            # NMLZ_YN 의 실제 값은 '0' / '1' 이다. 'Y' 비교는 정상화 152건을 전부
            # 미정상화로 판정한다 (step1_load.py 와 동일한 버그였다).
            budo["IS_RECOVERED"] = (
                budo["NMLZ_YN"].astype(str).str.strip().str.upper().isin(["1", "Y"])
            ).astype(int)

        if "NMLZ_DT" in budo.columns:
            budo["NMLZ_DT_STR"] = pd.to_datetime(
                budo["NMLZ_DT"], errors="coerce"
            ).dt.strftime("%Y%m%d")

        # 부도 횟수 계산
        default_cnt = budo[budo["DSH_DT_DT"].notna()].groupby("V_BZNO").size().rename("DEFAULT_CNT")

        target_cols = [c for c in ["V_BZNO", "IS_DEFAULT", "DEFAULT_YM", "DEFAULT_YEAR",
                                    "DSH_RSN_DSC", "IS_RECOVERED", "NMLZ_DT_STR",
                                    "BRWR_DSH_YN"]
                       if c in budo.columns]
                       
        # 여러 번 부도가 발생한 경우 '최초' 부도 발생 시점을 기준으로 타겟을 설정
        if "DSH_DT_DT" in budo.columns:
            budo_sorted = budo.sort_values(by=["V_BZNO", "DSH_DT_DT"], ascending=[True, True])
        else:
            budo_sorted = budo
            
        budo_slim = budo_sorted[target_cols].drop_duplicates("V_BZNO")

        sheet = sheet.merge(budo_slim, on="V_BZNO", how="left")
        sheet = sheet.merge(default_cnt, on="V_BZNO", how="left")
        
        sheet["IS_DEFAULT"] = sheet["IS_DEFAULT"].fillna(0).astype(int)
        sheet["IS_RECOVERED"] = sheet.get("IS_RECOVERED", pd.Series(0, index=sheet.index)).fillna(0).astype(int)
        sheet["DEFAULT_CNT"] = sheet.get("DEFAULT_CNT", pd.Series(0, index=sheet.index)).fillna(0).astype(int)
        
        log.info("  Target - 부도: %d건", sheet["IS_DEFAULT"].sum())
        return sheet

    # ================================================================
    # 3. OBV 관찰세부등급 (월별 → 요약)
    # ================================================================

    def _attach_obv(self, sheet: pd.DataFrame) -> pd.DataFrame:
        if "obv" not in self.frames:
            return sheet
        obv = self.frames["obv"].copy()
        obv["V_BZNO"] = obv["V_BZNO"].astype(str).str.strip()
        obv["BAS_YM"] = obv["BAS_YM"].astype(str).str.strip()

        num_cols = [c for c in obv.columns if c not in ("V_BZNO", "BAS_YM", "ELYWRN_OBV_GRD_DSC")]
        for c in num_cols:
            obv[c] = pd.to_numeric(obv[c], errors="coerce")

        # 관찰 월수 (데이터 커버리지 품질)
        obs_cnt = obv.groupby("V_BZNO")["BAS_YM"].count().rename("OBV_MONTHS_CNT")

        # 최신 & 최초 관측 월 → 각 지표의 최신/최초값
        obv_sorted = obv.sort_values("BAS_YM")
        first_obs = obv_sorted.drop_duplicates("V_BZNO", keep="first").set_index("V_BZNO")[num_cols]
        last_obs  = obv_sorted.drop_duplicates("V_BZNO", keep="last").set_index("V_BZNO")[num_cols]
        mean_obs  = obv.groupby("V_BZNO")[num_cols].mean()

        # 최근 OBV 등급 (범주형)
        grd_last = (obv_sorted
                    .dropna(subset=["ELYWRN_OBV_GRD_DSC"])
                    .drop_duplicates("V_BZNO", keep="last")
                    .set_index("V_BZNO")[["ELYWRN_OBV_GRD_DSC"]]
                    .rename(columns={"ELYWRN_OBV_GRD_DSC": "OBV_GRD_LATEST"}))

        # 추세: (마지막 - 처음) / |처음| → 각 수치 지표별
        trend = pd.DataFrame(index=first_obs.index)
        for c in num_cols:
            first_v = first_obs[c]
            last_v  = last_obs[c]
            denom   = first_v.replace(0, np.nan).abs()
            trend[c] = (last_v - first_v) / denom

        # 컬럼명 prefix 붙이기
        first_obs.columns  = [f"OBV_{c}_FIRST"  for c in num_cols]
        last_obs.columns   = [f"OBV_{c}_LAST"   for c in num_cols]
        mean_obs.columns   = [f"OBV_{c}_MEAN"   for c in num_cols]
        trend.columns      = [f"OBV_{c}_TREND"  for c in num_cols]

        obv_agg = pd.concat([
            obs_cnt, first_obs, last_obs, mean_obs, trend, grd_last
        ], axis=1).reset_index()

        sheet = sheet.merge(obv_agg, on="V_BZNO", how="left")
        log.info("  OBV 집계 완료 - 추가 컬럼: %d개",
                 len([c for c in sheet.columns if c.startswith("OBV_")]))
        return sheet

    # ================================================================
    # 4. JEMU 재무데이터 (최신 + YoY)
    # ================================================================

    def _attach_jemu(self, sheet: pd.DataFrame) -> pd.DataFrame:
        if "jemu" not in self.frames:
            return sheet
        jemu = self.frames["jemu"].copy()
        jemu["V_BZNO"] = jemu["V_BZNO"].astype(str).str.strip()
        jemu["FNA_CLS_YM"] = jemu["FNA_CLS_YM"].astype(str).str.strip().str.zfill(6)
        jemu["FNA_YEAR"] = jemu["FNA_CLS_YM"].str[:4]

        num_cols = [c for c in jemu.columns
                    if c not in ("V_BZNO", "AUD_OPI_DSC", "FNA_CLS_YM", "FNA_YEAR")]
        for c in num_cols:
            jemu[c] = pd.to_numeric(jemu[c], errors="coerce")

        # 연도별 중복 제거 (최신 결산기 우선)
        jemu_dedup = (jemu.sort_values("FNA_CLS_YM", ascending=False)
                         .drop_duplicates(subset=["V_BZNO", "FNA_YEAR"], keep="first"))

        # 보유 재무제표 연수
        avail_years = (jemu_dedup.groupby("V_BZNO")["FNA_YEAR"]
                       .nunique().rename("JEMU_AVAIL_YEARS"))
        latest_year = (jemu_dedup.groupby("V_BZNO")["FNA_YEAR"]
                       .max().rename("JEMU_LATEST_YEAR"))

        # 최신 재무 값 (연도 내림차순 정렬 후 첫 번째)
        jemu_sorted_desc = jemu_dedup.sort_values(["V_BZNO", "FNA_YEAR"], ascending=[True, False])
        latest_jemu = jemu_sorted_desc.drop_duplicates("V_BZNO", keep="first").copy()
        latest_jemu = latest_jemu.set_index("V_BZNO")

        # 전년도 재무 값 (최신 다음 순위)
        jemu_sorted_asc = jemu_dedup.sort_values(["V_BZNO", "FNA_YEAR"], ascending=[True, True])

        def _get_prev_row(g: pd.DataFrame):
            """두 개 이상 연도 보유 시 마지막에서 2번째 행 반환."""
            if len(g) >= 2:
                return g.iloc[-2][num_cols]
            return g.iloc[-1][num_cols]

        prev_jemu = jemu_sorted_asc.groupby("V_BZNO").apply(
            _get_prev_row, include_groups=False
        )  # 인덱스 = V_BZNO

        # YoY 변화율
        yoy = pd.DataFrame(index=latest_jemu.index)
        for c in num_cols:
            if c in prev_jemu.columns and c in latest_jemu.columns:
                denom = prev_jemu[c].replace(0, np.nan).abs()
                yoy[c] = (latest_jemu[c] - prev_jemu[c]) / denom * 100

        # 컬럼명은 계정 코드를 유지한다. 한글 라벨은 JEMU_COL_MAP 을 참조해
        # 사람이 읽는 리포트에서만 적용하고, 필요하면 _kr.csv 로 병행 출력한다.
        # (한글 컬럼명은 인코딩 문제를 일으킬 수 있다.)
        def _jemu_name(code: str, suffix: str) -> str:
            return f"JEMU_{code}_{suffix}"

        latest_cols_renamed = {c: _jemu_name(c, "LATEST") for c in num_cols}
        yoy_cols_renamed    = {c: _jemu_name(c, "YOY")    for c in num_cols}

        latest_jemu_r = latest_jemu[num_cols].rename(columns=latest_cols_renamed)
        yoy_r         = yoy.rename(columns=yoy_cols_renamed)

        # 감사의견 (최신)
        if "AUD_OPI_DSC" in latest_jemu.columns:
            latest_jemu_r["JEMU_감사의견_LATEST"] = latest_jemu["AUD_OPI_DSC"]

        jemu_agg = pd.concat([avail_years, latest_year, latest_jemu_r, yoy_r], axis=1).reset_index()
        sheet = sheet.merge(jemu_agg, on="V_BZNO", how="left")
        log.info("  JEMU 집계 완료 - 추가 컬럼: %d개",
                 len([c for c in sheet.columns if c.startswith("JEMU_")]))
        return sheet

    # ================================================================
    # 5. GRD_HIS 당행 내부등급 이력
    # ================================================================

    def _attach_grd_his(self, sheet: pd.DataFrame) -> pd.DataFrame:
        if "grd_his" not in self.frames:
            return sheet
        grd = self.frames["grd_his"].copy()
        grd["V_BZNO"] = grd["V_BZNO"].astype(str).str.strip()
        grd["BASE_YEAR"] = grd["BASE_YEAR"].astype(str).str.strip()
        grd["LS_NICS_GRDC"] = pd.to_numeric(grd["LS_NICS_GRDC"], errors="coerce")

        # ── 연도별 NICS 등급 Wide ─────────────────────────────────────
        years = sorted(grd["BASE_YEAR"].dropna().unique())
        nics_wide = (grd.pivot_table(index="V_BZNO", columns="BASE_YEAR",
                                     values="LS_NICS_GRDC", aggfunc="first")
                        .rename(columns={yr: f"GRD_NICS_{yr}" for yr in years}))
        nics_wide.columns.name = None
        nics_wide = nics_wide.reset_index()

        # ── 요약 파생변수 ────────────────────────────────────────────
        grd_sorted = grd.sort_values("BASE_YEAR")

        def _grd_stats(g: pd.DataFrame) -> pd.Series:
            nics = g["LS_NICS_GRDC"].dropna()
            if nics.empty:
                return pd.Series({
                    "GRD_NICS_LATEST": np.nan, "GRD_NICS_EARLIEST": np.nan,
                    "GRD_NICS_CHANGE_TOTAL": np.nan, "GRD_NICS_CHANGE_LAST2Y": np.nan,
                    "GRD_NICS_DOWNGRADE_CNT": np.nan, "GRD_NICS_UPGRADE_CNT": np.nan,
                    "GRD_NICS_VOLATILITY": np.nan,
                    "GRD_CRDEVL_PTTP_LATEST": np.nan,
                })
            nics_sorted = g.sort_values("BASE_YEAR")["LS_NICS_GRDC"].dropna()
            diff = nics_sorted.diff().dropna()
            # NICS 등급: 숫자가 클수록 낮은 등급 → 상승(양수)=악화, 하락(음수)=개선
            return pd.Series({
                "GRD_NICS_LATEST":         nics_sorted.iloc[-1],
                "GRD_NICS_EARLIEST":       nics_sorted.iloc[0],
                "GRD_NICS_CHANGE_TOTAL":   nics_sorted.iloc[-1] - nics_sorted.iloc[0],
                "GRD_NICS_CHANGE_LAST2Y":  (nics_sorted.iloc[-1] - nics_sorted.iloc[-2]
                                            if len(nics_sorted) >= 2 else np.nan),
                "GRD_NICS_DOWNGRADE_CNT":  (diff > 0).sum(),   # 숫자 증가 = 등급 하락
                "GRD_NICS_UPGRADE_CNT":    (diff < 0).sum(),   # 숫자 감소 = 등급 상승
                "GRD_NICS_VOLATILITY":     nics_sorted.std(),
                "GRD_CRDEVL_PTTP_LATEST":  (g.sort_values("BASE_YEAR")["CRDEVL_PTTP_DSC"]
                                            .dropna().iloc[-1]
                                            if "CRDEVL_PTTP_DSC" in g.columns
                                               and not g["CRDEVL_PTTP_DSC"].dropna().empty
                                            else np.nan),
            })

        grd_stats = grd_sorted.groupby("V_BZNO").apply(_grd_stats, include_groups=False).reset_index()

        grd_agg = nics_wide.merge(grd_stats, on="V_BZNO", how="outer")
        sheet = sheet.merge(grd_agg, on="V_BZNO", how="left")
        log.info("  GRD_HIS 집계 완료 - 추가 컬럼: %d개",
                 len([c for c in sheet.columns if c.startswith("GRD_")]))
        return sheet

    # ================================================================
    # 6. CG01 나이스 신용평점
    # ================================================================

    def _attach_cg01(self, sheet: pd.DataFrame) -> pd.DataFrame:
        if "cg01" not in self.frames:
            return sheet
        cg01 = self.frames["cg01"].copy()
        cg01["V_BZNO"] = cg01["V_BZNO"].astype(str).str.strip()
        cg01["BASE_YEAR"] = cg01["BASE_YEAR"].astype(str).str.strip()
        cg01["KIS_LS_FNA_MKS"] = pd.to_numeric(
            cg01["KIS_LS_FNA_MKS"].replace(-1, np.nan), errors="coerce"
        )

        # 연도별 Wide
        years = sorted(cg01["BASE_YEAR"].dropna().unique())
        cg01_wide = (cg01.pivot_table(index="V_BZNO", columns="BASE_YEAR",
                                      values="KIS_LS_FNA_MKS", aggfunc="first")
                        .rename(columns={yr: f"CG01_KIS_{yr}" for yr in years}))
        cg01_wide.columns.name = None

        # 요약
        def _cg01_stats(g: pd.DataFrame) -> pd.Series:
            ks = g.sort_values("BASE_YEAR")["KIS_LS_FNA_MKS"].dropna()
            if ks.empty:
                return pd.Series({"CG01_KIS_LATEST": np.nan,
                                   "CG01_KIS_EARLIEST": np.nan,
                                   "CG01_KIS_CHANGE_TOTAL": np.nan,
                                   "CG01_KIS_TREND_SLOPE": np.nan})
            slope = np.nan
            if len(ks) >= 2:
                x = np.arange(len(ks))
                slope = np.polyfit(x, ks.values, 1)[0]
            return pd.Series({
                "CG01_KIS_LATEST":       ks.iloc[-1],
                "CG01_KIS_EARLIEST":     ks.iloc[0],
                "CG01_KIS_CHANGE_TOTAL": ks.iloc[-1] - ks.iloc[0],
                "CG01_KIS_TREND_SLOPE":  slope,    # 양수 = 평점 상승 = 개선
            })

        cg01_stats = cg01.groupby("V_BZNO").apply(_cg01_stats, include_groups=False).reset_index()
        cg01_agg = cg01_wide.reset_index().merge(cg01_stats, on="V_BZNO", how="outer")
        sheet = sheet.merge(cg01_agg, on="V_BZNO", how="left")
        log.info("  CG01 집계 완료 - 추가 컬럼: %d개",
                 len([c for c in sheet.columns if c.startswith("CG01_")]))
        return sheet

    # ================================================================
    # 7. C302 나이스 CRI 등급
    # ================================================================

    def _attach_c302(self, sheet: pd.DataFrame) -> pd.DataFrame:
        if "c302" not in self.frames:
            return sheet
        c302 = self.frames["c302"].copy()
        c302["V_BZNO"] = c302["V_BZNO"].astype(str).str.strip()
        c302["ST_DT"] = c302["ST_DT"].astype(str).str.replace(r"\.0$", "", regex=True).str.strip()
        c302["ED_DT"] = c302["ED_DT"].astype(str).str.replace(r"\.0$", "", regex=True).str.strip()
        c302["ST_DT_DT"] = pd.to_datetime(c302["ST_DT"], format="%Y%m%d", errors="coerce")
        c302["CRI_GRD_ORD"] = pd.to_numeric(c302.get("CRI_GRD_ORD", pd.Series(dtype=float)),
                                             errors="coerce")

        c302_sorted = c302.sort_values("ST_DT_DT")

        def _c302_stats(g: pd.DataFrame) -> pd.Series:
            g = g.sort_values("ST_DT_DT")
            grd_series = g["CRI_GRD"].dropna()
            ord_series = g["CRI_GRD_ORD"].dropna()
            if grd_series.empty:
                return pd.Series({
                    "C302_CRI_LATEST_GRD": np.nan, "C302_CRI_EARLIEST_GRD": np.nan,
                    "C302_CRI_LATEST_ORD": np.nan, "C302_CRI_CHANGE_ORD": np.nan,
                    "C302_CRI_DOWNGRADE_CNT": np.nan, "C302_CRI_PERIODS_CNT": 0,
                })
            diff_ord = ord_series.diff().dropna()
            return pd.Series({
                "C302_CRI_LATEST_GRD":   grd_series.iloc[-1],
                "C302_CRI_EARLIEST_GRD": grd_series.iloc[0],
                "C302_CRI_LATEST_ORD":   ord_series.iloc[-1] if not ord_series.empty else np.nan,
                "C302_CRI_CHANGE_ORD":   (ord_series.iloc[-1] - ord_series.iloc[0]
                                          if len(ord_series) >= 2 else np.nan),
                # 서열이 클수록 낮은 등급 → 증가=하락=악화
                "C302_CRI_DOWNGRADE_CNT": (diff_ord > 0).sum(),
                "C302_CRI_UPGRADE_CNT":   (diff_ord < 0).sum(),
                "C302_CRI_PERIODS_CNT":  len(g),
            })

        c302_stats = c302_sorted.groupby("V_BZNO").apply(_c302_stats, include_groups=False).reset_index()
        sheet = sheet.merge(c302_stats, on="V_BZNO", how="left")
        log.info("  C302 집계 완료 - 추가 컬럼: %d개",
                 len([c for c in sheet.columns if c.startswith("C302_")]))
        return sheet

    # ================================================================
    # 8. AC12 외화부채
    # ================================================================

    def _attach_ac12(self, sheet: pd.DataFrame) -> pd.DataFrame:
        if "ac12" not in self.frames:
            return sheet
        ac12 = self.frames["ac12"].copy()
        ac12["V_BZNO"] = ac12["V_BZNO"].astype(str).str.strip()
        ac12["BAS_YM"] = ac12["BAS_YM"].astype(str).str.replace(r"\.0$", "", regex=True).str.strip()
        ac12["BAS_YEAR"] = ac12["BAS_YM"].str[:4]

        krw_cols = [c for c in ac12.columns if "KRW" in c or c == "EXT_OTHER_KRW_AM"]
        fc_cols  = [c for c in ac12.columns if "FC_AM" in c]

        ac12_sorted = ac12.sort_values("BAS_YM")
        last_ac12 = (ac12_sorted.drop_duplicates("V_BZNO", keep="last")
                                .set_index("V_BZNO"))

        agg_parts = {}

        # 최신 연도 KRW 값
        for c in krw_cols:
            if c in last_ac12.columns:
                agg_parts[f"AC12_{c}_LATEST"] = last_ac12[c]

        # 전체 평균 KRW
        mean_ac12 = ac12.groupby("V_BZNO")[krw_cols].mean()
        for c in krw_cols:
            agg_parts[f"AC12_{c}_AVG"] = mean_ac12[c]

        # 외화 거래 통화 수 (FC_AM > 0인 통화 수)
        def _fc_cnt(g: pd.DataFrame) -> int:
            cnt = 0
            for fc in fc_cols:
                if fc in g.columns:
                    if pd.to_numeric(g[fc], errors="coerce").max() > 0:
                        cnt += 1
            return cnt

        fc_cnt = ac12.groupby("V_BZNO").apply(_fc_cnt, include_groups=False).rename("AC12_FC_CURRENCY_CNT")
        agg_parts["AC12_FC_CURRENCY_CNT"] = fc_cnt

        # 미국 비중 (최신)
        if "US_KRW_AM" in last_ac12.columns and "TOTAL_KRW_AM" in last_ac12.columns:
            denom = last_ac12["TOTAL_KRW_AM"].replace(0, np.nan)
            agg_parts["AC12_US_RATIO_LATEST"] = last_ac12["US_KRW_AM"] / denom

        ac12_agg = pd.DataFrame(agg_parts).reset_index()
        ac12_agg = ac12_agg.rename(columns={"index": "V_BZNO"})
        if "V_BZNO" not in ac12_agg.columns and ac12_agg.index.name == "V_BZNO":
            ac12_agg = ac12_agg.reset_index()

        sheet = sheet.merge(ac12_agg, on="V_BZNO", how="left")
        log.info("  AC12 집계 완료 - 추가 컬럼: %d개",
                 len([c for c in sheet.columns if c.startswith("AC12_")]))
        return sheet

    # ================================================================
    # 9. AA17 생산판매 (분기 → 연도 집계)
    # ================================================================

    def _attach_aa17(self, sheet: pd.DataFrame) -> pd.DataFrame:
        if "aa17" not in self.frames:
            return sheet
        aa17 = self.frames["aa17"].copy()
        aa17["V_BZNO"] = aa17["V_BZNO"].astype(str).str.strip()

        # BAS_QQ → 연도 추출 (2021Q1 → 2021)
        aa17["BAS_YEAR"] = aa17["BAS_QQ"].str[:4]
        aa17["BAS_Q"] = aa17["BAS_QQ"].str[-1].astype(int)

        # 연도별 합계
        annual = aa17.groupby(["V_BZNO", "BAS_YEAR"])[["LA_XPO_AM", "DME_AM", "TOT_SEL_AM"]].sum()
        years_avail = sorted(annual.index.get_level_values("BAS_YEAR").unique())

        # 연도별 Wide (총판매 + 수출비율)
        result_rows = []
        for yr in years_avail:
            sub = annual.xs(yr, level="BAS_YEAR") if yr in annual.index.get_level_values("BAS_YEAR") else pd.DataFrame()
            if sub.empty:
                continue
            sub = sub.copy()
            sub.columns = [f"AA17_{c}_{yr}" for c in sub.columns]
            denom = sub.get(f"AA17_TOT_SEL_AM_{yr}", pd.Series()).replace(0, np.nan)
            sub[f"AA17_XPO_RATIO_{yr}"] = sub.get(f"AA17_LA_XPO_AM_{yr}", pd.Series()) / denom
            result_rows.append(sub)

        if result_rows:
            aa17_wide = pd.concat(result_rows, axis=1).reset_index()
            aa17_wide = aa17_wide.rename(columns={"index": "V_BZNO"})
            if "V_BZNO" not in aa17_wide.columns:
                aa17_wide = aa17_wide.reset_index().rename(columns={"index": "V_BZNO"})
        else:
            aa17_wide = pd.DataFrame({"V_BZNO": []})

        # 요약
        avail_q = aa17.groupby("V_BZNO")["BAS_QQ"].nunique().rename("AA17_AVAIL_QUARTERS")

        # 최근 YoY 성장률 (총판매)
        annual_sorted = annual.reset_index().sort_values(["V_BZNO", "BAS_YEAR"])
        def _yoy_sel(g: pd.DataFrame) -> float:
            if len(g) < 2:
                return np.nan
            last, prev = g["TOT_SEL_AM"].iloc[-1], g["TOT_SEL_AM"].iloc[-2]
            return (last - prev) / abs(prev) * 100 if prev != 0 else np.nan
        yoy_sel = (annual_sorted.groupby("V_BZNO")
                   .apply(_yoy_sel, include_groups=False)
                   .rename("AA17_SEL_YOY"))

        aa17_agg = aa17_wide.merge(avail_q.reset_index(), on="V_BZNO", how="outer")
        aa17_agg = aa17_agg.merge(yoy_sel.reset_index(), on="V_BZNO", how="outer")
        sheet = sheet.merge(aa17_agg, on="V_BZNO", how="left")
        log.info("  AA17 집계 완료 - 추가 컬럼: %d개",
                 len([c for c in sheet.columns if c.startswith("AA17_")]))
        return sheet

    # ================================================================
    # 10. AA10 종업원수
    # ================================================================

    def _attach_aa10(self, sheet: pd.DataFrame) -> pd.DataFrame:
        if "aa10" not in self.frames:
            return sheet
        aa10 = self.frames["aa10"].copy()
        aa10["V_BZNO"] = aa10["V_BZNO"].astype(str).str.strip()
        aa10 = aa10.dropna(subset=["BAS_DT"])
        aa10_sorted = aa10.sort_values("BAS_DT")

        def _aa10_stats(g: pd.DataFrame) -> pd.Series:
            g = g.sort_values("BAS_DT")
            pers = g["PERS_CNT"].dropna()
            if pers.empty:
                return pd.Series({"AA10_PERS_LATEST": np.nan, "AA10_PERS_EARLIEST": np.nan,
                                   "AA10_PERS_CHANGE_RATE": np.nan, "AA10_MEASURE_CNT": 0,
                                   "AA10_PERS_LAST_DATE": np.nan})
            first_v, last_v = pers.iloc[0], pers.iloc[-1]
            chg_rate = (last_v - first_v) / abs(first_v) * 100 if first_v != 0 else np.nan
            return pd.Series({
                "AA10_PERS_LATEST":      last_v,
                "AA10_PERS_EARLIEST":    first_v,
                "AA10_PERS_CHANGE_RATE": chg_rate,
                "AA10_MEASURE_CNT":      len(g),
                "AA10_PERS_LAST_DATE":   g["BAS_DT"].max().strftime("%Y%m%d"),
            })

        aa10_stats = aa10_sorted.groupby("V_BZNO").apply(_aa10_stats, include_groups=False).reset_index()
        sheet = sheet.merge(aa10_stats, on="V_BZNO", how="left")
        log.info("  AA10 집계 완료 - 추가 컬럼: %d개",
                 len([c for c in sheet.columns if c.startswith("AA10_")]))
        return sheet

    # ================================================================
    # 11. CRIF 신용불량 이력
    # ================================================================

    def _attach_crif(self, sheet: pd.DataFrame) -> pd.DataFrame:
        if "crif" not in self.frames:
            return sheet
        crif = self.frames["crif"].copy()
        crif["V_BZNO"] = crif["V_BZNO"].astype(str).str.strip()

        for c in ["SUM(CRDBD_RSN_AM)", "SUM(CRDBD_OVD_AM)"]:
            if c in crif.columns:
                crif[c] = pd.to_numeric(crif[c], errors="coerce")

        def _crif_stats(g: pd.DataFrame) -> pd.Series:
            return pd.Series({
                "CRIF_HAS_HISTORY_YN":   1,
                "CRIF_RECORD_CNT":       len(g),
                "CRIF_LATEST_OCU_YY":    (g["CRDBD_OCU_YY"].max()
                                          if "CRDBD_OCU_YY" in g.columns else np.nan),
                "CRIF_TOTAL_RSNC_AMT":   (g["SUM(CRDBD_RSN_AM)"].sum()
                                          if "SUM(CRDBD_RSN_AM)" in g.columns else 0),
                "CRIF_TOTAL_OVD_AMT":    (g["SUM(CRDBD_OVD_AM)"].sum()
                                          if "SUM(CRDBD_OVD_AM)" in g.columns else 0),
                "CRIF_LATEST_RSNC":      (g["CRDBD_RSNC"].iloc[-1]
                                          if "CRDBD_RSNC" in g.columns else np.nan),
            })

        crif_stats = crif.groupby("V_BZNO").apply(_crif_stats, include_groups=False).reset_index()
        sheet = sheet.merge(crif_stats, on="V_BZNO", how="left")
        sheet["CRIF_HAS_HISTORY_YN"] = sheet["CRIF_HAS_HISTORY_YN"].fillna(0).astype(int)
        sheet["CRIF_RECORD_CNT"] = sheet["CRIF_RECORD_CNT"].fillna(0).astype(int)
        log.info("  CRIF 집계 완료 - 추가 컬럼: %d개",
                 len([c for c in sheet.columns if c.startswith("CRIF_")]))
        return sheet

    # ================================================================
    # 컬럼 정렬 & 저장
    # ================================================================

    def _reorder_columns(self, sheet: pd.DataFrame) -> pd.DataFrame:
        """Target 및 기업 기본정보를 앞으로 이동."""
        priority = [
            # 키
            "V_BZNO", "CONM",
            # Target
            "IS_DEFAULT", "DEFAULT_CNT", "DEFAULT_YM", "DEFAULT_YEAR", "DSH_RSN_DSC",
            "IS_RECOVERED", "NMLZ_DT_STR",
            # 기업 기본
            "ETB_DT", "ETB_YEAR", "COMPANY_AGE",
            "COPR_OPNP_C", "BZSCAL_C", "STD_INDS_CFC", "EMPCN",
        ]
        front = [c for c in priority if c in sheet.columns]
        rest  = [c for c in sheet.columns if c not in front]

        # 그룹별 정렬: OBV → JEMU → GRD → CG01 → C302 → AC12 → AA17 → AA10 → CRIF
        def _grp(c: str) -> int:
            for i, pfx in enumerate(["OBV_","JEMU_","GRD_","CG01_","C302_","AC12_","AA17_","AA10_","CRIF_"]):
                if c.startswith(pfx):
                    return i
            return 99
        rest_sorted = sorted(rest, key=lambda c: (_grp(c), c))
        return sheet[front + rest_sorted]

    def _save(self, sheet: pd.DataFrame) -> None:
        out = self.output_dir / "nh_borrower_sheet.csv"
        sheet.to_csv(out, index=False, encoding="utf-8-sig")

        # 엑셀로 여는 사용자를 위한 한글 헤더 병행본. 기본값 off (30MB 중복 산출).
        # 컬럼명 규칙: JEMU_<코드>_<접미사> -> JEMU_<한글라벨>_<접미사>
        if not self.write_kr:
            return

        import re as _re

        def _kr(col: str) -> str:
            m = _re.fullmatch(r"JEMU_(\d{6})_(.+)", col)
            if m and m.group(1) in JEMU_COL_MAP:
                return f"JEMU_{JEMU_COL_MAP[m.group(1)]}_{m.group(2)}"
            return col

        kr_path = self.output_dir / "nh_borrower_sheet_kr.csv"
        sheet.rename(columns=_kr).to_csv(kr_path, index=False, encoding="utf-8-sig")
        log.info("  한글 헤더 병행본: %s", kr_path.name)
        log.info("  저장: %s  (%d rows x %d cols, %.1f MB)",
                 out, len(sheet), len(sheet.columns),
                 out.stat().st_size / 1024 / 1024)

        # 결측률 요약 저장
        miss = (sheet.isnull().mean() * 100).sort_values(ascending=False)
        miss_df = miss.reset_index()
        miss_df.columns = ["컬럼명", "결측률(%)"]
        miss_df["결측률(%)"] = miss_df["결측률(%)"].round(2)
        miss_df.to_csv(self.output_dir / "nh_borrower_sheet_missing.csv",
                       index=False, encoding="utf-8-sig")
        log.info("  결측률 요약: nh_borrower_sheet_missing.csv")
