import os
import numpy as np
import pandas as pd
import logging
import warnings
import statsmodels.api as sm

warnings.filterwarnings('ignore')

# Logging setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
monitor_logger = logging.getLogger("MONITOR_LOG")
monitor_logger.setLevel(logging.DEBUG)
if not monitor_logger.handlers:
    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(message)s')
    ch.setFormatter(formatter)
    monitor_logger.addHandler(ch)
    
    os.makedirs('analysis/output', exist_ok=True)
    fh = logging.FileHandler('analysis/output/monitor_weak_iv.log', mode='w', encoding='utf-8')
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(formatter)
    monitor_logger.addHandler(fh)

# Constants
INPUT_FILE = 'api_data_processing/output/model_input/model_input_daily_cleaned.csv'
OUTPUT_DIR = 'analysis/output'
WINSOR_LO = 0.02
WINSOR_HI = 0.98
IV_THRESHOLD_WEAK = 0.02
VIF_THRESHOLD = 5.0

def assign_category(feature_name):
    f_lower = feature_name.lower()
    if any(k in f_lower for k in ['kospi', 'kosdaq', 'dowjones', 'nasdaq', 'sp500', 'nikkei', 'shanghai', 'equity']):
        return 'equity'
    elif any(k in f_lower for k in ['krw', 'dxy', 'exchange', 'fx']):
        return 'fx'
    elif any(k in f_lower for k in ['call_rate', 'koribor', 'treasury_bond', 'base_rate', 'cd_rate', 'corporate_bond', 'spread']):
        return 'interest_rate'
    elif any(k in f_lower for k in ['oil', 'gas', 'gold', 'silver', 'copper', 'corn', 'soybean', 'commodity']):
        return 'commodity'
    elif any(k in f_lower for k in ['cpi', 'ppi', 'housing_price', 'export_price', 'import_price', 'price']):
        return 'price'
    elif any(k in f_lower for k in ['m1', 'm2', 'lf', 'monetary', 'money']):
        return 'money'
    elif any(k in f_lower for k in ['trade', 'export', 'import', 'account', 'goods_balance']):
        if 'price' not in f_lower:
            return 'trade'
        return 'price'
    elif any(k in f_lower for k in ['bsi', 'csi', 'unemployment', 'vix', 'sentiment']):
        return 'sentiment'
    elif any(k in f_lower for k in ['household', 'loan', 'credit']):
        return 'household'
    else:
        return 'other'

def get_base_indicator(col_name):
    suffixes = ['_log_ret_ma90d', '_vol20d_ma90d', '_yoy_ma90d', '_log_ret', '_vol20d', '_yoy']
    base = col_name
    for suffix in suffixes:
        if base.endswith(suffix):
            base = base[:-len(suffix)]
            break
    return base

def get_fine_bins(s):
    # Try qcut (10 bins)
    try:
        _, bins = pd.qcut(s, q=10, duplicates='drop', retbins=True)
        if len(bins) - 1 >= 5:
            bins[0] = s.min() - 0.001
            bins[-1] = s.max() + 0.001
            return bins.tolist()
    except:
        pass
    
    # Try cut (10 bins)
    try:
        _, bins = pd.cut(s, bins=10, retbins=True)
        if len(bins) - 1 >= 2:
            bins[0] = s.min() - 0.001
            bins[-1] = s.max() + 0.001
            return bins.tolist()
    except:
        pass
        
    # Forced cut (3 bins)
    _, bins = pd.cut(s, bins=3, retbins=True)
    bins[0] = s.min() - 0.001
    bins[-1] = s.max() + 0.001
    return bins.tolist()

def build_woe_iv_table(df_temp, feature_col, target_col):
    grouped = df_temp.groupby(feature_col, observed=False)[target_col].agg(['count', 'sum'])
    grouped.columns = ['Total', 'Bad']
    grouped['Good'] = grouped['Total'] - grouped['Bad']
    
    # Dynamic Laplace Smoothing (only when 0)
    grouped.loc[grouped['Bad'] == 0, 'Bad'] += 0.5
    grouped.loc[grouped['Good'] == 0, 'Good'] += 0.5
    
    total_bad = grouped['Bad'].sum()
    total_good = grouped['Good'].sum()
    
    grouped['%Bad'] = grouped['Bad'] / total_bad
    grouped['%Good'] = grouped['Good'] / total_good
    
    grouped['WoE'] = np.log(grouped['%Good'] / grouped['%Bad'])
    grouped['IV'] = (grouped['%Good'] - grouped['%Bad']) * grouped['WoE']
    grouped['bad_rate'] = grouped['Bad'] / (grouped['Bad'] + grouped['Good'])
    
    return grouped

