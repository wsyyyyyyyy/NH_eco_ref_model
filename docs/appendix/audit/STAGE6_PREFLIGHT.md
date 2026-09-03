# STAGE 6 착수 전 — 선행 작업 및 필수 확인 결과

실행일: 2026-08-30
재현: `python -m eda_pipeline.step30_stage6_preflight`

---

## 1. 선행 6건 처리 결과

| # | 작업 | 상태 | 결과 |
|---|---|---|---|
| 1 | `portal_v2.duckdb` 재빌드 | 완료 | `database/build_portal_v2.py` 신규. 948,214행 / 268컬럼 |
| 2 | `db_migration.py` / `init_duckdb.py` 갱신 | 대체 | 구 스크립트는 손대지 않고 `build_portal_v2.py` 를 새로 만들었다. 구 스크립트는 `portal.duckdb` 를 지우고 다시 만드는 코드(`os.remove`)라 보호 대상 파일에 손댈 수 있어 STAGE 6 경로에서 제외했다 |
| 3 | `step7` 경로를 `config.read_panel()` 로 전환 | 완료 | 구 파일명 `nh_panel_macro_12m.csv` 하드코딩 제거 |
| 4 | `validation_common.py` 하드코딩 절대경로 4건 | 완료 | 전부 `config` 경유. 아래 2절 |
| 5 | `step7` 피처 선정 로직 | 완료 | `leaky_cols.feature_columns()` 단일 경로로 통일 + `assert` 추가 |
| 6 | `step7` early stopping Dev셋 | 완료 | `eval_set=[(X_dev, y_dev)]`. Valid 제거 |

부수적으로 고친 것 2건:

- `config.read_panel()` 이 파일을 못 찾을 때 `FileNotFoundError` 를 던지지 않고
  `None` 을 반환하고 있었다. `raise` 문이 `restore_categories()` 안 죽은 코드로
  밀려 있었다. 제자리로 옮겼다.
- `config.load_booster()` / `save_booster()` 추가. 프로젝트 경로에 한글이 있어
  (`바탕 화면`, `NH AI경진대회`) LightGBM 의 C++ 파일 IO 가
  `LightGBMError: Could not open ...` 로 죽는다. 파이썬 문자열 경유로 우회한다.
  **이 PC 에서 모델을 저장/로드하는 코드는 전부 이 함수를 써야 한다.**

---

## 2. 경로 정리 — config 단일 소스

`eda_pipeline/config.py`

```
DB_DIR         = <PROJECT_ROOT>/database
DB_PATH_LEGACY = DB_DIR/portal.duckdb       # 구 스키마. 읽기 전용. S0 전용.
DB_PATH_V2     = DB_DIR/portal_v2.duckdb    # 신 스키마. STAGE 6 기본.
DB_PATH        = DB_PATH_V2                 # 기본값

MODEL_PATH_LEGACY_FULL = output/lgbm_12m_model.txt        # 보호 대상. 읽기만.
MODEL_PATH_LEGACY_LEAN = output/lgbm_12m_lean_model.txt   # 보호 대상. 읽기만.
MODEL_PATH_V2_FULL     = output/lgbm_v2_full.txt
MODEL_PATH_V2_LEAN     = output/lgbm_v2_lean.txt
```

| 함수 | 동작 |
|---|---|
| `connect_db(which)` | **예외 없이 `read_only=True`**. 내부에서 `require_db()` 호출 |
| `require_db(which)` | 파일이 없으면 예외. **조용한 폴백 없음** |
| `assert_db_writable(which)` | `which='legacy'` 면 `PermissionError` |
| `assert_model_writable(path)` | legacy 2건이면 `PermissionError` |
| `save_booster(booster, path)` | 위 가드를 통과해야만 저장 |

`portal.duckdb` 부재 시 메시지 (조용히 넘어가지 않음):

```
...\database\portal.duckdb 없음.
  이 파일은 S0(기존 파이프라인 재현) 평가에만 필요하다.
  없으면 S0 을 건너뛰고 S1 을 상대 기준선으로 삼는다.
  대체 경로: ...\nh_panel_full.csv (legacy 베이스라인 패널) 가 있으면
  그 파일로 S0 을 평가할 수 있다.
  ※ 신 DB(portal_v2.duckdb) 로 폴백하지 않는다.
```

`validation_common.py` 4건 처리:

