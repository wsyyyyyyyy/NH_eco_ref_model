# STAGE 6 Ablation 시나리오 계획서

작성일: 2026-08-30 · 상태: **승인 완료. A축 실행 완료** (결과: `step30_ablation_A_results.md`)
기준 DB: `database/portal_v2.duckdb` (948,214행 / 268컬럼)

---

## 0. 결과표 상단에 반드시 들어갈 한계 문구

> 이번 Ablation 은 **거시 지표를 전부 제외한 기업 고유 피처만으로** 수행했다.
> 원본 모델(README Valid AUC 0.9005)은 실제 거시 172개를 포함한 모델이다.
> 이 체크아웃의 거시 데이터는 합성 난수이므로(아래 §5), 원본을 충실히 재현하지 못한다.
> **따라서 이 표의 AUC 절대값을 0.9005 와 비교해서는 안 된다.**
> A0 대비 상대 변화(ΔAUC)만 해석 대상이다.

이 문구는 결과표 상단과 STAGE 7 보고서에 각각 넣는다.

---

## 1. 피처 집합 정의

| 구분 | 개수 | 처리 |
|---|---:|---|
| DB 컬럼 | 268 | |
| − NON_FEATURE (키/메타/타겟) | 12 | 제외 |
| − LEAK_CONFIRMED | 10 | 패널에 부재 (§4 참조) |
| − LEAK_SUSPECT | 3 | 기본 제외, A3~A7 에서 on |
| − `V_BRANCH_CODE` (포털 데모용) | 1 | 제외 |
| = 전체 피처 후보 | **259** | |
| − 순수 거시지표 (합성) | 91 | 제외 |
| − 거시 × 기업 상호작용항 (합성) | 10 | 제외 |
| − 무분산 컬럼 | 4 | 제외 |
| − CG01 / C302 계열 | 4 | **A0 에서 제외** (아래 ★) |
| = **A0 기준선 피처** | **150** | |

목록은 `eda_pipeline/output/macro_columns_v2.json` 에 고정 저장했다.

무분산 4개: `JEMU_debt_dependency_capped`, `JEMU_asset_turnover_end_capped`,
`JEMU_asset_turnover_avg_capped`, `HAS_OBV_YN` — 패널 전체에서 값이 1개뿐이다.
거시가 아니라 파생 계산이 전부 0으로 떨어진 컬럼이며, 별도 확인 대상이다.

### ★ 지시하신 표에서 1건 조정이 필요합니다

지시서의 A4 = `A0 + CG01_KIS_SCORE_MISSING_YN 만`, A6 = `A0 + C302_..._MISSING_YN 만`
인데, **`CG01_MISSING_YN` / `C302_MISSING_YN` 은 `LEAK_SUSPECT` 에 없어서 이미 A0
안에 들어 있습니다.** 그대로 두면 **A4 ≡ A0, A6 ≡ A0** 가 되어 제안 58 의 분리
검증이 성립하지 않습니다.

따라서 A0 에서 CG01/C302 계열을 전부 빼고, A3~A6 에서 단계적으로 되넣는 구성으로
바꿉니다. A0 에서 추가로 빠지는 4개:

`CG01_MISSING_YN`, `C302_MISSING_YN`, `C302_IS_NR_YN`, `C302_IS_R_YN`

`C302_IS_NR_YN`(무등급) / `C302_IS_R_YN`(등급보유) 는 점수가 아니라 **평가 이력
유무** 정보이므로 A6 쪽(이력 유무 팔)에 넣었습니다.

---

## 2. [A축] 피처 토글 — 패널 재생성 불필요

기준 패널: 현재 최종형 (STAGE 1~5 전부 적용, obv 스파인)

| ID | 구성 | 피처 수 | 실행 | 예상 |
|---|---|---:|---|---:|
| **A0** | 기준선. LEAK_CONFIRMED + LEAK_SUSPECT + CG01/C302 계열 전부 제외 | 150 | 가능 | ~3분 |
| **A1** | A0 + `COPR_OPNP_C` | 151 | **가능 (조건부)** | ~3분 |
| **A2** | A0 + CRIF 계열 4개 | 154 | **가능 (조건부)** | ~3분 |
| **A3** | A0 + `CG01_KIS_SCORE` + `CG01_MISSING_YN` | 152 | 가능 | ~3분 |
| **A4** | A0 + `CG01_MISSING_YN` 만 | 151 | 가능 | ~3분 |
| **A5** | A0 + `C302_CRI_ORD` + C302 계열 3개 | 154 | 가능 | ~3분 |
| **A6** | A0 + `C302_MISSING_YN` + `C302_IS_NR_YN` + `C302_IS_R_YN` | 153 | 가능 | ~3분 |
| **A7** | A0 + LEAK_CONFIRMED 5 + LEAK_SUSPECT 3 + CG01/C302 4 (누수 상한) | 162 | 가능 | ~3분 |
| **A8** | A0 − JEMU sentinel 파생 39개 | 111 | 가능 | ~3분 |

