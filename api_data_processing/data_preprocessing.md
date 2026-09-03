# 🧹 데이터 전처리 및 결측치 정제(Imputation) 파이프라인

본 문서는 `model_input_monthly.csv`(월별 거시경제 및 금융 지표 통합 데이터)에 존재하는 결측치를 지표의 경제적/통계적 성격에 맞추어 정제하되, 신용평가 모형 개발 시 치명적인 **미래 기만 오류(Look-Ahead Bias)**를 원천 차단하기 위해 적용된 5단계 순차 처리 파이프라인을 정리한 문서입니다.

- **스크립트**: `api_data_processing/impute_data.py`
- **입력**: `api_data_processing/output/model_input/model_input_monthly.csv` (64개 지표, 65행)
- **출력**: `api_data_processing/output/model_input/model_input_monthly_cleaned.csv` (178개 변수, 65행, NaN 0개)
  - 종전 문서의 "172개 / 53행" 은 매핑 정정 이전 세대의 수치다. 정정 전 산출물도 이미 178개였으므로 개수를 바꾼 것은 이번 정정이 아니다 (2026-09-02 정정).
- **참조**: `api_data_processing/output/model_input/model_input_daily.csv` (Group A 변동성 집계용)

---

## 1. 결측치 발생 원인

서로 다른 발표 주기(Frequency)를 가진 64개의 지표를 월별(Monthly) 달력 기준으로 결합하는 과정에서 다음과 같은 이유로 결측치가 발생합니다:

- **발표 시점 차이(Publication Lag)**: 경제 지표의 기준월과 실제 발표 시점 사이의 시차로 인한 미래 누수 위험
- **분기/연간 데이터**: 발표 주기가 월별보다 낮은 지표의 공백 구간
- **시계열 시작점 불일치**: 일부 지표의 수집 시작 시점 차이

---

## 2. 지표 그룹 분류 (발표 시차 기반)

지표를 **발표 즉시성**에 따라 4개 그룹으로 분류하고, 그룹별로 서로 다른 시차 보정과 결측치 전략을 적용합니다.

### Group A: 금융 시장 지표 (t + 0, 즉시 공표) — 35개

| 카테고리 | 지표 |
|---|---|
| 국내 주가지수 | KOSPI, KOSDAQ |
| 해외 주가지수 | DowJones, NASDAQ, SP500, Nikkei225, Shanghai_Composite |
| 환율 | USD_KRW, EUR_KRW, JPY_KRW, CNY_KRW, DXY_dollar_index |
| 원자재 | brent_crude_oil, WTI_crude_oil, natural_gas, gold, silver, copper, corn, soybean |
| 변동성 | VIX |
| 일별 금리 | call_rate_overnight, call_rate_overnight_brokered, KORIBOR_3m/6m/12m, treasury_bond_1y/3y/5y/10y, corporate_bond_3y_AA, US_10Y_treasury, **US_3M_tbill**, CP_91d, MSB_91d |

- **시차 보정**: 없음 (당월 말일 종가 즉시 반영)
- **결측 전략**: **Forward Fill (LOCF)** — 공백은 직전 관측값 유지

### Group B: 실물 경제 및 물가 지표 (t + 1개월, 익월 공표) — 10개

| 카테고리 | 지표 |
|---|---|
| 물가 | CPI_core, CPI_core_excl_food_energy, CPI_food_nonalcohol, PPI_total, housing_price_index |
| 수출물가 | **export_price_index_KOR** (Group C 에서 이동) |
| 무역 | export_index, import_index |
| 월별 금리 | CD_rate_91d, treasury_bond_1y_monthly |

- **시차 보정**: **+1개월 Shift** (예: 3월 CPI → 4월에야 사용 가능)
- **결측 전략**: **Forward Fill (LOCF)** — 미래 데이터 누수(Look-Ahead Bias)를 차단하기 위해 선형 보간을 전면 금지하고 직전 공식 수치 유지

### Group C: 장기 거시 및 정책/심리 지표 (t + 2개월) — 17개

| 카테고리 | 지표 |
|---|---|
| 정책 금리 | base_rate |
| 통화량 | **M1_narrow_money, M2_broad_money, Lf_liquidity, monetary_base_sa** (Group B 에서 이동) |
| 국제수지 | **current_account, goods_balance** (Group B 에서 이동) |
| 심리 지수 | BSI_mfg_biz, BSI_mfg_export, BSI_mfg_domestic, BSI_nonmfg_biz, CSI_composite, CSI_living_prospect |
| KOSIS | unemployment_rate, construction_cost_index, unsold_housing |

