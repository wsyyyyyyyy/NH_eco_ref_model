# 🚀 기업 부도 예측(Early Warning) AI 모델 개발 (ECO Ref Model)

본 프로젝트는 기업의 재무, 비재무, 거시경제 데이터를 종합적으로 분석하여 향후 12개월 내 부도 발생 가능성을 예측하는 머신러닝 기반 조기경보시스템(EWS, Early Warning System) 개발 리포지토리입니다.

## 🎯 프로젝트 목표
1. **정확한 부도 예측**: LightGBM을 활용해 기업의 복합적인 리스크를 선제적으로 파악.
2. **현업 수용성 극대화**: 예측 확률을 1~5등급의 Z-Score 리스크 등급으로 변환하고, 현업의 비용 구조(미탐 비용 >> 오탐 비용)를 반영한 최적의 의사결정 임계값을 산출.
3. **기존 시스템의 한계 극복**: 은행 내부 조기경보등급(A등급) 내에 숨어있는 **사각지대(Blind Spot)를 발굴**하고, 평균 **6.8개월 먼저 부도를 경고**하는 조기경보 가치 입증.

---

## 🛠 데이터 파이프라인 & 전처리 (Data Pipeline)

전체 파이프라인은 `eda_pipeline/` 디렉토리 내에 단계별 스크립트(`step1` ~ `step13`)로 구성되어 있습니다.

### 1. 데이터 병합 (Data Integration)
- **차주 기본 정보 & 재무 정보**: KIS 신용평가 데이터, 기업 재무제표(`JEMU`), 비재무 지표 병합.
- **거시경제 지표 결합**: 코스피 지수, 환율(EUR/KRW), 금리, 물가상승률(CPI) 등 Macro 데이터를 시계열(패널) 형태로 조인.
- **업종 데이터 고도화**: 국세청 홈택스 표준산업분류 연계표(`업종코드-표준산업분류 연계표_홈택스 게시.xlsx`)를 활용하여 숫자형 업종코드(`STD_INDS_CFC`)를 비즈니스 해석이 가능한 한글명으로 매핑.

### 2. 결측치 및 이상치 처리 (Missing Value Handling)
- **결측치의 비즈니스적 해석**: KIS 신용평가 점수(`CG01_KIS_SCORE`)나 신용불량사유 등 결측(Null)이 발생하는 경우 무작정 평균으로 대치하거나 삭제하지 않고 `-1` 또는 특정 상수로 대체했습니다. 
- 모델은 이를 "점수가 없는 영세/신생 기업"이라는 강한 부도 리스크 시그널로 학습했으며, 이는 실제 데이터 분포와 현업의 비즈니스 상식에 완벽히 부합했습니다.

### 3. 타겟 변수 및 시계열 분리 (Target Engineering & CV)
- **타겟 차주 (Target Audience: 중소기업 집중)**: 전체 데이터 중 기업규모코드(`BZSCAL_C`)가 4.0(중소기업)인 기업군만 타겟팅하여 해당 세그먼트의 부도 패턴을 정밀하게 학습하도록 제한했습니다.
  - **타겟팅 사유 (Data-Driven)**: 데이터 병합 후 탐색적 분석(EDA) 결과, 중소기업(4.0)을 제외한 다른 규모의 기업군(대기업, 중견기업 등)은 전체 표본 수와 실제 부도 발생 건수가 머신러닝 모델을 안정적으로 학습하기에 턱없이 부족했습니다. 이들을 무리하게 포함할 경우 모델의 학습 패턴이 교란(Noise)될 우려가 커, 실제 부도 건수의 91% 이상이 집중된 중소기업에 타겟을 집중했습니다.
  
  | 기업규모 (BZSCAL_C) | 총 관측치 수 (Total) | 실제 부도 건수 (Defaults) | 비고 |
  | :--- | :--- | :--- | :--- |
  | **4.0 (중소기업)** | **1,775,314** | **2,586** | **🌟 최종 모델링 대상** |
  | 5.0 | 171,378 | 182 | 표본 및 부도수 부족 |
  | 2.0 (중견기업 등) | 55,080 | 6 | 부도 거의 발생하지 않음 |
  | 8.0 | 43,362 | 66 | 표본 부족 |
  | 기타 (0.0, 1.0, 6.0, 9.0) | 28,284 | 0 | 부도 0건 (학습 불가) |
