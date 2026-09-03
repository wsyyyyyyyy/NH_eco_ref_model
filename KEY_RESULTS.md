# KEY_RESULTS.md — 주요 산출물 색인

이 파일은 **지도**다. 수치를 다시 설명하지 않는다 (1절 제외) — "어디에 있는지"만 안내한다.
프로젝트를 처음 받았다면 이 파일에서 원하는 결과의 출처 파일을 찾아 그 파일을 열어라.

---

## 1. 한눈에 보는 핵심 수치

| 수치 | 값 | 근거 파일 |
|---|---|---|
| Valid AUC (최종, D8) | **0.8578** (σ 0.0007, 시드 3회 42/7/2024, 규제 R2) | [`docs/appendix/audit/step36_final_config.md`](docs/appendix/audit/step36_final_config.md) |
| 3층 성능 | 누수 포함 상한 A7 **0.9398** / 누수 제거 하단 A0c **0.7826** / 최종 D8 **0.8578** | [`docs/appendix/audit/step30_ablation_A_results.md`](docs/appendix/audit/step30_ablation_A_results.md) |
| 패널 규모 | **948,214행 · 27,147사** · 양성 9,814행(1.035%) | [`docs/appendix/audit/A2_number_reconciliation.md`](docs/appendix/audit/A2_number_reconciliation.md) |
| 피처 수 | Full **164** / 포털 Lean_macro **59** | [`eda_pipeline/output/lgbm_v2_full.txt`](eda_pipeline/output/lgbm_v2_full.txt) · [`eda_pipeline/output/lgbm_v2_lean_macro.txt`](eda_pipeline/output/lgbm_v2_lean_macro.txt) |
| 거시 지표 선별 | 63 → 검사 97 → 부호일치 15 → 통과 10(+완화 5) → 상호작용 **14** | [`docs/05_거시경제_결합.md`](docs/05_거시경제_결합.md) §7 |
| 포착률 (Valid 상위10%) | **76.0%** (421/554), Lift 5.75 | [`docs/appendix/audit/C1_venn_results.md`](docs/appendix/audit/C1_venn_results.md) §B |
| 재무양호군 포착률 | 전구간 **82.6%** (95/115) / Valid **62.5%** (40/64) | [`docs/appendix/audit/C1_venn_results.md`](docs/appendix/audit/C1_venn_results.md) §D |
| 긴축기경보 → 인하기부도 | **55.6%**, Lift 7.15 | [`docs/appendix/audit/C1_venn_results.md`](docs/appendix/audit/C1_venn_results.md) §C(39행) |
| 등급 체계 | Z-Score μ=**-4.2433** σ=**2.8871**, G1~G5 단조(0.063%→19.78%) | [`eda_pipeline/output/grade_mapping_v2.json`](eda_pipeline/output/grade_mapping_v2.json) |
| 임계값 | F2 **0.5534** / 비용비 10:1 **0.7846** | [`eda_pipeline/output/threshold_v2.json`](eda_pipeline/output/threshold_v2.json) |

---

## 2. 문서 (`docs/`)

| 문서 | 한 줄 요약 | 이 문서가 답하는 질문 |
|---|---|---|
| [`README.md`](README.md) | 프로젝트 전체 요약과 핵심 결과 | 이 프로젝트가 무엇을 만들었고 핵심 결과가 뭔가? |
| [`docs/01_문제정의와_데이터.md`](docs/01_문제정의와_데이터.md) | 예측 대상 정의와 원천 데이터 | 무엇을 예측하려 했고 어떤 데이터를 썼는가? |
| [`docs/02_전처리_설계.md`](docs/02_전처리_설계.md) | 패널 조인 단위·결측·거시 시차 설계 | 왜 조인 단위(연 vs 월)가 시점 누수를 가르는가? |
| [`docs/03_모델링과_검증.md`](docs/03_모델링과_검증.md) | 학습 조건과 판정 기준(사전 확정) | 결과를 보기 전에 정한 판정 규칙은 무엇인가? |
| [`docs/04_누수_발견과_제거.md`](docs/04_누수_발견과_제거.md) | **★핵심.** 시점 누수를 측정으로 증명·제거 | AUC 가 0.94 에서 0.86 으로 내려간 이유는? |
| [`docs/05_거시경제_결합.md`](docs/05_거시경제_결합.md) | 거시 결합 세 번의 시도와 실패 원인 | 거시경제 지표는 왜 결합이 그렇게 어려웠는가? |
| [`docs/06_비즈니스_임팩트.md`](docs/06_비즈니스_임팩트.md) | 포착률·등급·임계값·포털 연동 현황 | 성능이 낮아졌는데 왜 이 모형을 써야 하나? |
| [`docs/07_한계와_향후과제.md`](docs/07_한계와_향후과제.md) | 구조적 한계·미해결 결함·재현성 사고 | 이 프로젝트가 못한 것과 향후 과제는 무엇인가? |
| [`docs/ppt_master_presentation_draft.md`](docs/ppt_master_presentation_draft.md) | 발표용 슬라이드 대본 (Q&A 부록 포함) | 위 내용을 발표 15분 분량으로 압축하면? |
| [`SETUP.md`](SETUP.md) | 설치부터 재현까지 복사-붙여넣기 절차 | 이 저장소를 처음 받아 어떻게 돌려보는가? |

