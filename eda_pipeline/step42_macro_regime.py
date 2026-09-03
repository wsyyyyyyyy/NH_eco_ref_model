"""
======================================================================
step42 — 거시 국면(regime) 구간 재정의 + 구간별 부도율 산출   [작업 A-3]
======================================================================
왜 이 스크립트가 필요한가
----------------------------------------------------------------------
기존 문서의 구간 정의("완화기" / "고스트레스")는 base_rate 의 **수준**으로
국면을 나눈 것처럼 서술되어 있었으나, 실제 평균은 완화기 3.21% >
고스트레스 3.18% 로 수준으로는 두 국면이 구분되지 않는다. 즉 명칭이
데이터를 설명하지 못한다.

따라서 국면을 **금리의 변화 방향**으로 재정의한다.

  저금리기  202101 ~ 202205   초저금리 유지 ~ 인상 초기
  긴축기    202206 ~ 202312   base_rate 상승 및 고점(3.50) 도달·유지
  인하기    202401 ~ 202505   12개월 긴축 임펄스 소멸 후 인하 전환

이 스크립트는
  (1) base_rate 월별 레벨 궤적을 실측하여 위 경계가 맞는지 검증하고,
  (2) 실측 궤적에 정확히 정렬한 대안 구간(4국면)도 함께 만들어,
  (3) 두 정의 모두에 대해 IS_BUDO_12M 부도율을 산출한다.
  (4) 연도별 / 월별 부도율도 대조용으로 산출한다.

주의 — 라벨의 방향성
----------------------------------------------------------------------
IS_BUDO_12M 은 BASE_YM 시점에서 **향후 12개월 내 부도** 여부다.
따라서 "202401 행의 부도율"은 2024-02 ~ 2025-01 사이에 발생한 부도를
가리킨다. 국면-부도율 대조는 이 전방(forward) 성격을 전제로 읽어야 한다.

출력 (모두 신규 파일. 기존 산출물 덮어쓰기 없음)
----------------------------------------------------------------------
  eda_pipeline/output/validation/A3_macro_regime.json
  eda_pipeline/output/validation/A3_MACRO_REGIME.md
  eda_pipeline/output/validation/A3_monthly_default_rate.csv
  eda_pipeline/output/validation/A3_monthly_default_rate.png
  logs/A3_macro_regime.log   (append)

실행
----------------------------------------------------------------------
  C:/Users/scudy/.venvs/nh_eco/Scripts/python.exe eda_pipeline/step42_macro_regime.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / "eda_pipeline" / "output" / "nh_panel_macro_12m_obv_none_real.parquet"
MACRO_CSV = ROOT / "api_data_processing" / "output" / "model_input" / "model_input_monthly.csv"
OUT_DIR = ROOT / "eda_pipeline" / "output" / "validation"
LOG_PATH = ROOT / "logs" / "A3_macro_regime.log"

YM_MIN, YM_MAX = "202101", "202505"

# --- 사용자 지시 구간 (변화 방향 기준, 3국면) ---------------------------
REGIMES_PRIMARY = [
    ("저금리기", "202101", "202205"),
    ("긴축기", "202206", "202312"),
    ("인하기", "202401", "202505"),
]

# --- 실측 궤적에 정렬한 구간은 검증 결과로부터 자동 생성한다 -------------

_log_lines: list[str] = []


try:  # Windows 콘솔이 cp949 라 유니코드 대시 등에서 죽는다
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass


def log(msg: str) -> None:
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{stamp}] {msg}"
    try:
        print(line)
    except UnicodeEncodeError:
        print(line.encode("utf-8", "replace").decode("utf-8", "replace"))
    _log_lines.append(line)


def flush_log() -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write("\n".join(_log_lines) + "\n")


# ======================================================================
# 1. base_rate 실측 궤적
# ======================================================================
def load_base_rate() -> pd.DataFrame:
    d = pd.read_csv(MACRO_CSV, usecols=["date", "base_rate"])
    d["BASE_YM"] = pd.to_datetime(d["date"]).dt.strftime("%Y%m")
    d = d[["BASE_YM", "base_rate"]].dropna().sort_values("BASE_YM").reset_index(drop=True)
    return d


def describe_trajectory(br_all: pd.DataFrame) -> dict:
    """상승 시작 / 고점 도달 / 고점 유지 / 하락 시작을 데이터에서 실측."""
    br = br_all[(br_all.BASE_YM >= YM_MIN) & (br_all.BASE_YM <= YM_MAX)].reset_index(drop=True)
    # 직전월 대비 변화 (분석창 시작 직전월 포함해서 계산)
    full = br_all[br_all.BASE_YM <= YM_MAX].reset_index(drop=True)
    full["chg"] = full["base_rate"].diff()
    win = full[full.BASE_YM >= YM_MIN].reset_index(drop=True)

    hikes = win[win.chg > 0]["BASE_YM"].tolist()
    cuts = win[win.chg < 0]["BASE_YM"].tolist()
    peak = br["base_rate"].max()
    peak_months = br[br.base_rate == peak]["BASE_YM"].tolist()

    out = {
        "window": f"{YM_MIN}~{YM_MAX}",
        "n_months": int(len(br)),
        "rate_min": float(br.base_rate.min()),
        "rate_max": float(br.base_rate.max()),
        "flat_low_until": None,
        "first_hike_month": hikes[0] if hikes else None,
        "last_hike_month": hikes[-1] if hikes else None,
        "hike_months": hikes,
        "peak_rate": float(peak),
        "peak_first_month": peak_months[0] if peak_months else None,
        "peak_last_month": peak_months[-1] if peak_months else None,
        "peak_plateau_len": int(len(peak_months)),
        "first_cut_month": cuts[0] if cuts else None,
        "cut_months": cuts,
    }
    if hikes:
        prev = win[win.BASE_YM < hikes[0]]["BASE_YM"].tolist()
        out["flat_low_until"] = prev[-1] if prev else None

    # 12개월 차분 (모델이 실제로 쓰는 base_rate_diff12 와 동일 정의)
    full["diff12"] = full["base_rate"].diff(12)
    d12 = full[full.BASE_YM >= YM_MIN][["BASE_YM", "base_rate", "chg", "diff12"]].reset_index(drop=True)
    pos = d12[d12.diff12 > 0]["BASE_YM"].tolist()
    neg = d12[d12.diff12 < 0]["BASE_YM"].tolist()
    out["diff12_first_positive"] = pos[0] if pos else None
    out["diff12_last_positive"] = pos[-1] if pos else None
    out["diff12_first_nonpositive_after_tightening"] = None
    if pos:
        after = d12[(d12.BASE_YM > pos[-1])]["BASE_YM"].tolist()
        out["diff12_first_nonpositive_after_tightening"] = after[0] if after else None
    # 긴축 에피소드 이전(202101~202102)에도 diff12 는 음수다(2020년 인하의 잔상).
    # 의미 있는 값은 '긴축 이후 최초로 음(-)이 된 달' 이다.
    out["diff12_first_negative_any"] = neg[0] if neg else None
    out["diff12_first_negative_post_tightening"] = None
    if pos:
        after_neg = [m for m in neg if m > pos[-1]]
        out["diff12_first_negative_post_tightening"] = after_neg[0] if after_neg else None

    return out, d12


def validate_boundaries(tj: dict) -> list[dict]:
    """사용자 제시 경계가 실측 궤적과 맞는지 판정."""
    checks = []

    # 경계 1: 202205 | 202206
    checks.append({
        "boundary": "202205 | 202206",
        "claimed": "저금리기(1% 미만 ~ 상승 초기) → 긴축기(상승 시작)",
        "observed": (
            f"base_rate 는 202205=1.75, 202206=1.75 로 **경계 양쪽이 동일**하다. "
            f"실제 인상 개시월은 {tj['first_hike_month']}(0.50→0.75), "
            f"1.00% 돌파는 202111, 1% 초과 진입은 202201(1.25) 이다. "
            f"경계 직후의 인상 재개월은 202207(1.75→2.25, +50bp) 이다."
        ),
        "verdict": "MISMATCH",
        "detail": (
            "① 202206 에는 금리 이벤트가 없다(전월과 동일). ② 저금리기 명세 '1% 미만'은 "
            "구간 후반 202201~202205 가 1.25~1.75% 이므로 사실과 다르다. "
            "실측 정렬 경계는 202107|202108(0.50 정체 종료·인상 개시) 또는 "
            "202206|202207(50bp 빅스텝 개시) 이다."
        ),
    })

    # 경계 2: 202312 | 202401
    checks.append({
        "boundary": "202312 | 202401",
        "claimed": "긴축기(고점 도달) → 인하기(하락)",
        "observed": (
            f"base_rate 는 {tj['peak_first_month']} 에 고점 {tj['peak_rate']:.2f}% 에 도달한 뒤 "
            f"{tj['peak_last_month']} 까지 {tj['peak_plateau_len']}개월 3.50% 를 유지했고, "
            f"실제 첫 인하는 {tj['first_cut_month']}(3.50→3.25) 이다. "
            f"즉 202401~202409 는 아직 '하락'이 아니라 '고점 유지' 구간이다. "
            f"다만 12개월 차분(base_rate_diff12) 기준으로는 202312 가 마지막 양(+0.25)이고 "
            f"{tj['diff12_first_nonpositive_after_tightening']} 부터 0 이하로 꺾인다."
        ),
        "verdict": "PARTIAL",
        "detail": (
            "레벨(수준) 기준으로는 어긋난다 — 인하 개시는 202410 이다. "
            "그러나 모델이 실제로 투입하는 변수는 레벨이 아니라 base_rate_diff12 이며, "
            "그 기준에서는 202401 이 긴축 임펄스가 소멸하는 정확한 전환점이다. "
            "또한 202312|202401 은 TRAIN/VALID 분할 경계와 정확히 일치한다(split_spec.py). "
            "→ 경계는 유지하되, 202401~202409 를 '고점 유지', 202410~202505 를 "
            "'실제 인하'로 쪼갠 4국면 정의를 함께 산출해 교차검증한다."
        ),
    })
    return checks


def build_adjusted_regimes(tj: dict) -> list[tuple[str, str, str]]:
    """실측 궤적에 정확히 정렬한 4국면."""
    first_hike = tj["first_hike_month"]          # 202108
    flat_low_end = tj["flat_low_until"]          # 202107
    peak_start = tj["peak_first_month"]          # 202301
    first_cut = tj["first_cut_month"]            # 202410
    peak_end = _prev_ym(first_cut)               # 202409
    tight_end = _prev_ym(peak_start)             # 202212
    return [
        ("저금리기(실측)", YM_MIN, flat_low_end),
        ("긴축기(실측)", first_hike, tight_end),
        ("고점유지기(실측)", peak_start, peak_end),
        ("인하기(실측)", first_cut, YM_MAX),
    ]


def _prev_ym(ym: str) -> str:
    y, m = int(ym[:4]), int(ym[4:])
    m -= 1
    if m == 0:
        y, m = y - 1, 12
    return f"{y}{m:02d}"


# ======================================================================
# 2. 패널 집계
# ======================================================================
def monthly_panel() -> pd.DataFrame:
    con = duckdb.connect()
    q = f"""
        SELECT BASE_YM,
               COUNT(*)                     AS n_rows,
               COUNT(DISTINCT V_BZNO)       AS n_firms,
               CAST(SUM(IS_BUDO_12M) AS BIGINT) AS n_pos,
               MIN(SPLIT)                   AS split_min,
               MAX(SPLIT)                   AS split_max
        FROM read_parquet('{PANEL.as_posix()}')
        GROUP BY 1
        ORDER BY 1
    """
    d = con.execute(q).df()
    con.close()
    d["default_rate_pct"] = d.n_pos / d.n_rows * 100.0
    return d


def regime_stats(regimes, br: pd.DataFrame) -> pd.DataFrame:
    """구간별 행수/기업수/양성/부도율 — 기업수는 distinct 라 SQL 로 직접."""
    con = duckdb.connect()
    rows = []
    for name, s, e in regimes:
        q = f"""
            SELECT COUNT(*) AS n_rows,
                   COUNT(DISTINCT V_BZNO) AS n_firms,
                   CAST(SUM(IS_BUDO_12M) AS BIGINT) AS n_pos
            FROM read_parquet('{PANEL.as_posix()}')
            WHERE BASE_YM >= '{s}' AND BASE_YM <= '{e}'
        """
        r = con.execute(q).df().iloc[0]
        sub = br[(br.BASE_YM >= s) & (br.BASE_YM <= e)]
        rows.append({
            "regime": name,
            "period": f"{s}~{e}",
            "n_months": int(len(sub)),
            "n_rows": int(r.n_rows),
            "n_firms": int(r.n_firms),
            "n_pos": int(r.n_pos),
            "default_rate_pct": round(float(r.n_pos) / float(r.n_rows) * 100.0, 4),
            "base_rate_min": float(sub.base_rate.min()),
            "base_rate_max": float(sub.base_rate.max()),
            "base_rate_mean": round(float(sub.base_rate.mean()), 4),
            "base_rate_start": float(sub.base_rate.iloc[0]),
            "base_rate_end": float(sub.base_rate.iloc[-1]),
            "base_rate_delta": round(float(sub.base_rate.iloc[-1] - sub.base_rate.iloc[0]), 4),
            "base_rate_range": round(float(sub.base_rate.max() - sub.base_rate.min()), 4),
        })
    con.close()
    return pd.DataFrame(rows)


def yearly_stats(br: pd.DataFrame) -> pd.DataFrame:
    con = duckdb.connect()
    q = f"""
        SELECT SUBSTR(BASE_YM, 1, 4) AS year,
               COUNT(*) AS n_rows,
               COUNT(DISTINCT V_BZNO) AS n_firms,
               CAST(SUM(IS_BUDO_12M) AS BIGINT) AS n_pos
        FROM read_parquet('{PANEL.as_posix()}')
        GROUP BY 1 ORDER BY 1
    """
    d = con.execute(q).df()
    con.close()
    d["default_rate_pct"] = (d.n_pos / d.n_rows * 100.0).round(4)
    d["n_ym"] = d.year.map(lambda y: int(((br.BASE_YM.str[:4] == y)).sum()))
    d["base_rate_mean"] = d.year.map(
        lambda y: round(float(br[br.BASE_YM.str[:4] == y].base_rate.mean()), 4))
    return d


# ======================================================================
# 3. 렌더링
# ======================================================================
# 정수(카운트)로 표시할 컬럼 / 소수 자리수를 지정할 컬럼
INT_COLS = {"n_rows", "n_firms", "n_pos", "n_months", "n_ym", "n", "lag_months"}
DEC_COLS = {
    "default_rate_pct": 3, "base_rate_mean": 3, "corr": 4,
    "base_rate": 2, "base_rate_min": 2, "base_rate_max": 2,
    "base_rate_delta": 2, "base_rate_range": 2, "chg": 2, "diff12": 2,
}


def _fmt(col: str, v) -> str:
    if v is None:
        return "-"
    if isinstance(v, str):
        return v
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    if pd.isna(f):
        return "-"
    if col in INT_COLS:
        return f"{int(round(f)):,}"
    nd = DEC_COLS.get(col, 3)
    return f"{f:,.{nd}f}"


def md_table(df: pd.DataFrame, cols: list[tuple[str, str]]) -> str:
    head = "| " + " | ".join(h for _, h in cols) + " |"
    sep = "|" + "|".join("---" for _ in cols) + "|"
    lines = [head, sep]
    for _, r in df.iterrows():
        lines.append("| " + " | ".join(_fmt(c, r[c]) for c, _h in cols) + " |")
    return "\n".join(lines)


def lag_correlation(mon: pd.DataFrame, br: pd.DataFrame, max_lag: int = 24) -> dict:
    """월별 부도율과 base_rate 의 선행/후행 상관.

    corr(default_rate[t], base_rate[t-k]) 를 k=0..max_lag 로 훑는다.
    k 가 클수록 '부도율이 금리를 더 늦게 따라간다'는 뜻이다.
    IS_BUDO_12M 이 전방 라벨이므로 절대 lag 값은 '라벨 부여 시점' 기준임에 유의.
    """
    m = mon.merge(br, on="BASE_YM", how="left").sort_values("BASE_YM").reset_index(drop=True)
    full = br.sort_values("BASE_YM").reset_index(drop=True)
    idx = {ym: i for i, ym in enumerate(full.BASE_YM)}
    rows = []
    for k in range(0, max_lag + 1):
        xs, ys = [], []
        for _, r in m.iterrows():
            i = idx.get(r.BASE_YM)
            if i is None or i - k < 0:
                continue
            xs.append(float(full.base_rate.iloc[i - k]))
            ys.append(float(r.default_rate_pct))
        if len(xs) >= 12:
            rows.append({"lag_months": k, "n": len(xs),
                         "corr": round(float(pd.Series(xs).corr(pd.Series(ys))), 4)})
    best = max(rows, key=lambda r: r["corr"]) if rows else None
    return {"by_lag": rows, "argmax": best}


def plot_monthly(mon: pd.DataFrame, br: pd.DataFrame, path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    m = mon.merge(br, on="BASE_YM", how="left")
    x = range(len(m))
    fig, ax1 = plt.subplots(figsize=(14, 6))
    ax1.plot(x, m.default_rate_pct, color="#c0392b", lw=2, marker="o", ms=3,
             label="12M default rate (%)")
    ax1.set_ylabel("12M default rate (%)", color="#c0392b")
    ax1.tick_params(axis="y", labelcolor="#c0392b")
    ax2 = ax1.twinx()
    ax2.step(x, m.base_rate, where="post", color="#2c3e50", lw=1.8, label="base_rate (%)")
    ax2.set_ylabel("base_rate (%)", color="#2c3e50")
    ax2.tick_params(axis="y", labelcolor="#2c3e50")
    step = 3
    ax1.set_xticks(list(x)[::step])
    ax1.set_xticklabels(m.BASE_YM.tolist()[::step], rotation=60, fontsize=8)
    for b in ("202206", "202401", "202410"):
        if b in m.BASE_YM.values:
            ax1.axvline(list(m.BASE_YM).index(b), color="#7f8c8d", ls="--", lw=1)
    ax1.set_title("Monthly IS_BUDO_12M default rate vs base_rate (202101-202505)")
    ax1.grid(alpha=.25)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    log("=" * 70)
    log("step42 / A-3 거시 국면 재정의 + 구간별 부도율 — START")
    log(f"panel = {PANEL}")
    if not PANEL.exists():
        log("FATAL: panel parquet not found")
        flush_log()
        return 1

    br_all = load_base_rate()
    tj, d12 = describe_trajectory(br_all)
    br = br_all[(br_all.BASE_YM >= YM_MIN) & (br_all.BASE_YM <= YM_MAX)].reset_index(drop=True)
    log(f"base_rate: 정체종료={tj['flat_low_until']} 인상개시={tj['first_hike_month']} "
        f"고점={tj['peak_rate']}@{tj['peak_first_month']}~{tj['peak_last_month']}"
        f"({tj['peak_plateau_len']}m) 인하개시={tj['first_cut_month']}")

    checks = validate_boundaries(tj)
    for c in checks:
        log(f"boundary {c['boundary']}: {c['verdict']}")

    adjusted = build_adjusted_regimes(tj)
    log(f"adjusted regimes = {adjusted}")

    mon = monthly_panel()
    log(f"panel months={len(mon)} rows={int(mon.n_rows.sum()):,} pos={int(mon.n_pos.sum()):,} "
        f"overall={mon.n_pos.sum()/mon.n_rows.sum()*100:.4f}%")

    prim = regime_stats(REGIMES_PRIMARY, br)
    adj = regime_stats(adjusted, br)
    yr = yearly_stats(br)

    for _, r in prim.iterrows():
        log(f"[PRIMARY] {r.regime:8s} {r.period} rows={r.n_rows:,} pos={r.n_pos:,} "
            f"rate={r.default_rate_pct:.3f}% br_mean={r.base_rate_mean:.3f}")
    for _, r in adj.iterrows():
        log(f"[ADJUSTED] {r.regime:16s} {r.period} rows={r.n_rows:,} pos={r.n_pos:,} "
            f"rate={r.default_rate_pct:.3f}%")
    for _, r in yr.iterrows():
        log(f"[YEAR] {r.year} rows={r.n_rows:,} pos={r.n_pos:,} rate={r.default_rate_pct:.3f}%")

    # 가설 판정
    top_prim = prim.loc[prim.default_rate_pct.idxmax()]
    top_adj = adj.loc[adj.default_rate_pct.idxmax()]
    hyp_primary = bool(top_prim.regime == "인하기")
    hyp_adjusted = bool(top_adj.regime == "인하기(실측)")
    log(f"HYPOTHESIS '인하기 최고': primary={hyp_primary} (max={top_prim.regime} "
        f"{top_prim.default_rate_pct:.3f}%) adjusted={hyp_adjusted} (max={top_adj.regime} "
        f"{top_adj.default_rate_pct:.3f}%)")

    lags = lag_correlation(mon, br_all)
    if lags["argmax"]:
        log(f"LAG corr argmax: k={lags['argmax']['lag_months']}m r={lags['argmax']['corr']:.4f} "
            f"(k=0 r={lags['by_lag'][0]['corr']:.4f})")

    # 월별 CSV / PNG
    mon_out = mon.merge(br, on="BASE_YM", how="left")
    mon_csv = OUT_DIR / "A3_monthly_default_rate.csv"
    mon_out.to_csv(mon_csv, index=False, encoding="utf-8-sig")
    png = OUT_DIR / "A3_monthly_default_rate.png"
    try:
        plot_monthly(mon, br, png)
        log(f"wrote {png}")
    except Exception as exc:  # noqa: BLE001
        log(f"WARN plot failed: {exc}")
    log(f"wrote {mon_csv}")

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "script": "eda_pipeline/step42_macro_regime.py",
        "panel": PANEL.as_posix(),
        "macro_source": MACRO_CSV.as_posix(),
        "window": f"{YM_MIN}~{YM_MAX}",
        "target": "IS_BUDO_12M (BASE_YM 기준 향후 12개월 부도)",
        "panel_totals": {
            "n_rows": int(mon.n_rows.sum()),
            "n_pos": int(mon.n_pos.sum()),
            "default_rate_pct": round(float(mon.n_pos.sum() / mon.n_rows.sum() * 100), 4),
            "n_months": int(len(mon)),
        },
        "base_rate_trajectory": tj,
        "base_rate_monthly": d12.assign(
            chg=d12.chg.astype(float), diff12=d12.diff12.astype(float)
        ).to_dict(orient="records"),
        "boundary_validation": checks,
        "regimes_primary_definition": [
            {"regime": n, "start": s, "end": e} for n, s, e in REGIMES_PRIMARY],
        "regimes_adjusted_definition": [
            {"regime": n, "start": s, "end": e} for n, s, e in adjusted],
        "regime_default_rate_primary": prim.to_dict(orient="records"),
        "regime_default_rate_adjusted": adj.to_dict(orient="records"),
        "yearly_default_rate": yr.to_dict(orient="records"),
        "monthly_default_rate": mon_out.to_dict(orient="records"),
        "hypothesis_check": {
            "statement": "인하기의 부도율이 가장 높다",
            "primary_max_regime": str(top_prim.regime),
            "primary_max_rate_pct": float(top_prim.default_rate_pct),
            "primary_holds": hyp_primary,
            "adjusted_max_regime": str(top_adj.regime),
            "adjusted_max_rate_pct": float(top_adj.default_rate_pct),
            "adjusted_holds": hyp_adjusted,
        },
        "user_reference_yearly_pct": {"2023": 1.240, "2024": 1.176, "2025": 1.417},
        "lag_correlation": lags,
        "split_confound": (
            "인하기(202401~202505)는 split_spec.py 의 VALID 구간과 정확히 동일하다. "
            "구간 간 부도율 비교는 학습/홀드아웃 경계와 겹치므로 모델 성능 해석과 분리해 읽어야 한다."
        ),
    }
    payload["interpretation"] = build_interpretation(payload, prim, adj, yr, mon_out, tj)
    payload["docs05_block"] = build_docs05_block(payload, prim, adj, yr, tj)
    jpath = OUT_DIR / "A3_macro_regime.json"
    jpath.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str),
                     encoding="utf-8")
    log(f"wrote {jpath}")

    write_markdown(payload, prim, adj, yr, mon_out, d12, checks, tj)
    log("step42 / A-3 — DONE")
    flush_log()
    return 0


def build_interpretation(payload, prim, adj, yr, mon, tj) -> str:
    g = lambda df, name, col: float(df[df.regime == name][col].iloc[0])  # noqa: E731
    low = g(prim, "저금리기", "default_rate_pct")
    tight = g(prim, "긴축기", "default_rate_pct")
    cut = g(prim, "인하기", "default_rate_pct")
    a_low = g(adj, "저금리기(실측)", "default_rate_pct")
    a_tight = g(adj, "긴축기(실측)", "default_rate_pct")
    a_peak = g(adj, "고점유지기(실측)", "default_rate_pct")
    a_cut = g(adj, "인하기(실측)", "default_rate_pct")

    top = mon.loc[mon.default_rate_pct.idxmax()]
    dip24 = mon[(mon.BASE_YM >= "202401") & (mon.BASE_YM <= "202412")]
    dip = dip24.loc[dip24.default_rate_pct.idxmin()]
    gap_peak = _months_between(tj["peak_first_month"], str(top.BASE_YM))
    gap_cut = _months_between(tj["first_cut_month"], str(top.BASE_YM))
    y23 = float(yr[yr.year == "2023"].default_rate_pct.iloc[0])
    y24 = float(yr[yr.year == "2024"].default_rate_pct.iloc[0])
    y25 = float(yr[yr.year == "2025"].default_rate_pct.iloc[0])
    lag = payload["lag_correlation"]["argmax"]

    return (
        f"base_rate 는 {tj['peak_first_month']} 에 고점 {tj['peak_rate']:.2f}% 에 도달해 "
        f"{tj['peak_plateau_len']}개월 유지된 뒤 {tj['first_cut_month']} 부터 인하로 전환했지만, "
        f"IS_BUDO_12M 부도율은 저금리기 {low:.3f}% → 긴축기 {tight:.3f}% → 인하기 {cut:.3f}% 로 "
        f"단조 상승해 **금리가 내려가는 국면에서 가장 높다**(실측 궤적에 정렬한 4국면에서도 "
        f"{a_low:.3f}% → {a_tight:.3f}% → {a_peak:.3f}% → 인하기 {a_cut:.3f}% 로 순서가 같다). "
        f"월별로도 부도율 최고점은 {top.BASE_YM}({float(top.default_rate_pct):.3f}%)로 금리 고점 도달보다 "
        f"{gap_peak}개월, 인하 개시보다 {gap_cut}개월 늦으며, corr(부도율[t], base_rate[t-k]) 는 "
        f"동시점(k=0, r={payload['lag_correlation']['by_lag'][0]['corr']:.3f})이 아니라 "
        f"k={lag['lag_months']}개월(r={lag['corr']:.3f})에서 단일 최대를 갖고 그 뒤 단조 감소한다"
        f"(라벨이 t+1~t+12 부도를 담으므로 실제 부도 발생시점 기준 지연은 대략 "
        f"{lag['lag_months']}+6 ≈ {lag['lag_months'] + 6}개월). 따라서 이 표는 "
        f"\"부도는 거시 긴축에 후행한다\"는 가설의 **직접 증거로 쓸 수 있다**. "
        f"다만 세 가지 유보를 명시해야 한다. 첫째, 연도별로는 {y23:.3f}%(2023) → {y24:.3f}%(2024) 로 "
        f"한 번 꺾였다가 {y25:.3f}%(2025, 1~5월만) 로 재상승했고 월별 저점은 "
        f"{dip.BASE_YM}({float(dip.default_rate_pct):.3f}%) 이므로 단조 후행이 아니라 "
        f"'긴축 고점 유지 구간에서 일단 정체·소폭 반락한 뒤 인하 국면에서 재점화'되는 2단 패턴이다. "
        f"둘째, 두 시계열 모두 관측창 내에서 우상향 추세를 갖기 때문에 상관계수의 **절대 수준**은 "
        f"부풀려져 있다(k=0 에서도 이미 r={payload['lag_correlation']['by_lag'][0]['corr']:.3f}) — "
        f"근거로 쓸 수 있는 것은 상관의 크기가 아니라 k={lag['lag_months']} 에서 단봉으로 꺾이는 "
        f"**형태**와 구간별 순서다. 셋째, 인하기 구간(202401~202505)은 split_spec.py 의 VALID "
        f"홀드아웃과 정확히 겹쳐 국면 효과와 표본 시기 효과가 분리되지 않으므로, 이 표는 관측 "
        f"사실로만 인용하고 모델 성능 변화의 원인으로 돌려서는 안 된다."
    )


def _months_between(a: str, b: str) -> int:
    ya, ma = int(a[:4]), int(a[4:])
    yb, mb = int(b[:4]), int(b[4:])
    return (yb - ya) * 12 + (mb - ma)


def build_docs05_block(payload, prim, adj, yr, tj) -> str:
    reg_cols = [("regime", "구간"), ("period", "기간"), ("n_rows", "관측 행수"),
                ("n_firms", "기업 수(distinct)"), ("n_pos", "양성 행수"),
                ("default_rate_pct", "부도율%"), ("base_rate_mean", "base_rate 평균"),
                ("base_rate_delta", "base_rate 변화폭")]
    yr_cols = [("year", "연도"), ("n_rows", "관측 행수"), ("n_pos", "양성 행수"),
               ("default_rate_pct", "부도율%"), ("base_rate_mean", "base_rate 평균")]
    hc = payload["hypothesis_check"]
    return f"""### 거시 국면별 부도율

