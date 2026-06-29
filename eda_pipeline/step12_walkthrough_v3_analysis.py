import pandas as pd
import numpy as np
import lightgbm as lgb
from sklearn.metrics import roc_auc_score, precision_recall_curve
import json
import warnings
warnings.filterwarnings('ignore')

def calculate_f_beta(precision, recall, beta):
    # Add epsilon to prevent division by zero
    num = (1 + beta**2) * (precision * recall)
    den = ((beta**2 * precision) + recall)
    # Using np.divide with where parameter to safely divide
    return np.divide(num, den, out=np.zeros_like(num), where=den!=0)

def main():
    out_file = 'C:/Users/User/.gemini/antigravity/brain/617e8e08-d8ba-41a7-9ac5-95cca35aa6fe/walkthrough_v3_research.txt'
    with open(out_file, 'w', encoding='utf-8') as f:
        f.write("=== Walkthrough V3 Research Results ===\n\n")

        # 1. Load Data
        f.write("[1] Loading Data & Models...\n")
        df = pd.read_csv('eda_pipeline/output/nh_panel_macro_12m.csv')
        df['BASE_YM'] = df['BASE_YM'].astype(str)
        
        valid_df = df[df['SPLIT'] == 'VALID'].copy()
        train_df = df[df['SPLIT'] == 'TRAIN'].copy()
        
        ignore_cols = ['V_BZNO', 'BASE_YM', 'SPLIT', 'IS_BUDO_12M']
        features_full = [c for c in df.columns if c not in ignore_cols]
        
        model_full = lgb.Booster(model_file='eda_pipeline/output/lgbm_12m_model.txt')
        model_lean = lgb.Booster(model_file='eda_pipeline/output/lgbm_12m_lean_model.txt')
        features_lean = model_lean.feature_name()
        
        X_valid_full = valid_df[features_full].copy()
        y_valid = valid_df['IS_BUDO_12M'].copy()
        
        # Categoricals for model_full
        cat_cols_full = [c for c in df.select_dtypes(include=['object', 'string']).columns if c in features_full]
        for c in cat_cols_full:
            if c in X_valid_full.columns:
                X_valid_full[c] = X_valid_full[c].astype('category')
                
        # Categoricals for model_lean
        X_valid_lean = valid_df[features_lean].copy()
        cat_cols_lean = [c for c in df.select_dtypes(include=['object', 'string']).columns if c in features_full]
        cat_cols_lean.append('STD_INDS_CFC')
        for c in cat_cols_lean:
            if c in X_valid_lean.columns:
                X_valid_lean[c] = X_valid_lean[c].astype('category')

        valid_df['PROB_FULL'] = model_full.predict(X_valid_full)
        valid_df['PROB_LEAN'] = model_lean.predict(X_valid_lean)
        
        # 1. Z-Score Table on VALID
        f.write("\n[2] Z-Score Table on Valid Set Only (Out-of-Sample)\n")
        eps = 1e-15
        valid_df['LOG_ODDS'] = np.log(valid_df['PROB_FULL'] / (1 - valid_df['PROB_FULL'] + eps))
        mu, std = valid_df['LOG_ODDS'].mean(), valid_df['LOG_ODDS'].std()
        valid_df['Z_SCORE'] = (valid_df['LOG_ODDS'] - mu) / std
        
        def map_grade(z):
            if z <= -1: return 'G1 (Safe)'
            elif z <= 0: return 'G2'
            elif z <= 1: return 'G3'
            elif z <= 2: return 'G4'
            else: return 'G5 (Risk)'
        valid_df['Z_GRADE'] = valid_df['Z_SCORE'].apply(map_grade)
        
        z_stats = valid_df.groupby('Z_GRADE').agg(
            Count=('IS_BUDO_12M', 'count'),
            Budo_Count=('IS_BUDO_12M', 'sum'),
            Budo_Rate=('IS_BUDO_12M', 'mean')
        )
        z_stats['Budo_Rate'] = z_stats['Budo_Rate'] * 100
        f.write(z_stats.to_string() + "\n")
        f.write(f"Total Valid Count: {len(valid_df):,}, Total Budo: {valid_df['IS_BUDO_12M'].sum():,}\n")
        
        # 2. & 3. Sensitivity Analysis (Cost 10x, 20x, 50x) and F2
        f.write("\n[3] Threshold Sensitivity (10x, 20x, 50x) & F2 Score\n")
        precisions, recalls, thresholds = precision_recall_curve(y_valid, valid_df['PROB_FULL'])
        
        # Remove last element because precision/recall length is len(thresholds)+1
        precisions = precisions[:-1]
        recalls = recalls[:-1]
        
        f1_scores = calculate_f_beta(precisions, recalls, 1)
        f2_scores = calculate_f_beta(precisions, recalls, 2)
        
        best_f1_idx = np.argmax(f1_scores)
        best_f2_idx = np.argmax(f2_scores)
        
        f.write(f"Best F1 : Threshold={thresholds[best_f1_idx]:.4f}, F1={f1_scores[best_f1_idx]:.4f}, Prec={precisions[best_f1_idx]:.4f}, Rec={recalls[best_f1_idx]:.4f}\n")
        f.write(f"Best F2 : Threshold={thresholds[best_f2_idx]:.4f}, F2={f2_scores[best_f2_idx]:.4f}, Prec={precisions[best_f2_idx]:.4f}, Rec={recalls[best_f2_idx]:.4f}\n")
        
        P = y_valid.sum()
        N = len(y_valid) - P
        
        for cost_multiplier in [10, 20, 50]:
            TP = recalls * P
            FN = P - TP
            # Calculate FP safely
            FP = np.zeros_like(TP)
            valid_p = precisions > 0
            FP[valid_p] = (TP[valid_p] / precisions[valid_p]) - TP[valid_p]
            FP[~valid_p] = N
            
            costs = (FN * cost_multiplier) + (FP * 1)
            best_cost_idx = np.argmin(costs)
            
            best_t = thresholds[best_cost_idx]
            best_p = precisions[best_cost_idx]
            best_r = recalls[best_cost_idx]
            
            f.write(f"Cost Multiplier {cost_multiplier}x: Optimal Threshold={best_t:.4f}, Prec={best_p:.4f}, Rec={best_r:.4f}\n")
            
        # 4. Industry Impact (Train without STD_INDS_CFC)
        f.write("\n[4] Industry Impact (Model without STD_INDS_CFC)\n")
        X_train_full = train_df[features_full].copy()
        y_train = train_df['IS_BUDO_12M'].copy()
        
        features_no_ind = [c for c in features_full if c != 'STD_INDS_CFC']
        X_train_no_ind = train_df[features_no_ind].copy()
        X_valid_no_ind = valid_df[features_no_ind].copy()
        
        for c in cat_cols_full:
            if c in X_train_no_ind.columns:
                X_train_no_ind[c] = X_train_no_ind[c].astype('category')
                X_valid_no_ind[c] = X_valid_no_ind[c].astype('category')
                
        lgb_train = lgb.Dataset(X_train_no_ind, y_train)
        params = {
            'objective': 'binary', 'metric': 'auc', 'boosting_type': 'gbdt',
            'learning_rate': 0.05, 'num_leaves': 63, 'max_depth': 8,
            'verbose': -1, 'random_state': 42, 'n_jobs': -1
        }
        model_no_ind = lgb.train(params, lgb_train, num_boost_round=150)
        
        prob_no_ind = model_no_ind.predict(X_valid_no_ind)
        auc_no_ind = roc_auc_score(y_valid, prob_no_ind)
        auc_full = roc_auc_score(y_valid, valid_df['PROB_FULL'])
        
        f.write(f"AUC (Full Model, with Industry): {auc_full:.4f}\n")
        f.write(f"AUC (Model without Industry): {auc_no_ind:.4f}\n")
        f.write(f"Difference: {auc_full - auc_no_ind:.4f}\n")
        
        # 5. Lean vs Full at fixed Recall 82.6%
        f.write("\n[5] Lean vs Full Model Comparison (Fixed Recall = 82.6%)\n")
        target_recall = 0.826
        
        def get_precision_at_recall(probs, y, target_r):
            p, r, t = precision_recall_curve(y, probs)
            p = p[:-1]
            r = r[:-1]
            t = t
            idx = np.argmin(np.abs(r - target_r))
            return p[idx], r[idx], t[idx]
            
        p_full, r_full, t_full = get_precision_at_recall(valid_df['PROB_FULL'], y_valid, target_recall)
        p_lean, r_lean, t_lean = get_precision_at_recall(valid_df['PROB_LEAN'], y_valid, target_recall)
        
        f.write(f"Full Model: Precision={p_full:.4f} at Recall={r_full:.4f} (Threshold={t_full:.4f})\n")
        f.write(f"Lean Model: Precision={p_lean:.4f} at Recall={r_lean:.4f} (Threshold={t_lean:.4f})\n")
        
        TP_full = r_full * P
        FP_full = (TP_full / p_full) - TP_full
        
        TP_lean = r_lean * P
        FP_lean = (TP_lean / p_lean) - TP_lean
        
        f.write(f"False Positives Full: {FP_full:.0f}\n")
        f.write(f"False Positives Lean: {FP_lean:.0f}\n")
        f.write(f"Difference in FP (cost of using Lean): {FP_lean - FP_full:.0f} more false alarms\n")

if __name__ == '__main__':
    main()
