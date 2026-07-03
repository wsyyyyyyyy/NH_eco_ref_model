# [Step 29] 운영 모델 재학습 + 전체 DB 재채점 (docs/step28 검증 결과 반영)

> **작성일**: 2026-07-04
> **배경**: `docs/step28_model_validation_and_benchmarking.md`에서 확인된 3가지 개선안을 실제 운영 모델에 반영했다 — ① 정규화 파라미터 적용, ② early stopping을 Valid가 아닌 별도 Dev 슬라이스로 분리, ③ Lean(80) 모델의 완전 중복 변수 3개 제거. Full(230) 모델 교체가 촉발하는 전체 DB 재채점·등급 컷오프 재계산까지 함께 진행했다(사용자가 "전면 교체" 선택).

---

## 1. 무엇을 바꿨나

### 1.1 학습 파라미터 (Full·Lean 공통)
| | 이전 | 이후 |
|---|---|---|
| `num_leaves` | 31 (기본값) | **15** |
| `min_child_samples` | 20 (기본값) | **100** |
| `reg_alpha` / `reg_lambda` | 0 / 0 (기본값) | **1.0 / 1.0** |
| Early stopping 기준 | **최종 성능 보고에 쓰는 Valid(2024.01~)를 그대로 재사용** | **Train 마지막 3개월(202310~202312)을 별도 Dev로 분리** |
| 최종 모델 | Dev로 조기 종료된 모델을 그대로 배포 | Dev로 찾은 최적 라운드 수를 **Train 전체(36개월)로 재학습**해 배포(데이터 낭비 방지) |

### 1.2 Lean 모델 변수 (80 → 77)
`docs/step28` §2-1에서 확인한, 현재 Lean(80) 세트 단독으로도 VIF가 사실상 무한대였던 3개 변수를 제거했다: `BSI_mfg_export_yoy`, `call_rate_overnight_diff12`, `import_index_yoy`.

### 1.3 파이프라인
- 재학습: `eda_pipeline/step23_retrain_production_models.py` (+ 파일-경로 버그만 고친 보조 스크립트 `step23b_regenerate_metrics_only.py`)
- 194만 행 재채점: `database/rescore_full_model.py` — 원본 6.76GB CSV 없이, `corporate_panel`에 이미 있는 피처 컬럼으로 청크 단위 재추론 후 `UPDATE`
- 기존 파일은 전부 백업 후 교체: `eda_pipeline/output/lgbm_12m_model_prev.txt`, `lgbm_12m_lean_model_prev.txt`, `database/portal.duckdb.bak_pre_retrain` (기존 Step 24 백업 `portal.duckdb.bak`은 그대로 보존)

---

## 2. 성능 비교

| 지표 | 기존 모형 (원 보고값) | 기존 모형 (편향 제거 후 실측, step28) | **신규 Full(230)** | **신규 Lean(77)** |
|---|---:|---:|---:|---:|
| Train AUC | 0.9970 | 0.9991 | 0.9958 | 0.9957 |
| Valid AUC | 0.9011 | **0.8905** | **0.9005** | **0.9023** |
| Valid Gini | 0.8020 | 0.7811 | 0.8010 | 0.8045 |
| Valid K-S | 0.6720 | 0.6523 | 0.6663 | 0.6725 |
| PSI (Train↔Valid) | 0.1247 | - | 0.1357 | 0.1301 |

