# [Step 19] Gemini 안정화 및 실제 SHAP/역량진단 연동 작업 보고서

> **작성일**: 2026-07-02
> **기준**: Step 18 이후, Gemini 할당량 문제 대응 및 남은 mock 카드(SHAP, 역량진단) 실데이터 전환

---

## 1. Gemini API 안정화

- **모델 교체**: `gemini-1.5-flash`/`-8b`는 요청받았으나 API에서 완전히 제거됨(404) 확인. `client.models.list()`로 실제 사용 가능 모델을 조회하고 하나씩 라이브 테스트한 결과, 이 API 키에서 `gemini-2.0-flash-lite`는 할당량이 0으로 막혀 있었고 **`gemini-2.5-flash-lite`**가 정상 동작함을 확인하여 채택.
- **캐싱**: `functools.lru_cache`로 `(bzno, base_ym, prompt)` 키 기반 캐싱 도입. 동일 차주·동일 기준월 재조회는 API 재호출 없이 캐시 반환, 기준월이 바뀌면 재무 데이터가 달라지므로 새로 생성. (최초 설계는 `bzno`만 키로 써서 "기준월이 달라도 같은 답변이 나온다"는 문제가 있었음 — 실사용 확인 후 수정.)
- **Fallback UX**: 429/502 등 실패 시 raw 에러 텍스트 대신 "⏳ 현재 실시간 AI 분석 요청이 몰려 지연되고 있습니다..." 안내 + 등급(G4/G5 vs 그 외) 기준 정적 관리 가이드 3개로 대체. 노란색 박스로 시각적으로 구분.
- **구조화 출력**: Gemini 응답을 자유 텍스트 대신 `response_schema`로 `{summary, tips:[{title, reason}]}` JSON을 직접 받도록 변경. 프론트는 각 팁을 번호 배지 박스로 표시하고 클릭 시 아코디언으로 이유가 펼쳐지도록 구현.

## 2. 부도 확률 시계열 추이 실데이터 연동

- 완전히 고정된 mock 배열(`tsMockData`, 23.09~24.02 고정값)을 제거.
- 신규 엔드포인트 `GET /api/borrowers/{bzno}/pd_history?base_ym=&months=`로 실제 월별 `PROB_FULL` 이력(최근 6개월, 기준월 반영, 중복행 제거 적용)을 조회.

## 3. 요인별 기여도(SHAP) 실데이터 연동

- 기존 `shapMockData`/`featureContributions`는 모든 차주·모든 기준월에 동일한 하드코딩 숫자를 보여주고 있었음.
- `backend/model_inference.py`에 `shap.TreeExplainer` 캐싱 추가 (최초 빌드 ~3초, 이후 요청당 <0.5초).
- 신규 엔드포인트 `GET /api/borrowers/{bzno}/shap`: 실제 LightGBM 모델로 해당 차주의 SHAP 값을 계산.
  - SHAP 값은 로그오즈(log-odds) 단위로 가산되는 값이라 확률(%)로 그대로 환산하면 안 됨 — 특히 이 데이터셋처럼 평균 1%대에서 개별 차주가 90%대까지 크게 벌어지는 경우, "로그오즈 → %p" 단순 선형 근사는 지나치게 작은 숫자가 나와 오해를 줌.
  - 따라서 `base_pd`/`final_pd`(실제 확률)는 그대로 노출하고, 막대그래프는 상위 N개 피처의 SHAP 절대값을 0~100으로 정규화한 `impact_score`(상대적 영향력)로 분리해서 표시 — 실제 확률과 섞어서 착시를 주지 않도록 함.
  - 원본 피처 코드(JEMU_121000 등)를 한글 라벨로 매핑하는 `backend/feature_labels.py` 신규 작성 (`eda_pipeline/step4_borrower_sheet.py`의 `JEMU_COL_MAP` + `docs/데이터명세서.md` 근거).

## 4. 기업 역량 진단(Radar) 실데이터 연동

- `radarMockData`(활동성/수익성/안정성/성장성/규모 5축, 완전 고정값) 제거.
- 신규 엔드포인트 `GET /api/borrowers/{bzno}/capability`: 실제 JEMU 재무비율을 **동일 업종(KSIC 대분류)·동일 기준월 전체 기업 대비 `PERCENT_RANK()`**로 계산해 0~100 백분위 점수화.
  - 활동성 = 총자산/매출채권/재고자산 회전율 평균
  - 수익성 = 영업이익률 + ROE 평균
  - 안정성 = 부채비율(역산) + 자기자본비율 + 이자보상배율 평균
  - 성장성 = 매출액증가율 + 자본증가율 평균
  - 규모 = 자산총계 백분위
  - "업종 평균"도 같은 업종 표본의 실제 평균이며, 표본 크기(`peer_count`)를 화면에 함께 노출.

## 5. 검증

- 각 신규 엔드포인트 curl/urllib 직접 호출로 응답 형태·소요시간 확인 (SHAP ~3초 첫 호출/캐시 후 개선 여지, capability ~2초, pd_history <1초).
- `npx tsc --noEmit` 통과.
- Playwright로 재부팅 후 페이지 전체 스크린샷 재확인, 콘솔 에러 0건 (Gemini 429는 할당량 소진 시의 정상적인 fallback 경로로 별도 확인).

## 6. 후속 과제

- SHAP 계산이 매 요청마다 재실행됨 (bzno+base_ym 캐싱 없음) — 트래픽이 늘면 AI 팁과 동일한 방식의 캐싱 고려.
