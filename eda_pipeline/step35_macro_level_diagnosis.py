"""
======================================================================
E0 — 거시 '수준(level)' 진단
======================================================================
배경: D축 결과(D_AXIS_RESULT.md §5)에서 거시 **차분** 지표의 부호가 Train 과
      Valid 사이에서 뒤집혔다 (base_rate_diff12: Train +0.904 / Valid −0.909).
      차분은 "금리가 오르고 있는가"를 재는데, 부도는 "금리가 높은 상태가
      얼마나 오래 지속됐는가"에 반응한다는 가설이 남았다.
      이 스크립트는 그 가설을 **부호 안정성**만으로 사전 점검한다.

  E0-1  수준(level) vs 차분(diff/yoy) 의 부호 비교
  E0-2  누적 변수 시제품 3종의 부호 확인
  E0-3  Train 내부 안정성 검사 — **Valid 미사용**

★ E0-3 이 이후 변수 선별의 유일한 근거다.
  E0-1 / E0-2 의 Valid 컬럼은 '무슨 일이 벌어졌는지' 를 기록하기 위한 것이며,
  변수 선별에 쓰면 홀드아웃 오염이다. E0-3 함수는 Valid 구간을 아예 읽지
  않도록 분리해 두었다 (train_only_frame).

Usage
-----
    python -m eda_pipeline.step35_macro_level_diagnosis
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import duckdb
import numpy as np
import pandas as pd

from eda_pipeline import config, split_spec

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("E0")

PANEL = config.OUTPUT_DIR / "nh_panel_macro_12m_obv_none_real.parquet"
RAW_MONTHLY = (_PROJECT_ROOT / "api_data_processing" / "output"
               / "model_input" / "model_input_monthly.csv")
CLEANED = config.macro_input_path()

OUT_MD = config.VALIDATION_DIR / "E0_MACRO_LEVEL_DIAGNOSIS.md"
OUT_JSON = config.VALIDATION_DIR / "E0_macro_level_diagnosis.json"

# ── E0-1 대상 ───────────────────────────────────────────────────────
# (컬럼, 설명). 원천 레벨 — model_input_monthly.csv. cleaned 아님.
LEVEL_COLS: list[tuple[str, str]] = [
    ("base_rate",            "기준금리 수준"),
    ("treasury_bond_3y",     "국고채 3년 수준"),
    ("corporate_bond_3y_AA", "회사채 AA 수준"),
    ("credit_spread",        "신용스프레드 수준"),
    ("liquidity_spread",     "유동성스프레드 수준"),
    ("CPI_core",             "물가 수준"),
    ("USD_KRW",              "환율 수준"),
    ("BSI_mfg_biz",          "제조업 BSI 수준"),
]

# 비교 대상 — model_input_monthly_cleaned.csv 의 차분/변화율
DIFF_COLS: list[tuple[str, str]] = [
    ("base_rate_diff12",        "기준금리 12개월 차분"),
    ("credit_spread_diff12",    "신용스프레드 12개월 차분"),
    ("liquidity_spread_diff12", "유동성스프레드 12개월 차분"),
    ("CPI_core_yoy",            "물가 전년동월비"),
    ("USD_KRW_log_ret",         "환율 월간 로그수익률"),
    ("BSI_mfg_biz_yoy",         "제조업 BSI 전년동월비"),
]

# ── E0-2 누적 변수 파라미터 ─────────────────────────────────────────
CUM_WINDOW = 24          # cum_tightening_24m 롤링 창
ABOVE_THRESHOLD = 3.0    # months_above_3pct 임계 (기준금리 %)
AVG_WINDOW = 60          # rate_level_vs_5y_avg 이동평균 창
AVG_MIN_PERIODS = 12     # 원천이 2020-01 부터라 60개월을 못 채운다. 아래 §E0-2 참조

# 파생 스프레드는 원천 레벨 파일에 없다. impute_data.phase0 와 같은 식으로 만든다.
DERIVED_LEVEL = {
    "credit_spread": ("corporate_bond_3y_AA", "treasury_bond_3y"),
    "liquidity_spread": ("CP_91d", "MSB_91d"),
}


# ══════════════════════════════════════════════════════════════════════
# 적재
# ══════════════════════════════════════════════════════════════════════

def default_rate_by_month() -> pd.Series:
    """월별 12개월 선행 부도율(%). D축 §5-1 과 동일한 산출."""
    con = duckdb.connect()
    try:
        q = ('SELECT "BASE_YM","IS_BUDO_12M" FROM read_parquet('
             + "'" + PANEL.as_posix() + "')")
        d = con.execute(q).df()
    finally:
        con.close()
    d["BASE_YM"] = d["BASE_YM"].astype(str)
    return d.groupby("BASE_YM")["IS_BUDO_12M"].mean() * 100


def raw_levels() -> pd.DataFrame:
    """원천 레벨 (model_input_monthly.csv). 공표 시차 미적용 상태다."""
    raw = pd.read_csv(RAW_MONTHLY)
    raw["BASE_YM"] = pd.to_datetime(raw["date"]).dt.strftime("%Y%m")
    raw = raw.sort_values("BASE_YM").set_index("BASE_YM").drop(columns=["date"])
    for name, (a, b) in DERIVED_LEVEL.items():
        if name not in raw.columns and a in raw.columns and b in raw.columns:
            raw[name] = pd.to_numeric(raw[a], errors="coerce") - \
                        pd.to_numeric(raw[b], errors="coerce")
    return raw


def cleaned_diffs() -> pd.DataFrame:
    m = pd.read_csv(CLEANED, dtype={"BASE_YM": str})
    m["BASE_YM"] = m["BASE_YM"].str.strip()
    return m.sort_values("BASE_YM").set_index("BASE_YM")


# ══════════════════════════════════════════════════════════════════════
# E0-2 누적 변수
# ══════════════════════════════════════════════════════════════════════

def build_cumulative(raw: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """누적 변수 시제품 3종.

    전부 base_rate **수준**에서만 만든다. 원천이 2020-01 부터이므로
    warm-up 구간에서 창을 다 못 채운다. 몇 개월이 그런지 함께 반환한다.
    """
    br = pd.to_numeric(raw["base_rate"], errors="coerce")
    out = pd.DataFrame(index=raw.index)

    # (1) 과거 24개월간 '상승분만' 누적
    hike = (br - br.shift(1)).clip(lower=0)
    out["cum_tightening_24m"] = hike.rolling(CUM_WINDOW, min_periods=1).sum()

    # (2) base_rate >= 3.0 이 연속된 개월 수
    flag = br >= ABOVE_THRESHOLD
    grp = (~flag).cumsum()
    out["months_above_3pct"] = flag.groupby(grp).cumsum().astype(float)

    # (3) 수준 − 과거 60개월 이동평균
    ma = br.rolling(AVG_WINDOW, min_periods=AVG_MIN_PERIODS).mean()
    out["rate_level_vs_5y_avg"] = br - ma

    # 창을 실제로 몇 개월 채웠는지 (경고용)
    eff = br.notna().rolling(AVG_WINDOW, min_periods=1).sum()
    meta = {
        "source_first_month": str(raw.index.min()),
        "source_n_months": int(len(raw)),
        "cum_window": CUM_WINDOW,
        "avg_window": AVG_WINDOW,
        "avg_min_periods": AVG_MIN_PERIODS,
        "effective_avg_window": {ym: int(v) for ym, v in eff.items()},
    }
    return out, meta


# ══════════════════════════════════════════════════════════════════════
# 상관
# ══════════════════════════════════════════════════════════════════════

# 상관의 절대값이 이보다 작으면 부호를 신뢰하지 않는다.
# n=17 에서 상관계수의 표준오차가 대략 1/sqrt(n-3) = 0.25 다.
WEAK_ABS = 0.20


def _corr(x: pd.Series, y: pd.Series, idx: list[str]) -> tuple[float, str]:
    """상관과 '왜 못 쟀는지' 를 함께 돌려준다.

    무분산이라 못 잰 것과 부호가 안 맞는 것은 전혀 다른 사건인데,
    NaN 을 그냥 '불일치' 로 흘리면 둘이 섞인다.
    """
    xs = pd.to_numeric(x.reindex(idx), errors="coerce")
    ys = pd.to_numeric(y.reindex(idx), errors="coerce")
    ok = xs.notna() & ys.notna()
    if int(ok.sum()) < 4:
        return float("nan"), f"표본 부족 (n={int(ok.sum())})"
    if xs[ok].nunique() < 2:
        return float("nan"), f"이 구간에서 무분산 (값이 {xs[ok].iloc[0]:g} 하나뿐)"
    if ys[ok].nunique() < 2:
        return float("nan"), "부도율이 무분산"
    return float(np.corrcoef(xs[ok], ys[ok])[0, 1]), ""


def _classify(a: float, b: float, ra: str, rb: str,
              kept: str, broken: str) -> tuple[str, str]:
    """부호 판정을 4단계로 나눈다. '못 쟀다' 와 '안 맞는다' 를 구분한다."""
    if not np.isfinite(a) or not np.isfinite(b):
        return "판정불가", (ra or rb)
    if a * b <= 0:
        return broken, ""
    if min(abs(a), abs(b)) < WEAK_ABS:
        return f"{kept}(약함)", f"한쪽 |r| < {WEAK_ABS} 라 부호의 의미가 약하다"
    return kept, ""


def _cell(v: float, d: int = 3) -> str:
    return "—" if not np.isfinite(v) else f"{v:+.{d}f}"


def _mark(status: str) -> str:
    return status if status in ("유지", "일치") else f"**★ {status}**"


def sign_table(series: dict[str, tuple[pd.Series, str]], rate: pd.Series,
               tr: list[str], va: list[str], allm: list[str]) -> list[dict]:
    rows = []
    for col, (s, desc) in series.items():
        a, ra = _corr(s, rate, tr)
        b, rb = _corr(s, rate, va)
        t, _ = _corr(s, rate, allm)
        n_na = int(pd.to_numeric(s.reindex(allm), errors="coerce").isna().sum())
        status, note = _classify(a, b, ra, rb, "유지", "뒤집힘")
        rows.append({
            "col": col, "desc": desc,
            "train": a, "valid": b, "all": t,
            "status": status, "note": note,
            "sign_kept": status.startswith("유지"),
            "n_missing_in_panel": n_na,
        })
    return rows


def split_table(series: dict[str, tuple[pd.Series, str]], rate: pd.Series,
                first: list[str], second: list[str]) -> list[dict]:
    """E0-3 — Train 을 전반/후반으로 쪼갠 부호 일치 검사. Valid 미사용."""
    rows = []
    for col, (s, desc) in series.items():
        a, ra = _corr(s, rate, first)
        b, rb = _corr(s, rate, second)
        status, note = _classify(a, b, ra, rb, "일치", "불일치")
        rows.append({
            "col": col, "desc": desc,
            "train_first": a, "train_second": b,
            "status": status, "note": note,
            "sign_match": status.startswith("일치"),
            "gap": (abs(a - b) if np.isfinite(a) and np.isfinite(b) else float("nan")),
        })
    return rows


# ══════════════════════════════════════════════════════════════════════

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--panel", default=str(PANEL))
    ap.parse_args()

    rate = default_rate_by_month()
    raw = raw_levels()
    cln = cleaned_diffs()
    cum, cum_meta = build_cumulative(raw)

    months = sorted(rate.index)                       # 패널 53개월
    tr = [m for m in months if m < split_spec.DEV_START]        # 202101~202309
    dv = [m for m in months if split_spec.DEV_START <= m <= split_spec.DEV_END]
    va = [m for m in months if m >= split_spec.VALID_START]     # 202401~202505
    half = len(tr) // 2 + len(tr) % 2                 # 33 -> 전반 17 / 후반 16
    tr1, tr2 = tr[:half], tr[half:]

    log.info("패널 %d개월 / Train %d (전반 %d %s~%s / 후반 %d %s~%s) / Dev %d / Valid %d",
             len(months), len(tr), len(tr1), tr1[0], tr1[-1],
             len(tr2), tr2[0], tr2[-1], len(dv), len(va))

    # ── 계열 사전 ────────────────────────────────────────────────
    lv = {c: (raw[c], d) for c, d in LEVEL_COLS if c in raw.columns}
    df_ = {c: (cln[c], d) for c, d in DIFF_COLS if c in cln.columns}
    cm = {c: (cum[c], d) for c, d in [
        ("cum_tightening_24m", f"과거 {CUM_WINDOW}개월 기준금리 상승분 누적"),
        ("months_above_3pct", f"기준금리 >= {ABOVE_THRESHOLD}% 연속 개월 수"),
        ("rate_level_vs_5y_avg", f"기준금리 − 과거 {AVG_WINDOW}개월 이동평균"),
    ] if c in cum.columns}

    missing_lv = [c for c, _ in LEVEL_COLS if c not in raw.columns]
    if missing_lv:
        log.warning("원천 레벨에 없는 컬럼: %s", missing_lv)

    e01_level = sign_table(lv, rate, tr, va, months)
    e01_diff = sign_table(df_, rate, tr, va, months)
    e02 = sign_table(cm, rate, tr, va, months)
    allser = {**lv, **df_, **cm}
    e03 = split_table(allser, rate, tr1, tr2)

    # ── 콘솔 출력 ────────────────────────────────────────────────
    def show(title, rows, cols):
        print()
        print("=" * 96)
        print(title)
        print("=" * 96)
        print(f"{'지표':26s} {'설명':28s} " + " ".join(f"{c:>10s}" for c in cols[:-1])
              + f" {cols[-1]:>10s}")
        print("-" * 96)
        for r in rows:
            def _f(v):
                return "       —  " if not np.isfinite(v) else f"{v:+10.3f}"
            if "train" in r:
                vals = [_f(r["train"]), _f(r["valid"]), _f(r["all"])]
            else:
                vals = [_f(r["train_first"]), _f(r["train_second"]),
                        ("       —  " if not np.isfinite(r["gap"]) else f"{r['gap']:10.3f}")]
            mark = r["status"]
            if mark in ("뒤집힘", "불일치", "판정불가"):
                mark = "★ " + mark
            print(f"{r['col']:26s} {r['desc']:28s} " + " ".join(vals) + f" {mark:>12s}")
            if r["note"]:
                print(f"{'':26s} {'':28s}   -> {r['note']}")

    show("[E0-1] 수준(level) — 원천 레벨, 공표 시차 미적용", e01_level,
         ["Train", "Valid", "전체", "부호"])
    show("[E0-1] 차분(diff/yoy) — cleaned, 공표 시차 적용됨 (비교 대상)", e01_diff,
         ["Train", "Valid", "전체", "부호"])
    show("[E0-2] 누적 변수 시제품 3종", e02, ["Train", "Valid", "전체", "부호"])
    show(f"[E0-3] Train 내부 안정성 (전반 {len(tr1)}개월 vs 후반 {len(tr2)}개월) "
         f"— Valid 미사용", e03, ["Train전반", "Train후반", "격차", "부호"])

    # ── 마크다운 ─────────────────────────────────────────────────
    eff = cum_meta["effective_avg_window"]
    eff_panel = {m: eff[m] for m in months if m in eff}
    n_short = sum(1 for v in eff_panel.values() if v < AVG_WINDOW)
    n_nan_avg = int(pd.to_numeric(cum["rate_level_vs_5y_avg"].reindex(months),
                                  errors="coerce").isna().sum())

    L: list[str] = []
    w = L.append
    w("# E0 — 거시 '수준(level)' 진단")
    w("")
    w("실행일: 2026-08-31 · 재현: `python -m eda_pipeline.step35_macro_level_diagnosis`")
    w("원자료: `E0_macro_level_diagnosis.json`")
    w(f"대상 기간: 패널 {len(months)}개월 ({months[0]}~{months[-1]})")
    w("")
    w("## 0. 왜 이걸 재는가")
    w("")
    w("D축 결과(`D_AXIS_RESULT.md` §5)에서 거시 **차분** 지표의 부호가 Train 과 Valid")
    w("사이에서 뒤집혔다 (`base_rate_diff12` Train +0.904 / Valid −0.909).")
    w("차분은 \"금리가 **오르고 있는가**\"를 재는데, 부도는 \"금리가 **높은 상태가**")
    w("**얼마나 오래 지속됐는가**\"에 반응한다는 가설이 남았다. 수준·누적 변수의")
    w("부호 안정성만 사전 점검한다. **모델 학습은 하지 않는다.**")
    w("")
    w("### 산출 방식")
    w("")
    w("- 종속 계열: 월별 **12개월 선행 부도율**(%) = `IS_BUDO_12M` 의 `BASE_YM` 별 평균.")
    w("  D축 §5-1 과 동일하다.")
    w(f"- Train = `BASE_YM < {split_spec.DEV_START}` ({len(tr)}개월), "
      f"Valid = `>= {split_spec.VALID_START}` ({len(va)}개월). "
      f"Dev {len(dv)}개월은 양쪽 어디에도 넣지 않았다 (D축 §5-1 과 동일).")
    w("- 상관은 Pearson. 결측은 쌍 단위로 제외한다.")
    w("")
    w("### ★ 읽을 때의 주의 — 수준과 차분은 공표 시차가 다르다")
    w("")
    w("지시대로 수준값은 `model_input_monthly.csv`(원천 레벨)에서 가져왔다. 이 파일은")
    w("**공표 시차가 적용되기 전** 상태다. 반면 비교 대상인 차분 지표는")
    w("`model_input_monthly_cleaned.csv` 라 `impute_data` Phase 1 의 지표군별 시차가")
    w("이미 걸려 있다 (Group A 0개월 / B +1 / C +2). `base_rate` 는 Group C 이므로")
    w("**수준은 차분보다 2개월 앞선 값**이다.")
    w("")
    w("이 진단의 목적은 부호의 **방향**이지 시점 정합이 아니므로 그대로 두었다.")
    w("다만 여기서 고른 변수를 실제 모델에 넣을 때는 **반드시 같은 공표 시차를**")
    w("**적용해야 한다.** 적용하지 않으면 시점 누수다.")
    w("")
    w("---")
    w("")

    # E0-1
    w("## E0-1. 수준 vs 차분 부호 비교")
    w("")
    w("### 수준 (level) — 원천 레벨")
    w("")
    w("| 지표 | 설명 | Train 상관 | Valid 상관 | 전체 | 부호 |")
    w("|---|---|---:|---:|---:|:---:|")
    for r in e01_level:
        w(f"| `{r['col']}` | {r['desc']} | {_cell(r['train'])} | {_cell(r['valid'])} | "
          f"{_cell(r['all'])} | {_mark(r['status'])} |"
          + (f" <!-- {r['note']} -->" if r["note"] else ""))
    w("")
    w("### 차분 (diff / yoy) — cleaned, 비교 대상")
    w("")
    w("| 지표 | 설명 | Train 상관 | Valid 상관 | 전체 | 부호 |")
    w("|---|---|---:|---:|---:|:---:|")
    for r in e01_diff:
        w(f"| `{r['col']}` | {r['desc']} | {_cell(r['train'])} | {_cell(r['valid'])} | "
          f"{_cell(r['all'])} | {_mark(r['status'])} |")
    w("")
    n_lv_ok = sum(r["sign_kept"] for r in e01_level)
    n_df_ok = sum(r["sign_kept"] for r in e01_diff)
    w(f"**요약: 수준 {n_lv_ok}/{len(e01_level)} 부호 유지, "
      f"차분 {n_df_ok}/{len(e01_diff)} 부호 유지.**")
    w("")
    w("---")
    w("")

    # E0-2
    w("## E0-2. 누적 변수 시제품 3종")
    w("")
    w("| 변수 | 정의 |")
    w("|---|---|")
    w(f"| `cum_tightening_24m` | 매월 `max(base_rate_t − base_rate_(t−1), 0)` 을 "
      f"{CUM_WINDOW}개월 롤링 합 |")
    w(f"| `months_above_3pct` | `base_rate >= {ABOVE_THRESHOLD}` 인 상태가 연속된 개월 수 |")
    w(f"| `rate_level_vs_5y_avg` | `base_rate − (과거 {AVG_WINDOW}개월 이동평균)` |")
    w("")
    w("| 지표 | 설명 | Train 상관 | Valid 상관 | 전체 | 부호 |")
    w("|---|---|---:|---:|---:|:---:|")
    for r in e02:
        w(f"| `{r['col']}` | {r['desc']} | {_cell(r['train'])} | {_cell(r['valid'])} | "
          f"{_cell(r['all'])} | {_mark(r['status'])} |")
    w("")
    w("### 창(window) 결측 보고 — 지시하신 확인 사항")
    w("")
    w(f"원천 `model_input_monthly.csv` 는 **{cum_meta['source_first_month']}** 부터 "
      f"{cum_meta['source_n_months']}개월이다. "
      f"{AVG_WINDOW}개월 이동평균은 초기 구간에서 창을 채울 수 없다.")
    w("")
    w(f"- `min_periods = {AVG_MIN_PERIODS}` 로 두었다.")
    w(f"- 패널 {len(months)}개월 중 `rate_level_vs_5y_avg` 가 **결측인 달: "
      f"{n_nan_avg}개월**")
    w(f"- 다만 결측이 아니어도 창을 다 못 채운 달이 있다. "
      f"패널 {len(months)}개월 중 **{n_short}개월**이 {AVG_WINDOW}개월 미만으로 계산됐다.")
    w("")
    w("| BASE_YM | 실제 사용된 개월 수 | | BASE_YM | 실제 사용된 개월 수 |")
    w("|---|---:|---|---|---:|")
    keys = months
    mid = (len(keys) + 1) // 2
    for i in range(mid):
        a = keys[i]
        b = keys[i + mid] if i + mid < len(keys) else None
        left = f"| {a} | {eff_panel.get(a, 0)} |"
        right = (f" | {b} | {eff_panel.get(b, 0)} |" if b else " | | |")
        w(left + right)
    w("")
    w(f"→ **{months[0]} 시점의 `rate_level_vs_5y_avg` 는 5년 평균이 아니라 "
      f"{eff_panel.get(months[0], 0)}개월 평균 대비 편차다.** 초기 구간일수록 "
      f"'장기 평균 대비' 의 의미가 약해진다. 이 변수를 채택한다면 원천을 "
      f"최소 2015년까지 확장해야 정의대로 동작한다.")
    w("")
    w("---")
    w("")

    # E0-3
    w("## E0-3. ★ Train 내부 안정성 검사 — Valid 미사용")
    w("")
    w(f"Train {len(tr)}개월을 전반 {len(tr1)}개월(`{tr1[0]}~{tr1[-1]}`) / "
      f"후반 {len(tr2)}개월(`{tr2[0]}~{tr2[-1]}`)로 쪼갰다.")
    w("")
    w("**이 표가 이후 변수 선별의 유일한 근거다.** Valid 구간은 이 계산에")
    w("들어가지 않는다 (`split_table()` 은 `tr1`, `tr2` 만 받는다).")
    w("")
    w("| 지표 | 설명 | Train전반 상관 | Train후반 상관 | 격차 | 부호 | 비고 |")
    w("|---|---|---:|---:|---:|:---:|---|")
    for r in e03:
        gap = "—" if not np.isfinite(r["gap"]) else f"{r['gap']:.3f}"
        w(f"| `{r['col']}` | {r['desc']} | {_cell(r['train_first'])} | "
          f"{_cell(r['train_second'])} | {gap} | {_mark(r['status'])} | "
          f"{r['note'] or ''} |")
    w("")
    n_strong = sum(1 for r in e03 if r["status"] == "일치")
    n_weak = sum(1 for r in e03 if r["status"] == "일치(약함)")
    n_bad = sum(1 for r in e03 if r["status"] == "불일치")
    n_und = sum(1 for r in e03 if r["status"] == "판정불가")
    w(f"**일치 {n_strong} / 일치(약함) {n_weak} / 불일치 {n_bad} / "
      f"판정불가 {n_und} — 총 {len(e03)}개.**")
    w("")
    w(f"'일치(약함)' 은 부호는 같지만 한쪽 |r| 이 {WEAK_ABS} 미만이라 부호 자체가")
    w("우연일 수 있는 경우다. 선별 근거로 쓰지 않는다.")
    w("")
    w("### 판정 등급")
    w("")
    w("| 등급 | 뜻 |")
    w("|---|---|")
    w("| 일치 | 두 구간 부호가 같고, 양쪽 모두 |r| >= "
      f"{WEAK_ABS} |")
    w("| 일치(약함) | 부호는 같으나 한쪽 |r| < "
      f"{WEAK_ABS} — 부호가 우연일 수 있다 |")
    w("| 불일치 | 두 구간 부호가 다르다 |")
    w("| 판정불가 | 한쪽 구간에서 변수가 무분산이라 상관을 잴 수 없다 |")
    w("")
    w("### 이 표의 한계 — 판단 전에 반드시 감안할 것")
    w("")
    w(f"- 표본이 전반 {len(tr1)}개월 / 후반 {len(tr2)}개월뿐이다. n=17 에서 상관계수의")
    w("  표준오차는 대략 0.25 다. 부호가 같아도 '안정적' 이라고 단정할 수 없고,")
    w("  부호가 달라도 우연일 수 있다.")
    w("- 두 구간은 서로 다른 국면이다. 전반은 저금리·완화 국면,")
    w("  후반은 급격한 긴축 국면이다. 부호 일치는 '두 국면을 모두 통과했다' 는")
    w("  뜻이라 의미가 있지만, 국면이 둘뿐이라 세 번째 국면(완화 전환)에서도")
    w("  유지된다는 보장은 없다. 실제로 Valid 가 그 세 번째 국면이다.")
    w("- 월별 시계열은 자기상관이 강해 유효 표본이 명목 개월 수보다 작다.")
    w("")
    w("→ **이 표는 후보를 좁히는 데만 쓰고, 최종 판정은 별도 홀드아웃으로 한다.**")
    w("")

    # ── 방법 자체의 점검 ────────────────────────────────────────
    w("---")
    w("")
    w("## E0-4. ★ E0-3 이 선별 도구로 작동하는가 — 방법 자체의 점검")
    w("")
    w("**이 절은 변수 선별에 쓰지 않는다.** E0-3(Train 내부 안정성)이 실제로")
    w("'Valid 에서도 부호가 유지될 변수' 를 골라내는지, **선별 도구의 성능**만")
    w("사후 확인한다. 여기 나오는 Valid 결과를 보고 변수를 고르면 그 순간")
    w("홀드아웃 오염이다. Valid 부호는 D축에서 이미 공개된 정보라 새로 열어 본")
    w("것은 없지만, **용도를 구분하지 않으면 같은 잘못이 된다.**")
    w("")
    by_col = {r["col"]: r for r in (e01_level + e01_diff + e02)}
    w("| 지표 | E0-3 (Train 내부) | Valid 실제 | 예측 성공 |")
    w("|---|:---:|:---:|:---:|")
    hit = miss = 0
    for r in e03:
        v = by_col.get(r["col"])
        vs = v["status"] if v else "—"
        if r["status"] == "일치":
            ok = vs.startswith("유지")
            hit += int(ok)
            miss += int(not ok)
            mark = "**O**" if ok else "**X**"
        else:
            mark = "—"
        w(f"| `{r['col']}` | {r['status']} | {vs} | {mark} |")
    w("")
    tot = hit + miss
    w(f"**E0-3 에서 '일치' 로 통과한 {tot}개 중 Valid 에서도 부호가 유지된 것은 "
      f"{hit}개다.**")
    w("")
    if tot:
        surv = [r["col"] for r in e03 if r["status"] == "일치"
                and by_col.get(r["col"], {}).get("status", "").startswith("유지")]
        fell = [r["col"] for r in e03 if r["status"] == "일치"
                and not by_col.get(r["col"], {}).get("status", "").startswith("유지")]
        w(f"- 살아남은 것: {', '.join('`' + c + '`' for c in surv) or '없음'}")
        w(f"- 뒤집힌 것: {', '.join('`' + c + '`' for c in fell) or '없음'}")
        w("")
    w("### 이것이 뜻하는 바")
    w("")
    w("Train 내부에서 두 국면(전반 저금리·완화 / 후반 급긴축)을 모두 통과한 금리")
    w("계열이 세 번째 국면(완화 전환)에서 무너졌다. **Train 내부 안정성은 국면")
    w("전환에 대한 안정성을 보장하지 못한다.** Train 두 구간이 모두 '금리가")
    w("올라가거나 높은' 국면이었기 때문이다 — 서로 다른 구간처럼 보이지만")
    w("부도 대비 금리의 방향은 같았다.")
    w("")
    w("**E0-3 를 단독 선별 기준으로 쓰면 안 된다는 뜻이다.** 통과한 변수 중")
    w("실제로 살아남은 것은 심리지수 계열뿐이고, 그것은 E0-3 를 돌리기 전에")
    w("D축 §5-4 에서 이미 나온 단서다. 즉 E0-3 가 새로 알려 준 것이 없다.")
    w("")

    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text("\n".join(L) + "\n", encoding="utf-8")
    OUT_JSON.write_text(json.dumps({
        "months": months, "train": tr, "train_first": tr1, "train_second": tr2,
        "dev": dv, "valid": va,
        "note_publication_lag": ("수준은 원천 레벨(시차 미적용), 차분은 cleaned"
                                 "(Group A 0 / B +1 / C +2 적용). base_rate 는 Group C."),
        "e0_1_level": e01_level, "e0_1_diff": e01_diff,
        "e0_2_cumulative": e02, "e0_2_meta": cum_meta,
        "e0_3_train_split": e03,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    log.info("저장: %s", OUT_MD)
    log.info("저장: %s", OUT_JSON)


if __name__ == "__main__":
    main()