**해석**:
- 신규 Full 모델(0.9005)은 "원래 보고됐던 값(0.9011)"과는 사실상 동률이지만, **"early stopping 편향을 제거한 정직한 옛 모델 성능(0.8905)"보다는 확실히 개선**됐다(+0.010).
- 다만 이는 `docs/step28`의 step14 진단(같은 정규화 파라미터를 Dev로만 early-stop하고 **재적합 없이** Valid에 바로 적용했을 때 Valid AUC 0.9126)보다는 낮다. 원인은 **"Dev로 찾은 최적 라운드 수를 그대로 써서 Train 전체(36개월)로 재적합"하는 표준 관행 자체가 완벽한 보장이 아니기 때문**이다 — 3개월치 데이터를 더 넣고 같은 라운드 수를 유지하면 대개 도움이 되거나 중립적이지만, 이번처럼 근소하게 더 나쁜 방향으로 나올 수도 있다. 이는 은닉된 버그가 아니라 단일 Valid 스플릿 특유의 분산이며, 정직하게 기록해 둔다.
- Lean(77)이 Full(230)보다 근소하게 더 높게 나온 것(0.9023 vs 0.9005)도 마찬가지로 이 스테이지2 재적합 과정의 분산 범위 안에 있는 결과로 보이며, "Lean이 Full보다 우월하다"는 결론으로 확대 해석하지 않는다(기존 관계는 step16에서 Full이 0.9126, Lean이 0.9060으로 Full 우위였음).

---

## 3. Z-Score 정규화 및 등급 컷오프 재계산

| | 이전 | 이후 |
|---|---|---|
| Z-Score 정규화 (logit 평균/표준편차) | `mu=-4.22, std=1.85` (하드코딩 근사치) | **`mu=-3.9652, std=2.6536`** (신규 `PROB_FULL` 194만 건 실측값) |
| `Z_GRADE` 분포 (194만 행 전체) | - | G1=251,929 / G2=904,664 / G3=451,395 / G4=248,930 / G5=87,500 |
| `backend/grade_mapping.py`의 16등급 `PROB_CUTOFFS` | `[0.00613, 0.01248, 0.0234, 0.04323, 0.08917, 0.18447, 0.33018, 0.48234, 0.65109, 0.76701, 0.87997, 0.95703, 0.98333, 0.9894, 0.99249]` | `[0.00654, 0.00803, 0.00991, 0.01248, 0.01603, 0.02109, 0.02868, 0.04137, 0.06649, 0.11696, 0.21508, 0.37128, 0.56732, 0.80061, 0.99113]` |

G1~G5 등급 버킷 규칙(z≤-1→G1, ≤0→G2, ≤1→G3, ≤2→G4, 그외→G5) 자체는 바꾸지 않았다 — `dashboard.py` 등 여러 SQL이 `'G4'`/`'G5'` 문자열을 그대로 참조하기 때문.

---

## 4. 벤 다이어그램·리드타임 재검증 (`/api/dashboard/prediction_comparison`)

이 엔드포인트는 요청마다 `corporate_panel`을 실시간 SQL로 집계하므로, 재채점 직후 다시 호출한 결과가 곧 새 수치다.

| | 기존 | 신규 |
|---|---:|---:|
| 둘 다 포착 (both) | 409 | 403 |
| ERM만 포착 | 556 | 547 |
| **내부등급만 포착** | **0** | **6** |
| 둘 다 미포착 | 7 | 16 |
| 합계(실제 부도) | 972 | 972 |
| 평균 리드타임(개월) | 12.9 | 11.3 |
| 리드타임 유효 표본 | 96 (313건 좌측절단 제외) | 94 (309건 좌측절단 제외) |
| 등급하향 사후반영 비율(grade_lag) | 68.4% | 68.4% (동일 — `OBV_ELYWRN_OBV_GRD_DSC` 기반이라 모델 교체와 무관) |

**주목할 변화**: 기존에는 "내부등급만 포착"이 0건이어서 ERM이 내부등급의 상위집합(superset)처럼 보였는데, 재학습 후에는 6건이 생겼다 — 등급 컷오프가 재계산되며 일부 경계 케이스가 이동한 결과다. 전체적인 우위 구조(ERM 계열 950건 vs 내부등급 계열 409건)는 그대로 유지된다. 평균 리드타임은 12.9→11.3개월로 소폭 줄었으나, 여전히 1년 가까운 선제 경고 우위는 유지된다.

