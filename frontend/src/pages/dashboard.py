from fastapi import APIRouter, Depends
from backend.database import get_db, dedup_panel_sql

router = APIRouter()

@router.get("/summary")
def get_dashboard_summary(base_ym: str = "202505", db=Depends(get_db)):
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



@router.get("/prediction_comparison")
def get_prediction_comparison(db=Depends(get_db)):
    """Venn-diagram style comparison of which model 'caught' each company
    that actually defaulted, restricted to companies with a real internal
    early-warning grade on record (OBV_ELYWRN_OBV_GRD_DSC != '-1').

    The default pivot month uses the real default date (DSH_DT, sourced
    from the bank's own default ledger, first/earliest default per
    company) whenever available; for companies without a matching DSH_DT
    record it falls back to the previous approximation (the last month
    whose 12-month-forward IS_BUDO_12M window still covers the default).

    'Caught' means the model flagged high risk (ERM: Z_GRADE in G4/G5,
    internal: grade = 'B') at or before the company's default pivot month.

    Average lead time is computed only over the subset that shows a
    genuine within-sample 'A' -> 'B' downgrade before default; companies
    whose internal grade was already 'B' on their very first observed row
    are left-censored (the true downgrade date is unknown, could predate
    the panel's start) and are excluded from the lead-time average to
    avoid an artificially negative/misleading number, though they are
    still counted in the 'both caught' Venn bucket.
    """
    PIVOTS_CTE = """
        pivots AS (
            SELECT V_BZNO,
                COALESCE(
                    MAX(CASE WHEN DSH_DT IS NOT NULL THEN CAST(SUBSTRING(DSH_DT, 1, 6) AS BIGINT) END),
                    MAX(CASE WHEN IS_BUDO_12M = 1 THEN BASE_YM END)
                ) AS default_pivot,
                MAX(CASE WHEN DSH_DT IS NOT NULL THEN 1 ELSE 0 END) AS has_real_date
            FROM corporate_panel
            WHERE IS_BUDO_12M = 1 OR DSH_DT IS NOT NULL
            GROUP BY V_BZNO
        )
    """

    venn_row = db.execute(f"""
        WITH {PIVOTS_CTE},
        warns AS (
            SELECT p.V_BZNO, p.default_pivot, p.has_real_date,
                MIN(CASE WHEN c.Z_GRADE IN ('G4', 'G5') AND c.BASE_YM <= p.default_pivot THEN c.BASE_YM END) AS erm_warn,
                MIN(CASE WHEN c.OBV_ELYWRN_OBV_GRD_DSC = 'B' AND c.BASE_YM <= p.default_pivot THEN c.BASE_YM END) AS internal_warn,
                MAX(CASE WHEN c.OBV_ELYWRN_OBV_GRD_DSC != '-1' AND c.BASE_YM <= p.default_pivot THEN 1 ELSE 0 END) AS has_internal_grade
            FROM pivots p
            JOIN corporate_panel c ON c.V_BZNO = p.V_BZNO
            GROUP BY p.V_BZNO, p.default_pivot, p.has_real_date
        )
        SELECT
            SUM(CASE WHEN erm_warn IS NOT NULL AND internal_warn IS NOT NULL THEN 1 ELSE 0 END) AS both_cnt,
            SUM(CASE WHEN erm_warn IS NOT NULL AND internal_warn IS NULL THEN 1 ELSE 0 END) AS erm_only_cnt,
            SUM(CASE WHEN erm_warn IS NULL AND internal_warn IS NOT NULL THEN 1 ELSE 0 END) AS internal_only_cnt,
            SUM(CASE WHEN erm_warn IS NULL AND internal_warn IS NULL THEN 1 ELSE 0 END) AS neither_cnt,
            COUNT(*) AS total_cnt,
            SUM(has_real_date) AS real_date_cnt
        FROM warns
        WHERE has_internal_grade = 1
    """).fetchone()

    lead_row = db.execute(f"""
        WITH {PIVOTS_CTE},
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

    # 등급하향(A->B) 시점이 실제 부도일자(DSH_DT) 대비 몇 개월 전/후인지 -- 내부등급이
    # 진짜 "조기"경보인지, 부도가 이미 발생한 뒤 사후적으로 반영되는 지표인지 검증.
    grade_lag_row = db.execute("""
        WITH per_company AS (
            SELECT V_BZNO,
                MIN(DSH_DT) AS dsh_dt,
                MIN(CASE WHEN OBV_ELYWRN_OBV_GRD_DSC = 'A' THEN BASE_YM END) AS first_a_ym,
                MIN(CASE WHEN OBV_ELYWRN_OBV_GRD_DSC = 'B' THEN BASE_YM END) AS first_b_ym
            FROM corporate_panel
            WHERE DSH_DT IS NOT NULL
            GROUP BY V_BZNO
        ),
        filtered AS (
            SELECT
                (CAST(SUBSTRING(dsh_dt, 1, 4) AS INT) * 12 + CAST(SUBSTRING(dsh_dt, 5, 2) AS INT))
                - (CAST(SUBSTRING(CAST(first_b_ym AS VARCHAR), 1, 4) AS INT) * 12 + CAST(SUBSTRING(CAST(first_b_ym AS VARCHAR), 5, 2) AS INT))
                AS lead_months
            FROM per_company
            WHERE first_a_ym IS NOT NULL AND first_b_ym IS NOT NULL AND first_a_ym < first_b_ym
        )
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN lead_months < 0 THEN 1 ELSE 0 END) AS after_default_cnt,
               MEDIAN(lead_months) AS median_lead_months
        FROM filtered
    """).fetchone()

    return {
        'both': both_cnt,
        'erm_only': int(venn_row[1] or 0),
        'internal_only': int(venn_row[2] or 0),
        'neither': int(venn_row[3] or 0),
        'total': int(venn_row[4] or 0),
        'real_default_date_cnt': int(venn_row[5] or 0),
        'lead_time': {
            'avg_months': round(lead_row[0], 1) if lead_row[0] is not None else None,
            'n': int(lead_row[1] or 0),
            'left_censored_excluded': left_censored_cnt,
        },
        'grade_lag': {
            'total': int(grade_lag_row[0] or 0),
            'after_default_cnt': int(grade_lag_row[1] or 0),
            'after_default_pct': round((grade_lag_row[1] / grade_lag_row[0]) * 100, 1) if grade_lag_row[0] else None,
            'median_lead_months': int(grade_lag_row[2]) if grade_lag_row[2] is not None else None,
        },
    }

