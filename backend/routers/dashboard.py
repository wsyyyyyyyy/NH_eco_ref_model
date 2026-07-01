from fastapi import APIRouter, Depends
from backend.database import get_db

router = APIRouter()

@router.get("/summary")
def get_dashboard_summary(base_ym: str = "202402", db=Depends(get_db)):
    # 1. Total and Risk
    q_total = """
        SELECT COUNT(*) as total_companies, 
               SUM(CASE WHEN Z_GRADE IN ('G4', 'G5') THEN 1 ELSE 0 END) as risk_companies 
        FROM corporate_panel 
        WHERE BASE_YM = ?
    """
    res_total = db.execute(q_total, [base_ym]).fetchone()
    
    # 2. Grade Distribution
    q_grade = """
        SELECT Z_GRADE, COUNT(*) as cnt 
        FROM corporate_panel 
        WHERE BASE_YM = ? AND Z_GRADE IS NOT NULL
        GROUP BY Z_GRADE 
        ORDER BY Z_GRADE
    """
    res_grade = db.execute(q_grade, [base_ym]).df().to_dict(orient="records")
    
    # 3. Top Risky Industries
    q_ind = """
        SELECT SUBSTRING(LPAD(CAST(CAST(STD_INDS_CFC AS BIGINT) AS VARCHAR), 5, '0'), 1, 2) as industry, 
               COUNT(*) as total, 
               SUM(CASE WHEN Z_GRADE IN ('G4', 'G5') THEN 1 ELSE 0 END) as risk_cnt
        FROM corporate_panel
        WHERE BASE_YM = ? AND STD_INDS_CFC IS NOT NULL
        GROUP BY SUBSTRING(LPAD(CAST(CAST(STD_INDS_CFC AS BIGINT) AS VARCHAR), 5, '0'), 1, 2)
        HAVING COUNT(*) > 100
    """
    res_ind = db.execute(q_ind, [base_ym]).df().to_dict(orient="records")
    for r in res_ind:
        r['risk_ratio'] = round((r['risk_cnt'] / r['total']) * 100, 1)

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