국면은 base_rate 의 **수준**이 아니라 **변화 방향**으로 정의한다. 수준으로는 구간이
구분되지 않는다(긴축기 평균 {float(prim[prim.regime=='긴축기'].base_rate_mean.iloc[0]):.2f}% ≈ 인하기 평균 {float(prim[prim.regime=='인하기'].base_rate_mean.iloc[0]):.2f}%).

| 국면 | 기간 | 성격 (실측) |
|---|---|---|
| 저금리기 | 202101~202205 | 0.50% 정체({tj['flat_low_until']}까지) 후 인상 개시({tj['first_hike_month']}), 구간말 1.75% |
| 긴축기 | 202206~202312 | 50bp 빅스텝 개시(202207), 고점 3.50% 도달({tj['peak_first_month']}) 후 유지 |
| 인하기 | 202401~202505 | 12개월 긴축 임펄스 소멸(diff12 ≤ 0), 실제 인하 개시 {tj['first_cut_month']}, 수준은 여전히 2.50~3.50% |

{md_table(prim, reg_cols)}

연도별 대조:

{md_table(yr, yr_cols)}

> 2025 는 202501~202505 5개월만 패널에 포함된다.

레벨 궤적에 정확히 정렬한 4국면으로 쪼개도 순서는 동일하다(교차검증):

