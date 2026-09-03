"""Retrain the production Full(230) and Lean(80->77) LightGBM models with the
regularization + methodology fixes confirmed in docs/step28:

  1. Regularized params (num_leaves=15, min_child_samples=100, reg_alpha=1.0, reg_lambda=1.0)
     instead of the production defaults, which step14 showed both closes the overfit gap
     AND improves true holdout AUC.
  2. Early stopping is done against a Dev slice (last 3 months of TRAIN) instead of the
     final-report Valid set, then the winning boosting-round count is used to refit on the
     FULL Train window (all 36 months) so no training data is wasted in the deployed model.
  3. The Lean model additionally drops the lower-importance half of each of the 3 near-
     duplicate (raw vs. 3-month-moving-average) feature pairs identified in step21
     (BSI_mfg_export_yoy, call_rate_overnight_diff12, import_index_yoy), going from 80 to 77
     features.

Outputs:
  - eda_pipeline/output/lgbm_12m_model.txt       (overwritten; old copy -> lgbm_12m_model_prev.txt)
  - eda_pipeline/output/lgbm_12m_lean_model.txt   (overwritten; old copy -> lgbm_12m_lean_model_prev.txt)
  - eda_pipeline/output/step13_performance_metrics.txt (regenerated, same format monitoring.py parses)
"""
import json
import logging
import shutil

import lightgbm as lgb

