"""[Validation 4/5] Walk-forward (expanding-window) time-series cross-validation.

The production pipeline only ever reports a single static Train(<=2023.12)/Valid(>=2024.01)
split. For a 66-month panel this tells us nothing about whether performance is stable across
time or whether the reported 0.9011 AUC is a lucky/unlucky snapshot. This script builds an
expanding-window walk-forward CV: the initial 24 months (2021.01-2022.12) seed the training
window, then we roll forward in 3-month test blocks (14 folds, covering 2023.01-2026.06),
always training on everything strictly before the test block (point-in-time correct).

Note: exploratory analysis of corporate_panel found a strong within-year default-rate
seasonality (peaks every January, troughs every December, repeating 2021-2025) -- this
script reports each fold's actual default rate alongside its AUC so that seasonality isn't
mistaken for model instability when reading the results.

Full fold sweep runs on the Lean/VIF 80-feature set to keep runtime bounded; 2 representative
folds (first and last) are spot-checked with the Full 230-feature set to confirm the trend
generalizes.
"""
import json
import logging
import os
import time

import lightgbm as lgb
import pandas as pd

from validation_common import (
    OUTPUT_DIR, calculate_psi, evaluate, free, full_feature_list, lean_feature_list, load_panel,
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

STEP_MONTHS = 3
INITIAL_TRAIN_MONTHS = 24


def month_add(ym, n):
    y, m = divmod(ym, 100)
    idx = y * 12 + (m - 1) + n
    y2, m2 = divmod(idx, 12)
    return y2 * 100 + (m2 + 1)


def build_folds(all_months):
    all_months = sorted(all_months)
    folds = []
    train_end = all_months[INITIAL_TRAIN_MONTHS - 1]
    remaining = [m for m in all_months if m > train_end]
    i = 0
    while i < len(remaining):
        test_block = remaining[i:i + STEP_MONTHS]
        if len(test_block) < STEP_MONTHS:
            break
        folds.append((train_end, test_block[0], test_block[-1]))
        train_end = test_block[-1]
        i += STEP_MONTHS
    return folds


def load_reg_params(n_pos, n_neg):
    base = dict(objective='binary', metric='auc', boosting_type='gbdt',
                learning_rate=0.05, max_depth=8, num_leaves=31,
                scale_pos_weight=n_neg / n_pos, seed=42, verbose=-1, n_jobs=-1)
    variant_path = f'{OUTPUT_DIR}/step14_best_regularized_variant.json'
    if os.path.exists(variant_path):
        with open(variant_path, encoding='utf-8') as f:
            info = json.load(f)
        params = dict(info['params'])
        params['scale_pos_weight'] = n_neg / n_pos
        return params
    return base


def run_fold(fold_id, features, train_df, test_df, dev_months_count=2):
    all_train_months = sorted(train_df['BASE_YM'].unique())
    dev_months = all_train_months[-dev_months_count:]
    real_train_df = train_df[~train_df['BASE_YM'].isin(dev_months)]
    dev_df = train_df[train_df['BASE_YM'].isin(dev_months)]

    n_pos = real_train_df['IS_BUDO_12M'].sum()
    n_neg = len(real_train_df) - n_pos
    params = load_reg_params(n_pos, n_neg)

    t0 = time.time()
    train_set = lgb.Dataset(real_train_df[features], label=real_train_df['IS_BUDO_12M'],
                             categorical_feature=[c for c in ['OBV_ELYWRN_OBV_GRD_DSC'] if c in features],
                             free_raw_data=True)
    dev_set = lgb.Dataset(dev_df[features], label=dev_df['IS_BUDO_12M'], reference=train_set,
                           categorical_feature=[c for c in ['OBV_ELYWRN_OBV_GRD_DSC'] if c in features],
                           free_raw_data=True)
    booster = lgb.train(
        params, train_set, num_boost_round=400,
        valid_sets=[dev_set], valid_names=['dev'],
        callbacks=[lgb.early_stopping(40, verbose=False), lgb.log_evaluation(0)],
    )
    elapsed = time.time() - t0
    best_iter = booster.best_iteration

    train_prob = booster.predict(real_train_df[features], num_iteration=best_iter)
    test_prob = booster.predict(test_df[features], num_iteration=best_iter)
    metrics = evaluate(test_df['IS_BUDO_12M'], test_prob)
    psi = calculate_psi(train_prob, test_prob)

    result = {
        'fold': fold_id,
        'train_months': f"{all_train_months[0]}-{train_df['BASE_YM'].max()}",
        'test_months': f"{test_df['BASE_YM'].min()}-{test_df['BASE_YM'].max()}",
        'n_train': len(real_train_df),
        'n_test': len(test_df),
        'test_default_rate_pct': round(100 * test_df['IS_BUDO_12M'].mean(), 3),
        'test_auc': metrics['auc'],
        'test_gini': metrics['gini'],
        'test_ks': metrics['ks'],
        'psi_train_vs_test': psi,
        'best_iteration': best_iter,
        'train_seconds': round(elapsed, 1),
    }
    logging.info(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def main():
    lean_features = lean_feature_list()
    full_features = full_feature_list()

    logging.info("Loading Lean(80)-feature panel for the full fold sweep...")
    df_lean = load_panel(lean_features)
    all_months = sorted(df_lean['BASE_YM'].unique().tolist())
    folds = build_folds(all_months)
    logging.info(f"{len(folds)} walk-forward folds: {folds}")

    lean_results = []
    for i, (train_end, test_start, test_end) in enumerate(folds, start=1):
        train_df = df_lean[df_lean['BASE_YM'] <= train_end]
        test_df = df_lean[(df_lean['BASE_YM'] >= test_start) & (df_lean['BASE_YM'] <= test_end)]
        lean_results.append(run_fold(i, lean_features, train_df, test_df))

    lean_df = pd.DataFrame(lean_results)
    lean_csv = f'{OUTPUT_DIR}/step17_walkforward_lean.csv'
    lean_df.to_csv(lean_csv, index=False, encoding='utf-8-sig')
    logging.info(f"\n{lean_df.to_string(index=False)}")
    logging.info(f"Saved: {lean_csv}")

    import matplotlib.pyplot as plt
    plt.rcParams['font.family'] = 'Malgun Gothic'
    plt.rcParams['axes.unicode_minus'] = False
    fig, ax1 = plt.subplots(figsize=(12, 5))
    ax1.plot(lean_df['fold'], lean_df['test_auc'], marker='o', color='tab:blue', label='Test AUC')
    ax1.axhline(0.9011, color='gray', linestyle='--', label='Static split AUC (0.9011)')
    ax1.set_xlabel('Fold (expanding window, 3-month test blocks)')
    ax1.set_ylabel('AUC', color='tab:blue')
    ax2 = ax1.twinx()
    ax2.bar(lean_df['fold'], lean_df['test_default_rate_pct'], alpha=0.25, color='tab:red', label='Default rate (%)')
    ax2.set_ylabel('Test default rate (%)', color='tab:red')
    fig.legend(loc='upper right', bbox_to_anchor=(0.9, 0.9))
    plt.title('Walk-forward CV: Test AUC vs Default Rate by Fold (Lean/80 features)')
    plt.tight_layout()
    plot_path = f'{OUTPUT_DIR}/step17_walkforward_trend.png'
    plt.savefig(plot_path, dpi=150)
    logging.info(f"Saved: {plot_path}")
    free(df_lean)

    # Spot-check first and last fold with the Full 230-feature set
    logging.info("Loading Full(230)-feature panel for spot-check folds...")
    df_full = load_panel(full_features)
    spot_folds = [folds[0], folds[-1]]
    spot_results = []
    for idx, (train_end, test_start, test_end) in zip([1, len(folds)], spot_folds):
        train_df = df_full[df_full['BASE_YM'] <= train_end]
        test_df = df_full[(df_full['BASE_YM'] >= test_start) & (df_full['BASE_YM'] <= test_end)]
        spot_results.append(run_fold(idx, full_features, train_df, test_df))
    spot_df = pd.DataFrame(spot_results)
    spot_csv = f'{OUTPUT_DIR}/step17_walkforward_full_spotcheck.csv'
    spot_df.to_csv(spot_csv, index=False, encoding='utf-8-sig')
    logging.info(f"\n{spot_df.to_string(index=False)}")
    logging.info(f"Saved: {spot_csv}")


if __name__ == '__main__':
    main()
