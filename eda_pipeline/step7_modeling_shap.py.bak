import pandas as pd
import numpy as np
import lightgbm as lgb
from sklearn.metrics import roc_auc_score, f1_score, classification_report
import shap
import matplotlib.pyplot as plt
import logging
import os

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

def main():
    input_path = 'eda_pipeline/output/nh_panel_macro_12m.csv'
    model_path = 'eda_pipeline/output/lgbm_12m_model.txt'
    shap_path = 'C:/Users/User/.gemini/antigravity/brain/617e8e08-d8ba-41a7-9ac5-95cca35aa6fe/shap_summary.png'
    
    logging.info(f"데이터 로딩 중: {input_path}")
    df = pd.read_csv(input_path)
    
    # 1. Train / Valid Split
    # TRAIN: 202312 이전, VALID: 202401 이후
    df['BASE_YM'] = df['BASE_YM'].astype(str)
    train_df = df[df['BASE_YM'] <= '202312']
    valid_df = df[df['BASE_YM'] >= '202401']
    
    logging.info(f"Train Shape: {train_df.shape}, Valid Shape: {valid_df.shape}")
    
    # 2. 피처 및 타겟 분리
    ignore_cols = ['V_BZNO', 'BASE_YM', 'SPLIT', 'IS_BUDO_12M']
    features = [c for c in df.columns if c not in ignore_cols]
    
    X_train = train_df[features].copy()
    y_train = train_df['IS_BUDO_12M']
    X_valid = valid_df[features].copy()
    y_valid = valid_df['IS_BUDO_12M']
    
    # 카테고리 컬럼 처리
    cat_cols = X_train.select_dtypes(include=['object', 'string']).columns
    for c in cat_cols:
        X_train[c] = X_train[c].astype('category')
        X_valid[c] = X_valid[c].astype('category')
    
    # 3. LightGBM 모델 학습 (불균형 데이터 처리 위해 class_weight='balanced' 적용)
    logging.info("LightGBM 모델 학습 시작...")
    model = lgb.LGBMClassifier(
        n_estimators=300,
        learning_rate=0.05,
        max_depth=8,
        random_state=42,
        class_weight='balanced',
        n_jobs=-1
    )
    
    model.fit(
        X_train, y_train,
        eval_set=[(X_valid, y_valid)],
        callbacks=[lgb.early_stopping(50), lgb.log_evaluation(50)]
    )
    
    # 4. 성능 평가
    logging.info("Valid 데이터로 성능 평가 중...")
    y_pred = model.predict(X_valid)
    y_proba = model.predict_proba(X_valid)[:, 1]
    
    auc = roc_auc_score(y_valid, y_proba)
    f1 = f1_score(y_valid, y_pred)
    
    logging.info(f"=== 평가 지표 (Valid) ===")
    logging.info(f"ROC AUC: {auc:.4f}")
    logging.info(f"F1 Score: {f1:.4f}")
    logging.info(f"\\n{classification_report(y_valid, y_pred)}")
    
    # 모델 저장
    model.booster_.save_model(model_path)
    logging.info(f"모델 저장 완료: {model_path}")
    
    # 5. SHAP 분석
    logging.info("SHAP 값 계산 중... (상위 20개 핵심 변수 도출)")
    
    # 너무 오래 걸릴 수 있으므로 Valid 셋에서 5만 건 샘플링하여 계산
    sample_size = min(50000, len(X_valid))
    X_shap = X_valid.sample(sample_size, random_state=42)
    
    explainer = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(X_shap)
    
    # LightGBM은 이진 분류일 때 리스트 형태로 반환할 수 있으므로 1(부도) 클래스 추출
    if isinstance(shap_values, list):
        shap_values = shap_values[1]
        
    # 한글 폰트 설정
    plt.rcParams['font.family'] = 'Malgun Gothic'
    plt.rcParams['axes.unicode_minus'] = False
    
    plt.figure(figsize=(10, 8))
    shap.summary_plot(shap_values, X_shap, max_display=20, show=False)
    plt.title('부도 예측 모형 (N=12M) 핵심 변수 SHAP 중요도', fontsize=15)
    plt.tight_layout()
    plt.savefig(shap_path, dpi=150)
    logging.info(f"SHAP 중요도 그래프 저장 완료: {shap_path}")

if __name__ == '__main__':
    main()
