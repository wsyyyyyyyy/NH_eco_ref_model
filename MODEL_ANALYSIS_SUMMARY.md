# 경제참조모델(ERM) AI 신용평가 모형 구축 및 매크로 리스크 가중치 정제 요약 보고서

본 보고서는 차주 고유 재무 데이터와 거시경제 데이터를 통합하여 부실률을 예측하는 LightGBM 모형을 구축하고, SHAP 기반 **업종별 매크로 리스크 가중치 매트릭스**를 도출한 후 실무 스트레스 테스트를 위한 **스무딩(Smoothing)**까지 수행한 전체 과정과 결과를 요약합니다.

---

## 1. 모형 학습 및 SHAP 추출 요약

- **전체 데이터**: 540,568행 × 248열 (부실률 0.086% 불균형 보정 `scale_pos_weight = 1166.53`)
- **최종 모형 성능**: Test AUC **0.8627**, 부실 탐지율(Recall) **0.91**
- **외부 등급 배제**: NICE 신용등급 등 외부 평가지표 완전 차단 조건에서 달성한 변별력

---

## 2. 가중치 정제(Smoothing) 및 리스크 하한선(Floor) 부여

### 2.1 희소성(Sparsity) 문제 해결
- 원시 SHAP 가중치 매트릭스는 머신러닝 변수 선택의 한계로 인해 **96.2%의 변수가 0으로 쏠려 있는 현상** 발견.
- 이를 해결하기 위해 172개 거시경제 피처를 **6대 매크로 카테고리**로 묶어 정제 파이프라인 수행.

### 2.2 3단계 알고리즘 적용 결과

```
[1단계: 카테고리 분류] Equity(28), FX(20), Commodity(24), Agri(8), Interest(42), Macro/Biz(50)
[2단계: 균등 재분배] 각 업종의 카테고리 지분율을 하위 피처 수로 균등 분할 주입
[3단계: Floor 부여] 최소 리스크 하한선 0.005 적용 후 전체 행 재정규화(Sum=1.0)
```

- 정제 전 96.2%이던 Zero 가중치 비율이 **0.0%로 완전 해소**.
- 모든 지표가 최소한의 노출도(Floor)를 확보하여 웹 대시보드 및 스트레스 테스트 시뮬레이터 구동 안정성 확보.

---

## 3. 핵심 산출물 및 연동 경로

| 구분 | 파일명 | 파일 경로 | 설명 |
|:---|:---|:---|:---|
| **모형** | `lgbm_credit_model.pkl` | `model_building/output/` | LightGBM 신용평가 모형 |
| **원시 가중치** | `industry_macro_shap_weights.csv` | `model_building/output/` | 원시 SHAP 가중치 매트릭스 |
| **정제 가중치** | `industry_macro_smoothed_weights.csv` | `model_building/output/` | **최종 정제 매트릭스 (18업종 × 172피처)** |
| **지분율 분석** | `category_shares_by_industry.csv` | `model_building/output/` | 업종별 6대 카테고리 지분율 테이블 |
| **비교 히트맵** | `smoothing_comparison_heatmap.png` | `model_building/output/` | 정제 전후 비교 시각화 |

---

## 4. 파이프라인 실행 스크립트

```bash
# 1. 모형 구축 및 가중치 도출
.\.venv\Scripts\python.exe model_building/train_and_analyze.py

# 2. 가중치 스무딩 및 Floor 부여
.\.venv\Scripts\python.exe model_building/smooth_weights.py
```

---

## 5. 형상 관리 이력

- **원격 저장소**: [https://github.com/wsyyyyyyyy/eco_ref_model](https://github.com/wsyyyyyyyy/eco_ref_model)
- **반영 브랜치**: `main`