> ※ GNI_annual, manufacturing_index 는 Phase 0 사전 드롭(`DROP_COLS`) 대상입니다.
> `export_price_index_KOR` 는 **드롭 해제**되었습니다 — 구 매핑(902Y015 주요국 경제성장률)이
> 연간이라 대량 결측이었으나, 정정 후 402Y014 수출물가지수(월별)이므로 사유가 소멸했습니다.
> `trade_total` 은 `enabled=N` 으로 드롭되었습니다 (정정 시 `import_index` 와 100% 중복).

- **시차 보정**: **+2개월 Shift** (예: 1분기 GDP → 5월에야 사용 가능)
- **결측 전략**: **Forward Fill (LOCF)** — 다음 발표 전까지 공식 수치 고정

### Group D: 분기 공표 지표 (t + 3개월) — 3개

| 카테고리 | 지표 |
|---|---|
| 가계 | **household_credit, household_loan** (Group C 에서 이동) |
| 국제수지 분기 | **current_account_quarterly** (Group C 에서 이동) |

- **시차 보정**: **+3개월 Shift**
- **결측 전략**: **Forward Fill (LOCF)** — 분기 사이 두 달은 직전 분기 값 유지

> ★ **분기 지표라는 사실 자체는 시점 누수 사유가 아니다.** 분기 지표는 (기업, 연도) 안에서
> 연 4회 변하고 `ffill` 은 **과거 값을 반복**하므로, `GNI_annual` 처럼 "연도 내 변동이 0 이
> 되는" 구조와 다르다. Group D 를 신설한 근거는 오직 **관측된 공표 지연 3개월**이다.
> 드롭하지 않고 시차만 늘린 이유도 같다 — 시차를 늘리면 look-ahead 는 해소되고 정보는 남는다.

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
│ Group B: +1개월 shift, Group C: +2개월 shift, Group D: +3개월 shift
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
│ (기본 변환 89개 + 이동평균 89개 = 총 178개 변수 빌드 완료)
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
| Group C | +2행 (2개월) | 기준 기간 이후 약 2개월 뒤 발표 (분기·연간 지표 및 공표 지연이 긴 월간 지표) |
| Group D | +3행 (3개월) | 실측 공표 지연이 3개월인 분기 지표 3건 |

#### 시차 근거 — ECOS 실데이터 최종 수록월 관측 (측정일 2026-09-01)

ECOS 통계표 메타에는 공표시점 필드가 없고(`STAT_CODE`/`STAT_NAME`/`CYCLE`/`SRCH_YN` 뿐),
한국은행 공표일정 페이지도 조회되지 않았다. 그래서 **각 지표의 실데이터 최종 수록월을
직접 관측**해 시차를 정했다. 추정이 아니라 측정이다.

**Group B(+1) → Group C(+2) 로 이동한 6건**

| 지표 | 이동 | 실데이터 최종월 | 경과 | 판정 근거 |
|---|---|---|---:|---|
| `current_account` (경상수지) | B → C | 2026-06 | 3개월 | 9/1 시점에 7월 값 미공표 → `shift(+1)` 은 존재하지 않는 값을 쓴다 |
| `goods_balance` (상품수지) | B → C | 2026-06 | 3개월 | 동일 (국제수지는 기준월 익익월 공표) |
| `M1_narrow_money` | B → C | 2026-06 | 3개월 | 161Y001 |
| `M2_broad_money` | B → C | 2026-06 | 3개월 | 161Y005 |
| `Lf_liquidity` | B → C | 2026-06 | 3개월 | 171Y003 |
| `monetary_base_sa` | B → C | 2026-06 | 3개월 | 102Y004 (매핑 미변경 — 정정 이전부터 있던 문제) |

**★ M1 / M2 / Lf 는 매핑 정정으로 통계표가 바뀌면서 지연이 길어진 케이스다.**
구 매핑(`104Y016` 예금은행 대출금 · `104Y014` 예금은행 총수신 · `722Y001` 기준금리)의
공표 지연이 짧았던 것은 **잘못된 계열을 보고 있었기 때문**이다. 지연이 늘어난 것이 아니라,
원래부터 통화량 지표의 공표 지연이 이만큼이었는데 다른 계열을 통화량이라고 부르고 있었다.

**Group C(+2) → Group D(+3) 로 이동한 3건 (2026-09-02)**

| 지표 | 이동 | 실데이터 최종월 | 경과 | 판정 근거 |
|---|---|---|---:|---|
| `household_credit` (가계신용) | C → D | 2026-06 | 3개월 | 151Y001. `+2` 는 t 월 값을 t+2 월에 쓰는데 실제 공표는 t+3 이다 → 1개월 look-ahead |
| `household_loan` (가계대출) | C → D | 2026-06 | 3개월 | 151Y001 (동일 통계표) |
| `current_account_quarterly` (경상수지 분기) | C → D | 2026-06 | 3개월 | 301Y013 |

