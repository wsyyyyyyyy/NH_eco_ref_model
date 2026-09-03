# 감사·검증 문서 색인 — 본문 수치의 근거

> **이 폴더는 무엇인가**
>
> `docs/01~07` 본문이 인용하는 **수치의 근거**(시점 정합성 감사, 매핑 감사, 공표
> 지연 실측, ablation 결과, 벤 다이어그램, 등급 검증)를 한곳에 모은 것이다.
> 소스를 공유받는 사람이 본문 수치를 재현·검증할 수 있어야 하므로, 생성기가 쓰는
> 원본 경로(`eda_pipeline/output/validation/`)와 별개로 여기에 **사본**을 둔다.
> 생성기 산출물의 **최신본은 항상 원본 경로**이며, 여기 사본은 Group E 정리
> 시점(2026-09-03)의 스냅샷이다. 재생성 후에는 사본도 갱신해야 갈라지지 않는다.

## 이 폴더의 문서

### 수기 정본 (여기가 최신본)

| 문서 | 내용 |
|---|---|
| `PENDING_REVALIDATION.md` | **미결 항목과 정정 이력의 정본.** 시간순 기록 |
| `step36_final_config.md` | 최종 구성 D8 확정 근거 |
| `step30_ablation_A_results.md` | A축·C축 ablation 확정판 (누수 되넣기/제거) |
| `step30_scenario_plan.md` | ablation 시나리오 명세 |
| `step32_ablation_B_results.md` | B축 (시점 정합 재구성) 결과 서술 |
| `D_AXIS_RESULT.md` · `D_AXIS_GATE1_RESULT.md` · `D_AXIS_SUCCESS_CRITERIA.md` | 거시 결합 ablation 결과·게이트·판정 기준서 |
| `ECOS_MAPPING_AUDIT.md` · `ECOS_ITEM_CODE_AUDIT.md` | 거시 지표 항목코드 매핑 감사 |
| `STAGE5_VERDICT.md` · `STAGE6_PREFLIGHT.md` | 단계 판정 기록 |
| `B1_grade_basis.md` · `B1_grade_basis_for_doc06.md` | 등급 산출 기준 검증 (5단계 Z-Score / 16단계 raw 분위, 전수 순위 일치) |
| `C1_venn_results.md` | 벤 다이어그램 — Valid 상위 X% 포착률, 재무양호군, 긴축기→인하기 |
| `C1_macro_stress_results.md` | 거시 상호작용 스트레스 시뮬 (D8 독립 스크립트) |
| `A2_number_reconciliation.md` (+ `.json`) | 정본 수치 계보 (27,147사 / 948,214행 / 9,814) |
| `A3_MACRO_REGIME.md` (+ `.json`) | 거시 국면·구간별 부도율, k=4 시차 상관 |
| `PUBLICATION_LAG_AUDIT.md` | 거시 지표 공표 지연 전수 실측 |
| `E0_MACRO_LEVEL_DIAGNOSIS.md` | 수준 vs 차분 부호 안정성 진단 |

### 생성기 산출물 사본 (최신본은 `eda_pipeline/output/validation/`)

`A_axis_gain_top15.json`, `ablation_B_results.json`, `D_axis_gate1.json`,
`macro_sign_audit_full.json`, `macro_interaction_candidates.json`,
`A3_macro_regime.json`, `A2_number_reconciliation.json`.

### 참고

| 파일 | 비고 |
|---|---|
| `borrowers.py.bak` | 포털 라우터의 int() 비교 버그 증거 (07 문서 §4-7). `.bak` 이라 import 되지 않는다 |

## 원본 경로에만 있는 것 (git 추적, 여기로 복사하지 않음)

`eda_pipeline/output/validation/` 아래:
`step31_temporal_join_audit/` (조인 단위 전수 감사 CSV) ·
`d_axis/` (D축 원자료·캘리브레이션 곡선·월별 PD 그림) ·
`stage6_ablation/` (A·B·C축 원자료 JSON) ·
`stage7_report_inputs/` (캘리브레이션 비교) ·
`step1{4,7,9}_*.png` · `step22_*.png` (이전 세대 진단 플롯).

## 재실행 가능한 감사

```bash
PY="C:/Users/scudy/.venvs/nh_eco/Scripts/python.exe"

$PY -m eda_pipeline.step31_temporal_join_audit                      # 시점 정합성 전수 감사
$PY -m eda_pipeline.step31_temporal_join_audit --panel <p.parquet> --out-suffix _B46
$PY -m eda_pipeline.audit_feature_counts                            # ablation 피처 수 대조
$PY -m eda_pipeline.audit_number_reconciliation                     # 정본 수치 계보
$PY -m eda_pipeline.step43_venn_analysis                            # 벤 다이어그램
$PY -m eda_pipeline.step44_macro_stress_d8                          # 거시 스트레스 시뮬
$PY -m api_data_processing.audit_publication_lag --as-of 2026-09-01 # 공표 지연 (네트워크)
$PY -m api_data_processing.audit_mapping                            # 매핑 감사 (네트워크)
```

## 이전 세대 개발 기록

이전 세대 단계별 기록(`step01_to_06` ~ `step29`, `00_project_master_report.md`)은
Group E 정리에서 **`_archive/legacy_docs/`** 로 옮겼다. 그 문서들의 수치는 당시
세대 기준(AUC 0.9005 등)이며 **현재 세대와 기준선이 다르다 — 인용하지 말 것.**
