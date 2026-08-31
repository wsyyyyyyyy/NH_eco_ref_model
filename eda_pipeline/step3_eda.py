"""
======================================================================
Step 3 — EDA 분석 및 HTML 리포트 생성
======================================================================
통합된 패널 데이터(nh_panel_full.csv)에 대해 탐색적 데이터 분석을 수행하고
시각화 이미지와 HTML 리포트를 생성합니다.

사용법:
    from eda_pipeline.step3_eda import EDAReporter
    reporter = EDAReporter(panel_df, output_dir="eda_pipeline/output")
    reporter.run()
"""

from __future__ import annotations

import logging
import warnings
from pathlib import Path
from typing import Optional

import matplotlib
matplotlib.use("Agg")  # 비대화형 백엔드
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap

warnings.filterwarnings("ignore")
log = logging.getLogger(__name__)

# ── 한글 폰트 설정 ──────────────────────────────────────────────────
def _set_korean_font() -> None:
    """Windows 시스템 한글 폰트를 자동 감지하여 적용합니다."""
    candidates = ["Malgun Gothic", "NanumGothic", "AppleGothic", "Noto Sans CJK KR"]
    available = {f.name for f in fm.fontManager.ttflist}
    for font in candidates:
        if font in available:
            plt.rcParams["font.family"] = font
            break
    plt.rcParams["axes.unicode_minus"] = False

_set_korean_font()

# ── 팔레트 ───────────────────────────────────────────────────────────
PRIMARY   = "#4F6EF5"
SECONDARY = "#F5A623"
DANGER    = "#E84040"
SUCCESS   = "#27AE60"
DARK      = "#1A1D2E"
LIGHT_BG  = "#F0F4FF"
CMAP_CORR = LinearSegmentedColormap.from_list(
    "custom_rg", ["#E84040", "#FFFFFF", "#4F6EF5"]
)


