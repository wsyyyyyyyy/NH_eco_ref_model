# [Step 24] 실제 레거시 부도확률(RZVL_POD) 및 실제 부도일자(DSH_DT) 반영

> **작성일**: 2026-07-04
> **기준**: 사용자가 "기존 모델 비교를 은행 실제 산출 부도확률(RZVL_POD)로 해야 하지 않냐"고 지적, 원본 데이터를 재확인해 반영

---

## 1. 배경

PD-LAG/벤다이어그램에서 "기존 모델"로 써 온 `PROB_FULL * 0.15`는 실제 레거시 모형 산출물이 없어 만든 근사치였음. 사용자가 데이터 명세에 `POD/RZVL_POD`(은행 모형 산출 부도확률, 0.0~1.0) 필드가 있다고 지적하여 원본 데이터를 재조사.

## 2. 조사 결과

- `eda_pipeline/step5_panel_prep.py:104`에서 병합 데이터셋의 `OBV_RZVL_POD` 컬럼을 모델링 패널 생성 시 명시적으로 drop해온 것을 확인 — 학습 피처 누출/편향 방지 목적(사용자 확인: "학습할 때 들어가면 편향될 수 있어 제거"). 그 결과 서비스 중인 `portal.duckdb`에는 이 필드가 없었음.
- 사용자가 원본 데이터 위치(`Downloads/eco_ref_model_repo/input/`, `Downloads/eco_ref_model-main/.../nh_data_processing/output/`)를 제공, 두 개의 독립된 소스(raw txt, `nh_credit_risk.db`, CSV export)에서 `RZVL_POD` 실측값을 확인.
- **중요 발견**: `RZVL_POD`는 **2021.01~2021.11(11개월)에만 실제 값이 있고, 2021.12부터 2025.12까지 55개월은 원본 추출 자체에서 전부 0.0으로 고정**되어 있음(제 조인 실수가 아니라 원본 데이터 한계, 두 소스에서 동일하게 확인). 따라서 최근월 PD-LAG 차트에는 사용할 수 없음 — 대신 유효한 11개월 구간(14.7만 건)에서 실측 레거시 성능을 계산해 모델 모니터링 벤치마크로 사용.
- 사용자가 언급한 `OBV_DTL_GRD`(1~10등급) 필드는 원본 데이터(raw txt, `nh_credit_risk.db`, `nh_data_processing/output/` 11개 CSV, 도메인 코드사전) 전체를 검색했으나 **존재하지 않음**을 확인. 도메인 코드사전에 `ELYWRN_OBV_GRD_DSC`의 공식 명칭이 "관찰B등급판정기준코드"로 명시되어 있어, 처음부터 A/B 이진 판정 코드였음이 확인됨(벤다이어그램에 이미 정확히 사용 중이었음).
- 부가 발견: `04_당행부도정보_BUDO_CUST.csv`에 **실제 부도일자(`DSH_DT`)** 원장이 존재. 지금까지 벤다이어그램의 "부도 시점"은 `IS_BUDO_12M` 타겟플래그가 마지막으로 1인 월로 근사 추정했는데, 이 파일로 정확한 날짜 기준 계산이 가능해짐.

## 3. 조치

### 데이터 (`database/portal.duckdb`)
- 수정 전 전체 백업(`portal.duckdb.bak`, gitignore 대상) 생성.
- `corporate_panel`에 컬럼 2개 추가:
  - `RZVL_POD DOUBLE`: 2021.01~11만 실측값(0~1 스케일), 그 이후는 NULL(원본이 0으로 고정된 구간을 "레거시가 0% 예측"으로 오인시키지 않기 위해 결측 처리).
  - `DSH_DT VARCHAR`: 회사별 최초 부도일자(`04_당행부도정보_BUDO_CUST.csv`, 여러 부도/정상화 이력이 있는 회사는 `MIN(DSH_DT)` 사용).

