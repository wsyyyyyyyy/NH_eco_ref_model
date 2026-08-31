# 🧹 데이터 전처리 및 결측치 정제(Imputation) 파이프라인

본 문서는 `model_input_monthly.csv`(월별 거시경제 및 금융 지표 통합 데이터)에 존재하는 결측치를 지표의 경제적/통계적 성격에 맞추어 정제하되, 신용평가 모형 개발 시 치명적인 **미래 기만 오류(Look-Ahead Bias)**를 원천 차단하기 위해 적용된 5단계 순차 처리 파이프라인을 정리한 문서입니다.

- **스크립트**: `api_data_processing/impute_data.py`
- **입력**: `api_data_processing/output/model_input/model_input_monthly.csv` (64개 지표, 65행)
- **출력**: `api_data_processing/output/model_input/model_input_monthly_cleaned.csv` (172개 지표, 53행, NaN 0개)
- **참조**: `api_data_processing/output/model_input/model_input_daily.csv` (Group A 변동성 집계용)

---

## 1. 결측치 발생 원인

서로 다른 발표 주기(Frequency)를 가진 64개의 지표를 월별(Monthly) 달력 기준으로 결합하는 과정에서 다음과 같은 이유로 결측치가 발생합니다:

- **발표 시점 차이(Publication Lag)**: 경제 지표의 기준월과 실제 발표 시점 사이의 시차로 인한 미래 누수 위험
- **분기/연간 데이터**: 발표 주기가 월별보다 낮은 지표의 공백 구간
- **시계열 시작점 불일치**: 일부 지표의 수집 시작 시점 차이

---

## 2. 지표 그룹 분류 (발표 시차 기반)

지표를 **발표 즉시성**에 따라 3개 그룹으로 분류하고, 그룹별로 서로 다른 시차 보정과 결측치 전략을 적용합니다.

### Group A: 금융 시장 지표 (t + 0, 즉시 공표) — 35개

| 카테고리 | 지표 |
|---|---|
| 국내 주가지수 | KOSPI, KOSDAQ |
| 해외 주가지수 | DowJones, NASDAQ, SP500, Nikkei225, Shanghai_Composite |
| 환율 | USD_KRW, EUR_KRW, JPY_KRW, CNY_KRW, DXY_dollar_index |
| 원자재 | brent_crude_oil, WTI_crude_oil, natural_gas, gold, silver, copper, corn, soybean |
| 변동성 | VIX |
| 일별 금리 | call_rate_overnight, call_rate_overnight_brokered, KORIBOR_3m/6m/12m, treasury_bond_1y/3y/5y/10y, corporate_bond_3y_AA, US_10Y/2Y_treasury, CP_91d, MSB_91d |

- **시차 보정**: 없음 (당월 말일 종가 즉시 반영)
- **결측 전략**: **Forward Fill (LOCF)** — 공백은 직전 관측값 유지

### Group B: 실물 경제 및 물가 지표 (t + 1개월, 익월 공표) — 16개

| 카테고리 | 지표 |
|---|---|
| 물가 | CPI_core, CPI_core_excl_food_energy, CPI_food_nonalcohol, PPI_total, housing_price_index |
| 통화량 | M1_narrow_money, M2_broad_money, Lf_liquidity, monetary_base_sa |
| 무역/국제수지 | export_index, import_index, trade_total, current_account, goods_balance |
| 월별 금리 | CD_rate_91d, treasury_bond_1y_monthly |

- **시차 보정**: **+1개월 Shift** (예: 3월 CPI → 4월에야 사용 가능)
- **결측 전략**: **Forward Fill (LOCF)** — 미래 데이터 누수(Look-Ahead Bias)를 차단하기 위해 선형 보간을 전면 금지하고 직전 공식 수치 유지

### Group C: 장기 거시 및 정책/심리 지표 (t + 2개월, 분기/연간 공표) — 10개

| 카테고리 | 지표 |
|---|---|
| 정책 금리 | base_rate |
| 가계 | household_credit, household_loan |
| 산업/무역 | current_account_quarterly |
| 심리 지수 | BSI_mfg_biz, BSI_mfg_export, BSI_mfg_domestic, BSI_nonmfg_biz, CSI_composite, CSI_living_prospect |

> ※ GNI_annual, manufacturing_index, export_price_index_KOR 3개 지표는 대량 결측으로 Phase 0에서 사전 드롭됩니다.

- **시차 보정**: **+2개월 Shift** (예: 1분기 GDP → 5월에야 사용 가능)
- **결측 전략**: **Forward Fill (LOCF)** — 다음 발표 전까지 공식 수치 고정

### 파생변수 (Phase 0에서 생성) — 2개

| 변수명 | 산출식 |
|---|---|
| `credit_spread` | `corporate_bond_3y_AA - treasury_bond_3y` |
| `liquidity_spread` | `CP_91d - MSB_91d` |

