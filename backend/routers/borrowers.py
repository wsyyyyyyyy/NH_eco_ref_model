import math
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from backend.database import get_db, dedup_panel_sql
from backend.feature_labels import get_feature_label
from backend.grade_mapping import prob_to_grade
from backend.model_inference import get_feature_row, get_model, get_shap_explainer

router = APIRouter()

@router.get("/")
def get_borrowers(branch_code: str = "VB001", base_ym: str = "202402", page: int = 1, limit: int = 50, db=Depends(get_db)):
    offset = (page - 1) * limit
    query = """
        SELECT
            V_BZNO,
            ANY_VALUE(STD_INDS_CFC) as STD_INDS_CFC,
            MAX(PROB_FULL) as PROB_FULL,
            ANY_VALUE(Z_SCORE) as Z_SCORE,
            ANY_VALUE(Z_GRADE) as Z_GRADE,
            ANY_VALUE(OBV_ELYWRN_OBV_GRD_DSC) as OBV_ELYWRN_OBV_GRD_DSC,
            ROUND(MAX(PROB_FULL) * 0.15, 4) as OLD_PROB
        FROM corporate_panel
        WHERE V_BRANCH_CODE = ? AND CAST(BASE_YM AS VARCHAR) = ?
        GROUP BY V_BZNO
        ORDER BY PROB_FULL DESC
        LIMIT ? OFFSET ?
    """
    res = db.execute(query, [branch_code, str(base_ym), limit, offset]).df()
    records = res.to_dict(orient="records")
    for r in records:
        r["NICE_GRADE_PREV"] = prob_to_grade(r["OLD_PROB"])
        r["NICE_GRADE_CUR"] = prob_to_grade(r["PROB_FULL"])
        r["KIS_GRADE_PREV"] = prob_to_grade(r["OLD_PROB"])
        r["KIS_GRADE_CUR"] = prob_to_grade(r["PROB_FULL"])
    return records

@router.get("/{bzno}/financials")
def get_borrower_financials(bzno: str, base_ym: Optional[str] = None, years: int = 3, db=Depends(get_db)):
    """Last N distinct annual financial-statement vintages for a borrower.

    JEMU_* columns (자본총계/총자산/매출액/영업이익 등) come from yearly
    financial statements re-joined onto the monthly panel, so the same value
    repeats for ~12 months until the next fiscal year's statement lands
    (verified directly against the DB). Each vintage is labeled by the year
    it FIRST took effect (MIN(BASE_YM) of the run) rather than whatever
    month happens to be queried - otherwise the same FY2023 statement would
    be mislabeled "2024" or "2025" depending purely on which month the user
    is currently viewing, instead of the fiscal year it actually reports.

    Some borrowers have a second vintage starting mid-year (e.g. a "no data
    yet" placeholder for Jan-Jun, then the real first filing from Jul) which
    would otherwise produce two columns both labeled with the same year; we
    keep only the latest-starting vintage per calendar year.
    """
    panel = dedup_panel_sql("WHERE V_BZNO = ?")
    params = [bzno]
    cutoff = ""
    if base_ym:
        cutoff = "AND CAST(BASE_YM AS VARCHAR) <= ?"
        params.append(str(base_ym))
    params.append(years)

    query = f"""
        WITH vintages AS (
            SELECT
                MIN(BASE_YM) AS vintage_start,
                arg_max(PROB_FULL, BASE_YM) AS PROB_FULL,
                arg_max(CG01_KIS_SCORE, BASE_YM) AS CG01_KIS_SCORE,
                JEMU_121000, JEMU_115000, JEMU_125000, JEMU_126000
            FROM {panel}
            WHERE 1=1 {cutoff}
            GROUP BY JEMU_121000, JEMU_115000, JEMU_125000, JEMU_126000
        ),
        yearly AS (
            SELECT *,
                ROW_NUMBER() OVER (
                    PARTITION BY SUBSTRING(CAST(vintage_start AS VARCHAR), 1, 4)
                    ORDER BY vintage_start DESC
                ) AS _yr_rn
            FROM vintages
        )
        SELECT * FROM yearly WHERE _yr_rn = 1
        ORDER BY vintage_start DESC
        LIMIT ?
    """
    res = db.execute(query, params).df()
    if res.empty:
        raise HTTPException(status_code=404, detail=f"Borrower {bzno} not found")

    records = []
    for _, row in res.iloc[::-1].iterrows():  # oldest -> newest for a trend
        vintage_start_str = str(int(row['vintage_start']))
        records.append({
            'year': vintage_start_str[:4],
            'base_ym': vintage_start_str,
            'capital': row['JEMU_121000'],
            'total_assets': row['JEMU_115000'],
            'revenue': row['JEMU_125000'],
            'operating_profit': row['JEMU_126000'],
            'kis_score': row['CG01_KIS_SCORE'],
            'nice_grade': prob_to_grade(row['PROB_FULL']),
        })
    return records


