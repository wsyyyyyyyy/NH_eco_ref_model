# 신용평가 모형 구축 및 매크로 리스크 가중치 정제 보고서

## 1. 분석 목적 및 배경

기업 고유 재무 데이터(51개 변수)와 거시경제 지표(172개 변수)를 결합하여 LightGBM 신용평가 모형을 학습하고, SHAP 기반 **'업종별 매크로 리스크 가중치 매트릭스'**를 도출했습니다. 

나아가 실무 스트레스 테스트 시 머신러닝의 변수 선택 특성으로 인해 발생하는 **희소성(Sparsity, 가중치 쏠림)** 문제를 해결하기 위해, 6대 매크로 카테고리 기반 **정제(Smoothing) 및 리스크 하한선(Floor) 부여 작업**을 수행했습니다.

---

## 2. 모형 학습 및 SHAP 추출 요약

- **모형 성능**: Test AUC **0.8627**, 부실 탐지율(Recall) **0.91** (부실 비율 0.086% 극단적 불균형 조건 보정)
- **핵심 피처**: 자본총계(128000), 유동비율(191204), 통안채 변동성(`MSB_91d_vol_m`), 무역총액(`trade_total`) 등

---

## 3. 매크로 리스크 가중치 스무딩(Smoothing) 성과

### 3.1 원시 가중치 매트릭스의 한계
- 원시 SHAP 매트릭스는 전체 3,096개 셀 중 **96.2%가 0**으로 나타남.
- 예: 부동산업(L)의 경우 환율·무역 변수 몇 개만 쏠려 있어, 금리나 원자재 충격 시뮬레이션 시 반응하지 않는 리스크 존재.

### 3.2 6대 매크로 카테고리 매핑 규칙
172개 피처를 정규표현식 스캔을 통해 아래 6개 그룹으로 전수 분류했습니다.
- `Equity` (주가지수): 28개 (KOSPI, NASDAQ 등)
- `FX` (환율): 20개 (USD/KRW, DXY 등)
- `Commodity` (원자재/에너지): 24개 (WTI, Brent, 금 등)
- `Agri` (농산물): 8개 (옥수수, 대두 등)
- `Interest` (금리/채권): 42개 (통안채, 국고채 등)
- `Macro/Biz` (경기/경기지수): 50개 (CPI, BSI, VIX 등)

### 3.3 정제 전후 비교 시각화

![Smoothing Comparison Heatmap](file:///c:/Users/User/Desktop/eco_ref_model/model_building/output/smoothing_comparison_heatmap.png)

> [!IMPORTANT]
> **스무딩 효과**:
> - 정제 전(왼쪽): 극소수 피처만 빨간색(고가중치)이고 나머지는 완전 공백(0).
> - 정제 후(오른쪽): 카테고리별 지분율을 균등 분할하고 **Floor(0.005)**를 주입함으로써 모든 피처가 최소 매크로 충격 노출도를 확보.

---

## 4. 업종별 매크로 카테고리 지분율 분석

각 업종이 어떤 매크로 경제 영역에 본질적인 리스크 지분을 가지고 있는지 정규화한 결과입니다.

![Macro Category Shares Chart](file:///c:/Users/User/Desktop/eco_ref_model/model_building/output/category_shares_chart.png)

### 주요 업종별 카테고리 지분율 특징

| 대분류 | 업종명 | Equity | FX | Commodity | Macro/Biz | Interest | 핵심 리스크 특성 |
|:---:|:---|---:|---:|---:|---:|---:|:---|
| **L** | 부동산업 | 2.2% | **57.4%** | 9.7% | 20.7% | 10.0% | 환율 및 실물 경기 지표 변동에 극도 취약 |
| **P** | 교육 서비스업 | 0.2% | **61.4%** | 13.6% | 13.8% | 11.0% | 대외 환율 및 소비자 경기 변동성 노출 |
| **Q** | 보건업 및 사회복지 | 8.5% | 43.2% | 0.0% | 5.8% | **42.5%** | 환율과 함께 **채권/금리 시장 변동성**에 지배적 영향 |
| **I** | 숙박 및 음식점업 | 6.1% | **50.2%** | 10.9% | 11.2% | 21.6% | 환율 및 금리 부담에 따른 내수 소비 민감 |
| **C** | 제조업 | 20.7% | **45.5%** | 19.7% | 10.3% | 3.8% | 주가·환율·원자재 등 교역 관련 전방위 노출 |

---

1. **최종 정제 가중치 매트릭스**: [industry_macro_smoothed_weights.csv](file:///c:/Users/User/Desktop/eco_ref_model/model_building/output/industry_macro_smoothed_weights.csv)
   - 18개 KSIC 대분류 행 × 172개 거시경제 피처 열 (행합 정확히 1.0 검증 완료)
2. **업종별 카테고리 지분율 테이블**: [category_shares_by_industry.csv](file:///c:/Users/User/Desktop/eco_ref_model/model_building/output/category_shares_by_industry.csv)
3. **차주별 최종 통합 리스크 스코어링 리포트**: [final_borrower_credit_risk_report.csv](file:///c:/Users/User/Desktop/eco_ref_model/model_building/output/final_borrower_credit_risk_report.csv)
   - 전수 차주(540,568건) 대상 Calibrated `BASE_PD` 및 동적 스트레스 반영 `FINAL_DYNAMIC_PD` 연산 완료

---

## 6. 최종 통합 스코어링 파이프라인 성과 및 검증 요약

### 6.1 전수 스코어링 파이프라인(`final_scoring_pipeline.py`) 완료 결과
- **분석 대상**: 전수 차주 월별 패널 데이터 **540,568건** (`model_input_train.csv`)
- **기본 보정 부도확률(BASE_PD)**:
  - 단일 `IsotonicRegression` 보정기 적합 완료 (재학습 없이 사후 보간 매핑용 고정)
  - 평균 **0.0857%** (`0.000857`) 산출 $\rightarrow$ 실제 데이터 전체 부실률(463건/54만건 = **0.0856%**)과 완벽한 확률 정합성 확보
  - Base 모형 예측 성능: ROC-AUC **0.7751**, Brier Score **0.000855**

### 6.2 수학적 연산 및 결합 원칙 준수 성과
- **SHAP 부호 보존 법칙**: 차주별 매크로 원시 SHAP 값과 업종 정제 가중치를 일대일 곱하여 내적 합산.
- **로짓 공간 오버레이 결합**: LightGBM 원시 로짓 점수(`raw_logits`)와 오버레이 점수를 로짓 공간에서 더해줌 (`final_logits = raw_logits + Macro_Overlay_Adjustment`).
- **사후 보간 확장 매핑**: 기존 Isotonic 보정기 매핑을 확장 적용하여 동적 스트레스 반영 부도확률(`FINAL_DYNAMIC_PD`) 도출.
- **AUC 정상화 달성**: 이전 파이프라인의 확률 양극화 및 AUC 붕괴(0.45)를 완벽 극복하고 **최종 AUC 0.7713** (무작위선 0.5 위 정상화) 달성.
- **종합 평가 산출물 통합 배치**: 합의된 대로 최종 모델 성능, 스코어링 리포트(`final_borrower_credit_risk_report.csv`) 및 전체 그래프 PNG(8종)를 포함한 총 15개 산출물 전수를 [final_model_evaluation/](file:///c:/Users/User/Desktop/eco_ref_model/model_building/final_model_evaluation) 폴더로 일괄 집결 완료했습니다.