---

## 3. 6단계 순차 처리 파이프라인 (월별 전용)

결측치 정제는 **반드시 아래 순서(Sequence)를 엄격히 준수**하여 실행됩니다. 순서가 바뀌면 데이터 오염이 발생합니다.

```text
[최종 확정된 무결성 전처리 시퀀스 — Monthly Edition]
Phase 0: 파생변수 선행 연산 및 변수 정제 (원천 상태)
│ (GNI_annual 등 대량 결측 3개 지표 사전 드롭 처리)
│ (credit_spread, liquidity_spread 선행 계산)
▼
Phase 1: 가용성 시차 적용 및 일괄 ffill().bfill() (원천 레벨 NaN 0개 달성)
│ Group B: +1개월 shift, Group C: +2개월 shift
│ (레벨 결측 완전 청산)
▼
Phase 2: 비금리 Group A → 월간 로그 수익률 + 일별 원천 기반 월간 내 변동성
│ _log_ret: ln(P_t / P_{t-1}) — 월말 종가 기준
│ _vol_m: 일별 로그수익률 → YYYYMM groupby → std * sqrt(20) * 100
▼
Phase 3: 금리 → 12개월 차분(_diff12) / 비금리 B+C → YoY 증감률(_yoy)
│ 금리: col - col.shift(12) → _diff12
│ 비금리: (V_t - V_{t-12}) / V_{t-12} * 100 → _yoy
▼
Phase 4: 전체 변환 변수 대상 3개월 이동평균(_ma3m) 파생 변수 확장
│ (기본 변환 86개 + 이동평균 86개 = 총 172개 변수 빌드 완료)
▼
Phase 5: [치명적 미래 누수 원천 차단] 상위 12행 완전 절단 (Truncation)
· 로직: 변환 초기 행에서 발생한 12개월 분량의 NaN 구간을 bfill하지 않고 원천 Drop!
· 실행: df_final = df_transformed.iloc[12:]
· 최종 아웃풋 행수 보정: 65행 ➡️ 53행 (-12행 최종 절단)
· 유효 기간 보정: 2022-01-31 ~ 2026-05-31 (Look-Ahead Bias 0.00% 완전 청산 Zone)
```

---

## 4. 각 Phase별 처리 근거

### Phase 0: 왜 파생변수를 시차 적용 전에 계산하는가?

`credit_spread`(= `corporate_bond_3y_AA - treasury_bond_3y`)와 `liquidity_spread`(= `CP_91d - MSB_91d`)는 모두 Group A 금리 지표 간의 차이입니다. 이 지표들은 **동일한 월말 종가 인덱스**를 공유하므로, 시차(shift) 적용 전 원천 레벨 상태에서 계산해야 정확한 스프레드가 산출됩니다.

### Phase 1: 왜 시차 보정이 필요한가?

경제 지표의 **기준월(Reference Period)**과 **발표일(Release Date)**에는 시차가 존재합니다. 예를 들어, 3월 CPI는 4월에야 공표되므로 3월 시점에서 CPI를 사용하면 **아직 발표되지 않은 미래 정보를 사용하는 것**이 됩니다.

| 그룹 | 시차 (월 단위) | 근거 |
|---|---|---|
| Group A | 0행 (shift 없음) | 시장 종가는 당월 즉시 관찰 가능 |
| Group B | +1행 (1개월) | 통계청/한국은행 월간 지표는 기준월 이후 약 1개월 뒤 발표 |
| Group C | +2행 (2개월) | 분기/연간 지표는 기준 기간 이후 약 2개월 뒤 발표 |

시차 적용 후 발생한 NaN은 `ffill().bfill()`로 일괄 청산하여 원천 레벨 NaN 0개를 달성합니다.

### Phase 2: 월간 로그 수익률과 월간 내 변동성

#### 월간 로그 수익률 (`_log_ret`)
월말 종가 기준으로 전월 대비 로그 수익률을 산출합니다. **절대로 월평균(Mean) 값을 사용하지 않습니다** — 시장 쇼크 왜곡 방지.

| 변환 | 산출식 | 접미사 |
|---|---|---|
| 월간 로그 수익률 | `ln(당월_말일_종가 / 전월_말일_종가)` | `_log_ret` |

#### 월간 내 변동성 (`_vol_m`) — Realized Volatility
월별 레벨에서 단순 shift 표준편차를 구하면 **월간 내 발생한 불확실성 시그널이 소멸**됩니다. 따라서 일별 원천 데이터(`model_input_daily.csv`)에서 사전 집계합니다:

1. 일별 원천 데이터에서 각 변수의 일별 로그수익률 산출
2. YYYYMM 그룹별 `std(일별 로그수익률)` 산출
3. 스케일 매칭: `std * sqrt(20) * 100`

