"""[Follow-up] Does a genuinely separated Train/Validation/Test split (using all 66 months,
2021.01-2026.06) change the picture further?

Even the step14 Dev/Valid design has a subtle residual issue: the 4 regularization variants
were compared *on Valid*, and the best one (reg_v1) was then reported *using that same Valid
score* -- Valid was used both to pick the winner and to report its performance. This script
fixes that by fully separating the three roles:
  - Train      (2021.01-2023.12, 36mo)  -- fit each candidate config
  - Validation (2024.01-2024.12, 12mo)  -- early stopping AND picking the best config
  - Test       (2025.01-2026.06, 18mo)  -- touched exactly once, for the final reported metric

Test's final ~2 months (2026.05-06) are known to be severely right-censored (see step17), so
the Test metric is reported both including and excluding them.
"""
import json
import logging
import time

import lightgbm as lgb
import pandas as pd

from validation_common import OUTPUT_DIR, evaluate, free, full_feature_list, load_panel

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

TRAIN_END = 202312
VAL_START, VAL_END = 202401, 202412
TEST_START = 202501
TEST_CENSORED_START = 202605  # last 2 months, matches step17's censoring finding


def run_candidate(name, params, X_train, y_train, X_val, y_val, num_boost_round=500):
    t0 = time.time()
    train_set = lgb.Dataset(X_train, label=y_train,
                             categorical_feature=['OBV_ELYWRN_OBV_GRD_DSC'], free_raw_data=True)
    val_set = lgb.Dataset(X_val, label=y_val, reference=train_set,
                           categorical_feature=['OBV_ELYWRN_OBV_GRD_DSC'], free_raw_data=True)
    booster = lgb.train(
        params, train_set, num_boost_round=num_boost_round,
        valid_sets=[val_set], valid_names=['validation'],
        callbacks=[lgb.early_stopping(50, verbose=False), lgb.log_evaluation(0)],
    )
    elapsed = time.time() - t0
    val_prob = booster.predict(X_val, num_iteration=booster.best_iteration)
    val_metrics = evaluate(y_val, val_prob)
    logging.info(f"[{name}] validation_auc={val_metrics['auc']:.5f} best_iter={booster.best_iteration} ({elapsed:.1f}s)")
    return booster, val_metrics, elapsed


def main():
    features = full_feature_list()
    df = load_panel(features)

    train_df = df[df['BASE_YM'] <= TRAIN_END]
    val_df = df[(df['BASE_YM'] >= VAL_START) & (df['BASE_YM'] <= VAL_END)]
    test_df = df[df['BASE_YM'] >= TEST_START]
    test_df_excl_censored = test_df[test_df['BASE_YM'] < TEST_CENSORED_START]
    logging.info(f"Train={len(train_df)} ({train_df['BASE_YM'].min()}-{train_df['BASE_YM'].max()}) "
                 f"Validation={len(val_df)} ({VAL_START}-{VAL_END}) "
                 f"Test={len(test_df)} ({TEST_START}-{test_df['BASE_YM'].max()}) "
                 f"Test(excl. last 2mo)={len(test_df_excl_censored)}")
    free(df)

    X_train, y_train = train_df[features], train_df['IS_BUDO_12M']
    X_val, y_val = val_df[features], val_df['IS_BUDO_12M']
    X_test, y_test = test_df[features], test_df['IS_BUDO_12M']
    X_test_c, y_test_c = test_df_excl_censored[features], test_df_excl_censored['IS_BUDO_12M']

    n_pos = y_train.sum()
    n_neg = len(y_train) - n_pos
    scale_pos_weight = n_neg / n_pos
    base = dict(objective='binary', metric='auc', boosting_type='gbdt',
                learning_rate=0.05, max_depth=8, num_leaves=31,
                scale_pos_weight=scale_pos_weight, seed=42, verbose=-1, n_jobs=-1)
    candidates = {
        'baseline (production config)': dict(base),
        'reg_v1_leaves_and_penalty': dict(base, num_leaves=15, min_child_samples=100,
                                           reg_alpha=1.0, reg_lambda=1.0),
        'reg_v2_subsample': dict(base, feature_fraction=0.7, bagging_fraction=0.7,
                                  bagging_freq=5, min_child_samples=50),
        'reg_v3_combined': dict(base, max_depth=6, num_leaves=20, reg_alpha=0.5, reg_lambda=0.5,
                                 feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=5,
                                 min_child_samples=50),
    }

    logging.info("--- Step A: fit each candidate on Train, select winner using Validation only ---")
    boosters, val_results = {}, []
    for name, params in candidates.items():
        booster, val_metrics, elapsed = run_candidate(name, params, X_train, y_train, X_val, y_val)
        boosters[name] = booster
        val_results.append({'candidate': name, 'validation_auc': val_metrics['auc'],
                             'best_iteration': booster.best_iteration, 'train_seconds': round(elapsed, 1)})

    val_df_results = pd.DataFrame(val_results).sort_values('validation_auc', ascending=False)
    winner_name = val_df_results.iloc[0]['candidate']
    logging.info(f"Winner selected using Validation ONLY: {winner_name}")
    logging.info(f"\n{val_df_results.to_string(index=False)}")

    logging.info("--- Step B: score the winner on Test EXACTLY ONCE (never seen before) ---")
    winner_booster = boosters[winner_name]
    best_iter = winner_booster.best_iteration
    test_prob = winner_booster.predict(X_test, num_iteration=best_iter)
    test_metrics = evaluate(y_test, test_prob)
    test_prob_c = winner_booster.predict(X_test_c, num_iteration=best_iter)
    test_metrics_c = evaluate(y_test_c, test_prob_c)

    summary = {
        'split': {
            'train': f'{TRAIN_END} and before (36mo, n={len(train_df)})',
            'validation': f'{VAL_START}-{VAL_END} (12mo, n={len(val_df)}) -- used ONLY for early stopping + candidate selection',
            'test': f'{TEST_START}-{test_df["BASE_YM"].max()} (18mo, n={len(test_df)}) -- touched exactly once',
        },
        'winner_selected_via_validation': winner_name,
        'validation_auc_of_winner': float(val_df_results.iloc[0]['validation_auc']),
        'test_auc_full_18mo': test_metrics['auc'],
        'test_gini_full_18mo': test_metrics['gini'],
        'test_ks_full_18mo': test_metrics['ks'],
        'test_auc_excl_last2mo_censored': test_metrics_c['auc'],
        'test_gini_excl_last2mo_censored': test_metrics_c['gini'],
        'test_ks_excl_last2mo_censored': test_metrics_c['ks'],
        'reference_original_static_split_auc': 0.9011,
        'reference_step14_dev_valid_auc_of_same_winner_config': 0.91255,
    }
    logging.info(json.dumps(summary, ensure_ascii=False, indent=2))

    val_df_results.to_csv(f'{OUTPUT_DIR}/step20_candidate_selection_on_validation.csv', index=False, encoding='utf-8-sig')
    with open(f'{OUTPUT_DIR}/step20_true_3way_summary.json', 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    logging.info(f"Saved: {OUTPUT_DIR}/step20_candidate_selection_on_validation.csv, step20_true_3way_summary.json")


if __name__ == '__main__':
    main()
