import pandas as pd
import numpy as np
import lightgbm as lgb
import matplotlib.pyplot as plt
import shap
import logging
from sklearn.metrics import precision_recall_curve, roc_auc_score, fbeta_score

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
import matplotlib.font_manager as fm

def set_korean_font():
    # Windows default Korean font
    font_path = 'C:/Windows/Fonts/malgun.ttf'
    if os.path.exists(font_path):
        font_name = fm.FontProperties(fname=font_path).get_name()
        plt.rc('font', family=font_name)
    plt.rc('axes', unicode_minus=False)

import os
set_korean_font()

def main():
    input_path = 'eda_pipeline/output/nh_panel_macro_12m.csv'
    model_path = 'eda_pipeline/output/lgbm_12m_model.txt'
    out_dir = 'C:/Users/User/.gemini/antigravity/brain/617e8e08-d8ba-41a7-9ac5-95cca35aa6fe'
    
    logging.info("데이터 로딩 중...")
    df = pd.read_csv(input_path)
    df['BASE_YM'] = df['BASE_YM'].astype(str)
    
    ignore_cols = ['V_BZNO', 'BASE_YM', 'SPLIT', 'IS_BUDO_12M']
    features = [c for c in df.columns if c not in ignore_cols]
    
    logging.info("모델 로딩 중...")
    model = lgb.Booster(model_file=model_path)
    
    valid_df = df[df['BASE_YM'] >= '202401'].copy()
    X_valid = valid_df[features].copy()
    y_valid = valid_df['IS_BUDO_12M'].copy()
    
    cat_cols = [c for c in valid_df.select_dtypes(include=['object', 'string']).columns if c in features]
    for c in cat_cols:
        X_valid[c] = X_valid[c].astype('category')
            
    logging.info("예측 확률 산출...")
    preds = model.predict(X_valid)
    
    # 1. 임계값 및 비용 기반 최적화
    logging.info("1. 임계값 및 비용 기반 최적화")
    precisions, recalls, thresholds = precision_recall_curve(y_valid, preds)
    
    # F1-Score
    f1_scores = 2 * (precisions[:-1] * recalls[:-1]) / (precisions[:-1] + recalls[:-1] + 1e-10)
    best_f1_idx = np.argmax(f1_scores)
    best_f1_thresh = thresholds[best_f1_idx]
    
    # F2-Score (Recall 가중치 2)
    f2_scores = fbeta_score_custom(precisions[:-1], recalls[:-1], beta=2)
    best_f2_idx = np.argmax(f2_scores)
    best_f2_thresh = thresholds[best_f2_idx]
    
    # Cost-Optimal (FN_Cost = 20, FP_Cost = 1)
    # Total Cost = FN_Cost * FN + FP_Cost * FP
    # We can evaluate cost over thresholds
    fn_cost_weight = 20
    fp_cost_weight = 1
    
    total_positives = y_valid.sum()
    tp = recalls[:-1] * total_positives
    fn = total_positives - tp
    
    fp = np.zeros_like(tp)
    valid_p = precisions[:-1] > 0
    fp[valid_p] = tp[valid_p] / precisions[:-1][valid_p] - tp[valid_p]
    
    costs = (fn * fn_cost_weight) + (fp * fp_cost_weight)
    
    best_cost_idx = np.argmin(costs)
    best_cost_thresh = thresholds[best_cost_idx]
    
    plt.figure(figsize=(12, 5))
    plt.subplot(1, 2, 1)
    plt.plot(recalls[:-1], precisions[:-1], label='PR Curve', color='blue')
    plt.plot(recalls[best_f1_idx], precisions[best_f1_idx], 'ro', label=f'Best F1 (Thr={best_f1_thresh:.3f})')
    plt.plot(recalls[best_f2_idx], precisions[best_f2_idx], 'go', label=f'Best F2 (Thr={best_f2_thresh:.3f})')
    plt.plot(recalls[best_cost_idx], precisions[best_cost_idx], 'ko', label=f'Min Cost (Thr={best_cost_thresh:.3f})')
    plt.xlabel('Recall')
    plt.ylabel('Precision')
    plt.title('Precision-Recall Curve')
    plt.legend()
    
    plt.subplot(1, 2, 2)
    plt.plot(thresholds, costs, color='red')
    plt.axvline(best_cost_thresh, color='k', linestyle='--', label=f'Min Cost Thr={best_cost_thresh:.3f}')
    plt.xlabel('Threshold')
    plt.ylabel('Total Cost (FN=20, FP=1)')
    plt.title('Cost Curve by Threshold')
    plt.legend()
    plt.tight_layout()
    plt.savefig(f"{out_dir}/threshold_optimization.png")
    plt.close()
    
    with open(f"{out_dir}/threshold_analysis.txt", 'w') as f:
        f.write(f"Best F1 Threshold: {best_f1_thresh:.4f} (Precision: {precisions[best_f1_idx]:.4f}, Recall: {recalls[best_f1_idx]:.4f})\n")
        f.write(f"Best F2 Threshold: {best_f2_thresh:.4f} (Precision: {precisions[best_f2_idx]:.4f}, Recall: {recalls[best_f2_idx]:.4f})\n")
        f.write(f"Min Cost Threshold: {best_cost_thresh:.4f} (Precision: {precisions[best_cost_idx]:.4f}, Recall: {recalls[best_cost_idx]:.4f})\n")

    # 2. SHAP Dependence Plot
    logging.info("2. SHAP Dependence Plot")
    # To save time, we take a sample of valid_df for SHAP computation
    shap_sample = X_valid.sample(min(10000, len(X_valid)), random_state=42)
    explainer = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(shap_sample)
    if isinstance(shap_values, list):
        shap_values = shap_values[1] # positive class
        
    importance = model.feature_importance(importance_type='gain')
    feature_imp = pd.DataFrame({'Feature': features, 'Importance': importance}).sort_values(by='Importance', ascending=False)
    
    top_continuous = []
    for feat in feature_imp['Feature']:
        if feat not in cat_cols and len(shap_sample[feat].unique()) > 10:
            top_continuous.append(feat)
        if len(top_continuous) >= 12:
            break
            
    fig, axes = plt.subplots(4, 3, figsize=(18, 20))
    axes = axes.flatten()
    for i, feat in enumerate(top_continuous):
        shap.dependence_plot(feat, shap_values, shap_sample, ax=axes[i], show=False, interaction_index=None)
        axes[i].set_title(f"SHAP: {feat}")
    plt.tight_layout()
    plt.savefig(f"{out_dir}/shap_dependence.png")
    plt.close()

    # 3. Missing Value Impact Analysis
    logging.info("3. 결측치/특이값 영향도 분석")
    # For CG01_KIS_SCORE, we need to know the median that was used.
    # Since step5 used the median of the entire dataset at the time of fillna, we can guess it's the most frequent value.
    median_kis = df['CG01_KIS_SCORE'].mode()[0]
    
    kis_score_idx = features.index('CG01_KIS_SCORE')
    crif_rsnc_idx = features.index('CRIF_CRDBD_RSNC')
    
    shap_sample_full = X_valid.copy()
    shap_vals_full = explainer.shap_values(shap_sample_full)
    if isinstance(shap_vals_full, list):
        shap_vals_full = shap_vals_full[1]
        
    # KIS_SCORE Analysis
    is_missing_kis = (shap_sample_full['CG01_KIS_SCORE'] == median_kis)
    kis_missing_shap = shap_vals_full[is_missing_kis, kis_score_idx].mean()
    kis_actual_shap = shap_vals_full[~is_missing_kis, kis_score_idx].mean()
    kis_missing_def = y_valid[is_missing_kis].mean() * 100
    kis_actual_def = y_valid[~is_missing_kis].mean() * 100
    
    # CRIF_CRDBD_RSNC Analysis (-1 is missing)
    is_missing_crif = (shap_sample_full['CRIF_CRDBD_RSNC'] == -1)
    crif_missing_shap = shap_vals_full[is_missing_crif, crif_rsnc_idx].mean()
    crif_actual_shap = shap_vals_full[~is_missing_crif, crif_rsnc_idx].mean()
    crif_missing_def = y_valid[is_missing_crif].mean() * 100
    crif_actual_def = y_valid[~is_missing_crif].mean() * 100
    
    with open(f"{out_dir}/missing_value_analysis.txt", 'w') as f:
        f.write("=== CG01_KIS_SCORE (Median Imputation) ===\n")
        f.write(f"Imputed Value (Median): {median_kis}\n")
        f.write(f"Missing Group - Default Rate: {kis_missing_def:.2f}%, Avg SHAP: {kis_missing_shap:.4f}, Count: {is_missing_kis.sum()}\n")
        f.write(f"Actual Group  - Default Rate: {kis_actual_def:.2f}%, Avg SHAP: {kis_actual_shap:.4f}, Count: {(~is_missing_kis).sum()}\n\n")
        
        f.write("=== CRIF_CRDBD_RSNC (-1 Imputation) ===\n")
        f.write(f"Missing Group - Default Rate: {crif_missing_def:.2f}%, Avg SHAP: {crif_missing_shap:.4f}, Count: {is_missing_crif.sum()}\n")
        f.write(f"Actual Group  - Default Rate: {crif_actual_def:.2f}%, Avg SHAP: {crif_actual_shap:.4f}, Count: {(~is_missing_crif).sum()}\n")

    # 4. Time-Series CV
    logging.info("4. Time-Series Cross Validation")
    # We will do a simple rolling window:
    # Q1: Train <= 202303, Valid 202304~202306
    # Q2: Train <= 202306, Valid 202307~202309
    # Q3: Train <= 202309, Valid 202310~202312
    
    cv_splits = [
        ('202303', '202304', '202306'),
        ('202306', '202307', '202309'),
        ('202309', '202310', '202312')
    ]
    
    cv_results = []
    
    for train_end, valid_start, valid_end in cv_splits:
        logging.info(f"CV Fold: Train <= {train_end}, Valid {valid_start} ~ {valid_end}")
        cv_train = df[df['BASE_YM'] <= train_end].copy()
        cv_valid = df[(df['BASE_YM'] >= valid_start) & (df['BASE_YM'] <= valid_end)].copy()
        
        cv_X_train = cv_train[features].copy()
        cv_y_train = cv_train['IS_BUDO_12M'].copy()
        cv_X_valid = cv_valid[features].copy()
        cv_y_valid = cv_valid['IS_BUDO_12M'].copy()
        
        for c in cat_cols:
            if c in cv_X_train.columns:
                cv_X_train[c] = cv_X_train[c].astype('category')
                cv_X_valid[c] = cv_X_valid[c].astype('category')
                
        lgb_train = lgb.Dataset(cv_X_train, cv_y_train, categorical_feature=cat_cols, free_raw_data=False)
        lgb_valid = lgb.Dataset(cv_X_valid, cv_y_valid, reference=lgb_train, categorical_feature=cat_cols, free_raw_data=False)
        
        params = {
            'objective': 'binary',
            'metric': 'auc',
            'boosting_type': 'gbdt',
            'learning_rate': 0.1, # slightly higher for faster CV
            'num_leaves': 31,     # simpler model for fast CV
            'seed': 42,
            'verbose': -1,
            'n_jobs': -1
        }
        
        cv_model = lgb.train(
            params,
            lgb_train,
            num_boost_round=100, # fast CV
            valid_sets=[lgb_train, lgb_valid],
            callbacks=[lgb.early_stopping(10), lgb.log_evaluation(0)]
        )
        
        cv_preds = cv_model.predict(cv_X_valid)
        cv_auc = roc_auc_score(cv_y_valid, cv_preds)
        cv_results.append((f"{valid_start}~{valid_end}", cv_auc))
        logging.info(f"Fold AUC: {cv_auc:.4f}")
        
    with open(f"{out_dir}/time_series_cv.txt", 'w') as f:
        for fold, auc in cv_results:
            f.write(f"Valid Period: {fold} | ROC AUC: {auc:.4f}\n")

def fbeta_score_custom(precisions, recalls, beta=2):
    return (1 + beta**2) * (precisions * recalls) / ((beta**2 * precisions) + recalls + 1e-10)

if __name__ == '__main__':
    main()
