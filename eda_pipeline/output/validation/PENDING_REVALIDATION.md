# 매핑 오류 영향 범위 — STAGE 6 이후 재검증 대상

JEMU 계정 코드 매핑이 `118100` 부터 한 칸씩 밀려 있었다.
`input/가상사업자_JEMU_재무데이터v.txt` 0행(한글 논리명)이 정본이며,
28개 중 21개 라벨이 어긋나 있었다 (예: `191204` 를 "ROE" 로, `191208` 을 "매출채권회전율" 로).

표시 라벨뿐 아니라 `backend/routers/borrowers.py` 의 **실제 데이터 매핑**도 같은 오류를
갖고 있어, 포털 차주 상세 화면이 잘못된 값을 표시하고 있었다.

| # | 대상 | 상태 | 비고 |
|---|---|---|---|
| 1 | 포털 차주 상세 재무 요약 4개 값 | 확인 전 | 수정 완료, 재확인 필요 (capital/revenue/operating_profit) |
| 2 | 포털 레이더 차트 11개 축 | 확인 전 | 수정 완료 (10축 정정 + 1축 제거 -> 10축) |
| 3 | README.md 포털 관련 지표 | 확인 전 | |
| 4 | MODEL_EVALUATION_REPORT.md | 확인 전 | |
| 5 | docs/ 산출물 (step01~step29 중 JEMU 라벨 인용 문서) | 확인 전 | |
| 6 | eda_report.html 및 플롯 8종 | 확인 전 | |

문서 파일 자체는 아직 수정하지 않았다. STAGE 6 이후 위 항목을 하나씩 확인하고
상태를 "영향 있음" / "영향 없음" 으로 갱신한다.

## STAGE 6 선행 필수

- `portal.duckdb` 를 새 패널 스키마로 재빌드한다 (`JEMU_191506_val` 등 신규 컬럼).
- `database/db_migration.py` / `database/init_duckdb.py` 를 갱신한다.
- 재빌드 전까지 backend 는 구 스키마 기준으로만 동작하며, 레이더 SQL 은
  `Binder Error: column JEMU_191506_val not found` 가 예상된다. **정상이다.**
- 재빌드 시 기존 `portal.duckdb` 를 덮어쓰지 말고 **`portal_v2.duckdb`** 로 생성한다.

현재는 코드만 새 컬럼명 기준으로 맞춰 두었고, 실행 검증은 STAGE 6 에서 한다.

## 레이더 축 최종 구성 (STAGE 5 시점)

| 그룹 | 축 | 참조 |
|---|---|---|
| 활동성 | pr_asset_turnover / pr_receivable_turnover / pr_inventory_turnover | 191506_val / 191502_val / 191505_val |
| 수익성 | pr_op_margin / pr_roe | 191204_val / 191208_val |
| 안정성 | pr_debt_ratio_inv / pr_current_ratio / pr_interest_coverage | -JEMU_debt_ratio / JEMU_current_ratio / 191207_val |
| 성장성 | pr_revenue_growth | 191104_val |
| 규모 | pr_assets | JEMU_115000 |

축 개수·구성 최적화는 STAGE 6 에서 SHAP 상위 변수가 확정된 뒤 재설계한다.

## 거시 데이터 재현성 결함 (STAGE 5 발견)

`api_data_processing/output/model_input/model_input_monthly_cleaned.csv` 가 존재하지 않는다.
`api_data_processing/` 에는 `assign_virtual_branch.py` 하나뿐이고 **거시 데이터 수집
스크립트가 레포에 없다.**

- `.gitignore:29` 에 `*.csv` 가 있어 커밋 대상에서 제외되어 있다.
  (커밋된 적이 없는 것이 아니라, 로컬 산출물로만 존재했고 gitignore 로 빠진 것이다.
   `portal.duckdb`, `nh_panel_full.csv` 와 같은 경우다.)
- 상위 폴더(`sy/NH AI경진대회/`) 전체를 탐색했으나 거시 CSV 는 발견되지 않았다.
  거시 변수명이 남아 있는 곳은 `lgbm_12m_model.txt` / `lgbm_12m_lean_model.txt` 뿐이다.

**거시 데이터의 출처·수집일·산출 로직이 현재 재현 불가능하다.**
프로젝트 재현성 측면에서 중대한 결함이며, 아래가 필요하다.

