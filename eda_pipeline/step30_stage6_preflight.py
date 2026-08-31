"""
======================================================================
STAGE 6 착수 전 필수 확인 4건
======================================================================
Ablation 을 돌리기 전에 아래를 코드로 증명한다. 말로 하지 않는다.

  1) 학습에 실제로 투입되는 features 리스트를 출력하고,
     LEAK_CONFIRMED 가 하나도 없는지 assert 통과를 증명
  2) early stopping 의 eval_set 이 Dev셋인지 코드로 확인
  3) scale_pos_weight 가 각 시나리오의 실제 클래스 비율로 재계산되는지 확인
  4) 기존 모델 파일 2개의 md5 출력 (작업 전후 비교용)

Usage
-----
    python -m eda_pipeline.step30_stage6_preflight
"""

from __future__ import annotations

import ast
import hashlib
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import pandas as pd

from eda_pipeline import config, split_spec
from eda_pipeline.leaky_cols import (LEAK_CONFIRMED, LEAK_SUSPECT, NON_FEATURE,
                                     feature_columns)

RULE = "=" * 78
SUB = "-" * 74

# 포털 데모 전용 컬럼. 피처가 아니다.
EXTRA_EXCLUDE = ["V_BRANCH_CODE"]


def _hr(title: str) -> None:
    print("\n" + RULE)
    print(title)
    print(RULE)


# ── 1. 피처 리스트 + 누수 assert ──────────────────────────────────────
def check_1_features() -> list[str]:
    _hr("[확인 1] 학습 투입 features 와 LEAK_CONFIRMED 제외 증명")
    con = config.connect_db("v2")
    try:
        cols = con.execute(
            "SELECT * FROM " + config.PANEL_TABLE + " LIMIT 0").df().columns.tolist()
    finally:
        con.close()

    df_stub = pd.DataFrame(columns=cols)
    features = feature_columns(df_stub, target="IS_BUDO_12M",
                               include_suspect=False, extra_exclude=EXTRA_EXCLUDE)

    print("  DB 컬럼 총 %d개 -> 학습 투입 피처 %d개" % (len(cols), len(features)))
    print("  제외: NON_FEATURE %d / LEAK_CONFIRMED %d / LEAK_SUSPECT %d / 기타 %d"
          % (len(NON_FEATURE), len(LEAK_CONFIRMED), len(LEAK_SUSPECT), len(EXTRA_EXCLUDE)))

    print("\n  " + SUB)
    print("  LEAK_CONFIRMED 정의 및 패널 내 존재 여부")
    print("  " + SUB)
    present = []
    for c in LEAK_CONFIRMED:
        in_db = c in cols
        if in_db:
            present.append(c)
        print("    %-32s DB에존재=%-5s  피처에포함=%s"
              % (c, str(in_db), c in features))

    leaked = [c for c in features if c in set(LEAK_CONFIRMED)]
    assert not leaked, "LEAK_CONFIRMED 가 피처에 남아 있다: %s" % leaked
    print("\n  assert not leaked  ->  통과")
    print("    LEAK_CONFIRMED %d개 중 패널에 실재하는 %d개 전부 제외됨"
          % (len(LEAK_CONFIRMED), len(present)))

    print("\n  " + SUB)
    print("  LEAK_SUSPECT (기본 제외. S2/S3 에서 on/off 비교)")
    print("  " + SUB)
    for c in LEAK_SUSPECT:
        print("    %-32s DB에존재=%-5s  기본피처포함=%s"
              % (c, str(c in cols), c in features))

    print("\n  " + SUB)
    print("  학습 투입 피처 %d개 전체 목록" % len(features))
    print("  " + SUB)
    for i in range(0, len(features), 4):
        print("    " + "  ".join("%-33s" % c for c in features[i:i + 4]).rstrip())
    return features