@router.get("/{bzno}/pd_history")
def get_borrower_pd_history(bzno: str, base_ym: Optional[str] = None, months: int = 6, db=Depends(get_db)):
    """Real recent monthly PROB_FULL trend for a borrower, up to base_ym."""
    panel = dedup_panel_sql("WHERE V_BZNO = ?")
    params = [bzno]
    cutoff = ""
    if base_ym:
        cutoff = "AND CAST(BASE_YM AS VARCHAR) <= ?"
        params.append(str(base_ym))
    params.append(months)

    query = f"""
        SELECT BASE_YM, PROB_FULL
        FROM {panel}
        WHERE 1=1 {cutoff}
        ORDER BY BASE_YM DESC
        LIMIT ?
    """
    res = db.execute(query, params).df()
    if res.empty:
        raise HTTPException(status_code=404, detail=f"Borrower {bzno} not found")

    records = []
    for _, row in res.iloc[::-1].iterrows():  # oldest -> newest for a trend
        ym = str(int(row['BASE_YM']))
        records.append({
            'month': f"{ym[2:4]}.{ym[4:6]}",
            'base_ym': ym,
            'pd': round(row['PROB_FULL'], 4),
        })
    return records


@router.get("/{bzno}/capability")
def get_borrower_capability(bzno: str, base_ym: Optional[str] = None, db=Depends(get_db)):
    """5-axis capability diagnostic (활동성/수익성/안정성/성장성/규모) for the
    borrower vs. its industry (KSIC division) peers in the same month.

    Each axis is the average PERCENT_RANK() of the borrower's real JEMU_*
    financial ratios against every company in the same division/month
    (0~100, 50 = median). This replaces the previous fully hardcoded
    radarMockData with a real, population-relative score."""
    if not base_ym:
        panel_latest = dedup_panel_sql("WHERE V_BZNO = ?")
        row = db.execute(f"SELECT MAX(BASE_YM) FROM {panel_latest}", [bzno]).fetchone()
        if not row or row[0] is None:
            raise HTTPException(status_code=404, detail=f"Borrower {bzno} not found")
        base_ym = str(int(row[0]))

    division_expr = "CAST(SUBSTRING(LPAD(CAST(CAST(STD_INDS_CFC AS BIGINT) AS VARCHAR), 5, '0'), 1, 2) AS INT)"
    panel = dedup_panel_sql("WHERE CAST(BASE_YM AS VARCHAR) = ?")

    query = f"""
        WITH ranked AS (
            SELECT
                V_BZNO,
                {division_expr} AS division,
                PERCENT_RANK() OVER (ORDER BY JEMU_191207) AS pr_asset_turnover,
                PERCENT_RANK() OVER (ORDER BY JEMU_191208) AS pr_receivable_turnover,
                PERCENT_RANK() OVER (ORDER BY JEMU_191210) AS pr_inventory_turnover,
                PERCENT_RANK() OVER (ORDER BY JEMU_191110) AS pr_op_margin,
                PERCENT_RANK() OVER (ORDER BY JEMU_191204) AS pr_roe,
                PERCENT_RANK() OVER (ORDER BY -JEMU_191105) AS pr_debt_ratio_inv,
                PERCENT_RANK() OVER (ORDER BY JEMU_191108) AS pr_equity_ratio,
                PERCENT_RANK() OVER (ORDER BY JEMU_191310) AS pr_interest_coverage,
                PERCENT_RANK() OVER (ORDER BY JEMU_191502) AS pr_revenue_growth,
                PERCENT_RANK() OVER (ORDER BY JEMU_191506) AS pr_capital_growth,
                PERCENT_RANK() OVER (ORDER BY JEMU_115000) AS pr_assets
            FROM {panel}
        ),
        scored AS (
            SELECT
                V_BZNO, division,
                (pr_asset_turnover + pr_receivable_turnover + pr_inventory_turnover) / 3.0 * 100 AS activity,
                (pr_op_margin + pr_roe) / 2.0 * 100 AS profitability,
                (pr_debt_ratio_inv + pr_equity_ratio + pr_interest_coverage) / 3.0 * 100 AS stability,
                (pr_revenue_growth + pr_capital_growth) / 2.0 * 100 AS growth,
                pr_assets * 100 AS scale
            FROM ranked
        )
        SELECT * FROM scored
        WHERE division = (SELECT division FROM scored WHERE V_BZNO = ?)
    """
    df = db.execute(query, [str(base_ym), bzno]).df()
    if df.empty or not (df['V_BZNO'] == int(bzno)).any():
        raise HTTPException(status_code=404, detail=f"Borrower {bzno} not found")

    target = df[df['V_BZNO'] == int(bzno)].iloc[0]
    industry_avg = df[['activity', 'profitability', 'stability', 'growth', 'scale']].mean()

    axes = {
        '활동성': ('activity', target['activity']),
        '수익성': ('profitability', target['profitability']),
        '안정성': ('stability', target['stability']),
        '성장성': ('growth', target['growth']),
        '규모': ('scale', target['scale']),
    }
    return {
        'target': {label: round(float(val), 1) for label, (_, val) in axes.items()},
        'industry_avg': {label: round(float(industry_avg[col]), 1) for label, (col, _) in axes.items()},
        'peer_count': int(len(df)),
    }