| # | 필요 조치 | 상태 |
|---|---|---|
| 7 | 거시 데이터 수집 스크립트 복원 또는 재작성 | **진행 중** — `api_data_processing/collect_macro.py` 신규 작성 (2026-08-30). 수집/변환 2단계 분리, 원시는 `raw/` 에 수집일 박아 저장. yfinance 21개 READY / ECOS 40개는 통계표코드 확인 필요 / 파생 2개 미해결 |
| 8 | `model_input_monthly_cleaned.csv` 원본 확보 | **미확보** — 재수집으로 대체한다. 7번 완료 시 `--transform` 으로 생성 |
| 9 | 거시 172개 변수의 정의·출처·산출식 문서화 | **완료(역파싱분)** — `eda_pipeline/output/macro_respec_from_model.json`. 172개 = 원지표 63개 x 변환 2~4종. 변환 정의는 `collect_macro.transform()` docstring |

### 7번 잔여 작업

| 항목 | 개수 | 막힌 이유 |
|---|---:|---|
| yfinance | 21 | 없음. 바로 수집 가능 |
| ECOS | 40 | 통계표코드/항목코드 미확인. 통계목록 API 로 조회해 채울 것. 추측값을 코드에 넣지 않았다 |
| 파생 (`credit_spread`, `liquidity_spread`) | 2 | 어느 두 금리의 차인지 산출식이 문서에 없다 |

추가 확인 필요 2건: `treasury_bond_1y` vs `treasury_bond_1y_monthly`,
`current_account` vs `current_account_quarterly` 의 차이.

STAGE 5 의 5-2 / 5-4 / 5-5 는 합성 거시 프레임으로 로직만 검증했다.
합성 프레임 생성 규칙: `lgbm_12m_model.txt` 에서 거시 변수 172개 이름을 추출,
BASE_YM 202101~202505(53개월), `numpy.random.default_rng(20260829)` 고정 시드.
파일명은 `macro_SYNTHETIC_DO_NOT_USE_FOR_TRAINING.csv` 이며 **학습에 사용 금지**다.

### 5-3 업종별 거시 민감도 — STAGE 6 보류

`STD_INDS_CFC` 대분류 x 주요 거시지표의 Train 구간 민감도 계수 산출은
거시 실데이터가 없으면 불가능하다. 거시 파일 확보 후 STAGE 6 에서 착수한다.

| # | 필요 조치 | 상태 |
|---|---|---|
| 10 | 5-3 업종별 거시 민감도 계수 산출 (거시 실데이터 필요) | 보류 |

## STAGE 6 선행 작업 목록 (확정)

| # | 작업 | 비고 |
|---|---|---|
| 1 | `portal.duckdb` 를 새 패널 스키마로 재빌드 | **`portal_v2.duckdb`** 로 생성. 기존 파일 덮어쓰지 말 것 |
| 2 | `db_migration.py` / `init_duckdb.py` 갱신 | Parquet 직접 읽기 가능 |
| 3 | `step7_modeling_shap.py` 경로를 `config.read_panel()` 로 전환 | 현재 구 파일명 `nh_panel_macro_12m.csv` 를 봄 |
| 4 | `validation_common.py` 하드코딩 절대경로 4건 정리 | `C:/Users/User/model_kbm/...` — 다른 계정 경로라 이 PC에서 동작 불가 |
| 5 | `step7` 피처 선정 로직 수정 | 현재 `ignore_cols` 4개뿐. `LEAK_CONFIRMED` + `NON_FEATURE` 제외 적용 필요 |
| 6 | `step7` early stopping 이 Valid 를 보지 않도록 Dev셋 사용 확인 | |

`step8`~`step15` 의 `.gemini/antigravity/brain` 경로 2건은 이번 리팩터링 범위 밖이다.
**건드리지 않고 목록에만 기록한다.**

## STAGE 5 에서 발견한 -1 잔재 (조치 대기)

`STD_INDS_CFC` 의 유효하지 않은 813행은 `-1` 765건 / `0` 34건 / `25` 14건이었다.
`-1` 은 step5 의 범주형 결측 대체값이다.

전수 점검 결과, **`CG01_KIS_SCORE` 140,419행(14.81%)이 `-1`** 이다.
`step1_load.py:345` 의 `fillna(-1).astype(int)` 때문이며, 이는 '평가 이력 없음'을
실제 점수 -1 로 만든 것이다. STAGE 3 에서 이 변수를 '유형 3(진짜 결측) → NaN 유지' 로
처리했으나, step1 에서 이미 -1 로 채워져 NaN 이 존재하지 않아 그 처리가 무효였다.
`CG01_KIS_SCORE` 는 기존 모델 gain 2위(14.5%)이므로 영향이 크다. **조치 승인 대기.**

`JEMU_pl_turn_dir`(-1 = 흑자→적자), `_val` 계열, `AA17_YOY_*`(-100%) 의 -1 은
실제 값이므로 조치 대상이 아니다.

## STAGE 6 시나리오 — 중요도 아티팩트 분리 검증 (제안 58)

`CG01_KIS_SCORE` 의 기존 모델 gain 14.51% 에는 성격이 다른 두 원인이 섞여 있을 수 있다.