- 근거는 **실데이터 최종월 관측(측정일 2026-09-01)** 이다. 세 건 모두 최종 2026-06 으로
  경과 3개월이었다. 2026-09-02 재측정에서도 동일했다.
- **드롭하지 않는다.** 시차만 +3 으로 늘리면 look-ahead 가 해소되고 정보는 남는다.
- 구현: `impute_data.GROUP_D_COLS` / `LAG_MONTHS_D = 3` / `data_collector.SHIFT_GROUP["D"] = 3`.
- 산출물 영향: `household_credit_yoy` · `household_loan_yoy` ·
  `current_account_quarterly_yoy` 와 각각의 `_ma3m` = **6개 컬럼의 값만** 1개월 뒤로 밀렸다.
  컬럼 집합과 총 개수(178)는 불변이며, `_yoy` 블록 안에서 세 컬럼의 **순서**만 뒤로 옮겨졌다
  (하류는 컬럼명으로 참조하므로 영향 없음).

**+1 이 안전한 대조군** (변경 없음)

| 지표 | 실데이터 최종월 | 경과 |
|---|---|---:|
| CPI 3종 · PPI_total · export_index · import_index · export_price_index_KOR | 2026-07 | 2개월 |
| housing_price_index · CD_rate_91d · treasury_bond_1y_monthly | 2026-08 | 1개월 |
| base_rate (Group C) | 2026-07 | 2개월 |
| BSI/CSI (Group C) | 2026-08 | 1개월 |

> ### ⚠ 측정일 의존성 경고
>
> 위 근거는 **2026-09-01 하루의 관측**이다. 공표 일정은 개편·지연으로 달라질 수 있으므로
> 이 표를 영구 사실로 취급하면 안 된다.
>
> 이를 일회성으로 두지 않기 위해 **수집 스크립트에 자동 관측을 내장했다**
> (`data_collector.check_publication_lag`). 수집할 때마다 지표별
> `수집일 − 실데이터 최종월` 격차를 기록하고, 그룹 배정과 어긋나면 경고를 남긴다.
> 기록 위치: `output/metadata/collected_series_meta.json` 의 `publication_lag_months`.

#### 가드 임계 조정 — `lag > shift + 1` → `lag > shift` (2026-09-02)

구 임계는 **경과월이 시차보다 정확히 1개월 큰 경계선을 통과시켰다.** 그 경계선이 곧
1개월 look-ahead 다. 분기 3건이 Group C(+2) 에 경과 3개월로 앉아 있던 것을 구 임계가
놓친 것이 그 증거다. 경계선은 통과가 아니라 경고여야 한다.

조정 후 **전 지표(enabled=Y 65개)를 재검사**했다
(`api_data_processing/audit_publication_lag.py`, 리포트
`eda_pipeline/output/validation/PUBLICATION_LAG_AUDIT.md`).

| 그룹 | 대상 | 걸림 | 새로 걸린 지표 |
|---|---:|---:|---|
| A (+0) | 35 | 0 | — |
| B (+1) | 10 | **7** | CPI_core, CPI_core_excl_food_energy, CPI_food_nonalcohol, PPI_total, export_price_index_KOR, export_index, import_index |
| C (+2) | 17 | **8** | M1_narrow_money, M2_broad_money, Lf_liquidity, monetary_base_sa, current_account, goods_balance, unsold_housing, construction_cost_index |
| D (+3) | 3 | 0 | — (이번 이동으로 해소) |

- 15건 **전부** `경과 = 시차 + 1` 인 경계선 사례다. 구 임계에서 통과하던 것이 그대로 드러났다.
- **시차를 더 늘리지 않았다.** 아래 한계 때문에 관측 하루치로 판단할 사안이 아니다.

> ### ⚠ 측정일이 월초라는 점을 함께 봐야 한다
>
> 월간 통계는 보통 **익월 중순** 공표다. 8월 CPI가 9월 중순에 나온다면,
> 9월 1~2일에 재면 최신 수록월이 7월이라 경과가 2개월로 잡힌다. 그러나 `shift(+1)` 이
> 묻는 것은 "**8월 값을 9월 안에 쓸 수 있는가**" 이고, 9월 중순 공표라면 답은 예다.
> 즉 15건은 "월 단위로는 맞고 **월초 며칠은 아직 아니다**" 인 사례일 수 있다.
>
> 2026-09-01 과 2026-09-02 두 날 모두 같은 결과였다 (하루 차이로는 갈리지 않았다).
> 판단하려면 **공표일까지 관측한 뒤** 결정해야 한다. 이 문서는 관측값만 남긴다.
> Group D 3건은 다르다 — 분기 지표의 경과 3개월은 월초 효과로 설명되지 않는다.

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
| `_yoy` | 전년 동월 대비 증감률 | Group B + C + D (비금리) | 26개 |
| `_ma3m` | 3개월 이동평균 | 전체 변환 변수 (86개 × 1) | 86개 |
| **합계** | | | **178개 + BASE_YM** |