---

## 3. 그림 (`docs/images/`)

폴더에 실제로 존재하는 png 22개 전부.

| 파일 | 무엇을 보여주는가 | 인용 |
|---|---|---|
| [`default_rate_vs_base_rate.png`](docs/images/default_rate_vs_base_rate.png) | 월별 실제 부도율 vs 기준금리 | `05` §5, `06`, ppt |
| [`lag_correlation_curve.png`](docs/images/lag_correlation_curve.png) | 거시-부도 시차 상관 곡선 (k=4 에서 꺾임) | `05` §5, `06`, ppt |
| [`missing_rate.png`](docs/images/missing_rate.png) | 변수별 결측률 | `eda_pipeline/output/eda_report.html` §2 |
| [`target_distribution.png`](docs/images/target_distribution.png) | Target(`IS_BUDO_12M`) 분포 | `eda_report.html` §3 |
| [`numeric_distributions.png`](docs/images/numeric_distributions.png) | 수치형 변수 분포 | `eda_report.html` §4 |
| [`categorical_distributions.png`](docs/images/categorical_distributions.png) | 범주형 변수 분포 | `eda_report.html` §5 |
| [`timeseries_trends.png`](docs/images/timeseries_trends.png) | 주요 지표 시계열 추이 | `eda_report.html` §6 |
| [`target_correlation.png`](docs/images/target_correlation.png) | Target 상관 | `eda_report.html` §7 |
| [`correlation_heatmap.png`](docs/images/correlation_heatmap.png) | 변수 간 상관관계 히트맵 | `eda_report.html` §7 |
| [`default_trajectory.png`](docs/images/default_trajectory.png) | 부도 전 주요 지표 변화 궤적 | `eda_report.html` §8 |
| `corr_grade_pd.png` | 등급별 PD 상관 (구세대 자료) | `_archive/legacy_docs/` 만 인용 — 현재 문서 미인용 |
| `shap_dependence.png` | SHAP dependence plot (구세대 자료) | `_archive/legacy_docs/` 만 인용 — 현재 문서 미인용 |
| `shap_summary.png` | SHAP summary plot (구세대 자료) | `_archive/legacy_docs/` 만 인용 — 현재 문서 미인용 |
| `shap_summary_top50.png` | SHAP summary top50 (구세대 자료) | `_archive/legacy_docs/` 만 인용 — 현재 문서 미인용 |
| `threshold_optimization.png` | 임계값 최적화 곡선 (구세대 자료) | `_archive/legacy_docs/` 만 인용 — 현재 문서 미인용 |
| `ttd_analysis.png` | Time-to-default 분석 (구세대 자료) | `_archive/legacy_docs/` 만 인용 — 현재 문서 미인용 |
| `ttd_analysis_raw_facts.png` | TTD 원자료 팩트 (구세대 자료) | `_archive/legacy_docs/` 만 인용 — 현재 문서 미인용 |
| `media__1782745739963.png` ~ `media__1782746167008.png` (6개) | 출처 불명 | 어느 문서에도 인용 없음 |

> ★ 위 마지막 7종(구세대 SHAP/TTD/임계값 자료)과 media__ 6개는 **현재 세대 문서(01~07/ppt)가 인용하지 않는다.** 삭제 여부는 이 문서의 범위 밖이므로 판단하지 않았다.

---

## 4. 모델 파일 (`eda_pipeline/output/`)

| 파일 | 피처 수 | Valid AUC | 용도 |
|---|--:|---|---|
| [`lgbm_v2_full.txt`](eda_pipeline/output/lgbm_v2_full.txt) | 164 | **0.8578** (σ 0.0007) | **최종 확정 모형(D8).** 본문 수치의 기준 |
| [`lgbm_v2_lean.txt`](eda_pipeline/output/lgbm_v2_lean.txt) | 46 | 0.8531 | 순수 gain 컷 Lean — 거시 상호작용이 1개만 남아 포털엔 부적합 |
| [`lgbm_v2_lean_macro.txt`](eda_pipeline/output/lgbm_v2_lean_macro.txt) | 59 | 0.8541 (σ 0.0030) | **★ 포털(backend)이 실제로 로드하는 모델.** `backend/model_inference.py`의 `MODEL_PATH` |
| [`grade_mapping_v2.json`](eda_pipeline/output/grade_mapping_v2.json) | — | — | Z-Score μ/σ, G1~G5·16단계 등급 컷오프 (Full D8 기준 산출, 포털과 공유) |
| [`threshold_v2.json`](eda_pipeline/output/threshold_v2.json) | — | — | F2·비용비(5:1/10:1/20:1) 최적 임계값 (Full D8 기준 산출, 포털과 공유) |

