# A-4: 포털 기능 3건 구현 현황 (조사 전용)

조사일: 2026-09-03 / 조사자: wsy0309@nonghyup.com / 상한 15분 조사 결과 정리.
**코드 수정 없음. 아래는 현황 판정만.**

---

## 1. 라우터 전수 목록

`backend/routers/` 6개 `.py` 파일 모두 `backend/main.py` 에 등록되어 있음(누락 없음).
`backend/routers/borrowers.py.bak` 존재 — `.bak` 확장자라 import 되지 않으므로 미등록(구버전 백업으로 추정, borrowers.py 대비 shap/capability 로직이 다름).

| 메서드 | 전체 경로 | 함수명 | 파일:줄 |
|---|---|---|---|
| POST | /api/auth/login | login | backend/routers/auth.py:15 |
| GET | /api/dashboard/summary | get_dashboard_summary | backend/routers/dashboard.py:7 |
| GET | /api/dashboard/months | get_available_months | backend/routers/dashboard.py:55 |
| GET | /api/dashboard/prediction_comparison | get_prediction_comparison | backend/routers/dashboard.py:64 |
| GET | /api/borrowers/ | get_borrowers | backend/routers/borrowers.py:13 |
| GET | /api/borrowers/{bzno}/financials | get_borrower_financials | backend/routers/borrowers.py:40 |
| GET | /api/borrowers/{bzno}/pd_history | get_borrower_pd_history | backend/routers/borrowers.py:114 |
| GET | /api/borrowers/{bzno}/capability | get_borrower_capability | backend/routers/borrowers.py:147 |
| GET | /api/borrowers/{bzno}/shap | get_borrower_shap | backend/routers/borrowers.py:263 |
| GET | /api/borrowers/{bzno} | get_borrower_detail | backend/routers/borrowers.py:319 |
| POST | /api/ai/tips | get_ai_tips | backend/routers/ai.py:52 |
| POST | /api/simulation/ | run_simulation | backend/routers/simulation.py:28 |
| GET | /api/monitoring/metrics | get_metrics | backend/routers/monitoring.py:23 |
| GET | /api/monitoring/pd_distribution | get_pd_distribution | backend/routers/monitoring.py:48 |
| GET | /api/monitoring/drift | get_drift | backend/routers/monitoring.py:86 |
| GET | /api/monitoring/borrowers | get_borrowers_by_bin | backend/routers/monitoring.py:146 |
| GET | /api/health | health_check | backend/main.py:27 (라우터 아닌 앱 직속) |

**총 17개 엔드포인트**(라우터 16 + health 1). main.py 미등록 라우터 파일 없음.

---

## 2. 3개 기능 구현 현황 판정

### (1) 업종별 리스크 대시보드 — **부분구현 (프론트 제거됨, 백엔드만 잔존) → 사실상 미구현**

| 계층 | 판정 | 근거 |
|---|---|---|
| 백엔드 엔드포인트 | 구현됨 | `GET /api/dashboard/summary` 가 `top_risk_industries`(업종별 total/risk_cnt/risk_ratio/legacy_risk_pct) 를 실제 DuckDB 집계로 반환. backend/routers/dashboard.py:28-44 |
| 프론트엔드 화면 | **미구현(제거됨)** | 커밋 `10a0f2c` "Remove the broken 업종별 리스크 매트릭스 scatter chart"로 `GlobalDashboard.tsx`에서 scatter 차트, 업종 그룹핑 로직, `scatterData` 전부 삭제(-149줄). 현재 `frontend/src/pages/GlobalDashboard.tsx` 에는 업종 관련 렌더링이 전혀 없음(벤다이어그램 + 등급분포 바차트만 존재, GlobalDashboard.tsx:214,226 참고). 삭제 사유: X축(legacy_risk_pct)이 그룹핑 단계에서 누락되어 항상 0으로 클램프되는 버그. |
| 실제 데이터 연결 | 해당 없음(화면 자체가 없음) | 백엔드 응답의 `top_risk_industries` 는 `frontend/src/utils/mockData.ts:12`, `mockApi.ts:65` 목업 데이터에만 이름이 남아있고 실사용처 없음 |
| **종합판정** | **목업만/미구현** — 백엔드는 살아있지만 프론트가 없어 "업종별 리스크 대시보드"라는 기능 자체가 현재 화면에 존재하지 않음 |

