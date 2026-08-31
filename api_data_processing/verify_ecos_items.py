"""
======================================================================
ECOS 항목코드 ↔ 우리 지표명 대조 감사
======================================================================
계기: Phase 6 산출 중 `credit_spread`(= corporate_bond_3y_AA − treasury_bond_3y)가
      77개월 중 68개월에서 **음수**로 나왔다. AA- 회사채가 국고채보다 금리가
      낮을 수 없으므로 항목코드 매핑이 의심된다.

  [확인 1] 817Y002 항목 명세 조회 — 010190000 / 010210000 의 ITEM_NAME
  [확인 2] 값으로 교차 검증 — 2022-10 시장금리, 스프레드 시계열, 미 곡선 상관
  [확인 3] indicators.csv 의 ECOS 전 지표 전수 대조

★ 조회 결과 없이 추정으로 판정하지 않는다. API 실패 시 그 사실을 그대로 보고한다.
★ API 키는 어떤 경로로도 출력하지 않는다 (URL 도 마스킹해서 남긴다).

Usage
-----
    python -m api_data_processing.verify_ecos_items
    python -m api_data_processing.verify_ecos_items --stat 817Y002   # 한 코드만
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import numpy as np
import pandas as pd

# data_collector 는 `from .public_data_collector import ...` 를 쓰므로
# 패키지로 임포트해야 한다 (단독 모듈로 넣으면 relative import 가 깨진다).
from api_data_processing.data_collector import DataCollector as MacroDataCollector

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-5s | %(message)s")
LOGGER = logging.getLogger("ecos_verify")

HERE = Path(__file__).resolve().parent
CONFIG = HERE / "config" / "indicators.csv"
RAW_DIR = HERE / "output" / "raw"
MONTHLY = HERE / "output" / "model_input" / "model_input_monthly.csv"
OUT_DIR = _PROJECT_ROOT / "eda_pipeline" / "output" / "validation"
OUT_MD = OUT_DIR / "ECOS_ITEM_CODE_AUDIT.md"
OUT_CSV = OUT_DIR / "ecos_item_code_audit.csv"
ITEM_CACHE = HERE / "output" / "metadata" / "ecos_item_list.csv"

# 확인 2 — 시장 실측 기준값 (2022-10, 레고랜드 사태 정점)
BENCH_YM = "2022-10"
BENCH = {
    "국고채 3년": 4.2,
    "회사채 AA- 3년": 5.5,
}

# 확인 3 — 값 범위 상식 검증 규칙
#   (판정용 하한, 상한, 설명). 벗어나면 '범위이상' 으로 표시한다.
RATE_LIKE = ("rate", "bond", "KORIBOR", "CD_", "CP_", "MSB", "treasury", "call")
# BSI 는 불황기에 50 아래로 내려간다. 상식 검증이므로 넉넉히 잡는다.
RANGE_RULES: list[tuple[str, tuple[float, float], str]] = [
    ("BSI_", (20, 200), "BSI 지수"),
    ("CSI_", (20, 200), "CSI 지수"),
]


def _mask(url: str, key: str) -> str:
    return url.replace(key, "<API_KEY>") if key else url


PAGE = 500


def fetch_item_list(col: MacroDataCollector, stat_code: str) -> pd.DataFrame:
    """ECOS StatisticItemList — 통계표의 항목 목록. **전 페이지를 받는다.**

    초판은 1~500 만 받아서 301Y013 / 403Y003 / 901Y009 가 잘렸다.
    잘린 목록으로 '명세에 없음' 을 판정하면 오탐이 난다.
    """
    key = col.config.ecos_api_key
    rows: list[dict] = []
    start = 1
    while True:
        end = start + PAGE - 1
        url = (f"{col.ECOS_BASE_URL}/StatisticItemList/{key}/json/kr/"
               f"{start}/{end}/{stat_code}")
        if start == 1:
            LOGGER.info("  조회: %s", _mask(url, key))
        payload = col._request_json(url)
        k = next((x for x in payload if x.lower() == "statisticitemlist"), None)
        if not k:
            LOGGER.warning("  응답에 StatisticItemList 없음: %s", list(payload)[:3])
            break
        block = payload[k]
        cur = block.get("row", []) or []
        rows.extend(cur)
        total = int(block.get("list_total_count", len(rows)))
        if not cur or len(rows) >= total:
            if total > PAGE:
                LOGGER.info("    전체 %d개 항목 수신 (페이지 %d회)",
                            total, (total + PAGE - 1) // PAGE)
            break
        start = end + 1
        time.sleep(col.config.sleep_seconds)
    return pd.DataFrame(rows)


def load_indicator_config() -> pd.DataFrame:
    cfg = pd.read_csv(CONFIG, dtype=str, comment="#").fillna("")
    cfg.columns = [c.strip() for c in cfg.columns]
    for c in cfg.columns:
        cfg[c] = cfg[c].astype(str).str.strip()
    return cfg


def collect_item_lists(cfg: pd.DataFrame, only: str | None = None) -> pd.DataFrame:
    col = MacroDataCollector()
    if not col.config.ecos_api_key:
        raise RuntimeError(
            "ECOS_API_KEY 가 비어 있다. 프로젝트 루트 .env 를 확인할 것.\n"
            "  조회 없이 추정으로 판정하지 않는다 — 여기서 멈춘다.")
    ecos = cfg[cfg["source"].str.upper() == "ECOS"]
    codes = sorted({c for c in ecos["stat_code"] if c})
    if only:
        codes = [c for c in codes if c == only] or [only]
    LOGGER.info("ECOS 통계표 %d개 항목 명세 조회", len(codes))
    frames = []
    for i, sc in enumerate(codes, 1):
        LOGGER.info("[%d/%d] %s", i, len(codes), sc)
        try:
            df = fetch_item_list(col, sc)
        except Exception as exc:                                  # noqa: BLE001
            LOGGER.error("  실패 %s: %s", sc, exc)
            df = pd.DataFrame()
        if len(df):
            df["QUERY_STAT_CODE"] = sc
            frames.append(df)
        time.sleep(col.config.sleep_seconds)
    if not frames:
        raise RuntimeError("항목 명세를 하나도 받지 못했다. 네트워크/키를 확인할 것.")
    out = pd.concat(frames, ignore_index=True)
    ITEM_CACHE.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(ITEM_CACHE, index=False, encoding="utf-8-sig")
    LOGGER.info("항목 명세 저장: %s (%d행)", ITEM_CACHE, len(out))
    return out


def item_name(items: pd.DataFrame, stat: str, code: str,
              grp: str | None = None) -> tuple[str, str, str]:
    """(ITEM_NAME, UNIT_NAME, GRP_NAME). 못 찾으면 ('<명세에 없음>', '', '').

    ECOS 다차원 통계표는 item_code1 이 Group1, item_code2 가 Group2 에 속한다.
    그룹을 무시하고 코드만 맞추면 다른 차원의 동명 코드에 걸린다 — 초판의
    오탐 원인이었다. grp 를 주면 그 그룹 안에서만 찾는다.
    """
    if not code:
        return "", "", ""
    m = items[(items["QUERY_STAT_CODE"] == stat) & (items["ITEM_CODE"] == code)]
    if grp is not None and "GRP_CODE" in m.columns:
        g = m[m["GRP_CODE"] == grp]
        if not g.empty:
            m = g
    if m.empty:
        return "<명세에 없음>", "", ""
    r = m.iloc[0]
    extra = ""
    if len(m) > 1:
        extra = f" [동일코드 {len(m)}건: " +                 ", ".join(sorted(set(m["GRP_NAME"].astype(str))))[:60] + "]"
    return str(r.get("ITEM_NAME", "")) + extra, str(r.get("UNIT_NAME", "")),         str(r.get("GRP_NAME", ""))


# ══════════════════════════════════════════════════════════════════════
# 확인 2 — 값으로 교차 검증
# ══════════════════════════════════════════════════════════════════════

def value_cross_check() -> dict:
    m = pd.read_csv(MONTHLY)
    m["ym"] = pd.to_datetime(m["date"]).dt.strftime("%Y-%m")
    out: dict = {}

    cols = [c for c in ("corporate_bond_3y_AA", "treasury_bond_3y",
                        "CP_91d", "MSB_91d", "base_rate",
                        "US_10Y_treasury", "US_2Y_treasury") if c in m.columns]
    bench = m.loc[m["ym"] == BENCH_YM, ["ym"] + cols]
    out["bench_ym"] = BENCH_YM
    out["bench_row"] = (bench.iloc[0].to_dict() if len(bench) else {})

    if {"corporate_bond_3y_AA", "treasury_bond_3y"} <= set(m.columns):
        sp = m["corporate_bond_3y_AA"] - m["treasury_bond_3y"]
        out["spread"] = {
            "n_months": int(sp.notna().sum()),
            "n_negative": int((sp < 0).sum()),
            "min": float(sp.min()), "median": float(sp.median()), "max": float(sp.max()),
            "at_bench": (float(sp[m["ym"] == BENCH_YM].iloc[0])
                         if (m["ym"] == BENCH_YM).any() else None),
            "by_year": {k: round(float(v), 3) for k, v in
                        sp.groupby(m["ym"].str[:4]).mean().items()},
            "monthly": [{"ym": a, "spread": round(float(b), 4)}
                        for a, b in zip(m["ym"], sp)],
        }
        if {"US_10Y_treasury", "US_2Y_treasury"} <= set(m.columns):
            us = m["US_10Y_treasury"] - m["US_2Y_treasury"]
            ok = sp.notna() & us.notna()
            out["corr_with_us_term_spread"] = float(np.corrcoef(sp[ok], us[ok])[0, 1])
            out["us_term_by_year"] = {k: round(float(v), 3) for k, v in
                                      us.groupby(m["ym"].str[:4]).mean().items()}

    if {"CP_91d", "MSB_91d"} <= set(m.columns):
        lq = m["CP_91d"] - m["MSB_91d"]
        out["liquidity_spread"] = {
            "n_negative": int((lq < 0).sum()), "n_months": int(lq.notna().sum()),
            "min": float(lq.min()), "median": float(lq.median()), "max": float(lq.max()),
            "at_bench": (float(lq[m["ym"] == BENCH_YM].iloc[0])
                         if (m["ym"] == BENCH_YM).any() else None),
        }
    return out


# ══════════════════════════════════════════════════════════════════════
# 확인 3 — 전수 대조
# ══════════════════════════════════════════════════════════════════════

def range_check(series_name: str, s: pd.Series) -> tuple[str, str]:
    s = pd.to_numeric(s, errors="coerce").dropna()
    if s.empty:
        return "확인필요", "값 없음"
    lo, hi = float(s.min()), float(s.max())
    for pre, (a, b), what in RANGE_RULES:
        if series_name.startswith(pre):
            ok = a <= lo and hi <= b
            return ("정상" if ok else "범위이상"), f"{what} 기대 {a}~{b} / 실측 {lo:.2f}~{hi:.2f}"
    if any(k.lower() in series_name.lower() for k in RATE_LIKE):
        ok = -1.0 <= lo and hi <= 10.0
        return ("정상" if ok else "범위이상"), f"금리 기대 0~10% / 실측 {lo:.3f}~{hi:.3f}"
    return "해당없음", f"실측 {lo:.4g}~{hi:.4g}"


def audit_all(cfg: pd.DataFrame, items: pd.DataFrame) -> pd.DataFrame:
    m = pd.read_csv(MONTHLY) if MONTHLY.exists() else pd.DataFrame()
    rows = []
    ecos = cfg[cfg["source"].str.upper() == "ECOS"]
    grp_of = {}
    if "GRP_CODE" in items.columns:
        for sc_, g in items.groupby("QUERY_STAT_CODE"):
            grp_of[sc_] = sorted(set(g["GRP_CODE"].astype(str)))
    for _, r in ecos.iterrows():
        sn, sc = r["series_name"], r["stat_code"]
        ic1, ic2 = r.get("item_code1", ""), r.get("item_code2", "")
        gs = grp_of.get(sc, [])
        nm1, unit, gp1 = item_name(items, sc, ic1, gs[0] if gs else None)
        nm2 = gp2 = ""
        if ic2:
            nm2, _u2, gp2 = item_name(items, sc, ic2, gs[1] if len(gs) > 1 else None)
        rng, rng_note = ("확인필요", "월별 산출물에 없음")
        if sn in m.columns:
            rng, rng_note = range_check(sn, m[sn])
        rows.append(dict(series_name=sn, enabled=r.get("enabled", ""),
                         freq=r.get("frequency", ""), stat_code=sc,
                         item_code1=ic1, GRP1=gp1, ITEM_NAME1=nm1,
                         item_code2=ic2, GRP2=gp2, ITEM_NAME2=nm2,
                         UNIT_NAME=unit, n_groups=len(gs),
                         range_check=rng, range_note=rng_note))
    return pd.DataFrame(rows)


# ══════════════════════════════════════════════════════════════════════

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stat", default=None, help="특정 stat_code 만 조회")
    ap.add_argument("--use-cache", action="store_true",
                    help="이미 받아 둔 ecos_item_list.csv 를 재사용")
    a = ap.parse_args()

    cfg = load_indicator_config()
    if a.use_cache and ITEM_CACHE.exists():
        items = pd.read_csv(ITEM_CACHE, dtype=str).fillna("")
        LOGGER.info("항목 명세 캐시 사용: %s (%d행)", ITEM_CACHE, len(items))
    else:
        items = collect_item_lists(cfg, a.stat)
    for c in ("ITEM_CODE", "ITEM_NAME", "QUERY_STAT_CODE", "UNIT_NAME"):
        if c in items.columns:
            items[c] = items[c].astype(str).str.strip()

    # ── 확인 1 ───────────────────────────────────────────────────
    print()
    print("=" * 100)
    print("[확인 1] 817Y002 항목 명세")
    print("=" * 100)
    t = items[items["QUERY_STAT_CODE"] == "817Y002"]
    if t.empty:
        print("  ★ 817Y002 항목 명세를 받지 못했다. 아래 판정을 진행할 수 없다.")
    else:
        for code in ("010190000", "010210000"):
            nm, unit, gp = item_name(items, "817Y002", code)
            print(f"  {code}  ITEM_NAME = {nm!r}  UNIT = {unit!r}  GRP = {gp!r}")
        print()
        print(f"  {'ITEM_CODE':14s} {'ITEM_NAME':44s} {'CYCLE':6s} {'기간'}")
        print("  " + "-" * 96)
        for _, r in t.iterrows():
            st, en = str(r.get("START_TIME", "")), str(r.get("END_TIME", ""))
            print(f"  {str(r.get('ITEM_CODE','')):14s} "
                  f"{str(r.get('ITEM_NAME','')):44s} "
                  f"{str(r.get('CYCLE','')):6s} {st}~{en}")
        print()
        for kw, label in (("회사채", "회사채 계열"), ("국고채", "국고채 계열")):
            hit = t[t["ITEM_NAME"].str.contains(kw, na=False)]
            print(f"  [{label}] {len(hit)}건")
            for _, r in hit.iterrows():
                print(f"    {r['ITEM_CODE']:14s} {r['ITEM_NAME']}")

    # ── 확인 2 ───────────────────────────────────────────────────
    v = value_cross_check()
    print()
    print("=" * 100)
    print(f"[확인 2] 값 교차 검증 — 기준 시점 {BENCH_YM}")
    print("=" * 100)
    print(f"  시장 실측 기준: 국고채 3년 약 {BENCH['국고채 3년']}%, "
          f"회사채 AA- 3년 약 {BENCH['회사채 AA- 3년']}% (스프레드 130bp 내외)")
    print(f"  수집값: {json.dumps(v.get('bench_row', {}), ensure_ascii=False, default=str)}")
    sp = v.get("spread")
    if sp:
        print()
        print(f"  (corporate_bond_3y_AA − treasury_bond_3y)")
        print(f"    음수 {sp['n_negative']}/{sp['n_months']}개월  "
              f"min {sp['min']:+.3f} / 중앙 {sp['median']:+.3f} / max {sp['max']:+.3f}")
        print(f"    {BENCH_YM} 시점 = {sp['at_bench']:+.3f}")
        print(f"    연평균: " + "  ".join(f"{k} {x:+.3f}" for k, x in sp["by_year"].items()))
    if "corr_with_us_term_spread" in v:
        print()
        print(f"  US_10Y − US_2Y 와의 상관 = {v['corr_with_us_term_spread']:+.3f}")
        print(f"    US 연평균: " + "  ".join(f"{k} {x:+.3f}"
                                             for k, x in v["us_term_by_year"].items()))
    lq = v.get("liquidity_spread")
    if lq:
        print()
        print(f"  (CP_91d − MSB_91d) 음수 {lq['n_negative']}/{lq['n_months']}개월  "
              f"min {lq['min']:+.3f} / 중앙 {lq['median']:+.3f} / max {lq['max']:+.3f}  "
              f"{BENCH_YM}={lq['at_bench']:+.3f}")

    # ── 확인 3 ───────────────────────────────────────────────────
    df = audit_all(cfg, items)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")
    print()
    print("=" * 100)
    print(f"[확인 3] indicators.csv ECOS {len(df)}개 전수 대조")
    print("=" * 100)
    print(f"  {'series_name':28s} {'stat':9s} {'item1':11s} {'ITEM_NAME1':34s} "
          f"{'item2':7s} {'ITEM_NAME2':16s} {'범위'}")
    print("  " + "-" * 120)
    for _, r in df.iterrows():
        print(f"  {r['series_name']:28s} {r['stat_code']:9s} {r['item_code1']:11s} "
              f"{str(r['ITEM_NAME1'])[:34]:34s} {str(r['item_code2']):7s} "
              f"{str(r['ITEM_NAME2'])[:16]:16s} {r['range_check']}")
    bad = df[df["range_check"] == "범위이상"]
    print()
    print(f"  범위이상 {len(bad)}건 / 명세에 없는 항목코드 "
          f"{int((df['ITEM_NAME1'] == '<명세에 없음>').sum())}건")
    for _, r in bad.iterrows():
        print(f"    {r['series_name']:28s} {r['range_note']}")

    (OUT_DIR / "ecos_item_code_audit.json").write_text(
        json.dumps({"value_cross_check": v}, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8")
    print(f"\n저장: {OUT_CSV}")
    print(f"저장: {ITEM_CACHE}")


if __name__ == "__main__":
    main()
