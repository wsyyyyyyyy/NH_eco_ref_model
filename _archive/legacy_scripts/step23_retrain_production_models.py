"""Retrain the Full and Lean LightGBM models with the regularization + methodology fixes
confirmed in docs/appendix/step28, on the leakage-cleaned feature set (STAGE 1 refactor).

  1. Regularized params (num_leaves=15, min_child_samples=100, reg_alpha=1.0, reg_lambda=1.0)
     instead of the production defaults, which step14 showed both closes the overfit gap
     AND improves true holdout AUC.
  2. Early stopping is done against a Dev slice (last 3 months of TRAIN) instead of the
     final-report Valid set, then the winning boosting-round count is used to refit on the
     FULL Train window (all 36 months) so no training data is wasted in the deployed model.
  3. Feature sets are no longer inherited from the previously trained model files. The old
     models carry leakage columns (COPR_OPNP_C, the CRIF family), so reading their
     feature_name() back in would silently re-import the very leakage this refactor removes.
     The Full set is now derived from the training table's own columns minus
     eda_pipeline/leaky_cols.LEAK_CONFIRMED + NON_FEATURE, and the Lean set is managed as an
     explicit JSON list.

Inputs (READ ONLY -- never written):
  - eda_pipeline/output/lgbm_12m_model.txt      : STAGE 6 S0 baseline. Not read, not written.
  - eda_pipeline/output/lgbm_12m_lean_model.txt : STAGE 6 S0 baseline. Not read, not written.

Outputs (all new filenames -- the STAGE 1 rules forbid overwriting the two files above):
  - eda_pipeline/output/lgbm_v2_full.txt                 (old copy -> lgbm_v2_full_prev.txt)
  - eda_pipeline/output/lgbm_v2_lean.txt                 (old copy -> lgbm_v2_lean_prev.txt)
  - eda_pipeline/output/lean_features_v2.json            (the Lean feature list of record)
  - eda_pipeline/output/step13_performance_metrics_v2.txt
  - eda_pipeline/output/step23_retrain_summary_v2.json
"""
import json
import logging
import os
import shutil
import sys
from pathlib import Path

import duckdb
import lightgbm as lgb

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from eda_pipeline import config
from eda_pipeline.leaky_cols import LEAK_CONFIRMED, LEAK_SUSPECT, NON_FEATURE