class EDAReporter:
    """
    통합 패널 데이터에 대한 EDA를 수행하고
    이미지 + HTML 리포트를 생성합니다.
    """

    def __init__(
        self,
        panel: pd.DataFrame,
        output_dir: str | Path | None = None,
    ) -> None:
        self.panel = panel
        from eda_pipeline import config as _cfg
        self.output_dir = Path(output_dir) if output_dir is not None else _cfg.OUTPUT_DIR
        self.plots_dir = self.output_dir / "eda_plots"
        self.plots_dir.mkdir(parents=True, exist_ok=True)
        self._report_sections: list[str] = []

    # ================================================================
    # Public
    # ================================================================

    def run(self) -> None:
        """전체 EDA를 실행하고 HTML 리포트를 저장합니다."""
        log.info("=" * 60)
        log.info("[EDA] 분석 시작 — Panel Shape: %s", self.panel.shape)
        log.info("=" * 60)

        self._section_overview()
        self._section_missing()
        self._section_target_distribution()
        self._section_numeric_distributions()
        self._section_categorical()
        self._section_timeseries()
        self._section_correlation()
        self._section_default_trajectory()

        self._export_html()
        self._export_stats_csv()
        log.info("[EDA] 완료 — 리포트: %s", self.output_dir / "eda_report.html")

    # ================================================================
    # Section 1: 데이터 개요
    # ================================================================

    def _section_overview(self) -> None:
        df = self.panel
        n_companies = df["V_BZNO"].nunique()
        n_months    = df["BASE_YM"].nunique()
        n_defaults  = df["IS_BUDO_IN_SPINE_YN"].sum() if "IS_BUDO_IN_SPINE_YN" in df.columns else 0
        default_rate = n_defaults / len(df) * 100

        train_rows = (df["SPLIT"] == "TRAIN").sum() if "SPLIT" in df.columns else 0
        valid_rows = (df["SPLIT"] == "VALID").sum() if "SPLIT" in df.columns else 0

        dtype_counts = df.dtypes.value_counts().to_dict()
        dtype_str = ", ".join(f"{str(k)}: {v}" for k, v in dtype_counts.items())

        html = f"""
<section id="overview">
  <h2>📊 1. 데이터 개요</h2>
  <div class="stats-grid">
    <div class="stat-card"><div class="stat-value">{len(df):,}</div><div class="stat-label">전체 행수</div></div>
    <div class="stat-card"><div class="stat-value">{len(df.columns):,}</div><div class="stat-label">전체 컬럼수</div></div>
    <div class="stat-card"><div class="stat-value">{n_companies:,}</div><div class="stat-label">차주 수</div></div>
    <div class="stat-card"><div class="stat-value">{n_months}</div><div class="stat-label">관측 월수</div></div>
    <div class="stat-card highlight"><div class="stat-value">{n_defaults:,}</div><div class="stat-label">부도 건수</div></div>
    <div class="stat-card highlight"><div class="stat-value">{default_rate:.3f}%</div><div class="stat-label">전체 부도율</div></div>
    <div class="stat-card"><div class="stat-value">{train_rows:,}</div><div class="stat-label">Train 행수 (≤2023)</div></div>
    <div class="stat-card"><div class="stat-value">{valid_rows:,}</div><div class="stat-label">Valid 행수 (≥2024)</div></div>
  </div>
  <p class="note">데이터 타입: {dtype_str}</p>
  <p class="note">기간: {df['BASE_YM'].min() if 'BASE_YM' in df.columns else 'N/A'} ~ {df['BASE_YM'].max() if 'BASE_YM' in df.columns else 'N/A'}</p>
</section>
"""
        self._report_sections.append(html)
        log.info("  [1] 개요 섹션 완료")

    # ================================================================
    # Section 2: 결측치
    # ================================================================

    def _section_missing(self) -> None:
        df = self.panel
        miss = (df.isnull().mean() * 100).sort_values(ascending=False)
        miss = miss[miss > 0]

        if miss.empty:
            self._report_sections.append("<section id='missing'><h2>📉 2. 결측치</h2><p>결측치 없음</p></section>")
            return

        # 결측률 막대 그래프
        fig, ax = plt.subplots(figsize=(14, max(6, len(miss) * 0.35)))
        fig.patch.set_facecolor(LIGHT_BG)
        ax.set_facecolor(LIGHT_BG)

        colors = [DANGER if v >= 45 else (SECONDARY if v >= 20 else PRIMARY)
                  for v in miss.values]
        bars = ax.barh(miss.index[:50], miss.values[:50], color=colors[:50], edgecolor="white", linewidth=0.5)
        ax.axvline(45, color=DANGER, linestyle="--", linewidth=1.5, label="45% 임계선")
        ax.axvline(20, color=SECONDARY, linestyle="--", linewidth=1, label="20% 주의선")
        ax.set_xlabel("결측률 (%)", fontsize=12)
        ax.set_title("컬럼별 결측률 (상위 50개)", fontsize=14, fontweight="bold", pad=15)
        ax.legend()
        plt.tight_layout()
        fig_path = self.plots_dir / "missing_rate.png"
        fig.savefig(fig_path, dpi=120, bbox_inches="tight")
        plt.close(fig)

        # 임계값별 요약
        high_miss = (miss >= 45).sum()
        mid_miss  = ((miss >= 20) & (miss < 45)).sum()
        low_miss  = ((miss > 0) & (miss < 20)).sum()

        miss_table = miss.head(20).reset_index()
        miss_table.columns = ["컬럼명", "결측률(%)"]
        miss_table["결측률(%)"] = miss_table["결측률(%)"].round(2)
        table_html = miss_table.to_html(index=False, classes="data-table", border=0)

        html = f"""
<section id="missing">
  <h2>📉 2. 결측치 분석</h2>
  <div class="stats-grid">
    <div class="stat-card danger"><div class="stat-value">{high_miss}</div><div class="stat-label">결측률 ≥45% (제거 후보)</div></div>
    <div class="stat-card warning"><div class="stat-value">{mid_miss}</div><div class="stat-label">결측률 20~45% (주의)</div></div>
    <div class="stat-card"><div class="stat-value">{low_miss}</div><div class="stat-label">결측률 &lt;20% (양호)</div></div>
  </div>
  <img src="eda_plots/missing_rate.png" alt="결측률" class="plot-img">
  <h3>결측률 상위 20개 컬럼</h3>
  {table_html}
</section>
"""
        self._report_sections.append(html)
        log.info("  [2] 결측치 섹션 완료 (45%%+ 컬럼: %d개)", high_miss)

    # ================================================================
    # Section 3: Target 분포
    # ================================================================

    def _section_target_distribution(self) -> None:
        if "IS_BUDO_IN_SPINE_YN" not in self.panel.columns:
            self._report_sections.append("<section id='target'><h2>🎯 3. Target</h2><p>IS_BUDO_IN_SPINE_YN 없음</p></section>")
            return

        df = self.panel.copy()

        fig, axes = plt.subplots(1, 3, figsize=(18, 5))
        fig.patch.set_facecolor(LIGHT_BG)
        for ax in axes:
            ax.set_facecolor(LIGHT_BG)

        # (1) 전체 부도율
        counts = df["IS_BUDO_IN_SPINE_YN"].value_counts()
        wedges, texts, autotexts = axes[0].pie(
            counts, labels=["정상(0)", "부도(1)"],
            colors=[SUCCESS, DANGER], autopct="%1.2f%%",
            startangle=90, textprops={"fontsize": 12}
        )
        axes[0].set_title("전체 부도/정상 비율", fontsize=13, fontweight="bold")

        # (2) 월별 부도 발생 건수
        if "BASE_YM" in df.columns:
            monthly = df.groupby("BASE_YM")["IS_BUDO_IN_SPINE_YN"].sum()
            axes[1].bar(range(len(monthly)), monthly.values, color=DANGER, alpha=0.8)
            axes[1].set_xticks(range(0, len(monthly), max(1, len(monthly)//12)))
            axes[1].set_xticklabels(monthly.index[::max(1, len(monthly)//12)], rotation=45, ha="right", fontsize=8)
            axes[1].set_title("월별 부도 발생 건수", fontsize=13, fontweight="bold")
            axes[1].set_ylabel("부도 건수")

        # (3) SPLIT별 부도율
        if "SPLIT" in df.columns:
            split_rate = df.groupby("SPLIT")["IS_BUDO_IN_SPINE_YN"].mean() * 100
            bars = axes[2].bar(split_rate.index, split_rate.values,
                               color=[PRIMARY, SECONDARY], edgecolor="white")
            for bar, val in zip(bars, split_rate.values):
                axes[2].text(bar.get_x() + bar.get_width() / 2,
                             bar.get_height() + 0.001, f"{val:.3f}%",
                             ha="center", va="bottom", fontsize=11, fontweight="bold")
            axes[2].set_title("학습/검증 분리별 부도율", fontsize=13, fontweight="bold")
            axes[2].set_ylabel("부도율 (%)")

        plt.tight_layout(pad=2)
        fig.savefig(self.plots_dir / "target_distribution.png", dpi=120, bbox_inches="tight")
        plt.close(fig)

        # 업종별 부도율 (STD_INDS_CFC 상위 20개)
        industry_html = ""
        if "STD_INDS_CFC" in df.columns:
            ind_rate = (df.groupby("STD_INDS_CFC")["IS_BUDO_IN_SPINE_YN"]
                        .agg(["sum", "count", "mean"])
                        .rename(columns={"sum": "부도건수", "count": "전체건수", "mean": "부도율"})
                        .sort_values("부도건수", ascending=False)
                        .head(20))
            ind_rate["부도율"] = (ind_rate["부도율"] * 100).round(3)
            ind_rate = ind_rate.reset_index()
            industry_html = f"<h3>업종별 부도율 (상위 20)</h3>{ind_rate.to_html(index=False, classes='data-table', border=0)}"

        html = f"""
<section id="target">
  <h2>🎯 3. Target 분포 (부도 여부)</h2>
  <img src="eda_plots/target_distribution.png" alt="Target 분포" class="plot-img">
  {industry_html}
</section>
"""
        self._report_sections.append(html)
        log.info("  [3] Target 분포 섹션 완료")

    # ================================================================
    # Section 4: 수치형 변수 분포
    # ================================================================

    def _section_numeric_distributions(self) -> None:
        df = self.panel
        num_cols = df.select_dtypes(include=[np.number]).columns.tolist()
        # 키/Target 제외
        exclude = {"IS_BUDO_IN_SPINE_YN", "SPLIT", "ETB_DT"}
        num_cols = [c for c in num_cols if c not in exclude][:30]  # 상위 30개

        if not num_cols:
            self._report_sections.append("<section id='numeric'><h2>📈 4. 수치형 변수</h2><p>없음</p></section>")
            return

        # 기술 통계
        desc = df[num_cols].describe(percentiles=[0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99]).T
        desc["skew"] = df[num_cols].skew()
        desc["kurtosis"] = df[num_cols].kurt()
        desc["missing_pct"] = df[num_cols].isnull().mean() * 100
        desc = desc.round(4)

        # 히스토그램 그리드 (상위 16개)
        plot_cols = num_cols[:16]
        n_rows = (len(plot_cols) + 3) // 4
        fig, axes = plt.subplots(n_rows, 4, figsize=(20, n_rows * 4))
        fig.patch.set_facecolor(LIGHT_BG)
        axes_flat = axes.flatten() if n_rows > 1 else [axes] if len(plot_cols) == 1 else axes.flatten()

        for ax, col in zip(axes_flat, plot_cols):
            ax.set_facecolor(LIGHT_BG)
            data = df[col].dropna()
            if len(data) > 0:
                ax.hist(data.clip(data.quantile(0.01), data.quantile(0.99)),
                        bins=50, color=PRIMARY, alpha=0.8, edgecolor="white")
            ax.set_title(col[:30], fontsize=9, fontweight="bold")
            ax.tick_params(labelsize=7)

        for ax in axes_flat[len(plot_cols):]:
            ax.set_visible(False)

        plt.suptitle("수치형 변수 분포 (상위 16개)", fontsize=14, fontweight="bold", y=1.01)
        plt.tight_layout()
        fig.savefig(self.plots_dir / "numeric_distributions.png", dpi=100, bbox_inches="tight")
        plt.close(fig)

        html = f"""
<section id="numeric">
  <h2>📈 4. 수치형 변수 분포</h2>
  <img src="eda_plots/numeric_distributions.png" alt="수치형 분포" class="plot-img">
  <h3>기술 통계 (상위 30개 수치형 컬럼)</h3>
  {desc.to_html(classes="data-table", border=0)}
</section>
"""
        self._report_sections.append(html)
        log.info("  [4] 수치형 변수 섹션 완료 (%d개 컬럼)", len(num_cols))

    # ================================================================
    # Section 5: 범주형 변수
    # ================================================================

    def _section_categorical(self) -> None:
        df = self.panel
        cat_candidates = ["COPR_OPNP_C", "BZSCAL_C", "STD_INDS_CFC",
                          "GRD_CRDEVL_PTTP_DSC", "GRD_LS_NICS_GRDC",
                          "C302_CRI_GRD", "OBV_ELYWRN_OBV_GRD_DSC"]
        cat_cols = [c for c in cat_candidates if c in df.columns]

        if not cat_cols:
            self._report_sections.append("<section id='categorical'><h2>🏷️ 5. 범주형 변수</h2><p>없음</p></section>")
            return

        n_cols = min(len(cat_cols), 6)
        n_rows = (n_cols + 2) // 3
        fig, axes = plt.subplots(n_rows, 3, figsize=(18, n_rows * 5))
        fig.patch.set_facecolor(LIGHT_BG)
        axes_flat = axes.flatten() if hasattr(axes, 'flatten') else [axes]

        for ax, col in zip(axes_flat, cat_cols):
            ax.set_facecolor(LIGHT_BG)
            vc = df[col].astype(str).value_counts().head(15)
            bars = ax.barh(vc.index[::-1], vc.values[::-1], color=PRIMARY, edgecolor="white")
            ax.set_title(col, fontsize=11, fontweight="bold")
            ax.tick_params(labelsize=8)

        for ax in axes_flat[n_cols:]:
            ax.set_visible(False)

        plt.suptitle("범주형 변수 분포", fontsize=14, fontweight="bold")
        plt.tight_layout()
        fig.savefig(self.plots_dir / "categorical_distributions.png", dpi=100, bbox_inches="tight")
        plt.close(fig)

        html = f"""
<section id="categorical">
  <h2>🏷️ 5. 범주형 변수 분포</h2>
  <img src="eda_plots/categorical_distributions.png" alt="범주형 분포" class="plot-img">
</section>
"""
        self._report_sections.append(html)
        log.info("  [5] 범주형 변수 섹션 완료")

    # ================================================================
    # Section 6: 시계열 트렌드
    # ================================================================

    def _section_timeseries(self) -> None:
        df = self.panel
        if "BASE_YM" not in df.columns:
            return

        key_metrics = []
        if "OBV_LN_BAC" in df.columns:     key_metrics.append(("OBV_LN_BAC", "여신 잔액"))
        if "OBV_RZVL_POD" in df.columns:   key_metrics.append(("OBV_RZVL_POD", "PD (부도확률)"))
        if "CG01_KIS_SCORE" in df.columns:  key_metrics.append(("CG01_KIS_SCORE", "나이스 신용평점"))
        if "C302_CRI_ORD" in df.columns:    key_metrics.append(("C302_CRI_ORD", "CRI 등급 서열"))

        if not key_metrics:
            self._report_sections.append("<section id='timeseries'><h2>📅 6. 시계열</h2><p>주요 시계열 지표 없음</p></section>")
            return

        n = len(key_metrics)
        fig, axes = plt.subplots(n, 1, figsize=(16, 4 * n))
        fig.patch.set_facecolor(LIGHT_BG)
        if n == 1:
            axes = [axes]

        for ax, (col, label) in zip(axes, key_metrics):
            ax.set_facecolor(LIGHT_BG)
            monthly_mean = df.groupby("BASE_YM")[col].mean()
            monthly_median = df.groupby("BASE_YM")[col].median()
            x = range(len(monthly_mean))
            ax.plot(x, monthly_mean.values, color=PRIMARY, linewidth=2, label="평균")
            ax.plot(x, monthly_median.values, color=SECONDARY, linewidth=1.5, linestyle="--", label="중앙값")
            # 학습/검증 구분선
            if "202312" in monthly_mean.index.tolist():
                split_idx = monthly_mean.index.tolist().index("202312")
                ax.axvline(split_idx, color=DANGER, linestyle="--", linewidth=1.5, label="TRAIN/VALID 분리")
            ax.set_xticks(range(0, len(monthly_mean), max(1, len(monthly_mean)//12)))
            ax.set_xticklabels(monthly_mean.index[::max(1, len(monthly_mean)//12)],
                               rotation=45, ha="right", fontsize=8)
            ax.set_title(f"월별 {label} 추이", fontsize=12, fontweight="bold")
            ax.legend(fontsize=9)
            ax.grid(alpha=0.3)

        plt.tight_layout(pad=2)
        fig.savefig(self.plots_dir / "timeseries_trends.png", dpi=100, bbox_inches="tight")
        plt.close(fig)

        html = f"""
<section id="timeseries">
  <h2>📅 6. 주요 지표 시계열 추이</h2>
  <img src="eda_plots/timeseries_trends.png" alt="시계열" class="plot-img">
  <p class="note">점선: 학습(Train) / 검증(Valid) 분리 시점 (2023-12)</p>
</section>
"""
        self._report_sections.append(html)
        log.info("  [6] 시계열 섹션 완료")

    # ================================================================
    # Section 7: 상관관계
    # ================================================================

    def _section_correlation(self) -> None:
        df = self.panel
        num_cols = df.select_dtypes(include=[np.number]).columns.tolist()
        exclude = {"ETB_DT"}
        num_cols = [c for c in num_cols if c not in exclude]

        if len(num_cols) < 3:
            self._report_sections.append("<section id='corr'><h2>🔗 7. 상관관계</h2><p>수치형 변수 부족</p></section>")
            return

        # Target과의 상관
        target_corr = pd.DataFrame()
        if "IS_BUDO_IN_SPINE_YN" in df.columns:
            tc = df[num_cols].corrwith(df["IS_BUDO_IN_SPINE_YN"]).dropna().sort_values(key=abs, ascending=False)
            target_corr = tc.head(20)

            fig, ax = plt.subplots(figsize=(12, 7))
            fig.patch.set_facecolor(LIGHT_BG)
            ax.set_facecolor(LIGHT_BG)
            colors = [DANGER if v > 0 else PRIMARY for v in target_corr.values]
            ax.barh(target_corr.index[::-1], target_corr.values[::-1],
                    color=colors[::-1], edgecolor="white")
            ax.axvline(0, color=DARK, linewidth=0.8)
            ax.set_title("IS_BUDO_IN_SPINE_YN과의 상관계수 (상위 20개)", fontsize=13, fontweight="bold")
            ax.set_xlabel("Pearson r")
            plt.tight_layout()
            fig.savefig(self.plots_dir / "target_correlation.png", dpi=120, bbox_inches="tight")
            plt.close(fig)

        # 변수 간 상관행렬 (상위 20개 변수)
        top_cols = num_cols[:20]
        corr_mat = df[top_cols].corr()
        fig, ax = plt.subplots(figsize=(14, 12))
        fig.patch.set_facecolor(LIGHT_BG)
        im = ax.imshow(corr_mat.values, cmap=CMAP_CORR, vmin=-1, vmax=1, aspect="auto")
        ax.set_xticks(range(len(top_cols)))
        ax.set_yticks(range(len(top_cols)))
        ax.set_xticklabels([c[:20] for c in top_cols], rotation=45, ha="right", fontsize=7)
        ax.set_yticklabels([c[:20] for c in top_cols], fontsize=7)
        plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
        ax.set_title("상관관계 히트맵 (상위 20개 수치형 변수)", fontsize=13, fontweight="bold")
        plt.tight_layout()
        fig.savefig(self.plots_dir / "correlation_heatmap.png", dpi=100, bbox_inches="tight")
        plt.close(fig)

        corr_html = (f"<h3>Target(IS_BUDO_IN_SPINE_YN)과의 상관 상위 20개</h3>"
                     f"{target_corr.reset_index().rename(columns={'index':'컬럼명', 0:'상관계수'}).to_html(index=False, classes='data-table', border=0)}"
                     if not target_corr.empty else "")

        html = f"""
<section id="correlation">
  <h2>🔗 7. 상관관계 분석</h2>
  <img src="eda_plots/target_correlation.png" alt="Target 상관" class="plot-img">
  <img src="eda_plots/correlation_heatmap.png" alt="상관행렬" class="plot-img">
  {corr_html}
</section>
"""
        self._report_sections.append(html)
        log.info("  [7] 상관관계 섹션 완료")

    # ================================================================
    # Section 8: 부도 전 지표 변화 추이
    # ================================================================

    def _section_default_trajectory(self) -> None:
        df = self.panel.copy()
        if "IS_BUDO_IN_SPINE_YN" not in df.columns or "BASE_YM" not in df.columns:
            return

        # 부도 발생 차주 목록
        default_companies = df[df["IS_BUDO_IN_SPINE_YN"] == 1]["V_BZNO"].unique()

        if len(default_companies) == 0:
            self._report_sections.append(
                "<section id='trajectory'><h2>📉 8. 부도 전 지표 변화</h2><p>부도 사례 없음</p></section>")
            return

        track_cols = []
        for col in ["OBV_RZVL_POD", "OBV_LN_BAC", "CG01_KIS_SCORE", "C302_CRI_ORD",
                    "OBV_XPC_LSS_AM"]:
            if col in df.columns:
                track_cols.append(col)

        if not track_cols:
            self._report_sections.append(
                "<section id='trajectory'><h2>📉 8. 부도 전 지표 변화</h2><p>추적 가능한 지표 없음</p></section>")
            return

        # 부도 시점 기준 N개월 전 지표 평균 계산
        df["BASE_YM_DT"] = pd.to_datetime(df["BASE_YM"], format="%Y%m")
        default_month_map = (df[df["IS_BUDO_IN_SPINE_YN"] == 1]
                             .groupby("V_BZNO")["BASE_YM_DT"].min()
                             .to_dict())

        trajectories = {col: {} for col in track_cols}
        look_back = 12  # 부도 전 12개월

        for company in default_companies[:200]:  # 최대 200개사
            if company not in default_month_map:
                continue
            d_month = default_month_map[company]
            company_df = df[df["V_BZNO"] == company].copy()
            company_df = company_df.sort_values("BASE_YM_DT")

            for months_before in range(look_back, 0, -1):
                target_dt = d_month - pd.DateOffset(months=months_before)
                row = company_df[company_df["BASE_YM_DT"] == target_dt]
                if row.empty:
                    continue
                for col in track_cols:
                    val = row[col].iloc[0]
                    if pd.notna(val):
                        if -months_before not in trajectories[col]:
                            trajectories[col][-months_before] = []
                        trajectories[col][-months_before].append(float(val))

        # 정상 차주 평균 (기준선)
        normal_means = {}
        normal_df = df[df["IS_BUDO_IN_SPINE_YN"] == 0]
        for col in track_cols:
            normal_means[col] = normal_df[col].mean()

        n = len(track_cols)
        fig, axes = plt.subplots(1, n, figsize=(6 * n, 5))
        fig.patch.set_facecolor(LIGHT_BG)
        if n == 1:
            axes = [axes]

        for ax, col in zip(axes, track_cols):
            ax.set_facecolor(LIGHT_BG)
            traj = trajectories[col]
            if not traj:
                continue
            x_vals = sorted(traj.keys())
            y_means = [np.mean(traj[x]) for x in x_vals]
            ax.plot(x_vals, y_means, color=DANGER, linewidth=2.5,
                    marker="o", markersize=5, label="부도 차주")
            if col in normal_means and not np.isnan(normal_means[col]):
                ax.axhline(normal_means[col], color=SUCCESS, linestyle="--",
                           linewidth=2, label="정상 차주 평균")
            ax.set_xlabel("부도 전 개월수")
            ax.set_title(col[:25], fontsize=10, fontweight="bold")
            ax.legend(fontsize=8)
            ax.grid(alpha=0.3)
            ax.axvline(0, color=DANGER, linestyle="-", linewidth=0.5, alpha=0.5)

        plt.suptitle("부도 N개월 전 주요 지표 평균 추이", fontsize=14, fontweight="bold")
        plt.tight_layout()
        fig.savefig(self.plots_dir / "default_trajectory.png", dpi=100, bbox_inches="tight")
        plt.close(fig)

        html = f"""
<section id="trajectory">
  <h2>📉 8. 부도 전 주요 지표 변화 궤적</h2>
  <p class="note">부도 발생 12개월 전부터의 평균 지표 변화 (최대 200개사 기준)</p>
  <img src="eda_plots/default_trajectory.png" alt="부도 전 궤적" class="plot-img">
</section>
"""
        self._report_sections.append(html)
        log.info("  [8] 부도 전 궤적 섹션 완료 (%d개사 분석)", len(default_companies))

    # ================================================================
    # 저장
    # ================================================================

    def _export_html(self) -> None:
        """HTML 리포트 생성."""
        css = """
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap');
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Inter', 'Malgun Gothic', sans-serif; background: #F0F4FF; color: #1A1D2E; }
  .container { max-width: 1400px; margin: 0 auto; padding: 20px; }
  header { background: linear-gradient(135deg, #4F6EF5 0%, #7B5EA7 100%);
           color: white; padding: 40px; border-radius: 16px; margin-bottom: 30px; }
  header h1 { font-size: 2rem; margin-bottom: 8px; }
  header p  { opacity: 0.85; font-size: 1rem; }
  section   { background: white; border-radius: 16px; padding: 30px;
              margin-bottom: 24px; box-shadow: 0 2px 12px rgba(79,110,245,0.08); }
  h2 { font-size: 1.4rem; margin-bottom: 20px; color: #4F6EF5;
       border-bottom: 2px solid #E8EDFF; padding-bottom: 10px; }
  h3 { font-size: 1.1rem; margin: 20px 0 10px; color: #1A1D2E; }
  .stats-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
                gap: 16px; margin-bottom: 24px; }
  .stat-card { background: #F0F4FF; border-radius: 12px; padding: 16px;
               text-align: center; border: 1px solid #E0E8FF; }
  .stat-card.highlight { background: #FFF0F0; border-color: #FFD0D0; }
  .stat-card.danger  { background: #FFF0F0; border-color: #E84040; }
  .stat-card.warning { background: #FFF8E8; border-color: #F5A623; }
  .stat-value { font-size: 1.8rem; font-weight: 700; color: #4F6EF5; }
  .stat-card.highlight .stat-value { color: #E84040; }
  .stat-card.danger   .stat-value  { color: #E84040; }
  .stat-card.warning  .stat-value  { color: #F5A623; }
  .stat-label { font-size: 0.8rem; color: #6B7280; margin-top: 4px; }
  .plot-img { width: 100%; border-radius: 12px; margin: 16px 0;
              box-shadow: 0 4px 16px rgba(0,0,0,0.08); }
  .note { font-size: 0.85rem; color: #6B7280; margin-top: 8px; }
  table.data-table { width: 100%; border-collapse: collapse; font-size: 0.85rem;
                     margin-top: 12px; }
  table.data-table th { background: #4F6EF5; color: white; padding: 10px 14px;
                        text-align: left; }
  table.data-table td { padding: 8px 14px; border-bottom: 1px solid #E8EDFF; }
  table.data-table tr:nth-child(even) { background: #F7F9FF; }
  table.data-table tr:hover { background: #EEF2FF; }
  nav { background: white; border-radius: 12px; padding: 16px 24px;
        margin-bottom: 24px; box-shadow: 0 2px 8px rgba(0,0,0,0.06); }
  nav a { color: #4F6EF5; text-decoration: none; margin-right: 20px;
          font-weight: 600; font-size: 0.9rem; }
  nav a:hover { text-decoration: underline; }
</style>
"""
        nav_links = ("".join(
            f'<a href="#{"overview target missing numeric categorical timeseries correlation trajectory".split()[i]}">'
            f'{"1.개요 2.결측치 3.Target 4.수치형 5.범주형 6.시계열 7.상관관계 8.부도궤적".split()[i]}</a>'
            for i in range(8)
        ))

        html_content = f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>NH 차주 데이터 EDA 리포트</title>
  {css}
</head>
<body>
<div class="container">
  <header>
    <h1>📊 NH 차주 데이터 EDA 리포트</h1>
    <p>탐색적 데이터 분석(EDA) — 통합 패널 데이터셋 기반 부도율 예측 모형 준비</p>
    <p style="margin-top:8px; font-size:0.85rem; opacity:0.7">자동 생성 | eda_pipeline/step3_eda.py</p>
  </header>
  <nav>{nav_links}</nav>
  {"".join(self._report_sections)}
</div>
</body>
</html>"""

        out = self.output_dir / "eda_report.html"
        out.write_text(html_content, encoding="utf-8")
        log.info("  HTML 리포트 저장: %s", out)

    def _export_stats_csv(self) -> None:
        """기본 통계 CSV 저장."""
        df = self.panel
        num_cols = df.select_dtypes(include=[np.number]).columns.tolist()
        if num_cols:
            desc = df[num_cols].describe(percentiles=[0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99]).T
            desc["missing_pct"] = df[num_cols].isnull().mean() * 100
            desc["skew"] = df[num_cols].skew()
            desc.to_csv(self.output_dir / "eda_stats_summary.csv", encoding="utf-8-sig")
            log.info("  통계 요약 CSV 저장: eda_stats_summary.csv")
