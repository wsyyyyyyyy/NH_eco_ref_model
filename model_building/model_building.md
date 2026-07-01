# 모델 빌딩(Model Building) 파이프라인

본 문서는 **차주 고유 재무 데이터**와 **거시경제 데이터**를 통합하여 부실률을 예측하는 LightGBM 모형을 학습하고, SHAP 기반 **업종별 매크로 리스크 가중치 매트릭스**를 도출한 후 실무 스트레스 테스트용 **스무딩(Smoothing)**까지 수행하는 전체 파이프라인을 설명합니다.

---

## 1. 파이프라인 개요

### 주요 스크립트
1. `train_and_analyze.py` — 전처리 + LightGBM 학습 + 원시 SHAP 매트릭스 추출
2. `smooth_weights.py` — 6대 매크로 카테고리 기반 가중치 스무딩 및 Floor 부여
3. `final_scoring_pipeline.py` — 전수 차주(54만건) 대상 PD 보정(Calibration) 및 동적 매크로 오버레이 스코어링

### 입력 및 산출 데이터
- **입력 데이터**: `input/model_input_train.csv`, `input/bzcc.xlsx`
- **핵심 산출물**:
  - `output/lgbm_credit_model.pkl` (LightGBM 모형)
  - `output/industry_macro_shap_weights.csv` (원시 매트릭스)
  - `output/industry_macro_smoothed_weights.csv` (최종 정제 매트릭스)
  - `output/final_borrower_credit_risk_report.csv` (차주별 통합 PD 보고서)
  - `final_model_evaluation/` (종합 평가 지표 JSON 및 시각화 차트)

---

## 2. [1~3단계] 모형 학습 및 원시 SHAP 가중치 산출

1. **데이터 전처리**: 불부실(`BRWR_DSH_YN`) 타깃 매핑 및 결측치 중앙값(Median) 대체
2. **LightGBM 학습**: 극단적 불균형(`scale_pos_weight = 1166.53`) 보정 후 학습 (Test AUC: `0.8627`)
3. **SHAP 매트릭스 추출**: 18개 대분류 업종 × 172개 거시경제 피처별 평균 절대값 정규화

---

## 3. [4단계] 매크로 리스크 가중치 스무딩(Smoothing) 및 하한선 부여

### 3.1 배경 및 문제점 (Sparsity)
- 머신러닝 모형의 트리 분할 변수 선택 특성상 원시 SHAP 가중치 매트릭스의 **96.2%가 0으로 쏠리는 현상** 발생.
- 특정 매크로 변수에 충격(Shock)을 가하는 실무 스트레스 테스트 시, 가중치가 0인 지표는 모형에 전혀 반영되지 않는 한계 존재.

### 3.2 해결 알고리즘 (3-Step Smoothing)

```
[피처 분류] 172개 피처 → 6대 카테고리 매핑
    ↓
[지분율 산출] 카테고리별 합산 → 정규화(Sum=1.0)
    ↓
[스무딩 분배] 카테고리 내 피처별 균등 재분배(Uniform Redistribution)
    ↓
[Floor 부여] 최소 리스크 하한선(0.005) 주입 후 행 정규화(Sum=1.0)
```

1. **6대 매크로 카테고리 분류**:
   - `Equity` (주가지수: KOSPI, S&P500 등 28개)
   - `FX` (환율: 원달러, 엔달러 등 20개)
   - `Commodity` (원자재/에너지: 유가, 금 등 24개)
   - `Agri` (농산물: 옥수수, 대두 등 8개)
   - `Interest` (금리/채권: 국고채, 통안채 등 42개)
   - `Macro/Biz` (거시경제/경기지수: CPI, BSI, VIX 등 50개)

2. **지분율 기반 균등 재분배**:
   - 업종별로 각 카테고리가 차지하는 전체 중요도 합(지분율)을 구한 뒤, 해당 카테고리 내의 모든 개별 피처들에게 `지분율 / 피처 수`만큼 균등 분배.

3. **리스크 하한선(Floor) 부여**:
   - 모든 피처에 최소 가중치 `0.005` 주입 후 행별 최종 정규화 수행.
   - 정제 전 96.2%에 달하던 Zero 비율이 **0.0%로 완전 해소**.

---

## 4. 실행 방법

```powershell
# 1. 모형 학습 및 원시 가중치 추출
.\.venv\Scripts\python.exe model_building/train_and_analyze.py

# 2. 가중치 스무딩 및 정제
.\.venv\Scripts\python.exe model_building/smooth_weights.py

# 3. 차주 전수 최종 스코어링 및 종합 평가 산출
.\.venv\Scripts\python.exe model_building/final_scoring_pipeline.py
```

---

## 5. 디렉토리 구조

```
model_building/
├── train_and_analyze.py          # 베이스 학습 및 SHAP 추출 스크립트
├── smooth_weights.py             # 모형 정제(Smoothing) 스크립트
├── final_scoring_pipeline.py     # 통합 스코어링 및 평가 스크립트
├── model_building.md             # 본 문서
├── walkthrough.md                # 분석 결과 종합 보고서
├── input/
├── output/
│   ├── lgbm_credit_model.pkl     # 학습된 모형
│   ├── industry_macro_shap_weights.csv      # 원시 매트릭스
│   ├── industry_macro_smoothed_weights.csv  # 최종 정제 매트릭스
│   ├── category_shares_by_industry.csv      # 업종별 카테고리 지분율
│   └── final_borrower_credit_risk_report.csv # 차주별 통합 PD 보고서
└── final_model_evaluation/       # 최종 모델 종합 평가 결과
    ├── evaluation_metrics_summary.json
    ├── roc_curve_comparison.png
    ├── calibration_curve_comparison.png
    └── pd_distribution_comparison.png
```
