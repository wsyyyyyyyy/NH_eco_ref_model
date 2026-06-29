import pandas as pd
import numpy as np
import lightgbm as lgb
import matplotlib.pyplot as plt
from sklearn.metrics import roc_auc_score, precision_recall_curve

import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
import matplotlib.font_manager as fm
import os

def set_korean_font():
    font_path = 'C:/Windows/Fonts/malgun.ttf'
    if os.path.exists(font_path):
        font_name = fm.FontProperties(fname=font_path).get_name()
        plt.rc('font', family=font_name)
    plt.rc('axes', unicode_minus=False)

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
    
    # Validation 셋 사용 (24년 이후)
    valid_df = df[df['BASE_YM'] >= '202401'].copy()
    X_valid = valid_df[features].copy()
    y_valid = valid_df['IS_BUDO_12M'].copy()
    
    cat_cols = [c for c in valid_df.select_dtypes(include=['object', 'string']).columns if c in features]
    for c in cat_cols:
        X_valid[c] = X_valid[c].astype('category')
            
    logging.info("예측 확률 산출...")
    valid_df['PRED_PROB'] = model.predict(X_valid)
    
    # Z-Score 매핑
    eps = 1e-15
    valid_df['LOG_ODDS'] = np.log(valid_df['PRED_PROB'] / (1 - valid_df['PRED_PROB'] + eps))
    mu, std = valid_df['LOG_ODDS'].mean(), valid_df['LOG_ODDS'].std()
    valid_df['Z_SCORE'] = (valid_df['LOG_ODDS'] - mu) / std
    
    # Grade 매핑 (-1, 0, 1, 2)
    def map_grade(z):
        if z <= -1: return 'G1 (Safe)'
        elif z <= 0: return 'G2'
        elif z <= 1: return 'G3'
        elif z <= 2: return 'G4'
        else: return 'G5 (Risk)'
    valid_df['OUR_GRADE'] = valid_df['Z_SCORE'].apply(map_grade)
    
    logging.info("내부 등급과 비교 분석...")
    # 당행 내부 조기경보등급: OBV_ELYWRN_OBV_GRD_DSC
    # 보통 A, B, C... 로 나뉨. -1은 결측치
    
    # 1. 내부 등급 존재 건에 대해서만 분석
    has_internal = valid_df[valid_df['OBV_ELYWRN_OBV_GRD_DSC'] != '-1']
    
    # 내부 등급별 실제 부도율
    internal_stats = has_internal.groupby('OBV_ELYWRN_OBV_GRD_DSC').agg(
        Count=('IS_BUDO_12M', 'count'),
        Budo_Count=('IS_BUDO_12M', 'sum'),
        Budo_Rate=('IS_BUDO_12M', 'mean'),
        Our_Avg_Prob=('PRED_PROB', 'mean')
    )
    internal_stats['Budo_Rate'] = internal_stats['Budo_Rate'] * 100
    internal_stats['Our_Avg_Prob'] = internal_stats['Our_Avg_Prob'] * 100
    
    with open(f"{out_dir}/internal_comparison.txt", 'w') as f:
        f.write("=== 은행 내부 조기경보등급 기준 분석 ===\n")
        f.write(internal_stats.to_string())
        f.write("\n\n")
        
        f.write("=== 내부 등급 + 우리 모델(G1~G5) 교차 분석 ===\n")
        cross_tab = pd.crosstab(
            has_internal['OBV_ELYWRN_OBV_GRD_DSC'], 
            has_internal['OUR_GRADE'], 
            values=has_internal['IS_BUDO_12M'], 
            aggfunc='mean'
        ).fillna(0) * 100
        f.write("교차 부도율 (%):\n")
        f.write(cross_tab.to_string())
        f.write("\n\n")
        
        cross_count = pd.crosstab(has_internal['OBV_ELYWRN_OBV_GRD_DSC'], has_internal['OUR_GRADE'])
        f.write("건수 분포:\n")
        f.write(cross_count.to_string())
        f.write("\n")

    logging.info("분석 완료")

if __name__ == '__main__':
    main()
