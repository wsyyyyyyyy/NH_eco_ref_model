import bisect

# 16-notch corporate credit rating scale (NICE/KIS 공통 표기 체계).
# Cutoffs are quantile breakpoints of the actual PROB_FULL distribution in
# corporate_panel (40th~99.9th percentile), computed once from the full
# 1.9M-row dataset so that grade bands reflect the real population instead
# of arbitrary thresholds.
GRADE_LABELS = [
    'AAA', 'AA+', 'AA0', 'AA-', 'A+', 'A0', 'A-',
    'BBB+', 'BBB0', 'BBB-', 'BB+', 'BB0', 'BB-', 'B+', 'B0', 'CCC',
]

PROB_CUTOFFS = [
    0.00613, 0.01248, 0.0234, 0.04323, 0.08917, 0.18447, 0.33018,
    0.48234, 0.65109, 0.76701, 0.87997, 0.95703, 0.98333, 0.9894, 0.99249,
]


def prob_to_grade(prob: float) -> str:
    """Maps a default probability to a NICE/KIS-style rating notch using
    the pre-computed population quantile cutoffs."""
    idx = bisect.bisect_right(PROB_CUTOFFS, prob)
    return GRADE_LABELS[idx]