- **Target**: 향후 12개월 내 부도 발생 여부 (`IS_BUDO_12M`).
  - **과학적 타겟 설정 (Time-to-Default 분석)**: 사전 데이터 탐색(EDA) 과정에서 실제 부도 기업들의 '기준 시점 대비 부도 발생까지의 소요 기간(Time-to-Default)' 분포를 시각화 및 분석했습니다. 그 결과, 부도 징후 발현 후 12개월 이내에 실제 부도로 이어지는 비율이 통계적으로 유의미한 변곡점을 형성함을 확인했습니다. 이를 근거로 현업의 선제적 리스크 관리(채권 보전 등)가 가능한 최적의 골든타임을 12개월로 산정하여 최종 예측 타겟을 도출했습니다.
- **Out-of-Time 검증**: 특정 시점의 경제 상황에 과적합되지 않도록, 학습(Train)은 2023년 12월 이전 데이터로, 검증(Valid)은 2024년 1월 이후 미래 데이터로 완벽히 분리(Out-of-Sample)하여 모델의 시간적 강건성(Robustness)을 확보했습니다.

---

## 🤖 모델링 및 심층 분석 (Modeling & Analysis)

### 1. LightGBM 기반 베이스 모델 학습 (`step7`, `step8`)
- **성과**: ROC AUC `0.9011` 달성.
- **SHAP 분석**: 상위 50대 변수를 추출하여 재무지표(자본총계, 차입금 의존도), 거시경제지표(환율 변동성), 업력(`BUSINESS_AGE`)이 부도에 미치는 영향을 직관적으로 시각화.
- **업종 심층 분석**: 경기 민감 산업(건설업, 인력 대행업 등)의 높은 위험도와 필수 소비재(식음료 제조 등)의 높은 안전도를 확인. 업종 변수를 통제(Ablation)하더라도 전체 성능은 유지됨을 증명하여 모델의 맹목적 과적합 우려를 해소했습니다.

### 2. 경량화(Lean) 모델 및 VIF 다이어트 (`step9`)
- **VIF < 10**: 다중공선성이 높은 지표들을 엄격하게 제거하여 기존 **230개의 변수를 80개 핵심 변수로 대폭 압축**했습니다.
- **페널티 검증**: 탐지율(Recall)을 82.6%로 고정했을 때, 150개 변수를 덜어낸 Lean 모델의 추가 오경보 발생 건수는 전체 89만 건(Valid) 중 불과 3,216건(0.36%)에 불과했습니다. 모델 API 응답 속도 최적화 및 파이프라인 유지보수 비용을 혁신적으로 절감했습니다.

### 3. Z-Score 리스크 등급화 (`step12`)
- **실전 5등급 체계**: 기계학습 모델의 복잡한 로그-오즈(Log-odds) 값을 표준정규분포(Z-Score)로 정규화하여 현업 심사역들이 즉시 사용할 수 있는 5등급(G1~G5) 체계로 맵핑 완료했습니다.
- 89만 건의 미래 Valid 셋 검증 결과, **G1(0.00%)부터 G5(22.92%)까지 부도율이 단 한 번의 역전 없이 완벽하게 단조 증가(Monotonic Increase)**함을 확인했습니다.

### 4. 비용 기반 최적 임계값 도출 (Cost-Sensitivity)
- 현업 피드백인 "부도 미탐 비용이 오경보 비용보다 압도적으로 높다"는 점을 수리적으로 반영하여 10배, 20배, 50배 민감도 분석(Sensitivity Analysis)을 수행했습니다.
- 통계적 지표인 **F2-Score의 최적 임계값(`0.3797`)**이 '10배 미탐 비용' 시나리오와 완벽히 일치함을 증명했으며, 0.27~0.38 사이의 Threshold를 통해 실무 오경보 피로도와 부도 방어율의 최적 밸런스 설정 가이드라인을 제시했습니다.

### 5. 핵심 성능 지표 검증 및 가상 지점 매핑 (`step13`)
- **평가 지표 결과 (Valid):** ROC-AUC **0.9011**, Gini **80.2**, K-S **67.2**, PSI **0.1247**
- 과거 AUROC 0.77 수준에 머물던 은행 내부 모형 대비 **압도적으로 정교한 예측력(0.9 돌파)**을 입증했습니다.
- **데이터 활용 준비 완료:** 확보된 고도화 스코어링 데이터를 기반으로 전체 194만 건의 중소기업 데이터에 5개의 가상 지점(Virtual Branch, VB001~VB005) 맵핑(태깅)을 성공적으로 완료하여 현업 서비스 도입 준비를 마쳤습니다.

