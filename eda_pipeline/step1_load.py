"""
======================================================================
Step 1 — Raw 데이터 로더
======================================================================
input/ 폴더의 파이프(|) 구분 TXT 파일 11개를 읽어 Dict[str, pd.DataFrame]으로
반환합니다. DuckDB 없이 순수 Pandas만 사용합니다.

사용법:
    from eda_pipeline.step1_load import RawLoader
    frames = RawLoader(data_dir="input").load_all()
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Dict

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

# ── 파일명 키워드 → 내부 식별자 ────────────────────────────────────
FILE_KEYS: Dict[str, str] = {
    "UPCHE_TOT":  "upche",    # 기업정보 (마스터)
    "GRD_HIS":    "grd_his",  # 당행 등급 이력 (연도별 Wide)
    "JEMU":       "jemu",     # 재무데이터 (연도별 Long)
    "BUDO_CUST":  "budo",     # 당행 부도정보 → Target
    "VH_CRIF":    "crif",     # CB 신용불량 이력
    "VH_OBV_DTL": "obv",      # 관찰세부등급 (월별 Long)
    "CG01":       "cg01",     # 나이스 신용평점 (연도별 Wide)
    "C302":       "c302",     # 나이스 CRI 등급 (유효기간 Wide)
    "AC12":       "ac12",     # 외화부채 (연도별 Long)
    "AA17":       "aa17",     # 생산·판매 (분기별 Wide)
    "AA10":       "aa10",     # 종업원수 (변동 시점 Wide)
}

# ── CRI 서열 인코딩 ─────────────────────────────────────────────────
CRI_ORDINAL: Dict[str, int] = {
    "AAA": 1,
    "AA+": 2, "AA0": 3, "AA-": 4,
    "A+": 5,  "A0": 6,  "A-": 7,
    "BBB+": 8, "BBB0": 9, "BBB-": 10,
    "BB+": 11, "BB0": 12, "BB-": 13,
    "B+": 14,  "B0": 15,  "B-": 16,
    "CCC+": 17, "CCC0": 18, "CCC-": 19,
    "CC+": 20, "C+": 21,   "D": 22,
    "Missing": -1, "NR": -2, "R": -3,
}

# ── AC12 컬럼명 리네임 맵 ───────────────────────────────────────────
AC12_RENAME: Dict[str, str] = {
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


class RawLoader:
    """
    input/ 디렉토리에서 원천 TXT 파일을 로드하고
    기초 전처리(소수점 정형화, 패딩, 날짜 0→NaT, Wide→Long 변환)까지 수행합니다.
    """

    def __init__(self, data_dir: str | Path = "input") -> None:
        self.data_dir = Path(data_dir)
        self.frames: Dict[str, pd.DataFrame] = {}

    # ================================================================
    # Public
    # ================================================================

    def load_all(self) -> Dict[str, pd.DataFrame]:
        """전체 로드 + 전처리를 실행하고 frames 딕셔너리를 반환합니다."""
        log.info("=" * 60)
        log.info("[LOAD] input/ 원천 파일 로드 시작")
        log.info("=" * 60)

        self._load_txt_files()
        self._preprocess_all()

        log.info("[LOAD] 완료 — 로드된 테이블: %s", list(self.frames.keys()))
        return self.frames

    # ================================================================
    # 내부 — 파일 로드
    # ================================================================

    def _read_txt(self, filepath: Path) -> pd.DataFrame:
        """파이프(|) 구분 TXT 파일을 읽습니다. 0번째 행(한글 논리명)은 제거."""
        for enc in ("utf-8", "cp949"):
            try:
                df = pd.read_csv(
                    filepath,
                    sep="|",
                    encoding=enc,
                    dtype=str,
                    skipinitialspace=True,
                )
                break
            except (UnicodeDecodeError, UnicodeError):
                continue
        else:
            raise ValueError(f"인코딩 로드 실패: {filepath}")

        df = df.iloc[1:].reset_index(drop=True)                   # 한글 논리명 행 제거
        df = df.loc[:, ~df.columns.str.startswith("Unnamed")]     # 트레일링 빈 컬럼 제거
        df = df.dropna(how="all").reset_index(drop=True)          # 완전 공백 행 제거
        return df

    def _load_txt_files(self) -> None:
        txt_files = sorted(self.data_dir.glob("가상사업자*.txt"))
        for fp in txt_files:
            for keyword, key in FILE_KEYS.items():
                if keyword in fp.name:
                    df = self._read_txt(fp)
                    self.frames[key] = df
                    log.info("  Loaded %-8s: %s  (%d rows × %d cols)",
                             key, fp.name, len(df), len(df.columns))
                    break

        # 도메인 마스터
        domain_path = self.data_dir / "도메인값.txt"
        if domain_path.exists():
            self.frames["domain"] = self._read_txt(domain_path)
            log.info("  Loaded domain: %d rows", len(self.frames["domain"]))

    # ================================================================
    # 내부 — 통합 전처리 호출
    # ================================================================

    def _preprocess_all(self) -> None:
        self._fix_decimal_distortion()
        self._fix_code_padding()
        self._fix_date_zero_values()
        self._fix_cg01_duplicates()
        self._rename_ac12_columns()

        # Wide → Long 변환
        self._melt_grd_his()
        self._melt_cg01()
        self._melt_c302()
        self._melt_aa17()
        self._melt_aa10()

        # 결측/파생 처리
        self._process_crif_missing()
        self._fill_external_grade_missing()
        self._process_ac12()
        self._process_jemu()
        self._process_obv()
        self._process_aa17_flags()
        self._process_budo_target()

    # ================================================================
    # 전처리 세부 메서드
    # ================================================================

    def _fix_decimal_distortion(self) -> None:
        """JEMU·OBV의 `.0` 접미사 제거 + zfill."""
        if "jemu" in self.frames:
            df = self.frames["jemu"]
            for col, width in [("AUD_OPI_DSC", 2), ("FNA_CLS_YM", 6)]:
                if col in df.columns:
                    df[col] = (df[col].astype(str)
                               .str.replace(r"\.0$", "", regex=True)
                               .str.strip().str.zfill(width))
        if "obv" in self.frames:
            df = self.frames["obv"]
            if "BAS_YM" in df.columns:
                df["BAS_YM"] = (df["BAS_YM"].astype(str)
                                .str.replace(r"\.0$", "", regex=True)
                                .str.strip().str.zfill(6))

    def _fix_code_padding(self) -> None:
        """GRD_HIS NICS 등급 2자리, CRIF 코드 패딩."""
        if "grd_his" in self.frames:
            df = self.frames["grd_his"]
            for col in [c for c in df.columns if c.startswith("LS_NICS_GRDC")]:
                df[col] = df[col].astype(str).str.strip().str.zfill(2)
        if "crif" in self.frames:
            df = self.frames["crif"]
            if "CRDBD_RSNC" in df.columns:
                df["CRDBD_RSNC"] = df["CRDBD_RSNC"].astype(str).str.strip().str.zfill(4)
            rls = "MAX(CRDBD_RLS_RSNC)"
            if rls in df.columns:
                df[rls] = df[rls].astype(str).str.strip().str.zfill(2)

    def _fix_date_zero_values(self) -> None:
        """날짜 컬럼 '0' / '0.0' → NaT."""
        zero = re.compile(r"^0(\.0)?$")
        if "budo" in self.frames:
            df = self.frames["budo"]
            for col in ("NMLZ_DT", "DSH_DT"):
                if col in df.columns:
                    mask = df[col].astype(str).str.match(zero)
                    df.loc[mask, col] = np.nan
                    df[col] = pd.to_datetime(df[col], errors="coerce")
        if "crif" in self.frames:
            df = self.frames["crif"]
            col = "MAX(CRDBD_RLS_OCU_DT)"
            if col in df.columns:
                mask = df[col].astype(str).str.match(zero)
                df.loc[mask, col] = np.nan
                df[col] = pd.to_datetime(df[col], errors="coerce")

    def _fix_cg01_duplicates(self) -> None:
        if "cg01" in self.frames:
            before = len(self.frames["cg01"])
            self.frames["cg01"] = (self.frames["cg01"]
                                   .drop_duplicates(subset=["V_BZNO"], keep="first")
                                   .reset_index(drop=True))
            after = len(self.frames["cg01"])
            log.info("  CG01 dedup: %d → %d rows (-%d)", before, after, before - after)

    def _rename_ac12_columns(self) -> None:
        if "ac12" in self.frames:
            self.frames["ac12"] = self.frames["ac12"].rename(columns=AC12_RENAME)

    # ── Wide → Long ─────────────────────────────────────────────────

    def _melt_grd_his(self) -> None:
        """당행등급이력: 연도별 [모형구분, NICS등급] → Long."""
        if "grd_his" not in self.frames:
            return
        df = self.frames["grd_his"]
        years = sorted({c.split("_")[-1] for c in df.columns
                        if c.startswith("CRDEVL_PTTP_DSC_")})
        rows = []
        for yr in years:
            pc, nc = f"CRDEVL_PTTP_DSC_{yr}", f"LS_NICS_GRDC_{yr}"
            if pc not in df.columns or nc not in df.columns:
                continue
            chunk = df[["V_BZNO", pc, nc]].copy()
            chunk.columns = ["V_BZNO", "CRDEVL_PTTP_DSC", "LS_NICS_GRDC"]
            chunk["BASE_YEAR"] = yr
            rows.append(chunk)
        result = (pd.concat(rows, ignore_index=True)
                  [["V_BZNO", "BASE_YEAR", "CRDEVL_PTTP_DSC", "LS_NICS_GRDC"]])
        result = result.dropna(subset=["CRDEVL_PTTP_DSC", "LS_NICS_GRDC"], how="all")
        self.frames["grd_his"] = result.reset_index(drop=True)
        log.info("  Melted GRD_HIS → %d rows", len(result))

    def _melt_cg01(self) -> None:
        """나이스신용평점: 연도별 → Long."""
        if "cg01" not in self.frames:
            return
        df = self.frames["cg01"]
        score_cols = [c for c in df.columns if c.startswith("KIS_LS_FNA_MKS_")]
        melted = df.melt(id_vars=["V_BZNO"], value_vars=score_cols,
                         var_name="_yr", value_name="KIS_LS_FNA_MKS")
        melted["BASE_YEAR"] = melted["_yr"].str.extract(r"(\d{4})$")
        self.frames["cg01"] = melted[["V_BZNO", "BASE_YEAR", "KIS_LS_FNA_MKS"]].reset_index(drop=True)
        log.info("  Melted CG01 → %d rows", len(self.frames["cg01"]))

    def _melt_c302(self) -> None:
        """나이스CRI등급: 7세트 → Long."""
        if "c302" not in self.frames:
            return
        df = self.frames["c302"]
        rows = []
        for i in range(1, 8):
            sc, ec, gc = f"{i}_ST_DT", f"{i}_ED_DT", f"{i}_CRI_GRDNM"
            if not all(c in df.columns for c in [sc, ec, gc]):
                continue
            chunk = df[["V_BZNO", sc, ec, gc]].copy()
            chunk.columns = ["V_BZNO", "ST_DT", "ED_DT", "CRI_GRD"]
            chunk = chunk.dropna(subset=["ST_DT", "ED_DT", "CRI_GRD"], how="all")
            rows.append(chunk)
        result = pd.concat(rows, ignore_index=True)
        self.frames["c302"] = result.reset_index(drop=True)
        log.info("  Melted C302 → %d rows", len(result))

    def _melt_aa17(self) -> None:
        """생산판매: 분기별 → Long."""
        if "aa17" not in self.frames:
            return
        df = self.frames["aa17"]
        quarters = sorted({"_".join(c.split("_")[-2:]) for c in df.columns
                           if c.startswith("LA_XPO_AM_")})
        rows = []
        for qq in quarters:
            xc, dc, tc = f"LA_XPO_AM_{qq}", f"DME_AM_{qq}", f"TOT_SEL_AM_{qq}"
            if not all(c in df.columns for c in [xc, dc, tc]):
                continue
            chunk = df[["V_BZNO", xc, dc, tc]].copy()
            chunk.columns = ["V_BZNO", "LA_XPO_AM", "DME_AM", "TOT_SEL_AM"]
            for c in ["LA_XPO_AM", "DME_AM", "TOT_SEL_AM"]:
                chunk[c] = pd.to_numeric(chunk[c], errors="coerce")
            chunk = chunk.dropna(subset=["LA_XPO_AM", "DME_AM", "TOT_SEL_AM"], how="all")
            yr, q = qq.split("_")
            chunk["BAS_QQ"] = f"{yr}Q{q}"
            rows.append(chunk)
        result = pd.concat(rows, ignore_index=True)[["V_BZNO", "BAS_QQ", "LA_XPO_AM", "DME_AM", "TOT_SEL_AM"]]
        self.frames["aa17"] = result.reset_index(drop=True)
        log.info("  Melted AA17 → %d rows", len(result))

    def _melt_aa10(self) -> None:
        """종업원수: 11슬롯 페어 → Long."""
        if "aa10" not in self.frames:
            return
        df = self.frames["aa10"]
        rows = []
        for i in range(1, 12):
            dc, pc = f"BASDT{i}", f"PERS{i}"
            if dc not in df.columns or pc not in df.columns:
                continue
            chunk = df[["V_BZNO", dc, pc]].copy()
            chunk.columns = ["V_BZNO", "BAS_DT", "PERS_CNT"]
            chunk = chunk.dropna(subset=["BAS_DT", "PERS_CNT"], how="any")
            chunk = chunk[(chunk["BAS_DT"].astype(str) != "nan") &
                          (chunk["PERS_CNT"].astype(str) != "nan")]
            rows.append(chunk)
        result = pd.concat(rows, ignore_index=True)
        result["BAS_DT"] = pd.to_datetime(result["BAS_DT"], format="%Y%m%d", errors="coerce")
        result["PERS_CNT"] = pd.to_numeric(result["PERS_CNT"], errors="coerce")
        self.frames["aa10"] = result.reset_index(drop=True)
        log.info("  Melted AA10 → %d rows", len(result))

    # ── 결측·파생 처리 ───────────────────────────────────────────────

    def _process_crif_missing(self) -> None:
        """CRIF: CRDBD_OCU_YY 정형화."""
        if "crif" not in self.frames:
            return
        df = self.frames["crif"]
        if "CRDBD_OCU_YY" in df.columns:
            df["CRDBD_OCU_YY"] = (df["CRDBD_OCU_YY"].astype(str)
                                  .str.replace(r"\.0$", "", regex=True)
                                  .str.strip())

    def _fill_external_grade_missing(self) -> None:
        """CG01 / C302 의 결측을 NaN 으로 유지한다.

        과거에는 CG01 을 -1, C302 서열을 -1/-2/-3 으로 채웠다. 그러나 이 둘은
        순서형 점수·등급이라 -1 이 '정보 없음' 이 아니라 실제 수치로 학습된다.
        평가 이력이 없는 영세기업이 점수 축의 극단값을 갖게 되어 스플릿이 왜곡된다.
        (CG01_KIS_SCORE 는 기존 모델 gain 2위이고 14.81% 가 -1 이었다.)

        STAGE 3 [3-5] 의 유형 3(진짜 결측) 원칙대로 NaN 을 유지하고,
        step5 가 CG01_MISSING_YN / C302_MISSING_YN 플래그를 만든다.
        LightGBM 은 NaN 을 스플릿에서 네이티브로 처리한다.
        """
        if "cg01" in self.frames:
            df = self.frames["cg01"]
            df["KIS_LS_FNA_MKS"] = pd.to_numeric(df["KIS_LS_FNA_MKS"], errors="coerce")
        if "c302" in self.frames:
            df = self.frames["c302"]
            # 등급 문자열은 'Missing' 으로 남긴다 (step2 의 D/NR/R 플래그가 참조한다).
            df["CRI_GRD"] = df["CRI_GRD"].fillna("Missing")
            _ord = df["CRI_GRD"].map(CRI_ORDINAL)
            # Missing(-1) / NR(-2) / R(-3) 은 서열이 아니므로 NaN 으로 둔다.
            df["CRI_GRD_ORD"] = _ord.where(_ord > 0)

    def _process_ac12(self) -> None:
        """외화부채: NaN → 0, 기타통화 파생변수 생성."""
        if "ac12" not in self.frames:
            return
        df = self.frames["ac12"]
        num_cols = [c for c in df.columns if c not in ("V_BZNO", "BAS_YM")]
        for c in num_cols:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        fill_cols = [c for c in num_cols if c != "TOTAL_KRW_AM"]
        df[fill_cols] = df[fill_cols].fillna(0)
        krw4 = [c for c in ["US_KRW_AM", "JP_KRW_AM", "CN_KRW_AM", "EU_KRW_AM"] if c in df.columns]
        df["EXT_OTHER_KRW_AM"] = (df["TOTAL_KRW_AM"].fillna(0) - df[krw4].sum(axis=1)).clip(lower=0)

    def _process_jemu(self) -> None:
        """재무데이터: 수치형 변환 + 결산년도 연도 추출."""
        if "jemu" not in self.frames:
            return
        df = self.frames["jemu"]
        num_cols = [c for c in df.columns if c not in ("V_BZNO", "AUD_OPI_DSC", "FNA_CLS_YM")]
        for c in num_cols:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        # 결산년도(YYYYMM) → 연도(YYYY)
        if "FNA_CLS_YM" in df.columns:
            df["FNA_YEAR"] = df["FNA_CLS_YM"].astype(str).str[:4]

    def _process_obv(self) -> None:
        """관찰세부등급: 수치형 변환."""
        if "obv" not in self.frames:
            return
        df = self.frames["obv"]
        num_cols = [c for c in df.columns
                    if c not in ("V_BZNO", "BAS_YM", "ELYWRN_OBV_GRD_DSC")]
        for c in num_cols:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    def _process_aa17_flags(self) -> None:
        """생산판매: NaN → 0, 실적보유여부 플래그."""
        if "aa17" not in self.frames:
            return
        df = self.frames["aa17"]
        amt_cols = ["LA_XPO_AM", "DME_AM", "TOT_SEL_AM"]
        df["EXT_PROD_RECORD_YN"] = df[amt_cols].notna().any(axis=1).astype(int)
        df[amt_cols] = df[amt_cols].fillna(0)

    def _process_budo_target(self) -> None:
        """
        부도정보: TARGET 컬럼 생성.
        - IS_DEFAULT: 부도 발생 여부 (DSH_DT 존재 = 1)
        - DEFAULT_YM: 부도 발생 월 (YYYYMM 문자열)
        - IS_RECOVERED: 정상화 여부 (NMLZ_YN)
        - RECOVER_DT / RECOVER_YM: 정상화 일자 / 월

        주의: NMLZ_YN 의 실제 값은 '0' / '1' 이다. 'Y' / 'N' 이 아니다.
              과거 'Y' 비교 방식은 정상화 152건을 전부 미정상화로 판정했다.
        """
        if "budo" not in self.frames:
            return
        df = self.frames["budo"]
        df["IS_DEFAULT"] = df["DSH_DT"].notna().astype(int)
        df["DEFAULT_YM"] = df["DSH_DT"].apply(
            lambda d: d.strftime("%Y%m") if pd.notna(d) else None
        )
        if "NMLZ_YN" in df.columns:
            _nz = df["NMLZ_YN"].astype(str).str.strip().str.upper()
            df["IS_RECOVERED"] = _nz.isin(["1", "Y"]).astype(int)
        if "NMLZ_DT" in df.columns:
            df["RECOVER_DT"] = df["NMLZ_DT"]
            df["RECOVER_YM"] = df["RECOVER_DT"].apply(
                lambda d: d.strftime("%Y%m") if pd.notna(d) else None
            )
        log.info("  BUDO Target 생성 — 부도 건수: %d  |  정상화 건수: %d (기업 %d사)",
                 df["IS_DEFAULT"].sum(),
                 int(df.get("IS_RECOVERED", pd.Series(dtype=int)).sum()),
                 df.loc[df.get("IS_RECOVERED", 0) == 1, "V_BZNO"].nunique()
                 if "IS_RECOVERED" in df.columns else 0)