> Full(164) 이 학습·본문 수치의 기준이고, Lean_macro(59) 만 응답 속도를 위해 포털에 축소 배치됐다 — 자세한 사유는 [`docs/06`](docs/06_비즈니스_임팩트.md) §5-1.

---

## 5. 근거 자료 (`docs/appendix/audit/`)

본문 수치를 의심할 때 볼 원자료. 폴더의 파일 전부.

### 수기 정본 문서

| 파일 | 무엇의 근거인가 | 인용 문서 |
|---|---|---|
| [`PENDING_REVALIDATION.md`](docs/appendix/audit/PENDING_REVALIDATION.md) | 미결 항목·정정 이력의 정본(시간순) | README, 01~05, 07 |
| [`step36_final_config.md`](docs/appendix/audit/step36_final_config.md) | 최종 구성 D8 확정 근거 | README, 01, 03, 05, 06, 07, ppt |
| [`step30_ablation_A_results.md`](docs/appendix/audit/step30_ablation_A_results.md) | A/C축 ablation 확정판 (누수 되넣기/제거) | README, 03, 04, ppt |
| [`step30_scenario_plan.md`](docs/appendix/audit/step30_scenario_plan.md) | ablation 시나리오 명세 | 04 |
| [`step32_ablation_B_results.md`](docs/appendix/audit/step32_ablation_B_results.md) | B축(시점 정합 재구성) 결과 | 04 |
| [`D_AXIS_RESULT.md`](docs/appendix/audit/D_AXIS_RESULT.md) | 거시 결합 D축 ablation 결과 | 05 |
| [`D_AXIS_GATE1_RESULT.md`](docs/appendix/audit/D_AXIS_GATE1_RESULT.md) | D축 게이트1 판정 | 05 |
| [`D_AXIS_SUCCESS_CRITERIA.md`](docs/appendix/audit/D_AXIS_SUCCESS_CRITERIA.md) | D축 성공 판정 기준서 | 03, 05 |
| [`ECOS_MAPPING_AUDIT.md`](docs/appendix/audit/ECOS_MAPPING_AUDIT.md) | 거시 지표 항목코드 매핑 감사 | 01, 05 |
| [`ECOS_ITEM_CODE_AUDIT.md`](docs/appendix/audit/ECOS_ITEM_CODE_AUDIT.md) | ECOS 항목코드 감사 원자료 | 본문 직접 인용 없음(내부 참고) |
| [`STAGE5_VERDICT.md`](docs/appendix/audit/STAGE5_VERDICT.md) | 단계 판정 기록(STAGE 5) | 05 |
| [`STAGE6_PREFLIGHT.md`](docs/appendix/audit/STAGE6_PREFLIGHT.md) | 단계 판정 기록(STAGE 6, 사전점검) | 본문 직접 인용 없음(내부 참고) |
| [`B1_grade_basis.md`](docs/appendix/audit/B1_grade_basis.md) | 등급 산출 기준 검증(Z-Score/16단계 순위 일치) | 03, 06, ppt |
| [`B1_grade_basis_for_doc06.md`](docs/appendix/audit/B1_grade_basis_for_doc06.md) | 06 문서용 등급 근거 발췌 | 본문 직접 인용 없음(내부 참고) |
| [`C1_venn_results.md`](docs/appendix/audit/C1_venn_results.md) | 포착률·재무양호군·긴축→인하기 벤 다이어그램 | README, 06, 07, ppt |
| [`C1_macro_stress_results.md`](docs/appendix/audit/C1_macro_stress_results.md) | 거시 상호작용 스트레스 시뮬(D8 독립 산출) | 06, ppt |
| [`A2_number_reconciliation.md`](docs/appendix/audit/A2_number_reconciliation.md) (+ `.json`) | 정본 수치 계보(27,147사/948,214행/9,814) | 01, 04, ppt |
| [`A3_MACRO_REGIME.md`](docs/appendix/audit/A3_MACRO_REGIME.md) (+ `.json`) | 거시 국면·구간별 부도율, k=4 시차 상관 | 본문 직접 인용 없음(내부 참고) |
| [`PUBLICATION_LAG_AUDIT.md`](docs/appendix/audit/PUBLICATION_LAG_AUDIT.md) | 거시 지표 공표 지연 전수 실측 | 02, 07 |
| [`E0_MACRO_LEVEL_DIAGNOSIS.md`](docs/appendix/audit/E0_MACRO_LEVEL_DIAGNOSIS.md) | 수준 vs 차분 부호 안정성 진단 | 05 |
| [`README.md`](docs/appendix/audit/README.md) | 이 폴더 자체의 색인 (더 상세함) | — |

