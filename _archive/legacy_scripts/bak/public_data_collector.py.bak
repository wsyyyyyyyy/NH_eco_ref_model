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
        
        # KOSIS 통계표 매핑 (OrgId는 기본 통계청 101, tblId는 각각 다름)
        # 미분양(DT_1YL0001, orgId=116 국토교통부), 실업률(DT_1DA7001, orgId=101 통계청), 건설공사비(DT_1IF1003, orgId=116 등)
        # KOSIS API 파라미터로 OrgId와 TblId를 함께 받아야 함.
        kosis_mapping = {
            "unemployment_rate": ("101", "DT_1DA7001", "T90"), # itmId는 구체적인 항목ID
            "construction_cost_index": ("116", "DT_1IF1003", "ALL"),
            "unsold_housing": ("116", "DT_1YL0001", "ALL")
        }
        
        if indicator_name in kosis_mapping:
            org_id, tbl_id, itm_id = kosis_mapping[indicator_name]
            return self._fetch_kosis_data(indicator_name, org_id, tbl_id, itm_id, start_m, end_m)
            
        else:
            LOGGER.warning(f"Unknown public indicator: {indicator_name}")
            return pd.DataFrame(columns=["date", indicator_name])

    def _fetch_kosis_data(self, indicator_name: str, org_id: str, tbl_id: str, itm_id: str, start_m: str, end_m: str) -> pd.DataFrame:
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
                
            df = df[["PRD_DE", "DT"]].rename(columns={"PRD_DE": "date", "DT": indicator_name})
            df["date"] = pd.to_datetime(df["date"], format="%Y%m", errors="coerce")
            df[indicator_name] = pd.to_numeric(df[indicator_name], errors="coerce")
            
            # 중복 날짜 처리 및 정렬 (월초 기준)
            return df.dropna().groupby("date").last().reset_index().sort_values("date")
        except Exception as e:
            LOGGER.error(f"Failed to parse KOSIS data for {indicator_name}: {e}")
            return pd.DataFrame(columns=["date", indicator_name])

