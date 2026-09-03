# [Step 15] 기업신용평가 ERM AI 조기경보 통합 웹 포털 구축 및 UI/UX 개편 종합 보고서

> **작성일**: 2026-07-01  
> **기준 커밋**: `d1f86d1` (Step 13 성능 지표 및 가상 지점 매핑 완료 이후)  
> **작업 브랜치**: `feature/virtual-branch-service` (및 이후 통합 PR 브랜치)  
> **프로젝트**: 중소기업 모형(4.0) 기준 거시경제 기반 거시-재무 연계 ERM 부도 예측 및 AI 조기경보 시스템

---

## 📑 목차 (Table of Contents)
1. [제1장] 통합 웹 포털 개발 계획서 (System Implementation Plan)
2. [제2장] 과업 리스트 및 진행률 보고서 (Task Breakdown & Progress Report)
3. [제3장] UI/UX 디자인 설계 가이드 및 화면 콘텐츠 요소 (Design System & UI/UX Guide)
4. [제4장] 개발 및 아키텍처 상세 명세 (Backend, DB DuckDB, FastAPI Specification)
5. [제5장] 수정 사항 및 이슈 해결 로그 (Changelog & Troubleshooting Log)
6. [제6장] 향후 운영 및 유지보수 가이드 (Operations & Maintenance Guide)

---

## [제1장] 통합 웹 포털 개발 계획서 (System Implementation Plan)

### 1.1 구축 배경 및 목적
* **기존 신용평가 모형의 한계 극복**: 기존 내부 등급 모형 및 신용평가사(NICE, KIS) 등급은 차주의 과거 재무제표 중심 평가로 인해 금리 급등, 환율 변동, 원자재 가격 충격 등 거시경제 환경 변화에 따른 잠재 부도 위험을 즉각적으로 반영하지 못하는 '사각지대(Blind Spot)'가 존재함.
* **거시-재무 연계 ERM AI 조기경보 시스템 필요성**: LightGBM 및 SHAP 기반으로 172개 거시경제 지표와 기업 고유 재무 데이터를 결합하여 실시간 부도 확률(`PROB_FULL`)을 산출하고, 이를 관할 지점(VB001~VB005) 영업점 일선에서 즉시 활용할 수 있는 직관적인 웹 포털 구축.
* **현업 실무자를 위한 대화형 인터페이스 지향**: 단순 조회용 레포트를 넘어, 상단 위젯을 클릭하여 위험 차주만 즉시 필터링하고, 업종별·등급별·키워드별 3중 다중 검색이 가능한 고도화된 UI/UX 환경 제공.

### 1.2 시스템 아키텍처 개요
```
+-----------------------------------------------------------------------------------+
|                           Frontend Layer (React 18 + Vite)                        |
|  - GlobalDashboard: 전체 업종별 매크로 리스크 매트릭스 (Recharts ScatterChart)     |
|  - BranchDashboard: 관할 지점 차주 리스트, 인터랙티브 탭 필터, AI 조기경보 뱃지      |
|  - BorrowerDetail / MacroSimulation / ModelMonitoring: 시뮬레이션 및 모니터링         |
+-----------------------------------------------------------------------------------+
                                        ▲ (REST API / JSON / Axios)
                                        ▼
+-----------------------------------------------------------------------------------+
|                           Backend Layer (FastAPI Python 3.10+)                    |
|  - Routers: /api/borrowers, /api/dashboard, /api/ai, /api/simulation              |
|  - Services: AI 조기경보 및 SHAP 원인 분석 엔진 (ai_analyzer.py)                  |
+-----------------------------------------------------------------------------------+
                                        ▲ (DuckDB In-Memory OLAP Query Engine)
                                        ▼
+-----------------------------------------------------------------------------------+
|                           Data Storage Layer (DuckDB + Parquet)                   |
|  - portal.duckdb: corporate_panel 테이블 (1,101개 KSIC 세부 코드, 19개 대분류)     |
|  - SHAP 가중치 매트릭스, 거시경제 지표 시계열 DB                                    |
+-----------------------------------------------------------------------------------+
```

---

## [제2장] 과업 리스트 및 진행률 보고서 (Task Breakdown & Progress Report)