**A축 합계 예상 ~25~35분.** 실측 근거: 154피처 / Train 579,859행에서
100 부스팅 라운드 = 4.4초. 2000 라운드 상한이어도 1.5분, 조기종료로 더 짧다.

### A1 / A2 의 "조건부" — 컬럼 복원이 필요합니다

`LEAK_CONFIRMED` 10개는 **`portal_v2.duckdb` 에 존재하지 않습니다.** step5 가
떨어뜨렸습니다. "패널에 남긴 설계 덕분에 A축이 가능하다"는 전제가 이 패널에는
성립하지 않습니다.

다만 **재생성 없이 복원 가능합니다.** step5 이전 산출물
`eda_pipeline/output/nh_panel_full_obv.parquet` (951,908행 / 149컬럼)에 살아 있고,
`(V_BZNO, BASE_YM)` 조인 매칭률이 **100.0000%** 입니다 (중복 그룹 0).

| 컬럼 | 조인 후 nonnull | 고유값 |
|---|---:|---:|
| `COPR_OPNP_C` | 948,214 (100%) | 13 |
| `CRIF_EVENT_CNT` | 10,243 (1.08%) | 11 |
| `CRIF_RSN_AM_SUM` | 10,243 | 1,522 |
| `CRIF_OVD_AM_SUM` | 10,243 | 1,516 |
| `CRIF_WORST_RSNC` | 10,243 | 5 |

→ 러너가 A1/A2/A7 에서만 이 parquet 을 조인해 붙입니다. DB 는 읽기 전용이므로
`portal_v2.duckdb` 에 컬럼을 추가하지 않고 메모리에서만 붙입니다.

**주의**: 원본 gain 은 `CRIF_CRDBD_RSNC` 등 **원천 컬럼**(36.34%) 기준이고,
여기서 붙이는 것은 STAGE 1 이후 **(V_BZNO, 연도) 집계 컬럼** 4개입니다.
누수 성격은 같지만 gain 수치를 1:1 비교할 수는 없습니다. 표에 각주로 답니다.

---

## 3. [B축] 패널 변종 — 재생성 필요

각 변종은 해당 수정 하나만 되돌리고 나머지는 최종형 유지. 피처 구성은 A0 고정.

| ID | 되돌릴 수정 | 재생성 범위 | 실행 | 예상 |
|---|---|---|---|---:|
| **B1** | 행 중복 미제거. `generate_12m_target` 을 `merge(on='V_BZNO')` 로 복원 | step5 만 | **가능** | 20~40분 |
| **B2** | 재무 as-of → 연 단위 조인 복원 | step1 → step2 → step5 | **가능** | 60~120분 |
| **B3** | STAGE 1~5 전부 미적용 (원본 파이프라인) | 없음 (기존 파일 사용) | **가능 (재정의)** | 15~25분 |

### B1 — 근거 확인 완료
`eda_pipeline/step5_panel_prep.py.bak:26` 에 구 코드가 그대로 있습니다.
```
df = df.merge(default_records, on='V_BZNO', how='left')      # 다중부도 기업 전 구간 복제
df['IS_BUDO_12M'] = ((df['MONTHS_TO_DEFAULT'] > 0) & (df['MONTHS_TO_DEFAULT'] <= 12)).astype(int)
```
현재 코드는 `merge_asof(direction='forward', allow_exact_matches=False)` 입니다.
step5 는 `nh_panel_full_obv.parquet` 만 읽으므로 step1~2 재실행이 불필요합니다.
거시를 안 쓰므로 step6 도 건너뜁니다.
**B1 은 행수가 늘어나므로 `scale_pos_weight` 가 크게 달라집니다 — 재계산 필수.**