def coarse_classing_monotonic(df, feature, target):
    bins = get_fine_bins(df[feature])
    
    while len(bins) - 1 > 2:
        df_temp = pd.DataFrame({
            'feature': pd.cut(df[feature], bins=bins, include_lowest=True),
            'target': df[target]
        })
        woe_table = build_woe_iv_table(df_temp, 'feature', 'target')
        
        intervals = woe_table.index.tolist()
        
        # Check monotonicity if bins <= 4
        if len(bins) - 1 <= 4:
            woes = woe_table['WoE'].values
            is_monotonic = np.all(np.diff(woes) >= 0) or np.all(np.diff(woes) <= 0)
            if is_monotonic:
                break
        
        # Merge adjacent bins with min abs WoE diff
        min_diff = float('inf')
        merge_idx = -1
        for i in range(len(intervals) - 1):
            diff = abs(woe_table.loc[intervals[i], 'WoE'] - woe_table.loc[intervals[i+1], 'WoE'])
            if diff < min_diff:
                min_diff = diff
                merge_idx = i
                
        if merge_idx != -1:
            bins.pop(merge_idx + 1)
        else:
            break
            
    # Final evaluation
    df_temp = pd.DataFrame({
        'feature': pd.cut(df[feature], bins=bins, include_lowest=True),
        'target': df[target]
    })
    woe_table = build_woe_iv_table(df_temp, 'feature', 'target')
    total_iv = woe_table['IV'].sum()
    woes = woe_table['WoE'].values
    is_monotonic = np.all(np.diff(woes) >= 0) or np.all(np.diff(woes) <= 0)
    
    return woe_table, total_iv, is_monotonic

