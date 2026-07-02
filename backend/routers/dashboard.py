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
    Note: IS_BUDO_12M is right-censored for months too close to the most
    recent data (defaults up to 12 months out can't be observed yet), so
    the "actual" series is only reliable when base_ym is well before the
    latest available month."""
    all_months = [str(r[0]) for r in db.execute(
        "SELECT DISTINCT BASE_YM FROM corporate_panel WHERE CAST(BASE_YM AS VARCHAR) <= ? ORDER BY BASE_YM DESC",
        [str(base_ym)]
    ).fetchall()]
    target_months = list(reversed(all_months[:months]))

    result = []
    for ym in target_months:
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
            '실제': round(row[2], 2) if row[2] is not None else None,
        })
    return result