- **(a) 시점 누수** — 연 단위 조인으로 최종재무평점_2021 이 2021년 1월에 붙는다.
- **(b) 인위적 극단값** — `-1` 이 14.81% 였다. 사실상 "평가 이력 없음" 이진 신호가
  점수 축의 극단값 형태로 들어가 있었다.

(a)는 제거해야 할 누수이고, (b)는 정당한 신호를 잘못된 형태로 담고 있던 것이다.
STAGE 5 에서 `-1` 을 NaN + `CG01_MISSING_YN` 으로 바꿨으므로 (b)는 올바른 형태로 살아난다.

| 시나리오 | 구성 | 해석 |
|---|---|---|
| S2a | `CG01_KIS_SCORE` 제거 (기존 S2) | 기준 |
| S2b | 유지 + `-1` → NaN/MISSING_YN 전환만 적용 | gain 급락 시 = 기존 중요도는 `-1` 아티팩트 |
| S2c | `CG01_MISSING_YN` 만 유지, 점수 자체는 제거 | S2b 와 비슷하면 = "평가 이력 유무" 가 신호 |

세 버전의 AUC 와 해당 변수군 gain 을 비교한다.
**동일 분석을 `C302_CRI_ORD` 에도 적용한다** (같은 `-1` 대체 대상이었다).

이 비교 결과는 STAGE 7 최종 보고서에 별도 섹션으로 넣는다.
"중요 변수의 높은 중요도가 실제 신호인지 전처리 아티팩트인지 분리 검증" 은
방법론적 엄밀성을 보여주는 소재다.


---

# STAGE 6 선행작업 — 처리 완료 (2026-08-30)

`STAGE6_PREFLIGHT.md` / `step30_scenario_plan.md` 참조.

| # | 작업 | 상태 |
|---|---|---|
| 1 | `portal_v2.duckdb` 재빌드 | 완료. 948,214행 / 268컬럼. `portal.duckdb` 는 부재했고 손대지 않음 |
| 2 | `db_migration.py` / `init_duckdb.py` 갱신 | 대체. 구 스크립트는 `os.remove(portal.duckdb)` 를 하므로 STAGE 6 경로에서 제외하고 `database/build_portal_v2.py` 신규 작성 |
| 3 | `step7` 경로를 `config.read_panel()` 로 | 완료 |
| 4 | `validation_common.py` 하드코딩 절대경로 4건 | 완료. 전부 config 경유, DB 연결은 예외 없이 `read_only=True` |
| 5 | `step7` 피처 선정 로직 | 완료. `leaky_cols.feature_columns()` 단일 경로 + assert |
| 6 | `step7` early stopping Dev셋 | 완료. `eval_set=[(X_dev, y_dev)]` |

## 새로 드러난 것

**LEAK_CONFIRMED 10개가 `portal_v2.duckdb` 에 없다.** step5 가 떨어뜨렸다.
assert 는 통과하지만 "제외했다"가 아니라 "들어온 적이 없다"는 뜻이다.
Ablation A1/A2(누수 변수 되넣기)는 step5 이전 산출물
`nh_panel_full_obv.parquet` 에서 조인해 복원한다 (매칭률 100.0000%).

**`CG01_MISSING_YN` / `C302_MISSING_YN` 이 `LEAK_SUSPECT` 에 없어 기본 피처에 포함된다.**
제안 58 의 아티팩트 분리 검증(A3/A4, A5/A6)이 성립하려면 기준선에서 빼야 한다.
`step30_scenario_plan.md` §1 ★ 참조.

**무분산 컬럼 4개**: `JEMU_debt_dependency_capped`, `JEMU_asset_turnover_end_capped`,
`JEMU_asset_turnover_avg_capped`, `HAS_OBV_YN` — 패널 전체에서 값이 1개뿐이다.
파생 계산이 전부 0으로 떨어진 것으로 보이며 별도 확인이 필요하다.

**`IS_BUDO_12M` 양성 9,814** — STAGE 5 기대치 9,985 와 171건 차이. 미해결.

## 환경 메모

이 PC 는 ML 스택이 없었다(`duckdb`/`pandas` 만). `C:/Users/scudy/.venvs/nh_eco` 에
venv 를 만들고 lightgbm 4.7.0 / scikit-learn 1.9.0 / shap 0.52.0 을 설치했다.
OneDrive 동기화를 피해 프로젝트 밖에 두었다.

프로젝트 경로에 한글이 있어(`바탕 화면`, `NH AI경진대회`) LightGBM 의 C++ 파일 IO 가
`LightGBMError: Could not open ...` 로 죽는다. **모델 저장/로드는 반드시
`config.load_booster()` / `config.save_booster()` 를 쓸 것.**
