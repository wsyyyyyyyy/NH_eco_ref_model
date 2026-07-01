"""
Credit Scoring Data Processing Pipeline
========================================
11개 원천 데이터 + 1개 도메인 마스터 → 모델링용 클린 데이터셋 변환.

사용법:
    from nh_data_processing import CreditDataPipeline
    pipe = CreditDataPipeline(data_dir='input', output_dir='nh_data_processing/output')
    results = pipe.run()
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Dict, Optional

import numpy as np
import pandas as pd

LOGGER = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────
# CRI 등급 서열화 인코딩 매핑 (Ordinal Encoding)
# ──────────────────────────────────────────────────────────────────
CRI_ORDINAL_MAP: Dict[str, int] = {
    "AAA":  1,
    "AA+":  2, "AA0":  3, "AA-":  4,
    "A+":   5, "A0":   6, "A-":   7,
    "BBB+": 8, "BBB0": 9, "BBB-": 10,
    "BB+": 11, "BB0":  12, "BB-": 13,
    "B+":  14, "B0":   15, "B-":  16,
    "CCC+": 17, "CCC0": 18, "CCC-": 19,  # 세부 등급 반영
    "CC+": 20,                             # 세부 등급 반영
    "C+":  21,                             # 세부 등급 반영
    "D":   22,                             # 최하위 등급
    # 특이값 → 별도 구간
    "Missing": -1, "NR": -2, "R": -3,
}


class CreditDataPipeline:
    """신용평가 모형용 데이터 전처리 파이프라인."""

    # 파일명 키워드 → 내부 식별자 매핑
    FILE_KEYS = {
        "UPCHE_TOT": "upche",
        "GRD_HIS": "grd_his",
        "JEMU": "jemu",
        "BUDO_CUST": "budo",
        "VH_CRIF": "crif",
        "VH_OBV_DTL": "obv",
        "CG01": "cg01",
        "C302": "c302",
        "AC12": "ac12",
        "AA17": "aa17",
        "AA10": "aa10",
    }

    def __init__(
        self,
        data_dir: str | Path = "./input",
        output_dir: str | Path = "./nh_data_processing/output",
    ) -> None:
        self.data_dir = Path(data_dir)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.frames: Dict[str, pd.DataFrame] = {}

    # ================================================================
    # Public Entry Point
    # ================================================================

    def run(self) -> Dict[str, pd.DataFrame]:
        """전체 파이프라인 실행."""
        LOGGER.info("=" * 60)
        LOGGER.info("Phase 1: 데이터 로드 및 소수점/패딩 전처리")
        LOGGER.info("=" * 60)
        self._load_all_files()
        # self._drop_upche_empcn()  # USER REQUEST: 종업원수(EMPCN) 컬럼 복원
        self._rename_ac12_columns()
        self._fix_decimal_distortion()
        self._fix_code_padding()
        self._fix_date_zero_values()
        self._fix_cg01_duplicates()

        LOGGER.info("=" * 60)
        LOGGER.info("Phase 2: Wide → Long 구조 변환")
        LOGGER.info("=" * 60)
        self._melt_grd_his()
        self._melt_cg01()
        self._melt_c302()
        self._melt_aa17()
        self._melt_aa10()

        LOGGER.info("=" * 60)
        LOGGER.info("Phase 3: 결측치 처리 및 파생변수 생성")
        LOGGER.info("=" * 60)
        self._fill_external_grade_missing()
        self._process_ac12()
        self._process_aa17_flags()

        LOGGER.info("=" * 60)
        LOGGER.info("저장 중...")
        LOGGER.info("=" * 60)
        self._save_all()

        LOGGER.info("[DONE] 전처리 완료 → %s", self.output_dir)
        return self.frames

    # ================================================================
    # Phase 1: 로드 및 기초 전처리
    # ================================================================

    def _load_txt(self, filepath: Path) -> pd.DataFrame:
        """파이프 구분자 TXT 파일 로드. 0번째 행(논리명) 스킵."""
        for enc in ("utf-8", "cp949"):
            try:
                df = pd.read_csv(
                    filepath, sep="|", encoding=enc, dtype=str,
                    skipinitialspace=True,
                )
                break
            except (UnicodeDecodeError, UnicodeError):
                continue
        else:
            raise ValueError(f"인코딩 로드 실패: {filepath}")

        # 0번째 행 = 한글 논리명 → 제거
        df = df.iloc[1:].reset_index(drop=True)
        # Unnamed 트레일링 컬럼 제거
        df = df.loc[:, ~df.columns.str.startswith("Unnamed")]
        # 완전 빈 행 제거
        df = df.dropna(how="all").reset_index(drop=True)
        return df

    def _load_all_files(self) -> None:
        """input 디렉토리 내 모든 가상사업자 TXT 파일 로드."""
        txt_files = sorted(self.data_dir.glob("가상사업자*.txt"))
        for fp in txt_files:
            for keyword, key in self.FILE_KEYS.items():
                if keyword in fp.name:
                    df = self._load_txt(fp)
                    self.frames[key] = df
                    LOGGER.info("Loaded %-8s: %s (%d rows × %d cols)",
                                key, fp.name, len(df), len(df.columns))
                    break

        # 도메인 마스터
        domain_path = self.data_dir / "도메인값.txt"
        if domain_path.exists():
            self.frames["domain"] = self._load_txt(domain_path)
            LOGGER.info("Loaded domain master (%d rows)", len(self.frames["domain"]))

    # ── Phase 1 추가: UPCHE EMPCN 삭제 ─────────────────────────────

    # def _drop_upche_empcn(self) -> None:
    #     """기업정보(UPCHE)에서 EMPCN(종업원수) 컬럼 삭제."""
    #     if "upche" in self.frames:
    #         df = self.frames["upche"]
    #         if "EMPCN" in df.columns:
    #             df = df.drop(columns=["EMPCN"])
    #             self.frames["upche"] = df
    #             LOGGER.info("Dropped UPCHE EMPCN column → %d cols remain", len(df.columns))

    # ── Phase 1 추가: AC12 컬럼명 변경 ─────────────────────────────

    AC12_RENAME_MAP = {
        "FC_AM1":          "US_FC_AM",
        "LA_INSP_KRW_AM1": "US_KRW_AM",
        "FC_AM2":          "JP_FC_AM",
        "LA_INSP_KRW_AM2": "JP_KRW_AM",
        "FC_AM3":          "CN_FC_AM",
        "LA_INSP_KRW_AM3": "CN_KRW_AM",
        "FC_AM4":          "EU_FC_AM",
        "LA_INSP_KRW_AM4": "EU_KRW_AM",
        "LA_INSP_KRW_AM5": "TOTAL_KRW_AM",
    }

    def _rename_ac12_columns(self) -> None:
        """외화부채(AC12) 컬럼명을 통화별 의미 있는 이름으로 변경."""
        if "ac12" in self.frames:
            df = self.frames["ac12"]
            df = df.rename(columns=self.AC12_RENAME_MAP)
            self.frames["ac12"] = df
            LOGGER.info("Renamed AC12 columns → %s", list(df.columns))

    # ── Phase 1-2: 소수점 왜곡 정형화 ──────────────────────────────

    def _fix_decimal_distortion(self) -> None:
        """JEMU, OBV 파일의 .0 접미사 제거 + zfill 패딩."""
        # JEMU: AUD_OPI_DSC(2자리), FNA_CLS_YM(6자리)
        if "jemu" in self.frames:
            df = self.frames["jemu"]
            for col, width in [("AUD_OPI_DSC", 2), ("FNA_CLS_YM", 6)]:
                if col in df.columns:
                    df[col] = (
                        df[col].astype(str)
                        .str.replace(r"\.0$", "", regex=True)
                        .str.strip()
                        .str.zfill(width)
                    )
            LOGGER.info("Fixed decimal distortion: JEMU (AUD_OPI_DSC, FNA_CLS_YM)")

        # OBV: BAS_YM(6자리)
        if "obv" in self.frames:
            df = self.frames["obv"]
            if "BAS_YM" in df.columns:
                df["BAS_YM"] = (
                    df["BAS_YM"].astype(str)
                    .str.replace(r"\.0$", "", regex=True)
                    .str.strip()
                    .str.zfill(6)
                )
            LOGGER.info("Fixed decimal distortion: OBV (BAS_YM)")

    # ── Phase 1-3: 코드성 변수 패딩 ────────────────────────────────

    def _fix_code_padding(self) -> None:
        """GRD_HIS, CRIF 코드 변수 앞자리 0 패딩."""
        # GRD_HIS: LS_NICS_GRDC 계열 → 2자리 (멜트 전이므로 연도 접미사 포함)
        if "grd_his" in self.frames:
            df = self.frames["grd_his"]
            nics_cols = [c for c in df.columns if c.startswith("LS_NICS_GRDC")]
            for col in nics_cols:
                df[col] = df[col].astype(str).str.strip().str.zfill(2)
            LOGGER.info("Padded GRD_HIS NICS columns (%d cols)", len(nics_cols))

        # CRIF: CRDBD_RSNC(4자리), MAX(CRDBD_RLS_RSNC)(2자리)
        if "crif" in self.frames:
            df = self.frames["crif"]
            if "CRDBD_RSNC" in df.columns:
                df["CRDBD_RSNC"] = df["CRDBD_RSNC"].astype(str).str.strip().str.zfill(4)
            rls_col = "MAX(CRDBD_RLS_RSNC)"
            if rls_col in df.columns:
                df[rls_col] = df[rls_col].astype(str).str.strip().str.zfill(2)
            LOGGER.info("Padded CRIF code columns")

    # ── Phase 1-4: 날짜 '0'값 → NaT ───────────────────────────────

    def _fix_date_zero_values(self) -> None:
        """BUDO, CRIF 날짜 컬럼의 '0'/'0.0' → NaT 변환."""
        zero_pattern = re.compile(r"^0(\.0)?$")

        # BUDO: NMLZ_DT
        if "budo" in self.frames:
            df = self.frames["budo"]
            if "NMLZ_DT" in df.columns:
                mask = df["NMLZ_DT"].astype(str).str.match(zero_pattern)
                df.loc[mask, "NMLZ_DT"] = np.nan
                df["NMLZ_DT"] = pd.to_datetime(df["NMLZ_DT"], errors="coerce")
            LOGGER.info("Fixed BUDO NMLZ_DT zero values → NaT")

        # CRIF: MAX(CRDBD_RLS_OCU_DT)
        if "crif" in self.frames:
            df = self.frames["crif"]
            col = "MAX(CRDBD_RLS_OCU_DT)"
            if col in df.columns:
                mask = df[col].astype(str).str.match(zero_pattern)
                df.loc[mask, col] = np.nan
                df[col] = pd.to_datetime(df[col], errors="coerce")
            LOGGER.info("Fixed CRIF release date zero values → NaT")

    # ── Phase 1-5: CG01 중복 제거 ──────────────────────────────────

    def _fix_cg01_duplicates(self) -> None:
        """CG01 V_BZNO 기준 중복 제거 (first 유지)."""
        if "cg01" in self.frames:
            before = len(self.frames["cg01"])
            self.frames["cg01"] = (
                self.frames["cg01"]
                .drop_duplicates(subset=["V_BZNO"], keep="first")
                .reset_index(drop=True)
            )
            after = len(self.frames["cg01"])
            LOGGER.info("CG01 dedup: %d → %d rows (-%d)", before, after, before - after)

    # ================================================================
    # Phase 2: Wide → Long 구조 변환
    # ================================================================

    def _melt_grd_his(self) -> None:
        """당행등급이력: 연도별 [모형구분, NICS등급] → Long."""
        if "grd_his" not in self.frames:
            return
        df = self.frames["grd_his"]

        years = sorted({c.split("_")[-1] for c in df.columns
                        if c.startswith("CRDEVL_PTTP_DSC_")})
        rows = []
        for yr in years:
            pttp_col = f"CRDEVL_PTTP_DSC_{yr}"
            nics_col = f"LS_NICS_GRDC_{yr}"
            if pttp_col not in df.columns or nics_col not in df.columns:
                continue
            chunk = df[["V_BZNO", pttp_col, nics_col]].copy()
            chunk.columns = ["V_BZNO", "CRDEVL_PTTP_DSC", "LS_NICS_GRDC"]
            chunk["BASE_YEAR"] = yr
            rows.append(chunk)

        result = pd.concat(rows, ignore_index=True)
        result = result[["V_BZNO", "BASE_YEAR", "CRDEVL_PTTP_DSC", "LS_NICS_GRDC"]]
        # NaN 행 제거 (모형구분, 등급 모두 비어있는 경우)
        result = result.dropna(subset=["CRDEVL_PTTP_DSC", "LS_NICS_GRDC"], how="all")
        self.frames["grd_his"] = result.reset_index(drop=True)
        LOGGER.info("Melted GRD_HIS → %d rows, schema: %s",
                     len(result), list(result.columns))

    def _melt_cg01(self) -> None:
        """나이스신용평점: 연도별 KIS_LS_FNA_MKS → Long."""
        if "cg01" not in self.frames:
            return
        df = self.frames["cg01"]

        score_cols = [c for c in df.columns if c.startswith("KIS_LS_FNA_MKS_")]
        melted = df.melt(
            id_vars=["V_BZNO"],
            value_vars=score_cols,
            var_name="_year_col",
            value_name="KIS_LS_FNA_MKS",
        )
        melted["BASE_YEAR"] = melted["_year_col"].str.extract(r"(\d{4})$")
        melted = melted[["V_BZNO", "BASE_YEAR", "KIS_LS_FNA_MKS"]]
        self.frames["cg01"] = melted.reset_index(drop=True)
        LOGGER.info("Melted CG01 → %d rows", len(melted))

    def _melt_c302(self) -> None:
        """나이스CRI등급: 7개 세트 [시작일, 종료일, CRI등급] → Long."""
        if "c302" not in self.frames:
            return
        df = self.frames["c302"]

        rows = []
        for i in range(1, 8):
            st_col = f"{i}_ST_DT"
            ed_col = f"{i}_ED_DT"
            grd_col = f"{i}_CRI_GRDNM"
            if not all(c in df.columns for c in [st_col, ed_col, grd_col]):
                continue
            chunk = df[["V_BZNO", st_col, ed_col, grd_col]].copy()
            chunk.columns = ["V_BZNO", "ST_DT", "ED_DT", "CRI_GRD"]
            # 세트 전체가 비어있는 행 제거
            chunk = chunk.dropna(subset=["ST_DT", "ED_DT", "CRI_GRD"], how="all")
            rows.append(chunk)

        result = pd.concat(rows, ignore_index=True)
        self.frames["c302"] = result.reset_index(drop=True)
        LOGGER.info("Melted C302 → %d rows, schema: %s",
                     len(result), list(result.columns))

    def _melt_aa17(self) -> None:
        """생산판매: 분기별 [수출, 내수, 총판매] 세트 → Long."""
        if "aa17" not in self.frames:
            return
        df = self.frames["aa17"]

        # 분기 식별: LA_XPO_AM_YYYY_Q 패턴
        quarters = sorted({
            "_".join(c.split("_")[-2:])
            for c in df.columns if c.startswith("LA_XPO_AM_")
        })

        rows = []
        for qq in quarters:
            xpo_col = f"LA_XPO_AM_{qq}"
            dme_col = f"DME_AM_{qq}"
            tot_col = f"TOT_SEL_AM_{qq}"
            if not all(c in df.columns for c in [xpo_col, dme_col, tot_col]):
                continue
            chunk = df[["V_BZNO", xpo_col, dme_col, tot_col]].copy()
            chunk.columns = ["V_BZNO", "LA_XPO_AM", "DME_AM", "TOT_SEL_AM"]

            # 숫자형 변환
            for c in ["LA_XPO_AM", "DME_AM", "TOT_SEL_AM"]:
                chunk[c] = pd.to_numeric(chunk[c], errors="coerce")

            # 3개 모두 NaN인 행 제거
            chunk = chunk.dropna(subset=["LA_XPO_AM", "DME_AM", "TOT_SEL_AM"], how="all")

            # BAS_QQ 생성: "2021_1" → "2021Q1"
            year, q = qq.split("_")
            chunk["BAS_QQ"] = f"{year}Q{q}"
            rows.append(chunk)

        result = pd.concat(rows, ignore_index=True)
        result = result[["V_BZNO", "BAS_QQ", "LA_XPO_AM", "DME_AM", "TOT_SEL_AM"]]
        self.frames["aa17"] = result.reset_index(drop=True)
        LOGGER.info("Melted AA17 → %d rows", len(result))

    def _melt_aa10(self) -> None:
        """종업원수: 11개 슬롯 [일자, 인원] 페어 → Long."""
        if "aa10" not in self.frames:
            return
        df = self.frames["aa10"]

        rows = []
        for i in range(1, 12):
            dt_col = f"BASDT{i}"
            ps_col = f"PERS{i}"
            if dt_col not in df.columns or ps_col not in df.columns:
                continue
            chunk = df[["V_BZNO", dt_col, ps_col]].copy()
            chunk.columns = ["V_BZNO", "BAS_DT", "PERS_CNT"]
            # 일자·인원 모두 존재하는 건만 유지
            chunk = chunk.dropna(subset=["BAS_DT", "PERS_CNT"], how="any")
            # 'nan' 문자열 제거
            chunk = chunk[
                (chunk["BAS_DT"].astype(str) != "nan") &
                (chunk["PERS_CNT"].astype(str) != "nan")
            ]
            rows.append(chunk)

        result = pd.concat(rows, ignore_index=True)
        result["BAS_DT"] = pd.to_datetime(result["BAS_DT"], format="%Y%m%d", errors="coerce")
        result["PERS_CNT"] = pd.to_numeric(result["PERS_CNT"], errors="coerce")
        self.frames["aa10"] = result.reset_index(drop=True)
        LOGGER.info("Melted AA10 → %d rows", len(result))

    # ================================================================
    # Phase 3: 결측치 처리 및 파생변수 생성
    # ================================================================

    def _fill_external_grade_missing(self) -> None:
        """CG01, C302 외부 등급 결측치 → 'Missing' / -1 처리."""
        # CG01: 수치형 평점 → -1
        if "cg01" in self.frames:
            df = self.frames["cg01"]
            df["KIS_LS_FNA_MKS"] = pd.to_numeric(df["KIS_LS_FNA_MKS"], errors="coerce")
            df["KIS_LS_FNA_MKS"] = df["KIS_LS_FNA_MKS"].fillna(-1).astype(int)
            LOGGER.info("CG01: NaN → -1 (Missing category)")

        # C302: 문자열 등급
        if "c302" in self.frames:
            df = self.frames["c302"]
            # NR, R → 그대로 유지 (별도 구간), NaN → 'Missing'
            df["CRI_GRD"] = df["CRI_GRD"].fillna("Missing")
            # 서열화 인코딩 컬럼 추가
            df["CRI_GRD_ORD"] = df["CRI_GRD"].map(CRI_ORDINAL_MAP).fillna(-1).astype(int)
            LOGGER.info("C302: NaN → 'Missing', NR/R 유지, 서열 인코딩 추가")

    def _process_ac12(self) -> None:
        """외화부채: NaN → 0, 기타 외화부채 파생변수 생성."""
        if "ac12" not in self.frames:
            return
        df = self.frames["ac12"]

        # 숫자형 변환 (V_BZNO, BAS_YM 제외)
        num_cols = [c for c in df.columns if c not in ("V_BZNO", "BAS_YM")]
        for c in num_cols:
            df[c] = pd.to_numeric(df[c], errors="coerce")

        # 개별 국가 컬럼 NaN → 0 (합계 컬럼 제외)
        fill_cols = [c for c in num_cols if c != "TOTAL_KRW_AM"]
        df[fill_cols] = df[fill_cols].fillna(0)

        # 4개국 원화 합산: 미국 + 일본 + 중국 + 유럽
        krw_4_cols = ["US_KRW_AM", "JP_KRW_AM", "CN_KRW_AM", "EU_KRW_AM"]
        existing_krw = [c for c in krw_4_cols if c in df.columns]
        df["EXT_OTHER_KRW_AM"] = (
            df["TOTAL_KRW_AM"].fillna(0) - df[existing_krw].sum(axis=1)
        ).clip(lower=0)

        self.frames["ac12"] = df
        LOGGER.info("AC12: NaN → 0, 기타통화 외화부채(EXT_OTHER_KRW_AM) 파생변수 생성")

    def _process_aa17_flags(self) -> None:
        """생산판매: 금액 결측 → 0, 실적보유여부 플래그 생성."""
        if "aa17" not in self.frames:
            return
        df = self.frames["aa17"]

        amt_cols = ["LA_XPO_AM", "DME_AM", "TOT_SEL_AM"]
        for c in amt_cols:
            df[c] = pd.to_numeric(df[c], errors="coerce")

        # 플래그: 원천에 데이터가 있었으면 1, NaN이었으면 0
        has_any = df[amt_cols].notna().any(axis=1).astype(int)
        df["EXT_PROD_RECORD_YN"] = has_any

        # NaN → 0
        df[amt_cols] = df[amt_cols].fillna(0)

        self.frames["aa17"] = df
        LOGGER.info("AA17: NaN → 0, EXT_PROD_RECORD_YN 플래그 생성")

    # ================================================================
    # 저장
    # ================================================================

    def _save_all(self) -> None:
        """모든 처리된 DataFrame을 CSV로 저장."""
        name_map = {
            "upche":   "01_기업정보_UPCHE_TOT",
            "grd_his": "02_당행등급이력_GRD_HIS",
            "jemu":    "03_재무데이터_JEMU",
            "budo":    "04_당행부도정보_BUDO_CUST",
            "crif":    "05_신용불량_VH_CRIF",
            "obv":     "06_관찰세부등급_VH_OBV_DTL",
            "cg01":    "07_나이스신용평점_CG01",
            "c302":    "08_나이스CRI등급_C302",
            "ac12":    "09_외화부채_AC12",
            "aa17":    "10_생산판매_AA17",
            "aa10":    "11_종업원수_AA10",
            "domain":  "99_도메인마스터",
        }
        for key, df in self.frames.items():
            fname = name_map.get(key, key)
            out_path = self.output_dir / f"{fname}.csv"
            df.to_csv(out_path, index=False, encoding="utf-8-sig")
            LOGGER.info("Saved: %s (%d rows × %d cols)", out_path.name, len(df), len(df.columns))