@router.get("/{bzno}/shap")
def get_borrower_shap(bzno: str, base_ym: Optional[str] = None, top_n: int = 8):
    """Real per-borrower SHAP feature attribution from the trained LightGBM
    model (TreeExplainer), instead of the previous static mock chart.

    SHAP values from a LightGBM binary classifier are additive in log-odds
    (margin) space, not probability space. A naive "SHAP * local sigmoid
    slope" conversion to %p looks tiny and misleading whenever the
    prediction is far from the population baseline (which is common here -
    e.g. base 1.3% vs. a G5 borrower's 93% both being routine), since the
    slope is evaluated near the baseline. Rather than fabricate a
    percentage-point number that doesn't hold up, we report:
    - base_pd / final_pd: real probabilities (population baseline vs. this
      borrower's actual predicted PD) - both unambiguous.
    - shap_raw: the true SHAP value in log-odds units (additive, correct).
    - impact_score: shap_raw normalized so the largest-magnitude feature
      among the top N is 100/-100, purely for bar-chart comparison.
    """
    row = get_feature_row(bzno, base_ym)
    if row.empty:
        raise HTTPException(status_code=404, detail=f"Borrower {bzno} not found")

    model = get_model()
    features = model.feature_name()
    explainer = get_shap_explainer()
    shap_values = explainer.shap_values(row[features])[0]
    base_value = explainer.expected_value
    if isinstance(base_value, (list, tuple)):
        base_value = base_value[0]

    def sigmoid(x):
        return 1 / (1 + math.exp(-x))

    base_prob = sigmoid(base_value)
    final_prob = sigmoid(base_value + sum(shap_values))

    contributions = sorted(
        zip(features, shap_values), key=lambda fv: abs(fv[1]), reverse=True
    )[:top_n]
    max_abs = max((abs(v) for _, v in contributions), default=1) or 1

    return {
        'base_pd': round(base_prob * 100, 2),
        'final_pd': round(final_prob * 100, 2),
        'features': [
            {
                'feature': f,
                'label': get_feature_label(f),
                'shap_raw': round(float(v), 5),
                'impact_score': round(float(v) / max_abs * 100, 1),
            }
            for f, v in contributions
        ],
    }


@router.get("/{bzno}")
def get_borrower_detail(bzno: str, base_ym: Optional[str] = None, db=Depends(get_db)):
    panel = dedup_panel_sql("WHERE V_BZNO = ?")
    if base_ym:
        query = f"SELECT * FROM {panel} WHERE CAST(BASE_YM AS VARCHAR) = ?"
        params = [bzno, str(base_ym)]
    else:
        # No month specified: fall back to the borrower's most recent record
        # rather than an arbitrary (effectively earliest) row.
        query = f"SELECT * FROM {panel} ORDER BY BASE_YM DESC LIMIT 1"
        params = [bzno]

    res = db.execute(query, params).df()
    if res.empty:
        raise HTTPException(status_code=404, detail=f"Borrower {bzno} not found")

    record = res.to_dict(orient="records")[0]
    record.pop("_rn", None)
    # pandas represents SQL NULL in numeric columns as float('nan'), which json.dumps
    # cannot serialize (raises ValueError) -- convert to None. Matters now that
    # RZVL_POD is mostly NULL (only populated for 2021.01~11).
    record = {k: (None if isinstance(v, float) and math.isnan(v) else v) for k, v in record.items()}
    old_prob = round(record["PROB_FULL"] * 0.15, 4)
    record["OLD_PROB"] = old_prob
    record["NICE_GRADE_PREV"] = prob_to_grade(old_prob)
    record["NICE_GRADE_CUR"] = prob_to_grade(record["PROB_FULL"])
    record["KIS_GRADE_PREV"] = prob_to_grade(old_prob)
    record["KIS_GRADE_CUR"] = prob_to_grade(record["PROB_FULL"])
    return record
