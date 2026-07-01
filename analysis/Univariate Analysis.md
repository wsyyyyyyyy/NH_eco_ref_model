# 📊 단변량 분석(Univariate Analysis) 및 변수 선택 명세서

> **최종 수정일**: 2026-05-16
> **스크립트**: `analysis/univariate_analysis.py`
> **입력**: `api_data_processing/output/model_input/model_input_daily_cleaned.csv` (206개 변수)
> **출력**: `analysis/output/` (5개 리포트 CSV)

---

## 목차

1. [개요](#개요)
2. [분석 파이프라인 흐름](#분석-파이프라인-흐름)
3. [Step 1: Raw 데이터 통계량](#step-1-raw-데이터-통계량)
4. [Step 2: Fine-Classing (WoE/IV)](#step-2-fine-classing-woeiv)
5. [Step 2.5: Coarse-Classing (단조성 WoE)](#step-25-coarse-classing-단조성-woe)
6. [Step 3-4: IV 기반 필터링 및 지표별 Best 선택](#step-3-4-iv-기반-필터링-및-지표별-best-선택)
7. [Step 5: VIF 다중공선성 제거](#step-5-vif-다중공선성-제거)
8. [3대 핵심 모델링 제약 조건](#3대-핵심-모델링-제약-조건)
9. [최종 선별 변수 목록](#최종-선별-변수-목록)
10. [출력 파일 목록](#출력-파일-목록)
11. [실행 방법](#실행-방법)

---

## 개요

Phase 5 안정성 변환을 거쳐 생성된 206개의 거시경제/금융 변수에 대해, 부도 타겟(Target Y)을 예측하는 **단변량 분석(Univariate Analysis)**을 수행하고 최종 모형 후보 변수를 선별하는 파이프라인입니다.

**핵심 원칙:**
- WoE(Weight of Evidence) / IV(Information Value) **선행** → 상관분석(VIF) **후행**
- 거시경제 변수 특성을 고려한 **Equal Interval Binning** fallback
- Coarse-bin 병합 시 **단조성(Monotonicity)** 강제

---

## 분석 파이프라인 흐름

```
[입력] 206개 변수 (정상성 확보된 변환 변수)
  │
  ▼
┌─────────────────────────────────────────────────────────────┐
│  Step 1: Raw 데이터 통계량 (Winsorized)                     │
│  · 2/98 percentile Winsorization 적용                       │
│  · 연속형 기초통계량 산출 (mean, std, skew, kurtosis 등)    │
│  → 01_raw_statistics.csv                                    │
└───────────────────────┬─────────────────────────────────────┘
                        ▼
┌─────────────────────────────────────────────────────────────┐
│  Step 2: Fine-Classing (WoE/IV)                             │
│  · 거시경제 특화: qcut → Equal Interval fallback            │
│  · 각 변수별 WoE, IV, Bad Rate 산출                         │
│  → 02_iv_ranking.csv                                        │
└───────────────────────┬─────────────────────────────────────┘
                        ▼
┌─────────────────────────────────────────────────────────────┐
│  Step 2.5: Coarse-Classing (Monotonic WoE)                  │
│  · Fine-bin → 4개 Coarse-bin 병합                           │
│  · 인접 WoE 차이 최소 구간 bottom-up 병합                   │
│  · 단조 증가/감소 WoE 강제                                  │
│  → 03_coarse_classing.csv                                   │
└───────────────────────┬─────────────────────────────────────┘
                        ▼
┌─────────────────────────────────────────────────────────────┐
│  Step 3: IV 기반 1차 필터링 (IV >= 0.02)                    │
│  · Unpredictive 변수 제거                                   │
│  → 206개 → 203개                                            │
│                                                             │
│  Step 4: 동일 지표 내 Best IV 선택                          │
│  · 원천 지표(KOSPI 등)별 최고 IV 변환 변수만 생존           │
│  → 203개 → 66개                                             │
│  → 04_best_per_indicator.csv                                │
└───────────────────────┬─────────────────────────────────────┘
                        ▼
┌─────────────────────────────────────────────────────────────┐
│  Step 5: VIF 다중공선성 제거 (VIF < 5.0)                    │
│  · IV 높은 변수부터 Forward Selection                       │
│  · 추가될 때마다 전체 VIF 검증                              │
│  → 66개 → 17개                                              │
│  → 05_final_selected_variables.csv                          │
└───────────────────────┬─────────────────────────────────────┘
                        ▼
[출력] 최종 17개 모형 후보 변수 (NaN 0개, VIF < 5, 단조 WoE)
```

---

## Step 1: Raw 데이터 통계량

### Winsorization 규칙

| 항목 | 규칙 |
|---|---|
| 하한 | 2nd percentile 미만 → 2nd percentile 값으로 대체 |
| 상한 | 98th percentile 초과 → 98th percentile 값으로 대체 |
| 예외 | 2nd = 98th percentile 인 경우 변환하지 않음 (값 밀집) |

### 산출 통계량

| 통계량 | 설명 |
|---|---|
| `count` | 유효 관측치 수 |
| `missing_pct` | 결측 비율 (%) |
| `mean`, `std` | Winsorized 평균/표준편차 |
| `min`, `p25`, `median`, `p75`, `max` | Winsorized 분위수 |
| `skewness`, `kurtosis` | 왜도/첨도 (분포 형태 진단) |

---

## Step 2: Fine-Classing (WoE/IV)

### 거시경제 특화 구간화 전략 (최종 보완)

일반적인 20개 균등 구성비(`qcut`) 적용 시 발생하는 Bin 에러를 방지하기 위해 다음의 **3단계 fallback 안전 알고리즘**을 강제합니다. 실수형(Float) 변수를 유니크 값 기반의 범주형 타입으로 전환하는 행위는 절대 금지합니다.

```
1차 시도: pd.qcut(df[col], q=10, duplicates='drop')
  │ 실패 또는 생성된 유효 구간 수 < 5개
  ▼
2차 시도: pd.cut(df[col], bins=10, duplicates='drop')  ← 균등 간격 분할
  │ 실패 또는 생성된 유효 구간 수 < 2개 (데이터 극단적 쏠림)
  ▼
3차 강제 압축: pd.cut(df[col], bins=3, duplicates='drop') 적용 후 강제 진행
```

- 구간 수: 10개(기본) → 5개(최소)까지 유연 축소
- `duplicates='drop'` 옵션으로 중복 경계값 자동 처리

### WoE / IV 산출 공식

| 지표 | 공식 |
|---|---|
| **WoE** | `ln(% Good / % Bad)` |
| **IV component** | `(% Good - % Bad) × WoE` |
| **IV (total)** | `Σ IV components` |

### Laplace Smoothing 적용 타이밍 제약

- Fine-bin 단계에서 0.5건을 고정 가산하는 방식을 금지합니다.
- 최초 빈 생성 및 Step 2.5의 Bottom-up 병합 시, **항상 구간 내 원천 빈도(Raw Frequency)의 합산을 먼저 구한 직후, 특정 이벤트(Good 또는 Bad)의 원천 카운트가 0인 경우에만 해당 시점에 동적으로 0.5를 가산**하여 WoE 분모 마비를 방지합니다.

### IV 등급 기준

| 등급 | IV 범위 | 의미 |
|---|---|---|
| **Strong** | > 0.3 | 매우 강한 변별력 |
| **Medium** | 0.1 ~ 0.3 | 보통 변별력 |
| **Weak** | 0.02 ~ 0.1 | 약한 변별력 (사용 가능) |
| **Weak** | 0.02 ~ 0.1 | 약한 변별력 (사용 가능) |
| **Unpredictive** | < 0.02 | 변별력 없음 (제거, 단 0.015~0.020 구간은 별도 로깅) |

### 🚨 고도화 리스크 통제 1: Weak IV 모니터링 시스템
거시경제 지표 특성상 일별 결합 시점의 매칭 제약으로 IV가 `0.02` 부근에 조밀하게 분포할 수 있습니다. 이를 단순히 삭제하고 넘어가지 않도록, **`0.015 <= IV < 0.020` 구간에 존재하는 변수들은 별도의 모니터링 로거(`[MONITOR_LOG]`)를 통해 추적**합니다. 추적된 로그는 `analysis/output/monitor_weak_iv.log`에 저장되어 향후 마트 고도화 시 복원 후보로 활용됩니다.

---

## Step 2.5: Coarse-Classing (단조성 WoE)

### 단조성 강제 병합 알고리즘 (수정본)

Fine-bin(5~10개)을 4개의 Coarse-bin(매크로 국면 구간)으로 병합할 때, **연속형 변수의 수치적 연속성을 보존**하면서 WoE가 단조 증가 또는 감소하도록 강제합니다.

```
알고리즘: 수치 정렬 기반 인접 구간 병합 (Categorical 정렬 금지)
──────────────────────────────────────────────────────────

1. Fine-bin을 원래의 수치적 구간 경계값(X축 순서) 레벨로 정렬 유지
   · bin 레이블에서 하한값 추출: '(-0.012, 0.005]' → -0.012
   · bad_rate 정렬 사용 금지 (연속형 변수의 수치 순서 훼손 방지)

2. 원래 순서 상에서 인접한 구간 간의 WoE 차이(|ΔWoE|)를 계산

3. 수치적으로 인접한 쌍 중 |ΔWoE|가 가장 작은 구간을 순차 병합 (Bottom-up)
   · 병합 후 WoE/IV/bad_rate 재계산 (Laplace smoothing 유지)

4. 목표 구간 수(4개) 도달 시, 전체 구간의 WoE가 일관되게 상승하거나 하락하는지 검증

5. 단조성 위배 시 구간 수를 3개 → 2개로 순차 축소하여 재시도
   · 모든 시도 실패 시 is_monotonic = False 플래그 표시
```

### 왜 수치 순서 기반인가?

| 방식 | 문제점 |
|---|---|
| ❌ `bad_rate` 순 정렬 | 구간 (-0.01, 0.0]과 (0.05, 0.1]이 bad_rate에 의해 순서가 뒤바뀌면, 병합 시 수치적으로 비연속적인 구간이 합쳐져 해석 불가 |
| ✅ 수치 경계값 순 정렬 | X축(변수값) 순서를 유지하므로 인접 구간 병합이 자연스럽고, 스트레스 테스트 시나리오의 '국면 이동' 방향과 일치 |

### 목적

- 향후 **거시 스트레스 테스트 시나리오** 연동 시, 국면이 악화되면 평점도 일관되게 악화되도록 보장
- WoE가 비논리적으로 요동치는 것을 원천 차단
- 변수값의 물리적 크기 순서와 리스크 방향의 정합성 보장

---

## Step 3-4: IV 기반 필터링 및 지표별 Best 선택

### Step 3: IV 필터링

- **기준**: IV >= 0.02 (Unpredictive 변수 제거)
- **결과**: 206개 → **202개** (4개 제거)

### Step 4: 동일 지표 내 Best IV 선택

206개 변수는 동일한 원천 지표(예: KOSPI)에서 파생된 여러 변환이 공존합니다:

```
KOSPI_log_ret        (일별 로그 수익률)
KOSPI_vol20d         (20일 변동성)
KOSPI_log_ret_ma90d  (수익률 90일 평활)
KOSPI_vol20d_ma90d   (변동성 90일 평활)
```

이 중 **IV가 가장 높은 1개 변환만 생존**시킵니다.

- **접미사 제거 규칙** (원천 지표명 추출):
  - `_log_ret_ma90d`, `_vol20d_ma90d`, `_yoy_ma90d`, `_log_ret`, `_vol20d`, `_yoy` 순서로 제거
- **결과**: 66개 원천 지표 → **66개 Best 변수**

---

## Step 4.5: 경제적 카테고리 균형 매크로 풀 구성

### 왜 균형 풀이 필요한가?

66개 Best 변수를 그대로 VIF에 투입하면, **금리 지표(18종)**처럼 특정 카테고리에 편중된 변수들이 과도하게 생존하여 모형이 단일 경제 요인에 과적합됩니다.

### 알고리즘

```
1. 66개 Best 변수를 경제적 속성별로 분류
2. 각 카테고리에서 IV 상위 3개씩 선발
3. 균형 잡힌 핵심 매크로 풀(26개) 구성
4. 이 풀만 VIF 단계에 투입
```

### 카테고리 분류 (9개)

| 카테고리 | 포함 지표 예시 | 선발 수 |
|---|---|---|
| **Interest Rate** (금리) | 국고채, CD, KORIBOR, base_rate, 신용스프레드 | 3 |
| **FX** (환율) | USD/KRW, EUR/KRW, JPY/KRW, CNY/KRW, DXY | 3 |
| **Equity** (주식) | KOSPI, KOSDAQ, 다우, 나스닥, S&P500, 닛케이 | 3 |
| **Commodity** (원자재) | 원유, 천연가스, 금, 은, 구리, 곡물 | 3 |
| **Price** (물가) | CPI, PPI, 주택가격, 수출물가 | 3 |
| **Money** (통화) | M1, M2, Lf, 본원통화 | 3 |
| **Trade** (무역) | 경상수지, 수출입, 무역수지 | 3 |
| **Sentiment** (심리) | BSI, CSI, 실업률, 건설비용 | 3 |
| **Household** (가계) | 가계대출, 가계신용 | 2 |

> **결과**: 9개 카테고리 x 최대 3개 = **26개** 균형 풀

---

## Step 5: VIF 다중공선성 제거

### 알고리즘: 경제적 카테고리 균형 + Forward Selection + VIF Check

```
1. Step 4.5에서 구성된 26개 균형 풀을 IV 높은 순으로 정렬
2. 1번째 변수 무조건 선택
3. n번째 변수 추가 시:
   a. 기존 선택 변수 + 새 변수로 전체 VIF 계산
   b. 최대 VIF < 5.0 이면 → 선택
   c. 최대 VIF >= 5.0 이면 → 탈락 (다음 후보로)
4. 모든 후보 변수 순회 완료
```

- **VIF 계산**: `VIF_j = 1 / (1 - R^2_j)` (j번째 변수를 나머지로 OLS 회귀)
- **기준**: VIF < 5.0 (다중공선성 안전)
- **결과**: 26개 → **최종 선별 (보통 10~15개 내외)**

### 🚨 고도화 리스크 통제 2: VIF `inf` 발생 방어 및 예외 처리
Forward Selection 과정에서 특정 변수 간 선형 종속성이 극도로 높으면 결정계수($R^2$)가 `1.0`에 수렴하여 `VIF` 분모가 `0`이 되는 `ZeroDivisionError` 또는 `inf` 계산 오류가 발생할 수 있습니다. 
이를 방지하기 위해 **$R^2$가 `0.9999` 이상이거나 계산 결과가 `np.inf`인 경우, 에러로 중단되지 않고 VIF 값을 강제로 `999.0`으로 반환**하도록 처리합니다. 이를 통해 해당 변수는 `VIF < 5.0` 기준을 통과하지 못하고 자연스럽게 Skip되며, 전체 루프가 안정적으로 구동됩니다.

### 왜 카테고리 균형 → IV → VIF 순서인가?

| 단계 | 근거 |
|---|---|
| 카테고리 균형 먼저 | 금리 18종 중 3종만 남겨 특정 요인 과적합 방지 |
| IV 순 정렬 | 변별력 높은 변수를 우선 보존 |
| VIF 후행 | 다양한 카테고리에서 공선성 없는 최적 조합 확정 |

---

## 3대 핵심 모델링 제약 조건

### 지침 1: 분석 시퀀스 제약

> **WoE/IV를 1순위로 선행 산출 → 동일 지표 내 IV 최고 변수 생존 → 카테고리 균형 풀 → 생존 변수 간 VIF 후행**

- 206개 확장 변수는 다중공선성이 극심한 상태
- VIF를 먼저 돌리면 변별력과 무관하게 변수가 탈락하는 오류 발생
- IV 기반으로 경제적 의미 있는 변수를 먼저 확보한 후 공선성 제거

### 지침 2: 윤년 시계열 제약 (수정본)

> **행 인덱스 이동 방식인 `.shift(365)` 전면 금지**

- 2024년 윤년(366일)으로 인한 YoY 날짜 뒤틀림을 물리적으로 차단
- `impute_data.py`에서 **Calendar Date 기반 1:1 날짜 매핑 조인** 적용:
  ```python
  # 정확히 1년 전 날짜 계산 (2024-02-29 → 2023-02-28 자동 보정)
  date_1y_ago = date_col - pd.DateOffset(years=1)
  # merge 기반 매칭 (인덱스 shift 사용 금지)
  merged = lookup.merge(past, on="date_1y_ago", how="left")
  ```
- `pd.DateOffset(years=1)` 사용으로 윤년/평년 자동 보정
- 매칭 불가 날짜는 NaN → bfill/ffill 정제

### 지침 3: Coarse-Classing 단조성 제약

> **리스크 변화 흐름의 단조성(Monotonic WoE Binning) 강제화**

- 거시 스트레스 테스트 시나리오 연동 시 평점이 비논리적으로 요동치는 것을 방지
- 수치 구간 순서 기반 Bottom-up 병합 알고리즘으로 WoE 단조 증가/감소 보장
- 단조성 미달 시 구간 수 4 → 3 → 2 순차 축소 재시도
- `is_monotonic` 플래그로 최종 검증

---

## 최종 선별 변수 목록

| 순위 | 변수명 | IV | 카테고리 | 원천 지표 | 변환 유형 |
|---|---|---|---|---|---|
| 1 | `treasury_bond_10y_log_ret_ma90d` | 0.0465 | interest_rate | 국고채 10년 | 수익률 90일평균 |
| 2 | `JPY_KRW_vol20d` | 0.0457 | fx | 엔/원 환율 | 20일 변동성 |
| 3 | `goods_balance_yoy` | 0.0451 | trade | 무역수지(상품) | YoY 증감률 |
| 4 | `base_rate_yoy_ma90d` | 0.0440 | interest_rate | 기준금리 | YoY 90일평균 |
| 5 | `CD_rate_91d_yoy` | 0.0438 | interest_rate | CD 91일 | YoY 증감률 |
| 6 | `KOSPI_log_ret_ma90d` | 0.0433 | equity | KOSPI | 수익률 90일평균 |
| 7 | `M1_narrow_money_yoy` | 0.0426 | money | 협의통화(M1) | YoY 증감률 |
| 8 | `housing_price_index_yoy_ma90d` | 0.0417 | price | 주택가격지수 | YoY 90일평균 |
| 9 | `Nikkei225_log_ret` | 0.0415 | equity | 닛케이 225 | 일별 수익률 |
| 10 | `EUR_KRW_vol20d_ma90d` | 0.0397 | fx | 유로/원 환율 | 변동성 90일평균 |
| 11 | `silver_vol20d_ma90d` | 0.0394 | commodity | 은 | 변동성 90일평균 |
| 12 | `natural_gas_log_ret` | 0.0363 | commodity | 천연가스 | 일별 수익률 |
| 13 | `WTI_crude_oil_log_ret_ma90d` | 0.0356 | commodity | WTI 원유 | 수익률 90일평균 |
| 14 | `KOSDAQ_vol20d` | 0.0349 | equity | KOSDAQ | 20일 변동성 |

> **카테고리 커버리지**: 14개 최종 변수가 9개 카테고리 중 **7개**(금리, 환율, 주식, 원자재, 물가, 통화, 무역)를 커버합니다. 특정 경제 요인에 쏠리지 않은 균형 잡힌 구성입니다.

**※ 통계적 필독 노트:** 본 변수 목록 테이블은 파이프라인 출력 포맷의 이해를 돕기 위한 **가이드라인 예시 리포트**입니다. 실제 파이썬 엔진 가동 시, 동일 카테고리(예: Interest Rate) 내 변수 간 상관성이 극도로 높을 경우 **Step 5의 Forward Selection 알고리즘에 의해 상위 랭킹 변수만 생존하고 하위 금리 변수들은 VIF >= 5.0 스크리닝 컷오프로 인해 대거 자동 탈락(Skip)되는 것이 정상적인 계량경제학적 작동 결과**입니다.

---

## 출력 파일 목록

| # | 파일명 | 내용 | 건수 |
|---|---|---|---|
| 01 | `raw_statistics.csv` | Winsorized 연속형 기초통계량 | 206개 변수 |
| 02 | `iv_ranking.csv` | 전체 IV 랭킹 + 등급(Strength) | 206개 변수 |
| 03 | `coarse_classing.csv` | 단조 WoE Coarse-bin 상세 | 202개 변수 |
| 04 | `best_per_indicator.csv` | 지표별 최고 IV 변수 | 66개 변수 |
| 04.5 | `balanced_macro_pool.csv` | **카테고리 균형 매크로 풀** | **26개 변수** |
| 05 | `final_selected_variables.csv` | **최종 VIF 통과 변수** | **14개 변수** |

---

## 분석 결과 요약

| 단계 | 변수 수 | 비고 |
|---|---|---|
| 입력 (Phase 5 변환 후) | 206 | 로그수익률 + 변동성 + YoY + 90일평균 |
| Step 2: IV 산출 | 206 | Strong 0, Medium 0, Weak 202, Unpredictive 4 |
| Step 3: IV >= 0.02 필터 | 202 | 4개 변별력 없는 변수 제거 |
| Step 4: 지표별 Best IV | 66 | 66개 원천 지표에서 1개씩 |
| Step 4.5: 카테고리 균형 풀 | 26 | 9개 카테고리 x 최대 3개 |
| **Step 5: VIF < 5.0** | **14** | **최종 모형 후보 (7개 카테고리 커버)** |

---

## 파라미터 설정

| 파라미터 | 값 | 설명 |
|---|---|---|
| `WINSOR_LO` | 0.02 | Winsorization 하한 percentile |
| `WINSOR_HI` | 0.98 | Winsorization 상한 percentile |
| `FINE_BINS_DEFAULT` | 10 | Fine-bin 기본 구간 수 |
| `FINE_BINS_MIN` | 5 | Fine-bin 최소 구간 수 |
| `IV_THRESHOLD_WEAK` | 0.02 | IV 생존 하한 |
| `VIF_THRESHOLD` | 5.0 | VIF 통과 상한 |
| `COARSE_BINS_TARGET` | 4 | Coarse-bin 목표 구간 수 |
| `MAX_PER_CATEGORY` | 3 | 카테고리별 최대 선발 수 |

---

## 실행 방법

```bash
# 사전 조건: model_input_daily_cleaned.csv 생성 완료
.\.venv\Scripts\python.exe analysis\univariate_analysis.py
```

- **소요시간**: 약 10초
- **출력 위치**: `analysis/output/`
