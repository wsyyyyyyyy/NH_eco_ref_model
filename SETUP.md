# 실행 방법

이 소스를 처음 받은 사람이 파이프라인을 처음부터 끝까지 돌려 보는 절차다.
**복사-붙여넣기만으로 끝난다.** 각 단계마다 "이게 나오면 정상"을 함께 적었다.

> 프로젝트가 무엇이고 무엇을 발견했는지는 [`README.md`](README.md) 를 먼저 읽어라.
> 이 문서는 "돌려보는 법" 만 다룬다.

---

## 0. 시작 전 확인

- **경로에 한글이 없어야 한다.** LightGBM 의 C++ 파일 IO 가 한글 경로에서 실패한다.
  - 좋은 예: `C:\work\NH_eco_ref_model`
  - 나쁜 예: `C:\사용자\바탕화면\NH_eco_ref_model`
  - 한글 경로에 두면 실행 시작 시 경고가 뜬다. 폴더째로 옮기면 된다.
- **Python 3.11 이상.** (`python --version` 으로 확인)
- **포털 화면까지 보려면 Node.js 20 이상.** 파이프라인·모델 재현만 할 거면 필요 없다.
- **디스크 여유 5GB 이상.** 중간 산출물(패널 parquet 등)이 그만큼 쌓인다.
- Windows 기준으로 적었다. macOS/Linux 는 `.venv\Scripts\activate` 를
  `. .venv/bin/activate` 로만 바꾸면 된다.

---

## 1. 설치

프로젝트 폴더 안에서 아래를 통째로 붙여넣어라.

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

**정상:** 마지막 줄에 `Successfully installed lightgbm-4.7.0 ... shap-0.52.0 ...` 가 뜬다.
경고(`WARNING: ...`)는 무시해도 된다.

> 프로젝트 외부에 이미 만들어둔 venv 를 쓰는 경우 위 activate 대신
> 그 venv 의 인터프리터로 직접 실행하면 된다.
> 예: `<venv경로>/Scripts/python.exe run_all.py` (Windows) /
> `<venv경로>/bin/python run_all.py` (macOS/Linux)

---

## 2. 전체 실행

```bash
python run_all.py
```

전처리 → 통합 패널 → 거시 결합 → D8 모델 학습(시드 3회)까지 한 번에 돈다.
**순서를 사람이 정할 필요가 없다.** 이미 만들어진 산출물이 있으면 그 단계는
자동으로 건너뛴다.

**정상 출력 (요약):**
```
[run_all] 출력 위치 : ...\eda_pipeline\output
[run_all] 거시 CSV  : 있음 (거시 수집 건너뜀)
[시작]    step 1-3  원천 적재 → 통합 패널 → EDA
[완료]    step 1-3  — <N>초 / <크기> bytes
[시작]    step 5    패널 전처리 ...
[완료]    step 5    — <N>초 / ...
[시작]    step 6    거시경제 결합 ...
[완료]    step 6    — <N>초 / ...
[시작]    step 38   D8 프로덕션 재학습 (시드 3회)
[완료]    step 38   — <N>초 / ...
[run_all] 전체 완료 — <합계>초
```

**소요 시간 (참고, 이 PC 실측 — §검증 결과 참조):**

| 단계 | 시간 |
|---|---|
| step 1-3 (원천 → 948,214행 패널) | *검증 후 기재* |
| step 5 (전처리) | *검증 후 기재* |
| step 6 (거시 결합) | *검증 후 기재* |
| step 38 (D8 학습 시드 3회) | *검증 후 기재* |
| **합계** | *검증 후 기재* |

**막히면:** 어느 `[실패] step ...` 에서 멈췄는지 확인하고, 그 위의 마지막
`INFO`/`ERROR` 줄을 본다. `§5 자주 막히는 곳` 을 참조.

---

## 3. 결과 확인

```bash
python verify_reproduction.py
```

재현 결과가 확정본과 맞는지 항목별로 판정한다.

**정상 출력:**
```
  [PASS]  패널 행수 948,214
  [PASS]  양성 행수 9,814
  [PASS]  기업 수 27,147
  [PASS]  D8 Valid AUC 0.8578 ± 0.003
  [PASS]  등급 G1~G5 부도율 단조 증가
[verify] 5 PASS / 0 FAIL
[verify] 재현 성공 — 확정본과 일치합니다.
```

| 대조 항목 | 기대값 |
|---|---|
| 패널 행수 | 948,214 |
| 양성(부도) 행수 | 9,814 |
| 기업 수 | 27,147 |
| D8 Valid AUC | 0.8578 ± 0.003 |
| 등급 G1~G5 | 부도율이 단조 증가 |

