import re

import duckdb
from fastapi import APIRouter, HTTPException

from backend.database import DB_PATH, dedup_panel_sql
from backend.grade_mapping import prob_to_grade

router = APIRouter()

METRICS_PATH = 'eda_pipeline/output/step13_performance_metrics.txt'

PD_BINS = [
    ('0~10% (안전)', 0.0, 0.10),
    ('10~30% (보통)', 0.10, 0.30),
    ('30~50% (주의)', 0.30, 0.50),
    ('50~70% (경고)', 0.50, 0.70),
    ('70%+ (고위험)', 0.70, 1.0001),
]


@router.get("/metrics")
def get_metrics():
    """Real Step-13 validation metrics (ROC-AUC, Gini, K-S, PSI), parsed from
    the report produced when the model was trained/evaluated."""
    try:
        with open(METRICS_PATH, encoding='utf-8') as f:
            text = f.read()
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail=f"{METRICS_PATH} not found")

    def grab(pattern):
        m = re.search(pattern, text)
        return float(m.group(1)) if m else None

    return {
        'train_auc': grab(r'Train AUC\s*:\s*([\d.]+)'),
        'valid_auc': grab(r'Valid AUC\s*:\s*([\d.]+)'),
        'train_gini': grab(r'Train Gini:\s*([\d.]+)'),
        'valid_gini': grab(r'Valid Gini:\s*([\d.]+)'),
        'train_ks': grab(r'Train K-S\s*:\s*([\d.]+)'),
        'valid_ks': grab(r'Valid K-S\s*:\s*([\d.]+)'),
        'total_psi': grab(r'Total PSI\s*:\s*([\d.]+)'),
    }


@router.get("/pd_distribution")
def get_pd_distribution():
    """Real distribution of the current model's predicted default probability
    (PROB_FULL) across risk bins, compared against OLD_PROB (= PROB_FULL *
    0.15), an approximation of the legacy model since no legacy model
    artifact is available to re-score against."""
    conn = duckdb.connect(DB_PATH, read_only=True)
    case_new = ' '.join(
        f"WHEN PROB_FULL >= {lo} AND PROB_FULL < {hi} THEN '{label}'" for label, lo, hi in PD_BINS
    )
    case_old = ' '.join(
        f"WHEN PROB_FULL * 0.15 >= {lo} AND PROB_FULL * 0.15 < {hi} THEN '{label}'" for label, lo, hi in PD_BINS
    )
    panel = dedup_panel_sql("WHERE PROB_FULL IS NOT NULL")
    df = conn.execute(f"""
        SELECT
            CASE {case_new} END AS new_bin,
            CASE {case_old} END AS old_bin,
            COUNT(*) AS cnt
        FROM {panel}
        GROUP BY new_bin, old_bin
    """).df()
    conn.close()

    total = df['cnt'].sum()
    new_counts = df.groupby('new_bin')['cnt'].sum()
    old_counts = df.groupby('old_bin')['cnt'].sum()

    result = []
    for label, _, _ in PD_BINS:
        result.append({
            'bin': label,
            '기존모형': round(float(old_counts.get(label, 0)) / total * 100, 2),
            'ERM모형': round(float(new_counts.get(label, 0)) / total * 100, 2),
        })
    return result


@router.get("/drift")
def get_drift():
    """Real month-over-month Population Stability Index of PROB_FULL,
    measured against the earliest available month as the reference
    distribution."""
    conn = duckdb.connect(DB_PATH, read_only=True)
    months = [str(r[0]) for r in conn.execute(
        "SELECT DISTINCT BASE_YM FROM corporate_panel ORDER BY BASE_YM"
    ).fetchall()]
    if not months:
        conn.close()
        return []

    ref_month = months[0]
    breakpoints = conn.execute(f"""
        SELECT quantile_cont(PROB_FULL, [0.1,0.2,0.3,0.4,0.5,0.6,0.7,0.8,0.9])
        FROM {dedup_panel_sql(f"WHERE BASE_YM = '{ref_month}'")}
    """).fetchone()[0]

    edges = [0.0] + list(breakpoints) + [1.0001]

    def bucket_shares(month):
        case_expr = ' '.join(
            f"WHEN PROB_FULL >= {edges[i]} AND PROB_FULL < {edges[i+1]} THEN {i}"
            for i in range(len(edges) - 1)
        )
        panel = dedup_panel_sql(f"WHERE BASE_YM = '{month}' AND PROB_FULL IS NOT NULL")
        df = conn.execute(f"""
            SELECT CASE {case_expr} END AS bucket, COUNT(*) AS cnt
            FROM {panel}
            GROUP BY bucket
        """).df()
        total = df['cnt'].sum()
        shares = {i: 1e-6 for i in range(len(edges) - 1)}
        for _, row in df.iterrows():
            if row['bucket'] is not None:
                shares[int(row['bucket'])] = max(row['cnt'] / total, 1e-6)
        return shares

    ref_shares = bucket_shares(ref_month)

    sample_months = months[::max(1, len(months) // 24)]
    if months[-1] not in sample_months:
        sample_months.append(months[-1])

    import math

    result = []
    for month in sample_months:
        shares = bucket_shares(month)
        psi = sum(
            (shares[i] - ref_shares[i]) * math.log(shares[i] / ref_shares[i])
            for i in ref_shares
        )
        result.append({'month': f"{month[2:4]}.{month[4:6]}", 'psi': round(psi, 4)})

    conn.close()
    return result


@router.get("/borrowers")
def get_borrowers_by_bin(bin: str):
    matching = [b for b in PD_BINS if b[0] == bin]
    if not matching:
        raise HTTPException(status_code=400, detail=f"Unknown bin: {bin}")
    _, lo, hi = matching[0]

    conn = duckdb.connect(DB_PATH, read_only=True)
    panel = dedup_panel_sql("WHERE BASE_YM = (SELECT MAX(BASE_YM) FROM corporate_panel)")
    df = conn.execute(f"""
        SELECT V_BZNO, STD_INDS_CFC, PROB_FULL, Z_GRADE
        FROM {panel}
        WHERE PROB_FULL >= ? AND PROB_FULL < ?
        ORDER BY PROB_FULL DESC
        LIMIT 20
    """, [lo, hi]).df()
    conn.close()

    from backend.model_inference import get_industry_name

    records = []
    for _, row in df.iterrows():
        old_pd = row['PROB_FULL'] * 0.15
        old_grade = prob_to_grade(old_pd)
        is_blind_spot = old_grade in ('AAA', 'AA+', 'AA0', 'AA-', 'A+', 'A0', 'A-') and row['PROB_FULL'] >= 0.5
        records.append({
            'id': str(row['V_BZNO']),
            'name': f"기업_{row['V_BZNO']}",
            'industry': get_industry_name(row['STD_INDS_CFC']),
            'pd': round(row['PROB_FULL'] * 100, 2),
            'oldGrade': old_grade,
            'oldPd': round(old_pd * 100, 2),
            'ermGrade': row['Z_GRADE'],
            'isBlindSpot': bool(is_blind_spot),
        })
    return records
