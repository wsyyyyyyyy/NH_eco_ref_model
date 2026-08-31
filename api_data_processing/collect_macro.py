"""
======================================================================
거시 지표 재수집 — model_input_monthly_cleaned.csv 복원
======================================================================
배경
----
`api_data_processing/output/model_input/model_input_monthly_cleaned.csv` 가
레포에 없다. `.gitignore:29` 의 `*.csv` 로 커밋에서 빠졌고, 수집 스크립트 자체가
레포에 존재하지 않는다. 거시 172개 변수의 출처·수집일·산출식이 재현 불가능한
상태이며, 이는 프로젝트 재현성의 중대한 결함이다.
(PENDING_REVALIDATION.md 7~9번)

STAGE 5 는 이 파일 없이 `default_rng(20260829)` 합성 프레임으로 로직만 검증했고,
그 합성값이 `portal_v2.duckdb` 에 그대로 들어가 있다. **학습에 쓰면 안 된다.**

설계
----
2단계로 분리한다. 수집과 변환을 한 함수에 섞으면 재수집할 때마다 변환 로직이
같이 흔들리고, 어느 쪽이 값을 바꿨는지 추적할 수 없다.

  [1단계] collect  : 원시 시계열을 그대로 raw/ 에 저장. 가공하지 않는다.
                     파일명에 수집일을 박고, 출처 메타를 JSON 으로 함께 남긴다.
  [2단계] transform: raw/ 를 읽어 log_ret / vol_m / diff12 / yoy / _ma3m 를 만들고
                     model_input_monthly_cleaned.csv 를 만든다. 네트워크를 타지 않는다.

재수집 명세
----------
`lgbm_12m_model.txt` 의 feature_name() 에서 거시 172개를 뽑아 역파싱한 결과가
`eda_pipeline/output/macro_respec_from_model.json` 에 있다.
  거시 피처 172개 = 원지표 63개 x 변환 2~4종
이 스크립트는 그 JSON 을 읽어 "무엇을 수집해야 하는가" 를 스스로 도출한다.
목록을 여기에 다시 하드코딩하지 않는다.

출처
----
  한국은행 ECOS OpenAPI   https://ecos.bok.or.kr/api/
      금리(기준금리/국고채/회사채/KORIBOR/CD/CP/통안채), 물가(CPI/PPI),
      통화(M1/M2/Lf/본원통화), 국제수지, 가계신용, BSI, CSI
      - 인증키 무료 발급: https://ecos.bok.or.kr/api/#/AuthKeyApply
      - 요청 형식: /api/StatisticSearch/{KEY}/json/kr/{시작}/{끝}/{통계표코드}/{주기}/{시작일}/{종료일}/{항목코드}
      - ※ 통계표코드/항목코드는 반드시 통계목록 API(StatisticTableList / StatisticItemList)로
        조회해 확인할 것. 이 파일에 추측값을 적어 두지 않는다. 아래 SPEC 참조.
  yfinance                https://pypi.org/project/yfinance/
      주가지수(KOSPI/KOSDAQ/DowJones/NASDAQ/SP500/Nikkei225/Shanghai),
      환율(USD/EUR/JPY/CNY KRW), 원자재(WTI/Brent/gold/silver/copper/corn/soybean/
      natural_gas), VIX, DXY

미해결
------
  - `credit_spread` / `liquidity_spread` 는 원지표가 아니라 파생이다.
    산출식(어느 두 금리의 차인지)이 문서에 남아 있지 않다. 확정 후 SPEC 에 적을 것.
  - `treasury_bond_1y` 와 `treasury_bond_1y_monthly` 가 별도 변수로 존재한다.
    둘의 차이(일별평균 vs 월별)를 확인해야 한다.
  - `current_account` 와 `current_account_quarterly` 도 같다.
  위 3건은 확인 전까지 SPEC 에서 status='UNRESOLVED' 로 둔다.

Usage
-----
    python -m api_data_processing.collect_macro --spec        # 수집 명세만 출력
    python -m api_data_processing.collect_macro --collect     # 1단계 (API 키 필요)
    python -m api_data_processing.collect_macro --transform   # 2단계 (오프라인)
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import numpy as np
import pandas as pd

OUT_DIR = _PROJECT_ROOT / "api_data_processing" / "output" / "model_input"
RAW_DIR = _PROJECT_ROOT / "api_data_processing" / "raw"
RESPEC = _PROJECT_ROOT / "eda_pipeline" / "output" / "macro_respec_from_model.json"

# 패널이 덮는 구간. step6 가 1개월 시차를 적용하므로 한 달 앞에서 시작한다.
PERIOD_START = "202012"
PERIOD_END = "202505"

ECOS_KEY_ENV = "ECOS_API_KEY"

# ── 원지표 -> 출처 매핑 ───────────────────────────────────────────────
# yfinance 티커는 공개된 심볼이므로 여기 적는다.
# ECOS 통계표코드는 추측하지 않는다. 통계목록 API 로 조회해 채운다.
YF_TICKER = {
    "KOSPI": "^KS11", "KOSDAQ": "^KQ11", "DowJones": "^DJI", "NASDAQ": "^IXIC",
    "SP500": "^GSPC", "Nikkei225": "^N225", "Shanghai_Composite": "000001.SS",
    "USD_KRW": "KRW=X", "EUR_KRW": "EURKRW=X", "JPY_KRW": "JPYKRW=X",
    "CNY_KRW": "CNYKRW=X", "DXY_dollar_index": "DX-Y.NYB",
    "brent_crude_oil": "BZ=F", "WTI_crude_oil": "CL=F", "natural_gas": "NG=F",
    "gold": "GC=F", "silver": "SI=F", "copper": "HG=F",
    "corn": "ZC=F", "soybean": "ZS=F", "VIX": "^VIX",
}

# ECOS 로 받아야 하는 원지표. 값은 통계표코드 확인 후 채운다.
ECOS_PENDING = {
    "call_rate_overnight", "call_rate_overnight_brokered", "corporate_bond_3y_AA",
    "KORIBOR_12m", "KORIBOR_3m", "KORIBOR_6m", "treasury_bond_10y",
    "treasury_bond_1y", "treasury_bond_3y", "treasury_bond_5y",
    "US_10Y_treasury", "US_2Y_treasury", "base_rate", "CD_rate_91d",
    "treasury_bond_1y_monthly", "CP_91d", "MSB_91d",
    "CPI_core", "CPI_core_excl_food_energy", "CPI_food_nonalcohol", "PPI_total",
    "housing_price_index", "M1_narrow_money", "M2_broad_money", "Lf_liquidity",
    "monetary_base_sa", "export_index", "import_index", "trade_total",
    "current_account", "goods_balance", "household_credit", "household_loan",
    "current_account_quarterly", "BSI_mfg_biz", "BSI_mfg_export",
    "BSI_mfg_domestic", "BSI_nonmfg_biz", "CSI_composite", "CSI_living_prospect",
}

# 원지표가 아니라 파생. 산출식 미확인.
DERIVED_UNRESOLVED = {"credit_spread", "liquidity_spread"}


# ══════════════════════════════════════════════════════════════════════
# 수집 명세
# ══════════════════════════════════════════════════════════════════════

def load_respec() -> dict:
    if not RESPEC.exists():
        raise FileNotFoundError(
            f"{RESPEC} 없음. 먼저 아래를 실행해 명세를 만들 것:\n"
            f"  lgbm_12m_model.txt 의 feature_name() 역파싱 (STAGE6 preflight 참조)")
    return json.loads(RESPEC.read_text(encoding="utf-8"))


def build_spec() -> pd.DataFrame:
    """역파싱 결과 + 출처 매핑을 합쳐 '무엇을 어디서 받아야 하는가' 표를 만든다."""
    spec = load_respec()
    rows = []
    for base, transforms in spec["base_indicators"].items():
        if base in YF_TICKER:
            source, ref, status = "yfinance", YF_TICKER[base], "READY"
        elif base in DERIVED_UNRESOLVED:
            source, ref, status = "derived", "", "UNRESOLVED"
        elif base in ECOS_PENDING:
            source, ref, status = "ECOS", "", "NEED_STAT_CODE"
        else:
            source, ref, status = "?", "", "UNMAPPED"
        rows.append({"base_indicator": base, "source": source, "ref": ref,
                     "transforms": ",".join(transforms),
                     "n_features": len(transforms), "status": status})
    df = pd.DataFrame(rows).sort_values(["status", "source", "base_indicator"])
    return df.reset_index(drop=True)


# ══════════════════════════════════════════════════════════════════════
# 1단계 — 수집 (원시 그대로 저장)
# ══════════════════════════════════════════════════════════════════════

def collect() -> Path:
    """원시 월별 시계열을 raw/ 에 저장하고 수집 메타를 남긴다."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.date.today().strftime("%Y%m%d")
    spec = build_spec()

    ready = spec[spec["status"] == "READY"]
    blocked = spec[spec["status"] != "READY"]
    if len(blocked):
        print(f"[경고] 출처 미확정 {len(blocked)}개는 이번 수집에서 빠진다:")
        for _, r in blocked.iterrows():
            print(f"    {r['base_indicator']:32s} {r['status']}")

    try:
        import yfinance as yf
    except ImportError:
        raise SystemExit("yfinance 미설치. pip install yfinance")

    frames = {}
    for _, r in ready.iterrows():
        name, ticker = r["base_indicator"], r["ref"]
        print(f"  수집 {name:28s} <- yfinance {ticker}")
        h = yf.Ticker(ticker).history(
            start=f"{PERIOD_START[:4]}-{PERIOD_START[4:]}-01", end="2025-06-30",
            interval="1d", auto_adjust=False)
        if h.empty:
            print(f"    ! 빈 응답 — 건너뜀")
            continue
        # 원시 일별을 그대로 남긴다. 월별 집계는 2단계에서 한다.
        h.index = pd.to_datetime(h.index).tz_localize(None)
        frames[name] = h["Close"]

    if not frames:
        raise SystemExit("수집된 시계열이 없다.")

    raw = pd.DataFrame(frames)
    raw_path = RAW_DIR / f"macro_raw_daily_{stamp}.csv"
    raw.to_csv(raw_path, encoding="utf-8-sig")

    meta = {
        "collected_at": dt.datetime.now().isoformat(timespec="seconds"),
        "period": {"start": PERIOD_START, "end": PERIOD_END},
        "sources": {"yfinance": "https://pypi.org/project/yfinance/",
                    "ECOS": "https://ecos.bok.or.kr/api/"},
        "collected_indicators": sorted(frames),
        "missing_indicators": blocked.set_index("base_indicator")["status"].to_dict(),
        "ecos_key_present": bool(os.environ.get(ECOS_KEY_ENV)),
        "note": "원시 일별 종가. 가공하지 않았다. 변환은 transform() 단계에서 한다.",
    }
    (RAW_DIR / f"macro_raw_meta_{stamp}.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n저장: {raw_path.name}  ({raw.shape[0]:,}행 x {raw.shape[1]}개 지표)")
    print(f"메타: macro_raw_meta_{stamp}.json")
    return raw_path