### 생성기 산출물 사본 (최신본은 `eda_pipeline/output/validation/`)

`A_axis_gain_top15.json` · `ablation_B_results.json` · `D_axis_gate1.json` · `macro_sign_audit_full.json` · `macro_interaction_candidates.json` · `A3_macro_regime.json` · `A2_number_reconciliation.json` · [`B_exp_obv5_drop.json`](docs/appendix/audit/B_exp_obv5_drop.json)(OBV 죽은 피처 5개 제외 재학습 판정 원자료 — 04 §7-3·07 §1-4-1 수치의 데이터).

### 참고

`borrowers.py.bak` — 포털 라우터의 `int()` 비교 버그 증거 (07 §4-7). `.bak` 이라 import 되지 않는다.

---

## 6. 실행 산출물

| 산출물 | 상세 |
|---|---|
| [`database/portal_v2.duckdb`](database/portal_v2.duckdb) | 1.43 GB. 재빌드: `python -m database.build_portal_v2` (git 미추적 — `SETUP.md` 절차로 재생성) |
| [`eda_pipeline/output/eda_report.html`](eda_pipeline/output/eda_report.html) | 26KB. 브라우저로 직접 열면 EDA 8개 섹션(3절 그림 참조)이 인라인으로 보인다 |
| [`verify_reproduction.py`](verify_reproduction.py) | `python verify_reproduction.py` (또는 venv 인터프리터로) 실행. 기대값: 패널 948,214행 / 양성 9,814 / 기업 27,147사 / D8 Valid AUC 0.8578±0.003 / 등급 G1~G5 단조 — **5 PASS** |
| [`docs/SME4.0_Portal_Real_App_Demo.html`](docs/SME4.0_Portal_Real_App_Demo.html) | 797KB. 포털 프론트엔드 번들 스냅샷(정적 목업, `<title>frontend</title>`) |
| [`docs/SME4.0_Presentation_Draft.html`](docs/SME4.0_Presentation_Draft.html) | 3.6MB. `docs/ppt_master_presentation_draft.md` 의 HTML 렌더 초안 |

---

## 7. 보관 (`_archive/`)

**★ 전부 인용 금지.** 현행 수치가 아니다 — 현행 결과는 위 1~6절만 참조할 것. 상세 사유는 [`_archive/README.md`](_archive/README.md).

| 폴더 | 설명 | git 추적 |
|---|---|---|
| [`legacy_model/`](_archive/legacy_model/) | 누수 포함 구세대 모델(230피처). `docs/04` gain 수치의 출처 | 3/3 파일 추적 |
| [`legacy_docs/`](_archive/legacy_docs/) | AUC 0.9005 를 주장하던 구세대 개발 문서(step01~29 등). 전부 무효 | 31/31 파일 추적 |
| [`legacy_scripts/`](_archive/legacy_scripts/) | 이 PC 에서 실행 불가하거나 현행 스크립트로 대체된 것 | 36/43 파일 추적 — **`bak/`·`pre_remap/`(7개) 는 실체가 git 미추적** |
| [`legacy_panels/`](_archive/legacy_panels/) | 구세대 패널 CSV(`nh_panel_full.csv` 등, ~350MB) | 1/2 파일 추적 — **CSV 실체는 git 미추적**, README 만 추적 |
| [`ablation_models/`](_archive/ablation_models/) | A~D축 시나리오별 모델(`lgbm_v2_A*`, `lgbm_v2_C*`, ~76MB) | 1/18 파일 추적 — **모델 실체 17개는 git 미추적**, README 만 추적 |
| [`legacy_validation/`](_archive/legacy_validation/) | 매핑 정정 이전(preGroupD) D축 결과 (~100MB) | 1/148 파일 추적 — **원자료는 git 미추적**, README 만 추적 |
| [`superseded_d8_169/`](_archive/superseded_d8_169/) | OBV 죽은 피처 5개 제외 전 D8(169피처, AUC 0.8548). 04 §7-3·07 §1-4-1 경위 | 1/11 파일 추적 — **모델·JSON 실체는 git 미추적**, README 만 추적 |

각 폴더의 대용량 실체는 저장소 용량을 줄이기 위해 의도적으로 git에서 제외했다(이전 세션 결정). 재현이 필요하면 해당 폴더 `README.md`의 재생성 절차를 따르거나 별도 요청할 것.
