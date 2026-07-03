"""Generates the remaining chart assets for docs/step28 (items 2, 3, 5 originally had tables
only). Reads the CSVs already produced by step15/16/18 -- no retraining needed.
"""
import pandas as pd
import matplotlib.pyplot as plt

from validation_common import OUTPUT_DIR

plt.rcParams['font.family'] = 'Malgun Gothic'
plt.rcParams['axes.unicode_minus'] = False


def plot_topn_ablation():
    df = pd.read_csv(f'{OUTPUT_DIR}/step16_topN_ablation.csv')
    metrics = ['valid_auc', 'valid_gini', 'valid_ks']
    labels = ['Valid AUC', 'Valid Gini', 'Valid K-S']
    x = range(len(df))
    width = 0.25
    fig, ax = plt.subplots(figsize=(9, 5.5))
    for i, (m, lab) in enumerate(zip(metrics, labels)):
        bars = ax.bar([xi + (i - 1) * width for xi in x], df[m], width, label=lab)
        for b, v in zip(bars, df[m]):
            ax.text(b.get_x() + b.get_width() / 2, v + 0.01, f'{v:.3f}', ha='center', fontsize=8)
    ax.set_xticks(list(x))
    ax.set_xticklabels(df['feature_set'])
    ax.set_ylim(0, 1.0)
    ax.set_ylabel('Score')
    ax.set_title('Feature-set Ablation: Full (230) vs Lean/VIF (80) vs Top-20 (gain)')
    ax.legend()
    ax.grid(axis='y', alpha=0.3)
    plt.tight_layout()
    plt.savefig(f'{OUTPUT_DIR}/step19_topN_ablation_bar.png', dpi=150)
    plt.close()


def plot_model_benchmark():
    df = pd.read_csv(f'{OUTPUT_DIR}/step18_model_benchmark.csv')
    df = df.sort_values('valid_auc', ascending=True)
    fig, ax = plt.subplots(figsize=(9, 5.5))
    colors = ['#2ca02c' if 'regularized' in m else '#1f77b4' for m in df['model']]
    bars = ax.barh(df['model'], df['valid_auc'], color=colors)
    for b, v, sec in zip(bars, df['valid_auc'], df['train_seconds']):
        sec_label = f'{sec/3600:.1f}h' if sec > 3600 else f'{sec:.0f}s'
        ax.text(v + 0.003, b.get_y() + b.get_height() / 2, f'{v:.4f} ({sec_label})', va='center', fontsize=8.5)
    ax.set_xlim(0.75, 0.95)
    ax.set_xlabel('Valid AUC (true holdout)')
    ax.set_title('Model Benchmark: Valid AUC (train time annotated)')
    ax.grid(axis='x', alpha=0.3)
    plt.tight_layout()
    plt.savefig(f'{OUTPUT_DIR}/step19_model_benchmark_bar.png', dpi=150)
    plt.close()


def plot_shap_top20():
    df = pd.read_csv(f'{OUTPUT_DIR}/step15_reference_shap_ranking_top50.csv', index_col=0)
    top20 = df.head(20).iloc[::-1]
    fig, ax = plt.subplots(figsize=(8, 7))
    ax.barh(top20.index, top20['mean_abs_shap'], color='#d62728')
    ax.set_xlabel('Mean |SHAP value|')
    ax.set_title('Top-20 Features by SHAP Importance (Valid pool, n=100,000)')
    ax.grid(axis='x', alpha=0.3)
    plt.tight_layout()
    plt.savefig(f'{OUTPUT_DIR}/step19_shap_top20_importance.png', dpi=150)
    plt.close()


def main():
    plot_topn_ablation()
    plot_model_benchmark()
    plot_shap_top20()
    print("Saved: step19_topN_ablation_bar.png, step19_model_benchmark_bar.png, step19_shap_top20_importance.png")


if __name__ == '__main__':
    main()