from validation_common import (
    FULL_MODEL_PATH, LEAN_MODEL_PATH, OUTPUT_DIR, calculate_psi, evaluate,
    free, full_feature_list, lean_feature_list, load_panel, TRAIN_END, DEV_START, DEV_END,
    VALID_START, CATEGORICAL_COLS,
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

REG_PARAMS_TEMPLATE = dict(
    objective='binary', metric='auc', boosting_type='gbdt',
    learning_rate=0.05, max_depth=8, num_leaves=15, min_child_samples=100,
    reg_alpha=1.0, reg_lambda=1.0, seed=42, verbose=-1, n_jobs=-1,
)


def resolve_lean_features():
    """step21_full_multicollinearity_check.py's standalone VIF-diet run over the current
    Lean(80) set (Check A) directly identified these 3 features as the ones whose removal
    brings the whole set's VIF <= 10 (near-infinite VIF, i.e. near-perfectly explained by
    some combination of the rest of the set -- not necessarily a single raw/ma3m partner,
    that was only true for BSI_mfg_export_yoy; the other two don't even have their ma3m
    companion in the Lean set). So we drop exactly these 3, as VIF-diet itself determined.
    """
    features = lean_feature_list()
    drop = ['BSI_mfg_export_yoy', 'call_rate_overnight_diff12', 'import_index_yoy']
    drop = [d for d in drop if d in features]
    final_features = [f for f in features if f not in drop]
    logging.info(f"Lean feature set: {len(features)} -> {len(final_features)} (dropped {drop}, "
                 f"per step21's standalone VIF-diet check A result)")
    return final_features


def train_final_model(name, features, backup_path, save_path):
    df = load_panel(features)
    train_all = df[df['BASE_YM'] <= TRAIN_END].copy()
    dev_mask = (train_all['BASE_YM'] >= DEV_START) & (train_all['BASE_YM'] <= DEV_END)
    train_fit = train_all[~dev_mask]
    dev = train_all[dev_mask]
    valid = df[df['BASE_YM'] >= VALID_START].copy()
    free(df)

    n_pos = train_fit['IS_BUDO_12M'].sum()
    n_neg = len(train_fit) - n_pos
    params = dict(REG_PARAMS_TEMPLATE, scale_pos_weight=n_neg / n_pos)
    cat_features = [c for c in CATEGORICAL_COLS if c in features]

    logging.info(f"[{name}] Stage 1: fit on Train-minus-Dev ({len(train_fit)}), early-stop on Dev ({len(dev)})")
    train_set = lgb.Dataset(train_fit[features], label=train_fit['IS_BUDO_12M'],
                             categorical_feature=cat_features, free_raw_data=True)
    dev_set = lgb.Dataset(dev[features], label=dev['IS_BUDO_12M'], reference=train_set,
                           categorical_feature=cat_features, free_raw_data=True)
    booster_probe = lgb.train(
        params, train_set, num_boost_round=500, valid_sets=[dev_set], valid_names=['dev'],
        callbacks=[lgb.early_stopping(50, verbose=False), lgb.log_evaluation(0)],
    )
    best_iter = booster_probe.best_iteration
    logging.info(f"[{name}] best_iteration from Dev early-stopping: {best_iter}")

    logging.info(f"[{name}] Stage 2: refit on FULL Train ({len(train_all)}, all 36mo) with fixed {best_iter} rounds")
    full_train_set = lgb.Dataset(train_all[features], label=train_all['IS_BUDO_12M'],
                                  categorical_feature=cat_features, free_raw_data=True)
    final_booster = lgb.train(params, full_train_set, num_boost_round=best_iter)

    train_prob = final_booster.predict(train_all[features])
    valid_prob = final_booster.predict(valid[features])
    train_metrics = evaluate(train_all['IS_BUDO_12M'], train_prob)
    valid_metrics = evaluate(valid['IS_BUDO_12M'], valid_prob)
    psi = calculate_psi(train_prob, valid_prob)

    logging.info(f"[{name}] FINAL -- Train AUC={train_metrics['auc']:.4f}, Valid AUC={valid_metrics['auc']:.4f}, "
                 f"Valid Gini={valid_metrics['gini']:.4f}, Valid K-S={valid_metrics['ks']:.4f}, PSI={psi:.4f}")

    shutil.copy(save_path, backup_path)
    logging.info(f"Backed up previous model: {save_path} -> {backup_path}")
    final_booster.save_model(save_path)
    logging.info(f"Saved new model: {save_path}")

    return {
        'name': name, 'n_features': len(features), 'best_iteration': best_iter,
        'train_auc': train_metrics['auc'], 'train_gini': train_metrics['gini'], 'train_ks': train_metrics['ks'],
        'valid_auc': valid_metrics['auc'], 'valid_gini': valid_metrics['gini'], 'valid_ks': valid_metrics['ks'],
        'psi': psi,
    }


def write_step13_metrics_file(full_result):
    text = "=== STEP 13: Core Performance Metrics (retrained, docs/step29) ===\n\n"
    text += "[1] ROC-AUC Score\n"
    text += f" - Train AUC : {full_result['train_auc']:.4f}\n"
    text += f" - Valid AUC : {full_result['valid_auc']:.4f}\n"
    text += f" - Degradation : {full_result['train_auc'] - full_result['valid_auc']:.4f}\n\n"
    text += "[2] Gini Index\n"
    text += f" - Train Gini: {full_result['train_gini']:.4f} ({full_result['train_gini']*100:.1f})\n"
    text += f" - Valid Gini: {full_result['valid_gini']:.4f} ({full_result['valid_gini']*100:.1f})\n\n"
    text += "[3] Kolmogorov-Smirnov (K-S) Statistic\n"
    text += f" - Train K-S : {full_result['train_ks']:.4f} ({full_result['train_ks']*100:.1f})\n"
    text += f" - Valid K-S : {full_result['valid_ks']:.4f} ({full_result['valid_ks']*100:.1f})\n"
    text += "   * Interpretation: > 0.4 (40) indicates excellent separation.\n\n"
    text += "[4] Population Stability Index (PSI)\n"
    text += f" - Total PSI : {full_result['psi']:.4f}\n"
    text += "   * Interpretation: < 0.1 (Very Stable), 0.1~0.25 (Monitor), > 0.25 (Unstable, Needs Retraining)\n"
    out_path = FULL_MODEL_PATH.replace('lgbm_12m_model.txt', 'step13_performance_metrics.txt')
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(text)
    logging.info(f"Regenerated: {out_path}")


def main():
    lean_features = resolve_lean_features()
    full_features = full_feature_list()

    full_result = train_final_model(
        'Full (230)', full_features,
        backup_path=FULL_MODEL_PATH.replace('lgbm_12m_model.txt', 'lgbm_12m_model_prev.txt'),
        save_path=FULL_MODEL_PATH,
    )
    lean_result = train_final_model(
        f'Lean ({len(lean_features)})', lean_features,
        backup_path=LEAN_MODEL_PATH.replace('lgbm_12m_lean_model.txt', 'lgbm_12m_lean_model_prev.txt'),
        save_path=LEAN_MODEL_PATH,
    )

    write_step13_metrics_file(full_result)

    summary = {'full': full_result, 'lean': lean_result}
    with open(f'{OUTPUT_DIR}/step23_retrain_summary.json', 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    logging.info(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