# ══════════════════════════════════════════════════════════════════════
# 2단계 — 변환 (네트워크 없음)
# ══════════════════════════════════════════════════════════════════════

def _monthly_close(daily: pd.DataFrame) -> pd.DataFrame:
    m = daily.resample("ME").last()
    m.index = m.index.strftime("%Y%m")
    return m


def _monthly_vol(daily: pd.DataFrame) -> pd.DataFrame:
    """월내 일별 로그수익률의 표준편차."""
    lr = np.log(daily / daily.shift(1))
    v = lr.resample("ME").std()
    v.index = v.index.strftime("%Y%m")
    return v


def transform(raw_path: Path | None = None) -> Path:
    """raw/ 의 원시 시계열 -> model_input_monthly_cleaned.csv

    변환 정의 (변수명 접미사와 1:1 대응):
      _log_ret : 월말 종가의 전월 대비 로그수익률
      _vol_m   : 월내 일별 로그수익률의 표준편차
      _diff12  : 12개월 차분 (금리·스프레드용. 수준 변수라 차분한다)
      _yoy     : 전년 동월 대비 증가율
      _ma3m    : 위 값의 3개월 이동평균
    """
    if raw_path is None:
        cands = sorted(RAW_DIR.glob("macro_raw_daily_*.csv"))
        if not cands:
            raise FileNotFoundError(f"{RAW_DIR} 에 macro_raw_daily_*.csv 가 없다. --collect 먼저.")
        raw_path = cands[-1]

    daily = pd.read_csv(raw_path, index_col=0, parse_dates=True, encoding="utf-8-sig")
    spec = load_respec()

    close = _monthly_close(daily)
    vol = _monthly_vol(daily)

    out = pd.DataFrame(index=close.index)
    for base, transforms in spec["base_indicators"].items():
        if base not in close.columns:
            continue
        s = close[base]
        built = {}
        if "log_ret" in transforms:
            built["log_ret"] = np.log(s / s.shift(1))
        if "vol_m" in transforms and base in vol.columns:
            built["vol_m"] = vol[base]
        if "diff12" in transforms:
            built["diff12"] = s - s.shift(12)
        if "yoy" in transforms:
            built["yoy"] = s / s.shift(12) - 1.0
        for t, v in built.items():
            out[f"{base}_{t}"] = v
            if f"{t}_ma3m" in transforms:
                out[f"{base}_{t}_ma3m"] = v.rolling(3).mean()

    out = out.loc[(out.index >= PERIOD_START) & (out.index <= PERIOD_END)]
    out.index.name = "BASE_YM"
    out = out.reset_index()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    dst = OUT_DIR / "model_input_monthly_cleaned.csv"
    if dst.exists():
        bak = dst.with_name(f"{dst.stem}_{dt.datetime.now():%Y%m%d_%H%M%S}.csv")
        dst.rename(bak)
        print(f"기존 파일을 삭제하지 않고 옮김 -> {bak.name}")
    out.to_csv(dst, index=False, encoding="utf-8-sig")

    want = set(spec["macro_features_full"])
    got = set(out.columns) - {"BASE_YM"}
    print(f"\n저장: {dst.name}  {out.shape[0]}개월 x {len(got)}개 변수")
    print(f"원본 모델이 요구하는 172개 중 확보 {len(want & got)} / 미확보 {len(want - got)}")
    if want - got:
        print("  미확보 예시:", sorted(want - got)[:10])
    return dst


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", action="store_true", help="수집 명세만 출력")
    ap.add_argument("--collect", action="store_true", help="1단계: 원시 수집")
    ap.add_argument("--transform", action="store_true", help="2단계: 변환")
    a = ap.parse_args()

    if a.spec or not (a.collect or a.transform):
        df = build_spec()
        print(df.to_string(index=False))
        print(f"\n원지표 {len(df)}개 -> 거시 피처 {int(df['n_features'].sum())}개")
        print(df["status"].value_counts().to_string())
        return
    if a.collect:
        collect()
    if a.transform:
        transform()


if __name__ == "__main__":
    main()
