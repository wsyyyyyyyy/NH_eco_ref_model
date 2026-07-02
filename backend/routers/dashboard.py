from fastapi import APIRouter, Depends
from backend.database import get_db, dedup_panel_sql

router = APIRouter()

@router.get("/summary")
def get_dashboard_summary(base_ym: str = "202402", db=Depends(get_db)):
    panel = dedup_panel_sql("WHERE BASE_YM = ?")

    # 1. Total and Risk
    q_total = f"""
        SELECT COUNT(*) as total_companies,
               SUM(CASE WHEN Z_GRADE IN ('G4', 'G5') THEN 1 ELSE 0 END) as risk_companies
        FROM {panel}
    """
    res_total = db.execute(q_total, [base_ym]).fetchone()

    # 2. Grade Distribution
    q_grade = f"""
        SELECT Z_GRADE, COUNT(*) as cnt
        FROM {panel}
        WHERE Z_GRADE IS NOT NULL
        GROUP BY Z_GRADE
        ORDER BY Z_GRADE
    """
    res_grade = db.execute(q_grade, [base_ym]).df().to_dict(orient="records")

    # 3. Top Risky Industries
    # legacy_risk_pct: 기존모델 근사치(OLD_PROB = PROB_FULL * 0.15) 업종 평균 예측위험도.
    # 실제 레거시 모형 산출물이 없어 다른 화면(차주 상세 등)과 동일한 근사식을 사용.
    q_ind = f"""
        SELECT SUBSTRING(LPAD(CAST(CAST(STD_INDS_CFC AS BIGINT) AS VARCHAR), 5, '0'), 1, 2) as industry,
               COUNT(*) as total,
               SUM(CASE WHEN Z_GRADE IN ('G4', 'G5') THEN 1 ELSE 0 END) as risk_cnt,
               AVG(PROB_FULL) * 0.15 * 100 as legacy_risk_pct
        FROM {panel}
        WHERE STD_INDS_CFC IS NOT NULL
        GROUP BY SUBSTRING(LPAD(CAST(CAST(STD_INDS_CFC AS BIGINT) AS VARCHAR), 5, '0'), 1, 2)
        HAVING COUNT(*) > 100
    """
    res_ind = db.execute(q_ind, [base_ym]).df().to_dict(orient="records")
    for r in res_ind:
        r['risk_ratio'] = round((r['risk_cnt'] / r['total']) * 100, 1)
        r['legacy_risk_pct'] = round(r['legacy_risk_pct'], 2)

    return {
        "base_ym": base_ym,
        "total_companies": res_total[0] if res_total else 0,
        "risk_companies": res_total[1] if res_total else 0,
        "grade_distribution": res_grade,
        "top_risk_industries": res_ind
    }

@router.get("/months")
def get_available_months(db=Depends(get_db)):
    q = "SELECT DISTINCT BASE_YM FROM corporate_panel WHERE BASE_YM IS NOT NULL ORDER BY BASE_YM DESC"
    res = db.execute(q).fetchall()
    months = [str(r[0]) for r in res]
    return {"months": months}

@router.get("/trend")
def get_dashboard_trend(base_ym: str = "202402", months: int = 6, db=Depends(get_db)):
    """Real monthly trend up to base_ym: ERM model's average predicted PD,
    a legacy-model proxy average (OLD_PROB = PROB_FULL * 0.15, same
    approximation used elsewhere since no real legacy model exists), and
    the actual realized 12-month-forward default rate (IS_BUDO_12M).
    IS_BUDO_12M is right-censored for months whose 12-month observation
    window hasn't fully elapsed yet (i.e. month + 12 > latest month in the
    panel) — for those months '실제' is returned as null (not a biased
    near-zero value) and flagged via `censored: true` so the frontend can
    show a gap/annotation instead of a misleading crash-to-zero line."""
    all_months_desc = [str(r[0]) for r in db.execute(
        "SELECT DISTINCT BASE_YM FROM corporate_panel ORDER BY BASE_YM DESC"
    ).fetchall()]
    max_ym = all_months_desc[0]
    max_year, max_month = int(max_ym[:4]), int(max_ym[4:6])

    all_months = [ym for ym in all_months_desc if ym <= str(base_ym)]
    target_months = list(reversed(all_months[:months]))

    result = []
    for ym in target_months:
        year, month = int(ym[:4]), int(ym[4:6])
        window_end_year = year + (month + 12 - 1) // 12
        window_end_month = (month + 12 - 1) % 12 + 1
        censored = (window_end_year, window_end_month) > (max_year, max_month)

        panel = dedup_panel_sql("WHERE CAST(BASE_YM AS VARCHAR) = ?")
        row = db.execute(f"""
            SELECT AVG(PROB_FULL) * 100 AS erm, AVG(PROB_FULL) * 0.15 * 100 AS legacy,
                   AVG(IS_BUDO_12M) * 100 AS actual
            FROM {panel}
        """, [ym]).fetchone()
        result.append({
            'month': f"{ym[2:4]}.{ym[4:6]}",
            'base_ym': ym,
            '신규': round(row[0], 2) if row[0] is not None else None,
            '기존': round(row[1], 2) if row[1] is not None else None,
            '실제': round(row[2], 2) if (row[2] is not None and not censored) else None,
            'censored': censored,
        })
    return result


