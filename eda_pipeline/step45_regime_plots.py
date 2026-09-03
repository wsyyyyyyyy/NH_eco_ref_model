"""
step45_regime_plots.py — 거시 국면 그림 2종
======================================================================
  1) default_rate_vs_base_rate.png
     주축: 월별 실제 부도율(IS_BUDO_12M, 12개월 선행) 2021-01~2025-05
     보조축: base_rate 수준
     배경: 저금리기 / 긴축기 / 인하기 3분할 + 구간 평균 부도율 텍스트
     Train/Valid 경계선
  2) lag_correlation_curve.png
     x: k(0~24개월), y: corr(부도율[t], base_rate[t-k])
     k=4 단봉을 표시. 절대값이 아니라 '형태'를 보여주는 것이 목적.

원자료: eda_pipeline/output/validation/A3_macro_regime.json (step42_macro_regime 산출)
저장:  docs/images/

    python -m eda_pipeline.step45_regime_plots
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import matplotlib
matplotlib.use("Agg")
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt

_avail = {f.name for f in fm.fontManager.ttflist}
for _f in ("Malgun Gothic", "NanumGothic", "AppleGothic", "Noto Sans CJK KR"):
    if _f in _avail:
        plt.rcParams["font.family"] = _f
        break
plt.rcParams["axes.unicode_minus"] = False

SRC = _ROOT / "eda_pipeline" / "output" / "validation" / "A3_macro_regime.json"
OUT_DIR = _ROOT / "docs" / "images"

REGIME_COLOR = {"저금리기": "#e8f0fe", "긴축기": "#fdeaea", "인하기": "#eafaf0"}


def _ym_to_idx(ym: str, months: list[str]) -> int:
    return months.index(ym)


def main() -> None:
    d = json.loads(SRC.read_text(encoding="utf-8"))
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    m = d["monthly_default_rate"]
    months = [r["BASE_YM"] for r in m]
    rate = [r["default_rate_pct"] for r in m]
    brate = [r["base_rate"] for r in m]
    x = list(range(len(months)))

    regimes = d["regime_default_rate_primary"]     # 3개, period="YYYYMM~YYYYMM"

    # ── 그림 1 ─────────────────────────────────────────────────────
    fig, ax1 = plt.subplots(figsize=(14, 6))
    ax2 = ax1.twinx()

    lo, hi = min(rate) * 0.9, max(rate) * 1.08
    ax1.set_ylim(lo, hi)
    for rg in regimes:
        s, e = rg["period"].split("~")
        i0, i1 = _ym_to_idx(s, months), _ym_to_idx(e, months)
        ax1.axvspan(i0 - 0.5, i1 + 0.5, color=REGIME_COLOR.get(rg["regime"], "#f0f0f0"),
                    zorder=0)
        mid = (i0 + i1) / 2
        ax1.text(mid, lo + (hi - lo) * 0.93,
                 f"{rg['regime']}  (평균 {rg['default_rate_pct']:.3f}%)",
                 ha="center", va="top", fontsize=10, fontweight="bold", color="#333")

    ax1.plot(x, rate, color="#c0392b", linewidth=2.4, marker="o", markersize=3,
             label="월별 실제 부도율 (12M 선행, %)")
    ax2.plot(x, brate, color="#2c3e50", linewidth=1.8, linestyle="--",
             label="기준금리 (base_rate, %)")

    # Train/Valid 경계 (202401 직전)
    if "202401" in months:
        vi = _ym_to_idx("202401", months)
        ax1.axvline(vi - 0.5, color="#7f8c8d", linewidth=1.6, linestyle=":")
        ax1.text(vi - 0.4, lo + (hi - lo) * 0.05, "Train | Valid", fontsize=9,
                 color="#7f8c8d", rotation=90, va="bottom")

    step = max(1, len(months) // 14)
    ax1.set_xticks(x[::step])
    ax1.set_xticklabels([months[i] for i in x[::step]], rotation=45, ha="right",
                        fontsize=8)
    ax1.set_ylabel("월별 실제 부도율 (%)", color="#c0392b")
    ax2.set_ylabel("기준금리 (%)", color="#2c3e50")
    ax1.set_title("월별 실제 부도율 vs 기준금리\n금리 상승 뒤 부도율이 시차를 두고 따라 오른다 (k=4개월 상관 최대)",
                  fontsize=12, fontweight="bold")
    ax1.grid(alpha=0.25)
    l1, lab1 = ax1.get_legend_handles_labels()
    l2, lab2 = ax2.get_legend_handles_labels()
    ax1.legend(l1 + l2, lab1 + lab2, loc="upper left", fontsize=9)
    fig.tight_layout()
    p1 = OUT_DIR / "default_rate_vs_base_rate.png"
    fig.savefig(p1, dpi=120, bbox_inches="tight")
    plt.close(fig)
    print("저장:", p1.relative_to(_ROOT))

    # ── 그림 2 ─────────────────────────────────────────────────────
    lc = d["lag_correlation"]["by_lag"]
    ks = [r["lag_months"] for r in lc]
    cs = [r["corr"] for r in lc]
    amax = d["lag_correlation"]["argmax"]

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(ks, cs, color="#2980b9", linewidth=2.2, marker="o", markersize=4)
    ax.scatter([amax["lag_months"]], [amax["corr"]], color="#c0392b", zorder=5, s=70)
    ax.annotate(f"k={amax['lag_months']}  r={amax['corr']:.3f}  (단봉)",
                (amax["lag_months"], amax["corr"]),
                textcoords="offset points", xytext=(12, 6), fontsize=10,
                fontweight="bold", color="#c0392b")
    ax.axvline(amax["lag_months"], color="#c0392b", linewidth=1, linestyle=":")
    ax.set_xlabel("시차 k (개월)  —  corr(부도율[t], base_rate[t-k])")
    ax.set_ylabel("피어슨 상관계수")
    ax.set_title("시차 상관 — 절대값이 아니라 k=4 에서 꺾이는 '형태'가 근거다",
                 fontsize=12, fontweight="bold")
    ax.set_xticks(range(0, 25, 2))
    ax.grid(alpha=0.3)
    ax.text(0.02, 0.05,
            "두 시계열이 공통 우상향 추세라 k=0 에서도 r=0.88 수준.\n"
            "상관의 크기가 아니라 k=4 단봉·이후 단조 감소가 후행 구조의 근거.",
            transform=ax.transAxes, fontsize=8, color="#555",
            va="bottom", bbox=dict(boxstyle="round", fc="#f8f8f8", ec="#ddd"))
    fig.tight_layout()
    p2 = OUT_DIR / "lag_correlation_curve.png"
    fig.savefig(p2, dpi=120, bbox_inches="tight")
    plt.close(fig)
    print("저장:", p2.relative_to(_ROOT))


if __name__ == "__main__":
    main()
