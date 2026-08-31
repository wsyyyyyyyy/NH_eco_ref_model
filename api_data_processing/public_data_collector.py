import os
import time
import logging
import requests
import pandas as pd
from typing import Dict, Optional

LOGGER = logging.getLogger(__name__)

class PublicDataCollector:
    """
    통계청 KOSIS 수집기
    """
    def __init__(self):
        self.kosis_api_key = os.getenv("KOSIS_API_KEY", "")
        self.max_retries = int(os.getenv("MAX_RETRIES", "3"))
        self.timeout = int(os.getenv("REQUEST_TIMEOUT", "10"))
        
    def _request_with_retry(self, url: str, params: Dict) -> Optional[requests.Response]:
        for attempt in range(1, self.max_retries + 1):
            try:
                response = requests.get(url, params=params, timeout=self.timeout)
                response.raise_for_status()
                return response
            except requests.RequestException as e:
                LOGGER.warning(f"[Attempt {attempt}/{self.max_retries}] API Request Failed: {e}")
                if attempt == self.max_retries:
                    LOGGER.error("Max retries reached. Skipping.")
                    return None
                time.sleep(2 ** attempt)
        return None

    def collect(self, indicator_name: str, start_date: str, end_date: str, **kwargs) -> pd.DataFrame:
        """지표명에 따른 라우팅"""
        LOGGER.info(f"Collecting Public Data: {indicator_name} [{start_date} ~ {end_date}]")
        
        start_m = pd.to_datetime(start_date).strftime("%Y%m")
        end_m = pd.to_datetime(end_date).strftime("%Y%m")
        
        # ── KOSIS 통계표 매핑 ────────────────────────────────────────
        # 2026-08-30 실측으로 전면 교체. 기존 매핑 3건이 모두 실패했다.
        #   unemployment_rate       101/DT_1DA7001  -> err 30 데이터가 존재하지 않습니다
        #   construction_cost_index 116/DT_1IF1003  -> err 21 해당 통계표가 존재하지 않습니다
        #   unsold_housing          116/DT_1YL0001  -> err 21 해당 통계표가 존재하지 않습니다
        # KOSIS statisticsSearch.do 로 올바른 표를 찾아 실 데이터로 확인했다.
        #
        # 값: (org_id, tbl_id, itm_id, {추가 objL 파라미터}, 필터)
        #   필터는 전국·총합 계열만 남기기 위한 (컬럼, 허용값) 목록이다.
        #   objL1=ALL 로 받아 시도별/부문별이 섞여 들어오므로 반드시 걸러야 한다.
        kosis_mapping = {
            # 성/연령별 실업률. itmId=T80(실업률), C1='계'(성별 계), C2='계'(연령 계)
            # 실측 기간 201901~202607 (지연 1개월)
            "unemployment_rate": ("101", "DT_1DA7102S", "T80",
                                  {"objL2": "ALL"},
                                  [("C1_NM", {"계"}), ("C2_NM", {"계"})]),
            # 건설공사비지수(2020년기준). 기관이 통계청(101)이 아니라 397 이다.
            # 실측 기간 201901~202606 (지연 2개월)
            "construction_cost_index": ("397", "DT_39701_A003", "16397AAA0",
                                        {}, []),
            # 규모별 미분양현황. 전국/총합/총합 만 사용. itmId='호'
            # 실측 기간 202401~202606 확인 (지연 2개월)
            "unsold_housing": ("116", "DT_MLTM_2080", "ALL",
                               {"objL2": "ALL", "objL3": "ALL"},
                               [("C1_NM", {"전국"}), ("C2_NM", {"총합"}),
                                ("C3_NM", {"총합"})]),
        }

        if indicator_name in kosis_mapping:
            org_id, tbl_id, itm_id, extra, filters = kosis_mapping[indicator_name]
            # KOSIS 는 1회 응답 40,000셀 상한이 있다 (err 31).
            # objL 을 여러 단계 ALL 로 여는 표는 몇 년치를 한 번에 받으면 넘친다.
            # 연 단위로 쪼개 받고 이어 붙인다.
            frames = []
            for y0, y1 in self._year_chunks(start_m, end_m):
                part = self._fetch_kosis_data(indicator_name, org_id, tbl_id, itm_id,
                                              y0, y1, extra, filters)
                if not part.empty:
                    frames.append(part)
            if not frames:
                return pd.DataFrame(columns=["date", indicator_name])
            out = pd.concat(frames, ignore_index=True)
            return (out.dropna().groupby("date").last().reset_index()
                       .sort_values("date").reset_index(drop=True))
            
        else:
            LOGGER.warning(f"Unknown public indicator: {indicator_name}")
            return pd.DataFrame(columns=["date", indicator_name])

    @staticmethod
    def _year_chunks(start_m: str, end_m: str):
        """YYYYMM 구간을 연 단위로 쪼갠다. KOSIS 40,000셀 상한 회피용."""
        y0, y1 = int(start_m[:4]), int(end_m[:4])
        for y in range(y0, y1 + 1):
            lo = start_m if y == y0 else f"{y}01"
            hi = end_m if y == y1 else f"{y}12"
            yield lo, hi

    def _fetch_kosis_data(self, indicator_name: str, org_id: str, tbl_id: str,
                          itm_id: str, start_m: str, end_m: str,
                          extra: Optional[Dict] = None,
                          filters: Optional[list] = None) -> pd.DataFrame:
        """KOSIS API 공통 수집 함수"""
        if not self.kosis_api_key:
            LOGGER.warning("KOSIS_API_KEY is not set.")
            return pd.DataFrame(columns=["date", indicator_name])

        url = "https://kosis.kr/openapi/Param/statisticsParameterData.do"
        params = {
            "method": "getList",
            "apiKey": self.kosis_api_key,
            "itmId": itm_id,
            "objL1": "ALL",
            "objL2": "",
            "objL3": "",
            "objL4": "",
            "objL5": "",
            "objL6": "",
            "objL7": "",
            "objL8": "",
            "format": "json",
            "jsonVD": "Y",
            "prdSe": "M",
            "startPrdDe": start_m,
            "endPrdDe": end_m,
            "orgId": org_id,
            "tblId": tbl_id
        }
        if extra:
            params.update(extra)

        
        res = self._request_with_retry(url, params)
        if not res:
            return pd.DataFrame(columns=["date", indicator_name])
            
        try:
            data = res.json()
            if "err" in data:
                LOGGER.error(f"KOSIS API Error: {data['err']}")
                return pd.DataFrame(columns=["date", indicator_name])
                
            df = pd.DataFrame(data)
            if "PRD_DE" not in df.columns or "DT" not in df.columns:
                return pd.DataFrame(columns=["date", indicator_name])

            # 전국·총합 계열만 남긴다. 안 거르면 시도별/규모별이 섞여
            # groupby(date).last() 가 임의의 한 지역 값을 집어간다.
            n0 = len(df)
            for col, allowed in (filters or []):
                if col in df.columns:
                    df = df[df[col].astype(str).str.strip().isin(allowed)]
            if filters:
                LOGGER.info("  %s: %d행 -> %d행 (전국/총합 필터)", indicator_name, n0, len(df))
            if df.empty:
                LOGGER.error("KOSIS %s: 필터 후 데이터가 비었다. 매핑 확인 필요.", indicator_name)
                return pd.DataFrame(columns=["date", indicator_name])

            df = df[["PRD_DE", "DT"]].rename(columns={"PRD_DE": "date", "DT": indicator_name})
            df["date"] = pd.to_datetime(df["date"], format="%Y%m", errors="coerce")
            df[indicator_name] = pd.to_numeric(df[indicator_name], errors="coerce")
            
            # 중복 날짜 처리 및 정렬 (월초 기준)
            return df.dropna().groupby("date").last().reset_index().sort_values("date")
        except Exception as e:
            LOGGER.error(f"Failed to parse KOSIS data for {indicator_name}: {e}")
            return pd.DataFrame(columns=["date", indicator_name])