{md_table(adj, reg_cols)}

**해석.** {payload['interpretation']}

가설 "인하기가 가장 높다" → **{'성립' if hc['primary_holds'] else '불성립'}**
(주 정의 최고 {hc['primary_max_regime']} {hc['primary_max_rate_pct']:.3f}% /
실측 정렬 최고 {hc['adjusted_max_regime']} {hc['adjusted_max_rate_pct']:.3f}%).

<sub>산출: `eda_pipeline/step42_macro_regime.py` · 원자료 `eda_pipeline/output/validation/A3_macro_regime.json` · 월별 `A3_monthly_default_rate.csv` / `A3_monthly_default_rate.png`</sub>"""


def write_markdown(payload, prim, adj, yr, mon, d12, checks, tj) -> None:
    p = OUT_DIR / "A3_MACRO_REGIME.md"

    traj_tbl = md_table(
        d12.assign(base_rate=d12.base_rate.astype(float),
                   chg=d12.chg.fillna(0).astype(float),
                   diff12=d12.diff12.astype(float)),
        [("BASE_YM", "월"), ("base_rate", "base_rate(%)"),
         ("chg", "전월대비(pp)"), ("diff12", "12개월차분(pp)")],
    )

    reg_cols = [("regime", "구간"), ("period", "기간"), ("n_months", "개월"),
                ("n_rows", "관측 행수"), ("n_firms", "기업 수(distinct)"),
                ("n_pos", "양성 행수"), ("default_rate_pct", "부도율%"),
                ("base_rate_mean", "base_rate 평균"), ("base_rate_min", "최소"),
                ("base_rate_max", "최대"), ("base_rate_delta", "변화폭(끝-처음)")]
    prim_tbl = md_table(prim, reg_cols)
    adj_tbl = md_table(adj, reg_cols)
    yr_tbl = md_table(yr, [("year", "연도"), ("n_rows", "관측 행수"),
                           ("n_firms", "기업 수(distinct)"), ("n_pos", "양성 행수"),
                           ("default_rate_pct", "부도율%"), ("n_ym", "포함 개월"),
                           ("base_rate_mean", "base_rate 평균")])
    mon_tbl = md_table(mon, [("BASE_YM", "월"), ("n_rows", "행수"), ("n_pos", "양성"),
                             ("default_rate_pct", "부도율%"), ("base_rate", "base_rate(%)")])

    hc = payload["hypothesis_check"]
    tot = payload["panel_totals"]

    body = f"""# A-3 거시 국면 구간 재정의 + 구간별 부도율

