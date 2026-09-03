from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
import requests
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .public_data_collector import PublicDataCollector

LOGGER = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════
# 수집 단계 매핑·값 검증
# ══════════════════════════════════════════════════════════════════════
# 사고 이력이 두 번이다.
#   1차 (2026-08-30) JEMU 계정코드 라벨이 한 칸씩 밀렸다 — 라벨만 틀렸다.
#   2차 (2026-09-01) ECOS 항목코드 오매핑 — **수집된 값 자체가 다른 계열**이었다.
#                    817Y002 국고채 만기가 한 칸씩 밀려 corporate_bond_3y_AA 에
#                    국고채(1년)이 들어왔고, credit_spread 가 77개월 중 68개월 음수였다.
# 사후 감사(`audit_mapping.py`)로만 잡으면 늦다. 수집 시점에 막는다.

#: 지표 유형 → 값 범위 상식 규칙 (하한, 상한).
#: 벗어나면 경고 로그를 남긴다. 수집 자체를 막지는 않는다 —
#: 값이 정말 이상한지 사람이 원자료를 보고 판단해야 하기 때문이다.
RANGE_RULES: Dict[str, tuple] = {
    "RATE": (-1.0, 10.0),      # 금리(연%) — 마이너스 금리 여지로 하한을 -1 로 둔다
    "BSI": (50.0, 150.0),      # 확산지수
    "INDEX": (0.0, None),      # 지수 — 양수. 기준연도 근처 출발은 별도 확인
    "MONEY": (None, None),     # 잔액 — 단위 일관성만 본다
    "PCT": (-30.0, 30.0),      # 증감률/비율(%)
    "FX": (0.0, None),
    "PRICE": (0.0, None),
    "COUNT": (0.0, None),
}

#: series_name → 지표 유형. indicators.csv 와 함께 갱신할 것.
SERIES_TYPE: Dict[str, str] = {
    **{k: "RATE" for k in (
        "base_rate", "call_rate_overnight", "call_rate_overnight_brokered",
        "treasury_bond_1y", "treasury_bond_3y", "treasury_bond_5y",
        "treasury_bond_10y", "corporate_bond_3y_AA", "KORIBOR_3m",
        "KORIBOR_6m", "KORIBOR_12m", "CD_rate_91d", "treasury_bond_1y_monthly",
        "CP_91d", "MSB_91d", "US_10Y_treasury", "US_3M_tbill")},
    **{k: "BSI" for k in (
        "BSI_mfg_biz", "BSI_mfg_export", "BSI_mfg_domestic",
        "BSI_nonmfg_biz", "CSI_composite", "CSI_living_prospect")},
    **{k: "INDEX" for k in (
        "PPI_total", "CPI_core", "CPI_core_excl_food_energy",
        "CPI_food_nonalcohol", "housing_price_index", "export_price_index_KOR",
        "export_index", "import_index", "trade_total", "manufacturing_index",
        "construction_cost_index")},
    **{k: "MONEY" for k in (
        "M2_broad_money", "M1_narrow_money", "Lf_liquidity", "monetary_base_sa",
        "current_account", "current_account_quarterly", "goods_balance",
        "household_credit", "household_loan",
        "GNI_annual", "GNI_nominal", "GNI_per_capita")},
    **{k: "FX" for k in ("CNY_KRW", "USD_KRW", "JPY_KRW", "EUR_KRW")},
    **{k: "PRICE" for k in (
        "KOSPI", "KOSDAQ", "SP500", "NASDAQ", "DowJones", "Nikkei225",
        "Shanghai_Composite", "VIX", "DXY_dollar_index", "WTI_crude_oil",
        "brent_crude_oil", "gold", "silver", "copper", "natural_gas",
        "soybean", "corn")},
    "unemployment_rate": "PCT",
    "unsold_housing": "COUNT",
}

#: 파생 스프레드의 부호 규칙.
#:   (피감수, 감수, 기대부호, 허용 위반 비율)
#: 기대부호 '+' 는 (a - b) 가 양수여야 한다는 뜻이다.
#: 위반 비율이 허용치를 넘으면 **예외를 던진다.** credit_spread 사고를
#: 수집 직후에 잡기 위한 장치이므로 경고가 아니라 중단이다.
DERIVED_SIGN_RULES: Dict[str, tuple] = {
    # 회사채 AA- 3년 − 국고채 3년 = 신용스프레드. 음수는 차익거래로 소멸한다.
    "credit_spread": ("corporate_bond_3y_AA", "treasury_bond_3y", "+", 0.10),
    # CP 91일 − 통안증권 91일 = 유동성스프레드. 신용위험 프리미엄만큼 양수다.
    "liquidity_spread": ("CP_91d", "MSB_91d", "+", 0.10),
}


#: 지표 -> 시차 그룹. impute_data 의 GROUP_*_COLS 와 같은 뜻이며,
#: 수집 시점에 "이 그룹이 실제 공표 지연을 감당하는가" 를 자동 점검하는 데 쓴다.
#: impute_data 를 임포트하면 순환 참조가 되므로 여기서는 그룹명만 둔다.
SHIFT_GROUP = {
    "A": 0, "B": 1, "C": 2, "D": 3,
}