### (2) PSI 모니터링 — **구현됨 (단, 구모델 기준)**

| 계층 | 판정 | 근거 |
|---|---|---|
| 백엔드 엔드포인트 | 구현됨 | `GET /api/monitoring/metrics` — `eda_pipeline/output/step13_performance_metrics.txt` 텍스트 파싱, Total PSI=0.1357 (monitoring.py:11,22-44). `GET /api/monitoring/drift` — 월별 PROB_FULL 분포를 최초월 기준 breakpoint로 실시간 PSI 계산(monitoring.py:85-142), 하드코딩 아님 |
| 프론트엔드 화면 | 구현됨 | `ModelMonitoring.tsx` 가 `/api/monitoring/metrics`, `/api/monitoring/drift`, `/api/monitoring/pd_distribution` 세 엔드포인트를 모두 실호출(ModelMonitoring.tsx:30-32), PSI 카드(118-123)와 드리프트 라인차트(178-197) 렌더링 |
| 실제 데이터 연결 | **부분** — 실계산이지만 원천이 구모델 | `total_psi`(정적 스냅샷)와 `drift`(실시간 계산) 모두 `PROB_FULL` 컬럼에 의존. `PROB_FULL`은 `database/rescore_full_model.py:32` 에서 `MODEL_PATH='eda_pipeline/output/lgbm_12m_model.txt'`로 스코어링된 값 — README가 "최종 구성"이라 명시한 D8(`lgbm_v2_full.txt`)이 아님. `step13_performance_metrics.txt` mtime(Aug 26)도 `lgbm_12m_model.txt`와 같은 날짜로, D8 학습(Sep 2~3) 이후 갱신 안 됨 |
| **종합판정** | **구현됨 (실계산, 실시간) — 다만 D8이 아닌 구모델(lgbm_12m_model.txt) 기준**이라는 점을 표기 필요 |

### (3) ★ 매크로 시뮬레이션 (거시지표 슬라이더) — **구현됨(구모델 기준) / D8 기준으로는 무효(교집합 0)**

| 계층 | 판정 | 근거 |
|---|---|---|
| 백엔드 엔드포인트 | 구현됨 | `POST /api/simulation/` 실제 LightGBM `predict()` 두 번(충격 전/후) 호출, 업종별 median PD 집계(simulation.py:27-90) |
| 프론트엔드 화면 | 구현됨 | `MacroSimulation.tsx` 가 파라미터 변경 시 350ms debounce 후 `/api/simulation/` POST, `useRealData=true` 가 기본값(MacroSimulation.tsx:22,39-64), 결과를 bar/heatmap/tier/radar 탭으로 시각화 |
| 실제 데이터 연결 | **부분구현 — 모델이 D8이 아님** | `backend/model_inference.py:7` `MODEL_PATH = 'eda_pipeline/output/lgbm_12m_model.txt'`. README(README.md:26)가 "최종 구성"·"실질 성능"이라 못박은 모델은 `eda_pipeline/output/lgbm_v2_full.txt`(D8, 169 피처) 인데, 포털은 이를 로드하지 않음 |
| **★핵심: apply_macro_shock 컬럼 ∩ 모델 피처** | | `apply_macro_shock`(model_inference.py:186-249)이 건드리는 컬럼은 총 84개(중복 제거, `_RATE_COLS`/`_CPI_COLS`/`_OIL_COLS`/`_GROWTH_COLS`/KOSPI·VIX·commodity 등). **lgbm_12m_model.txt(현재 사용 모델, 230피처)와의 교집합 = 84개(전부 반영됨, 정상 동작)**. **lgbm_v2_full.txt(D8, 169피처)와의 교집합 = 0개.** D8 은 원시 거시 컬럼을 하나도 갖지 않고, 대신 `ix_*` 상호작용항 14개(`ix_KORIBOR_spread_d12__liq` 등, D8 feature_names 확인)만 보유 — 이는 raw 컬럼과 이름이 달라 `apply_macro_shock`의 `shift()`가 매칭시키지 못함 |
| **DB 측 ix_ 컬럼** | 없음 | `database/portal_v2.duckdb` `corporate_panel`(총 280컬럼) 에 `ix_` 접두 컬럼 0개. 즉 DB에 D8이 요구하는 상호작용항 자체가 적재되어 있지 않아, D8로 교체하더라도 baseline 조회(`get_baseline()`, model_inference.py:34-48)부터 실패함(SELECT 대상 컬럼 없음) |
| **종합판정** | **구모델(lgbm_12m_model.txt) 기준으로는 "구현됨"(슬라이더가 실제로 예측을 움직임). D8 기준으로는 "무효/미구현"** — 슬라이더 84개 반영 컬럼과 D8 피처의 교집합이 0이므로 D8로 모델만 교체해도 시뮬레이션이 전혀 작동하지 않음(추가로 DB에 ix_* 상호작용항도 없어 baseline 조회부터 실패) |