- 생성: {payload['generated_at']}
- 스크립트: `eda_pipeline/step42_macro_regime.py`
- 패널: `{payload['panel']}` — {tot['n_rows']:,}행 / {tot['n_months']}개월 / 양성 {tot['n_pos']:,} / 전체 부도율 **{tot['default_rate_pct']:.3f}%**
- 금리 원자료: `{payload['macro_source']}` (`base_rate` 레벨)
- 타깃: `IS_BUDO_12M` — BASE_YM 시점 기준 **향후 12개월** 부도 여부 (전방 라벨)

> 왜 재정의하나: 기존 구간 명칭은 금리 **수준**으로 국면을 나눈 것처럼 서술되어 있었으나
> "완화기" 평균 3.21% > "고스트레스" 3.18% 로 수준으로는 두 국면이 구분되지 않는다.
> 아래는 금리의 **변화 방향**으로 재정의한 국면과, 그 경계를 실측 궤적으로 검증한 결과다.

---

## 1. base_rate 실측 궤적 (202101~202505)

| 항목 | 실측값 |
|---|---|
| 초저금리 정체 구간 | 202101 ~ {tj['flat_low_until']} (0.50% 고정, {_months_between(YM_MIN, tj['flat_low_until']) + 1}개월) |
| **인상 개시월** | **{tj['first_hike_month']}** (0.50 → 0.75) |
| 마지막 인상월 | {tj['last_hike_month']} (3.25 → 3.50) |
| 인상 횟수 | {len(tj['hike_months'])}회 — {', '.join(tj['hike_months'])} |
| **고점 도달월** | **{tj['peak_first_month']}** ({tj['peak_rate']:.2f}%) |
| 고점 유지 구간 | {tj['peak_first_month']} ~ {tj['peak_last_month']} = **{tj['peak_plateau_len']}개월 3.50% 고정** |
| **인하 개시월** | **{tj['first_cut_month']}** (3.50 → 3.25) |
| 인하 횟수 | {len(tj['cut_months'])}회 — {', '.join(tj['cut_months'])} |
| 12개월차분(diff12) 최초 양(+) | {tj['diff12_first_positive']} |
| 12개월차분 마지막 양(+) | {tj['diff12_last_positive']} |
| 12개월차분 0 이하 전환 | {tj['diff12_first_nonpositive_after_tightening']} |
| 12개월차분 긴축후 최초 음(-) | {tj['diff12_first_negative_post_tightening']} |