def calculate_vif(df, col_idx):
    y = df.iloc[:, col_idx].values
    X_cols = [i for i in range(df.shape[1]) if i != col_idx]
    X = df.iloc[:, X_cols].values
    
    if X.shape[1] == 0:
        return 1.0
        
    try:
        X_with_const = sm.add_constant(X)
        model = sm.OLS(y, X_with_const)
        results = model.fit()
        r_squared = results.rsquared
        # R^2 >= 0.9999 means perfect multicollinearity
        if r_squared >= 0.9999:
            return 999.0
        
        vif = 1.0 / (1.0 - r_squared)
        if np.isinf(vif) or np.isnan(vif):
            return 999.0
        return vif
    except ZeroDivisionError:
        return 999.0
    except Exception:
        return 999.0

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    logging.info("Starting Univariate Analysis...")
    
    # 1. Load Data
    try:
        df = pd.read_csv(INPUT_FILE)
        logging.info(f"Loaded input data: {df.shape}")
    except Exception as e:
        logging.error(f"Failed to load input file: {e}")
        return

    # Identify target column
    target_col = None
    if 'BUDO' in df.columns:
        target_col = 'BUDO'
    elif 'target' in df.columns:
        target_col = 'target'
    elif 'target_y' in df.columns:
        target_col = 'target_y'
        
    if not target_col:
        logging.warning("Target column not found! Generating random dummy 'BUDO' for testing.")
        np.random.seed(42)
        df['BUDO'] = np.random.randint(0, 2, size=len(df))
        target_col = 'BUDO'
        
    features = [c for c in df.columns if c not in [target_col, 'date'] and df[c].dtype in [np.float64, np.int64]]
    
    # Step 1: Raw Data Statistics & Winsorization
    logging.info("Step 1: Winsorization & Raw Statistics")
    stats_list = []
    
    for f in features:
        s = df[f].copy()
        
        p02 = s.quantile(WINSOR_LO)
        p98 = s.quantile(WINSOR_HI)
        
        if p02 != p98:
            s = np.clip(s, p02, p98)
            df[f] = s 
            
        stats = {
            'feature': f,
            'count': s.count(),
            'missing_pct': s.isna().mean() * 100,
            'mean': s.mean(),
            'std': s.std(),
            'min': s.min(),
            'p25': s.quantile(0.25),
            'median': s.median(),
            'p75': s.quantile(0.75),
            'max': s.max(),
            'skewness': s.skew(),
            'kurtosis': s.kurtosis()
        }
        stats_list.append(stats)
        
    df_stats = pd.DataFrame(stats_list)
    df_stats.to_csv(os.path.join(OUTPUT_DIR, '01_raw_statistics.csv'), index=False)
    
    df = df.dropna(subset=[target_col] + features).reset_index(drop=True)
    
    # Step 2 & 2.5: Fine-Classing & Coarse-Classing
    logging.info("Step 2 & 2.5: WoE/IV Binning & Monotonicity Check")
    
    iv_results = []
    coarse_details = []
    weak_iv_vars = []
    
    for f in features:
        woe_table, total_iv, is_monotonic = coarse_classing_monotonic(df, f, target_col)
        
        iv_results.append({
            'feature': f,
            'IV': total_iv,
            'is_monotonic': is_monotonic
        })
        
        for idx, row in woe_table.iterrows():
            coarse_details.append({
                'feature': f,
                'interval': str(idx),
                'Total': row['Total'],
                'Bad': row['Bad'],
                'Good': row['Good'],
                'bad_rate': row['bad_rate'],
                'WoE': row['WoE'],
                'IV_component': row['IV']
            })
            
        # Weak IV Tracking Filter (0.015 <= IV < 0.020)
        if 0.015 <= total_iv < 0.020:
            weak_iv_vars.append(f)
            monitor_logger.info(f"[MONITOR_LOG] IV 0.02 미만 턱걸이 탈락 변수 추적: {f} (산출 IV: {total_iv:.4f})")
            
    df_iv = pd.DataFrame(iv_results).sort_values('IV', ascending=False)
    df_iv.to_csv(os.path.join(OUTPUT_DIR, '02_iv_ranking.csv'), index=False)
    
    df_coarse = pd.DataFrame(coarse_details)
    df_coarse.to_csv(os.path.join(OUTPUT_DIR, '03_coarse_classing.csv'), index=False)
    
    # Step 3: IV >= 0.02 Filter
    logging.info("Step 3: Filtering IV >= 0.02")
    df_filtered = df_iv[df_iv['IV'] >= IV_THRESHOLD_WEAK].copy()
    
    # Step 4: Best IV per Indicator
    logging.info("Step 4: Selecting Best IV per Base Indicator")
    df_filtered['base_indicator'] = df_filtered['feature'].apply(get_base_indicator)
    df_best = df_filtered.loc[df_filtered.groupby('base_indicator')['IV'].idxmax()]
    df_best = df_best.sort_values('IV', ascending=False)
    df_best.to_csv(os.path.join(OUTPUT_DIR, '04_best_per_indicator.csv'), index=False)
    
    # Step 4.5: Category Balancing Pool
    logging.info("Step 4.5: Category Balancing")
    df_best['category'] = df_best['base_indicator'].apply(assign_category)
    df_pool = df_best.groupby('category').head(3)
    df_pool = df_pool.sort_values('IV', ascending=False).reset_index(drop=True)
    df_pool.to_csv(os.path.join(OUTPUT_DIR, '04.5_balanced_macro_pool.csv'), index=False)
    
    # Step 5: Forward VIF Selection
    logging.info("Step 5: Forward VIF Selection")
    selected_features = []
    pool_features = df_pool['feature'].tolist()
    
    for f in pool_features:
        if not selected_features:
            selected_features.append(f)
            continue
            
        current_candidates = selected_features + [f]
        X_df = df[current_candidates]
        
        max_vif = 0.0
        for i in range(len(current_candidates)):
            vif = calculate_vif(X_df, i)
            if vif > max_vif:
                max_vif = vif
                
        if max_vif < VIF_THRESHOLD:
            selected_features.append(f)
            
    df_final = df_pool[df_pool['feature'].isin(selected_features)].reset_index(drop=True)
    df_final.to_csv(os.path.join(OUTPUT_DIR, '05_final_selected_variables.csv'), index=False)
    
    logging.info(f"Pipeline completed. Final selected variables count: {len(selected_features)}")
    logging.info(f"Final variables: {selected_features}")

if __name__ == '__main__':
    main()