### B2 — 실행 가능하나 가장 김
`input/` 원천 11개 파일 전부 존재합니다. `step2_integrate.py.bak` 도 있습니다.
`step2_integrate.py:351` 의 `pd.merge_asof(...)` 를 구 연 단위 조인으로 되돌립니다.
JEMU 원천이 35MB 라 step1 로딩부터 다시 돕니다.

### B3 — 재정의가 필요합니다
`nh_panel_full.csv` 는 있지만(367MB / 70컬럼) **타겟 `IS_BUDO_12M` 이 없습니다**
(`IS_BUDO_YN` 만 있음). 따라서 그대로는 학습할 수 없습니다.

지시하신 대로 **"거시 제외 + 기존 전처리" 조건으로 재정의**하고, 타겟만 구
`merge(on='V_BZNO')` 방식으로 생성해 붙입니다. 표에 다음과 같이 기록합니다:

> B3 = legacy 패널 70컬럼 + 구 방식 타겟 생성. 원본 모델과 달리 거시 172개가
> 없으므로 **원본 재현이 아니라 "STAGE 1~5 미적용 상태의 기업 고유 피처 성능"**이다.

우선순위는 지시대로 **B1 > B2 > B3**. 시간이 부족하면 B3 부터 포기합니다.

---

## 4. [C축] 구성 최적화 — A축 결과 확인 후

| ID | 구성 | 실행 | 예상 |
|---|---|---|---:|
| C1 | 업종 피처 `STD_INDS_SECTION` 만 | 가능 | ~3분 |
| C2 | 업종 피처 `STD_INDS_MID2` 만 | 가능 | ~3분 |
| C3 | 둘 다 (= A0 현재 상태) | A0 재사용 | 0분 |
| C4 | Lean: A0 gain 상위 N개 (N 은 A0 결과 보고 후 결정) | 가능 | ~3분 |

패널에 존재하는 업종 피처는 `STD_INDS_SECTION`, `STD_INDS_MID2` 2개입니다
(원본 `STD_INDS_CFC` 는 고유값 1,147개라 `NON_FEATURE` 로 제외되어 있습니다).

---

## 5. [D축] 보류 — 거시 실데이터 확보 후

결과표에 **"실데이터 미확보로 미실행"** 으로 표기합니다.

| ID | 구성 | 사유 |
|---|---|---|
| D1 | A0 + 거시 원본 (상호작용 없이) | 거시 91개가 합성 난수 |
| D2 | A0 + 거시 상호작용항 | 동일 |
| D3 | D2 에서 fx actual vs hybrid | 동일 |
| D4 | MACRO_REDUCE 172 vs 87 | 동일 |
| 5-3 | 업종별 거시 민감도 계수 | 동일 |

합성 판정 근거: `KOSPI_log_ret` 평균 **0.323**(월 32% 수익률), min −1.445 / max 2.334.
`base_rate_diff12` 가 202104 에 **1.643**, 202106 에 −1.050. 기준금리 12개월 차분이
이렇게 움직이지 않습니다. `default_rng(20260829)` 표준정규 난수입니다.

거시 재수집(3번 병행 작업)은 별도로 진행하며 Ablation 을 막지 않습니다.

---

## 6. 공통 규칙 (지시 반영)

- 학습 파라미터를 전 시나리오 동일 고정 (`REG_PARAMS_TEMPLATE`).
- `scale_pos_weight` 는 시나리오별 Train 부분집합에서 매번 재계산.
  B1 은 양성이 6배 이상 늘어나므로 고정값이면 비교가 무의미해집니다.
- 분할: Train(~202309) / **Dev(202310~202312, early stopping 전용)** / Valid(202401~).
  Valid 는 최종 1회 평가에만 사용. 경계는 `eda_pipeline/split_spec.py` 단일 정의.
- 시나리오별 출력: Train/Dev/Valid AUC, Gini, K-S, PSI(Train↔Valid), gain 상위 15개.
- 모델은 `lgbm_v2_<scenario>.txt` 로 저장. 기존 모델 2개는 읽기만 (가드로 강제).
- 결과표에 A0 기준 ΔAUC 병기.

**분할 관련 확인 필요 1건**: 지시서에는 `Train(~202312)` 이라고 되어 있으나
Dev 가 202310~202312 이므로 실제 Train 은 `~202309` 입니다. 그렇지 않으면 Dev 가
Train 에 포함되어 early stopping 이 무의미해집니다. `~202309` 로 구현했습니다.