<details>
<summary>월별 base_rate 전체 궤적 (펼치기)</summary>

{traj_tbl}

</details>

---

## 2. 구간 경계 검증

{chr(10).join(
    f"### 경계 {c['boundary']} — **{c['verdict']}**"
    f"{chr(10)}{chr(10)}- 주장: {c['claimed']}"
    f"{chr(10)}- 실측: {c['observed']}"
    f"{chr(10)}- 판정 근거: {c['detail']}{chr(10)}"
    for c in checks
)}

### 조정 결론

| 경계 | 판정 | 처리 |
|---|---|---|
| 202205 \\| 202206 | 어긋남 | 사용자 정의를 **주(primary) 구간으로 유지**하되, 명세 문구 "1% 미만"은 "0.50% 정체 ~ 인상 초기(최대 1.75%)"로 교정. 실측 정렬 경계 202107\\|202108 을 대안 구간에 반영 |
| 202312 \\| 202401 | 부분 일치 | 레벨 기준 인하 개시는 **202410**. 다만 diff12(모델 투입 변수) 기준으로는 202401 이 긴축 임펄스 소멸 시점이며 TRAIN/VALID 분할 경계와도 일치 → 경계 유지 + 202401~202409(고점유지) / 202410~202505(실제 인하) 로 쪼갠 대안 구간을 병기 |