#: 월초 측정 보정 기준일. 측정일이 이 날보다 이르면 경과에서 1개월을 뺀다.
#: 근거는 `check_publication_lag` 의 주석에 있다.
MONTH_START_CUTOFF_DAY = 15


def _observed_month_step(d: pd.Series) -> int:
    """관측된 수록월 간격의 중앙값(개월). 월간이면 1, 분기면 3.

    설정의 `frequency` 를 믿지 않고 **받은 데이터로 직접 잰다.** 매핑 사고가
    두 번 있었던 프로젝트에서 설정값은 정본이 아니다.
    """
    months = sorted({int(x.year) * 12 + int(x.month) for x in d})
    if len(months) < 3:
        return 1
    gaps = [b - a for a, b in zip(months, months[1:]) if b > a]
    if not gaps:
        return 1
    return int(np.median(gaps))


def check_publication_lag(series_name: str, dates: pd.Series, group: str,
                          requested_end: Optional[str] = None,
                          collected_at: Optional[pd.Timestamp] = None
                          ) -> tuple[Optional[int], Optional[str]]:
    """수집일과 실데이터 최종월의 격차를 재고, 시차 그룹이 부족하면 경고한다.

    2026-09-01 관측에서 국제수지·통화량 6건이 Group B(+1) 인데 실제로는
    t+2 이후에야 공표된다는 것이 드러났다 (최종 수록 2026-06). shift(+1) 은
    아직 존재하지 않는 값을 쓰는 look-ahead 다.

    그 관측을 일회성으로 두지 않기 위해 **수집할 때마다 다시 잰다.**
    공표 일정은 개편·지연으로 달라지므로 문서에 박아 둔 값을 믿지 않는다.

    측정일이 월초(15일 이전)면 직전월 공표를 아직 반영하지 못하므로 경과에서
    1을 뺀다 (`MONTH_START_CUTOFF_DAY`). 단 **월간 공표 계열에만** 적용한다 —
    분기 계열에는 놓칠 직전월분이 없다. 보정 근거는 본문 주석에 있다.

    Returns
    -------
    (lag_months, warning) — 경고가 없으면 warning 은 None.
      lag_months 는 **보정 후** 값이다. 원값은 경고 문구에 병기한다.
    """
    d = pd.to_datetime(pd.Series(dates), errors="coerce").dropna()
    if d.empty:
        return None, None
    now = collected_at or pd.Timestamp.now()
    # ★ 기준은 '오늘' 이 아니라 **요청 종료일과 오늘 중 이른 쪽** 이다.
    #   --end-date 2026-05-31 로 끊어 받고 오늘(2026-09)과 비교하면 전 지표가
    #   4개월 지연으로 잡힌다. 초판이 62건 오탐을 낸 원인이다.
    #   애초에 요청하지 않은 구간을 '공표 지연' 이라 부를 수 없다.
    if requested_end:
        try:
            now = min(now, pd.Timestamp(requested_end))
        except (ValueError, TypeError):
            pass
    last = d.max()
    lag_raw = (now.year - last.year) * 12 + (now.month - last.month)

    # ★ [2026-09-02] 월초 측정 보정.
    #
    #   `lag > shift` 로 조인 임계가 월초 측정에서 **전 지표를 걸리게** 했다.
    #   2026-09-01 관측에서 15건이 걸렸는데, 그 15건의 `경과 − 시차` 가
    #   **일률적으로 +1** 이었다. Group B(+1) 7건과 Group C(+2) 8건은 시차가
    #   다른 두 그룹인데 편차가 같았다. 개별 지표의 공표 지연 문제라면 값이
    #   흩어져야 한다. 균일한 +1 은 지표 특성이 아니라 **측정 방법의 공통 편향**이다.
    #
    #   원인: 측정일이 월초다.
    #     CPI 7월분 -> 8월 초 공표 -> 9/1 시점 가용     시차 +1 정합
    #     CPI 8월분 -> 9월 초 공표 -> 9/1 시점 미공표
    #   경과 = 2026-09 − 2026-07 = 2 로 계산되지만, 9월분은 애초에 존재할 수 없는
    #   달이다. 월초 측정으로 한 달치를 덜 본 착시다. 월말에 측정했다면
    #   `경과 − 시차 = 0` 이 나왔을 것이다.
    #
    #   그래서 임계를 느슨하게 하는 대신(경과−시차>=2) **원인에 직접 대응**한다.
    #   측정일이 그 달 15일 이전이면 직전월 공표를 아직 반영하지 못한 것으로 보고
    #   경과에서 1을 뺀다. 임계는 `lag > shift` 를 유지한다 — 보정 후에도 걸리는
    #   지표는 **진짜 look-ahead 후보**다.
    #   ★ 보정은 **월간 공표 계열에만** 적용한다.
    #     보정의 근거는 "직전월 공표를 아직 반영하지 못했다" 이고, 그런 직전월
    #     공표가 존재하는 것은 월간 계열뿐이다. 분기 계열에는 놓칠 직전월분이
    #     없으므로 보정하면 실제 지연을 1개월 깎아 버린다.
    #     실제로 일률 보정하면 분기 3건(household_credit / household_loan /
    #     current_account_quarterly)이 경과 3 -> 2 가 되어 Group C(+2) 로도
    #     통과한다. 그러면 **가드가 Group D 이동 사유를 스스로 못 잡게 된다.**
    #     주기는 설정값이 아니라 받은 데이터에서 실측한다(_observed_month_step).
    step = _observed_month_step(d)
    month_start_adj = 1 if (now.day < MONTH_START_CUTOFF_DAY and step <= 1) else 0
    lag = max(lag_raw - month_start_adj, 0)

    shift = SHIFT_GROUP.get(str(group).upper())
    if shift is None:
        return lag, None
    # t 월 값을 t+shift 월에 쓰려면, 늦어도 t+shift 월 안에는 공표되어 있어야 한다.
    # 관측된 지연이 shift 를 넘으면 그 시차로는 없는 값을 쓰게 된다.
    #
    # ★ [2026-09-02] 임계를 `lag > shift + 1` 에서 `lag > shift` 로 조였다.
    #   구 임계는 경과월이 시차보다 정확히 1개월 큰 경계선을 통과시켰다.
    #   그 경계선이 바로 1개월 look-ahead 다 — 분기 3건(household_credit /
    #   household_loan / current_account_quarterly)이 Group C(+2) 에 경과 3개월로
    #   앉아 있던 것을 이 임계가 놓쳤다. 경계선은 통과가 아니라 경고여야 한다.
    if lag > shift:
        adj = (f" [월초 보정 −1, 원값 {lag_raw}]" if month_start_adj
               else (f" [관측 주기 {step}개월 — 월초 보정 미적용]" if step > 1 else ""))
        return lag, (f"공표 지연 초과: {series_name} 실데이터 최종 {last:%Y-%m} "
                     f"(수집일 기준 {lag}개월 경과{adj}) 인데 "
                     f"Group {group}(+{shift}) 이다. "
                     f"+{lag} 이상이 필요하다 — 시차 그룹을 재검토할 것")
    return lag, None