| 기존 (동작 불가) | 현재 |
|---|---|
| `DB_PATH = 'C:/Users/User/model_kbm/database/portal.duckdb'` | `config.DB_PATH` (= v2). `load_panel(..., which=)` 로 시나리오가 선택 |
| `FULL_MODEL_PATH = 'C:/Users/User/model_kbm/.../lgbm_12m_model.txt'` | `config.MODEL_PATH_LEGACY_FULL` |
| `LEAN_MODEL_PATH = '.../lgbm_12m_lean_model.txt'` | `config.MODEL_PATH_LEGACY_LEAN` |
| `OUTPUT_DIR = '.../output/validation'` | `config.VALIDATION_DIR` |

Train/Dev/Valid 경계는 `eda_pipeline/split_spec.py` 한 곳으로 모았다.
step7 / validation_common / Ablation 러너가 각자 상수를 들고 있으면 어긋난다.

---

## 3. portal_v2.duckdb 재빌드 결과

원천: `eda_pipeline/output/nh_panel_macro_12m_obv_none.parquet` (109 MB)

- `portal.duckdb` 는 **존재하지 않았다**. 따라서 덮어쓰기·수정 발생 없음.
  존재했더라도 `assert_db_writable('legacy')` 가 물리적으로 막는다.
- `portal_v2.duckdb` 기존 파일 없음 → 타임스탬프 회피 불필요.

| 항목 | 값 |
|---|---|
| 행수 | 948,214 |
| 컬럼 수 | 268 |
| 신규 컬럼 | 228개 (기준선: 구 패널 `nh_panel_full.csv` 70컬럼) |
| `JEMU_191506_val` 등 신규 컬럼 | 전부 존재 확인 |
| `IS_BUDO_12M` 양성 | **9,814 / 948,214 = 1.0350%** |
| `IS_BUDO_12M` 기여기업 | 988 |
| `(V_BZNO, BASE_YM)` 중복 | **0 — OK** |
| BASE_YM 범위 | 202101 ~ 202505 (53개월) |
| SPLIT | TRAIN 635,880 / VALID 312,334 |

지시서 기대치 9,985 와 **171건 차이**가 난다. STAGE 5 검증서에도 같은
`MISMATCH` 가 기록되어 있다. **해결(A-2)**: 9,985 는 `drop_in_default_periods`
적용 전(951,908행) 양성이고 9,814 는 적용 후(948,214행) 양성이다. 정본은 9,814 —
근거 `A2_number_reconciliation.md`.

---

## 4. 필수 확인 4건

### 확인 1 — 학습 투입 피처와 LEAK_CONFIRMED

```
DB 컬럼 268개 -> 학습 투입 피처 259개
제외: NON_FEATURE 12 / LEAK_CONFIRMED 10 / LEAK_SUSPECT 3 / V_BRANCH_CODE 1
assert not leaked  ->  통과
```

**주의**: `LEAK_CONFIRMED` 10개는 v2 패널에 **애초에 존재하지 않는다**
(`COPR_OPNP_C`, `CRIF_*` 전부 `DB에존재=False`). 패널 생성 단계(step2/step5)에서
이미 떨어져 나갔다는 뜻이다. assert 는 통과하지만 "제외했다" 가 아니라
"들어온 적이 없다" 다.

부작용: **S3b(CRIF 를 시점 정합적으로 재구성) 은 이 DB 로 실행할 수 없다.**
CRIF 원천 컬럼이 패널에 없으므로 step2 부터 다시 만들어야 한다.

`LEAK_SUSPECT` 3개는 전부 DB 에 존재하고 기본 피처에서 제외되어 있다 —
S2/S3 의 on/off 비교가 가능하다.

### 확인 2 — early stopping eval_set

```
step7_modeling_shap.py:80              eval_set   = [(X_dev, y_dev)]   -> Dev 전용 OK
step23_retrain_production_models.py:155 valid_sets = [dev_set]          -> Dev 전용 OK
판정: 통과 — Valid 는 eval_set 에 들어가지 않는다
```

경계: TRAIN ~202309 / DEV 202310~202312 / VALID 202401~202505.
AST 로 소스를 파싱해 확인한다. 러너 작성 후 재실행할 것.

### 확인 3 — scale_pos_weight

| 구간 | 행수 | 양성 | 부도율 | scale_pos_weight |
|---|---:|---:|---:|---:|
| TRAIN | 579,859 | 5,286 | 0.9116% | **108.70** |
| DEV | 56,021 | 696 | 1.2424% | 79.49 |
| VALID | 312,334 | 3,832 | 1.2269% | 80.51 |

