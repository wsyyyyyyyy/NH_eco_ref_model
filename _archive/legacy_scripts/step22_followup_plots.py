"""Generates chart assets for the two follow-up sections of docs/step28 (1-1: true 3-way
split, 2-1: full multicollinearity audit). Reads the CSVs/JSONs already produced by
step17/step20/step21 -- no retraining needed.
"""
import json

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from validation_common import OUTPUT_DIR

plt.rcParams['font.family'] = 'Malgun Gothic'
plt.rcParams['axes.unicode_minus'] = False


def plot_3way_comparison():
    with open(f'{OUTPUT_DIR}/step20_true_3way_summary.json', encoding='utf-8') as f:
        s = json.load(f)
    wf = pd.read_csv(f'{OUTPUT_DIR}/step17_walkforward_lean.csv')
    wf_same_period = wf[wf['fold'] >= 9]['test_auc'].mean()  # folds 9-14 = 202501-202606, same as Test period

    labels = ['정적 스플릿\n(기존 보고값)', 'Dev/Valid 방식\n(§1, reg_v1)', '순수 Test 18개월\n(§1-1, 고정모델)',
              '워크포워드 평균\n(§4, 동일기간 재학습)']
    values = [s['reference_original_static_split_auc'], s['reference_step14_dev_valid_auc_of_same_winner_config'],
              s['test_auc_full_18mo'], wf_same_period]
    colors = ['#7f7f7f', '#1f77b4', '#d62728', '#2ca02c']

    fig, ax = plt.subplots(figsize=(9, 5.5))
    bars = ax.bar(labels, values, color=colors)
    for b, v in zip(bars, values):
        ax.text(b.get_x() + b.get_width() / 2, v + 0.005, f'{v:.4f}', ha='center', fontweight='bold')
    ax.set_ylim(0.75, 0.98)
    ax.set_ylabel('AUC')
    ax.set_title('같은 2025.01~2026.06 기간, 평가 방식에 따른 AUC 차이')
    ax.grid(axis='y', alpha=0.3)
    plt.tight_layout()
    plt.savefig(f'{OUTPUT_DIR}/step22_3way_split_comparison_bar.png', dpi=150)
    plt.close()
    print(f"walk-forward mean (folds 9-14): {wf_same_period:.4f}")


def plot_multicollinearity_survival():
    with open(f'{OUTPUT_DIR}/step21_multicollinearity_summary.json', encoding='utf-8') as f:
        s = json.load(f)

    groups = ['Full (230) 228개 수치형\nfrom-scratch 재검증', '현재 Lean (80) 78개 수치형\n단독 재검증']
    survived = [s['full_model_vif_survivors_from_scratch'],
                s['current_lean80_numeric_features_checked_standalone'] - len(s['current_lean80_features_that_fail_standalone_vif'])]
    dropped = [s['full_model_dropped_for_multicollinearity'], len(s['current_lean80_features_that_fail_standalone_vif'])]

    fig, ax = plt.subplots(figsize=(8, 5.5))
    x = np.arange(len(groups))
    width = 0.5
    b1 = ax.bar(x, survived, width, label='VIF ≤ 10 (생존)', color='#2ca02c')
    b2 = ax.bar(x, dropped, width, bottom=survived, label='VIF > 10 (다중공선성)', color='#d62728')
    for i in range(len(groups)):
        ax.text(x[i], survived[i] / 2, f'{survived[i]}', ha='center', va='center', color='white', fontweight='bold')
        ax.text(x[i], survived[i] + dropped[i] / 2, f'{dropped[i]}', ha='center', va='center', color='white', fontweight='bold')
    ax.set_xticks(x)
    ax.set_xticklabels(groups)
    ax.set_ylabel('변수 개수')
    ax.set_title('다중공선성(VIF) 재검증: 생존 vs 탈락')
    ax.legend()
    plt.tight_layout()
    plt.savefig(f'{OUTPUT_DIR}/step22_multicollinearity_survival_bar.png', dpi=150)
    plt.close()


def plot_vif_distribution():
    drop_log = pd.read_csv(f'{OUTPUT_DIR}/step21_full_vif_drop_log.csv')
    drop_log = drop_log.dropna(subset=['vif'])
    drop_log['log10_vif'] = np.log10(drop_log['vif'].astype(float))
    drop_log['category'] = np.where(drop_log['feature'].str.startswith('JEMU_') | drop_log['feature'].str.startswith('AC12_'),
                                     '재무비율 (JEMU/AC12)', '거시경제/외부 API')
    drop_log = drop_log.sort_values('log10_vif')

    fig, ax = plt.subplots(figsize=(9, 6))
    colors = drop_log['category'].map({'재무비율 (JEMU/AC12)': '#1f77b4', '거시경제/외부 API': '#d62728'})
    ax.barh(range(len(drop_log)), drop_log['log10_vif'], color=colors)
    ax.set_yticks([])
    ax.set_xlabel('log10(VIF)')
    ax.set_title(f'VIF 다이어트 탈락 {len(drop_log)}개 변수의 VIF 분포 (낮은 순)')
    ax.axvline(1, color='gray', linestyle='--', linewidth=1, label='VIF=10 기준선')
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(color='#1f77b4', label='재무비율 (JEMU/AC12)'),
                       Patch(color='#d62728', label='거시경제/외부 API'),
                       ax.lines[-1]])
    plt.tight_layout()
    plt.savefig(f'{OUTPUT_DIR}/step22_vif_distribution.png', dpi=150)
    plt.close()


def main():
    plot_3way_comparison()
    plot_multicollinearity_survival()
    plot_vif_distribution()
    print("Saved: step22_3way_split_comparison_bar.png, step22_multicollinearity_survival_bar.png, step22_vif_distribution.png")


if __name__ == '__main__':
    main()