---

## 🚀 비즈니스 임팩트 (Business Value & Conclusion)

이 모델의 가장 큰 가치는 단순한 정확도 수치 향상을 넘어 **기존 은행 내부 조기경보모형의 치명적 맹점을 완벽히 해결**했다는 데 있습니다.

기존 내부 모형이 **"안전(A등급)"**하다고 맹신한 집단을 신규 AI 모델로 재평가한 결과, **실제 부도율이 30%에 육박하는 1.7만 개의 시한폭탄 차주(G5)**를 핀셋처럼 솎아냈습니다.
이 A등급 內 시한폭탄 집단에서 실제로 부도가 터진 차주들의 과거 등급 궤적(Trajectory)을 추적한 결과:
1. **완전한 사각지대 해소 (63.4%)**: 부도가 터지는 시점까지도 은행 내부 등급이 끝내 'A'를 유지했던 기업들을 AI 모델이 사전에 색출했습니다.
2. **압도적인 조기 탐지 속도 (36.6%)**: 내부 모형이 뒤늦게 위험을 감지하여 B등급으로 하향 조정한 기업들에 대해, AI 모델이 이들보다 **평균 6.8개월 먼저 초고위험(G5) 상태임을 경고**했습니다.

👉 **결론**: 본 예측 모델을 여신 심사 프로세스에 도입할 경우, 향후 발생할 막대한 충당금 손실을 방어할 수 있는 **반년(6.8개월)의 선제적 리스크 관리 골든타임**을 안정적으로 확보할 수 있습니다.

---

## 🖥 AI 조기경보 웹 포털 (Portal & Real-Data Integration)

모델링 산출물을 실사용자가 쓸 수 있는 형태로 서비스화한 FastAPI + DuckDB 백엔드와 React 프론트엔드 포털입니다 (`step14` ~ `step20`).

### 1. 포털 구축 (`step14`, `step15`)
- **DuckDB + FastAPI**: 194만 건 규모의 기업 시계열 패널(`portal.duckdb`)을 실시간 OLAP 조회하는 API 서버 구축.
- **React 포털 UI/UX**: 글로벌 뱅크 뷰(전사 현황) → 지점 대시보드(차주 리스트) → 차주 상세(개별 심사) 3단 계층 구조의 실사용자 웹 포털 개발.

### 2. 백엔드 안정화 및 모델 실연동 (`step16`, `step17`)
- **거시경제 시뮬레이션 실모델화**: `/api/simulation`을 목업 대신 실제 LightGBM 모델 재추론(`model_inference.py`)으로 교체.
- **데이터 정합성 확보**: 차주 리스트/상세 화면 간 등급 불일치 원인이었던 `(V_BZNO, BASE_YM)` 중복 행을 `dedup_panel_sql()`로 전면 제거, 기준연월 파라미터 미반영 버그 수정.
- 운영 안전성: `.env` 기반 설정 분리, CORS 제한, LightGBM 모델 파일 CRLF 손상 방지용 `.gitattributes` 추가.

### 3. 차주 상세 페이지 실데이터 전환 (`step18`, `step19`)
- **재무/비재무 3개년 이력, 부도확률(PD) 시계열, 요인별 기여도(SHAP), 기업역량진단(Radar)**: 모두 하드코딩 mock을 제거하고 실제 DB 집계·`shap.TreeExplainer`·업종 백분위(`PERCENT_RANK`) 기반 실계산으로 교체.
- **Gemini AI 조기경보 의견**: `google-genai` 구조화 출력(`response_schema`)으로 실시간 리스크 코멘트 생성, `(bzno, base_ym)` 캐싱 및 할당량 초과 시 정적 가이드로 자연스럽게 폴백하는 UX 적용.

### 4. 글로벌 뱅크 뷰 실데이터 전환 (`step20`)
- 전사 KPI, 등급분포, PD-LAG 실질 부도율 추이(`/api/dashboard/trend`), 업종별 리스크 매트릭스 산점도까지 남아있던 마지막 가짜 수식(mock)을 실제 월별 집계·실현 부도율(`IS_BUDO_12M`)로 전면 교체하여, 포털 전 화면이 end-to-end로 실데이터와 연동됨을 확인.

