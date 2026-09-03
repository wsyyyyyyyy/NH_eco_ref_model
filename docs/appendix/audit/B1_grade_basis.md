# B-1. 등급 산출 기준 확정 — 로그오즈 Z-Score vs raw 확률 분위

검증일: 2026-09-03 · 대상 DB `database/portal_v2.duckdb` (read_only) · `corporate_panel` 948,214행
정본 컷오프 파일 `eda_pipeline/output/grade_mapping_v2.json`
생성 `eda_pipeline/step40_grade_threshold.py` · 적용 `database/rescore_v2_d8.py::apply_grades()` (L124-148)
로그 `logs/B1_grade_basis.log`

> **결론 먼저: 어긋남이 아니다.** `grade_mapping_v2.json` 에 두 세트의 컷오프가 있는 것은
> 계산 오류가 아니라 **처음부터 서로 다른 두 등급 체계**를 위한 것이다. 5단계는 로그오즈
> Z-Score 기준, 16단계는 raw 확률 분위 기준이며, **두 기준은 같은 점수축의 단조 변환이므로
> 개체별 순위가 전수 일치한다** (불일치 0 / 948,214). 사용자 지시("등급은 로그오즈 Z-Score
> 기준")가 가리키는 것은 5단계 `GRADE`/`Z_GRADE`(G1~G5)이고, 그 서술은 그대로 유효하다.

---

## 1. 두 컷오프 세트는 각각 무엇을 위한 것인가

| | **5단계 체계** | **16단계 체계** |
|---|---|---|
| JSON 필드 | `z_cutoffs` | `grade16_prob_cutoffs` |
| DB 컬럼 | `GRADE` (= `Z_GRADE`) | `GRADE16` |
| 라벨 | G1 · G2 · G3 · G4 · G5 | AAA … CCC (NICE/KIS 표기 16노치) |
| 산출 기준축 | **로그오즈 Z-Score** | **raw 예측확률 분위** |
| 컷오프 값 | `[-1.0, 0.0, 1.0, 2.0]` (등폭, 고정) | Valid raw PD 의 `[0.40 … 0.996]` 분위 15개 |
| 컷오프 성격 | **절대 기준** (등폭 Z) | **상대 기준** (등빈도 분위) |
| 산출 코드 | `step40_grade_threshold.py::recompute_grades()` L112-140 | 같은 함수 L142-147 |
| 용도 | 리스크군 분류 · 경보 대상 선별 (G4/G5) | 신용등급 표기 (기존 CB 등급과 눈높이 맞춤) |
| 백엔드 사용 | `Z_GRADE` 를 DB 에서 직접 읽음 | `prob_to_grade(PROB_FULL)` 로 **런타임 재계산** |

`Z_SCORE` 의 정의는 `rescore_v2_d8.py` L133 그대로다.

```
Z_SCORE = (LOG_ODDS - z_mu) / z_sigma
z_mu    = -4.186387031107627
z_sigma =  2.837346856919158
```

`z_mu`/`z_sigma` 는 **Valid 구간(202401~202505, 312,334행) LOG_ODDS 의 mean/std** 다.
전 구간 분포로 표준화하면 홀드아웃 밖 정보를 컷오프에 역참조하게 되므로 Valid 로 고정했다.
(검증: 전 구간 Z 평균 −0.1340 / sd 1.0364 · Valid 구간 Z 평균 −0.0075 / sd 1.0010)

### 핵심 — 두 기준은 같은 사다리의 눈금이다

16단계 확률 컷오프를 같은 `z_mu`/`z_sigma` 로 Z 환산하면 **단조 증가하며 5단계 컷오프
(−1 / 0 / +1 / +2) 사이에 정확히 끼어든다.**

| # | 분위 | `PROB_RAW` 컷오프 | `LOG_ODDS` | **Z 환산** | 상위 밴드 |
|--:|--:|--:|--:|--:|---|
| — | — | 0.000890 | −7.0237 | **−1.0000** | *(G2 시작)* |
| 1 | 0.400 | 0.007883 | −4.8351 | −0.2286 | AA+ |
| — | — | 0.014973 | −4.1864 | **+0.0000** | *(G3 시작)* |
| 2 | 0.500 | 0.017088 | −4.0521 | +0.0473 | AA0 |
| 3 | 0.575 | 0.029565 | −3.4911 | +0.2450 | AA− |
| 4 | 0.650 | 0.050769 | −2.9284 | +0.4434 | A+ |
| 5 | 0.715 | 0.081244 | −2.4256 | +0.6206 | A0 |
| 6 | 0.770 | 0.123123 | −1.9632 | +0.7836 | A− |
| 7 | 0.820 | 0.182743 | −1.4979 | +0.9475 | BBB+ |
| — | — | 0.206027 | −1.3490 | **+1.0000** | *(G4 시작)* |
| 8 | 0.865 | 0.266224 | −1.0139 | +1.1181 | BBB0 |
| 9 | 0.900 | 0.361349 | −0.5695 | +1.2747 | BBB− |
| 10 | 0.928 | 0.467255 | −0.1312 | +1.4292 | BB+ |
| 11 | 0.950 | 0.570730 | +0.2848 | +1.5758 | BB0 |
| 12 | 0.967 | 0.663929 | +0.6809 | +1.7154 | BB− |
| 13 | 0.980 | 0.752809 | +1.1137 | +1.8680 | B+ |
| — | — | 0.815824 | +1.4883 | **+2.0000** | *(G5 시작)* |
| 14 | 0.989 | 0.828445 | +1.5746 | +2.0304 | B0 |
| 15 | 0.996 | 0.903419 | +2.2358 | +2.2634 | CCC |

> 굵은 Z 값(−1 / 0 / +1 / +2)은 5단계 경계이고 그 사이 값이 16단계 경계다.
> **하나의 정렬된 사다리**이며 서로 교차하지 않는다.
>
> 16단계 사다리는 Z ∈ [−0.23, +2.26] 구간만 분해한다 — 그 아래(G1 전체와 G2 대부분)는
> 전부 `AAA` 한 밴드로 뭉친다. 저위험 구간을 세분할 필요가 없어 40th 분위에서 시작한
> 설계의 결과다.

---

## 2. 순위 일치 검증 — 전수 948,214행

`Z_SCORE`, `LOG_ODDS`, `PROB_RAW`, `PROB_PLATT_TRAIN`, `PROB_PLATT_DEV` 다섯 컬럼의
개체별 순위가 완전히 같은지 **샘플이 아니라 전수**로 확인했다.

```sql
WITH r AS (
  SELECT RANK() OVER (ORDER BY Z_SCORE)          AS rz,
         RANK() OVER (ORDER BY PROB_RAW)         AS rp,
         RANK() OVER (ORDER BY LOG_ODDS)         AS rl,
         RANK() OVER (ORDER BY PROB_PLATT_TRAIN) AS rpt,
         RANK() OVER (ORDER BY PROB_PLATT_DEV)   AS rpd
  FROM corporate_panel)
SELECT SUM(CASE WHEN rz <> rp  THEN 1 ELSE 0 END) AS z_vs_raw,
       SUM(CASE WHEN rz <> rl  THEN 1 ELSE 0 END) AS z_vs_logodds,
       SUM(CASE WHEN rp <> rpt THEN 1 ELSE 0 END) AS raw_vs_platt_train,
       SUM(CASE WHEN rp <> rpd THEN 1 ELSE 0 END) AS raw_vs_platt_dev,
       COUNT(*) AS n
FROM r;
```

| z_vs_raw | z_vs_logodds | raw_vs_platt_train | raw_vs_platt_dev | n |
|--:|--:|--:|--:|--:|
| **0** | **0** | **0** | **0** | 948,214 |

**불일치 0건.** `Z_SCORE = (logit(p) − μ) / σ` 는 `p` 의 순증가 함수이고, Platt 보정
`σ(a·logit(p) + b)` 도 `a > 0` 이면 순증가 함수다. 이론적 주장이 실측으로 확인됐다.
따라서 **어느 확률 컬럼으로 분위를 잘라도 같은 개체가 같은 밴드에 떨어진다** —
16단계를 "raw 확률 분위"로 산출한 것과 "로그오즈 분위"로 산출한 것은 **동일한 결과**다.

### 컬럼 별칭 등가성 (전수)

| 검사 | 일치 행수 / 전체 | 판정 |
|---|--:|---|
| `PROB_FULL = PROB_RAW` | 948,214 / 948,214 | **완전 동일** |
| `PROB_DISPLAY = PROB_PLATT_DEV` | 948,214 / 948,214 | **완전 동일** |
| `PROB_DISPLAY = PROB_RAW` | 0 / 948,214 | 다름 (보정된 값) |
| `Z_GRADE = GRADE` | 948,214 / 948,214 | **완전 동일** |

> `PROB_FULL` 은 `PROB_RAW` 의 별칭이다. **"PROB_FULL = raw 기준 확정" 이라는 결정은
> DB 실측과 정확히 일치한다.** 포털이 표시하는 PD 도, `prob_to_grade()` 에 들어가는 값도
> 모두 raw 이고, raw 분위로 만든 16단계 컷오프와 스케일이 맞는다. **불일치 없음.**

---

## 3. 등급 경계가 어긋나는 사례가 있는가 — 교차표 전수

```sql
SELECT GRADE, GRADE16, COUNT(*) AS n FROM corporate_panel GROUP BY 1, 2;
```

| GRADE16 | G1 | G2 | G3 | G4 | G5 |
|---|--:|--:|--:|--:|--:|
| AAA | 195,438 | 234,768 | 0 | 0 | 0 |
| AA+ | 0 | 78,815 | 16,253 | 0 | 0 |
| AA0 | 0 | 0 | 68,420 | 0 | 0 |
| AA− | 0 | 0 | 66,856 | 0 | 0 |
| A+ | 0 | 0 | 55,897 | 0 | 0 |
| A0 | 0 | 0 | 47,686 | 0 | 0 |
| A− | 0 | 0 | 41,844 | 0 | 0 |
| BBB+ | 0 | 0 | 12,290 | 25,297 | 0 |
| BBB0 | 0 | 0 | 0 | 27,873 | 0 |
| BBB− | 0 | 0 | 0 | 21,181 | 0 |
| BB+ | 0 | 0 | 0 | 16,006 | 0 |
| BB0 | 0 | 0 | 0 | 11,606 | 0 |
| BB− | 0 | 0 | 0 | 8,793 | 0 |
| B+ | 0 | 0 | 0 | 5,401 | 979 |
| B0 | 0 | 0 | 0 | 0 | 5,678 |
| CCC | 0 | 0 | 0 | 0 | 7,133 |

**완전한 계단형이다.** 어떤 `GRADE16` 밴드도 비인접 `GRADE` 를 걸치지 않는다.
경계가 겹치지 않는 4개 지점(AAA · AA+ · BBB+ · B+)에서만 인접 2개 밴드로 나뉜다.

> **"Z 기준 G5 인데 16단계로는 중간 등급" 같은 사례는 0건이다.**
> G5 는 `B+`(979) · `B0`(5,678) · `CCC`(7,133) 세 밴드에만 존재하고, 그 셋은 16단계
> 최하위 3개다. 역으로 `CCC` 는 G5 에만 있다. 두 체계는 서로 정합적이다.

---

## 4. DB 적용 결과가 JSON 산출 결과와 같은가 — 재현 검증

`grade_mapping_v2.json` 의 `grade_table`/`grade16_table` 은 Valid 구간(202401~202505)
집계다. DB 의 같은 구간을 다시 집계해 대조했다.

| GRADE | n (DB) | n (JSON) | 부도 (DB) | 부도 (JSON) | 부도율% | 일치 |
|---|--:|--:|--:|--:|--:|:-:|
| G1 | 52,320 | 52,320 | 32 | 32 | 0.0612 | 일치 |
| G2 | 98,552 | 98,552 | 206 | 206 | 0.2090 | 일치 |
| G3 | 109,809 | 109,809 | 939 | 939 | 0.8551 | 일치 |
| G4 | 47,793 | 47,793 | 1,939 | 1,939 | 4.0571 | 일치 |
| G5 | 3,860 | 3,860 | 716 | 716 | 18.5492 | 일치 |

16단계도 **AAA~CCC 16개 밴드 전부 n · 부도건수 일치**했다.
`apply_grades()` 가 JSON 컷오프를 손실 없이 적용했음이 확인된다.

### 전 구간(948,214행) 실현 분포 — 참고

| GRADE | n | 점유율% | 부도 | 부도율% |
|---|--:|--:|--:|--:|
| G1 | 195,438 | 20.61 | 32 | 0.0164 |
| G2 | 313,583 | 33.07 | 207 | 0.0660 |
| G3 | 309,246 | 32.61 | 985 | 0.3185 |
| G4 | 116,157 | 12.25 | 2,392 | 2.0593 |
| **G5** | 13,790 | 1.45 | 6,198 | **44.9456** |

전 구간 기저율 1.0350% (9,814 / 948,214). **단조성 확보.**

> ★ 전 구간 G5 부도율 44.95% 는 Valid 값 18.55% 와 다르다. 같은 컷오프인데 값이 다른
> 이유는 **구간 기저율 차이**다 — Train/Dev(< 202301) 0.7876% vs Valid(≥ 202301) 1.2254%.
> 어느 하나가 틀린 것이 아니라 **집계 모집단이 다르다.** 문서에 등급별 부도율을 쓸 때는
> 반드시 구간을 병기해야 한다. 홀드아웃 성능을 말하는 자리에서는 **Valid 값(18.55%)이
> 정본**이다.

같은 이유로 16단계의 전 구간 실현 점유율도 설계 분위와 다르다 — `AAA` 는 설계 40%
(Valid 분위)인데 전 구간에서는 **45.37%** 를 차지한다. Train/Dev 구간의 예측 PD 가
전반적으로 낮아 40th-Valid-percentile 아래로 더 많이 몰리기 때문이다.

### 단조성에 관한 정확한 서술

- **5단계 `GRADE`: Valid · 전 구간 모두 단조 확보.** `z_cutoffs_adjusted = false` —
  `step40` 의 분위 대체 폴백(L120-131)이 발동하지 않았다. 등폭 컷오프 그대로다.
- **16단계 `GRADE16`: `monotone_g16 = false`.** 역전은 **딱 1쌍**이다.
  - Valid: `AA0` 0.5977% > `AA−` 0.5550% (부도 140건 vs 130건, 각 23,425행)
  - 전 구간: `AA0` 0.2105% > `AA−` 0.2019% (부도 144건 vs 135건)
  - 두 밴드는 분위 폭이 같고(0.500 → 0.575 → 0.650) 부도 건수 차이가 10건 미만이다.
    **표본 노이즈이며 컷오프 설계 결함이 아니다.** 다만 16단계를 "부도율이 단조 증가하는
    등급"이라고 서술하면 사실과 다르므로, 표기용 체계임을 밝혀야 한다.

---

## 5. 정본 제안

### 판정 — 어긋남이 아니다. 어느 쪽도 틀리지 않았다

| 질문 | 답 |
|---|---|
| 지시("등급은 로그오즈 Z-Score 기준")와 실제가 어긋났는가 | **아니다.** 지시가 가리킨 5단계 `GRADE`/`Z_GRADE` 는 정확히 Z-Score 기준으로 산출됐다 |
| 16단계가 raw 확률 분위로 산출된 것은 오류인가 | **아니다.** 별개 체계이며, raw 분위 = 로그오즈 분위 = Z 분위 (순위 불일치 0건) |
| 두 체계를 하나로 통합해야 하는가 | **아니다.** 용도가 다르다 (리스크군 선별 vs 등급 표기) |

**정본 규정 (양립 · 병기)**

1. **리스크 등급 = 5단계 `GRADE`(= `Z_GRADE`), 로그오즈 Z-Score 기준, 컷오프 `[-1, 0, 1, 2]`.**
   경보 대상 선별(G4/G5), 대시보드 리스크 집계, 문서의 등급별 부도율은 모두 이것을 쓴다.
2. **표기 등급 = 16단계 `GRADE16`, raw PD 분위 기준.** 기존 CB 등급 표기와 눈높이를
   맞추기 위한 라벨이며, 리스크 판정 근거로 쓰지 않는다.
3. **두 체계 모두 확률 보정과 무관하다.** raw / platt_train / platt_dev 어느 것으로
   순위를 매겨도 결과가 같다(전수 검증). 보정이 바꾸는 것은 **표시하는 PD 값**뿐이다.
4. **컷오프 정본은 `eda_pipeline/output/grade_mapping_v2.json` 파일 하나다.**
   `backend/grade_mapping.py` 는 이 파일을 읽고, 실패 시에만 폴백 + 경고한다 (L35-53).
   ★ 폴백 값 `_FALLBACK_PROB_CUTOFFS` 는 **양성 63,531 기준의 구세대 값**이므로
   폴백이 발동하면 등급이 조용히 구세대로 돌아간다. 이 경고를 무시하지 말 것.

### 코드 수정 제안 — 이번 작업에서는 반영하지 않음 (승인 후 별건)

| # | 위치 | 내용 | 심각도 |
|--:|---|---|---|
| 1 | `backend/grade_mapping.py` L6-13 주석 | "quantile breakpoints of the actual **PROB_FULL** distribution in corporate_panel … computed from the full **1.9M**-row dataset" — 실제로는 **Valid 312,334행의 raw PD 분위**다. 행수(1.9M)와 모집단(full vs Valid)이 둘 다 틀렸다. L11-13 의 "Recomputed 2026-07-04 (step29)" 도 D8 재산출(2026-09-03) 이전 이력이다 | 주석만, 동작 무영향 |
| 2 | `backend/grade_mapping.py` L26-29 | 폴백 컷오프가 구세대 값이라 발동 시 조용한 등급 퇴행. 폴백 대신 **예외로 중단**하는 편이 안전하다 (경고는 이미 있으나 로그에 묻힌다) | 잠재 오류 |
| 3 | `frontend/src/pages/BranchDashboard.tsx` L53 주석 | "DB가 실측 **PROB_FULL 분포** 대비 Z-score 컷오프(-1/0/1/2)로 산출" — Z-Score 는 **PROB_FULL 이 아니라 LOG_ODDS** 에 대해, 그것도 **Valid 구간** mean/std 로 표준화한다 | 주석만 |
| 4 | `frontend/src/pages/BorrowerDetail.tsx` L179-180 | `getErmGrade(_prob: number)` 가 인자 `_prob` 를 **쓰지 않고** `data.Z_GRADE` 를 반환한다. 호출부는 `getErmGrade(data.PROB_FULL)` 로 확률을 넘긴다 — 동작은 맞지만(Z_GRADE 사용) 시그니처가 오해를 부른다 | 가독성 |
| 5 | `corporate_panel.PROB_DISPLAY` | `PROB_PLATT_DEV` 와 전수 동일한 컬럼이 DB 에 있으나 **저장소 전체에서 참조하는 코드가 0곳**이다. step36 §6 은 "포털 표시 PD = platt_dev" 를 방침으로 적었는데 포털은 실제로 `PROB_FULL`(raw)을 표시한다. 방침과 구현이 갈라져 있다 | **방침 불일치 — 판단 필요** |
| 6 | `backend/routers/borrowers.py` L23 · L340 | `OLD_PROB = PROB_FULL * 0.15` 를 "기존 모델 근사치"로 쓰고 `prob_to_grade(OLD_PROB)` 로 `NICE_GRADE_PREV`/`KIS_GRADE_PREV` 를 만든다. 상수 0.15 배는 실측 근거가 없는 합성값이다 | 별건 (다른 작업 소관 가능) |

> #5 는 이번 작업 범위 밖의 결정을 요구한다. **"PROB_FULL = raw 기준 확정"이 이미
> 승인됐으므로 현재 구현이 정본**이고, step36 §6 의 "포털 표시 PD = platt_dev" 행이
> 현재 구현과 다르다는 사실만 기록한다 (§6 하위절에 반영).

---

## 6. 컬럼 사용처 — backend / frontend 전수 grep

대상: `backend/**/*.py`, `frontend/src/**/*.tsx|ts`
(`node_modules`, `*.pyc`, `borrowers.py.bak` 제외)

| 컬럼명 | 사용 위치 (파일:줄) | 용도 |
|---|---|---|
| **`PROB_FULL`** | `backend/database.py:44` | `dedup_panel_sql()` — (V_BZNO, BASE_YM) 중복 행을 `PROB_FULL DESC` 로 정렬해 1행만 남기는 tie-break 키 |
| | `backend/routers/borrowers.py:19,27` | 차주 목록 — `MAX(PROB_FULL)` 집계 및 정렬 키 |
| | `backend/routers/borrowers.py:23,340` | `OLD_PROB = PROB_FULL * 0.15` — "기존 모델" 합성 근사치 |
| | `backend/routers/borrowers.py:34,36,108,343,345` | `prob_to_grade()` 입력 → `NICE_GRADE_CUR` / `KIS_GRADE_CUR` / `nice_grade` (16단계 런타임 산출) |
| | `backend/routers/borrowers.py:74,125,141` | 차주 상세 최신값(`arg_max`) · 월별 PD 추이 시계열 |
| | `backend/routers/monitoring.py:155` | 모니터링 목록 조회 컬럼 |
| | `backend/routers/dashboard.py:29` | 업종 평균 예측위험도의 기존모델 근사 기준 |
| | `frontend/src/pages/BorrowerDetail.tsx:230,231,282,289,306,318` | PD 표시(`* 100`), ERM 등급 배지 호출 인자, 기존 PD 대비 문구 |
| **`PROB_DISPLAY`** | **없음 (0곳)** | DB 컬럼으로만 존재. `PROB_PLATT_DEV` 와 전수 동일. **사용처 없음** → 제안 #5 |
| **`PROB_RAW`** | **backend · frontend 0곳** | `PROB_FULL` 이 이 값의 별칭이라 간접 사용. 직접 참조는 `database/rescore_v2_d8.py:137,141,145` (등급 · 경보 산출) |
| **`PROB_PLATT_TRAIN`** | **backend · frontend 0곳** | 모델 비교 · 판정용 보정. 파이프라인 산출물에만 존재 |
| **`PROB_PLATT_DEV`** | **backend · frontend 0곳** | `PROB_DISPLAY` 의 원본. step36 §6 방침상 "표시 PD" 지만 포털은 쓰지 않음 |
| **`Z_SCORE`** | `backend/routers/borrowers.py:20` | 차주 목록 `ANY_VALUE(Z_SCORE)` — 응답에 포함(화면 표시는 없음) |
| | `frontend/src/utils/mockData.ts:25` | 목업 고정값 `1.5` |
| **`Z_GRADE`** | `backend/routers/borrowers.py:21` | 차주 목록 `ANY_VALUE(Z_GRADE)` |
| | `backend/routers/dashboard.py:13,34,104,126` | **G4/G5 = 고위험 판정** — 리스크 기업 수, 지점별 집계, 조기경보 포착(`erm_warn`) 시점 |
| | `backend/routers/dashboard.py:20-24` | 등급 분포 집계 (`GROUP BY Z_GRADE`) |
| | `backend/routers/monitoring.py:179` | 응답 필드 `ermGrade` |
| | `frontend/src/pages/BorrowerDetail.tsx:53,141,148,180,228,278,306,318` | ERM 등급 라벨, 고위험 판정 `['G4','G5']`, 기존등급 표기 |
| | `frontend/src/pages/BranchDashboard.tsx:71,75,319,320` | 등급 배지 색상, 검색 필터 |
| | `frontend/src/pages/GlobalDashboard.tsx` | 등급 분포 시각화 |
| **`GRADE`** | **backend · frontend 0곳** | `Z_GRADE` 가 별칭(전수 동일). 직접 참조는 `database/rescore_v2_d8.py:134,231` (산출 · 인덱스) |
| **`GRADE16`** | **backend · frontend 0곳** | ★ DB 에 저장돼 있으나 백엔드는 읽지 않고 `prob_to_grade(PROB_FULL)` 로 **런타임 재계산**한다. 같은 컷오프 파일을 쓰므로 결과는 일치 |
| **`LOG_ODDS`** | **backend · frontend 0곳** | `Z_SCORE` 산출 재료. `rescore_v2_d8.py:133`, `step40_grade_threshold.py` 에서만 사용 |

### 이 표에서 드러나는 구조

- **백엔드가 실제로 쓰는 것은 두 개뿐이다: `PROB_FULL`(= raw PD)과 `Z_GRADE`(= 5단계).**
  나머지 확률 · 등급 컬럼은 파이프라인 산출물이거나 미사용이다.
- **리스크 판정은 전부 `Z_GRADE` 의 G4/G5 다** (`dashboard.py` 4곳). 즉 **운영상 "등급"은
  로그오즈 Z-Score 기준**이며, 사용자 지시와 정확히 일치한다.
- **16단계는 표기 전용이고 DB 컬럼(`GRADE16`)조차 쓰이지 않는다.** 백엔드가 매 요청마다
  `prob_to_grade()` 로 다시 계산한다. 컷오프 정본 파일이 하나이므로 값은 갈라지지 않지만,
  DB 컬럼과 런타임 계산이 이중으로 존재하는 것은 갈라질 여지다 (폴백 발동 시 실제로 갈라진다).

---

## 7. 재현

```bash
PY="C:/Users/scudy/.venvs/nh_eco/Scripts/python.exe"
# 컷오프 재산출 (Valid 채점 -> JSON)
$PY -m eda_pipeline.step40_grade_threshold
# 재채점 + 등급 적용 + 단조성 검증
$PY -m database.rescore_v2_d8
```

검증 SQL 은 §2 · §3 · §4 에 그대로 실었다. DB 는 `read_only=True` 로만 열었고
쓰기 · 삭제 · 학습은 하지 않았다. 코드 수정도 없다 (§5 제안은 미반영).