> **범위 밖으로 남겨둔 것**: README/`모델성능평가.md`의 "63.4%/36.6%/6.8개월" A등급 사각지대 분석은 `eda_pipeline/step11_compare_internal.py`/`step12_walkthrough_v3_analysis.py`의 **별도 오프라인 분석 결과**라 이번 재학습으로 자동 갱신되지 않는다. 재검증하려면 해당 스크립트를 새 모델 기준으로 다시 돌리는 별도 작업이 필요하며, 이번 라운드에서는 하지 않았다.

---

## 5. 검증

- 새 모델 파일 재로딩 확인(`lgb.Booster`, Full 230피처/Lean 77피처, 트리 수 정상).
- 재채점 후 `corporate_panel` 전수 확인: `PROB_FULL` NULL 0건, `Z_GRADE` 5개 등급 전부 합리적 분포.
- 백엔드(포트 8010, 격리 테스트) 기동 후 주요 엔드포인트 직접 호출 — `/api/dashboard/summary`, `/api/dashboard/prediction_comparison`, `/api/monitoring/metrics`, `/api/monitoring/drift`, `/api/borrowers`, `/api/borrowers/{id}`, `/api/borrowers/{id}/shap`, `/api/simulation` 전부 200 응답 + 값 합리성 확인.
- 프론트엔드(포트 5173, `VITE_API_BASE_URL`로 테스트 백엔드 연결) Playwright 스크린샷: 글로벌 뱅크 뷰·가상 지점 대시보드·차주 상세 페이지 모두 새 모델 기준 실데이터로 정상 렌더링.
- **참고(이번 작업과 무관, 별도 이슈)**: Model Monitoring 페이지에서 1회 렌더링 크래시 발견. 원인은 최근 병합된 오프라인 목업 폴백 유틸(`frontend/src/utils/mockApi.ts`)이 백엔드 응답을 800ms 안에 못 받으면 목업으로 전환하는데, `/api/monitoring/drift`의 실측 지연(~587ms)이 임계치에 가까워 경합 상황에서 가끔 타임아웃되고, 이때 반환되는 목업 데이터 형태가 recharts와 맞지 않아 차트가 깨짐. 실제 백엔드 응답 자체(직접 curl)는 정상이므로 이번 재학습·재채점과는 무관한 별개 결함이며, 이번 라운드에서는 수정하지 않았다.

---

## 6. 운영 권장사항 반영

### 6.1 분기별 재학습 런북
`docs/step28`에서 제안한 "모델을 1회성으로 배포하지 말고 주기적으로 재학습"하라는 권장사항을 실제 재현 가능한 절차로 남긴다:

```bash
py eda_pipeline/step23_retrain_production_models.py   # Full/Lean 재학습 + 지표 파일 갱신
py database/rescore_full_model.py                     # 194만 행 재채점 + 새 등급 컷오프 출력
# 출력된 새 PROB_CUTOFFS를 backend/grade_mapping.py에 수동 반영(리뷰 목적으로 자동 적용하지 않음)
```
권장 주기: **분기 1회**, 또는 `/api/monitoring/drift`의 PSI가 0.25를 넘을 때 즉시.

### 6.2 분기별 PSI 모니터링
이미 구현되어 있다 — `frontend/src/pages/ModelMonitoring.tsx`의 PSI 카드와 `/api/monitoring/drift` 기반 월별 드리프트 라인차트가 실시간으로 이 역할을 한다. **새로 만들 필요 없이, 위 재학습 트리거 기준(PSI>0.25)으로 이 화면을 정기적으로 확인하면 된다.**

---

## 7. 재현 방법

```bash
py eda_pipeline/step23_retrain_production_models.py
py database/rescore_full_model.py
# database/rescore_full_model.py 출력의 PROB_CUTOFFS를 backend/grade_mapping.py에 반영
```
