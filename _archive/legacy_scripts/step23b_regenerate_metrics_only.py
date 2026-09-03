"""One-off fix: step23_retrain_production_models.py's model retraining succeeded and saved
both new model files, but crashed on a relative-path bug before writing
step13_performance_metrics.txt. This reloads the already-saved new Full model (no retraining)
and just regenerates that metrics file.
"""
import logging

import lightgbm as lgb

from validation_common import FULL_MODEL_PATH, evaluate, calculate_psi, load_panel, TRAIN_END, VALID_START
from step23_retrain_production_models import write_step13_metrics_file

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')


def main():
    model = lgb.Booster(model_file=FULL_MODEL_PATH)
    features = model.feature_name()
    df = load_panel(features)
    train = df[df['BASE_YM'] <= TRAIN_END]
    valid = df[df['BASE_YM'] >= VALID_START]

    train_prob = model.predict(train[features])
    valid_prob = model.predict(valid[features])
    train_metrics = evaluate(train['IS_BUDO_12M'], train_prob)
    valid_metrics = evaluate(valid['IS_BUDO_12M'], valid_prob)
    psi = calculate_psi(train_prob, valid_prob)

    logging.info(f"Train AUC={train_metrics['auc']:.4f} Valid AUC={valid_metrics['auc']:.4f} "
                 f"Valid Gini={valid_metrics['gini']:.4f} Valid K-S={valid_metrics['ks']:.4f} PSI={psi:.4f}")

    result = {
        'train_auc': train_metrics['auc'], 'train_gini': train_metrics['gini'], 'train_ks': train_metrics['ks'],
        'valid_auc': valid_metrics['auc'], 'valid_gini': valid_metrics['gini'], 'valid_ks': valid_metrics['ks'],
        'psi': psi,
    }
    write_step13_metrics_file(result)


if __name__ == '__main__':
    main()
