#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
================================================================================
  [리스크 검증역] 모델 피처 다중공선성(VIF) 분석 스크립트
  Variance Inflation Factor (VIF) Analysis Pipeline
================================================================================
"""

import os
import sys
import pickle
import shutil
import logging
import numpy as np
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
log = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_DIR = os.path.join(BASE_DIR, "input")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
EVAL_DIR = os.path.join(BASE_DIR, "final_model_evaluation")


def main():
    log.info("=" * 80)
    log.info("  [리스크 검증역] 모델 피처 다중공선성(VIF) 정밀 분석")
    log.info("=" * 80)

    # 1. 모델 피처명 및 중앙값 로드
    model_pkl_path = os.path.join(OUTPUT_DIR, "integrated_scoring_model.pkl")
    if not os.path.exists(model_pkl_path):
        model_pkl_path = os.path.join(EVAL_DIR, "integrated_scoring_model.pkl")
        
    log.info(f"1. 학습된 통합 모델 객체 로딩... ({model_pkl_path})")
    with open(model_pkl_path, 'rb') as f:
        model_data = pickle.load(f)

    feature_names = model_data['feature_names']
    train_medians = model_data['train_medians']
    weight_feat_cols = set(model_data['weight_feat_cols'])
    log.info(f"   [완료] 총 {len(feature_names)}개 피처 확인 (재무: {len(feature_names)-len(weight_feat_cols)}개, 거시: {len(weight_feat_cols)}개)")

    # 2. 데이터 로드 및 전처리
    train_path = os.path.join(INPUT_DIR, "model_input_train.csv")
    log.info(f"2. 학습 데이터셋 로딩 중... ({train_path})")
    df_train = pd.read_csv(train_path, low_memory=False)
    
    X = df_train[feature_names].copy()
    X = X.fillna(train_medians)
    
    # 0 분산 변수(Constant feature) 필터링
    stds = X.std()
    const_cols = stds[stds == 0].index.tolist()
    if const_cols:
        log.warning(f"   [경고] 분산이 0인 상수 변수 {len(const_cols)}개 제외: {const_cols}")
        X = X.drop(columns=const_cols)
        valid_features = [c for c in feature_names if c not in const_cols]
    else:
        valid_features = feature_names

    # 3. 고속 VIF 산출 (상관행렬의 역행렬 주대각선 원소 활용)
    log.info("3. 상관행렬 역행렬(Inverse Correlation Matrix) 기반 고속 VIF 산출 중...")
    corr_matrix = X.corr().values
    
    # 수치적 안정성을 위해 pseudo-inverse (pinv) 활용
    inv_corr = np.linalg.pinv(corr_matrix)
    vif_values = np.diag(inv_corr)

    # DataFrame 구성
    df_vif = pd.DataFrame({
        'Feature': valid_features,
        'VIF': np.round(vif_values, 4),
        'Category': ['Macro Overlay' if c in weight_feat_cols else 'Borrower Financial' for c in valid_features]
    })
    
    # VIF 값 기준으로 내림차순 정렬
    df_vif = df_vif.sort_values(by='VIF', ascending=False).reset_index(drop=True)

    # 4. 결과 요약 분석
    log.info("\n--------------------------------------------------------------------------------")
    log.info("  [VIF 분석 요약 통계]")
    log.info("--------------------------------------------------------------------------------")
    vif_series = df_vif['VIF']
    high_vif_10 = (vif_series > 10.0).sum()
    high_vif_5 = (vif_series > 5.0).sum()
    
    log.info(f" - 전체 피처 수: {len(df_vif)}개")
    log.info(f" - 평균 VIF: {vif_series.mean():.2f} | 중앙값 VIF: {vif_series.median():.2f}")
    log.info(f" - 최대 VIF: {vif_series.max():.2f} ({df_vif.iloc[0]['Feature']})")
    log.info(f" - VIF > 10 (강한 다중공선성 위험): {high_vif_10}개 피처 ({high_vif_10/len(df_vif)*100:.1f}%)")
    log.info(f" - VIF > 5 (주의 수준): {high_vif_5}개 피처 ({high_vif_5/len(df_vif)*100:.1f}%)")

    log.info("\n--------------------------------------------------------------------------------")
    log.info("  [TOP 20 최고 VIF 피처 목록]")
    log.info("--------------------------------------------------------------------------------")
    print(df_vif.head(20).to_string(index=False))

    # 카테고리별 요약
    log.info("\n--------------------------------------------------------------------------------")
    log.info("  [피처 카테고리별 VIF 평균 및 다중공선성 비교]")
    log.info("--------------------------------------------------------------------------------")
    cat_summary = df_vif.groupby('Category')['VIF'].agg(['count', 'mean', 'median', 'max', lambda x: (x > 10).sum()]).reset_index()
    cat_summary.columns = ['Category', 'Feature_Count', 'Mean_VIF', 'Median_VIF', 'Max_VIF', 'VIF_gt_10_Count']
    print(cat_summary.to_string(index=False))

    # 파일 저장
    report_path = os.path.join(EVAL_DIR, "feature_vif_report.csv")
    df_vif.to_csv(report_path, index=False, encoding='utf-8-sig')
    log.info(f"\n [저장 완료] 전체 피처 VIF 리포트 저장: {report_path}")

    output_path = os.path.join(OUTPUT_DIR, "feature_vif_report.csv")
    shutil.copy2(report_path, output_path)

    log.info("=" * 80)


if __name__ == "__main__":
    main()
