# Task Checklist: VIF 다이어트 및 Z-Score 모델 평가

- `[x]` 1. VIF 다이어트 로직 구현
  - 기존 모델의 SHAP 기준 상위 100개 변수 추출
  - 연속형 수치 변수 필터링 및 다중공선성(VIF) 검사
  - VIF > 10 이상인 중복성 변수를 제거하되, SHAP 중요도가 높은 변수를 우선 보존하는 로직 적용
- `[x]` 2. Lean Model(경량화 모델) 재학습 및 평가
  - VIF 다이어트를 거친 핵심 변수(수치형 + 범주형/거시지표)만으로 LightGBM 모델 재학습
  - 기존 모델(ROC AUC 0.9011)과 비교하여 성능 저하 최소화 여부 검증
  - 경량화 모델에 대한 SHAP 차트 다시 생성
- `[x]` 3. Z-Score 관점 평가 및 임계값 튜닝
  - 모델의 예측 확률(Probability)을 Z-Score 및 분위수로 변환하여 1~10등급의 리스크 등급 생성
  - 각 등급별 실제 부도율(Default Rate) 확인
  - Precision/Recall Trade-off 분석을 통한 최적 임계값(Threshold) 제안
- `[x]` 4. Walkthrough 업데이트
  - 결과 정리 및 사용자를 위한 시각화(Z-Score 부도율 등) 추가