class MappingValidationError(RuntimeError):
    """수집·파생 단계에서 매핑이 틀렸다고 판정될 때 던진다."""


def _group_of(series_name: str) -> str:
    """impute_data 의 GROUP_*_COLS 에서 시차 그룹을 읽는다.

    그룹 정의를 여기에 복제하면 두 곳이 갈라진다. **impute_data 를 정본으로 둔다.**
    임포트 실패(경로/의존성)는 검증 생략으로 처리하고 수집을 막지 않는다.
    """
    try:
        from api_data_processing import impute_data as _imp
    except Exception:                                             # noqa: BLE001
        return ""
    for g in ("A", "B", "C", "D"):
        if series_name in getattr(_imp, f"GROUP_{g}_COLS", []):
            return g
    return ""


def check_item_name(series_name: str, expected_name_kr: str,
                    actual_names: str) -> Optional[str]:
    """`expected_name_kr` 의 키워드가 실제 응답 명칭에 전부 들어 있는지 본다.

    `expected_name_kr` 은 `|` 로 나눈 키워드 목록이다 (예: ``회사채(3년)|AA-``).
    비어 있으면 검증하지 않고 None 을 돌려준다 — 기대값을 안 적어 둔 지표는
    '통과' 가 아니라 '미검증' 이다.
    """
    if not expected_name_kr:
        return None
    hay = "".join(str(actual_names).split()).lower()
    missing = [q for q in expected_name_kr.split("|") if q.strip()
               and "".join(q.split()).lower() not in hay]
    if not missing:
        return None
    return (f"항목명 불일치: {series_name} — 기대 {expected_name_kr!r} 중 "
            f"{missing!r} 가 응답 명칭 {actual_names!r} 에 없다")


def check_value_range(series_name: str, values: pd.Series) -> Optional[str]:
    """지표 유형별 값 범위 상식 검증. 벗어나면 경고 문자열을 돌려준다."""
    s = pd.to_numeric(values, errors="coerce").dropna()
    if s.empty:
        return f"값 범위 검증 불가: {series_name} — 수집값이 비어 있다"
    typ = SERIES_TYPE.get(series_name)
    if typ is None:
        return None
    if typ == "MONEY":
        # 단위 일관성. 잔액·수지는 십억원(1e5~1e7) 또는 백만달러(1e3~1e5) 규모다.
        # 규모가 두 자릿수 이하면 금리·비율 계열이 잘못 들어온 것이다 —
        # M2_broad_money 자리에 기준금리(0.5~3.5)가 들어와 있던 것이 이 경우다.
        med = float(s.abs().median())
        if med < 100.0:
            return (f"단위 이상: {series_name} [MONEY] 잔액·수지 규모가 아니다 "
                    f"(|중앙값| {med:.4g}). 금리·비율 계열이 들어왔는지 확인할 것")
        return None
    if typ == "INDEX":
        # 지수는 기준연도 100 근처에서 출발해야 한다.
        first = float(s.iloc[0])
        if not (50.0 <= first <= 200.0):
            return (f"기준연도 이상: {series_name} [INDEX] 시작값 {first:.4g} — "
                    f"기준연도 100 근처가 아니다 (실측 {float(s.min()):.4g}~{float(s.max()):.4g})")
    if typ == "PRICE" and series_name == "WTI_crude_oil":
        # WTI 는 2020-04-20 에 실제로 -37.63 을 찍었다. 실측 사건이라 예외로 둔다.
        # 다른 가격 계열의 음수는 그대로 경고 대상이다.
        return None
    lo, hi = RANGE_RULES.get(typ, (None, None))
    vmin, vmax = float(s.min()), float(s.max())
    bad = (lo is not None and vmin < lo) or (hi is not None and vmax > hi)
    if not bad:
        return None
    return (f"값 범위 이상: {series_name} [{typ}] 기대 "
            f"{'-inf' if lo is None else lo}~{'inf' if hi is None else hi} / "
            f"실측 {vmin:.4g}~{vmax:.4g}")


