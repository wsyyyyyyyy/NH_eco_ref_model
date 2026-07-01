# [Step 16] 백엔드 하드닝 및 실모형(LightGBM) 연동 작업 보고서

> **작성일**: 2026-07-01
> **기준**: Step 15 통합 포털 구축 완료 이후, 포털 각 페이지의 Mock 데이터를 실제 모델/DB 연동으로 전환
> **작업 브랜치**: `main`

---

## 1. 배경

Step 15까지 포털 UI/UX와 기본 API 파이프라인은 구축되었으나, 다음 항목들이 임시 처리(Mock/하드코딩) 상태로 남아 있었음:

- `/api/simulation`이 완전히 하드코딩된 응답만 반환 (LightGBM 미연동)
- 차주별 NICE/KIS 등급이 `PROB_FULL` 임계값 2개(0.3/0.1)로만 대충 분기
- `/api/ai/tips`가 실패 시에도 HTTP 200 반환, deprecated `google-generativeai` 패키지 사용
- 프론트엔드 4개 파일에 `http://localhost:8000`이 하드코딩
- `BorrowerDetail.tsx`가 실제 AI 응답 대신 `aiTipsMock`을 렌더링
- `MacroSimulation.tsx`, `ModelMonitoring.tsx`가 전부 로컬 mock 데이터로만 동작

## 2. 발견 및 수정한 이슈

### 2.1 LightGBM 모델 파일 손상 (CRLF 변환)
`eda_pipeline/output/lgbm_12m_model.txt`, `lgbm_12m_lean_model.txt`가 git의 `core.autocrlf=true` 설정으로 인해 LF→CRLF로 변환되어 있었음. LightGBM 모델 텍스트 포맷은 `tree_sizes`의 바이트 오프셋으로 각 트리 블록을 파싱하므로, CRLF 변환은 오프셋을 깨뜨려 `lgb.Booster(model_file=...)` 로딩 시 `Model format error, expect a tree here` 오류를 유발함.

- **조치**: 두 파일을 LF로 재정규화, `.gitattributes`에 `eda_pipeline/output/*.txt -text` 추가하여 재발 방지.

### 2.2 카테고리형 피처 오인
전체 모델(`lgbm_12m_model.txt`)의 유일한 범주형 피처는 `STD_INDS_CFC`(산업코드)가 아니라 `OBV_ELYWRN_OBV_GRD_DSC`(값: `'-1'/'A'/'B'`)였음. `model.pandas_categorical` 메타데이터로 확인 후 `backend/model_inference.py`에서 해당 컬럼만 `category` dtype으로 캐스팅하도록 수정.

## 3. 백엔드 변경 사항

| 파일 | 변경 내용 |
| :--- | :--- |
| `backend/main.py` | `load_dotenv()` 적용, CORS를 `allow_origins=["*"] + credentials=True`(스펙 위반 조합)에서 `http://localhost:5173` 명시 origin으로 축소, `monitoring` 라우터 등록 |
| `backend/routers/ai.py` | `google-generativeai` → `google-genai` 마이그레이션, 실패 시 200 대신 `HTTPException(502)` |
| `backend/routers/borrowers.py` | 404를 `HTTPException`으로, NICE/KIS 등급을 `grade_mapping.py` 기반으로 산출 |
| `backend/routers/simulation.py` | 5개 거시 슬라이더(금리/환율/물가/유가/GDP)를 실제 모델 피처에 매핑하여 재추론 |
| `backend/routers/monitoring.py` (신규) | 성능지표/PD분포/PSI 드리프트/차주 드릴다운 4개 실데이터 엔드포인트 |
| `backend/grade_mapping.py` (신규) | `PROB_FULL` 전체 분포의 분위수(40~99.9pct)로 산출한 16단계 등급표 |
| `backend/model_inference.py` (신규) | 모델 로딩, 최신월 스냅샷 캐싱, 거시 충격 적용, KSIC→업종명 매핑 |
| `backend/requirements.txt` (신규) | `fastapi`, `uvicorn`, `duckdb`, `pydantic`, `python-dotenv`, `google-genai`, `lightgbm`, `pandas`, `numpy` |

### 3.1 `/api/simulation` 거시 변수 매핑
- 금리(bp): `base_rate_diff12` 등 국내 단/중/장기 금리 diff12 컬럼군에 델타 직접 반영
- 환율(원): `USD_KRW_log_ret`로 변환(기준 환율 1,350원 가정한 근사 로그수익률)
- 물가(%p): `CPI_core_yoy` 등 CPI 계열에 직접 반영
- 유가($): `brent_crude_oil_log_ret`/`WTI_crude_oil_log_ret`로 변환(기준 유가 $80 가정)
- GDP 성장률(%p): BSI/CSI/수출입 등 경기 동행 지표에 반영(직접적인 GDP 피처가 데이터셋에 없어 대체)

**참고**: 학습된 모델의 거시 변수 반응은 항상 교과서적 방향과 일치하지는 않음(예: 결합 시나리오에서 금리·환율·유가 동시 상승 시 평균 예측 부도율이 오히려 감소하는 경우 관찰). 이는 실제 학습 데이터의 상관관계를 반영한 결과이며, 파이프라인 버그가 아님을 개별 변수 격리 테스트로 확인함.

## 4. 프론트엔드 변경 사항

| 파일 | 변경 내용 |
| :--- | :--- |
| `frontend/src/config.ts` (신규), `.env` | `VITE_API_BASE_URL` 도입, `localhost:8000` 하드코딩 4곳 제거 |
| `BorrowerDetail.tsx` | `aiTipsMock` 제거, `/api/ai/tips` 실호출 후 Gemini 응답 렌더링 |
| `MacroSimulation.tsx` | `/api/simulation` 실호출(실모형 토글 ON 시), 기존 로컬 공식은 목업 모드로 보존 |
| `ModelMonitoring.tsx` | 4개 모니터링 API 실호출로 상단 지표/성능비교/PSI 드리프트/PD분포/차주 드릴다운 전환 |

## 5. 검증

- 신규/수정 엔드포인트 전체 curl/urllib 스모크 테스트
- `npx tsc --noEmit` 통과
- Playwright 헤드리스로 5개 페이지(글로벌/지점/차주상세/모니터링/시뮬레이션) 순회 후 스크린샷 확인, 콘솔 에러 없음(기존에 존재하던 차주 리스트 React key 중복 경고 제외)

## 6. 후속 과제

- `BranchDashboard.tsx` 차주 리스트의 React key 중복 경고(기존 이슈, 이번 작업 범위 외)
- `BorrowerDetail.tsx`의 `getLegacyGrade`/`getErmGrade` 헬퍼가 `grade_mapping.py`와 별개의 자체 하드코딩 테이블을 사용 중 — 추후 통일 필요
- 거시 시뮬레이션의 반직관적 결합 반응은 추가 피처 엔지니어링/재학습 없이는 근본적으로 해소되지 않음
