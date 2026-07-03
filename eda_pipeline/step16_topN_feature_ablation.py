"""[Validation 3/5] Does cutting the feature set down to the top 20 hold up?

Compares three feature sets under an identical Train/Dev/Valid split and the *regularized*
LightGBM config chosen in step14 (falls back to the production baseline config if step14
hasn't been run yet):
  - Full   (230 features, eda_pipeline/output/lgbm_12m_model.txt's feature set)
  - Lean   (80 features, the existing VIF-diet set from step9_vif_zscore_tuning.py)
  - Top-20 (by LightGBM gain importance of the production Full model, cross-checked against
            the SHAP ranking from step15 if available)
"""
import json
import logging
import os
import time

import lightgbm as lgb
import pandas as pd

from validation_common import (
    FULL_MODEL_PATH, OUTPUT_DIR, calculate_psi, evaluate, free, full_feature_list,
    lean_feature_list, load_panel, three_way_split,
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')


def load_reg_params(n_pos, n_neg):
    base = dict(objective='binary', metric='auc', boosting_type='gbdt',
                learning_rate=0.05, max_depth=8, num_leaves=31,
                scale_pos_weight=n_neg / n_pos, seed=42, verbose=-1, n_jobs=-1)
    variant_path = f'{OUTPUT_DIR}/step14_best_regularized_variant.json'
    if os.path.exists(variant_path):
        with open(variant_path, encoding='utf-8') as f:
            info = json.load(f)
        params = dict(info['params'])
        params['scale_pos_weight'] = n_neg / n_pos  # recompute for this data slice
        logging.info(f"Using regularized params from step14: {info['best_regularized_variant']}")
        return params
    logging.info("step14 output not found -- falling back to production baseline params")
    return base


def top20_by_gain():
    model = lgb.Booster(model_file=FULL_MODEL_PATH)
    imp = pd.Series(model.feature_importance(importance_type='gain'), index=model.feature_name())
    return imp.sort_values(ascending=False).head(20).index.tolist()


def train_and_eval(name, features, params, train_df, dev_df, valid_df, num_boost_round=500):
    logging.info(f"--- {name}: {len(features)} features ---")
    t0 = time.time()
    train_set = lgb.Dataset(train_df[features], label=train_df['IS_BUDO_12M'],
                             categorical_feature=[c for c in ['OBV_ELYWRN_OBV_GRD_DSC'] if c in features],
                             free_raw_data=True)
    dev_set = lgb.Dataset(dev_df[features], label=dev_df['IS_BUDO_12M'], reference=train_set,
                           categorical_feature=[c for c in ['OBV_ELYWRN_OBV_GRD_DSC'] if c in features],
                           free_raw_data=True)
    booster = lgb.train(
        params, train_set, num_boost_round=num_boost_round,
        valid_sets=[dev_set], valid_names=['dev'],
        callbacks=[lgb.early_stopping(50, verbose=False), lgb.log_evaluation(0)],
    )
    elapsed = time.time() - t0
    best_iter = booster.best_iteration

    train_prob = booster.predict(train_df[features], num_iteration=best_iter)
    valid_prob = booster.predict(valid_df[features], num_iteration=best_iter)
    metrics = evaluate(valid_df['IS_BUDO_12M'], valid_prob)
    psi = calculate_psi(train_prob, valid_prob)

    result = {
        'feature_set': name,
        'n_features': len(features),
        'best_iteration': best_iter,
        'valid_auc': metrics['auc'],
        'valid_gini': metrics['gini'],
        'valid_ks': metrics['ks'],
        'psi_train_vs_valid': psi,
        'train_seconds': round(elapsed, 1),
    }
    logging.info(json.dumps(result, indent=2, ensure_ascii=False))
    return result


def main():
    full_features = full_feature_list()
    lean_features = lean_feature_list()
    top20_features = top20_by_gain()
    logging.info(f"Top-20 by gain: {top20_features}")

    df = load_panel(full_features)
    train_df, dev_df, valid_df = three_way_split(df)
    logging.info(f"Train={len(train_df)} Dev={len(dev_df)} Valid={len(valid_df)}")
    free(df)

    n_pos = train_df['IS_BUDO_12M'].sum()
    n_neg = len(train_df) - n_pos
    params = load_reg_params(n_pos, n_neg)

    results = []
    for name, feats in [('Full (230)', full_features), ('Lean/VIF (80)', lean_features), ('Top-20 (gain)', top20_features)]:
        results.append(train_and_eval(name, feats, dict(params), train_df, dev_df, valid_df))

    result_df = pd.DataFrame(results)
    out_csv = f'{OUTPUT_DIR}/step16_topN_ablation.csv'
    result_df.to_csv(out_csv, index=False, encoding='utf-8-sig')
    logging.info(f"\n{result_df.to_string(index=False)}")
    logging.info(f"Saved: {out_csv}")


if __name__ == '__main__':
    main()
