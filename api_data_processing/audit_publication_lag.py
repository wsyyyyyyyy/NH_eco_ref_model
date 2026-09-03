"""
======================================================================
공표 지연 전수 재검사 — 시차 그룹 배정 감사
======================================================================
계기: `check_publication_lag` 의 임계를 `lag > shift + 1` 에서 `lag > shift` 로
      조였다 (2026-09-02). 구 임계는 "경과월이 시차보다 정확히 1개월 큰"
      경계선을 통과시켰고, 그 경계선이 곧 1개월 look-ahead 다.

  임계를 조인 뒤 **전 지표를 다시 재야** 새로 걸리는 것을 알 수 있다.
  이 스크립트는 수집 산출물(`output/`)을 건드리지 않는다. 각 지표의
  **실데이터 최종 수록월만** 조회해 재고, 리포트만 쓴다.

  ★ 측정 방법: `--end-date` 캡 없이 최근 구간을 조회해 최종 수록월을 본다.
    `indicator_metadata.csv` 의 data_end 는 수집 요청 종료일(2026-05-31)에
    묶여 있어 공표 지연 측정에 쓸 수 없다.

  ★ 한계: 하루치 관측이다. 월간 통계는 보통 익월 중순에 나오므로
    **월초에 재면 경과가 1개월 크게 잡힌다.** 이 스크립트는 관측값을
    그대로 기록하고 판단하지 않는다. 시차를 바꾸는 결정은 사람이 한다.

Usage
-----
    python -m api_data_processing.audit_publication_lag
    python -m api_data_processing.audit_publication_lag --as-of 2026-09-01
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import pandas as pd

from api_data_processing import impute_data as imp
from api_data_processing.data_collector import (
    SHIFT_GROUP, DataCollector, _group_of, check_publication_lag,
)
from api_data_processing.public_data_collector import PublicDataCollector

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-5s | %(message)s")
LOGGER = logging.getLogger("lag_audit")

HERE = Path(__file__).resolve().parent
CONFIG = HERE / "config" / "indicators.csv"
OUT_CSV = HERE / "output" / "metadata" / "publication_lag_audit.csv"
OUT_MD = _PROJECT_ROOT / "eda_pipeline" / "output" / "validation" / "PUBLICATION_LAG_AUDIT.md"

PROBE_START = "2025-06-01"      # 최종 수록월만 보면 되므로 짧게 받는다


def probe_last_date(dc: DataCollector, pdc: PublicDataCollector,
                    row: pd.Series, end_date: str
                    ) -> tuple[pd.Timestamp | None, pd.Series, str]:
    """지표 하나의 실데이터 최종 수록일과 **전체 수록일**.

    ★ 전체 수록일을 함께 돌려준다. `check_publication_lag` 이 관측 주기를
      데이터에서 추정하므로(월간/분기 판별) 최종일 하나만 넘기면 주기를 알 수
      없어 분기 계열에 월초 보정이 잘못 적용된다 (2026-09-02 실제로 겪었다).
    """
    src = str(row.get("source", "")).strip().upper()
    name = str(row.get("series_name", "")).strip()
    freq = str(row.get("frequency", "D")).strip() or "D"
    try:
        if src == "ECOS":
            df = dc.fetch_ecos_data(
                stat_code=str(row.get("stat_code", "")).strip(),
                item_code=str(row.get("item_code1", "")).strip(),
                item_code2=str(row.get("item_code2", "")).strip() or None,
                item_code3=str(row.get("item_code3", "")).strip() or None,
                item_code4=str(row.get("item_code4", "")).strip() or None,
                start_date=PROBE_START, end_date=end_date,
                frequency=freq, series_name=name)
        elif src == "YAHOO":
            df = dc.fetch_yahoo_data(
                ticker=str(row.get("ticker", "")).strip(),
                start_date=PROBE_START, end_date=end_date,
                frequency=freq, series_name=name,
                field=str(row.get("field", "Close")).strip() or "Close")
        elif src == "PUBLIC":
            df = pdc.collect(indicator_name=name,
                             start_date=PROBE_START, end_date=end_date)
        else:
            return None, pd.Series(dtype="datetime64[ns]"), f"미지원 source: {src}"
    except Exception as exc:                                      # noqa: BLE001
        return None, pd.Series(dtype="datetime64[ns]"), f"조회 실패: {type(exc).__name__}"
    empty = pd.Series(dtype="datetime64[ns]")
    if df is None or df.empty or "date" not in df.columns:
        return None, empty, "응답 비어 있음"
    d = pd.to_datetime(df["date"], errors="coerce").dropna()
    if d.empty:
        return None, empty, "날짜 파싱 실패"
    return d.max(), d, ""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--as-of", default=None,
                    help="측정 기준일 (기본: 오늘). 기록 재현용")
    ap.add_argument("--only", default=None, help="쉼표로 구분한 series_name 부분집합")
    a = ap.parse_args()

    as_of = pd.Timestamp(a.as_of) if a.as_of else pd.Timestamp.now().normalize()
    cfg = pd.read_csv(CONFIG, dtype=str, comment="#").fillna("")
    cfg = cfg[cfg["enabled"].str.upper().isin(["Y", "YES", "1", "TRUE"])]
    if a.only:
        want = {x.strip() for x in a.only.split(",") if x.strip()}
        cfg = cfg[cfg["series_name"].str.strip().isin(want)]

    dc = DataCollector()
    pdc = PublicDataCollector()

    rows = []
    for i, (_, r) in enumerate(cfg.iterrows(), 1):
        name = str(r["series_name"]).strip()
        grp = _group_of(name)
        shift = SHIFT_GROUP.get(grp)
        dropped = name in imp.DROP_COLS
        last, dates, err = probe_last_date(
            dc, pdc, r, end_date=as_of.strftime("%Y-%m-%d"))
        lag, warn = (None, None)
        if last is not None:
            # 최종일만 넘기면 관측 주기를 알 수 없다. 전체 수록일을 넘긴다.
            lag, warn = check_publication_lag(
                name, dates, grp, requested_end=None, collected_at=as_of)
        rows.append(dict(
            series_name=name, source=str(r["source"]).strip(),
            frequency=str(r["frequency"]).strip(), group=grp or "(미배정)",
            shift=shift if shift is not None else "",
            last_data=last.strftime("%Y-%m") if last is not None else "",
            lag_months=lag if lag is not None else "",
            flagged="Y" if warn else "N", dropped="Y" if dropped else "N",
            note=err or (warn or "")))
        LOGGER.info("[%2d/%2d] %-30s %-3s shift=%-2s 최종 %-8s 경과 %-3s %s",
                    i, len(cfg), name, grp or "-",
                    shift if shift is not None else "-",
                    rows[-1]["last_data"] or "-",
                    rows[-1]["lag_months"] if rows[-1]["lag_months"] != "" else "-",
                    "★걸림" if warn else ("(실패)" if err else "OK"))

    out = pd.DataFrame(rows)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")

    flagged = out[out["flagged"] == "Y"]
    failed = out[out["last_data"] == ""]
    print()
    print("=" * 78)
    print(f"공표 지연 재검사 — 측정일 {as_of:%Y-%m-%d} / 임계 lag > shift")
    print("=" * 78)
    print(f"  대상 {len(out)}개 / 조회 실패 {len(failed)}개 / 걸림 {len(flagged)}개")
    if len(flagged):
        print()
        print(f"  {'series_name':30s} {'그룹':>4s} {'최종':>8s} {'경과':>4s}  비고")
        for _, r in flagged.iterrows():
            tail = "DROP대상" if r["dropped"] == "Y" else ""
            print(f"  {r['series_name']:30s} {r['group']:>4s} {r['last_data']:>8s} "
                  f"{r['lag_months']:>4}  {tail}")
    if len(failed):
        print()
        print("  조회 실패:")
        for _, r in failed.iterrows():
            print(f"    {r['series_name']:30s} {r['note']}")
    print()
    print(f"저장: {OUT_CSV}")

    lines = [f"# 공표 지연 전수 재검사 — 측정일 {as_of:%Y-%m-%d}", "",
             "임계 `lag > shift` (조정 전 `lag > shift + 1`).",
             "`lag` = 측정일과 실데이터 최종 수록월의 개월 차. "
             "`shift` = 시차 그룹의 개월 수 (A=0/B=1/C=2/D=3).", "",
             f"- 대상 {len(out)}개 / 조회 실패 {len(failed)}개 / **걸림 {len(flagged)}개**",
             "", "| series_name | source | freq | 그룹 | shift | 최종 수록월 | 경과 | 판정 |",
             "|---|---|---|---|---:|---|---:|---|"]
    for _, r in out.iterrows():
        if r["flagged"] == "Y":
            verdict = "걸림"
        elif not r["last_data"]:
            verdict = "조회 실패"
        else:
            verdict = "OK"
        if r["dropped"] == "Y":
            verdict += " (DROP_COLS)"
        lag_txt = r["lag_months"] if r["lag_months"] != "" else "—"
        lines.append(f"| `{r['series_name']}` | {r['source']} | {r['frequency']} | "
                     f"{r['group']} | {r['shift']} | {r['last_data'] or '—'} | "
                     f"{lag_txt} | {verdict} |")
    lines += ["", "## 측정 방법과 한계", "",
              "- 각 지표를 `--end-date` 캡 없이 최근 구간만 조회해 "
              "**실데이터 최종 수록월**을 본다.",
              "- `indicator_metadata.csv` 의 `data_end` 는 수집 요청 종료일(2026-05-31)에 "
              "묶여 있어 이 측정에 쓸 수 없다.",
              "- 하루치 관측이다. 월간 통계는 보통 익월 중순 공표이므로 "
              "**월초에 재면 경과가 1개월 크게 잡힌다.**",
              "  측정일이 월초일 때 Group B(+1) 월간 지표가 걸리는 것은 이 효과일 수 있다. "
              "관측값만 기록하고 판단은 사람이 한다.", ""]
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"저장: {OUT_MD}")


if __name__ == "__main__":
    main()