from validation_common import (
    DB_PATH, calculate_psi, evaluate, free, load_panel,
    TRAIN_END, DEV_START, DEV_END, VALID_START, CATEGORICAL_COLS,
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

# 규칙 5: lgbm_12m_model.txt / lgbm_12m_lean_model.txt 는 덮어쓰지 않는다.
#         새 모델은 반드시 다른 파일명으로 저장한다.
V2_FULL_PATH = str(config.OUTPUT_DIR / 'lgbm_v2_full.txt')
V2_LEAN_PATH = str(config.OUTPUT_DIR / 'lgbm_v2_lean.txt')
LEAN_FEATURES_JSON = config.OUTPUT_DIR / 'lean_features_v2.json'

# step21의 standalone VIF-diet(Check A)가 지목한 3개. VIF <= 10 을 만들기 위해 제거한다.
VIF_DROP = ['BSI_mfg_export_yoy', 'call_rate_overnight_diff12', 'import_index_yoy']

REG_PARAMS_TEMPLATE = dict(
    objective='binary', metric='auc', boosting_type='gbdt',
    learning_rate=0.05, max_depth=8, num_leaves=15, min_child_samples=100,
    reg_alpha=1.0, reg_lambda=1.0, seed=42, verbose=-1, n_jobs=-1,
)


def panel_columns():
    """corporate_panel 의 컬럼 목록을 읽는다 (규칙 6: read_only 연결)."""
    con = duckdb.connect(DB_PATH, read_only=True)
    try:
        cols = [r[0] for r in con.execute('DESCRIBE corporate_panel').fetchall()]
    finally:
        con.close()
    return cols


def resolve_full_features():
    """학습 테이블 컬럼에서 확정 누수 + 비피처 컬럼을 제외해 Full 피처를 직접 구성한다.

    기존처럼 lgb.Booster(model_file=...).feature_name() 으로 과거 모델에서 물려받지 않는다.
    그 목록에는 COPR_OPNP_C / CRIF 계열 같은 누수 변수가 그대로 들어 있기 때문이다.
    """
    cols = panel_columns()
    excluded = set(NON_FEATURE) | set(LEAK_CONFIRMED)
    features = [c for c in cols if c not in excluded]
    removed = sorted(set(cols) & set(LEAK_CONFIRMED))
    logging.info(f"Full feature set: {len(cols)} columns -> {len(features)} features "
                 f"(누수 제외 {removed}, 비피처 제외 {len(set(cols) & set(NON_FEATURE))}개)")
    if LEAK_SUSPECT:
        present = sorted(set(features) & set(LEAK_SUSPECT))
        if present:
            logging.info(f"  [LEAK_SUSPECT 포함됨 — STAGE 6에서 on/off 비교 대상] {present}")
    return features


def resolve_lean_features(full_features):
    """Lean 피처 목록은 JSON(lean_features_v2.json)으로 관리한다.

    JSON이 있으면 그대로 사용하고, 없으면 Full 에서 VIF_DROP 3개를 뺀 잠정 목록을 만들어
    저장한 뒤 사용한다. 잠정 목록임을 JSON 안에 명시하므로, STAGE 6에서 중요도/VIF 기반
    선별을 다시 돌린 결과로 이 파일을 갱신하면 된다.
    """
    if LEAN_FEATURES_JSON.exists():
        with open(LEAN_FEATURES_JSON, encoding='utf-8') as f:
            payload = json.load(f)
        features = payload['features']
        missing = [f for f in features if f not in full_features]
        if missing:
            raise ValueError(
                f"{LEAN_FEATURES_JSON.name} 의 피처 {missing} 가 학습 테이블에 없습니다. "
                f"누수 제거로 사라진 컬럼이라면 JSON을 갱신하세요.")
        logging.info(f"Lean feature set: {len(features)} (from {LEAN_FEATURES_JSON.name}, "
                     f"provisional={payload.get('provisional')})")
        return features

    features = [f for f in full_features if f not in VIF_DROP]
    payload = {
        'provisional': True,
        '_note': ('STAGE 1 리팩터링 시점의 잠정 목록. Full 에서 step21 VIF-diet(Check A)가 '
                  '지목한 3개만 제외했다. STAGE 6에서 중요도/VIF 선별을 다시 돌린 결과로 '
                  '이 파일을 갱신할 것.'),
        'derived_from': 'resolve_full_features() - VIF_DROP',
        'vif_dropped': [d for d in VIF_DROP if d in full_features],
        'features': features,
    }
    LEAN_FEATURES_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(LEAN_FEATURES_JSON, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    logging.warning(f"{LEAN_FEATURES_JSON.name} 이 없어 잠정 Lean 목록 {len(features)}개를 "
                    f"생성했습니다 (Full - {payload['vif_dropped']}).")
    return features


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

    # 이전 v2 모델이 있을 때만 백업한다 (최초 실행에는 백업 대상이 없다).
    if os.path.exists(save_path):
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
    text = "=== STEP 13: Core Performance Metrics (retrained v2, leakage-cleaned) ===\n\n"
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
    # 기존 step13_performance_metrics.txt 는 S0 베이스라인 모델의 지표이므로 덮어쓰지 않는다.
    out_path = config.OUTPUT_DIR / 'step13_performance_metrics_v2.txt'
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(text)
    logging.info(f"Regenerated: {out_path}")


def main():
    full_features = resolve_full_features()
    lean_features = resolve_lean_features(full_features)

    full_result = train_final_model(
        f'Full ({len(full_features)})', full_features,
        backup_path=str(config.OUTPUT_DIR / 'lgbm_v2_full_prev.txt'),
        save_path=V2_FULL_PATH,
    )
    lean_result = train_final_model(
        f'Lean ({len(lean_features)})', lean_features,
        backup_path=str(config.OUTPUT_DIR / 'lgbm_v2_lean_prev.txt'),
        save_path=V2_LEAN_PATH,
    )

    write_step13_metrics_file(full_result)

    summary = {'full': full_result, 'lean': lean_result}
    out = config.OUTPUT_DIR / 'step23_retrain_summary_v2.json'
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    logging.info(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