---

## 📂 리포지토리 파일 구조 (File Structure)

```text
├── README.md                          # 프로젝트 오버뷰 및 요약 (현재 파일)
├── docs/                              # 기획, 설계, 분석 결과 등 산출물 관리 (Walkthrough, Task 등)
│   ├── 00_project_master_report.md    # ⭐ 데이터 명세~전처리~목표변수~모델링~성능~기존모형 비교~포털화 전체 종합 리포트
│   ├── step01_to_06_data_pipeline_and_eda.md
│   ├── step07_to_09_modeling_and_shap_analysis.md
│   ├── step10_to_13_model_evaluation_and_walkthrough.md
│   ├── step14_portal_api_setup.md             # Step 14 DuckDB+FastAPI 웹 포털 구축 명세
│   ├── step15_integrated_portal_development_report.md # Step 15 AI 조기경보 웹 포털 UI/UX 종합 보고서
│   ├── step16_backend_hardening_and_real_model_integration.md # Step 16 시뮬레이션 실모델화 및 백엔드 하드닝
│   ├── step17_data_consistency_and_dedup_fixes.md      # Step 17 리스트/상세 정합성 및 중복행 제거
│   ├── step18_borrower_detail_ux_and_ai_tips_structuring.md # Step 18 차주 상세 UX 개편 및 AI 팁 구조화
│   ├── step19_gemini_reliability_and_real_shap_capability.md # Step 19 Gemini 안정화 및 실제 SHAP/역량진단
│   └── step20_global_dashboard_real_trend_and_industry_matrix.md # Step 20 글로벌 뱅크 뷰 실데이터 전환
├── frontend/                          # React 18 + Vite + Recharts 기반 실사용자 ERM 조기경보 웹 포털
│   └── src/
│       ├── config.ts                  # API_BASE_URL 등 환경설정
│       └── pages/                     # GlobalDashboard, BranchDashboard, BorrowerDetail, ModelMonitoring, MacroSimulation, LoginPage
├── backend/                            # FastAPI 기반 실시간 DuckDB OLAP 조회 및 AI 조기경보 분석 API
│   ├── main.py                        # FastAPI 앱 엔트리포인트, CORS/라우터 등록
│   ├── database.py                    # DuckDB 커넥션 및 dedup_panel_sql 등 공통 쿼리 유틸
│   ├── model_inference.py             # LightGBM 모델/SHAP explainer 로딩 및 실추론
│   ├── grade_mapping.py                # PROB_FULL → 16단계 등급 매핑
│   ├── feature_labels.py              # 모델 피처 코드 → 한글 라벨 매핑
│   └── routers/                       # dashboard, borrowers, monitoring, simulation, ai API 라우터
├── database/                          # portal.duckdb 기업 시계열 패널 데이터 저장소
├── eda_pipeline/
│   ├── step1_load.py                  # 원천 데이터 로드
│   ├── step2_integrate.py             # 차주 기본정보 통합
│   ├── step3_eda.py                   # 탐색적 데이터 분석
│   ├── step4_borrower_sheet.py        # 차주 상세 명세서 뷰어 스크립트
│   ├── step5_panel_prep.py            # 시계열 패널 데이터 변환
│   ├── step6_macro_integration.py     # 거시경제 지표 시계열 결합
│   ├── step7_modeling_shap.py         # LightGBM 학습 및 기초 SHAP 추출
│   ├── step8_shap_analysis_top50.py   # 상위 50대 변수 및 업종 심층 분석
│   ├── step9_vif_zscore_tuning.py     # 다중공선성(VIF) 다이어트 및 초기 Z-Score
│   ├── step10_walkthrough_v2...       # Threshold 민감도 초기 분석
│   ├── step11_compare_internal.py     # 은행 내부 A/B 등급 변별력 비교 분석
│   ├── step12_walkthrough_v3...       # OOT Z-score, Lean 비용, F2-score 고도화 검증
│   ├── step13_performance_metrics.py  # ROC-AUC, Gini, K-S, PSI 최종 성능 지표 추출
│   ├── output/                        # 데이터 중간 산출물 및 시각화 이미지 (Git Ignore 처리)
│   └── 업종코드-표준산업분류 연계표... # 한글 업종 매핑용 국세청 사전 데이터
```