def validate_derived_spread(name: str, series: pd.Series,
                            rules: Optional[Dict[str, tuple]] = None) -> None:
    """파생 스프레드의 부호를 검증한다. 규칙 위반이 허용치를 넘으면 예외.

    credit_spread 는 회사채 − 국고채이므로 음수가 나올 수 없다.
    68/77 개월이 음수였는데도 조용히 통과했던 것이 2차 사고의 본질이다.
    """
    rule = (rules or DERIVED_SIGN_RULES).get(name)
    if rule is None:
        return
    a, b, sign, tol = rule
    s = pd.to_numeric(series, errors="coerce").dropna()
    if s.empty:
        raise MappingValidationError(f"{name}: 파생값이 비어 있어 부호 검증 불가")
    wrong = float((s < 0).mean()) if sign == "+" else float((s > 0).mean())
    if wrong > tol:
        raise MappingValidationError(
            f"{name} 부호 위반: ({a} - {b}) 가 기대부호 '{sign}' 를 "
            f"{wrong:.1%} 구간에서 어긴다 (허용 {tol:.0%}). "
            f"항목코드 매핑을 의심할 것 — audit_mapping.py 로 명세를 대조하라")
    LOGGER.info("파생 부호 검증 통과: %s (위반 %.1f%% ≤ 허용 %.0f%%)",
                name, wrong * 100, tol * 100)


@dataclass
class CollectorConfig:
    ecos_api_key: str
    request_timeout: int = 30
    sleep_seconds: float = 0.35
    max_retries: int = 5
    backoff_factor: float = 1.0
    page_size: int = 1000