---

## 3. README / 문서 대조 — 정정 필요 목록 (직접 수정하지 않음, 제안만)

| 파일:줄 | 현재 문구 | 문제 | 제안 |
|---|---|---|---|
| `README.md:12` | "**포털**: 차주별 리스크 설명(SHAP), 글로벌 대시보드, 거시 시뮬레이션" | 거시 시뮬레이션이 README가 "최종 구성/실질 성능"이라 명시한 D8(`lgbm_v2_full.txt`, README.md:26)이 아니라 구모델(`lgbm_12m_model.txt`)로 동작 중임을 명시하지 않음 — 독자가 "포털 시연 = D8 성능 시연"으로 오해할 소지 | "거시 시뮬레이션(구모델 `lgbm_12m_model` 기준, D8 미연동)" 등으로 모델 버전을 명시하거나, 별도 각주로 한계 기술 |
| `docs/ppt_master_presentation_draft.md:269` | "...하단의 **'업종별 리스크 매트릭스'**를 통해 건설업, 도소매업 등 취약 업종을 즉각 식별합니다..." | 해당 차트는 커밋 `10a0f2c`로 GlobalDashboard.tsx에서 완전히 삭제됨(버그로 인한 제거) — 실제 화면에 존재하지 않음 | 삭제된 차트에 대한 데모 스크립트 문구 제거 또는 "삭제됨(버그로 제거, 대체 미구현)" 명시 |
| `docs/ppt_master_presentation_draft.md:34` | "[시연 4] 거시경제 스트레스 테스트 시뮬레이터: 금리/환율 급등 시 업종별 충격 추론" | 시연 자체는 화면상 동작하나 D8이 아닌 구모델 기준 — 시연 결과가 README가 강조하는 "최종 성능(D8)"과 무관함을 밝히지 않음 | 시연 설명에 "(구모델 lgbm_12m_model 기준)" 각주 추가 |
| `docs/ppt_master_presentation_draft.md:290-292` | "슬라이드 제목: Live Demo 04 — 거시경제 시뮬레이터..." / "시각화 제안: MacroSimulation.tsx 화면 스크린샷" | 상동(D8 미연동 사실 미기재) | 상동 |

grep 결과 `docs/03_모델링과_검증.md:62-71`, `docs/06_비즈니스_임팩트.md:29`, `docs/walkthrough.md:39` 는 PSI/업종/거시시뮬레이션을 모델링 관점에서 설명하는 문서로, 포털 화면의 실제 동작 여부를 주장하지 않으므로 정정 불필요.

---

## 4. 결론 (핵심)

**매크로 시뮬레이션은 D8 기준으로 무효다.** `apply_macro_shock` 이 흔드는 84개 컬럼과 D8(`lgbm_v2_full.txt`, 169피처) 피처의 교집합은 **0개**이며, D8이 쓰는 `ix_*` 상호작용항 14개는 `database/portal_v2.duckdb` 에 전혀 적재되어 있지 않다(0개). 포털은 현재 `eda_pipeline/output/lgbm_12m_model.txt`(구모델, 230피처)만 로드하며, 그 기준으로는 슬라이더 84개 컬럼이 전부 반영되어 정상 동작한다. 따라서 "D8 기준 벤 다이어그램 (c)" 류의 산출물이 필요하다면, 현재 포털 코드 경로를 재사용할 수 없고 **별도 독립 스크립트로 D8 모델 + DB의 ix_* 컬럼(현재 부재, 별도 생성 필요) 기준으로 새로 산출해야 한다.**