> 사전 드롭(`DROP_COLS` = GNI_annual, manufacturing_index)을 제외한 원천 63개 레벨 컬럼은 모두 삭제되고, 178개의 정상성 확보 변수셋으로 교체됩니다.
> 내역: `_log_ret` 23 + `_vol_m` 23 + `_diff12` 17 + `_yoy` 26 = 기본 89, 여기에 `_ma3m` 89 를 더해 178.

---

## 6. 최종 결과 요약

| 항목 | 값 |
|---|---|
| 입력 행수 | 65행 |
| 출력 행수 | **53행** (-12행 절단) |
| 입력 컬럼 | 64개 (date 제외) |
| 정제 후 컬럼 | 63개 (3개 사전 탈락, Phase 0 파생변수 선행 할당) |
| **최종 출력 컬럼** | **178개 + BASE_YM = 179 cols** |
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

---

## 재현 방법 (2026-09-02 확정)

**모든 실행을 하나의 가상환경으로 통일한다.** 거시 재수집·`impute_data` 를 시스템
파이썬으로, 학습을 venv 로 돌리면 두 pandas 세대가 한 파이프라인에 섞인다.

| 항목 | 값 |
|---|---|
| 인터프리터 | `C:/Users/scudy/.venvs/nh_eco/Scripts/python.exe` |
| Python | 3.14.3 |
| pandas | 3.0.5 |
| numpy | 2.5.2 |
| scipy | 1.18.1 |
| scikit-learn | 1.9.0 |
| lightgbm | 4.7.0 |
| duckdb | 1.5.5 |
| parquet 엔진 | **없음** (pyarrow·fastparquet 미설치). parquet 읽기·쓰기는 duckdb 로 한다 |

```bash
# 수집 -> 정제 -> 패널 결합 -> D축. 전부 같은 인터프리터로.
PY="C:/Users/scudy/.venvs/nh_eco/Scripts/python.exe"
$PY -m api_data_processing.collect_macro --transform      # 수집 (API 키는 .env)
$PY -m api_data_processing.impute_data                    # Phase 0~6
$PY -m api_data_processing.audit_publication_lag          # 공표 지연 전수 재검사
$PY -m eda_pipeline.step6_macro_integration --spine obv --segment none --tag real
$PY -m eda_pipeline.step34_d_axis --run D0 D1 D3 D6 D6m --seeds 42,7,2024
```

> **주의**: 시스템 파이썬(`C:/Users/scudy/AppData/Local/Programs/Python/Python314`)은
> pandas 2.3.3 / numpy 2.4.4 이고 **lightgbm·scikit-learn·scipy 가 없다.**
> 학습 단계는 애초에 시스템 파이썬으로 돌아가지 않는다.

### pandas 2.3.3 ↔ 3.0.5 교차 검증 (2026-09-02)

두 인터프리터에서 같은 파일을 읽어 `shape` / 컬럼 순서 / 컬럼별 `dtype` ·
결측수 · `sum` · `min` · `max` (범주형은 고유값 전수)를 대조했다.

| 파일 | shape | 값 불일치 | dtype 불일치 |
|---|---|---:|---|
| `model_input_monthly_cleaned.csv` | 65 × 179 (동일) | **0** | 0 |
| `model_input_monthly_level.csv` | 65 × 14 (동일) | **0** | 1 (`date`: `str` ↔ `object`) |
| `nh_panel_macro_12m_obv_none_real.parquet` | 948,214 × 267 (동일) | **0** | 10 (전부 문자열 컬럼) |
| `nh_panel_B46_asof.parquet` | 948,214 × 173 (동일) | **0** | 8 (전부 문자열 컬럼) |

- **값과 결측 수, 범주형 고유값은 전부 일치한다.** 조용한 데이터 손상은 없다.
- 차이는 문자열 dtype 표기뿐이다 — pandas 3.0 은 새 기본값 `str`, 2.3.3 은 `object` 로
  보고한다. `exp_fx_industry_level` · `exp_fx_source` · `STD_INDS_SECTION` ·
  `STD_INDS_MID2` 도 고유값이 완전히 같다. 학습 코드는 이들을 `astype("category")` 로
  변환해 쓰므로 표기 차이가 모델에 전달되지 않는다.
- 검증 스크립트: 세션 스크래치패드의 `fingerprint.py` (두 인터프리터에서 지문 JSON 생성 후 대조).
