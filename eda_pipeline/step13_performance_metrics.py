import pandas as pd
import numpy as np
import lightgbm as lgb
from sklearn.metrics import roc_auc_score
from scipy.stats import ks_2samp
import os
import warnings
warnings.filterwarnings('ignore')

def calculate_psi(expected, actual, bins=10):
    """
    Calculate the Population Stability Index (PSI) between two arrays of probabilities.
    expected: array-like (Train probabilities)
    actual: array-like (Valid probabilities)
    bins: int, number of deciles
    """
    # Create bin edges based on the expected distribution (Train)
    expected_pct = np.empty(bins)
    actual_pct = np.empty(bins)
    
    bin_edges = np.quantile(expected, np.linspace(0, 1, bins + 1))
    # Small adjustment to ensure the max value is included in the last bin
    bin_edges[0] = -np.inf
    bin_edges[-1] = np.inf
    
    for i in range(bins):
        # Expected
        exp_count = np.sum((expected >= bin_edges[i]) & (expected < bin_edges[i+1]))
        expected_pct[i] = exp_count / len(expected)
        
        # Actual
        act_count = np.sum((actual >= bin_edges[i]) & (actual < bin_edges[i+1]))
        actual_pct[i] = act_count / len(actual)
        
    # Add a small epsilon to avoid division by zero or log(0)
    eps = 1e-4
    expected_pct = np.maximum(expected_pct, eps)
    actual_pct = np.maximum(actual_pct, eps)
    
    psi_bins = (actual_pct - expected_pct) * np.log(actual_pct / expected_pct)
    total_psi = np.sum(psi_bins)
    
    return total_psi, psi_bins

def calculate_ks(y_true, y_prob):
    """
    Calculate K-S Statistic
    """
    # Separate probabilities for bad (1) and good (0)
    prob_bad = y_prob[y_true == 1]
    prob_good = y_prob[y_true == 0]
    
    ks_stat, p_value = ks_2samp(prob_good, prob_bad)
    return ks_stat

def main():
    print("=== [STEP 13] Performance Metrics Calculation ===")
    
    out_file = 'eda_pipeline/output/step13_performance_metrics.txt'
    
    # 1. Load Data & Model
    print("Loading data and model...")
    df = pd.read_csv('eda_pipeline/output/nh_panel_macro_12m.csv')
    df['BASE_YM'] = df['BASE_YM'].astype(str)
    
    train_df = df[df['SPLIT'] == 'TRAIN'].copy()
    valid_df = df[df['SPLIT'] == 'VALID'].copy()
    
    ignore_cols = ['V_BZNO', 'BASE_YM', 'SPLIT', 'IS_BUDO_12M']
    features_full = [c for c in df.columns if c not in ignore_cols]
    
    # 누수 포함 모델은 Group E 정리에서 _archive/legacy_model/ 로 이동했다.
    # 이 스크립트는 구세대(nh_panel_macro_12m.csv 의존)이며 D8 연동 시 재작성 대상이다 (07 문서 §6).
    from eda_pipeline import config as _cfg
    model_full = lgb.Booster(model_file=str(_cfg.MODEL_PATH_LEGACY_FULL))
    
    # Preprocess categorical features
    cat_cols_full = [c for c in df.select_dtypes(include=['object', 'string']).columns if c in features_full]
    
    X_train = train_df[features_full].copy()
    y_train = train_df['IS_BUDO_12M'].copy()
    
    X_valid = valid_df[features_full].copy()
    y_valid = valid_df['IS_BUDO_12M'].copy()
    
    for c in cat_cols_full:
        if c in X_train.columns:
            X_train[c] = X_train[c].astype('category')
            X_valid[c] = X_valid[c].astype('category')
            
    # 2. Predict Probabilities
    print("Generating predictions...")
    prob_train = model_full.predict(X_train)
    prob_valid = model_full.predict(X_valid)
    
    # 3. Calculate Metrics
    print("Calculating ROC-AUC and Gini...")
    # ROC-AUC
    auc_train = roc_auc_score(y_train, prob_train)
    auc_valid = roc_auc_score(y_valid, prob_valid)
    
    # Gini Index
    gini_train = (2 * auc_train) - 1
    gini_valid = (2 * auc_valid) - 1
    
    print("Calculating K-S Statistics...")
    # K-S Statistic
    ks_train = calculate_ks(y_train, prob_train)
    ks_valid = calculate_ks(y_valid, prob_valid)
    
    print("Calculating PSI...")
    # PSI
    psi_total, _ = calculate_psi(prob_train, prob_valid, bins=10)
    
    # 4. Save and Print Results
    result_text = "=== STEP 13: Core Performance Metrics ===\n\n"
    
    result_text += "[1] ROC-AUC Score\n"
    result_text += f" - Train AUC : {auc_train:.4f}\n"
    result_text += f" - Valid AUC : {auc_valid:.4f}\n"
    result_text += f" - Degradation : {auc_train - auc_valid:.4f}\n\n"
    
    result_text += "[2] Gini Index\n"
    result_text += f" - Train Gini: {gini_train:.4f} ({gini_train*100:.1f})\n"
    result_text += f" - Valid Gini: {gini_valid:.4f} ({gini_valid*100:.1f})\n\n"
    
    result_text += "[3] Kolmogorov-Smirnov (K-S) Statistic\n"
    result_text += f" - Train K-S : {ks_train:.4f} ({ks_train*100:.1f})\n"
    result_text += f" - Valid K-S : {ks_valid:.4f} ({ks_valid*100:.1f})\n"
    result_text += "   * Interpretation: > 0.4 (40) indicates excellent separation.\n\n"
    
    result_text += "[4] Population Stability Index (PSI)\n"
    result_text += f" - Total PSI : {psi_total:.4f}\n"
    result_text += "   * Interpretation: < 0.1 (Very Stable), 0.1~0.25 (Monitor), > 0.25 (Unstable, Needs Retraining)\n"
    
    print("\n" + result_text)
    
    with open(out_file, 'w', encoding='utf-8') as f:
        f.write(result_text)
        
    print(f"Results saved to: {out_file}")

if __name__ == '__main__':
    main()