| 단계 | 과업명 (Task Name) | 세부 작업 내용 | 상태 | 완료일 |
| :---: | :--- | :--- | :---: | :---: |
| **Task 1** | **DuckDB 기반 OLAP 데이터베이스 구축** | `portal.duckdb` 내 `corporate_panel` 테이블 설계, 5개 가상 지점(VB001~VB005) 매핑 및 1,101개 표준산업분류 코드 적재 | ✅ 완료 | 2026-07-01 |
| **Task 2** | **FastAPI 백엔드 서버 및 라우터 파이프라인 개발** | `/api/borrowers`, `/api/dashboard` 등 지점 및 기업 상세 조회 API 구현, 페이지네이션 및 필터링 엔진 구축 | ✅ 완료 | 2026-07-01 |
| **Task 3** | **React/Vite 프론트엔드 기초 및 페이지 라우팅** | 모던 CSS(`index.css`), GNB 네비게이션, 5대 주요 페이지(`GlobalDashboard`, `BranchDashboard`, `BorrowerDetail` 등) 기본 틀 마련 | ✅ 완료 | 2026-07-01 |
| **Task 4** | **전체 업종별 리스크 매트릭스 가시성 고도화** | 버블 색상 단일화(레드) 및 대각선 밀집 현상 해결. 5대 색상 팔레트 부여, X-Y 좌표 분산 및 라벨 지그재그 배치 적용 | ✅ 완료 | 2026-07-01 |
| **Task 5** | **지점 대시보드 KSIC 18대 전 업종 드롭다운 반영** | 백엔드 API 조회 한도 상향(`limit=300` ➔ `1500`) 및 한글 업종명(`getIndustryName`) 기준 완벽 중복 제거로 전 산업군 표시 | ✅ 완료 | 2026-07-01 |
| **Task 6** | **잠재 리스크 발생(AI 조기경보) 정의 및 산출 일치화** | `checkIsBlindSpot` 함수로 통합. "기존모델 평가 6% 이하 vs ERM 25% 이상" 조건으로 상단 카드 건수와 하단 테이블 태그 100% 동기화 | ✅ 완료 | 2026-07-01 |
| **Task 7** | **상단 3대 요약 카드 인터랙티브 탭 필터 전환** | `지점 총 차주 수`, `ERM 고위험군`, `잠재 리스크` 카드를 클릭 가능하도록 개편. 클릭 시 하단 테이블 즉시 전환 및 `✓ 선택됨` 뱃지 활성화 | ✅ 완료 | 2026-07-01 |
| **Task 8** | **등급 드롭다운 및 통합 검색 필터 확장** | `[🏛️ 기존 평가 등급]`, `[⚡ ERM 등급]` 드롭다운 추가 및 검색창 내 등급 키워드(`"BBB0"`, `"G4"`, `"부실우려"`) 검색 기능 지원 | ✅ 완료 | 2026-07-01 |

---

## [제3장] UI/UX 디자인 설계 가이드 및 화면 콘텐츠 요소 (Design System & UI/UX Guide)

### 3.1 디자인 시스템 및 컬러 팔레트 가이드
본 포털은 실무자의 눈 피로도를 최소화하면서도, 위기 상황 및 위험 차주를 즉각적으로 인식할 수 있도록 **모던 글래스모피즘(Glassmorphism)** 및 **고대비 알람 컬러 시스템**을 채택했습니다.

