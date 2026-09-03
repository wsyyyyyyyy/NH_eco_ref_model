"""
======================================================================
STAGE 6 D축 — 결과 보고서 생성
======================================================================
입력: eda_pipeline/output/validation/d_axis/d_axis_results.json  (step34)
      eda_pipeline/output/validation/D_axis_gate1.json           (step33)
출력: eda_pipeline/output/validation/D_AXIS_RESULT.md
      eda_pipeline/output/validation/d_axis/*.png

기준서: eda_pipeline/output/validation/D_AXIS_SUCCESS_CRITERIA.md (개정 R1)

Usage
-----
    python -m eda_pipeline.step35_d_axis_report --calib platt_train
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from eda_pipeline import config, split_spec
from eda_pipeline.step34_d_axis import SCENARIOS, summarize
from eda_pipeline.step6_macro_integration import INTERACTIONS

OUT_DIR = config.VALIDATION_DIR / "d_axis"
REPORT = config.VALIDATION_DIR / "D_AXIS_RESULT.md"

# 원본 모델(lgbm_12m_model.txt)의 거시 gain 합계. 기준서 G2-1 의 비교 기준.
REFERENCE_MACRO_GAIN_PCT = 5.12
NOISE_BAND = 0.003          # |ΔAUC| < 0.003 은 차이 없음

# 연도별 실제 부도율 — **폴백 전용 상수**.
#   ★ [2026-09-02] 이 값을 리포트에 직접 쓰지 않는다. 패널에서 실측한다.
#   패널이 재생성되면 이 상수는 조용히 어긋난다. 2026-09-02 실측 대조에서
#   매년 0.003~0.020%p 높게 박혀 있었다 (구 세대 패널의 값이었다).
#   패널을 읽을 수 없을 때만 쓰고, 그 사실을 리포트에 밝힌다.
ACTUAL_YEARLY_FALLBACK = {"2021": 0.671, "2022": 0.904, "2023": 1.240,
                          "2024": 1.176, "2025": 1.417}


def yearly_default_rates() -> tuple[dict[str, float], bool]:
    """패널에서 연도별 12개월 선행 부도율(%)을 실측한다.

    Returns
    -------
    (연도 -> 부도율%, 실측 성공 여부)
    """
    try:
        import duckdb
        pnl = config.OUTPUT_DIR / "nh_panel_macro_12m_obv_none_real.parquet"
        con = duckdb.connect()
        try:
            d = con.execute(
                "SELECT SUBSTR(BASE_YM,1,4) y, AVG(IS_BUDO_12M)*100 r "
                f"FROM read_parquet('{pnl.as_posix()}') GROUP BY 1 ORDER BY 1").df()
        finally:
            con.close()
        return {str(r.y): float(r.r) for r in d.itertuples()}, True
    except Exception:                                             # noqa: BLE001
        return dict(ACTUAL_YEARLY_FALLBACK), False

# ── 경제 채널 분류 ──────────────────────────────────────────────────
CHANNELS: list[tuple[str, tuple[str, ...]]] = [
    ("환율-수출", ("USD_KRW", "EUR_KRW", "JPY_KRW", "CNY_KRW", "DXY",
                   "export_index", "import_index", "trade_total",
                   "current_account", "goods_balance", "export_price")),
    ("금리-차입", ("base_rate", "KORIBOR", "treasury_bond", "corporate_bond",
                   "CD_rate", "CP_91d", "MSB_91d", "call_rate",
                   "credit_spread", "liquidity_spread", "US_10Y", "US_3M_tbill")),
    ("유가-원자재", ("brent", "WTI", "natural_gas", "gold", "silver",
                     "copper", "corn", "soybean")),
    ("심리지수", ("BSI", "CSI", "VIX")),
    ("물가", ("CPI", "PPI")),
    ("통화-유동성", ("M1_", "M2_", "Lf_", "monetary_base",
                     "household_credit", "household_loan")),
    ("주가", ("KOSPI", "KOSDAQ", "DowJones", "NASDAQ", "SP500",
              "Nikkei", "Shanghai")),
    ("부동산-건설", ("housing_price", "construction_cost", "unsold_housing")),
    ("고용", ("unemployment",)),
]
INTERACTION_CHANNEL = {
    "fx_shock_x_export": "환율-수출 (원/달러 충격 x 수출비중)",
    "fx_shock_x_export_hybrid": "환율-수출 (원/달러 x 수출비중 하이브리드)",
    "eur_shock_x_export": "환율-수출 (원/유로 충격 x 수출비중)",
    "eur_shock_x_export_hybrid": "환율-수출 (원/유로 x 수출비중 하이브리드)",
    "fx_vol_x_fxdebt": "환율-외화부채 (환변동성 x 외화부채비중)",
    "rate_shock_x_leverage": "금리-차입 (정책금리 충격 x 차입금의존도)",
    "credit_spread_x_lev": "금리-차입 (신용스프레드 x 차입금의존도)",
    "liq_spread_x_shortdebt": "금리-유동성 (유동성스프레드 x 단기부채비중)",
    "oil_shock_x_inv": "유가-재고 (유가 충격 x 재고부담)",
    "bsi_x_industry": "심리지수-업종 (제조업 BSI x 제조업 여부)",
}
INTER_ALL = [n for n, _, _ in INTERACTIONS]


def channel_of(feat: str) -> str:
    if feat in INTERACTION_CHANNEL:
        return INTERACTION_CHANNEL[feat]
    for name, keys in CHANNELS:
        if any(k.lower() in feat.lower() for k in keys):
            suffix = []
            if feat.endswith("_ma3m"):
                suffix.append("3개월 이동평균")
            if "_vol_m" in feat:
                suffix.append("월내 변동성")
            elif "_log_ret" in feat:
                suffix.append("월간 수익률")
            elif "_diff12" in feat:
                suffix.append("12개월 차분")
            elif "_yoy" in feat:
                suffix.append("전년동월비")
            return f"{name}" + (f" ({', '.join(suffix)})" if suffix else "")
    return "기타"


def fmt(x, d=4):
    return "—" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:.{d}f}"


# ══════════════════════════════════════════════════════════════════════
# 그림
# ══════════════════════════════════════════════════════════════════════

def plot_calibration_curve(by_sc: dict, calib: str, path: Path) -> None:
    """G3-5 예측PD 10분위별 실제부도율. 대각선에 가까울수록 좋다."""
    fig, ax = plt.subplots(figsize=(6.4, 6.0))
    show = [s for s in ("D0", "D1", "D2", "D3") if s in by_sc]
    colors = {"D0": "#888888", "D1": "#4C78A8", "D2": "#F58518", "D3": "#54A24B"}
    lim = 0.0
    for sc in show:
        rows = by_sc[sc]
        dec = rows[0]["calibration"][calib]["deciles"]
        n_bins = len(dec)
        pm = np.mean([[d["pred_mean"] for d in r["calibration"][calib]["deciles"]][:n_bins]
                      for r in rows], axis=0)
        am = np.mean([[d["actual_rate"] for d in r["calibration"][calib]["deciles"]][:n_bins]
                      for r in rows], axis=0)
        ax.plot(pm * 100, am * 100, "o-", color=colors.get(sc), label=sc, lw=1.6, ms=4)
        lim = max(lim, float(pm.max() * 100), float(am.max() * 100))
    lim *= 1.05
    ax.plot([0, lim], [0, lim], "k--", lw=1, label="완전 캘리브레이션")
    ax.set_xlabel("예측 PD 10분위 평균 (%)")
    ax.set_ylabel("실제 부도율 (%)")
    ax.set_title(f"G3-5 캘리브레이션 곡선 (Valid, 보정={calib}, 시드 3회 평균)")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def plot_monthly(by_sc: dict, calib: str, path: Path) -> None:
    """G3-2/G3-3 월별 예측평균PD vs 실제부도율."""
    show = [s for s in ("D0", "D3") if s in by_sc]
    if not show:
        return
    base = by_sc[show[0]][0]["calibration"]["monthly"][calib]
    ym = [m["ym"] for m in base]
    actual = [m["actual_rate"] * 100 for m in base]

    fig, ax = plt.subplots(figsize=(10.5, 4.6))
    ax.plot(ym, actual, "k-o", lw=2, ms=4, label="실제 부도율")
    colors = {"D0": "#888888", "D3": "#54A24B"}
    for sc in show:
        rows = by_sc[sc]
        pm = np.mean([[m["pred_mean_pd"] * 100
                       for m in r["calibration"]["monthly"][calib]] for r in rows], axis=0)
        ax.plot(ym, pm, "--o", color=colors.get(sc), lw=1.6, ms=3,
                label=f"{sc} 예측 평균 PD")
    ax.set_ylabel("%")
    ax.set_title(f"G3-2 월별 예측 평균 PD vs 실제 부도율 (Valid, 보정={calib})")
    ax.tick_params(axis="x", rotation=90, labelsize=8)
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


# ══════════════════════════════════════════════════════════════════════
# 진단 — 거시-부도 관계의 부호 안정성
# ══════════════════════════════════════════════════════════════════════

DIAG_COLS = ["base_rate_diff12", "credit_spread_diff12", "liquidity_spread_diff12",
             "USD_KRW_log_ret", "BSI_mfg_biz_yoy", "CPI_core_yoy", "KOSPI_log_ret",
             "housing_price_index_yoy", "WTI_crude_oil_log_ret"]
LAG_GRID = list(range(0, 25, 3))


def macro_vs_default() -> tuple:
    """월별 12개월 선행 부도율과 거시 지표의 상관을 Train/Valid 로 나눠 잰다.

    거시는 BASE_YM 하나당 값이 하나뿐이므로, 모델이 거시로부터 배울 수 있는
    실질 표본은 행수(948,214)가 아니라 **월 수(53)** 다.
    """
    import duckdb
    pnl = config.OUTPUT_DIR / "nh_panel_macro_12m_obv_none_real.parquet"
    con = duckdb.connect()
    try:
        q = ('SELECT "BASE_YM","IS_BUDO_12M" FROM read_parquet('
             + "'" + pnl.as_posix() + "')")
        d = con.execute(q).df()
    finally:
        con.close()
    d["BASE_YM"] = d["BASE_YM"].astype(str)
    rate = d.groupby("BASE_YM")["IS_BUDO_12M"].mean() * 100

    import pandas as pd
    m = pd.read_csv(config.macro_input_path(), dtype={"BASE_YM": str})
    m["BASE_YM"] = m["BASE_YM"].str.strip()
    m = m.sort_values("BASE_YM").set_index("BASE_YM")

    idx = [x for x in rate.index if x in m.index]
    # ★ [2026-09-02] 분할 경계를 하드코딩하지 않는다. `split_spec` 이 정본이다.
    #   하드코딩하면 분할을 바꿨을 때 이 진단만 옛 경계로 남아, 모델이 쓴 분할과
    #   다른 구간의 상관을 같은 분할이라고 제시한다 (G1-7 과 같은 형태의 결함).
    _TR_END = split_spec.DEV_START          # Train 은 Dev 시작 직전까지
    _VA_START = split_spec.VALID_START
    tr = [x for x in idx if x < _TR_END]
    va = [x for x in idx if x >= _VA_START]

    sign_rows = []
    for c in DIAG_COLS:
        if c not in m.columns:
            continue
        a = float(np.corrcoef(m.loc[tr, c], rate.loc[tr])[0, 1])
        b = float(np.corrcoef(m.loc[va, c], rate.loc[va])[0, 1])
        t = float(np.corrcoef(m.loc[idx, c], rate.loc[idx])[0, 1])
        sign_rows.append({"col": c, "train": a, "valid": b, "all": t,
                          "flip": a * b < 0, "channel": channel_of(c)})

    lag_rows = []
    for c in DIAG_COLS[:5]:
        if c not in m.columns:
            continue
        r = {"col": c, "train": {}, "valid": {}}
        for k in LAG_GRID:
            sh = m[c].shift(k)
            i2 = [x for x in idx if pd.notna(sh.get(x))]
            t2 = [x for x in i2 if x < _TR_END]
            v2 = [x for x in i2 if x >= _VA_START]
            r["train"][k] = (float(np.corrcoef(sh.loc[t2], rate.loc[t2])[0, 1])
                             if len(t2) > 3 else float("nan"))
            r["valid"][k] = (float(np.corrcoef(sh.loc[v2], rate.loc[v2])[0, 1])
                             if len(v2) > 3 else float("nan"))
        lag_rows.append(r)

    seg = {}
    # 구간 상·하한도 split_spec 과 실제 관측 범위에서 만든다.
    #   TRAIN 시작·VALID 끝은 패널의 실측 최소·최대월이다 (고정값 금지).
    _first, _last = min(idx), max(idx)

    def _prev_ym(ym: str) -> str:
        y, m = int(ym[:4]), int(ym[4:])
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
        return f"{y:04d}{m:02d}"

    for lo, hi, lab in ((_first, _prev_ym(split_spec.DEV_START), "TRAIN"),
                        (split_spec.DEV_START, split_spec.DEV_END, "DEV"),
                        (split_spec.VALID_START, _last, "VALID")):
        sub = rate.loc[(rate.index >= lo) & (rate.index <= hi)]
        br = m.loc[(m.index >= lo) & (m.index <= hi), "base_rate_diff12"]
        seg[lab] = {"n_months": int(len(sub)), "rate_mean": float(sub.mean()),
                    "rate_min": float(sub.min()), "rate_max": float(sub.max()),
                    "base_rate_diff12_mean": float(br.mean()),
                    "base_rate_diff12_min": float(br.min()),
                    "base_rate_diff12_max": float(br.max())}
    return sign_rows, lag_rows, seg, len(idx)


# ══════════════════════════════════════════════════════════════════════
# 판정
# ══════════════════════════════════════════════════════════════════════

def ac12_contamination_note(by_sc: dict, w) -> None:
    """AC12 연 단위 조인분이 전 시나리오에 남아 있다는 사실과 그 크기를 적는다.

    step31 감사(2026-09-02)에서 `AC12_*` 금액 10개와 `HAS_AC12_YN` 이
    (b) 시점누수, `exp_fx_dbt` 가 (d) 부분오염으로 판정됐다. 이 컬럼들은
    A0 피처 풀에 들어 있어 **D0 를 포함한 전 시나리오가 공유**한다.
    B46(월 단위 as-of) 에서 해소 가능함을 확인했으나, 본류(step2/step5) 반영은
    A/B/C/D 전 축 기준선을 함께 움직이므로 이번 범위에서는 적용하지 않았다.

    ★ 크기 판단은 gain 으로 한다. 수치를 하드코딩하지 않는다.
    """
    import duckdb
    pnl = config.OUTPUT_DIR / "nh_panel_macro_12m_obv_none_real.parquet"
    try:
        cols = [r[0] for r in duckdb.connect().execute(
            f"DESCRIBE SELECT * FROM read_parquet('{pnl.as_posix()}')").fetchall()]
    except Exception:                                             # noqa: BLE001
        cols = []
    ac12 = sorted(c for c in cols if c.startswith("AC12_"))
    flags = [c for c in ("HAS_AC12_YN", "exp_fx_dbt") if c in cols]
    watch = set(ac12) | set(flags)

    # 전 시나리오의 gain 상위 20 안에 들어간 적이 있는가
    seen = []
    for sc, rows in by_sc.items():
        for r in rows:
            for e in r.get("gain_top20", []):
                if e["feature"] in watch:
                    seen.append((sc, r.get("seed"), e["feature"], e["rank"], e["gain_pct"]))

    w("")
    w("> ### ⚠ 전 시나리오가 공유하는 AC12 시점 오염")
    w(">")
    if ac12:
        w(f"> `AC12_*` 금액 {len(ac12)}개"
          + (f" + `{'` · `'.join(flags)}`" if flags else "")
          + " 는 원천 `BAS_YM`(YYYYMM)을 `str[:4]` 로 잘라 **연 단위로 조인**한 값이다"
            " (step2). step31 감사에서 금액 10개와 `HAS_AC12_YN` 은 **(b) 시점누수**,"
            " `exp_fx_dbt` 는 **(d) 부분오염**으로 판정됐다.")
        w("> 이 컬럼들은 A0 피처 풀에 있어 **D0 를 포함한 전 시나리오가 공유**한다."
          " 따라서 시나리오 간 ΔAUC 비교는 공정하지만, **절대값은 이 오염을 포함**한다.")
    w(">")
    # fx_vol_x_fxdebt 는 D3 에만 있다 (exp_fx_dbt 를 직접 곱한 항)
    fx = []
    for sc, rows in by_sc.items():
        for r in rows:
            for e in r.get("interaction_gain", []):
                if e["feature"] == "fx_vol_x_fxdebt":
                    fx.append((sc, r.get("seed"), e["gain_pct"], e["rank"]))
    if fx:
        _g = [g for _, _, g, _ in fx]
        _r = [rk for _, _, _, rk in fx if rk is not None]
        _scs = sorted({sc for sc, _, _, _ in fx})
        w(f"> **영향 크기 — 제한적이다.** `fx_vol_x_fxdebt`(환변동성 × 외화부채비중)는"
          f" {', '.join(_scs)} 에만 들어가며 gain "
          f"{min(_g):.3f}~{max(_g):.3f}%"
          + (f" / 순위 {min(_r)}~{max(_r)}위" if _r else "") + " 다.")
    if not seen:
        w("> `AC12_*` 금액 컬럼과 `HAS_AC12_YN` · `exp_fx_dbt` 는 **어느 시나리오에서도"
          " 전체 gain 상위 20 밖**이다. 판정을 뒤집을 크기가 아니다.")
    else:
        w("> gain 상위 20 안에 든 사례: "
          + " · ".join(f"{sc}(seed {sd}) `{f}` {rk}위 {g:.3f}%"
                       for sc, sd, f, rk, g in seen))
    w(">")
    w("> `HAS_AC12_YN` 이 피처에 살아 있으므로 모델은 **\"금액 0 = 외화부채 없음\"**"
      " 과 **\"레코드 없음\"** 을 구분할 수 있다 (as-of 재구성에서도 결측은 step5 규칙대로"
      " 0 으로 채우고 보유 여부는 이 플래그가 담는다).")
    w(">")
    w("> **해소 경로는 확인됐다** — B46(월 단위 as-of)에서 (b)·(d) 판정이 모두 풀렸고,"
      " 성능 기여는 A0 대비 +0.00067(노이즈)이었다. 본류(step2/step5) 반영은 A/B/C/D"
      " 전 축 기준선을 함께 움직이므로 이번 범위에서는 적용하지 않았다."
      " 추적: `PENDING_REVALIDATION.md` 12번.")
    w("")


def _pooled_sd(a: float, b: float) -> float:
    return float(np.sqrt(a ** 2 + b ** 2))


def verdict(s: dict, base: dict, gate1_pass: bool) -> tuple[str, str]:
    """기준서 판정 규칙을 그대로 옮긴 것.

        성공     게이트1 통과 + G3-1 유지 + (G3-2 또는 G3-3 개선)
        부분성공 게이트1 통과 + AUC 유지 + 캘리브레이션 **무변화**
        실패     AUC 가 0.003 초과 하락 **또는 캘리브레이션 악화**

    '변화 없음' 과 '악화' 를 가르는 선은 시드 노이즈다. 두 시나리오의 시드
    표준편차를 합성해 2σ 를 넘으면 실질 변화로 본다 (AUC 의 |Δ|<0.003 규칙과
    같은 취지). 이 규칙은 개선 방향에도 대칭으로 적용한다.
    """
    if s["scenario"] == "D0":
        return "기준선", "모든 Δ 의 기준"
    if not gate1_pass:
        return "판정불가", "게이트 1 미통과"

    d_auc = s["delta_auc"]
    d_corr = s["corr_pd_rate"] - base["corr_pd_rate"]
    d_mape = s["count_mape_pct"] - base["count_mape_pct"]
    sd_corr = 2 * _pooled_sd(s["corr_pd_rate_sd"], base["corr_pd_rate_sd"])
    sd_mape = 2 * _pooled_sd(s["count_mape_pct_sd"], base["count_mape_pct_sd"])

    if d_auc < -NOISE_BAND:
        return "실패", (f"AUC {d_auc:+.4f} (노이즈대 −{NOISE_BAND} 초과 하락) / "
                        f"상관 {d_corr:+.4f} / MAPE {d_mape:+.2f}%p")

    worse = []
    if d_corr < -sd_corr:
        worse.append(f"상관 {d_corr:+.4f} (2σ {sd_corr:.4f} 초과 하락)")
    if d_mape > sd_mape:
        worse.append(f"MAPE {d_mape:+.2f}%p (2σ {sd_mape:.2f} 초과 상승)")
    if worse:
        return "실패", f"AUC 유지({d_auc:+.4f})이나 캘리브레이션 악화 — " + " / ".join(worse)

    better = []
    if d_corr > sd_corr:
        better.append(f"상관 {d_corr:+.4f}")
    if d_mape < -sd_mape:
        better.append(f"MAPE {d_mape:+.2f}%p")
    if better:
        return "성공", f"AUC 유지({d_auc:+.4f}) + " + " / ".join(better)
    return "부분성공", (f"AUC 유지({d_auc:+.4f}) / 캘리브레이션 무변화 "
                        f"(상관 {d_corr:+.4f}, MAPE {d_mape:+.2f}%p 모두 2σ 내)")


# ══════════════════════════════════════════════════════════════════════

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--calib", default="platt_train",
                    choices=["raw", "prior", "platt_train", "platt_dev"])
    a = ap.parse_args()

    results = json.loads((OUT_DIR / "d_axis_results.json").read_text(encoding="utf-8"))
    gate1 = json.loads(
        (config.VALIDATION_DIR / "D_axis_gate1.json").read_text(encoding="utf-8"))
    gate1_pass = bool(gate1["all_pass"])

    by_sc: dict[str, list] = {}
    for r in results:
        by_sc.setdefault(r["scenario"], []).append(r)
    summary = summarize(results, a.calib)
    alt = {s["scenario"]: s for s in summarize(results, "platt_dev")}
    base = next(s for s in summary if s["scenario"] == "D0")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    p_cal = OUT_DIR / "d_axis_calibration_curve.png"
    p_mon = OUT_DIR / "d_axis_monthly_pd.png"
    try:
        plt.rcParams["font.family"] = ["Malgun Gothic", "DejaVu Sans"]
        plt.rcParams["axes.unicode_minus"] = False
        plot_calibration_curve(by_sc, a.calib, p_cal)
        plot_monthly(by_sc, a.calib, p_mon)
        figs_ok = True
    except Exception as e:                                   # noqa: BLE001
        print(f"[warn] 그림 생성 실패: {e}")
        figs_ok = False

    # ── 0 비율 (게이트 1 G1-5b) ──────────────────────────────────
    zero = {t["interaction"]: t for t in gate1["g1_5_detail"]["per_interaction"]}

    L: list[str] = []
    w = L.append
    w("# STAGE 6 D축 — 거시 결합 방식 Ablation 결과")
    w("")
    import datetime as _dt
    import os as _os
    _ran = _dt.datetime.fromtimestamp(
        _os.path.getmtime(OUT_DIR / "d_axis_results.json")).strftime("%Y-%m-%d")
    _seeds = sorted({r["seed"] for r in results})
    _scs = [x["scenario"] for x in summary]
    w(f"실행일: {_ran} · 규제 **{results[0].get('reg_variant', 'R2')}** "
      f"(A/B/C축과 동일) · 시드 {len(_seeds)}회 "
      f"({'/'.join(str(x) for x in _seeds)})")
    w(f"시나리오: {' · '.join(_scs)}")
    w("기준서: `eda_pipeline/output/validation/D_AXIS_SUCCESS_CRITERIA.md` (**개정 R1**)")
    w("게이트 1: `eda_pipeline/output/validation/D_AXIS_GATE1_RESULT.md` — "
      f"**{'8/8 통과' if gate1_pass else '미통과'}**")
    w(f"재현: `python -m eda_pipeline.step34_d_axis --run "
      f"{' '.join(_scs)} --seeds {','.join(str(x) for x in _seeds)}`"
      f" (인터프리터는 `data_preprocessing.md` 의 '재현 방법' 절 참조)")
    _g1_age = _dt.datetime.fromtimestamp(
        _os.path.getmtime(config.VALIDATION_DIR / "D_axis_gate1.json")
    ).strftime("%Y-%m-%d")
    w(f"게이트 1 산출일: {_g1_age}"
      + ("" if _g1_age >= _ran else
         "  ⚠ **이 실행보다 오래됐다** — 거시 원천이 바뀌었으면 "
         "`step33_macro_gate1` 을 다시 돌릴 것"))
    _mac = config.macro_input_path()
    w(f"거시 원천: `{_mac.name}` (갱신 "
      f"{_dt.datetime.fromtimestamp(_os.path.getmtime(_mac)):%Y-%m-%d})"
      f" · 패널 `{results[0].get('panel') or gate1.get('panel', '(미기록)')}`"
      f"{'' if results[0].get('panel') else ' (게이트 1 기록 기준)'}")
    w("원자료: `d_axis/d_axis_results.json` · `d_axis/d_axis_summary.json`")
    w("세대 이력·정정 내역·미결 항목: `PENDING_REVALIDATION.md`")
    w("")
    w("---")
    w("")
    w("## 0. 이 표를 읽는 법")
    w("")
    w("> **AUC 로 거시를 판정하지 않는다.** AUC 는 동일 시점 내 순위 지표이고,")
    w("> 거시는 모든 기업을 같은 방향으로 이동시켜 순위를 거의 바꾸지 않는다.")
    w("> 거시의 가치는 AUC 오른쪽 컬럼(PD-부도율 상관 / 건수 MAPE / Brier)에 있다.")
    w("")
    w("> ★ **`rate_shock_x_leverage` 는 정책금리 동결 구간에서 구조적으로 0 이 된다.**")
    w("> 이 항의 gain 이 낮게 나오더라도 '금리 경로가 무의미하다'는 뜻이 아니라")
    w("> '분석 기간의 절반이 금리 변동이 없는 구간'이라는 뜻이다.")
    _rs = zero.get("rate_shock_x_leverage")
    if _rs:
        _rsv = _rs.get("zero_shock_row_pct_valid")
        # 행수는 결과 원자료에서 그대로 읽는다. 반올림된 %로 역산하면
        # 없는 정밀도가 생긴다 (역산값 312,320 vs 실제 312,334).
        _rsn = by_sc["D0"][0].get("n_valid")
        if _rsv is not None:
            w(f"> 실측: Valid"
              + (f" {int(_rsn):,}행 중" if _rsn else "")
              + f" **{float(_rsv):.2f}%** 에서 이 항이 0.")
    w("> gain 은 반드시 아래 §3 의 '0 비율' 컬럼과 함께 읽는다.")
    w("")
    w("### 확률 보정")
    w("")
    w(f"결과표의 캘리브레이션 지표는 **`{a.calib}`** 적용 후 값이다. "
      "AUC 는 단조변환에 불변이라 보정과 무관하다.")
    w("")
    w("| 방식 | 적합 구간 | D0 평균 PD | 채택 |")
    w("|---|---|---:|:---:|")
    mp = base["mean_pd"]
    w(f"| 실제 부도율 (Valid) | — | **{base['actual_rate_valid'] * 100:.4f}%** | — |")
    w(f"| `raw` (보정 없음) | — | {mp['raw'] * 100:.4f}% | 대조군 |")
    w(f"| `prior` (해석적 역변환) | Train spw | {mp['prior'] * 100:.4f}% | 부보정 |")
    w(f"| `platt_train` | Train ~202309 | {mp['platt_train'] * 100:.4f}% | "
      f"{'**주보정**' if a.calib == 'platt_train' else '기록'} |")
    w(f"| `platt_dev` | Dev 202310~202312 | {mp['platt_dev'] * 100:.4f}% | "
      f"{'**주보정**' if a.calib == 'platt_dev' else '참고'} |")
    w("")
    w("- `prior correction` 은 가중 학습이 부풀린 양성 오즈의 해석적 역변환이다"
      " (`p/(p+(1-p)·spw)`). 적합 파라미터가 없어 과적합이 불가능하지만,"
      " R2 규제(`num_leaves=7, reg_alpha=5, reg_lambda=5`)로 트리 확률이 수축돼 있어"
      " **과소보정된다.**")
    _d0r = by_sc["D0"][0]
    _rate_tr = _d0r["pos_train"] / _d0r["n_train"] * 100
    _rate_dv = _d0r["pos_dev"] / _d0r["n_dev"] * 100
    _rate_va = _d0r["rate_valid"] * 100
    w("- `platt_train` 은 기준서의 *\"보정은 Train 구간에서만 학습해 Valid 에 적용\"* 을"
      " 문자 그대로 만족한다. **D0 에서 평균 PD 가 실제보다 낮게 나오는 것은 결함이"
      " 아니라 측정 그 자체다** — "
      f"Train 기저율 {_rate_tr:.4f}% 에서 Valid {_rate_va:.4f}% 로의"
      " 상승분을 기업 고유 피처만으로는 따라가지 못한다는 뜻이고, 거시가 메워야"
      " 하는 지점이 정확히 여기다.")
    w("- `platt_dev` 는 Dev 가 Valid 와 시기가 인접해 기저율이 비슷하므로"
      f" (Dev {_rate_dv:.4f}% vs Valid {_rate_va:.4f}%) 절편이 Valid 기저율을 대신"
      " 알려 주는 효과가 있다. 거시가 없어도 캘리브레이션이 좋아 보여 판정이"
      " 무뎌지므로 참고용으로만 둔다. §5 에 로버스트니스로 병기한다.")
    w("- 보정 방식은 **전 시나리오에 동일하게** 적용되므로 시나리오 간 비교는 공정하다.")
    w("")
    w("---")
    w("")

    # ── 메인 결과표 ──────────────────────────────────────────────
    w("## 1. 시나리오 결과표")
    w("")
    w("| ID | 구성 | 피처수 | Valid AUC(σ) | ΔAUC | 거시gain% | "
      "PD-부도율 상관 | 건수 MAPE | Brier | 판정 |")
    w("|---|---|---:|---:|---:|---:|---:|---:|---:|:---:|")
    verdicts = {}
    for s in summary:
        v, why = verdict(s, base, gate1_pass)
        verdicts[s["scenario"]] = (v, why)
        d_auc = "—" if s["scenario"] == "D0" else f"{s['delta_auc']:+.4f}"
        w(f"| **{s['scenario']}** | {s['desc']} | {s['n_features']} | "
          f"{s['valid_auc']:.4f} ({s['valid_auc_sd']:.4f}) | {d_auc} | "
          f"{s['macro_gain_pct']:.2f} | "
          f"{s['corr_pd_rate']:+.4f} ({s['corr_pd_rate_sd']:.4f}) | "
          f"{s['count_mape_pct']:.2f}% ({s['count_mape_pct_sd']:.2f}) | "
          f"{s['brier']:.6f} | {v} |")
    w("")
    w(f"- 노이즈 규칙: `|ΔAUC| < {NOISE_BAND}` 은 **차이 없음**으로 기술한다.")
    w("- 괄호 안은 시드 3회 표준편차.")
    w("- 거시gain% = (거시 원본 + 상호작용) gain 합계 / 전체 gain.")
    ac12_contamination_note(by_sc, w)
    w("")

    # ── 게이트 2 ────────────────────────────────────────────────
    w("---")
    w("")
    w("## 2. 게이트 2 — 거시 작동 여부 (구조 검증)")
    w("")
    d3 = next((s for s in summary if s["scenario"] == "D3"), None)
    d1 = next((s for s in summary if s["scenario"] == "D1"), None)
    d2 = next((s for s in summary if s["scenario"] == "D2"), None)

    w("### G2-1 — D3 의 거시 gain 합계 비중")
    w("")
    if d3:
        ok = d3["macro_gain_pct"] > REFERENCE_MACRO_GAIN_PCT
        w(f"| 구분 | 거시 gain 합계 |")
        w(f"|---|---:|")
        w(f"| 원본 모델 (`lgbm_12m_model.txt`, 누수 포함) | {REFERENCE_MACRO_GAIN_PCT:.2f}% |")
        w(f"| **D3 (거시 원본 + 상호작용 8종)** | "
          f"**{d3['macro_gain_pct']:.2f}%** (σ {d3['macro_gain_pct_sd']:.2f}) |")
        w("")
        w(f"**판정: {'통과' if ok else '미달'}** — "
          f"원본 대비 {d3['macro_gain_pct'] - REFERENCE_MACRO_GAIN_PCT:+.2f}%p")
    w("")

    w("### G2-2 — 상호작용 8종 중 gain 상위 30위 진입 개수")
    w("")
    if d3:
        n30 = d3["n_interaction_in_top30"]
        w(f"D3 기준 **{n30}개** (기대 3개 이상) → "
          f"**{'통과' if n30 >= 3 else '미달'}**")
    w("")

    w("### G2-3 — D1(거시 원본만) vs D2(상호작용만)")
    w("")
    if d1 and d2:
        w("| ID | 구성 | 거시 피처수 | 거시gain% | Valid AUC | PD-부도율 상관 | 건수 MAPE |")
        w("|---|---|---:|---:|---:|---:|---:|")
        for s in (d1, d2):
            w(f"| {s['scenario']} | {s['desc']} | {s['n_macro_features']} | "
              f"{s['macro_gain_pct']:.2f}% | {s['valid_auc']:.4f} | "
              f"{s['corr_pd_rate']:+.4f} | {s['count_mape_pct']:.2f}% |")
        w("")
        d2_wins = d2["macro_gain_pct"] > d1["macro_gain_pct"]
        w(f"**D2 {'>' if d2_wins else '<='} D1** "
          f"({d2['macro_gain_pct']:.2f}% vs {d1['macro_gain_pct']:.2f}%) → "
          f"{'STAGE 5 상호작용 설계가 옳았다는 증거다.' if d2_wins else '★ 상호작용 설계를 재검토해야 한다.'}")
        w("")
        w("주의: D1 은 거시 91개, D2 는 상호작용 8개다. **피처 1개당 기여**로 보면 "
          f"D1 {d1['macro_gain_pct'] / max(d1['n_macro_features'], 1):.3f}%p, "
          f"D2 {d2['macro_gain_pct'] / max(d2['n_macro_features'], 1):.3f}%p 다.")
    w("")

    w("### G2-4 — 거시 변수 gain 상위 10개와 경제 채널")
    w("")
    if d3 and by_sc.get("D3"):
        r0 = by_sc["D3"][0]
        w("D3 / 시드 42 기준.")
        w("")
        w("| 순위(전체) | 거시 변수 | gain% | 경제 채널 |")
        w("|---:|---|---:|---|")
        for m in r0["macro_gain_top10"]:
            w(f"| {m['rank']} | `{m['feature']}` | {m['gain_pct']:.3f} | "
              f"{channel_of(m['feature'])} |")
    w("")

    # ── 상호작용 gain + 0 비율 ──────────────────────────────────
    w("---")
    w("")
    w("## 3. 상호작용항 gain — **반드시 0 비율과 함께 읽는다**")
    w("")
    if by_sc.get("D3"):
        r0 = by_sc["D3"][0]
        w("| 상호작용 | 경제 채널 | gain% | 순위(전체) | **충격0 개월** | "
          "**충격0 행%** | **충격0 Valid행%** | 노출도공백 |")
        w("|---|---|---:|---:|---:|---:|---:|---:|")
        for it in r0["interaction_gain"]:
            f = it["feature"]
            z = zero.get(f, {})
            w(f"| `{f}` | {INTERACTION_CHANNEL.get(f, '—')} | {it['gain_pct']:.3f} | "
              f"{it['rank']} | {z.get('n_zero_shock', '—')} | "
              f"{z.get('zero_shock_row_pct', 0):.2f}% | "
              f"{z.get('zero_shock_row_pct_valid', 0):.2f}% | "
              f"{z.get('n_exposure_empty', 0)}개월 |")
        w("")
        # ★ 수치를 하드코딩하지 않는다. 게이트 1 기록과 gain 표에서 읽는다.
        _rsz = zero.get("rate_shock_x_leverage", {})
        _rsp = _rsz.get("zero_shock_row_pct_valid")
        if _rsp is not None:
            w(f"> `rate_shock_x_leverage` 의 gain 을 다른 항과 나란히 비교하면 안 된다. "
              f"Valid 의 **{float(_rsp):.2f}%** 에서 이 항은 전 기업 0 이고, 트리는 "
              f"그 구간에서 이 변수로 분기할 수 없다.")
        # 나머지 금리 경로 항의 상태를 '커버한다' 고 단정하지 않고 수치로 적는다.
        #   초판은 "credit_spread_x_lev / liq_spread_x_shortdebt 가 커버한다" 고 썼다.
        #   2026-09-01 정정에서 그 논거는 무효 판정을 받았다 (credit_spread 가
        #   신용스프레드가 아니라 기간스프레드였고, liq 항은 gain 0.015 / 96위였다).
        #   매핑이 정정된 뒤에도 '커버' 여부는 gain 과 0 비율로 판단할 일이다.
        _other = [it for it in r0["interaction_gain"]
                  if it["feature"] in ("credit_spread_x_lev", "liq_spread_x_shortdebt")]
        if _other:
            _txt = " · ".join(
                f"`{it['feature']}` gain {it['gain_pct']:.3f} / {it['rank']}위 / "
                f"충격 0 인 달 {zero.get(it['feature'], {}).get('n_zero_shock', '—')}개"
                for it in _other)
            w(f"> 같은 금리 경로의 다른 항: {_txt}. "
              f"이 수치만으로 금리 경로가 메워졌다고 볼 수는 없다 — 판단은 "
              f"§5 의 부호 안정성과 함께 해야 한다.")
    w("")

    # ── 게이트 3 ────────────────────────────────────────────────
    w("---")
    w("")
    w("## 4. 게이트 3 — 실질 가치 (캘리브레이션)")
    w("")
    w("| ID | 지표 | D0 | " + " | ".join(s["scenario"] for s in summary if s["scenario"] != "D0") + " |")
    w("|---|---|---:|" + "---:|" * (len(summary) - 1))
    others = [s for s in summary if s["scenario"] != "D0"]
    w(f"| G3-1 | Valid AUC | {base['valid_auc']:.4f} | "
      + " | ".join(f"{s['valid_auc']:.4f} ({s['delta_auc']:+.4f})" for s in others) + " |")
    w(f"| G3-2 | PD-부도율 상관 ★ | {base['corr_pd_rate']:+.4f} | "
      + " | ".join(f"{s['corr_pd_rate']:+.4f} ({s['corr_pd_rate'] - base['corr_pd_rate']:+.4f})"
                   for s in others) + " |")
    w(f"| G3-3 | 건수 MAPE ★ | {base['count_mape_pct']:.2f}% | "
      + " | ".join(f"{s['count_mape_pct']:.2f}% ({s['count_mape_pct'] - base['count_mape_pct']:+.2f})"
                   for s in others) + " |")
    w(f"| G3-4 | Brier | {base['brier']:.6f} | "
      + " | ".join(f"{s['brier']:.6f} ({s['brier'] - base['brier']:+.6f})" for s in others) + " |")
    w(f"| G3-5 | ECE (대각선 평균거리) | {base['ece']:.6f} | "
      + " | ".join(f"{s['ece']:.6f} ({s['ece'] - base['ece']:+.6f})" for s in others) + " |")
    w("")
    w("괄호 = D0 대비 변화. 상관은 클수록, MAPE·Brier·ECE 는 작을수록 좋다.")
    w("")
    w("### 시드 표준편차")
    w("")
    w("| ID | AUC σ | 상관 σ | MAPE σ | Brier σ | ECE σ |")
    w("|---|---:|---:|---:|---:|---:|")
    for s in summary:
        w(f"| {s['scenario']} | {s['valid_auc_sd']:.4f} | {s['corr_pd_rate_sd']:.4f} | "
          f"{s['count_mape_pct_sd']:.2f} | {s['brier_sd']:.6f} | {s['ece_sd']:.6f} |")
    w("")
    if figs_ok:
        w(f"![캘리브레이션 곡선]({p_cal.relative_to(config.VALIDATION_DIR).as_posix()})")
        w("")
        w(f"![월별 예측 PD]({p_mon.relative_to(config.VALIDATION_DIR).as_posix()})")
        w("")

    # ── 월별 상세 ───────────────────────────────────────────────
    w("### 월별 예측 PD vs 실제 부도율 (D0 vs D3, 시드 3회 평균)")
    w("")
    if by_sc.get("D0") and by_sc.get("D3"):
        m0 = by_sc["D0"][0]["calibration"]["monthly"][a.calib]
        w("| BASE_YM | 행수 | 실제 부도건수 | 실제 부도율 | D0 예측건수 | D3 예측건수 | "
          "D0 오차 | D3 오차 |")
        w("|---|---:|---:|---:|---:|---:|---:|---:|")
        for i, m in enumerate(m0):
            c0 = np.mean([r["calibration"]["monthly"][a.calib][i]["pred_cnt"]
                          for r in by_sc["D0"]])
            c3 = np.mean([r["calibration"]["monthly"][a.calib][i]["pred_cnt"]
                          for r in by_sc["D3"]])
            act = m["actual_cnt"]
            e0 = (c0 - act) / act * 100 if act else float("nan")
            e3 = (c3 - act) / act * 100 if act else float("nan")
            w(f"| {m['ym']} | {m['n']:,} | {act} | {m['actual_rate'] * 100:.3f}% | "
              f"{c0:.1f} | {c3:.1f} | {e0:+.1f}% | {e3:+.1f}% |")
    w("")
    w("### 측정 근거 — 연도별 실제 부도율 (기준서)")
    w("")
    _yr, _yr_ok = yearly_default_rates()
    w("| 연도 | " + " | ".join(_yr) + " |")
    w("|---|" + "---:|" * len(_yr))
    w("| 실제 부도율 | " + " | ".join(f"{v:.3f}%" for v in _yr.values()) + " |")
    if not _yr_ok:
        w("")
        w("> ⚠ 패널을 읽지 못해 **폴백 상수**를 썼다 "
          "(`ACTUAL_YEARLY_FALLBACK`). 현재 패널의 실측값이 아니다.")
    w("")
    _yv = [v for v in _yr.values() if v]
    w(f"최저 대비 최고 **{max(_yv) / min(_yv):.1f}배 변동**. 거시가 설명해야 할 구간이다.")
    w("")

    # ── 진단 ────────────────────────────────────────────────────
    w("---")
    w("")
    w("## 5. ★ 원인 규명 — 거시-부도 관계의 부호가 Train 과 Valid 에서 뒤집힌다")
    w("")
    sign_rows, lag_rows, seg, n_months = macro_vs_default()
    w("거시 지표는 `BASE_YM` 하나당 값이 하나뿐이다. 따라서 모델이 거시로부터")
    w(f"배울 수 있는 **실질 표본은 행수 948,214 가 아니라 월 수 {n_months} 개**다.")
    w("그 {}개월 안에 금리 사이클이 한 번(2021 인상 개시 → 2022~23 급등 →".format(n_months))
    w("2024 동결 → 2024-12 인하 전환) 들어 있을 뿐이다.")
    w("")
    w("### 5-1. 월별 12개월 선행 부도율과 거시 지표의 상관")
    w("")
    w("| 거시 변수 | 경제 채널 | Train 상관 | Valid 상관 | 전체 | 부호 |")
    w("|---|---|---:|---:|---:|:---:|")
    for r in sign_rows:
        w(f"| `{r['col']}` | {r['channel']} | {r['train']:+.3f} | {r['valid']:+.3f} | "
          f"{r['all']:+.3f} | {'**★ 뒤집힘**' if r['flip'] else '유지'} |")
    w("")
    # ★ 서술의 수치를 하드코딩하지 않는다. 재실행마다 데이터에서 다시 읽는다.
    _rate = [r for r in sign_rows if r["channel"] == "금리-차입"]
    _flip = [r for r in _rate if r["flip"]]
    _br = next((r for r in sign_rows if r["col"] == "base_rate_diff12"), None)
    if _rate:
        if _flip and len(_flip) == len(_rate):
            w(f"**금리 계열 {len(_rate)}종이 전부 뒤집힌다.**")
        elif _flip:
            w(f"**금리 계열 {len(_rate)}종 중 {len(_flip)}종이 뒤집힌다** "
              f"({', '.join('`' + r['col'] + '`' for r in _flip)}).")
        else:
            w(f"**금리 계열 {len(_rate)}종은 부호가 유지된다.** "
              f"이 실행에서는 반전이 나타나지 않았다.")
    if _br is not None:
        _tail = (" 거의 완전한 부호 반전이다."
                 if _br["flip"] and min(abs(_br["train"]), abs(_br["valid"])) >= 0.5
                 else "")
        w(f"`base_rate_diff12` 는 Train **{_br['train']:+.3f}** / "
          f"Valid **{_br['valid']:+.3f}** 다.{_tail}")
    w("")
    w("| 구간 | 개월 | 12개월 선행 부도율 | `base_rate_diff12` |")
    w("|---|---:|---|---|")
    for lab in ("TRAIN", "DEV", "VALID"):
        v = seg[lab]
        w(f"| {lab} | {v['n_months']} | 평균 {v['rate_mean']:.3f}% "
          f"({v['rate_min']:.3f}~{v['rate_max']:.3f}%) | "
          f"평균 {v['base_rate_diff12_mean']:+.3f} "
          f"({v['base_rate_diff12_min']:+.3f}~{v['base_rate_diff12_max']:+.3f}) |")
    w("")
    w("### 5-2. 그래서 무슨 일이 벌어졌나")
    w("")
    w("1. 모델은 Train(2021~2023)에서 **\"금리가 오르면 부도가 는다\"** 를 배운다")
    w(f"   (`base_rate_diff12` 상관 "
      f"{_br['train']:+.3f}). 경제학적으로 맞는 관계다."
      if _br is not None else "   경제학적으로 맞는 관계다.")
    _d3 = next((x for x in summary if x["scenario"] == "D3"), None)
    _tr, _va = seg["TRAIN"], seg["VALID"]
    w(f"2. Valid 구간의 `base_rate_diff12` 평균은 "
      f"**{_va['base_rate_diff12_mean']:+.3f}** "
      f"({_va['base_rate_diff12_min']:+.3f}~{_va['base_rate_diff12_max']:+.3f}) 다"
      + (" — 금리가 **내려간다.** 모델은 배운 대로 **PD 를 낮춘다.**"
         if _va["base_rate_diff12_mean"] < 0 else "."))
    w(f"3. 같은 구간의 12개월 선행 부도율은 평균 {_va['rate_mean']:.3f}% "
      f"({_va['rate_min']:.3f}~{_va['rate_max']:.3f}%) 로, "
      f"Train 평균 {_tr['rate_mean']:.3f}% 보다 "
      + ("**높다**. 긴축 충격이 기업 재무를 갉아먹는 데 시간이 걸린다 — "
         "**부도는 거시에 후행한다.**"
         if _va["rate_mean"] > _tr["rate_mean"] else "낮다."))
    if _d3 is not None:
        w(f"4. 결과: 거시를 넣으면 PD-부도율 상관이 "
          f"D0 {base['corr_pd_rate']:+.3f} -> D3 {_d3['corr_pd_rate']:+.3f}, "
          f"건수 MAPE {base['count_mape_pct']:.2f}% -> "
          f"{_d3['count_mape_pct']:.2f}% 로 움직인다.")
    w("")
    def _mon_ends(sc: str):
        rows = by_sc.get(sc)
        if not rows:
            return None
        ms = [r["calibration"]["monthly"][a.calib] for r in rows]
        return (ms[0][0]["ym"], ms[0][-1]["ym"],
                float(np.mean([m[0]["pred_cnt"] for m in ms])),
                float(np.mean([m[-1]["pred_cnt"] for m in ms])),
                int(ms[0][0]["actual_cnt"]), int(ms[0][-1]["actual_cnt"]))

    _e3, _e0 = _mon_ends("D3"), _mon_ends("D0")
    if _e3 and _e0:
        _ym0, _ym1, _p3a, _p3b, _a0c, _a1c = _e3
        _p0a, _p0b = _e0[2], _e0[3]
        w(f"§4 의 월별 표가 이것을 그대로 보여 준다. D3 예측 부도건수는 "
          f"{_ym0} {_p3a:.1f}건 -> {_ym1} {_p3b:.1f}건으로 "
          f"**{'줄어드는데' if _p3b < _p3a else '늘어나는데'}**, "
          f"실제는 {_a0c}건 -> {_a1c}건으로 "
          f"**{'늘었다' if _a1c > _a0c else '줄었다'}**. "
          f"D0(거시 없음)는 같은 구간에서 {_p0a:.1f} -> {_p0b:.1f} 다.")
        w("")
    w("**상호작용항도 이 문제를 못 고친다.** STAGE 5 의 상호작용 설계가 해결한 것은")
    w("'시점 더미로의 퇴화'였다. 그런데 상호작용항은 같은 거시 충격에 기업 노출도를")
    w("곱한 것이라 **충격의 부호를 그대로 물려받는다.** 금리가 내려가면")
    w("`rate_shock_x_leverage` 도 음수가 되고, 차입 의존도가 높은 기업일수록 PD 가")
    w("더 크게 내려간다. 방향이 틀린 신호를 더 정교하게 배분한 셈이다.")
    w("")
    w("### 5-3. 시차를 더 주면 부호가 맞춰지는가 (가설, 검증 안 됨)")
    w("")
    w("거시에 추가 시차 k 개월을 주고 상관을 다시 쟀다.")
    w("")
    w("| 거시 변수 | 구간 | " + " | ".join(f"k={k}" for k in LAG_GRID) + " |")
    w("|---|---|" + "---:|" * len(LAG_GRID))
    for r in lag_rows:
        w(f"| `{r['col']}` | Train | "
          + " | ".join(f"{r['train'][k]:+.3f}" for k in LAG_GRID) + " |")
        w(f"| | Valid | "
          + " | ".join(f"{r['valid'][k]:+.3f}" for k in LAG_GRID) + " |")
    w("")
    # 부호가 맞는 k 를 표에서 찾아 쓴다. 하드코딩하지 않는다.
    def _agree_ks(r) -> list[int]:
        out = []
        for k in LAG_GRID:
            t, v = r["train"].get(k), r["valid"].get(k)
            if t is None or v is None:
                continue
            if not (np.isnan(t) or np.isnan(v)) and t * v > 0:
                out.append(k)
        return out

    _any_agree = False
    for r in lag_rows:
        ks = _agree_ks(r)
        if not ks:
            w(f"- `{r['col']}` — 어느 k 에서도 Train/Valid 부호가 맞지 않는다.")
            continue
        _any_agree = True
        _kk = ks[-1]
        w(f"- `{r['col']}` — 부호가 맞는 k: {', '.join(str(k) for k in ks)} "
          f"(k={_kk} 에서 Train {r['train'][_kk]:+.3f} / "
          f"Valid {r['valid'][_kk]:+.3f})")
    w("")
    if _any_agree:
        w("충격이 부도로 이어지는 데 시간이 걸린다는 뜻이고, 타겟이 이미 12개월")
        w("선행이므로 충격에서 부도까지 실질 시차는 여기에 12개월을 더한 값이 된다.")
        w("경제학적으로 무리한 값은 아니다.")
        w("")
    w("**그러나 이것을 지금 채택해서는 안 된다:**")
    w("")
    w("- k 를 **Valid 상관을 보고 골랐다.** 그 자체가 홀드아웃 오염이다.")
    w("- 판단 근거가 되는 표본이 Valid 17개월 / Train 33개월뿐이다. 사이클이 하나라")
    w(f"  {n_months}개월 안에서 고른 시차는 그 한 번의 사이클에 과적합된다.")
    w("- k=24 면 거시 원천이 202101 부터이므로 패널 202301 이전 행에 거시가 없다.")
    w("  Train 의 절반이 날아간다.")
    w("")
    w("→ **제안만 하고 승인을 받는다. 임의로 적용하지 않는다.**")
    w("   검증하려면 최소 2개 이상의 금리 사이클을 덮는 기간(2008 금융위기,")
    w("   2010년대 저금리기 포함)으로 거시와 부도 이력을 함께 확장해야 한다.")
    w("")
    w("### 5-4. 부호가 유지되는 지표도 있다")
    w("")
    stable = [r for r in sign_rows if not r["flip"]]
    if stable:
        w("| 거시 변수 | 경제 채널 | Train | Valid |")
        w("|---|---|---:|---:|")
        for r in stable:
            w(f"| `{r['col']}` | {r['channel']} | {r['train']:+.3f} | {r['valid']:+.3f} |")
        w("")
        _bsi = next((r for r in stable if r["col"] == "BSI_mfg_biz_yoy"), None)
        if _bsi is not None:
            w(f"`BSI_mfg_biz_yoy`(제조업 업황 BSI)는 Train {_bsi['train']:+.3f} / "
              f"Valid {_bsi['valid']:+.3f} 로")
            w("**부호와 크기가 모두 안정적**이다. 심리지수는 금리처럼 정책 결정으로")
            w("계단 변동하지 않고, 기업이 체감하는 업황을 동행적으로 반영하기 때문으로")
            w("보인다. 거시를 다시 설계한다면 **가격 변수(금리·환율)보다 심리·업황**")
            w("**지표를 축으로 삼는 편**이 유망하다는 단서다. 다만 이것도 위와 같은")
            w("표본 한계를 공유하므로 단서 이상으로 취급하지 않는다.")
    w("")

    # ── 로버스트니스 ────────────────────────────────────────────
    w("---")
    w("")
    w("## 6. 로버스트니스 — 보정 방식을 바꾸면")
    w("")
    w("| ID | `platt_train` 상관 | `platt_dev` 상관 | `platt_train` MAPE | `platt_dev` MAPE |")
    w("|---|---:|---:|---:|---:|")
    for s in summary:
        b = alt.get(s["scenario"])
        w(f"| {s['scenario']} | {s['corr_pd_rate']:+.4f} | "
          f"{b['corr_pd_rate']:+.4f} | {s['count_mape_pct']:.2f}% | "
          f"{b['count_mape_pct']:.2f}% |")
    w("")
    w("PD-부도율 상관은 단조 보정에 **불변**이다 (월별 평균은 엄밀히는 아니지만 "
      "실질적으로 순위가 유지된다). 건수 MAPE 는 수준(level) 지표라 보정 방식에 "
      "민감하다. 두 보정에서 **부호가 같은 결론**이 나오면 판정이 견고하다.")
    w("")

    # ── 최종 판정 ───────────────────────────────────────────────
    w("---")
    w("")
    w("## 7. 최종 판정")
    w("")
    w("기준서 판정 규칙:")
    w("")
    w("| 판정 | 조건 |")
    w("|---|---|")
    w("| 성공 | 게이트 1 전부 통과 + G3-1 유지 + (G3-2 **또는** G3-3 개선) |")
    w("| 부분성공 | 게이트 1 통과 + AUC 유지 + 캘리브레이션 무변화 |")
    w(f"| 실패 | AUC 가 {NOISE_BAND} 초과 하락하거나 캘리브레이션 악화 |")
    w("")
    w("| ID | 판정 | 근거 |")
    w("|---|:---:|---|")
    for s in summary:
        v, why = verdicts[s["scenario"]]
        w(f"| {s['scenario']} | **{v}** | {why} |")
    w("")

    REPORT.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"보고서 저장: {REPORT}")
    if figs_ok:
        print(f"그림: {p_cal.name} / {p_mon.name}")


if __name__ == "__main__":
    main()