고정값 금지. 러너는 시나리오별 Train 부분집합에서 매번 재계산한다
(preflight 가 러너 소스의 `scale_pos_weight=` 가 상수 리터럴인지 AST 로 검사).

### 확인 4 — 기존 모델 md5 (작업 전 = 작업 후, 변경 없음)

```
lgbm_12m_model.txt        md5=4e02cd3738dfae657da84edd906b9359   912,630 bytes
lgbm_12m_lean_model.txt   md5=25d1cc5bfe091c4549fd78fe4549fec7   901,565 bytes
```

`config.save_booster()` 로 이 두 경로에 쓰려 하면 `PermissionError`. 가드 확인 완료.

---

## 5. ★ 블로커 2건 — Ablation 실행 전 판단 필요

### 블로커 A — S0(기존 파이프라인 재현) 실행 불가

지시서의 대체 경로를 순서대로 확인했다.

| 후보 | 결과 |
|---|---|
| `database/portal.duckdb` | **없음** |
| `eda_pipeline/output/nh_panel_macro_12m.csv` (구 거시 결합 패널) | **없음** |
| `eda_pipeline/output/nh_panel_full.csv` (legacy 베이스라인 패널) | 있음 (367MB) — **그러나 사용 불가** |

`nh_panel_full.csv` 로 평가할 수 없는 이유:

- 컬럼 70개뿐. **타겟 `IS_BUDO_12M` 이 없다** (`IS_BUDO_YN` 만 있다).
- `lgbm_12m_model.txt`(FULL) 의 피처 230개 중 **173개(75.2%)가 없다**
  — 거시 172개 전부 + `BUSINESS_AGE`.
- `lgbm_12m_lean_model.txt`(LEAN) 도 77개 중 36개(46.8%)가 없다.

→ **S0 를 제외하고 S1 을 상대 기준선으로 삼는다. 최종 보고서에 명시한다.**

참고로 구 모델의 성능은 `docs/step28_model_validation_and_benchmarking.md` 에
기록이 남아 있다 (정적 스플릿 Valid AUC 0.9011 / 3-way 진짜 홀드아웃 0.880 /
워크포워드 1~11폴드 평균 0.933). 이 값들은 **이번에 재현한 것이 아니라 문서
인용**이며, 신 스키마 결과와 직접 비교할 수 없다 (모집단·타겟 정의가 다르다).

### 블로커 B — 거시 91개 컬럼이 합성 데이터다

`portal_v2.duckdb` 에 들어간 거시 지표는 **실데이터가 아니다.**

`api_data_processing/output/model_input/model_input_monthly_cleaned.csv` 는
이 체크아웃에 없고, `api_data_processing/` 에는 `assign_virtual_branch.py`
하나뿐이다 (PENDING_REVALIDATION 7~9번). STAGE 5 는 고정 시드
`default_rng(20260829)` 합성 프레임으로 로직만 검증했고, 그 값이 그대로
패널에 남아 있다.

실측 증거:

| 컬럼 | 값 |
|---|---|
| `KOSPI_log_ret` | min −1.445 / max 2.334 / avg **0.323** (= 월간 32% 수익률) |
| `base_rate_diff12` | 202104 = **1.643**, 202106 = −1.050 |

기준금리 12개월 차분이 1.64%p 를 오르내리지 않는다. 표준정규 난수다.

**영향 범위 (학습 피처 259개 기준):**

| 구분 | 개수 | 비중 |
|---|---:|---:|
| 순수 거시지표 (월 단위로만 변함) | 91 | 35.1% |
| 거시 × 기업 상호작용항 | 10 | 3.9% |
| **합성 거시 의존 소계** | **101** | **39.0%** |
| 기업 고유 정보만으로 구성 | 158 | 61.0% |

→ 거시가 관련된 시나리오(S7a/S7b 수출 노출도, S8 AA17 LAG, MACRO_REDUCE
172 vs 91, 5-3 업종별 거시 민감도)는 **지금 돌리면 난수를 해석하게 된다.**

---

## 6. 판단 대기

기업 고유 피처 158개만으로 구성한 Ablation 은 지금 그대로 유효하다
(CG01/C302 아티팩트 분리 검증 = 제안 58 이 여기 포함된다).
거시 관련 시나리오만 실데이터 확보까지 보류하면 된다.

Ablation 실행은 이 판단 이후로 미룬다.