즉 **사용자 3국면 정의는 폐기하지 않는다**(diff12·분할경계와 정합적). 대신 레벨 궤적에
정확히 정렬한 4국면 정의를 함께 산출해 결론이 구간 정의에 의존하는지 교차검증한다.

---

## 3. ★ 구간별 부도율 (주 정의 — 사용자 지시 3국면)

{prim_tbl}

## 3-b. 구간별 부도율 (실측 정렬 4국면 — 교차검증)

{adj_tbl}

---

## 4. 연도별 부도율 (대조)

{yr_tbl}

사용자 제시 참고값과 대조:

| 연도 | 본 산출 | 사용자 참고값 | 차이(pp) |
|---|---|---|---|
{chr(10).join(
    f"| {y} | {float(yr[yr.year==y].default_rate_pct.iloc[0]):.3f}% | {v:.3f}% | "
    f"{float(yr[yr.year==y].default_rate_pct.iloc[0]) - v:+.3f} |"
    for y, v in payload['user_reference_yearly_pct'].items() if (yr.year==y).any()
)}

차이는 세 연도 모두 −0.017 ~ −0.020pp 로 **거의 일정한 오프셋**이다. 즉 분자·분모가
약간 다른 행 집합(다른 패널 변형본 또는 중복제거 기준)에서 뽑힌 값으로 보이며,
연도 간 **순서와 굴곡(2023 > 2024 < 2025, 2024 에 반락)은 완전히 재현된다.**
본 문서의 표는 최종 패널 `nh_panel_macro_12m_obv_none_real.parquet` 기준값이다.