# ── 2. early stopping eval_set 이 Dev 인가 ────────────────────────────
def _eval_set_sources(path: Path):
    """소스에서 fit(..., eval_set=[...]) 인자를 AST 로 뽑아낸다."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for kw in (node.keywords or []):
                if kw.arg in ("eval_set", "valid_sets"):
                    hits.append((kw.value.lineno, kw.arg, ast.unparse(kw.value)))
    return hits


def check_2_early_stopping() -> bool:
    _hr("[확인 2] early stopping 의 eval_set 이 Dev 셋인가")
    print("  경계 정의 (eda_pipeline/split_spec.py — step7 / 검증 / Ablation 러너 공유)")
    print("    TRAIN  ~ %s" % (int(split_spec.DEV_START) - 1))
    print("    DEV    %s ~ %s   (early stopping 전용)"
          % (split_spec.DEV_START, split_spec.DEV_END))
    print("    VALID  %s ~          (진짜 홀드아웃. 학습 중 보지 않는다)"
          % split_spec.VALID_START)

    ok = True
    for f in ("step7_modeling_shap.py", "step23_retrain_production_models.py",
              "step30_stage6_ablation.py"):
        p = _PROJECT_ROOT / "eda_pipeline" / f
        if not p.exists():
            print("\n  %-40s (파일 없음 — 건너뜀)" % f)
            continue
        hits = _eval_set_sources(p)
        if not hits:
            print("\n  %-40s eval_set 사용 없음" % f)
            continue
        for lineno, arg, src in hits:
            bad = "valid" in src.lower()
            ok = ok and not bad
            print("\n  %s:%d" % (f, lineno))
            print("    %s = %s" % (arg, src))
            print("    -> %s" % ("VALID 유입 — Ablation 무효" if bad
                                 else "Dev 전용 — OK"))
    print("\n  판정: %s" % ("통과 — Valid 는 eval_set 에 들어가지 않는다" if ok
                            else "실패 — Valid 가 eval_set 에 있다"))
    return ok


# ── 3. scale_pos_weight 재계산 ────────────────────────────────────────
def check_3_scale_pos_weight() -> None:
    _hr("[확인 3] scale_pos_weight 가 시나리오별 실제 클래스 비율로 재계산되는가")
    con = config.connect_db("v2")
    try:
        rows = con.execute("""
            SELECT CASE
                     WHEN BASE_YM <  '%s' THEN '1_TRAIN'
                     WHEN BASE_YM <= '%s' THEN '2_DEV'
                     WHEN BASE_YM >= '%s' THEN '3_VALID'
                   END AS part,
                   COUNT(*) n,
                   SUM(CAST(IS_BUDO_12M AS BIGINT)) pos
            FROM %s GROUP BY 1 ORDER BY 1
        """ % (split_spec.DEV_START, split_spec.DEV_END,
               split_spec.VALID_START, config.PANEL_TABLE)).df()
    finally:
        con.close()

    print("  %-9s %12s %9s %10s %18s"
          % ("구간", "행수", "양성", "부도율", "scale_pos_weight"))
    print("  " + SUB)
    spw_train = None
    for _, r in rows.iterrows():
        pos, n = int(r["pos"]), int(r["n"])
        spw = (n - pos) / max(pos, 1)
        if r["part"].endswith("TRAIN"):
            spw_train = spw
        print("  %-9s %12s %9s %9.4f%% %18.2f"
              % (r["part"][2:], format(n, ","), format(pos, ","), 100.0 * pos / n, spw))

    print("\n  Train 실측 scale_pos_weight = %.2f" % spw_train)
    print("  고정값을 쓰면 안 되는 근거:")
    print("    행 중복 제거로 패널 양성 수가 63,531 -> 9,814 로 바뀌었다.")
    print("    시나리오가 행을 더 걸러내면 비율이 또 달라지므로,")
    print("    러너는 시나리오마다 해당 Train 부분집합에서 다시 계산한다.")

    runner = _PROJECT_ROOT / "eda_pipeline" / "step30_stage6_ablation.py"
    if runner.exists():
        tree = ast.parse(runner.read_text(encoding="utf-8"))
        found = False
        for node in ast.walk(tree):
            if isinstance(node, ast.keyword) and node.arg == "scale_pos_weight":
                found = True
                lit = isinstance(node.value, ast.Constant)
                print("\n  러너 step30_stage6_ablation.py:%d  scale_pos_weight=%s  -> %s"
                      % (node.value.lineno, ast.unparse(node.value),
                         "상수! 실패" if lit else "변수 — OK"))
        if not found:
            print("\n  러너에서 scale_pos_weight 키워드를 찾지 못했다.")
    else:
        print("\n  러너 step30_stage6_ablation.py 아직 없음 — 작성 시 이 확인을 다시 돌릴 것.")


# ── 4. 기존 모델 md5 ──────────────────────────────────────────────────
def check_4_md5() -> None:
    _hr("[확인 4] 기존 모델 파일 2개 md5 (작업 전후 비교용)")
    for p in (config.MODEL_PATH_LEGACY_FULL, config.MODEL_PATH_LEGACY_LEAN):
        if not p.exists():
            print("  %-28s 없음" % p.name)
            continue
        h = hashlib.md5(p.read_bytes()).hexdigest()
        print("  %-28s md5=%s  %s bytes" % (p.name, h, format(p.stat().st_size, ",")))
    print("\n  두 파일은 config.PROTECTED_MODELS 로 보호된다.")
    try:
        config.assert_model_writable(config.MODEL_PATH_LEGACY_FULL)
        print("  가드 실패 — 쓰기가 허용되고 있다")
    except PermissionError:
        print("  config.save_booster() 쓰기 시도 -> PermissionError. 가드 동작 확인.")


def main() -> None:
    check_1_features()
    check_2_early_stopping()
    check_3_scale_pos_weight()
    check_4_md5()
    print("\n" + RULE)
    print("선행 확인 4건 종료")
    print(RULE)


if __name__ == "__main__":
    main()
