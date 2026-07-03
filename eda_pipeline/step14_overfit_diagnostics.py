"""[Validation 1/5] Overfitting risk check for the current LightGBM training config.

The production script (step7_modeling_shap.py) trains with
LGBMClassifier(n_estimators=300, learning_rate=0.05, max_depth=8, class_weight='balanced')
and early-stops directly against the same VALID split (2024.01+) that is later reported as
the final metric -- num_leaves/reg_alpha/reg_lambda/subsample/colsample are all left at
LightGBM defaults (31 / 0 / 0 / 1.0 / 1.0), i.e. essentially no regularization.

This script:
  1. Reproduces that baseline honestly, but with VALID held out as a true, untouched test set
     (early stopping uses a Dev slice carved from the tail of TRAIN instead).
  2. Records a per-round Train vs Dev AUC learning curve to visualize when/how fast the gap
     opens up.
  3. Compares the baseline against a few regularized variants under the identical Train/Dev/
     Valid split, reporting Train/Valid AUC, the overfitting gap, and wall-clock time.
"""
import json
import logging
import time

import lightgbm as lgb
import matplotlib.pyplot as plt

from validation_common import (
    OUTPUT_DIR, evaluate, free, full_feature_list, load_panel, three_way_split,
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')


def run_variant(name, params, train_set, dev_set, X_train, y_train, X_valid, y_valid, num_boost_round=500):
    logging.info(f"--- Training variant: {name} ---")
    t0 = time.time()
    evals_result = {}
    booster = lgb.train(
        params, train_set,
        num_boost_round=num_boost_round,
        valid_sets=[train_set, dev_set],
        valid_names=['train', 'dev'],
        callbacks=[
            lgb.early_stopping(50, verbose=False),
            lgb.log_evaluation(50),
            lgb.record_evaluation(evals_result),
        ],
    )
    elapsed = time.time() - t0

    train_auc_curve = evals_result['train']['auc']
    dev_auc_curve = evals_result['dev']['auc']
    best_iter = booster.best_iteration

    valid_prob = booster.predict(X_valid, num_iteration=best_iter)
    valid_metrics = evaluate(y_valid, valid_prob)

    train_prob = booster.predict(X_train, num_iteration=best_iter)
    train_metrics = evaluate(y_train, train_prob)

    result = {
        'name': name,
        'best_iteration': best_iter,
        'train_auc': train_metrics['auc'],
        'dev_auc_at_best': dev_auc_curve[best_iter - 1],
        'valid_auc': valid_metrics['auc'],
        'valid_gini': valid_metrics['gini'],
        'valid_ks': valid_metrics['ks'],
        'overfit_gap(train-valid)': train_metrics['auc'] - valid_metrics['auc'],
        'train_seconds': round(elapsed, 1),
    }
    logging.info(json.dumps(result, indent=2, ensure_ascii=False))
    return result, train_auc_curve, dev_auc_curve


def main():
    features = full_feature_list()
    logging.info(f"Loading corporate_panel with {len(features)} production features...")
    df = load_panel(features)
    train_df, dev_df, valid_df = three_way_split(df)
    logging.info(f"Train={len(train_df)} Dev={len(dev_df)} Valid={len(valid_df)}")
    free(df)

    n_pos = train_df['IS_BUDO_12M'].sum()
    n_neg = len(train_df) - n_pos
    scale_pos_weight = n_neg / n_pos
    logging.info(f"scale_pos_weight (mimics class_weight='balanced'): {scale_pos_weight:.3f}")

    X_train = train_df[features]
    y_train = train_df['IS_BUDO_12M']
    X_dev = dev_df[features]
    y_dev = dev_df['IS_BUDO_12M']
    X_valid = valid_df[features]
    y_valid = valid_df['IS_BUDO_12M']

    train_set = lgb.Dataset(X_train, label=y_train,
                             categorical_feature=['OBV_ELYWRN_OBV_GRD_DSC'], free_raw_data=True)
    dev_set = lgb.Dataset(X_dev, label=y_dev, reference=train_set,
                           categorical_feature=['OBV_ELYWRN_OBV_GRD_DSC'], free_raw_data=True)

    base = dict(objective='binary', metric='auc', boosting_type='gbdt',
                learning_rate=0.05, max_depth=8, num_leaves=31,
                scale_pos_weight=scale_pos_weight, seed=42, verbose=-1, n_jobs=-1)

    variants = {
        'baseline (production config)': dict(base),
        'reg_v1_leaves_and_penalty': dict(base, num_leaves=15, min_child_samples=100,
                                           reg_alpha=1.0, reg_lambda=1.0),
        'reg_v2_subsample': dict(base, feature_fraction=0.7, bagging_fraction=0.7,
                                  bagging_freq=5, min_child_samples=50),
        'reg_v3_combined': dict(base, max_depth=6, num_leaves=20, reg_alpha=0.5, reg_lambda=0.5,
                                 feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=5,
                                 min_child_samples=50),
    }

    results = []
    curves = {}
    for name, params in variants.items():
        res, train_curve, dev_curve = run_variant(name, params, train_set, dev_set, X_train, y_train, X_valid, y_valid)
        results.append(res)
        curves[name] = (train_curve, dev_curve)

    import pandas as pd
    result_df = pd.DataFrame(results)
    out_csv = f'{OUTPUT_DIR}/step14_overfit_comparison.csv'
    result_df.to_csv(out_csv, index=False, encoding='utf-8-sig')
    logging.info(f"\n{result_df.to_string(index=False)}")
    logging.info(f"Saved: {out_csv}")

    # Learning curve plot: baseline vs the best regularized variant (smallest gap with valid_auc within 0.005 of baseline)
    best_reg_name = min(
        (r for r in results if r['name'] != 'baseline (production config)'),
        key=lambda r: r['overfit_gap(train-valid)'],
    )['name']

    plt.rcParams['font.family'] = 'Malgun Gothic'
    plt.rcParams['axes.unicode_minus'] = False
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))
    for ax, name in zip(axes, ['baseline (production config)', best_reg_name]):
        train_curve, dev_curve = curves[name]
        ax.plot(train_curve, label='Train AUC')
        ax.plot(dev_curve, label='Dev AUC')
        ax.set_title(name)
        ax.set_xlabel('Boosting round')
        ax.set_ylabel('AUC')
        ax.legend()
        ax.grid(alpha=0.3)
    plt.tight_layout()
    plot_path = f'{OUTPUT_DIR}/step14_learning_curves.png'
    plt.savefig(plot_path, dpi=150)
    logging.info(f"Saved: {plot_path}")

    with open(f'{OUTPUT_DIR}/step14_best_regularized_variant.json', 'w', encoding='utf-8') as f:
        json.dump({'best_regularized_variant': best_reg_name, 'params': variants[best_reg_name]}, f,
                   ensure_ascii=False, indent=2)


if __name__ == '__main__':
    main()