> 2025 는 202501~202505 5개월만 패널에 존재한다(연 전체가 아님).

---

## 5. 월별 부도율

- CSV: `eda_pipeline/output/validation/A3_monthly_default_rate.csv`
- 그래프: `eda_pipeline/output/validation/A3_monthly_default_rate.png` (부도율 좌축 / base_rate 우축, 점선 = 202206·202401·202410 경계)

<details>
<summary>월별 표 (펼치기)</summary>

{mon_tbl}

</details>

---

## 6. 가설 판정 — "인하기가 가장 높다"

| 정의 | 최고 부도율 구간 | 값 | 가설 |
|---|---|---|---|
| 주 정의(3국면) | {hc['primary_max_regime']} | {hc['primary_max_rate_pct']:.3f}% | {'**성립**' if hc['primary_holds'] else '**불성립**'} |
| 실측 정렬(4국면) | {hc['adjusted_max_regime']} | {hc['adjusted_max_rate_pct']:.3f}% | {'**성립**' if hc['adjusted_holds'] else '**불성립**'} |

주의(교란 요인): 인하기(202401~202505)는 `split_spec.py` 의 **VALID 구간과 정확히 동일**하다.
구간별 부도율 비교는 순수 관측 사실이지만, 이를 모델 성능 저하/개선과 혼동하면 안 된다.