class DataCollector:
    """
    Collect macroeconomic time-series data from ECOS and Yahoo Finance.

    Expected config CSV columns:
    - source: ECOS or YAHOO
    - series_name: final output column name
    - enabled: Y/N or 1/0
    - frequency: A/Q/M/W/D
    - stat_code: ECOS only
    - item_code1 ~ item_code4: ECOS only (optional)
    - ticker: Yahoo only
    - field: Yahoo only (default=Close)
    """

    ECOS_BASE_URL = "https://ecos.bok.or.kr/api"
    YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"

    def __init__(self, config: Optional[CollectorConfig] = None) -> None:
        load_dotenv()
        self.config = config or CollectorConfig(
            ecos_api_key=os.getenv("ECOS_API_KEY", ""),
            request_timeout=int(os.getenv("REQUEST_TIMEOUT", "30")),
            sleep_seconds=float(os.getenv("REQUEST_SLEEP", "0.35")),
            max_retries=int(os.getenv("MAX_RETRIES", "5")),
            backoff_factor=float(os.getenv("BACKOFF_FACTOR", "1.0")),
            page_size=int(os.getenv("ECOS_PAGE_SIZE", "1000")),
        )
        if not self.config.ecos_api_key:
            LOGGER.warning("ECOS_API_KEY is empty. ECOS collection will fail until .env is configured.")
        self.session = self._build_session()
        # 직전 수집 응답의 공식 명칭. check_item_name / 메타 기록에 쓴다.
        self._last_source_meta: Dict[str, str] = {}
        # series_name -> 수집 시점 메타. 수집 종료 시 metadata JSON 으로 남긴다.
        self.collected_meta: Dict[str, Dict] = {}

    def _build_session(self) -> requests.Session:
        retry = Retry(
            total=self.config.max_retries,
            connect=self.config.max_retries,
            read=self.config.max_retries,
            backoff_factor=self.config.backoff_factor,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=frozenset(["GET"]),
            raise_on_status=False,
            respect_retry_after_header=True,
        )
        adapter = HTTPAdapter(max_retries=retry)
        session = requests.Session()
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        session.headers.update({"User-Agent": "raw-macro-data-collector/1.0"})
        return session

    @staticmethod
    def _normalize_frequency(freq: str) -> str:
        freq = str(freq).upper().strip()
        alias = {
            "YEAR": "A",
            "ANNUAL": "A",
            "Y": "A",
            "QUARTER": "Q",
            "QUARTERLY": "Q",
            "MONTH": "M",
            "MONTHLY": "M",
            "WEEK": "W",
            "WEEKLY": "W",
            "DAY": "D",
            "DAILY": "D",
        }
        return alias.get(freq, freq)

    @staticmethod
    def _format_date_value(raw_time: str, freq: str) -> pd.Timestamp:
        freq = DataCollector._normalize_frequency(freq)
        raw = str(raw_time)

        if freq == "A":
            return pd.to_datetime(raw, format="%Y")
        if freq == "Q":
            year, quarter = raw[:4], raw[-1]
            month_map = {"1": "03", "2": "06", "3": "09", "4": "12"}
            return pd.to_datetime(f"{year}{month_map[quarter]}01", format="%Y%m%d")
        if freq == "M":
            return pd.to_datetime(raw + "01", format="%Y%m%d")
        if freq == "W":
            # ISO week fallback: convert to week start date (Monday)
            if len(raw) == 6 and raw[:4].isdigit() and raw[4:].isdigit():
                return pd.to_datetime(raw + "-1", format="%G%V-%u")
            return pd.to_datetime(raw)
        if freq == "D":
            return pd.to_datetime(raw, format="%Y%m%d")

        return pd.to_datetime(raw)

    @staticmethod
    def _date_for_request(value: str, freq: str) -> str:
        ts = pd.to_datetime(value)
        freq = DataCollector._normalize_frequency(freq)

        if freq == "A":
            return ts.strftime("%Y")
        if freq == "Q":
            quarter = (ts.month - 1) // 3 + 1
            return f"{ts.year}Q{quarter}"
        if freq == "M":
            return ts.strftime("%Y%m")
        if freq == "W":
            return ts.strftime("%Y%m%d")
        if freq == "D":
            return ts.strftime("%Y%m%d")

        return ts.strftime("%Y%m%d")

    @staticmethod
    def _to_float(series: pd.Series) -> pd.Series:
        return pd.to_numeric(
            series.astype(str).str.replace(",", "", regex=False),
            errors="coerce"
        ).astype(float)

    def _request_json(self, url: str, params: Optional[Dict] = None) -> Dict:
        last_error = None

        for attempt in range(1, self.config.max_retries + 1):
            try:
                response = self.session.get(
                    url,
                    params=params,
                    timeout=self.config.request_timeout,
                )

                if response.status_code == 429:
                    wait_seconds = min(2 ** attempt, 30)
                    LOGGER.warning("Rate limit hit. Sleeping %.1f seconds before retry...", wait_seconds)
                    time.sleep(wait_seconds)
                    continue

                response.raise_for_status()
                data = response.json()
                self._raise_if_api_error(data)
                return data

            except (requests.RequestException, ValueError) as exc:
                last_error = exc
                wait_seconds = min((2 ** (attempt - 1)) * self.config.backoff_factor, 30)
                LOGGER.warning(
                    "Request failed (attempt=%s/%s): %s",
                    attempt,
                    self.config.max_retries,
                    exc,
                )
                time.sleep(wait_seconds)

        raise RuntimeError(f"API request failed after retries: {url}") from last_error

    @staticmethod
    def _raise_if_api_error(payload: Dict) -> None:
        for value in payload.values():
            if isinstance(value, dict) and "CODE" in value:
                code = str(value.get("CODE", ""))
                message = value.get("MESSAGE", "Unknown API error")
                if code not in {"INFO-200"} and (code.startswith("INFO-") or code.startswith("ERROR-")):
                    raise RuntimeError(f"API error: {code} - {message}")

    def fetch_ecos_data(
        self,
        stat_code: str,
        item_code: Optional[str],
        start_date: str,
        end_date: str,
        frequency: str = "M",
        item_code2: Optional[str] = None,
        item_code3: Optional[str] = None,
        item_code4: Optional[str] = None,
        series_name: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        ECOS StatisticSearch 호출 후 표준화된 DataFrame 반환.
        """
        freq = self._normalize_frequency(frequency)
        item_code1 = item_code or ""
        codes = [item_code1 or "", item_code2 or "", item_code3 or "", item_code4 or ""]
        start = self._date_for_request(start_date, freq)
        end = self._date_for_request(end_date, freq)

        rows: List[Dict] = []
        start_row = 1

        while True:
            end_row = start_row + self.config.page_size - 1

            path = "/".join(
                [
                    "StatisticSearch",
                    self.config.ecos_api_key,
                    "json",
                    "kr",
                    str(start_row),
                    str(end_row),
                    stat_code,
                    freq,
                    start,
                    end,
                    *codes,
                ]
            )
            url = f"{self.ECOS_BASE_URL}/{path}"
            payload = self._request_json(url)

            key = next((k for k in payload.keys() if k.lower() == "statisticsearch"), None)
            if not key:
                break

            data_block = payload.get(key, {})
            current_rows = data_block.get("row", []) or []
            rows.extend(current_rows)

            total_count = int(data_block.get("list_total_count", len(rows)))
            if not current_rows or len(rows) >= total_count:
                break

            start_row = end_row + 1
            time.sleep(self.config.sleep_seconds)

        if not rows:
            LOGGER.info("No ECOS data found: stat_code=%s, item_code=%s", stat_code, item_code1)
            return pd.DataFrame(columns=["date", series_name or stat_code])

        df = pd.DataFrame(rows)
        # ── 매핑 검증용: 응답이 알려 주는 공식 명칭을 붙잡아 둔다 ──────────
        # ECOS 는 요청한 항목코드의 ITEM_NAME1~4 를 매 행에 실어 준다.
        # 이 값을 버렸기 때문에 항목코드 오매핑을 수집 시점에 못 잡았다.
        first = df.iloc[0]
        name_cols = [c for c in ("ITEM_NAME1", "ITEM_NAME2", "ITEM_NAME3", "ITEM_NAME4")
                     if c in df.columns]
        names = [str(first.get(f"ITEM_NAME{i}", "") or "") for i in range(1, 5)]
        combos = (df[name_cols].astype(str).drop_duplicates()
                  if name_cols else pd.DataFrame())
        dim_warning = ""
        if len(combos) > 1:
            # 다차원 통계표에서 하위 차원을 지정하지 않으면 여러 계열이 함께 온다.
            # 아래 drop_duplicates(keep="last") 가 그 중 하나를 임의로 고르고,
            # 이름은 첫 행에서 읽으므로 **이름과 값이 다른 계열일 수 있다.**
            # (402Y014 수출물가지수: 통화계약구분 D/W/C 3종이 함께 온다)
            picked = [" / ".join(x for x in r if x and x != "nan")
                      for r in combos.head(5).itertuples(index=False)]
            dim_warning = (f"차원 미지정: {stat_code}/{item_code1} 응답에 "
                           f"{len(combos)}개 계열이 섞여 있다 ({'; '.join(picked)}"
                           f"{' …' if len(combos) > 5 else ''}). "
                           f"item_code2~4 를 지정할 것 — 지정하지 않으면 임의의 한 계열이 저장된다")
            LOGGER.warning("★ %s", dim_warning)
        self._last_source_meta = {
            "stat_name": str(first.get("STAT_NAME", "") or ""),
            "item_names": " / ".join(x for x in names if x),
            "unit_name": str(first.get("UNIT_NAME", "") or ""),
            "dim_warning": dim_warning,
        }
        value_col = series_name or f"{stat_code}_{item_code1 or 'ALL'}"

        result = pd.DataFrame(
            {
                "date": df["TIME"].map(lambda x: self._format_date_value(x, freq)),
                value_col: self._to_float(df["DATA_VALUE"]),
            }
        )

        result = (
            result.sort_values("date")
            .drop_duplicates(subset=["date"], keep="last")
            .reset_index(drop=True)
        )
        return result

    def fetch_yahoo_data(
        self,
        ticker: str,
        start_date: str,
        end_date: str,
        frequency: str = "D",
        series_name: Optional[str] = None,
        field: str = "Close",
    ) -> pd.DataFrame:
        """
        Yahoo Finance chart endpoint 호출 (requests 기반)
        """
        start_ts = int(pd.Timestamp(start_date).timestamp())
        end_ts = int((pd.Timestamp(end_date) + pd.Timedelta(days=1)).timestamp())

        freq = self._normalize_frequency(frequency)
        interval_map = {"D": "1d", "W": "1wk", "M": "1mo"}
        interval = interval_map.get(freq, "1d")

        url = self.YAHOO_CHART_URL.format(ticker=ticker)
        params = {
            "period1": start_ts,
            "period2": end_ts,
            "interval": interval,
            "includeAdjustedClose": "true",
        }

        payload = self._request_json(url, params=params)

        chart = payload.get("chart", {})
        error = chart.get("error")
        if error:
            raise RuntimeError(f"Yahoo Finance error for {ticker}: {error}")

        result = chart.get("result", [])
        if not result:
            LOGGER.info("No Yahoo data found: ticker=%s", ticker)
            return pd.DataFrame(columns=["date", series_name or ticker])

        node = result[0]
        meta = node.get("meta", {}) or {}
        self._last_source_meta = {
            "stat_name": str(meta.get("exchangeName", "") or ""),
            "item_names": str(meta.get("longName") or meta.get("shortName") or ""),
            "unit_name": str(meta.get("currency", "") or ""),
        }
        timestamps = node.get("timestamp", []) or []
        quote = ((node.get("indicators") or {}).get("quote") or [{}])[0]

        field_map = {
            "OPEN": "open",
            "HIGH": "high",
            "LOW": "low",
            "CLOSE": "close",
            "VOLUME": "volume",
        }
        selected_field = field_map.get(field.upper(), "close")
        values = quote.get(selected_field, []) or []
        value_col = series_name or ticker

        result_df = pd.DataFrame(
            {
                "date": pd.to_datetime(pd.Series(timestamps), unit="s").dt.normalize(),
                value_col: pd.to_numeric(pd.Series(values), errors="coerce").astype(float),
            }
        )

        result_df = (
            result_df.sort_values("date")
            .drop_duplicates(subset=["date"], keep="last")
            .reset_index(drop=True)
        )
        return result_df

    def load_indicator_config(self, config_path: str | Path) -> pd.DataFrame:
        path = Path(config_path)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")

        df = pd.read_csv(path, dtype=str, comment="#").fillna("")

        if "enabled" not in df.columns:
            df["enabled"] = "Y"

        enabled_mask = df["enabled"].astype(str).str.upper().isin(["Y", "YES", "1", "TRUE"])
        df = df.loc[enabled_mask].reset_index(drop=True)

        if df.empty:
            raise ValueError("No enabled indicators found in config file.")

        return df

    def standardize_frame(self, df: pd.DataFrame, value_columns: Optional[List[str]] = None) -> pd.DataFrame:
        out = df.copy()
        out["date"] = pd.to_datetime(out["date"], errors="coerce").dt.normalize()
        out = out.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)

        if value_columns is None:
            value_columns = [col for col in out.columns if col != "date"]

        for col in value_columns:
            out[col] = self._to_float(out[col])

        return out

    def collect_from_config(
        self,
        config_df: pd.DataFrame,
        start_date: str,
        end_date: str,
        raw_dir: Optional[str | Path] = None,
        state_manager=None,
    ) -> List[pd.DataFrame]:
        """
        Collect indicators defined in *config_df*.

        Parameters
        ----------
        raw_dir : path, optional
            If given, each indicator is saved as an individual CSV under
            this directory (``raw_dir/{series_name}.csv``).
        state_manager : LoadStateManager, optional
            If given, enables **incremental load** – only data newer than
            the last-loaded date is fetched and appended.
        """
        collected_frames: List[pd.DataFrame] = []
        save_individually = raw_dir is not None
        if save_individually:
            raw_path = Path(raw_dir)
            raw_path.mkdir(parents=True, exist_ok=True)

        public_collector = PublicDataCollector()

        for idx, row in config_df.iterrows():
            source = row.get("source", "").strip().upper()
            series_name = row.get("series_name", f"series_{idx + 1}").strip()
            frequency = row.get("frequency", "D")

            # --- Incremental: determine effective start date ---------------
            effective_start = start_date
            if state_manager is not None:
                last = state_manager.get_last_date(series_name)
                if last is not None:
                    effective_start = last
                    LOGGER.info(
                        "Incremental: %s – resuming from %s",
                        series_name, effective_start,
                    )

            self._last_source_meta = {}
            try:
                LOGGER.info(
                    "Collecting (%s/%s): %s / %s  [%s → %s]",
                    idx + 1, len(config_df), source, series_name,
                    effective_start, end_date,
                )

                if source == "ECOS":
                    df = self.fetch_ecos_data(
                        stat_code=row.get("stat_code", "").strip(),
                        item_code=row.get("item_code1", "").strip(),
                        item_code2=row.get("item_code2", "").strip() or None,
                        item_code3=row.get("item_code3", "").strip() or None,
                        item_code4=row.get("item_code4", "").strip() or None,
                        start_date=effective_start,
                        end_date=end_date,
                        frequency=frequency,
                        series_name=series_name,
                    )

                elif source == "YAHOO":
                    df = self.fetch_yahoo_data(
                        ticker=row.get("ticker", "").strip(),
                        start_date=effective_start,
                        end_date=end_date,
                        frequency=frequency,
                        series_name=series_name,
                        field=row.get("field", "Close").strip(),
                    )

                elif source == "PUBLIC":
                    df = public_collector.collect(
                        indicator_name=series_name,
                        start_date=effective_start,
                        end_date=end_date,
                    )
                    # KOSIS 수집기가 남긴 통계표명·항목명을 ECOS 와 같은 형식으로 옮긴다.
                    # 이게 없으면 KOSIS 3건은 응답 명칭이 비어 항목명 대조가 늘 실패한다.
                    self._last_source_meta = dict(
                        getattr(public_collector, "last_meta", {}) or {})

                else:
                    raise ValueError(f"Unsupported source: {source}")

                df = self.standardize_frame(
                    df, value_columns=[c for c in df.columns if c != "date"],
                )

                # ── 매핑 검증 (2026-09-01 사고 재발 방지) ──────────────────
                # 실패해도 수집을 멈추지 않는다. 경고를 남기고 메타에 적재해
                # 수집 종료 후 한 번에 확인할 수 있게 한다.
                meta = dict(self._last_source_meta)
                expected = str(row.get("expected_name_kr", "") or "").strip()
                warnings: List[str] = []
                if meta.get("dim_warning"):
                    warnings.append(meta["dim_warning"])
                # 통계표명까지 대조 대상에 넣는다. '총지수' 같은 항목명은 그것만으로
                # CPI/PPI/수출/수입 표를 구분하지 못한다 (audit_mapping 과 동일 규칙).
                name_warn = check_item_name(
                    series_name, expected,
                    f"{meta.get('stat_name', '')} {meta.get('item_names', '')}")
                if name_warn:
                    warnings.append(name_warn)
                    LOGGER.warning("★ %s", name_warn)
                elif not expected:
                    LOGGER.warning(
                        "★ 항목명 미검증: %s — indicators.csv 에 "
                        "expected_name_kr 를 채울 것", series_name)
                # 공표 지연 관측 — 그룹 배정이 실제 공표 시점을 감당하는지 매 수집마다 다시 잰다.
                grp = _group_of(series_name)
                lag, lag_warn = check_publication_lag(
                    series_name, df["date"] if "date" in df.columns else pd.Series(dtype="datetime64[ns]"),
                    grp, requested_end=end_date)
                if lag_warn:
                    warnings.append(lag_warn)
                    LOGGER.warning("★ %s", lag_warn)
                value_cols = [c for c in df.columns if c != "date"]
                if value_cols:
                    range_warn = check_value_range(series_name, df[value_cols[0]])
                    if range_warn:
                        warnings.append(range_warn)
                        LOGGER.warning("★ %s", range_warn)
                self.collected_meta[series_name] = {
                    "source": source,
                    "stat_code": str(row.get("stat_code", "") or ""),
                    "item_code1": str(row.get("item_code1", "") or ""),
                    "item_code2": str(row.get("item_code2", "") or ""),
                    "ticker": str(row.get("ticker", "") or ""),
                    "expected_name_kr": expected,
                    "official_stat_name": meta.get("stat_name", ""),
                    "official_item_names": meta.get("item_names", ""),
                    "unit_name": meta.get("unit_name", ""),
                    "dim_warning": meta.get("dim_warning", ""),
                    "shift_group": grp,
                    "publication_lag_months": lag,
                    "n_rows": int(len(df)),
                    "warnings": warnings,
                }

                # --- Save individual raw CSV & merge with existing ---------
                if save_individually:
                    df = self._save_raw_indicator(df, series_name, raw_path)

                # --- Update load state -------------------------------------
                if state_manager is not None and not df.empty:
                    last_date = df["date"].max()
                    state_manager.update(
                        series_name,
                        last_date.strftime("%Y-%m-%d")
                        if hasattr(last_date, "strftime")
                        else str(last_date),
                    )

                collected_frames.append(df)

            except Exception as exc:
                LOGGER.exception(
                    "Failed to collect indicator: %s (%s)", series_name, exc,
                )

            finally:
                time.sleep(self.config.sleep_seconds)

        # Persist load state at the end of the run
        if state_manager is not None:
            state_manager.save()

        self._write_collected_meta(raw_path.parent / "metadata"
                                   if save_individually else None)
        return collected_frames

    def _write_collected_meta(self, meta_dir: Optional[Path]) -> None:
        """수집 시점의 공식 명칭·경고를 메타 JSON 으로 남긴다.

        원시 CSV 에 컬럼으로 넣으면 매 행이 같은 값으로 반복되므로
        지표당 1건인 별도 JSON 에 기록한다.
        """
        flagged = {k: v for k, v in self.collected_meta.items() if v["warnings"]}
        if flagged:
            LOGGER.warning("★ 매핑·값 검증 경고 %d개 지표: %s",
                           len(flagged), ", ".join(sorted(flagged)))
        else:
            LOGGER.info("매핑·값 검증 경고 없음 (%d개 지표)", len(self.collected_meta))
        if meta_dir is None:
            return
        meta_dir.mkdir(parents=True, exist_ok=True)
        path = meta_dir / "collected_series_meta.json"
        payload = {
            "collected_at": pd.Timestamp.now().isoformat(timespec="seconds"),
            "n_series": len(self.collected_meta),
            "n_flagged": len(flagged),
            "series": self.collected_meta,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                        encoding="utf-8")
        LOGGER.info("수집 메타 저장: %s", path)

    # ------------------------------------------------------------------
    # Raw indicator persistence
    # ------------------------------------------------------------------

    @staticmethod
    def _save_raw_indicator(
        new_df: pd.DataFrame, series_name: str, raw_dir: Path,
    ) -> pd.DataFrame:
        """
        Append-or-create a per-indicator CSV under *raw_dir*.

        If the file already exists the new rows are merged (dedup by date,
        keeping the latest value).  Returns the full combined DataFrame.
        """
        file_path = raw_dir / f"{series_name}.csv"

        if file_path.exists():
            existing = pd.read_csv(file_path, parse_dates=["date"])
            combined = pd.concat([existing, new_df], ignore_index=True)
            combined = (
                combined.sort_values("date")
                .drop_duplicates(subset=["date"], keep="last")
                .reset_index(drop=True)
            )
        else:
            combined = new_df.copy()

        combined.to_csv(file_path, index=False, encoding="utf-8-sig")
        LOGGER.info("Saved raw indicator: %s (%d rows)", file_path.name, len(combined))
        return combined

    # ------------------------------------------------------------------
    # Legacy helpers (backward compatibility)
    # ------------------------------------------------------------------

    def merge_to_wide(self, frames: List[pd.DataFrame]) -> pd.DataFrame:
        """Merge list of single-column frames into a wide DataFrame."""
        if not frames:
            return pd.DataFrame(columns=["date"])

        merged = frames[0].copy()
        for frame in frames[1:]:
            merged = merged.merge(frame, on="date", how="outer")

        merged = merged.sort_values("date").reset_index(drop=True)
        merged["date"] = merged["date"].dt.strftime("%Y-%m-%d")
        return merged

    def save_raw_data(
        self, df: pd.DataFrame, output_dir: str | Path = "./output",
    ) -> Path:
        """Save a wide DataFrame to a single CSV (legacy)."""
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        file_name = f"raw_macro_data_{pd.Timestamp.now().strftime('%Y%m%d')}.csv"
        file_path = output_path / file_name

        df.to_csv(file_path, index=False, encoding="utf-8-sig")
        LOGGER.info("Saved raw data: %s", file_path)
        return file_path


def setup_logging(log_dir: str | Path = "./logs") -> None:
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    log_file = Path(log_dir) / f"collector_{pd.Timestamp.now().strftime('%Y%m%d')}.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
