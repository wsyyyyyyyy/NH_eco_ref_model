"""
smooth_weights.py
=================
원시 SHAP 가중치 매트릭스의 Sparsity 문제를 해결하기 위한 스무딩 파이프라인.

[1단계] 172개 피처를 6대 매크로 카테고리로 매핑
[2단계] 카테고리별 가중치 합산 → 지분율 산출 → 균등 재분배 → 하한선(Floor) 부여
[3단계] 결과 저장 및 검증

입력: output/industry_macro_shap_weights.csv
출력: output/industry_macro_smoothed_weights.csv
"""

import os
import re
import logging
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm

# ─── 경로 및 로깅 설정 ───
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(_SCRIPT_DIR, "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(
            os.path.join(OUTPUT_DIR, "smooth_weights.log"),
            mode='w', encoding='utf-8'
        )
    ]
)
log = logging.getLogger(__name__)

# ─── 한글 폰트 설정 ───
def setup_korean_font():
    for font_name in ['Malgun Gothic', 'NanumGothic', 'AppleGothic']:
        font_path = fm.findfont(fm.FontProperties(family=font_name))
        if font_path and 'fallback' not in font_path.lower():
            plt.rcParams['font.family'] = font_name
            plt.rcParams['axes.unicode_minus'] = False
            return
    plt.rcParams['axes.unicode_minus'] = False

setup_korean_font()

# ═══════════════════════════════════════════════════════════════════════════════
#  [1단계] 6대 매크로 카테고리 매핑 규칙
# ═══════════════════════════════════════════════════════════════════════════════

CATEGORY_RULES = {
    'Equity (주가지수)': [
        'KOSPI', 'KOSDAQ', 'DowJones', 'NASDAQ', 'SP500',
        'Nikkei225', 'Shanghai_Composite'
    ],
    'FX (환율)': [
        'USD_KRW', 'EUR_KRW', 'JPY_KRW', 'CNY_KRW', 'DXY_dollar_index'
    ],
    'Commodity (원자재/에너지)': [
        'brent_crude_oil', 'WTI_crude_oil', 'natural_gas',
        'gold', 'silver', 'copper'
    ],
    'Agri (농산물)': [
        'corn', 'soybean'
    ],
    'Interest (금리/채권)': [
        'CP_91d', 'MSB_91d', 'call_rate', 'corporate_bond',
        'KORIBOR', 'treasury_bond', 'US_10Y', 'US_2Y',
        'base_rate', 'CD_rate', 'spread', 'credit_spread',
        'liquidity_spread'
    ],
    'Macro/Biz (거시경제/경기지수)': [
        'CPI', 'PPI', 'housing_price', 'M1_narrow', 'M2_broad',
        'Lf_liquidity', 'monetary_base', 'export_index', 'import_index',
        'trade_total', 'current_account', 'goods_balance', 'household',
        'BSI', 'CSI', 'VIX'
    ]
}

# 하한선(Floor) 값
FLOOR_VALUE = 0.005


def classify_feature(feature_name: str) -> str:
    """피처명을 6대 카테고리 중 하나로 분류"""
    for category, keywords in CATEGORY_RULES.items():
        for keyword in keywords:
            if keyword in feature_name:
                return category
    # 매칭 안 되는 경우 → Macro/Biz로 기본 할당
    return 'Macro/Biz (거시경제/경기지수)'