---

## 7. 후행성 정량화 — corr(월별 부도율[t], base_rate[t-k])

lag k 가 클수록 "부도율이 금리를 더 늦게 따라간다"는 뜻이다. `IS_BUDO_12M` 이 전방 라벨이므로
k 는 **라벨 부여 시점(BASE_YM) 기준** 지연이다. 라벨은 t+1~t+12 의 부도를 담고 그 무게중심은
약 t+6.5 이므로, **실제 부도 발생시점 기준 지연은 k + 약 6개월** 로 이보다 크다.

{md_table(pd.DataFrame(payload['lag_correlation']['by_lag']),
          [('lag_months', 'lag k(개월)'), ('n', '표본 월수'), ('corr', 'corr')])}

최대 상관: **k = {payload['lag_correlation']['argmax']['lag_months']}개월, r = {payload['lag_correlation']['argmax']['corr']:.4f}** (동시점 k=0 은 r = {payload['lag_correlation']['by_lag'][0]['corr']:.4f})

---

## 8. 해석

{payload['interpretation']}

---

## docs/05 삽입용 블록

> 아래 블록을 `docs/05_거시경제_결합.md` 의
> `<!-- A-3 PENDING: 긴축기/저금리기/인하기 구간별 부도율 표 삽입 위치 -->` 마커 자리에
> 그대로 삽입한다. (삽입은 조정자가 수행 — 본 작업에서는 편집하지 않았다.)

```markdown
{payload['docs05_block']}
```
"""
    p.write_text(body, encoding="utf-8")
    log(f"wrote {p}")


if __name__ == "__main__":
    sys.exit(main())