---

## 7. 실행 전 확인 4건 — 결과

전문: `eda_pipeline/output/validation/STAGE6_PREFLIGHT.md`
재현: `python -m eda_pipeline.step30_stage6_preflight`

### (1) LEAK_CONFIRMED 부재를 assert 로 증명 — 통과

```
DB 컬럼 268개 -> 학습 투입 피처 259개
제외: NON_FEATURE 12 / LEAK_CONFIRMED 10 / LEAK_SUSPECT 3 / V_BRANCH_CODE 1
assert not leaked  ->  통과
```

**단, "제외했다"가 아니라 "들어온 적이 없다"입니다.** 10개 전부 `DB에존재=False`
입니다. 그래서 A1/A2 에 §2 의 복원 절차가 필요합니다.
`LEAK_SUSPECT` 3개는 전부 DB 에 있고 기본 피처에서 빠져 있어 on/off 가 됩니다.

### (2) early stopping eval_set 이 Dev 인가 — 통과

AST 로 소스를 파싱해 확인합니다.
```
step7_modeling_shap.py:80               eval_set   = [(X_dev, y_dev)]   -> Dev 전용 OK
step23_retrain_production_models.py:155 valid_sets = [dev_set]          -> Dev 전용 OK
판정: 통과 — Valid 는 eval_set 에 들어가지 않는다
```
step7 은 이번에 고쳤습니다 (기존: `eval_set=[(X_valid, y_valid)]`).
러너 작성 후 이 검사를 다시 돌립니다.

### (3) scale_pos_weight 시나리오별 재계산 — 확인

| 구간 | 행수 | 양성 | 부도율 | scale_pos_weight |
|---|---:|---:|---:|---:|
| TRAIN | 579,859 | 5,286 | 0.9116% | **108.70** |
| DEV | 56,021 | 696 | 1.2424% | 79.49 |
| VALID | 312,334 | 3,832 | 1.2269% | 80.51 |

preflight 가 러너 소스의 `scale_pos_weight=` 가 상수 리터럴인지 AST 로 검사합니다.

### (4) 기존 모델 파일 md5 — 작업 전후 동일

```
lgbm_12m_model.txt        md5=4e02cd3738dfae657da84edd906b9359   912,630 bytes
lgbm_12m_lean_model.txt   md5=25d1cc5bfe091c4549fd78fe4549fec7   901,565 bytes
```
`config.save_booster()` 로 이 경로에 쓰면 `PermissionError`. 가드 확인 완료.

---

## 8. 승인 요청 사항

1. §1 ★ — A0 에서 CG01/C302 계열 4개를 빼는 조정 (A4/A6 가 A0 와 같아지는 문제)
2. §2 — A1/A2 를 `nh_panel_full_obv.parquet` 조인으로 복원하는 방식
3. §3 — B3 를 "거시 제외 + 기존 전처리 + 구 방식 타겟" 으로 재정의
4. §6 — Train 경계를 `~202309` 로 구현한 것

승인되면 A축 9회부터 실행합니다.


---

# 부록 A — LEAK_CONFIRMED 원천/집계 대조표 (확인 1)

지시서의 원래 목록은 **6개**였다. `leaky_cols.py` 의 `LEAK_CONFIRMED` 는 **10개**인데,
STAGE 2 에서 CRIF 를 재구성하며 이름이 바뀌었고 **원천명과 집계명을 둘 다** 넣어
두었기 때문이다. 중복 등재가 아니라 계보가 다른 두 세대의 이름이다.

| # | 원천명 (지시서 6개 / legacy 패널) | STAGE 2 집계명 | 집계 방식 | v2 패널 | 복원 |
|---|---|---|---|---|---|
| 1 | `COPR_OPNP_C` | (동일) | 변환 없음 | 없음 | **가능** — step5 이전 패널 |
| 2 | `CRIF_CRDBD_RSNC` | `CRIF_WORST_RSNC` | `min` (가장 심각한 코드) | 없음 | **가능** — 단 min 집계본 |
| 3 | `CRIF_SUM(CRDBD_RSN_AM)` | `CRIF_RSN_AM_SUM` | `sum` | 없음 | **가능** |
| 4 | `CRIF_SUM(CRDBD_OVD_AM)` | `CRIF_OVD_AM_SUM` | `sum` | 없음 | **가능** |
| 5 | `CRIF_MAX(CRDBD_RLS_RSNC)` | — | 패널로 넘기지 않음 | 없음 | **가능** — 원천 TXT 에서 |
| 6 | `CRIF_MAX(CRDBD_RLS_OCU_DT)` | — | 패널로 넘기지 않음 | 없음 | **가능** — 원천 TXT 에서 |
| — | (원천에 대응 없음) | `CRIF_EVENT_CNT` | `size` (신규) | 없음 | **가능** |