def main():
    log.info("=" * 80)
    log.info("  가중치 스무딩(Smoothing) 및 하한선(Floor) 부여 파이프라인")
    log.info("  Macro Risk Weight Smoothing Pipeline")
    log.info("=" * 80)

    # ─────────────────────────────────────────────────────────────────────────
    #  원시 데이터 로드
    # ─────────────────────────────────────────────────────────────────────────
    raw_path = os.path.join(OUTPUT_DIR, "industry_macro_shap_weights.csv")
    if not os.path.exists(raw_path):
        log.error(f"원시 가중치 파일 미존재: {raw_path}")
        return

    df_raw = pd.read_csv(raw_path)
    log.info(f"원시 데이터 로드 완료: {df_raw.shape}")

    # 메타 컬럼(STD_INDS_CFC, industry_name)과 피처 컬럼 분리
    meta_cols = ['STD_INDS_CFC', 'industry_name']
    existing_meta = [c for c in meta_cols if c in df_raw.columns]
    feature_cols = [c for c in df_raw.columns if c not in meta_cols]

    df_meta = df_raw[existing_meta].copy()
    df_weights = df_raw[feature_cols].copy().astype(float)

    log.info(f"메타 컬럼: {existing_meta}")
    log.info(f"피처 컬럼 수: {len(feature_cols)}")

    # 원시 Sparsity 분석
    zero_ratio = ((df_weights <= 0.001).sum(axis=1) / len(feature_cols) * 100).mean()
    log.info(f"원시 데이터 평균 Zero 비율: {zero_ratio:.1f}%")

    # ─────────────────────────────────────────────────────────────────────────
    #  [1단계] 피처 카테고리 매핑
    # ─────────────────────────────────────────────────────────────────────────
    log.info("")
    log.info("━" * 80)
    log.info("  [1단계] 172개 피처 → 6대 매크로 카테고리 매핑")
    log.info("━" * 80)

    feature_category_map = {}
    for feat in feature_cols:
        feature_category_map[feat] = classify_feature(feat)

    # 카테고리별 피처 목록 구축
    category_features = {}
    for feat, cat in feature_category_map.items():
        if cat not in category_features:
            category_features[cat] = []
        category_features[cat].append(feat)

    log.info("\n   📋 카테고리별 피처 매핑 결과:")
    for cat, feats in sorted(category_features.items()):
        log.info(f"   {cat}: {len(feats)}개 피처")
        # 대표 피처 5개만 출력
        sample = feats[:5]
        log.info(f"     예시: {sample}")

    total_mapped = sum(len(v) for v in category_features.values())
    log.info(f"\n   ✅ 전체 {total_mapped}개 피처 매핑 완료 (6개 카테고리)")

    # ─────────────────────────────────────────────────────────────────────────
    #  [2단계] 카테고리별 가중치 합산 → 스무딩
    # ─────────────────────────────────────────────────────────────────────────
    log.info("")
    log.info("━" * 80)
    log.info("  [2단계] 카테고리별 가중치 합산 및 스무딩(Smoothing) 적용")
    log.info("━" * 80)

    n_industries = len(df_weights)
    df_smoothed = pd.DataFrame(0.0, index=df_weights.index, columns=feature_cols)

    # 카테고리 지분율 기록용
    category_shares_records = []

    for idx in range(n_industries):
        row = df_weights.iloc[idx]
        industry_label = df_meta.iloc[idx].get('industry_name', df_meta.iloc[idx].get('STD_INDS_CFC', f'Row_{idx}'))

        # 2-1. 카테고리별 합계 산출
        cat_sums = {}
        for cat, feats in category_features.items():
            cat_sums[cat] = row[feats].sum()

        total_sum = sum(cat_sums.values())

        # 2-2. 지분율(Percentage) 정규화 → 합계 = 1
        cat_shares = {}
        if total_sum > 0:
            for cat in cat_sums:
                cat_shares[cat] = cat_sums[cat] / total_sum
        else:
            # 모든 가중치가 0인 경우 → 균등 배분
            n_cats = len(cat_sums)
            for cat in cat_sums:
                cat_shares[cat] = 1.0 / n_cats

        # 지분율 기록
        record = {'industry': industry_label}
        record.update(cat_shares)
        category_shares_records.append(record)

        # 2-3. 피처 단위 균등 재분배 (Uniform Redistribution)
        row_idx_label = df_smoothed.index[idx]
        for cat, feats in category_features.items():
            n_feats = len(feats)
            per_feat_weight = cat_shares[cat] / n_feats
            for feat in feats:
                df_smoothed.loc[row_idx_label, feat] = per_feat_weight

    # 카테고리 지분율 로깅
    df_shares = pd.DataFrame(category_shares_records)
    log.info("\n   📊 업종별 카테고리 지분율 (합계=1.0):")
    log.info(f"\n{df_shares.to_string(index=False)}")

    # 2-4. 하한선(Floor) 부여: 0.005 미만 → 0.005
    log.info(f"\n   Floor 하한선 적용: 모든 피처 최소값 = {FLOOR_VALUE}")
    below_floor_before = (df_smoothed < FLOOR_VALUE).sum().sum()
    df_smoothed = df_smoothed.clip(lower=FLOOR_VALUE)
    log.info(f"   - Floor 적용 대상 셀 수: {below_floor_before:,}개")

    # 2-5. 행별 재정규화 → 각 업종의 가중치 합 = 1.0
    log.info("   행별 재정규화 (각 업종 가중치 합 = 1.0)...")
    row_sums = df_smoothed.sum(axis=1)
    df_smoothed = df_smoothed.div(row_sums, axis=0)

    # 검증
    final_row_sums = df_smoothed.sum(axis=1)
    log.info(f"   - 최종 행합 검증: min={final_row_sums.min():.6f}, max={final_row_sums.max():.6f}")
    assert np.allclose(final_row_sums, 1.0, atol=1e-6), "행 합계가 1.0이 아닙니다!"

    # Sparsity 개선 분석
    zero_ratio_after = ((df_smoothed <= 0.001).sum(axis=1) / len(feature_cols) * 100).mean()
    log.info(f"\n   📈 Sparsity 개선: {zero_ratio:.1f}% → {zero_ratio_after:.1f}%")

    # ─────────────────────────────────────────────────────────────────────────
    #  [3단계] 결과 저장 및 검증
    # ─────────────────────────────────────────────────────────────────────────
    log.info("")
    log.info("━" * 80)
    log.info("  [3단계] 결과 저장 및 검증")
    log.info("━" * 80)

    # 메타 컬럼 재결합
    df_result = pd.concat([df_meta.reset_index(drop=True), df_smoothed.reset_index(drop=True)], axis=1)

    # CSV 저장
    smoothed_path = os.path.join(OUTPUT_DIR, "industry_macro_smoothed_weights.csv")
    df_result.to_csv(smoothed_path, index=False, encoding='utf-8-sig')
    log.info(f"   ✅ 스무딩된 매트릭스 저장 완료: {smoothed_path}")
    log.info(f"   - 크기: {df_result.shape}")

    # 카테고리 지분율 CSV도 별도 저장
    shares_path = os.path.join(OUTPUT_DIR, "category_shares_by_industry.csv")
    df_shares.to_csv(shares_path, index=False, encoding='utf-8-sig')
    log.info(f"   ✅ 카테고리 지분율 저장 완료: {shares_path}")

    # ─── 시각화 1: 원시 vs 스무딩 비교 히트맵 ───
    log.info("\n   히트맵 시각화 생성 중...")

    # 상위 20개 피처 선정 (원시 가중치 기준)
    top20 = df_weights.mean().nlargest(20).index.tolist()

    if 'industry_name' in df_meta.columns:
        labels = [f"{r['STD_INDS_CFC']} ({r['industry_name']})" for _, r in df_meta.iterrows()]
    else:
        labels = df_meta.iloc[:, 0].tolist()

    fig, axes = plt.subplots(1, 2, figsize=(28, max(8, len(labels)*0.5)))

    # 원시 히트맵
    ax0 = axes[0]
    im0 = ax0.imshow(df_weights[top20].values, cmap='YlOrRd', aspect='auto', vmin=0, vmax=1)
    ax0.set_xticks(range(len(top20)))
    ax0.set_xticklabels(top20, rotation=55, ha='right', fontsize=7)
    ax0.set_yticks(range(len(labels)))
    ax0.set_yticklabels(labels, fontsize=8)
    ax0.set_title('Before Smoothing (Raw SHAP Weights)', fontsize=13, fontweight='bold')
    for i in range(len(labels)):
        for j in range(len(top20)):
            v = df_weights[top20].values[i, j]
            ax0.text(j, i, f'{v:.3f}', ha='center', va='center',
                     color='white' if v > 0.5 else 'black', fontsize=6)
    plt.colorbar(im0, ax=ax0, shrink=0.6)

    # 스무딩 히트맵
    ax1 = axes[1]
    smoothed_top20 = df_smoothed[top20].values
    vmax_s = smoothed_top20.max()
    im1 = ax1.imshow(smoothed_top20, cmap='YlOrRd', aspect='auto', vmin=0, vmax=max(vmax_s, 0.05))
    ax1.set_xticks(range(len(top20)))
    ax1.set_xticklabels(top20, rotation=55, ha='right', fontsize=7)
    ax1.set_yticks(range(len(labels)))
    ax1.set_yticklabels(labels, fontsize=8)
    ax1.set_title('After Smoothing (Category Redistribution + Floor)', fontsize=13, fontweight='bold')
    for i in range(len(labels)):
        for j in range(len(top20)):
            v = smoothed_top20[i, j]
            ax1.text(j, i, f'{v:.4f}', ha='center', va='center',
                     color='white' if v > vmax_s * 0.6 else 'black', fontsize=6)
    plt.colorbar(im1, ax=ax1, shrink=0.6)

    plt.suptitle('Industry Macro Risk Weights: Raw vs Smoothed Comparison',
                 fontsize=15, fontweight='bold', y=1.02)
    plt.tight_layout()

    comparison_path = os.path.join(OUTPUT_DIR, "smoothing_comparison_heatmap.png")
    plt.savefig(comparison_path, dpi=200, bbox_inches='tight')
    plt.close()
    log.info(f"   ✅ 비교 히트맵 저장: {comparison_path}")

    # ─── 시각화 2: 카테고리 지분율 스택 바 차트 ───
    log.info("   카테고리 지분율 차트 생성 중...")

    cat_cols = [c for c in df_shares.columns if c != 'industry']
    fig, ax = plt.subplots(figsize=(14, max(8, len(labels)*0.45)))

    colors = ['#FF6B6B', '#4ECDC4', '#45B7D1', '#96CEB4', '#FFEAA7', '#DDA0DD']
    bottom = np.zeros(len(df_shares))

    for i, cat in enumerate(cat_cols):
        ax.barh(range(len(df_shares)), df_shares[cat].values, left=bottom,
                color=colors[i % len(colors)], label=cat, edgecolor='white', linewidth=0.5)
        bottom += df_shares[cat].values

    ax.set_yticks(range(len(df_shares)))
    ax.set_yticklabels(df_shares['industry'].values, fontsize=9)
    ax.set_xlabel('Category Share (Sum = 1.0)', fontsize=12)
    ax.set_title('Macro Category Share by Industry\n(Basis for Smoothed Weight Redistribution)',
                 fontsize=14, fontweight='bold')
    ax.legend(loc='lower right', fontsize=8, framealpha=0.9)
    ax.set_xlim(0, 1)
    ax.grid(True, axis='x', alpha=0.3)
    ax.invert_yaxis()
    plt.tight_layout()

    shares_chart_path = os.path.join(OUTPUT_DIR, "category_shares_chart.png")
    plt.savefig(shares_chart_path, dpi=200)
    plt.close()
    log.info(f"   ✅ 카테고리 지분율 차트 저장: {shares_chart_path}")

    # ─── 최종 요약 ───
    log.info("")
    log.info("=" * 80)
    log.info("  🎯 스무딩 파이프라인 완료!")
    log.info("=" * 80)
    log.info(f"  [입력]   {raw_path}")
    log.info(f"  [출력]   {smoothed_path}")
    log.info(f"  [지분율] {shares_path}")
    log.info(f"  [비교]   {comparison_path}")
    log.info(f"  [차트]   {shares_chart_path}")
    log.info(f"  [Sparsity 개선] {zero_ratio:.1f}% → {zero_ratio_after:.1f}%")
    log.info(f"  [Floor 하한선] {FLOOR_VALUE}")
    log.info(f"  [행합 검증] 모든 업종 = 1.0 ✅")
    log.info("=" * 80)


if __name__ == "__main__":
    main()
