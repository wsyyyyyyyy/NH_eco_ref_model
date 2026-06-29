# Task Checklist: Walkthrough v2 (실무 방향성 및 안정성 검증)

- `[ ]` 1. 임계값(Threshold) 및 비용 기반 최적화
  - Precision-Recall 커브 시각화
  - F1-Max, F2-Max(Recall 가중) 기준 임계값 산출
  - 사용자 피드백 반영: 미탐(FN) 비용을 오탐(FP) 비용의 20배로 설정한 Cost-Optimal 임계값 산출
- `[ ]` 2. SHAP Dependence Plot (방향성 검증)
  - `BUSINESS_AGE`, `CG01_KIS_SCORE`, 환율 등 Top 10~15 연속형 변수 대상 Dependence Plot 도출
  - 변수의 증감에 따른 부도 방향성(양/음)이 비즈니스 직관과 부합하는지 검증
- `[ ]` 3. 결측치(-1, 특이값) 영향도 분리 검증
  - `CG01_KIS_SCORE`(중간값 대체), `CRIF_CRDBD_RSNC`(-1 대체) 등 결측 그룹 vs 정상 점수 그룹 분리
  - "정보의 부재"가 모델에서 리스크로 작용하는지, 실제 값이 변별력을 가지는지 분리 분석
- `[ ]` 4. 시간 기반 교차 검증 (Time-Series CV)
  - 2023년 데이터를 분기/반기 단위로 나눈 Rolling Window Cross-Validation 구현
  - 시간 흐름에 따른 모델 AUC 안정성 체크
- `[ ]` 5. Walkthrough v2 업데이트
  - 도출된 인사이트 정리 및 시각화 결과물 캡처