### 백엔드 (`backend/routers/dashboard.py`)
- `/api/dashboard/prediction_comparison`: 부도 시점(`default_pivot`)을 실제 `DSH_DT`(있으면 우선) 또는 기존 근사치(없으면 폴백)로 재계산.
  - 결과 변화: 둘 다 포착 386→**409**, ERM만 포착 580→**556**, 평균 리드타임 +9.2개월(73개사)→**+12.9개월(96개사)**. 정밀도가 오르면서 ERM의 조기경보 우위가 오히려 더 뚜렷해짐.
  - 응답에 `real_default_date_cnt` 필드 추가(972개사 전원이 실제 날짜로 계산됨 — `IS_BUDO_12M` 타겟이 원래 이 부도 원장에서 파생되었을 가능성을 시사, 데이터 정합성 재확인).

### 프론트엔드 (`frontend/src/pages/ModelMonitoring.tsx`)
- `LEGACY_BENCHMARK`를 추정치(`0.81/0.62/0.42`, 출처 불명확)에서 **실측치(`0.823/0.646/0.499`, 2021.01~11 구간 14.7만 건 기준 AUROC/Gini/K-S 직접 계산)**로 교체.
- 차트 범례 및 안내 문구에 "2021.01~11 실측" 출처 명시.

### 공유용 목업 (`mockup.html`)
- 벤다이어그램·모니터링 벤치마크 하드코딩 값을 위 실측치와 동일하게 갱신.

## 4. 검증

- 두 개의 독립된 원본 소스(txt 파일, `nh_credit_risk.db`)에서 `RZVL_POD`의 월별 분포가 동일함을 확인(2021.12부터 0.0 고정) — 파싱 버그가 아님을 검증.
- `RZVL_POD` vs `ELYWRN_OBV_GRD_DSC`(같은 원장, 겹치는 행)에서 등급값 불일치 0건 — 조인 키 로직 정확성 확인.
- 실측 레거시 vs ERM 동일기간(2021.01~11) 비교: 레거시 AUROC 0.823 vs ERM 0.993(단, 이 시기는 학습구간에 가까워 낙관적일 수 있음 — 공식 Out-of-Time 검증치 0.901이 더 보수적 기준).
- 백엔드 API 직접 호출, `npx tsc --noEmit`, Playwright로 글로벌 뱅크 뷰/모델 모니터링/목업 3곳 모두 실렌더링 확인, 콘솔 에러 0건.

## 5. 사각지대 판정 로직을 실제 등급 기준으로 교체

`NICE_GRADE_CUR/PREV`, `KIS_GRADE_CUR/PREV`, `OLD_PROB`이 전부 `prob_to_grade(PROB_FULL * 0.15)`로 산출된다는 것(`backend/routers/borrowers.py`)을 확인 — 즉 진짜 외부 신용평가 데이터가 아니라 ERM 자체 확률을 등급 라벨만 바꿔 표시한 것. 사용자 확인: "기존 모델 = 신용평가 점수를 낮춘 경우로 이해해야겠다."

- **"부도로 예측했다"는 판정(분류) 질문**은 `ELYWRN_OBV_GRD_DSC`('A'/'B')로 66개월 전체 결측 없이 답할 수 있음 — 55개월 유실 문제는 `RZVL_POD`처럼 **확률 수치**가 필요한 경우에만 해당되고, 이진 판정에는 해당하지 않음.
- 이에 따라 가짜 기준(`OLD_PROB`)으로 돌아가던 "사각지대" 판정 3곳을 실제 등급 기준으로 교체:
  - `backend/routers/monitoring.py`의 `/api/monitoring/borrowers`: `is_blind_spot`을 `old_grade in (...)` → `OBV_ELYWRN_OBV_GRD_DSC == 'A'`로 교체, 쿼리에 해당 컬럼 추가.
  - `backend/routers/borrowers.py`의 `/api/borrowers/`(목록): 응답에 `OBV_ELYWRN_OBV_GRD_DSC` 추가.
  - `frontend/src/pages/BranchDashboard.tsx`의 `checkIsBlindSpot`: `PROB_FULL >= 0.25 && OLD_PROB <= 0.06` → `PROB_FULL >= 0.25 && OBV_ELYWRN_OBV_GRD_DSC === 'A'`.
  - `frontend/src/pages/BorrowerDetail.tsx`의 `isExistingHighRisk`: **버그 발견** — `['G4','G5'].includes(data.Z_GRADE)`로 되어 있었는데 `Z_GRADE`는 ERM 자체 등급이라 ERM을 ERM과 비교하는 셈이었음. `data.OBV_ELYWRN_OBV_GRD_DSC === 'B'`로 교체.