@router.get("/prediction_comparison")
def get_prediction_comparison(db=Depends(get_db)):
    """Venn-diagram style comparison of which model 'caught' each company
    that actually defaulted (IS_BUDO_12M=1 at some point), restricted to
    companies with a real internal early-warning grade on record
    (OBV_ELYWRN_OBV_GRD_DSC != '-1').

    'Caught' means the model flagged high risk (ERM: Z_GRADE in G4/G5,
    internal: grade = 'B') at or before the company's default pivot month
    (the last month whose 12-month-forward window still covers the
    default event).

    Average lead time is computed only over the subset that shows a
    genuine within-sample 'A' -> 'B' downgrade before default; companies
    whose internal grade was already 'B' on their very first observed row
    are left-censored (the true downgrade date is unknown, could predate
    the panel's start) and are excluded from the lead-time average to
    avoid an artificially negative/misleading number, though they are
    still counted in the 'both caught' Venn bucket.
    """
    venn_row = db.execute("""
        WITH pivots AS (
            SELECT V_BZNO, MAX(BASE_YM) AS default_pivot
            FROM corporate_panel
            WHERE IS_BUDO_12M = 1
            GROUP BY V_BZNO
        ),
        warns AS (
            SELECT p.V_BZNO, p.default_pivot,
                MIN(CASE WHEN c.Z_GRADE IN ('G4', 'G5') AND c.BASE_YM <= p.default_pivot THEN c.BASE_YM END) AS erm_warn,
                MIN(CASE WHEN c.OBV_ELYWRN_OBV_GRD_DSC = 'B' AND c.BASE_YM <= p.default_pivot THEN c.BASE_YM END) AS internal_warn,
                MAX(CASE WHEN c.OBV_ELYWRN_OBV_GRD_DSC != '-1' AND c.BASE_YM <= p.default_pivot THEN 1 ELSE 0 END) AS has_internal_grade
            FROM pivots p
            JOIN corporate_panel c ON c.V_BZNO = p.V_BZNO
            GROUP BY p.V_BZNO, p.default_pivot
        )
        SELECT
            SUM(CASE WHEN erm_warn IS NOT NULL AND internal_warn IS NOT NULL THEN 1 ELSE 0 END) AS both_cnt,
            SUM(CASE WHEN erm_warn IS NOT NULL AND internal_warn IS NULL THEN 1 ELSE 0 END) AS erm_only_cnt,
            SUM(CASE WHEN erm_warn IS NULL AND internal_warn IS NOT NULL THEN 1 ELSE 0 END) AS internal_only_cnt,
            SUM(CASE WHEN erm_warn IS NULL AND internal_warn IS NULL THEN 1 ELSE 0 END) AS neither_cnt,
            COUNT(*) AS total_cnt
        FROM warns
        WHERE has_internal_grade = 1
    """).fetchone()

    lead_row = db.execute("""
        WITH pivots AS (
            SELECT V_BZNO, MAX(BASE_YM) AS default_pivot
            FROM corporate_panel
            WHERE IS_BUDO_12M = 1
            GROUP BY V_BZNO
        ),
        warns AS (
            SELECT p.V_BZNO, p.default_pivot,
                MIN(CASE WHEN c.Z_GRADE IN ('G4', 'G5') AND c.BASE_YM <= p.default_pivot THEN c.BASE_YM END) AS erm_warn,
                MIN(CASE WHEN c.OBV_ELYWRN_OBV_GRD_DSC = 'B' AND c.BASE_YM <= p.default_pivot THEN c.BASE_YM END) AS internal_warn,
                MIN(CASE WHEN c.OBV_ELYWRN_OBV_GRD_DSC = 'A' THEN c.BASE_YM END) AS first_a_ym,
                MAX(CASE WHEN c.OBV_ELYWRN_OBV_GRD_DSC != '-1' AND c.BASE_YM <= p.default_pivot THEN 1 ELSE 0 END) AS has_internal_grade
            FROM pivots p
            JOIN corporate_panel c ON c.V_BZNO = p.V_BZNO
            GROUP BY p.V_BZNO, p.default_pivot
        )
        SELECT
            AVG(
                (CAST(SUBSTRING(CAST(internal_warn AS VARCHAR), 1, 4) AS INT) * 12 + CAST(SUBSTRING(CAST(internal_warn AS VARCHAR), 5, 2) AS INT))
                - (CAST(SUBSTRING(CAST(erm_warn AS VARCHAR), 1, 4) AS INT) * 12 + CAST(SUBSTRING(CAST(erm_warn AS VARCHAR), 5, 2) AS INT))
            ) AS avg_lead_months,
            COUNT(*) AS n
        FROM warns
        WHERE has_internal_grade = 1 AND erm_warn IS NOT NULL AND internal_warn IS NOT NULL
          AND first_a_ym IS NOT NULL AND first_a_ym < internal_warn
    """).fetchone()

    both_cnt = int(venn_row[0] or 0)
    left_censored_cnt = both_cnt - int(lead_row[1] or 0)

    return {
        'both': both_cnt,
        'erm_only': int(venn_row[1] or 0),
        'internal_only': int(venn_row[2] or 0),
        'neither': int(venn_row[3] or 0),
        'total': int(venn_row[4] or 0),
        'lead_time': {
            'avg_months': round(lead_row[0], 1) if lead_row[0] is not None else None,
            'n': int(lead_row[1] or 0),
            'left_censored_excluded': left_censored_cnt,
        },
    }

