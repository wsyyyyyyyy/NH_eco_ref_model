# _archive/ — 이전 세대 산출물 보관 (인용 금지)

이 폴더는 **누수가 포함된 이전 세대 모델과 그 근거 문서**를 보관한다.
현행 모델·문서와 수치가 다르며 **인용해서는 안 된다.**

보관 이유는 [`docs/04_누수_발견과_제거.md`](../docs/04_누수_발견과_제거.md) 의 수치
(예: `CRIF` gain 36.34%, A7 Valid AUC 0.9398)를 재현 가능하게 하기 위함이다. 이
증거를 지우면 04 문서의 서술이 출처 없는 주장이 된다.

**현행 결과는 루트 [`README.md`](../README.md) 와 [`docs/01~07`](../docs/) 을 참조할 것.**

## 저장소에 포함되는 것 / 안 되는 것

| 포함 (git 추적) | 미포함 (재생성/요청) |
|---|---|
| `legacy_model/lgbm_12m_model.txt` · `lgbm_12m_lean_model.txt` (합 ~1.7 MB) — `docs/04` gain 수치(CRIF 36.34%, A7 0.9398)의 직접 출처 | `ablation_models/` `lgbm_v2_A*`·`lgbm_v2_C*` 17개 (~76 MB) — `step30_stage6_ablation.py` 재실행으로 재생성 |
| 이 `README.md` + 6개 하위 `README.md` | `legacy_panels/nh_panel_full.csv` (~350 MB) — `python -m eda_pipeline.run` 로 재생성 |
| `legacy_docs/` 문서 전부 | `legacy_validation/*_preGroupD.parquet` (~100 MB) |

- **gain 수치만 확인**하려면 모델 파일 없이도 된다 —
  [`docs/appendix/audit/A_axis_gain_top15.json`](../docs/appendix/audit/A_axis_gain_top15.json)
  및 [`step30_ablation_A_results.md`](../docs/appendix/audit/step30_ablation_A_results.md)
  에 A0~A8 축의 gain·AUC 가 그대로 있다. `docs/04` 본문 수치는 전부 여기서 재현된다.
- 미포함 파일이 필요하면 별도 요청. md5 는 각 하위 `README.md` 에 있다.

## 하위 폴더

| 폴더 | 내용 |
|---|---|
| `legacy_model/` | 누수 포함 모델(230피처). `docs/04` gain 수치의 출처. `lgbm_12m_model.txt` md5 `4e02cd37…9359` / `lgbm_12m_lean_model.txt` md5 `25d1cc5b…fec7` (불변 확인) |
| `legacy_docs/` | AUC 0.9005 를 주장하던 이전 세대 개발 문서(step01~29 등). 전부 무효 |
| `legacy_scripts/` | 이 PC 에서 실행 불가(`.gemini/antigravity/brain` 절대경로)하거나 현행 스크립트로 대체된 것 |
| `legacy_panels/` | 구세대 패널 CSV (`nh_panel_full.csv` 등). 재현 시 `eda_pipeline` step1~2 로 재생성 가능 |
| `ablation_models/` | A~D축 시나리오별 모델(`lgbm_v2_A*`, `lgbm_v2_C*`). `docs/04` A축 표 · `docs/05` D축 표의 출처. 재실행으로 재생성 가능하나 시드 차이로 소수점이 달라질 수 있어 보관 |
| `legacy_validation/` | 매핑 정정 이전(preGroupD) D축 결과. `docs/05` §매핑 사고 절이 "보존했다" 로 참조하는 원자료 |