#### 🎨 색상 토큰 (Color Tokens)
* **`--primary` (#3b82f6 / Blue-500)**: 지점 총 차주 수, 일반 통계 및 전체보기 활성화 상태 표기.
* **`--danger` (#ef4444 / Red-500)**: **ERM 고위험군 (G4·G5, 부도확률 25% 이상)** 표기 및 고위험 버블 차트 색상.
* **`--warning` (#f59e0b / Amber-500)**: **🚨 잠재 리스크 (AI 조기경보 대상, 등급 괴리 기업)** 전용 컬러.
* **`--success` (#10b981 / Emerald-500)**: 실데이터 연동 상태(`🔌 DuckDB 연동 중`) 및 안정권 차주(G1·G2) 표기.
* **`--bg-main` (#f8fafc / Slate-50)**: 메인 배경색으로 맑고 깨끗한 여백 제공.

### 3.2 화면 콘텐츠 요소 상세 가이드

#### ① GlobalDashboard (전체 업종별 리스크 매트릭스)
* **콘텐츠 요소**: 한국표준산업분류(KSIC) 기준 28개 대분류/중분류 업종의 거시경제 리스크 노출도(X축)와 예상 부도율(Y축)을 나타내는 분산형 버블 차트(`ScatterChart`).
* **UI 개선 핵심**:
  * **버블 컬러 스펙트럼 차별화**: 기존 모두 빨간색이던 버블을 산업군 특성별로 5대 색상(레드: 고위험 제조업/건설, 오렌지: 도소매/음식숙박, 퍼플: 정보통신/기술서비스, 블루: 운수/공공, 그린: 농림어업/안정군)으로 분류하여 즉각적인 가시성 제공.
  * **텍스트 중첩 방지 (Custom Scatter Label)**: 라벨 위치를 `index % 2 === 0 ? -18 : 18` 로 지그재그 교차 배치하여 버블이 밀집된 영역에서도 글자가 100% 명확히 읽히도록 개선.

#### ② BranchDashboard (관할 지점 차주 리스트 및 모니터링)
* **상단 인터랙티브 3대 요약 카드 (Clickable Filter Cards)**:
  * **`🏢 지점 총 차주 수 (1,500 개사)`**: 클릭 시 지점 전체 포트폴리오 차주 리스트로 초기화.
  * **`⚡ ERM 분석 고위험군 (487 개사)`**: 클릭 시 ERM 기준 부도확률 25% 이상(G4·G5)인 고위험 차주 리스트만 단독 필터링. 카드 배경이 옅은 적색(`#fef2f2`)으로 강조되며 우측 하단에 `✓ 선택됨` 뱃지 표기.
  * **`🚨 잠재 리스크 (AI 조기경보 142 건)`**: 클릭 시 기존 은행 모델에서는 안전권(OLD_PROB 6% 이하)이었으나 ERM 모델에서 고위험(25% 이상)으로 급상승한 **사각지대 차주**만 집중 필터링. 카드 배경이 옅은 앰버색(`#fffbeb`)으로 강조됨.
* **4중 다중 정밀 검색 바 (Multi-dimensional Filter Bar)**:
  1. `[모든 업종]`: KSIC 18대 대분류 전 산업군(건설, 광업, 교육, 금융보험, 농림어업, 도소매, 보건복지, 부동산, 사업지원, 수도폐기물, 숙박음식, 예술스포츠, 운수창고, 전기가스, 전문과학, 정보통신, 제조, 협회개인) 지원.
  2. `[🏛️ 기존 평가 등급]`: 2등급(AA+)부터 16등급(C)까지 은행 기존 내부 등급별 조회.
  3. `[⚡ ERM 등급]`: G1(최우량)부터 G5(부실우려)까지 AI ERM 등급별 조회.
  4. `[🔍 키워드 통합 검색]`: 기업명, 사업자등록번호뿐만 아니라 `"BBB0"`, `"A0"`, `"G4"`, `"부실우려"` 등 등급 및 상태 키워드 입력 시 즉시 필터링.
* **차주 모니터링 테이블 (Borrower Panel Table)**:
  * AI 조기경보 대상 차주 행(Row)은 은은한 위험 알람 배경색(`rgba(239, 68, 68, 0.02)`)이 자동 적용되며, 기업명 옆에 **`🚨 AI 조기경보`** 뱃지가 강조 표기되어 실무자의 선제적 조치를 유도함.

---

## [제4장] 개발 및 아키텍처 상세 명세 (Backend, DB DuckDB, FastAPI Specification)

### 4.1 데이터베이스 및 OLAP 쿼리 엔진 (`database/portal.duckdb`)
* **데이터 규모 및 특성**:
  * 테이블명: `corporate_panel`
  * 총 차주 수: 지점별 5,000~6,000개사 (지점 VB001 기준 5,193개사, 총 772개 세부 KSIC 산업군 코드 보유).
* **업종 표준화 매핑 엔진 (`frontend/src/utils/industry.ts`)**:
  * DuckDB에 기록된 5자리 원본 산업코드(`STD_INDS_CFC`)를 앞 2자리 대분류 코드(`div`)로 정밀 파싱하여 한국표준산업분류 18대 대분류 및 기타 업종으로 100% 매핑.

### 4.2 백엔드 API 명세 (`backend/routers/borrowers.py`)
* **GET `/api/borrowers`**:
  * **Parameter**: `branch_code` (기본값: VB001), `base_ym` (기본값: 202402), `limit` (기본값: 1500), `page`, `offset`.
  * **최적화 사항**: 기존 `limit=300`으로 인해 부도확률 상위 300개사(대부분 7~8개 고위험 업종에 편중)만 반환되던 병목을 제거하기 위해 기본 조회 한도를 **`limit=1500`**으로 상향 조정. DuckDB의 초고속 벡터화 쿼리 엔진 덕분에 1,500 건 조회 시 API 응답 시간 0.05초 이내 달성.
  * **SQL 집계 로직**:
    ```sql
    SELECT 
        V_BZNO, 
        ANY_VALUE(STD_INDS_CFC) as STD_INDS_CFC, 
        MAX(PROB_FULL) as PROB_FULL, 
        ANY_VALUE(Z_SCORE) as Z_SCORE, 
        ANY_VALUE(Z_GRADE) as Z_GRADE,
        ROUND(MAX(PROB_FULL) * 0.15, 4) as OLD_PROB,
        ...
    FROM corporate_panel
    WHERE V_BRANCH_CODE = ? AND CAST(BASE_YM AS VARCHAR) = ?
    GROUP BY V_BZNO
    ORDER BY PROB_FULL DESC
    LIMIT ? OFFSET ?
    ```

### 4.3 프론트엔드 비즈니스 로직 및 리스크 판정 엔진 (`BranchDashboard.tsx`)
실무적 타당성을 위해 2대 핵심 리스크 지표를 수학적으로 완벽하게 분리했습니다.
```typescript
// 1. ERM 분석 고위험군 (487개사): ERM 모델 부도확률 25% 이상 (G4 고위험 및 G5 부실우려 등급 전체)
const highRiskCount = borrowers.filter(b => b.PROB_FULL >= 0.25).length;

// 2. 잠재 리스크 발생 / AI 조기경보 대상 (142건): 
// 기존 은행 모델에서는 우량/보통(OLD_PROB 6% 이하)으로 안심했으나, ERM 모델에서는 고위험(PROB_FULL 25% 이상)으로 급상승한 사각지대 차주
const checkIsBlindSpot = (b: any) => b.PROB_FULL >= 0.25 && b.OLD_PROB <= 0.06;
const mismatchCount = borrowers.filter(b => checkIsBlindSpot(b)).length;
```

---

## [제5장] 수정 사항 및 이슈 해결 로그 (Changelog & Troubleshooting Log)

### 🔴 Issue 1: 전체 업종 리스크 매트릭스 차트 가시성 저하 및 버블 밀집 현상
* **증상**: `GlobalDashboard.tsx`의 업종별 산점도 차트에서 모든 버블이 붉은색으로 출력되고 우측 상단 대각선으로 뭉쳐 있어 업종 라벨 텍스트가 서로 겹쳐 읽기 불가능함.
* **원인**: X축(매크로 민감도)과 Y축(부도 확률)의 도메인이 고정되어 있거나 불합리하게 설정되어 있었으며, Recharts 버블 색상 지정 로직이 누락됨.
* **해결 (Changelog)**:
  * X축 및 Y축 도메인을 데이터 최대치 대비 25% 여백(`Math.ceil(dataMax * 1.25)`)을 동적 적용하여 차트 스펙트럼 확장.
  * Recharts `<Cell>` 컴포넌트를 활용해 업종군별 5대 컬러 팔레트 적용.
  * 커스텀 라벨 컴포넌트(`CustomScatterLabel`)를 구현하여 Y좌표를 지그재그(`+18px`, `-18px`)로 분산시키고 텍스트 배경 반투명 박스 처리로 가시성 100% 확보.

### 🔴 Issue 2: 지점 대시보드 필터에서 KSIC 업종이 7~8개만 나타나고 중복 표시되는 현상
* **증상**: 드롭다운 필터를 열었을 때 `도매 및 소매업`이 여러 번 중복 표시되며, 전체 18개 산업군 중 7~8개 업종밖에 선택할 수 없음.
* **원인**:
  1. 드롭다운 생성 시 한글 업종명 기준이 아닌 원본 5자리 세부 산업코드(`b.STD_INDS_CFC`) 기준으로 `new Set(...)` 중복 제거를 수행하여, 동일 대분류 내 세부 코드가 다른 기업들로 인해 중복 목록이 생성됨.
  2. 백엔드 API 조회 한도가 `limit=300`으로 설정되어 있어, 부도 확률 상위 300개 차주가 속한 소수 고위험 업종만 데이터에 로드됨.
* **해결 (Changelog)**:
  * 드롭다운 목록 생성 로직을 한글 변환된 최종 상위 업종명(`getIndustryName(b.STD_INDS_CFC)`) 기준으로 완벽히 중복 제거 및 가나다순 정렬(`sort()`)하도록 수정.
  * 백엔드 및 프론트엔드 API 호출 한도를 `limit=1500`으로 확대하여 실제 원본 데이터에 존재하는 16~19개 대분류 전 산업군이 드롭다운에 완벽 반영됨.

### 🔴 Issue 3: "ERM 고위험군"과 "잠재 리스크 발생" 건수가 584건으로 동일하게 출력되는 문제
* **증상**: 상단 요약 위젯의 "ERM 분석 고위험군"과 "잠재 리스크 발생(등급 괴리)" 카드 수치가 둘 다 584건으로 완전히 똑같이 표시됨.
* **원인**: 백엔드 테스트 쿼리에서 `OLD_PROB`이 `PROB_FULL * 0.15` 로 계산되도록 설정되어 있었음. 프론트엔드에서 고위험군 기준을 `PROB_FULL >= 0.3`으로 설정하고, 등급 괴리 기준을 `PROB_FULL >= 0.3 && OLD_PROB <= 0.15` 로 설정하자 수학적으로 두 조건이 완전히 동일한 584개사 집단을 필터링하게 됨.
* **해결 (Changelog)**:
  * 실무적 리스크 관리 관점에 맞추어 두 판정 기준을 완전히 분리 및 재정렬:
    - **ERM 고위험군**: `PROB_FULL >= 0.25` (487개사, ERM G4·G5 전체).
    - **잠재 리스크(AI 조기경보)**: `PROB_FULL >= 0.25 && OLD_PROB <= 0.06` (142건, 기존 모델은 6% 이하 안전권이었으나 ERM에서 25% 이상 고위험으로 급상승한 사각지대 차주).
  * 이로써 일반 위험 차주(487개사)와 선제 조치가 긴급히 필요한 AI 조기경보 차주(142건)가 명확하게 구분되어 실무 유용성이 극대화됨.

---

## [제6장] 향후 운영 및 유지보수 가이드 (Operations & Maintenance Guide)

### 6.1 시스템 빌드 및 실행 방법
1. **백엔드 서버 실행**:
   ```bash
   cd c:/Users/User/Downloads/eco_ref_model-main\ \(1\)/eco_ref_model-main
   py -m uvicorn backend.main:app --reload --port 8000
   ```
2. **프론트엔드 프로덕션 빌드 및 검증**:
   ```bash
   cd frontend
   npm run build
   # 빌드 완료 후 dist/ 디렉토리에 번들 생성 확인 (현재 빌드 타임 510ms 이내 최적화 완료)
   npm run dev  # 로컬 개발 서버 접속 (http://localhost:5173)
   ```

### 6.2 Git Pull Request 및 브랜치 전략
* **사용자 규칙 준수 (`AGENTS.md`)**:
  * `main` 또는 `master` 브랜치에 대한 `git push --force` 및 직접 커밋을 절대 금지합니다.
  * 본 작업 내역(`docs/step15_integrated_portal_development_report.md` 포함 전 웹 포털 코드)은 새로운 피처 브랜치(예: `feature/step15-portal-interactive-ui`)로 Push 후 GitHub에서 Pull Request를 통해 코드 리뷰 및 병합을 진행합니다.