### 회귀 버그 발견 및 수정
`corporate_panel`에 추가한 `RZVL_POD`(대부분 NULL)를 `get_borrower_detail`이 `SELECT * → pandas.to_dict()`로 그대로 반환하면서, pandas가 NULL을 `float('nan')`으로 변환해 `json.dumps`가 `ValueError: Out of range float values are not JSON compliant: nan`로 터지는 회귀가 발생(대부분의 차주 상세 조회가 500 에러). `record`의 NaN 값을 `None`으로 치환하는 sanitize 로직 추가로 수정.

## 6. 검증 (사각지대 판정 교체분)

- `/api/borrowers/1000018057?base_ym=202402` 등 실제 500 에러였던 요청이 정상 200 응답으로 복구됨을 확인.
- Playwright로 지점 대시보드(사각지대 배지) 및 차주 상세("잠재 리스크 감지" 박스) 재렌더링, 콘솔 에러 0건.
- 실제로 발견된 예시: PROB_FULL 93%(G5)인데 `OBV_ELYWRN_OBV_GRD_DSC='A'`(내부적으로 "안전"), `DSH_DT` 확인 결과 실제로 4개월 뒤 부도 — 완전히 실데이터 기반의 사각지대 사례.

## 7. PD-LAG 차트 삭제

"기존 모델"이 항상 `PROB_FULL * 0.15`(우리 모델을 축소한 값)로 계산되는 한, ERM이 항상 압도적으로 높게 나오는 구조라 이 비교 자체가 무의미하다고 판단 — 사용자 확인 후 글로벌 뱅크 뷰의 "실질 부도율 vs 모델 예측력 비교 (PD-LAG)" 차트를 완전히 삭제.

- `frontend/src/pages/GlobalDashboard.tsx`: PD-LAG 차트 및 연동된 `trendData` state, `/api/dashboard/trend` fetch effect, `TrendTooltip` 컴포넌트, `lineChartData`/`censoredMonths`/`firstCensoredMonth`/`lastMonth` 파생값, 미사용 recharts import(`LineChart`, `Line`, `ReferenceArea`, `Legend`) 전부 제거. 업종별 리스크 매트릭스는 그대로 유지하되 전체 폭으로 확장(빈 공간 방지).
- `backend/routers/dashboard.py`: 더 이상 호출되지 않는 `GET /api/dashboard/trend` 엔드포인트 삭제.
- `mockup.html`: 동일하게 PD-LAG 섹션 삭제, 업종별 매트릭스 전체 폭 확장.
- 편집 과정에서 JSX `<div>` 닫는 태그 개수가 한 개 어긋나 Vite 빌드가 500 에러를 내는 실수가 있었음 — 스크립트로 div 중첩 깊이를 라인별로 추적해 정확한 위치를 찾아 수정.

### 검증
- `npx tsc --noEmit` 통과, Playwright로 글로벌 뱅크 뷰 재렌더링(콘솔 에러/네트워크 4xx·5xx 0건), `mockup.html`도 동일하게 확인.

## 8. 등급하향(A→B) 시점 vs 실제 부도일자 검증

사용자 요청: "A→B 등급 변화가 실제 부도가 났을 때 바뀐 건지 확인해달라, 등급변화 시기와 부도일자를 비교하면 모델 성능 검증에도 좋을 것 같다."

`DSH_DT`(실제 부도일자)와 진짜 A→B 전환(`first_a_ym < first_b_ym`)이 모두 있는 304개사를 비교:

