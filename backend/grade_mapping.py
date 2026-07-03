import bisect

# 16-notch corporate credit rating scale (NICE/KIS 공통 표기 체계).
# Cutoffs are quantile breakpoints of the actual PROB_FULL distribution in
# corporate_panel (40th~99.9th percentile), computed once from the full
# 1.9M-row dataset so that grade bands reflect the real population instead
# of arbitrary thresholds.
# Recomputed 2026-07-04 (docs/step29) after retraining the Full model with
# regularization (num_leaves=15, reg_alpha/lambda=1.0) and re-scoring all
# 1,944,418 rows -- see database/rescore_full_model.py.
GRADE_LABELS = [
    'AAA', 'AA+', 'AA0', 'AA-', 'A+', 'A0', 'A-',
    'BBB+', 'BBB0', 'BBB-', 'BB+', 'BB0', 'BB-', 'B+', 'B0', 'CCC',
]

PROB_CUTOFFS = [
    0.00654, 0.00803, 0.00991, 0.01248, 0.01603, 0.02109, 0.02868,
    0.04137, 0.06649, 0.11696, 0.21508, 0.37128, 0.56732, 0.80061, 0.99113,
]


def prob_to_grade(prob: float) -> str:
    """Maps a default probability to a NICE/KIS-style rating notch using
    the pre-computed population quantile cutoffs."""
    idx = bisect.bisect_right(PROB_CUTOFFS, prob)
    return GRADE_LABELS[idx]
