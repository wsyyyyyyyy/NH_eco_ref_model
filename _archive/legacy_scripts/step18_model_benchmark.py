"""[Validation 5/5] Benchmark LightGBM against other model families.

Uses the Lean/VIF 80-feature set (dense sklearn models don't scale well to 230 raw features
x ~1.9M rows on this machine) with the identical Train/Dev/Valid split used elsewhere in this
validation suite. Models compared:
  - LightGBM, production baseline config
  - LightGBM, regularized config chosen in step14 (falls back to baseline if step14 wasn't run)
  - Logistic Regression (L2, standardized + median-imputed) -- classic scorecard baseline
  - Random Forest (median-imputed)
  - XGBoost (hist, native NaN handling like LightGBM)
"""
import json
import logging
import os
import time

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from validation_common import (
    OUTPUT_DIR, calculate_psi, evaluate, free, lean_feature_list, load_panel, three_way_split,
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
        params['scale_pos_weight'] = n_neg / n_pos
        return params, info['best_regularized_variant']
    return base, 'baseline (step14 not found)'


def encode_categorical(df, features):
    X = df[features].copy()
    if 'OBV_ELYWRN_OBV_GRD_DSC' in X.columns:
        X['OBV_ELYWRN_OBV_GRD_DSC'] = (X['OBV_ELYWRN_OBV_GRD_DSC'] == 'B').astype(float)
    return X.replace([np.inf, -np.inf], np.nan)


def bench_lightgbm(name, params, features, train_df, dev_df, valid_df):
    t0 = time.time()
    train_set = lgb.Dataset(train_df[features], label=train_df['IS_BUDO_12M'],
                             categorical_feature=['OBV_ELYWRN_OBV_GRD_DSC'], free_raw_data=True)
    dev_set = lgb.Dataset(dev_df[features], label=dev_df['IS_BUDO_12M'], reference=train_set,
                           categorical_feature=['OBV_ELYWRN_OBV_GRD_DSC'], free_raw_data=True)
    booster = lgb.train(params, train_set, num_boost_round=500, valid_sets=[dev_set], valid_names=['dev'],
                         callbacks=[lgb.early_stopping(50, verbose=False), lgb.log_evaluation(0)])
    elapsed = time.time() - t0
    train_prob = booster.predict(train_df[features], num_iteration=booster.best_iteration)
    valid_prob = booster.predict(valid_df[features], num_iteration=booster.best_iteration)
    return finalize(name, elapsed, train_df['IS_BUDO_12M'], train_prob, valid_df['IS_BUDO_12M'], valid_prob)


def bench_xgboost(features, train_df, dev_df, valid_df, n_pos, n_neg):
    import xgboost as xgb
    t0 = time.time()
    X_train = encode_categorical(train_df, features)
    X_dev = encode_categorical(dev_df, features)
    X_valid = encode_categorical(valid_df, features)
    model = xgb.XGBClassifier(
        n_estimators=500, max_depth=8, learning_rate=0.05,
        scale_pos_weight=n_neg / n_pos, tree_method='hist', n_jobs=-1,
        random_state=42, eval_metric='auc', early_stopping_rounds=50,
    )
    model.fit(X_train, train_df['IS_BUDO_12M'], eval_set=[(X_dev, dev_df['IS_BUDO_12M'])], verbose=False)
    elapsed = time.time() - t0
    train_prob = model.predict_proba(X_train)[:, 1]
    valid_prob = model.predict_proba(X_valid)[:, 1]
    return finalize('XGBoost', elapsed, train_df['IS_BUDO_12M'], train_prob, valid_df['IS_BUDO_12M'], valid_prob)


def bench_logreg(features, train_df, dev_df, valid_df):
    t0 = time.time()
    X_train = encode_categorical(train_df, features)
    X_valid = encode_categorical(valid_df, features)
    imputer = SimpleImputer(strategy='median')
    scaler = StandardScaler()
    X_train_t = scaler.fit_transform(imputer.fit_transform(X_train))
    X_valid_t = scaler.transform(imputer.transform(X_valid))
    model = LogisticRegression(max_iter=300, class_weight='balanced', solver='lbfgs')
    model.fit(X_train_t, train_df['IS_BUDO_12M'])
    elapsed = time.time() - t0
    train_prob = model.predict_proba(X_train_t)[:, 1]
    valid_prob = model.predict_proba(X_valid_t)[:, 1]
    return finalize('Logistic Regression (L2)', elapsed, train_df['IS_BUDO_12M'], train_prob, valid_df['IS_BUDO_12M'], valid_prob)


def bench_random_forest(features, train_df, valid_df):
    t0 = time.time()
    X_train = encode_categorical(train_df, features)
    X_valid = encode_categorical(valid_df, features)
    imputer = SimpleImputer(strategy='median')
    X_train_t = imputer.fit_transform(X_train)
    X_valid_t = imputer.transform(X_valid)
    model = RandomForestClassifier(n_estimators=200, max_depth=12, n_jobs=-1,
                                    class_weight='balanced', random_state=42)
    model.fit(X_train_t, train_df['IS_BUDO_12M'])
    elapsed = time.time() - t0
    train_prob = model.predict_proba(X_train_t)[:, 1]
    valid_prob = model.predict_proba(X_valid_t)[:, 1]
    return finalize('Random Forest', elapsed, train_df['IS_BUDO_12M'], train_prob, valid_df['IS_BUDO_12M'], valid_prob)


def finalize(name, elapsed, y_train, train_prob, y_valid, valid_prob):
    train_metrics = evaluate(y_train, train_prob)
    valid_metrics = evaluate(y_valid, valid_prob)
    result = {
        'model': name,
        'train_auc': train_metrics['auc'],
        'valid_auc': valid_metrics['auc'],
        'valid_gini': valid_metrics['gini'],
        'valid_ks': valid_metrics['ks'],
        'overfit_gap': train_metrics['auc'] - valid_metrics['auc'],
        'psi_train_vs_valid': calculate_psi(train_prob, valid_prob),
        'train_seconds': round(elapsed, 1),
    }
    logging.info(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def main():
    features = lean_feature_list()
    logging.info(f"Loading Lean(80)-feature panel...")
    df = load_panel(features)
    train_df, dev_df, valid_df = three_way_split(df)
    logging.info(f"Train={len(train_df)} Dev={len(dev_df)} Valid={len(valid_df)}")
    free(df)

    n_pos = train_df['IS_BUDO_12M'].sum()
    n_neg = len(train_df) - n_pos
    base_params = dict(objective='binary', metric='auc', boosting_type='gbdt',
                        learning_rate=0.05, max_depth=8, num_leaves=31,
                        scale_pos_weight=n_neg / n_pos, seed=42, verbose=-1, n_jobs=-1)
    reg_params, reg_name = load_reg_params(n_pos, n_neg)

    results = []
    results.append(bench_lightgbm('LightGBM (production baseline config)', base_params, features, train_df, dev_df, valid_df))
    results.append(bench_lightgbm(f'LightGBM (regularized: {reg_name})', reg_params, features, train_df, dev_df, valid_df))
    results.append(bench_logreg(features, train_df, dev_df, valid_df))
    results.append(bench_random_forest(features, train_df, valid_df))
    try:
        results.append(bench_xgboost(features, train_df, dev_df, valid_df, n_pos, n_neg))
    except ImportError:
        logging.warning("xgboost not installed -- skipping XGBoost benchmark")

    result_df = pd.DataFrame(results)
    out_csv = f'{OUTPUT_DIR}/step18_model_benchmark.csv'
    result_df.to_csv(out_csv, index=False, encoding='utf-8-sig')
    logging.info(f"\n{result_df.to_string(index=False)}")
    logging.info(f"Saved: {out_csv}")


if __name__ == '__main__':
    main()