`LEAK_CONFIRMED` 10 = 원천 6 + 집계 4. 개념적으로는 **누수원 5종**이다
(폐업코드 / 사유코드 / 사유금액 / 연체금액 / 해제정보) + 신규 집계 1종(건수).

5·6번을 step2 가 넘기지 않은 이유는 `step2_integrate.py:667` 에 명시되어 있다 —
부도기업 182건 전부(100%)가 부도 이후 해제이고 값의 92.3%가 결측인 추출시점
스냅샷이다. 원천 프레임에는 남아 있어 A7 에서 `(V_BZNO, 연도)` 집계로 되붙였다.

### A7 실제 피처 수 (재산출)

```
A0 150
 + COPR_OPNP_C            1
 + CRIF 집계              4   (EVENT_CNT / RSN_AM_SUM / OVD_AM_SUM / WORST_RSNC)
 + CRIF 해제              2   (RLS_OCU_DT / RLS_RSNC — 원천에서 복원)
 + CG01 계열              2   (KIS_SCORE / MISSING_YN)
 + C302 계열              5   (CRI_ORD / IS_D_YN / MISSING_YN / IS_NR_YN / IS_R_YN)
= A7                    164
```

실행 결과와 일치한다 (A7 피처 164). 계획서 §2 의 "LEAK_CONFIRMED 5" 는
"복원분 7"(COPR 1 + CRIF 집계 4 + CRIF 해제 2)로 정정한다.

---

# 부록 B — A2 가 측정하는 누수의 성격 (확인 2)

**표 각주로 반드시 함께 적을 것:**

> A2 의 CRIF 4개는 STAGE 2 에서 **행 폭증만 고친 집계본**이다.
> 조인은 여전히 `(V_BZNO, 연도)` 단위이므로 **시점 누수는 그대로 남아 있다**
> (`step2_integrate.py:679` 가 `CRDBD_OCU_YY` 를 `str[:4]` 로 잘라 월을 버린다).
> 2021년 1월 행이 2021년 11월 발생 신용불량을 본다.
> 또한 원본 모델 gain 36.34% 는 **원천 컬럼** 기준이고 A2 는 **집계 컬럼**
> 기준이므로 gain 수치를 1:1 비교할 수 없다.
> 즉 A2 의 +0.0679 는 "집계로 정리했으나 시점 누수는 남은 CRIF" 의 효과다.

### 원천 데이터는 월 단위다 — B4 가 가능한 근거

`CRDBD_OCU_YY` 는 이름의 `_YY` 와 달리 **YYYYMM 6자리**다.
전 6,906행이 길이 6이고 고유값이 63개(= 월)다. `202508`, `202205` 등.

**시점 누수는 데이터의 한계가 아니라 가공 과정에서 만들어졌다.**
따라서 B4 는 원천만으로 완전히 구현 가능하다.

---

# 부록 C — B축 우선순위 (확인 2 반영)

**B1 > B4 > B2 > B3** 로 조정한다.

| ID | 구성 | 재생성 범위 | 예상 |
|---|---|---|---:|
| B1 | 행 중복 미제거 (`merge(on='V_BZNO')` 복원) | step5 만 | 20~40분 |
| **B4** | **CRIF 월 단위 조인 + `BASE_YM` 이전 발생분만 → "최근 12개월 내 발생 건수"** | 원천 조인만 (패널 재생성 불필요) | **10~20분** |
| B2 | 재무 as-of → 연 단위 조인 복원 | step1→2→5 | 60~120분 |
| B3 | STAGE 1~5 미적용 (거시 제외 + 구 방식 타겟으로 재정의) | 기존 파일 | 15~25분 |

B4 는 패널 재생성이 필요 없다. A1/A2 와 같은 메모리 조인 경로를 쓰면 되므로
예상보다 싸다. A2 대비 얼마가 남는지가 "누수 변수를 버리는 대신 살려 쓸 수
있는가"의 답이 된다.
