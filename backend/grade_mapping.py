import bisect
import json
import warnings
from pathlib import Path

# 16-notch corporate credit rating scale (NICE/KIS 공통 표기 체계).
# Cutoffs are quantile breakpoints of the actual PROB_FULL distribution in
# corporate_panel (40th~99.9th percentile), computed once from the full
# 1.9M-row dataset so that grade bands reflect the real population instead
# of arbitrary thresholds.
# Recomputed 2026-07-04 (docs/appendix/step29) after retraining the Full model with
# regularization (num_leaves=15, reg_alpha/lambda=1.0) and re-scoring all
# 1,944,418 rows -- see database/rescore_full_model.py.
GRADE_LABELS = [
    'AAA', 'AA+', 'AA0', 'AA-', 'A+', 'A0', 'A-',
    'BBB+', 'BBB0', 'BBB-', 'BB+', 'BB0', 'BB-', 'B+', 'B0', 'CCC',
]

# ── [2026-09-03] D8 재채점 기준으로 갱신 ────────────────────────────────
#   컷오프는 eda_pipeline/output/grade_mapping_v2.json 을 **정본으로 읽는다.**
#   여기에 값을 복제하면 재산출 때 두 곳이 갈라진다 (이번 작업에서 여러 번 겪은 형태).
#   파일이 없으면 아래 폴백을 쓰고, 그 사실을 한 번만 경고한다.
#
#   ★ 기존 컷오프는 양성 63,531 기준이었다. D8 재학습으로 양성이 9,814 로 바뀌어
#     전부 무효다. 폴백 값은 **구 세대**이므로 재산출 파일이 있으면 그것을 쓴다.
_FALLBACK_PROB_CUTOFFS = [
    0.00654, 0.00803, 0.00991, 0.01248, 0.01603, 0.02109, 0.02868,
    0.04137, 0.06649, 0.11696, 0.21508, 0.37128, 0.56732, 0.80061, 0.99113,
]

_GRADE_JSON = (Path(__file__).resolve().parent.parent
               / "eda_pipeline" / "output" / "grade_mapping_v2.json")


def _load_cutoffs() -> tuple[list[float], list[str], str]:
    """재산출 파일에서 컷오프와 라벨을 읽는다. 없으면 폴백."""
    try:
        d = json.loads(_GRADE_JSON.read_text(encoding="utf-8"))
        cuts = [float(x) for x in d["grade16_prob_cutoffs"]]
        labels = list(d["grade16_labels"])
        if len(cuts) != len(labels) - 1:
            raise ValueError(
                f"컷오프 {len(cuts)}개 / 라벨 {len(labels)}개 — 개수가 맞지 않는다")
        return cuts, labels, str(_GRADE_JSON.name)
    except Exception as exc:                                      # noqa: BLE001
        warnings.warn(
            f"{_GRADE_JSON.name} 를 읽지 못해 구 세대 폴백 컷오프를 쓴다 ({exc}). "
            f"python -m eda_pipeline.step40_grade_threshold 로 재산출할 것.",
            RuntimeWarning, stacklevel=2)
        return list(_FALLBACK_PROB_CUTOFFS), list(GRADE_LABELS), "(폴백)"


PROB_CUTOFFS, _LABELS, CUTOFF_SOURCE = _load_cutoffs()


def prob_to_grade(prob: float) -> str:
    """예측 부도확률을 NICE/KIS 표기 등급으로 매핑한다.

    컷오프는 모집단 분위 기준이며 `CUTOFF_SOURCE` 가 출처를 알려 준다.
    """
    idx = bisect.bisect_right(PROB_CUTOFFS, prob)
    return _LABELS[idx]
