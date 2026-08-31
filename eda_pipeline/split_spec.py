"""
======================================================================
Train / Dev / Valid 경계 — 단일 정의
======================================================================
step7 / validation_common / STAGE 6 Ablation 러너가 모두 여기를 import 한다.
세 곳이 각자 상수를 들고 있으면 어느 하나가 어긋났을 때 조용히 다른 실험이 된다.

  TRAIN  202101 ~ 202309   학습
  DEV    202310 ~ 202312   early stopping 전용. TRAIN 의 마지막 3개월을 떼어냈다.
  VALID  202401 ~ 202505   진짜 홀드아웃. 학습 중 단 한 번도 보지 않는다.

DEV 를 따로 두는 이유: 기존 step7 은 eval_set 에 VALID 를 넣고 early stopping 을
한 뒤 그 VALID AUC 를 최종 지표로 보고했다. 정지 시점이 VALID 에 맞춰지므로
보고값이 낙관적으로 편향되고, 시나리오별 정지 시점이 각자 VALID 에 최적화되어
Ablation 비교 자체가 무효가 된다.

BASE_YM 은 v2 스키마에서 VARCHAR 다. 문자열 비교가 사전순 = 시간순이므로
6자리 YYYYMM 에서는 안전하다. 정수 컬럼을 다룰 때는 int(...) 로 변환해 쓴다.
"""

from __future__ import annotations

DEV_START = "202310"
DEV_END = "202312"
TRAIN_END = "202312"      # SPLIT=='TRAIN' 의 마지막 달 (DEV 포함)
VALID_START = "202401"

DEV_START_INT = int(DEV_START)
DEV_END_INT = int(DEV_END)
TRAIN_END_INT = int(TRAIN_END)
VALID_START_INT = int(VALID_START)


def three_way_masks(base_ym):
    """pandas Series(BASE_YM) -> (train, dev, valid) 불리언 마스크.

    dtype 이 문자열이든 정수든 동작한다.
    """
    s = base_ym
    if str(s.dtype).startswith(("int", "float")):
        return (s < DEV_START_INT,
                (s >= DEV_START_INT) & (s <= DEV_END_INT),
                s >= VALID_START_INT)
    s = s.astype(str)
    return (s < DEV_START,
            (s >= DEV_START) & (s <= DEV_END),
            s >= VALID_START)