> 거시 지표를 API 로 다시 수집했다면 응답 시점 차이로 값이 미세하게 다를 수 있다.
> **행수·컬럼수가 맞고 AUC 가 허용 범위 안이면 통과**로 본다.

---

## 4. 포털 실행

포털은 **백엔드(FastAPI)** 와 **프론트엔드(React + Vite)** 두 서버를 함께 띄운다.
터미널 두 개가 필요하다. **포트는 바꾸지 말 것** — 백엔드 8000, 프론트 5173 이
서로 기본값으로 맞춰져 있다(백엔드 CORS 가 5173 만 허용, 프론트 API 주소가 8000 고정).

### 터미널 1 — 백엔드 (Python)

```bash
.venv\Scripts\activate
python -m pip install -r backend\requirements.txt
python -m database.rescore_v2_d8
uvicorn backend.main:app --port 8000
```

`rescore_v2_d8` 이 `portal_v2.duckdb`(약 1.5 GB, 저장소 미포함)를 만든다.
**정상:** 마지막에 `Uvicorn running on http://127.0.0.1:8000` 이 뜨고 콘솔이
대기 상태가 된다. 확인: **http://127.0.0.1:8000/api/health** → `{"status":"ok"}`.

### 터미널 2 — 프론트엔드 (Node.js 20 이상 필요)

```bash
cd frontend
npm install
npm run dev
```

**정상:** `Local: http://localhost:5173/` 이 뜬다. 브라우저에서 접속하면 로그인
화면 → 글로벌 대시보드 → 지점 대시보드 → 차주 상세(레이더·SHAP)가 보인다.

### 알려진 제약

- **Node.js 가 없으면 프론트엔드는 실행할 수 없다.** 이 저장소를 정리한 환경에는
  Node 가 없어 프론트 화면은 **미검증**이다. 백엔드 API 는 14개 중 12개가 200 이다.
- **500 을 내는 백엔드 엔드포인트 2개** — 프론트에서 아래 두 화면 요소가 깨진다.
  기존 결함이며 이번 범위에서 고치지 않았다(`docs/07` §4-7).
  - 글로벌 대시보드의 "예측 비교" (`/api/dashboard/prediction_comparison` — `DSH_DT` 컬럼 부재)
  - 차주 상세의 재무 표 (`/api/borrowers/{bzno}/financials` — `kis_score` NaN 직렬화 실패)
- 거시 시뮬레이션 화면은 D8 미연동이다(`docs/06` §5).

---

## 5. 자주 막히는 곳

| 증상 | 원인 | 해결 |
|---|---|---|
| 실행 시작 시 `[경고] 프로젝트 경로에 비ASCII 문자가 있습니다` | 폴더 경로에 한글 | 한글 없는 경로로 폴더째 이동 (§0) |
| `LightGBMError: Could not open ...` | 위와 같음 (경고를 무시하고 진행한 경우) | 한글 없는 경로로 이동 후 재실행 |
| `[run_all] ★ 거시 지표 CSV 가 없습니다` | `model_input_monthly_cleaned.csv` 부재 | §6 참조 (API 키 없이 우회 가능) |
| `FileNotFoundError: 거시 축소 기준 모델이 없습니다` | `_archive/legacy_model/lgbm_12m_model.txt` 누락 | 저장소를 통째로 받았는지 확인. `_archive/` 를 지우면 안 된다 |
| *검증 중 실제로 겪은 것을 여기에 추가* | | |

---

## 6. API 키가 없을 때

거시 지표(ECOS·KOSIS)는 신청·승인 절차가 있어 즉시 받을 수 없다. 그러나
**저장소에 수집 결과 CSV(`api_data_processing/output/model_input/model_input_monthly*.csv`,
약 280KB)가 포함되어 있어 키 없이도 `run_all.py` 가 완주한다.** `run_all.py` 가
이 파일을 감지하면 거시 수집 단계를 자동으로 건너뛴다.

**직접 다시 수집하려면** (키가 있을 때만):
1. [ECOS OpenAPI](https://ecos.bok.or.kr/api/#/AuthKeyApply) 에서 무료 키 발급 (즉시)
2. [KOSIS OpenAPI](https://kosis.kr/openapi/) 에서 무료 키 발급 (승인까지 시간 소요)
3. 프로젝트 루트에 `.env` 파일을 만들고 (`​.env.example` 참고):
   ```
   ECOS_API_KEY=발급받은_키
   KOSIS_API_KEY=발급받은_키
   ```
4. 재수집:
   ```bash
   python -m api_data_processing.main --target-freq M
   python -m api_data_processing.impute_data
   ```
   그 다음 `python run_all.py` 를 다시 돌린다.