| 구분 | 건수 | 비중 |
|---|---|---|
| **부도 이후에 등급하향 (뒤늦음)** | 208건 | **68.4%** |
| 부도와 같은 달 | 24건 | 7.9% |
| 1~3개월 전 | 9건 | 3.0% |
| 4~6개월 전 | 5건 | 1.6% |
| 7~12개월 전 | 11건 | 3.6% |
| 12개월 초과 전 | 47건 | 15.5% |

중앙값 기준 **내부등급은 부도 발생 2개월 후에야 B로 바뀜** — 내부등급 하향의 대다수(68.4%)는 조기경보가 아니라 부도가 이미 발생한 뒤 사후적으로 반영되는 지표였음. 이는 벤다이어그램의 리드타임(+12.9개월, 96개사)이 애초에 "진짜로 부도 전에 등급이 떨어진" 소수 사례만 필터링한 결과였음을 재확인시켜주는 동시에, ERM의 조기경보 가치를 뒷받침하는 근거가 됨.

### 조치
- `backend/routers/dashboard.py`의 `/api/dashboard/prediction_comparison`에 `grade_lag` 필드 추가(`total`, `after_default_cnt`, `after_default_pct`, `median_lead_months`) — 위 SQL을 실시간 계산.
- `frontend/src/pages/GlobalDashboard.tsx`의 `PredictionVenn`에 "등급하향의 사후 반영 비율" 통계 박스 및 각주 문장 추가.
- `mockup.html`에도 동일 반영.

### 검증
- 백엔드 응답(`grade_lag.after_default_pct: 68.4`)이 Python 분석 스크립트 결과와 정확히 일치.
- `npx tsc --noEmit` 통과, Playwright로 3단 통계 박스 줄바꿈 확인(처음엔 카드 폭을 넘어가 잘리는 문제가 있어 `flexWrap` 추가로 수정), 콘솔 에러 0건.

### 추가 확인: 사후 등급변경이 "둘 다 포착"에 잘못 섞이지 않는지 검증
사용자 질문: "사후에 등급을 변경한 건 예측하지 못했다로 표시하는 게 맞지 않냐?" — `internal_warn`이 `BASE_YM <= default_pivot` 조건으로 이미 제한되어 있어, 부도 이후에만 B로 바뀐 208개사는 부도 시점 이전엔 B등급 이력이 아예 없으므로 `internal_warn`이 NULL이 되어 애초에 "둘 다 포착"에 들어갈 수 없는 구조임을 SQL로 직접 검증(208개사 전원이 `erm_only`로 집계, `both`는 0). 즉 기존 로직 자체는 이미 정확했음 — 다만 각주만으로는 이 사실이 드러나지 않아 오해 소지가 있어, "이 208개사는 부도 시점 이전엔 B등급이 존재하지 않아 '둘 다 포착'이 아닌 'ERM만 포착'으로 이미 집계됩니다"라는 문장을 각주에 추가해 명확히 함.

## 9. 거시경제(환율) 민감도 차주 분석 (일회성, 포털 미반영)

전체 26,184개사에 대해 SHAP으로 환율 관련 피처(USD/EUR/JPY/CNY_KRW 수익률·변동성, 달러인덱스, 총 20개 피처) 기여도를 계산(기준월 202606, 계산 시간 약 11초). 상위 20개사 전부 환율 요인이 리스크를 증가시키는 방향으로 작용 중이며, 업종 분포는 도매및소매업 8개사, 제조업 6개사, 정보통신업 3개사 순. 사용자 확인에 따라 이번엔 포털 기능화하지 않고 분석 결과만 기록 — 필요 시 `GET /api/monitoring/fx_sensitivity` 같은 엔드포인트로 후속 개발 가능.

## 10. 후속 과제

- `PROB_FULL * 0.15` 근사치는 업종별 매트릭스 X축("기존 평가 위험도")과 `NICE_GRADE_*`/`KIS_GRADE_*` 등급 숫자 표시에는 여전히 남아있음 — `RZVL_POD`가 최근월 구간에 데이터가 없어 대체 불가. 제거할지 근사치임을 더 명확히 라벨링할지는 미결정(사용자 확인 필요).
- 환율 민감도 차주 분석을 포털 UI 기능으로 만드는 것은 보류 상태.