| 변환 | 산출식 | 접미사 |
|---|---|---|
| 월간 내 변동성 | `groupby(YYYYMM).std(일별 log_ret) * sqrt(20) * 100` | `_vol_m` |

### Phase 3: 왜 금리 지표는 YoY가 아닌 단순 차분(_diff12)을 사용하는가?

금리 지표(예: 기준금리, 국채 수익률)는 **제로 금리 국면**에서 1년 전 레벨 값이 `0.0`이 될 수 있으며, 이 경우 YoY 산출식의 분모가 0이 되어 **수치 폭발(ZeroDivision/Inf)**이 발생합니다. 따라서 금리류 지표 17개는 단순 차분(`col - col.shift(12)`)만을 적용합니다.

| 대상 | 변환 | 산출식 | 접미사 |
|---|---|---|---|
| 금리 지표 17개 | 단순 차분 | `V_t - V_{t-12}` | `_diff12` |
| 비금리 B+C 23개 | YoY 증감률 | `(V_t - V_{t-12}) / V_{t-12} * 100` | `_yoy` |

- `.shift(250)` / `.shift(365)` 절대 사용 금지 — 월별 인덱스에서는 `.shift(12)` 사용
- 분모 0 방지: `replace(0, 1e-6)` 적용

### Phase 4: 3개월 이동평균

| 변환 | 산출식 | 접미사 |
|---|---|---|
| 3개월 이동평균 | `mean(x, window=3)` | `_ma3m` |

- `_log_ret`, `_vol_m`, `_diff12`, `_yoy` 전체 86개 변수 대상
- 월별 노이즈를 제거하고 중기 추세를 포착
- 약 90일(≈ 3개월)에 해당하여 기존 일별 `_ma90d`와 동일한 시간 범위

### Phase 5: 왜 상위 12행을 bfill 없이 원천 절단하는가?

Phase 2~3에서 `.shift(12)` 연산의 초기 12행은 **계산 불가(NaN)**입니다. 이를 `bfill()`로 채우면 **미래 데이터를 과거로 역복사하는 치명적 데이터 누수**를 유발합니다. 따라서 `df.iloc[12:]`으로 해당 구간을 원천 삭제(Drop)하여 Look-Ahead Bias를 0.00%로 완전 청산합니다.

---

## 5. 최종 변수 구조 (정합성 락킹 완료)

| 접미사 | 의미 | 원천 그룹 | 생성 수 |
|---|---|---|---|
| `_log_ret` | 월간 로그 수익률 | Group A (비금리) | 23개 |
| `_vol_m` | 월간 내 변동성 (일별 원천 기반) | Group A (비금리) | 23개 |
| `_diff12` | 단순 차분 (12개월) | 금리 지표 전체 | 17개 |
| `_yoy` | 전년 동월 대비 증감률 | Group B + C (비금리) | 23개 |
| `_ma3m` | 3개월 이동평균 | 전체 변환 변수 (86개 × 1) | 86개 |
| **합계** | | | **172개 + date** |

> 사전 탈락한 3개 지표(GNI_annual 등)를 제외한 원천 63개 레벨 컬럼은 모두 삭제되고, 172개의 정상성 확보 변수셋으로 교체됩니다.

---

## 6. 최종 결과 요약

| 항목 | 값 |
|---|---|
| 입력 행수 | 65행 |
| 출력 행수 | **53행** (-12행 절단) |
| 입력 컬럼 | 64개 (date 제외) |
| 정제 후 컬럼 | 63개 (3개 사전 탈락, Phase 0 파생변수 선행 할당) |
| **최종 출력 컬럼** | **172개 + date = 173 cols** |
| 최종 NaN | **0개** |
| 유효 기간 | 2022-01-31 ~ 2026-05-31 (Look-Ahead Bias 0.00% 완전 청산 Zone) |
| Look-Ahead Bias | **완전 차단** (Phase 5: 상위 12행 원천 절단, bfill 미사용) |
| Stationarity | **확보** (레벨 제거, 수익률/YoY/차분/변동성 변환) |

### 최종 검증 Assert (스크립트 내장)

```python
assert df.isna().sum().sum() == 0,  "NaN 잔존"
assert len(df) == len(df_raw) - 12, "절단 행수 불일치"
```

---

## 7. 실행 방법

```bash
# 1. 월별 모델 입력 데이터 생성 (수집 생략, 기존 raw 데이터 사용)
.\.venv\Scripts\python.exe main.py --start-date 2021-01-01 --end-date 2026-05-17 --skip-collect --target-freq M

# 2. 결측치 정제 + 안정성 변환 파이프라인 실행
.\.venv\Scripts\python.exe api_data_processing\impute_data.py
```


