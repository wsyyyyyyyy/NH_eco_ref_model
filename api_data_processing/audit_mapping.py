"""
======================================================================
전 소스 매핑 감사 — ECOS / YAHOO / KOSIS
======================================================================
계기: `credit_spread` 음수 사고. 817Y002 국고채 만기가 한 칸씩 밀려 있었다.
      JEMU 라벨 한 칸 밀림에 이은 두 번째 매핑 사고이므로,
      ECOS 뿐 아니라 **전 소스**에 같은 감사를 적용한다.

  [ECOS]  StatisticItemList API 로 통계표별 항목 명세를 받아
          indicators.csv 의 stat_code / item_code 를 대조한다.
  [YAHOO] chart API 의 meta(shortName/longName/instrumentType) 로
          ticker 가 의도한 지수·상품인지 확인한다.
  [KOSIS] statisticsParameterData.do 응답의 TBL_NM / ITM_NM / C1_NM 으로
          orgId/tblId/itmId 조합을 확인하고,
          전국·총합 필터 적용 전/후 차이를 함께 기록한다.

★ 조회 결과 없이 추정으로 판정하지 않는다. 실패는 실패로 기록한다.
★ API 키는 어떤 경로로도 출력하지 않는다 (URL 도 마스킹).

Usage
-----
    python -m api_data_processing.audit_mapping
    python -m api_data_processing.audit_mapping --use-cache   # ECOS 명세 캐시 재사용
    python -m api_data_processing.audit_mapping --skip-yahoo --skip-kosis
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import pandas as pd
import requests

from api_data_processing.data_collector import DataCollector
from api_data_processing.verify_ecos_items import fetch_item_list

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-5s | %(message)s")
LOGGER = logging.getLogger("audit_mapping")

HERE = Path(__file__).resolve().parent
CONFIG = HERE / "config" / "indicators.csv"
MONTHLY = HERE / "output" / "model_input" / "model_input_monthly.csv"
DAILY = HERE / "output" / "model_input" / "model_input_daily.csv"
ITEM_CACHE = HERE / "output" / "metadata" / "ecos_item_list.csv"
OUT_DIR = _PROJECT_ROOT / "eda_pipeline" / "output" / "validation"
OUT_MD = OUT_DIR / "ECOS_MAPPING_AUDIT.md"
OUT_JSON = OUT_DIR / "ecos_mapping_audit.json"


# ══════════════════════════════════════════════════════════════════════
# 지표 유형 — 값 범위 상식 검증에 쓴다
# ══════════════════════════════════════════════════════════════════════
# RATE   금리(%)      기대 0~10
# BSI    확산지수      기대 50~150 (불황기 50 하회 가능하므로 20~200 을 '경고' 하한으로 둔다)
# INDEX  지수         기준연도 100 근처에서 출발해야 한다
# MONEY  통화량/잔액   단위 일관성 (십억원 기준 1e5~1e7)
# FX     환율
# PRICE  주가·원자재   범위 규칙 없음, 부호만 양수
# PCT    증감률(%)    -30~30
# COUNT  건수/호수
TYPES = {
    # ── ECOS 금리 ──
    "base_rate": "RATE", "call_rate_overnight": "RATE",
    "call_rate_overnight_brokered": "RATE", "treasury_bond_1y": "RATE",
    "treasury_bond_3y": "RATE", "treasury_bond_5y": "RATE",
    "treasury_bond_10y": "RATE", "corporate_bond_3y_AA": "RATE",
    "KORIBOR_3m": "RATE", "KORIBOR_6m": "RATE", "KORIBOR_12m": "RATE",
    "CD_rate_91d": "RATE", "treasury_bond_1y_monthly": "RATE",
    "CP_91d": "RATE", "MSB_91d": "RATE",
    "household_credit": "MONEY", "household_loan": "MONEY",
    # ── ECOS 통화량 ──
    "M2_broad_money": "MONEY", "M1_narrow_money": "MONEY",
    "Lf_liquidity": "MONEY", "monetary_base_sa": "MONEY",
    # ── ECOS 물가/지수 ──
    "PPI_total": "INDEX", "CPI_core": "INDEX",
    "CPI_core_excl_food_energy": "INDEX", "CPI_food_nonalcohol": "INDEX",
    "housing_price_index": "INDEX", "export_price_index_KOR": "INDEX",
    "export_index": "INDEX", "import_index": "INDEX", "trade_total": "INDEX",
    "manufacturing_index": "INDEX",
    # ── ECOS 국제수지 ──
    "current_account": "MONEY", "current_account_quarterly": "MONEY",
    "goods_balance": "MONEY",
    # ── ECOS 심리지수 ──
    "BSI_mfg_biz": "BSI", "BSI_mfg_export": "BSI", "BSI_mfg_domestic": "BSI",
    "BSI_nonmfg_biz": "BSI", "CSI_composite": "BSI", "CSI_living_prospect": "BSI",
    # ── ECOS 국민소득 (enabled=N) ──
    "GNI_annual": "MONEY", "GNI_nominal": "MONEY", "GNI_per_capita": "MONEY",
    # ── 환율 ──
    "CNY_KRW": "FX", "USD_KRW": "FX", "JPY_KRW": "FX", "EUR_KRW": "FX",
    "DXY_dollar_index": "PRICE",
    # ── YAHOO 주가/원자재 ──
    "KOSPI": "PRICE", "KOSDAQ": "PRICE", "SP500": "PRICE", "NASDAQ": "PRICE",
    "DowJones": "PRICE", "Nikkei225": "PRICE", "Shanghai_Composite": "PRICE",
    "VIX": "PRICE", "WTI_crude_oil": "PRICE", "brent_crude_oil": "PRICE",
    "gold": "PRICE", "silver": "PRICE", "copper": "PRICE",
    "natural_gas": "PRICE", "soybean": "PRICE", "corn": "PRICE",
    "US_10Y_treasury": "RATE", "US_3M_tbill": "RATE",
    # ── KOSIS ──
    "unemployment_rate": "PCT", "construction_cost_index": "INDEX",
    "unsold_housing": "COUNT",
}

# YAHOO ticker 가 무엇이어야 하는지에 대한 기대 (공식 명칭 키워드)
YAHOO_EXPECT = {
    "KOSPI": "KOSPI Composite", "KOSDAQ": "KOSDAQ Composite",
    "USD_KRW": "USD/KRW", "JPY_KRW": "JPY/KRW", "EUR_KRW": "EUR/KRW",
    "WTI_crude_oil": "Crude Oil (WTI)", "brent_crude_oil": "Brent Crude Oil",
    "gold": "Gold", "silver": "Silver", "copper": "Copper",
    "US_10Y_treasury": "CBOE 10-Year Treasury Note Yield",
    "US_3M_tbill": "13 WEEK TREASURY BILL",
    "SP500": "S&P 500", "NASDAQ": "NASDAQ Composite",
    "DowJones": "Dow Jones Industrial Average", "VIX": "CBOE Volatility Index",
    "DXY_dollar_index": "US Dollar Index", "Nikkei225": "Nikkei 225",
    "Shanghai_Composite": "SSE Composite Index", "natural_gas": "Natural Gas",
    "soybean": "Soybean", "corn": "Corn",
}


#: 정정 확정표 — series: (stat_code, item_code1, item_code2, ITEM_NAME, 비고)
#: 빈 stat_code 는 '정정하지 않는다' 는 뜻이다 ((d) 유형 및 enabled=N).
FIX_TABLE = {
    'treasury_bond_1y': ('817Y002', '010190000', '', '국고채(1년)', ''),
    'treasury_bond_3y': ('817Y002', '010200000', '', '국고채(3년)', ''),
    'treasury_bond_10y': ('817Y002', '010210000', '', '국고채(10년)', ''),
    'corporate_bond_3y_AA': ('817Y002', '010300000', '', '회사채(3년, AA-)', ''),
    'CD_rate_91d': ('721Y001', '2010000', '', 'CD(91일)', '시장금리(월) 표. frequency=M 유지. 일별이 필요하면 817Y002/010502000'),
    'treasury_bond_1y_monthly': ('721Y001', '5030000', '', '국고채(1년)', '조회 확인. 연%, 월'),
    'M2_broad_money': ('161Y005', 'BBHS00', '', 'M2(평잔,계절조정계열)', '십억원, 월'),
    'M1_narrow_money': ('161Y001', 'BBLS00', '', 'M1 (평잔, 계절조정계열)', '십억원, 월'),
    'Lf_liquidity': ('171Y003', 'LAS0000', '', 'Lf(금융기관유동성) : 상품별(평잔, 계절조정계열)', '십억원, 월'),
    'PPI_total': ('404Y014', '*AA', '', '총지수', '생산자물가지수(기본분류), 2020=100'),
    'CPI_core': ('901Y010', 'QB', '', '농산물및석유류제외지수', '소비자물가지수(특수분류), 2020=100'),
    'CPI_core_excl_food_energy': ('901Y010', 'DB', '', '식료품 및 에너지제외 지수', '소비자물가지수(특수분류), 2020=100'),
    'CPI_food_nonalcohol': ('901Y009', 'A', '', '식료품 및 비주류음료', '소비자물가지수, 2020=100'),
    'housing_price_index': ('901Y062', 'P63A', '', '총지수', '주택매매가격지수(KB), 2026.01=100'),
    'export_price_index_KOR': ('402Y014', '*AA', 'W', '총지수 / 원화기준', '수출물가지수(기본분류), 2020=100. frequency A→M. Group2(통화계약구분) D/W/C 중 W=원화기준 지정 — 미지정 시 3계열 혼입'),
    'current_account': ('301Y013', '000000', '', '경상수지', '백만달러'),
    'current_account_quarterly': ('301Y013', '000000', '', '경상수지', '백만달러'),
    'goods_balance': ('301Y013', '100000', '', '상품수지', '백만달러'),
    'export_index': ('403Y001', '*AA', '', '총지수', '수출금액지수, 2020=100'),
    'import_index': ('403Y003', '*AA', '', '총지수', '수입금액지수, 2020=100'),
    'household_credit': ('151Y001', '1000000', '', '가계신용', '십억원, 분기'),
    'household_loan': ('151Y001', '1100000', '', '가계대출', '십억원, 분기'),
    'CNY_KRW': ('731Y003', '0000010', '', '원/위안(종가)', ''),
    'GNI_annual': ('', '', '', '', 'enabled=N. 차원 구조 재설계 필요 — 이번 정정에서 제외, 드롭 유지'),
    'GNI_nominal': ('', '', '', '', 'enabled=N. Group2 를 item_code2 로 옮겨야 한다 — 드롭 유지'),
    'GNI_per_capita': ('', '', '', '', 'enabled=N. Group2 를 item_code2 로 옮겨야 한다 — 드롭 유지'),
    'manufacturing_index': ('', '', '', '', '(x) 의도적 드롭 — DROP_COLS 유지. 정정하지 않는다'),
    'trade_total': ('', '', '', '', 'enabled=N 드롭 — 정정 시 import_index(403Y003/*AA) 와 100% 중복'),
    'US_3M_tbill': ('', '', '', '', '개명으로 해결 — ticker ^IRX 유지, 지표명을 실제 계열(13주 T-bill)에 맞췄다'),
    'construction_cost_index': ('397', 'DT_39701_A003', 'C1=15397AA2AA', '건설공사비지수 총지수(건설)', 'KOSIS 차원 필터 추가'),
}


#: 불일치 유형 분류. (a) 완전 오매핑 / (b) 유사 계열 혼동 /
#: (c) 단위·기준 불일치 / (d) 지표 부재 — (d)는 임의 대체 금지, 별도 승인 대상.
MISMATCH_TYPE = {
    'CD_rate_91d': ('a', '금리 → 기업경기조사(전망) BSI. 통계표 자체가 다르다'),
    'M2_broad_money': ('a', '통화량 → 한국은행 기준금리. base_rate 와 값이 동일한 중복 컬럼'),
    'M1_narrow_money': ('a', '통화량 → 예금은행 총대출금(말잔)'),
    'Lf_liquidity': ('a', '통화량 → 예금은행 원화예금(평잔)'),
    'PPI_total': ('a', '생산자물가 → 소비자물가 총지수. 다른 통계표'),
    'CPI_core': ('a', '근원 CPI → 주택매매가격지수(KB) 총지수'),
    'CPI_core_excl_food_energy': ('a', '근원 CPI → 주택매매가격지수(KB) 아파트(서울)'),
    'CPI_food_nonalcohol': ('a', '식료품·비주류음료(포함) → 식료품 및 에너지제외(제외). 개념이 정반대'),
    'housing_price_index': ('a', '주택매매가격 총지수 → 주택전세가격 단독주택'),
    'export_price_index_KOR': ('a', '수출물가지수 → 주요국 경제성장률(%). 지수가 아니다'),
    'export_index': ('a', '수출금액지수 → 수입금액지수 곡류. 방향과 품목이 모두 다르다'),
    'corporate_bond_3y_AA': ('a', '회사채(신용물) → 국고채(무위험물)'),
    'treasury_bond_1y_monthly': ('a', '국고채 1년(월) → 무담보콜금리(1일)'),
    'goods_balance': ('a', '상품수지 → 운송수지'),
    'household_credit': ('a', '가계신용 잔액(십억원) → 예금은행 대출평균 금리(%)'),
    'household_loan': ('a', '가계대출 잔액(십억원) → 예금은행 기업대출 금리(%)'),
    'GNI_annual': ('x', "Group2(계정항목) 미지정. Group1 구분코드 '한국' 만 지정된 구조 오류"),
    'GNI_nominal': ('x', 'Group2 코드를 item_code1(Group1) 자리에 넣은 차원 자리 오류'),
    'GNI_per_capita': ('x', 'Group2 코드를 item_code1(Group1) 자리에 넣은 차원 자리 오류'),
    'treasury_bond_1y': ('b', '같은 1년 만기이나 발행주체가 다르다 (국고채 → 산금채)'),
    'treasury_bond_3y': ('b', '만기 혼동 (3년 → 10년)'),
    'treasury_bond_10y': ('b', '만기 혼동 (10년 → 20년)'),
    'import_index': ('b', '같은 수입금액지수 표 안에서 총지수 → 맥류및잡곡'),
    'current_account': ('b', '경상수지 → 상품수지. 상위 포괄범위가 하위로 좁혀졌다'),
    'current_account_quarterly': ('b', '경상수지 → 상품수지'),
    'construction_cost_index': ('b', '총지수(건설) → 기타건설. 차원 필터 부재로 24개 부문 중 하나가 선택됨'),
    'CNY_KRW': ('c', '같은 환율 계열이나 종가 → 고가. 다른 환율(YAHOO)은 Close 기준이라 정의가 섞인다'),
    'manufacturing_index': ('x', 'impute_data.DROP_COLS 에 유지. 501Y013 은 3차원(업종/연도기준/계정항목) 표인데 item_code1 만 지정해 41개 계열이 섞여 들어왔고, 연간이라 5행뿐이다. 대량 결측 드롭 사유가 여전히 유효하다'),
    'trade_total': ('x', 'enabled=N 확정. 실제 계열은 수입금액지수 총지수이며, import_index 정정 후 완전 중복이 된다'),
    'US_3M_tbill': ('x', '개명 확정 (US_2Y_treasury -> US_3M_tbill). ^IRX 가 13주 T-bill 이 맞고 값 자체는 유효하다'),
}

TYPE_LABEL = {
    'a': '(a) 완전 오매핑',
    'b': '(b) 유사 계열 혼동',
    'c': '(c) 단위·기준 불일치',
    'd': '(d) 지표 부재',
    # (x) 는 매핑 오류이긴 하나 **다른 사유로 이미 드롭이 확정**된 지표다.
    # (d) 미결과 섞으면 남은 결정 건수를 잘못 세게 된다.
    'x': '(x) 의도적 드롭',
}


def render_fix(series_name: str) -> str:
    v = FIX_TABLE.get(series_name)
    if not v:
        return ""
    stat, i1, i2, name, note = v
    if not stat:
        return f"정정 없음 — {note}"
    code = f"{stat} / {i1}" + (f" / {i2}" if i2 else "")
    return f"{code}  {name}" + (f"  ({note})" if note else "")


def _norm(x: str) -> str:
    return "".join(str(x).split()).lower()


def match_expected(expected: str, haystack: str) -> bool:
    """expected_name_kr 은 `|` 로 나눈 키워드 목록이다. **전부** 포함되어야 일치다.

    통계표명까지 걸러야 하므로 haystack 에는 STAT_NAME 과 ITEM_NAME 을 함께 넣는다.
    901Y009 처럼 '총지수' 항목명만 보면 CPI 와 PPI 를 구분할 수 없기 때문이다.
    """
    h = _norm(haystack)
    parts = [q for q in (expected or "").split("|") if q.strip()]
    return bool(parts) and all(_norm(q) in h for q in parts)


def mask(url: str, key: str) -> str:
    return url.replace(key, "<API_KEY>") if key else url


def load_cfg() -> pd.DataFrame:
    cfg = pd.read_csv(CONFIG, dtype=str, comment="#").fillna("")
    cfg.columns = [c.strip() for c in cfg.columns]
    for c in cfg.columns:
        cfg[c] = cfg[c].astype(str).str.strip()
    return cfg[cfg["series_name"] != ""]


def load_values() -> dict[str, pd.Series]:
    """series_name -> 관측 시계열. 월별을 우선하고 없으면 일별을 쓴다."""
    out: dict[str, pd.Series] = {}
    for path in (DAILY, MONTHLY):
        if not path.exists():
            continue
        df = pd.read_csv(path)
        for c in df.columns:
            if c == "date":
                continue
            s = pd.to_numeric(df[c], errors="coerce").dropna()
            if len(s):
                out[c] = s          # 월별이 나중에 덮어쓴다
    return out


# ══════════════════════════════════════════════════════════════════════
# 값 범위 상식 검증
# ══════════════════════════════════════════════════════════════════════

def range_check(name: str, s: pd.Series | None) -> tuple[str, str]:
    typ = TYPES.get(name, "")
    if s is None or not len(s):
        return "미검증", "산출물에 값 없음"
    lo, hi, first = float(s.min()), float(s.max()), float(s.iloc[0])
    if typ == "RATE":
        ok = -1.0 <= lo and hi <= 10.0
        return ("정상" if ok else "범위이상"), f"금리 0~10% 기대 / 실측 {lo:.3f}~{hi:.3f}"
    if typ == "BSI":
        ok = 20.0 <= lo and hi <= 200.0
        near = 50.0 <= lo and hi <= 150.0
        note = f"BSI 50~150 기대 / 실측 {lo:.1f}~{hi:.1f}"
        return ("정상" if near else ("경고" if ok else "범위이상")), note
    if typ == "INDEX":
        ok = 50.0 <= first <= 200.0 and lo > 0
        return ("정상" if ok else "범위이상"), \
               f"지수 기준연도 100 근처 출발 기대 / 시작 {first:.2f}, 실측 {lo:.4g}~{hi:.4g}"
    if typ == "MONEY":
        # 십억원 단위 통화·잔액이면 1e5~1e7 (100조~1경) 대. 백만달러 국제수지는 별도.
        note = f"단위 일관성 확인 / 실측 {lo:.4g}~{hi:.4g}"
        if 1e5 <= abs(hi) <= 1e7:
            return "정상", note + " (십억원 규모)"
        if abs(hi) < 100:
            return "범위이상", note + " (금리·비율 규모 — 잔액 아님)"
        return "확인필요", note
    if typ == "PCT":
        ok = -30.0 <= lo and hi <= 30.0
        return ("정상" if ok else "범위이상"), f"증감률 -30~30% 기대 / 실측 {lo:.3f}~{hi:.3f}"
    if typ in ("FX", "PRICE", "COUNT"):
        ok = lo > 0
        return ("정상" if ok else "범위이상"), f"양수 기대 / 실측 {lo:.4g}~{hi:.4g}"
    return "해당없음", f"실측 {lo:.4g}~{hi:.4g}"


# ══════════════════════════════════════════════════════════════════════
# ECOS
# ══════════════════════════════════════════════════════════════════════

def audit_ecos(cfg: pd.DataFrame, vals: dict, use_cache: bool) -> tuple[pd.DataFrame, dict]:
    col = DataCollector()
    if not col.config.ecos_api_key and not use_cache:
        raise RuntimeError("ECOS_API_KEY 가 비어 있다. .env 확인. 추정 판정은 하지 않는다.")

    ecos = cfg[cfg["source"].str.upper() == "ECOS"]
    codes = sorted({c for c in ecos["stat_code"] if c})
    fetch_status: dict[str, str] = {}

    if use_cache and ITEM_CACHE.exists():
        items = pd.read_csv(ITEM_CACHE, dtype=str).fillna("")
        LOGGER.info("ECOS 명세 캐시 사용 (%d행)", len(items))
        for c in codes:
            n = int((items["QUERY_STAT_CODE"] == c).sum())
            fetch_status[c] = f"캐시 {n}행" if n else "캐시에 없음"
    else:
        LOGGER.info("ECOS 통계표 %d개 항목 명세 라이브 조회", len(codes))
        frames = []
        for i, sc in enumerate(codes, 1):
            LOGGER.info("[%d/%d] %s", i, len(codes), sc)
            try:
                df = fetch_item_list(col, sc)
                fetch_status[sc] = f"성공 {len(df)}행"
            except Exception as exc:                              # noqa: BLE001
                LOGGER.error("  실패 %s: %s", sc, exc)
                fetch_status[sc] = f"실패: {exc}"
                df = pd.DataFrame()
            if len(df):
                df["QUERY_STAT_CODE"] = sc
                frames.append(df)
            time.sleep(col.config.sleep_seconds)
        if not frames:
            raise RuntimeError("항목 명세를 하나도 받지 못했다.")
        items = pd.concat(frames, ignore_index=True)
        ITEM_CACHE.parent.mkdir(parents=True, exist_ok=True)
        items.to_csv(ITEM_CACHE, index=False, encoding="utf-8-sig")

    for c in items.columns:
        items[c] = items[c].astype(str).str.strip()

    # stat_code -> 그룹 차원 순서
    grp_order = {sc: sorted(set(g["GRP_CODE"])) for sc, g in items.groupby("QUERY_STAT_CODE")}

    def lookup(stat: str, code: str, dim: int) -> tuple[str, str, str]:
        """(ITEM_NAME, GRP_NAME, UNIT_NAME). item_codeN 은 GroupN 차원에 속한다."""
        if not code:
            return "", "", ""
        t = items[items["QUERY_STAT_CODE"] == stat]
        if t.empty:
            return "<명세 미조회>", "", ""
        m = t[t["ITEM_CODE"] == code]
        gs = grp_order.get(stat, [])
        if dim < len(gs):
            g = m[m["GRP_CODE"] == gs[dim]]
            if not g.empty:
                m = g
        if m.empty:
            return "<명세에 없음>", "", ""
        r = m.iloc[0]
        return r.get("ITEM_NAME", ""), r.get("GRP_NAME", ""), r.get("UNIT_NAME", "")

    stat_name = {sc: sorted(set(g["STAT_NAME"]))[0] for sc, g in items.groupby("QUERY_STAT_CODE")}

    rows = []
    for _, r in ecos.iterrows():
        sn, sc = r["series_name"], r["stat_code"]
        n1, g1, u1 = lookup(sc, r.get("item_code1", ""), 0)
        n2, g2, _ = lookup(sc, r.get("item_code2", ""), 1)
        rng, note = range_check(sn, vals.get(sn))
        exp = r.get("expected_name_kr", "")
        actual_full = n1 + (f" / {n2}" if n2 else "")
        if not exp:
            verdict = "판정보류(expected_name_kr 미기재)"
        elif "<" in n1:
            verdict = "미조회" if "미조회" in n1 else "불일치"
        else:
            hay = f"{stat_name.get(sc, '')} {actual_full} {g1} {g2}"
            verdict = "일치" if match_expected(exp, hay) else "불일치"
        rows.append(dict(
            source="ECOS", series_name=sn, enabled=r.get("enabled", ""),
            freq=r.get("frequency", ""), stat_code=sc,
            stat_name=stat_name.get(sc, "<미조회>"),
            item_code1=r.get("item_code1", ""), item_code2=r.get("item_code2", ""),
            grp1=g1, grp2=g2, item_name=actual_full, unit=u1,
            expected_name_kr=exp, verdict=verdict,
            type=TYPES.get(sn, ""), range_check=rng, range_note=note,
            proposed_fix=render_fix(sn),
            mismatch_type=MISMATCH_TYPE.get(sn, ("", ""))[0],
            mismatch_note=MISMATCH_TYPE.get(sn, ("", ""))[1],
        ))
    return pd.DataFrame(rows), fetch_status


# ══════════════════════════════════════════════════════════════════════
# YAHOO
# ══════════════════════════════════════════════════════════════════════

def audit_yahoo(cfg: pd.DataFrame, vals: dict) -> pd.DataFrame:
    col = DataCollector()
    rows = []
    y = cfg[cfg["source"].str.upper() == "YAHOO"]
    for _, r in y.iterrows():
        sn, tk = r["series_name"], r["ticker"]
        url = DataCollector.YAHOO_CHART_URL.format(ticker=tk)
        meta, err = {}, ""
        try:
            payload = col._request_json(url, params={"range": "5d", "interval": "1d"})
            meta = ((payload.get("chart") or {}).get("result") or [{}])[0].get("meta", {}) or {}
        except Exception as exc:                                  # noqa: BLE001
            err = str(exc)[:120]
        LOGGER.info("YAHOO %-22s %-12s -> %s", sn, tk,
                    meta.get("longName") or meta.get("shortName") or f"실패({err})")
        official = str(meta.get("longName") or meta.get("shortName") or "")
        exp = r.get("expected_name_kr", "") or YAHOO_EXPECT.get(sn, "")
        if err or not official:
            verdict = "미조회"
        elif not exp:
            verdict = "판정보류"
        else:
            verdict = "일치" if match_expected(exp, official) else "불일치"
        rng, note = range_check(sn, vals.get(sn))
        rows.append(dict(
            source="YAHOO", series_name=sn, ticker=tk, field=r.get("field", ""),
            official_name=official or f"<조회실패: {err}>",
            instrument=meta.get("instrumentType", ""), exchange=meta.get("exchangeName", ""),
            currency=meta.get("currency", ""), expected_name_kr=exp, verdict=verdict,
            type=TYPES.get(sn, ""), range_check=rng, range_note=note,
            proposed_fix=render_fix(sn),
            mismatch_type=MISMATCH_TYPE.get(sn, ("", ""))[0],
            mismatch_note=MISMATCH_TYPE.get(sn, ("", ""))[1],
        ))
        time.sleep(0.25)
    return pd.DataFrame(rows)


# ══════════════════════════════════════════════════════════════════════
# KOSIS
# ══════════════════════════════════════════════════════════════════════

KOSIS_URL = "https://kosis.kr/openapi/Param/statisticsParameterData.do"


def audit_kosis(cfg: pd.DataFrame, vals: dict) -> pd.DataFrame:
    from api_data_processing.public_data_collector import PublicDataCollector
    pc = PublicDataCollector()
    key = pc.kosis_api_key
    rows = []

    # public_data_collector.collect 안의 kosis_mapping 을 그대로 재현한다.
    mapping = {
        "unemployment_rate": ("101", "DT_1DA7102S", "T80", {"objL2": "ALL"},
                              [("C1_NM", {"계"}), ("C2_NM", {"계"})]),
        "construction_cost_index": ("397", "DT_39701_A003", "16397AAA0", {},
                                    [("C1_NM", {"건설"})]),
        "unsold_housing": ("116", "DT_MLTM_2080", "ALL",
                           {"objL2": "ALL", "objL3": "ALL"},
                           [("C1_NM", {"전국"}), ("C2_NM", {"총합"}), ("C3_NM", {"총합"})]),
    }
    for _, r in cfg[cfg["source"].str.upper() == "PUBLIC"].iterrows():
        sn = r["series_name"]
        if sn not in mapping:
            rows.append(dict(source="KOSIS", series_name=sn, verdict="미조회",
                             note="public_data_collector 에 매핑 없음"))
            continue
        org, tbl, itm, extra, filters = mapping[sn]
        params = {"method": "getList", "apiKey": key, "itmId": itm, "objL1": "ALL",
                  "format": "json", "jsonVD": "Y", "prdSe": "M",
                  "startPrdDe": "202401", "endPrdDe": "202412",
                  "orgId": org, "tblId": tbl}
        params.update(extra)
        LOGGER.info("KOSIS %-24s org=%s tbl=%s itm=%s", sn, org, tbl, itm)
        try:
            res = requests.get(KOSIS_URL, params=params, timeout=30)
            data = res.json()
        except Exception as exc:                                  # noqa: BLE001
            rows.append(dict(source="KOSIS", series_name=sn, org_id=org, tbl_id=tbl,
                             itm_id=itm, verdict="미조회", note=f"조회 실패: {exc}"))
            continue
        if isinstance(data, dict) and "err" in data:
            rows.append(dict(source="KOSIS", series_name=sn, org_id=org, tbl_id=tbl,
                             itm_id=itm, verdict="미조회",
                             note=f"KOSIS err {data.get('err')}: {data.get('errMsg','')}"))
            continue
        df = pd.DataFrame(data)
        n_raw = len(df)
        tbl_nm = str(df["TBL_NM"].iloc[0]) if "TBL_NM" in df and n_raw else ""
        itm_nm = str(df["ITM_NM"].iloc[0]) if "ITM_NM" in df and n_raw else ""
        unit = str(df["UNIT_NM"].iloc[0]) if "UNIT_NM" in df and n_raw else ""
        # 필터 적용 전/후 비교
        f = df.copy()
        for cname, allow in filters:
            if cname in f.columns:
                f = f[f[cname].isin(allow)]
        dims = {c: sorted(set(df[c].astype(str)))[:8]
                for c in ("C1_NM", "C2_NM", "C3_NM") if c in df.columns}
        v_raw = pd.to_numeric(df.get("DT"), errors="coerce").dropna() if "DT" in df else pd.Series(dtype=float)
        v_flt = pd.to_numeric(f.get("DT"), errors="coerce").dropna() if "DT" in f else pd.Series(dtype=float)
        rng, note = range_check(sn, vals.get(sn))
        exp = r.get("expected_name_kr", "")
        # 차원을 ALL 로 열어 두고 필터를 걸지 않으면 부문별 계열이 섞인 채
        # groupby(date).last() 가 임의의 한 부문을 고른다. 통계표명이 맞아도 값이 틀린다.
        dim_warn = ""
        n_c1 = int(df["C1_NM"].nunique()) if "C1_NM" in df else 0
        if len(f) == n_raw and n_c1 > 1:
            picked = ""
            if {"PRD_DE", "C1_NM"} <= set(f.columns):
                mode = f.groupby("PRD_DE").last()["C1_NM"].mode()
                picked = str(mode.iloc[0]) if len(mode) else "?"
            dim_warn = (f"필터 없음 — C1 {n_c1}개 부문이 섞여 있고 "
                        f"groupby(date).last() 가 [{picked}] 를 고른다")
        if dim_warn:
            verdict = "불일치"
        elif exp:
            verdict = "일치" if match_expected(exp, f"{tbl_nm} {itm_nm}") else "불일치"
        else:
            verdict = "판정보류(expected_name_kr 미기재)"
        rows.append(dict(
            source="KOSIS", series_name=sn, org_id=org, tbl_id=tbl, itm_id=itm,
            tbl_nm=tbl_nm, itm_nm=itm_nm, unit=unit,
            n_rows_raw=n_raw, n_rows_filtered=len(f),
            raw_min=(float(v_raw.min()) if len(v_raw) else None),
            raw_max=(float(v_raw.max()) if len(v_raw) else None),
            flt_min=(float(v_flt.min()) if len(v_flt) else None),
            flt_max=(float(v_flt.max()) if len(v_flt) else None),
            dims=json.dumps(dims, ensure_ascii=False),
            expected_name_kr=exp, dim_warn=dim_warn, verdict=verdict,
            type=TYPES.get(sn, ""), range_check=rng, range_note=note,
            proposed_fix=render_fix(sn),
            mismatch_type=MISMATCH_TYPE.get(sn, ("", ""))[0],
            mismatch_note=MISMATCH_TYPE.get(sn, ("", ""))[1],
        ))
        time.sleep(0.4)
    return pd.DataFrame(rows)


# ══════════════════════════════════════════════════════════════════════

def write_md(ecos: pd.DataFrame, fetch: dict, yh: pd.DataFrame, ks: pd.DataFrame) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    L: list[str] = []
    A = L.append
    ts = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M")
    A("# 전 소스 매핑 감사 — ECOS / YAHOO / KOSIS\n")
    A(f"- 생성: {ts}")
    A("- ECOS: `StatisticItemList` 전 페이지 라이브 조회")
    A("- YAHOO: `chart` API `meta.longName / shortName / instrumentType` 라이브 조회")
    A("- KOSIS: `statisticsParameterData.do` 라이브 조회 (2024년 구간, 필터 전/후 비교)")
    A("- 판정: `indicators.csv` 의 `expected_name_kr`(우리 의도) 대 실제 조회 명칭")
    A("- 조회 실패는 `미조회` 로 기록했고 추정으로 메우지 않았다.\n")

    for src, df in (("ECOS", ecos), ("YAHOO", yh), ("KOSIS", ks)):
        if df is None or df.empty:
            continue
        vc = df["verdict"].value_counts().to_dict()
        A(f"**{src} {len(df)}건** — " + " / ".join(f"{k} {v}" for k, v in vc.items()))
    A("")

    A("## ECOS 통계표 조회 상태\n")
    A("| stat_code | 조회 결과 |")
    A("|---|---|")
    for k in sorted(fetch):
        A(f"| `{k}` | {fetch[k]} |")
    A("")

    A("## ECOS 지표 대조\n")
    A("| series_name | en | stat_code | 통계표명(STAT_NAME) | item | **실제 ITEM_NAME** | expected_name_kr | 판정 | 값범위 |")
    A("|---|---|---|---|---|---|---|---|---|")
    for _, r in ecos.iterrows():
        it = r["item_code1"] + (f" / {r['item_code2']}" if r["item_code2"] else "")
        A(f"| `{r['series_name']}` | {r['enabled']} | `{r['stat_code']}` | {r['stat_name']} "
          f"| `{it}` | **{r['item_name']}** | {r['expected_name_kr'] or '—'} "
          f"| {r['verdict']} | {r['range_check']} |")
    A("")

    bad = ecos[ecos["verdict"].isin(["불일치", "미조회"])]
    A(f"### ECOS 불일치·미조회 {len(bad)}건\n")
    for _, r in bad.iterrows():
        A(f"- `{r['series_name']}` — 의도 **{r['expected_name_kr'] or '(미기재)'}** "
          f"/ 실제 **{r['item_name']}** (`{r['stat_code']}` {r['stat_name']}, `{r['item_code1']}`) "
          f"· {r['range_note']}")
    A("")

    rb = ecos[ecos["range_check"].isin(["범위이상", "경고", "확인필요"])]
    A(f"### ECOS 값 범위 검증 지적 {len(rb)}건\n")
    for _, r in rb.iterrows():
        A(f"- `{r['series_name']}` [{r['type']}] {r['range_check']} — {r['range_note']}")
    A("")

    if yh is not None and not yh.empty:
        A("## YAHOO ticker 대조\n")
        A("| series_name | ticker | **공식 명칭(Yahoo meta)** | 종목유형 | 거래소 | 통화 | 기대 | 판정 | 값범위 |")
        A("|---|---|---|---|---|---|---|---|---|")
        for _, r in yh.iterrows():
            A(f"| `{r['series_name']}` | `{r['ticker']}` | **{r['official_name']}** "
              f"| {r['instrument']} | {r['exchange']} | {r['currency']} "
              f"| {r['expected_name_kr'] or '—'} | {r['verdict']} | {r['range_check']} |")
        A("")
        yb = yh[yh["verdict"].isin(["불일치", "미조회"])]
        A(f"### YAHOO 불일치·미조회 {len(yb)}건\n")
        for _, r in yb.iterrows():
            A(f"- `{r['series_name']}` (`{r['ticker']}`) — 기대 **{r['expected_name_kr']}** "
              f"/ 실제 **{r['official_name']}** · {r['range_note']}")
        A("")

    if ks is not None and not ks.empty:
        A("## KOSIS 통계표 대조\n")
        A("| series_name | orgId/tblId/itmId | **통계표명(TBL_NM)** | 항목(ITM_NM) | 단위 | 필터 전 행 | 필터 후 행 | 필터 전 값 | 필터 후 값 | 판정 |")
        A("|---|---|---|---|---|---|---|---|---|---|")
        for _, r in ks.iterrows():
            def fmt(a, b):
                return "—" if a is None or pd.isna(a) else f"{a:,.4g}~{b:,.4g}"
            A(f"| `{r.get('series_name','')}` | `{r.get('org_id','')}/{r.get('tbl_id','')}/{r.get('itm_id','')}` "
              f"| **{r.get('tbl_nm','')}** | {r.get('itm_nm','')} | {r.get('unit','')} "
              f"| {r.get('n_rows_raw','')} | {r.get('n_rows_filtered','')} "
              f"| {fmt(r.get('raw_min'), r.get('raw_max'))} | {fmt(r.get('flt_min'), r.get('flt_max'))} "
              f"| {r.get('verdict','')} |")
        A("")
        A("### KOSIS 차원 구성 (필터 대상)\n")
        for _, r in ks.iterrows():
            A(f"- `{r.get('series_name','')}` — {r.get('dims','')}")
            if r.get("note"):
                A(f"  - {r['note']}")
        A("")

    A("## 정정 확정표 — 불일치 전건\n")
    A("정정 후 코드는 전부 `StatisticTableList` / `StatisticItemList` 조회로 확인한 값이다.")
    A("`(x) 의도적 드롭` 은 다른 사유로 이미 `enabled=N` 이 확정된 지표다 — **미결이 아니다**.")
    A("`(d) 지표 부재` 는 **임의 대체 금지** 대상이므로 정정하지 않고 별도 승인을 기다린다.\n")
    A("| # | series_name | 기존 stat/item | **기존이 실제로 가리킨 ITEM_NAME** | 정정 후 stat/item | **정정 후 ITEM_NAME** | 불일치 유형 |")
    A("|---:|---|---|---|---|---|---|")
    i = 0
    for df in (ecos, yh, ks):
        if df is None or df.empty:
            continue
        for _, r in df.iterrows():
            if r.get("verdict") != "불일치":
                continue
            i += 1
            sn = r["series_name"]
            if r.get("source") == "KOSIS":
                old = f"{r.get('org_id','')} / {r.get('tbl_id','')} / {r.get('itm_id','')}"
            elif str(r.get("stat_code", "")):
                old = f"{r['stat_code']} / {r.get('item_code1','')}"
                if str(r.get("item_code2", "")):
                    old += f" / {r['item_code2']}"
            else:
                old = f"ticker {r.get('ticker','')}"
            cur = str(r.get("item_name") or r.get("official_name")
                      or f"{r.get('tbl_nm','')} {r.get('itm_nm','')}").strip()
            fx = FIX_TABLE.get(sn, ("", "", "", "", ""))
            newcode = ("`" + fx[0] + " / " + fx[1] + "`" + (" / `" + fx[2] + "`" if fx[2] else "")
                       if fx[0] else "— (정정 없음)")
            newname = fx[3] or fx[4] or "—"
            t = MISMATCH_TYPE.get(sn, ("", ""))
            A(f"| {i} | `{sn}` | `{old}` | **{cur}** | {newcode} | **{newname}** | "
              f"{TYPE_LABEL.get(t[0], t[0])} — {t[1]} |")
    A("")
    counts: dict = {}
    for df in (ecos, yh, ks):
        if df is None or df.empty:
            continue
        for sn2 in df.loc[df["verdict"] == "불일치", "series_name"]:
            k = MISMATCH_TYPE.get(sn2, ("?", ""))[0]
            counts[k] = counts.get(k, 0) + 1
    A("**유형별 집계** — " + " / ".join(
        f"{TYPE_LABEL.get(k, k)} {counts[k]}건" for k in sorted(counts))
      + f"  (합계 {sum(counts.values())}건)")
    A("")
    if ks is not None and not ks.empty and "dim_warn" in ks.columns:
        w = ks[ks["dim_warn"].astype(str) != ""]
        if len(w):
            A("### KOSIS 차원 필터 결함\n")
            for _, r in w.iterrows():
                A(f"- `{r['series_name']}` — {r['dim_warn']}")
            A("")

    OUT_MD.write_text("\n".join(L), encoding="utf-8")
    LOGGER.info("저장: %s", OUT_MD)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--use-cache", action="store_true")
    ap.add_argument("--skip-yahoo", action="store_true")
    ap.add_argument("--skip-kosis", action="store_true")
    a = ap.parse_args()

    cfg = load_cfg()
    vals = load_values()
    ecos, fetch = audit_ecos(cfg, vals, a.use_cache)
    yh = pd.DataFrame() if a.skip_yahoo else audit_yahoo(cfg, vals)
    ks = pd.DataFrame() if a.skip_kosis else audit_kosis(cfg, vals)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, df in (("ecos", ecos), ("yahoo", yh), ("kosis", ks)):
        if len(df):
            df.to_csv(OUT_DIR / f"mapping_audit_{name}.csv", index=False, encoding="utf-8-sig")
    OUT_JSON.write_text(json.dumps({"ecos_fetch_status": fetch}, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    write_md(ecos, fetch, yh, ks)

    for src, df in (("ECOS", ecos), ("YAHOO", yh), ("KOSIS", ks)):
        if len(df):
            print(f"{src}: " + " / ".join(f"{k} {v}" for k, v in
                                          df["verdict"].value_counts().items()))


if __name__ == "__main__":
    main()
