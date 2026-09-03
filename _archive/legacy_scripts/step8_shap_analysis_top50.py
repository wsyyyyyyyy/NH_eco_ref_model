import pandas as pd
import numpy as np
import lightgbm as lgb
import shap
import matplotlib.pyplot as plt
import logging
import os

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

def load_industry_mapping():
    excel_path = 'eda_pipeline/업종코드-표준산업분류 연계표_홈택스 게시.xlsx'
    try:
        df_ind = pd.read_excel(excel_path, skiprows=3)
        # Unnamed: 13 is KSIC 5-digit code, Unnamed: 11 is Homtax detailed name, Unnamed: 21 is KSIC 4-digit name, Unnamed: 22 is KSIC 4-digit detail name
        mapping = {}
        for _, row in df_ind.iterrows():
            code = str(row['Unnamed: 13']).replace('.0', '')
            if code and code != 'nan':
                # Use KSIC 4-digit detail name + HomeTax detail name for better description
                name = str(row['Unnamed: 22']) + " (" + str(row['Unnamed: 11']) + ")"
                if code not in mapping:
                    mapping[code] = name
        return mapping
    except Exception as e:
        logging.error(f"Error reading industry mapping: {e}")
        return {}

def main():
    input_path = 'eda_pipeline/output/nh_panel_macro_12m.csv'
    model_path = 'eda_pipeline/output/lgbm_12m_model.txt'
    shap_path = 'C:/Users/User/.gemini/antigravity/brain/617e8e08-d8ba-41a7-9ac5-95cca35aa6fe/shap_summary_top50.png'
    
    logging.info("데이터 로딩 중...")
    df = pd.read_csv(input_path)
    
    df['BASE_YM'] = df['BASE_YM'].astype(str)
    valid_df = df[df['BASE_YM'] >= '202401']
    
    ignore_cols = ['V_BZNO', 'BASE_YM', 'SPLIT', 'IS_BUDO_12M']
    features = [c for c in df.columns if c not in ignore_cols]
    
    X_valid = valid_df[features].copy()
    
    cat_cols = X_valid.select_dtypes(include=['object', 'string']).columns
    for c in cat_cols:
        X_valid[c] = X_valid[c].astype('category')
        
    logging.info("모델 로딩 중...")
    model = lgb.Booster(model_file=model_path)
    
    logging.info("SHAP 값 계산 중...")
    sample_size = min(50000, len(X_valid))
    X_shap = X_valid.sample(sample_size, random_state=42)
    
    explainer = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(X_shap)
    if isinstance(shap_values, list):
        shap_values = shap_values[1]
        
    plt.rcParams['font.family'] = 'Malgun Gothic'
    plt.rcParams['axes.unicode_minus'] = False
    
    plt.figure(figsize=(12, 14))
    shap.summary_plot(shap_values, X_shap, max_display=50, show=False)
    plt.title('부도 예측 모형 (N=12M) 핵심 변수 SHAP 중요도 (Top 50)', fontsize=15)
    plt.tight_layout()
    plt.savefig(shap_path, dpi=150)
    logging.info(f"Top 50 SHAP summary plot 저장 완료: {shap_path}")
    
    # Calculate feature importances
    mean_abs_shap = np.abs(shap_values).mean(axis=0)
    shap_importance = pd.DataFrame({
        'Feature': features,
        'Mean_Abs_SHAP': mean_abs_shap
    }).sort_values('Mean_Abs_SHAP', ascending=False)
    
    print("\n=== 상위 50개 변수 중요도 ===")
    for idx, row in shap_importance.head(50).iterrows():
        print(f"{row['Feature']}: {row['Mean_Abs_SHAP']:.4f}")
        
    # In-depth analysis on STD_INDS_CFC if it exists
    if 'STD_INDS_CFC' in features:
        logging.info("\n업종코드(STD_INDS_CFC) 심층 분석 중...")
        ind_idx = features.index('STD_INDS_CFC')
        ind_shap = shap_values[:, ind_idx]
        ind_values = X_shap['STD_INDS_CFC'].values
        
        ind_df = pd.DataFrame({
            'STD_INDS_CFC': ind_values,
            'SHAP': ind_shap
        })
        
        # Group by industry
        ind_summary = ind_df.groupby('STD_INDS_CFC').agg(
            Mean_SHAP=('SHAP', 'mean'),
            Count=('SHAP', 'count')
        ).reset_index()
        
        # Filter out very small industries for robust analysis
        ind_summary = ind_summary[ind_summary['Count'] >= 50]
        ind_summary = ind_summary.sort_values('Mean_SHAP', ascending=False)
        
        ind_mapping = load_industry_mapping()
        
        def map_code(code):
            c_str = str(code).replace('.0', '')
            return ind_mapping.get(c_str, "알 수 없음")
            
        ind_summary['Korean_Name'] = ind_summary['STD_INDS_CFC'].apply(map_code)
        
        print("\n=== 부도 확률 증가(Risky) 상위 10개 업종 ===")
        print(ind_summary.head(10).to_string(index=False))
        
        print("\n=== 부도 확률 감소(Safe) 상위 10개 업종 ===")
        print(ind_summary.tail(10).sort_values('Mean_SHAP').to_string(index=False))
        
        # Save analysis to markdown
        with open('C:/Users/User/.gemini/antigravity/brain/617e8e08-d8ba-41a7-9ac5-95cca35aa6fe/industry_analysis.md', 'w', encoding='utf-8') as f:
            f.write("# 업종별 부도 위험도 (SHAP 기준)\n\n")
            f.write("양수(+)는 부도 위험 증가, 음수(-)는 부도 위험 감소를 의미합니다.\n\n")
            f.write("## ⚠️ 부도 위험이 가장 높은 상위 10개 업종\n")
            f.write(ind_summary.head(10).to_markdown(index=False))
            f.write("\n\n## 🛡️ 부도 위험이 가장 낮은 상위 10개 업종\n")
            f.write(ind_summary.tail(10).sort_values('Mean_SHAP').to_markdown(index=False))
        logging.info("Industry analysis saved.")

if __name__ == '__main__':
    main()
