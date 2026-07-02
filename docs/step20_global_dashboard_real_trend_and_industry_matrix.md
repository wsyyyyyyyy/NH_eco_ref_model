# [Step 20] 글로벌 뱅크 뷰 실데이터 전환

> **작성일**: 2026-07-02
> **기준**: Step 19 이후, 첫 화면(글로벌 뱅크 뷰)에 남아있던 조작(fabricated) 데이터 확인 및 교체

---

## 1. 발견한 문제

KPI 카드 3개와 등급분포 막대그래프는 이미 실제 DB 집계였으나, 나머지 두 차트는 수식으로 지어낸 값이었음:

- **"실질 부도율 vs 모델 예측력 비교 (PD-LAG)" 라인 차트**: 현재 선택된 기준월의 위험률(`currentRiskNum`) 하나만 실측치였고, 나머지 6개월 추이(`실제`/`기존`/`신규`)는 `currentRiskNum * (0.38 + 0.62 * factor^1.3)` 같은 임의 수식으로 "ERM이 기존 모델보다 정확해 보이도록" 그린 가짜 곡선.
- **"업종별 리스크 매트릭스" 산점도**: Y축(ERM 고위험률)은 실제였으나, X축("기존 평가 위험도")은 `yVal * spreadFactors[idx]`(버블이 안 겹치도록 고른 임의 배수 배열)로 만든 값 — 실제 레거시 모형 점수가 아님.

## 2. 조치

### 백엔드 (`backend/routers/dashboard.py`)
- **`GET /api/dashboard/trend`** (신규): `base_ym` 기준 최근 N개월의 실제 월별 집계
  - `신규`: 해당월 전체 기업의 평균 `PROB_FULL` (ERM 실측)
  - `기존`: `AVG(PROB_FULL) * 0.15` (다른 화면과 동일한 레거시 근사식)
  - `실제`: `AVG(IS_BUDO_12M)` — 실제 12개월 내 부도 발생 여부의 실현치
  - IS_BUDO_12M은 최근월에 가까울수록 우측 절단(censoring)되어 인위적으로 0에 수렴하므로(12개월 관측이 아직 안 끝남), 이 지표는 `base_ym`이 최신월에 너무 가까우면 신뢰도가 떨어짐을 주석으로 명시.
- **`/api/dashboard/summary`의 `top_risk_industries`에 `legacy_risk_pct` 추가**: 업종별 `AVG(PROB_FULL) * 0.15` 실측 평균.

### 프론트엔드 (`GlobalDashboard.tsx`)
- `lineChartData`를 로컬 수식 대신 `/api/dashboard/trend` 실호출 결과로 교체.
- 산점도 `xVal`을 `spreadFactors` 배열 대신 실제 `legacy_risk_pct`로 교체, X축 domain을 실제 데이터 스케일(0~수%)에 맞게 자동 조정.

## 3. 검증

- 신규 엔드포인트 curl 확인: ERM 평균 PD 5.6~8.2%, 레거시 근사 0.84~1.23%, 실제 실현 부도율 0.94~1.0% — 모두 합리적인 범위.
- `npx tsc --noEmit` 통과, Playwright 스크린샷으로 두 차트 모두 실데이터 반영 확인, 콘솔 에러 0건.
