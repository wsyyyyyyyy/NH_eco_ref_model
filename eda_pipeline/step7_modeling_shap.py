import pandas as pd
import numpy as np
import lightgbm as lgb
from sklearn.metrics import roc_auc_score, f1_score, classification_report
import shap
import matplotlib.pyplot as plt
import logging
import os
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from eda_pipeline import config
from eda_pipeline.leaky_cols import (LEAK_CONFIRMED, LEAK_SUSPECT, NON_FEATURE,
                                     feature_columns)
from eda_pipeline.split_spec import DEV_START, DEV_END, VALID_START

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

def main():
    # [선행 3] 하드코딩된 구 파일명 대신 config 경유로 현재 SPINE_MODE 패널을 읽는다.
    input_path = config.OUTPUT_DIR / f"nh_panel_macro_12m_{config.SPINE_MODE}_none.csv"
    # [보호] 구 모델 파일(lgbm_12m_model.txt)에는 쓰지 않는다. config 가드가 막는다.
    model_path = config.MODEL_PATH_V2_FULL
    shap_path = str(config.OUTPUT_DIR / 'shap_summary.png')

    logging.info(f"데이터 로딩 중: {input_path.name}")
    df = config.read_panel(input_path, dtype={'BASE_YM': str})

    # 1. Train / Dev / Valid Split
    #    [선행 6] early stopping 은 Dev 로만 한다.
    #    기존 코드는 eval_set 에 Valid 를 넣고 그 Valid AUC 를 최종 지표로 보고했다.
    #    최종 성능이 낙관적으로 편향되고, Ablation 시나리오 간 비교도 무효가 된다.
    df['BASE_YM'] = df['BASE_YM'].astype(str)
    train_df = df[df['BASE_YM'] < str(DEV_START)]
    dev_df = df[(df['BASE_YM'] >= str(DEV_START)) & (df['BASE_YM'] <= str(DEV_END))]
    valid_df = df[df['BASE_YM'] >= str(VALID_START)]

    logging.info(f"Train {train_df.shape} / Dev {dev_df.shape} / Valid {valid_df.shape}")

    # 2. 피처 및 타겟 분리
    #    [선행 5] 누수/비피처 제외는 leaky_cols.feature_columns 한 곳에서 관리한다.
    features = feature_columns(df, target='IS_BUDO_12M', include_suspect=False)
    leaked = [c for c in features if c in set(LEAK_CONFIRMED)]
    assert not leaked, f"LEAK_CONFIRMED 가 피처에 남아 있다: {leaked}"
    logging.info(f'피처 {len(features)}개 '
                 f'(LEAK_CONFIRMED {len(LEAK_CONFIRMED)} + LEAK_SUSPECT {len(LEAK_SUSPECT)} '
                 f'+ NON_FEATURE {len(NON_FEATURE)} 제외)')

    X_train, y_train = train_df[features].copy(), train_df['IS_BUDO_12M']
    X_dev, y_dev = dev_df[features].copy(), dev_df['IS_BUDO_12M']
    X_valid, y_valid = valid_df[features].copy(), valid_df['IS_BUDO_12M']

    cat_cols = X_train.select_dtypes(include=['object', 'string']).columns
    for c in cat_cols:
        for X in (X_train, X_dev, X_valid):
            X[c] = X[c].astype('category')

    # 3. LightGBM 학습
    #    [선행 확인 3] scale_pos_weight 는 고정값을 쓰지 않고 Train 의 실제 클래스
    #    비율로 매번 계산한다. 행 중복 제거로 양성 수가 바뀌었으므로 고정값이면 틀린다.
    n_pos = int(y_train.sum())
    n_neg = int(len(y_train) - n_pos)
    spw = n_neg / max(n_pos, 1)
    logging.info(f"scale_pos_weight = {n_neg:,}/{n_pos:,} = {spw:.2f} (Train 실측)")

    # metric='auc' 를 반드시 명시한다. 생략하면 binary_logloss 가 함께 평가되고,
    # early_stopping(first_metric_only=False) 이 그 지표로 멈춘다. scale_pos_weight 로
    # 가중된 목적함수는 가중 없는 Dev logloss 를 1회차부터 악화시키므로
    # AUC 가 계속 오르는 중인데도 best_iteration=1 로 정지한다. STAGE 6 에서 실측 확인.
    model = lgb.LGBMClassifier(
        metric='auc',
        n_estimators=2000,
        learning_rate=0.05,
        max_depth=8,
        random_state=42,
        scale_pos_weight=spw,
        n_jobs=-1,
    )
    model.fit(
        X_train, y_train,
        eval_set=[(X_dev, y_dev)],          # Valid 는 절대 넣지 않는다
        eval_metric='auc',
        callbacks=[lgb.early_stopping(50), lgb.log_evaluation(50)]
    )
    logging.info(f"best_iteration = {model.best_iteration_}")

    # 4. 성능 평가 — Valid 는 여기서 처음이자 마지막으로 한 번만 본다
    logging.info("Valid 데이터로 성능 평가 중...")
    y_proba = model.predict_proba(X_valid)[:, 1]
    y_pred = (y_proba >= 0.5).astype(int)

    auc = roc_auc_score(y_valid, y_proba)
    f1 = f1_score(y_valid, y_pred)

    logging.info(f"=== 평가 지표 (Valid, 진짜 홀드아웃) ===")
    logging.info(f"ROC AUC: {auc:.4f}")
    logging.info(f"F1 Score: {f1:.4f}")
    logging.info(os.linesep + classification_report(y_valid, y_pred))

    # 모델 저장 — config.save_booster 가 legacy 2건 덮어쓰기를 막는다.
    saved = config.save_booster(model, model_path)
    logging.info(f"모델 저장 완료: {saved}")

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
