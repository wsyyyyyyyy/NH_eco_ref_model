from fastapi import APIRouter, Depends
from backend.database import get_db

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
            ROUND(MAX(PROB_FULL) * 0.15, 4) as OLD_PROB,
            CASE WHEN MAX(PROB_FULL) > 0.3 THEN 'BBB-' WHEN MAX(PROB_FULL) > 0.1 THEN 'A-' ELSE 'AA-' END as NICE_GRADE_PREV,
            CASE WHEN MAX(PROB_FULL) > 0.3 THEN 'BB+' WHEN MAX(PROB_FULL) > 0.1 THEN 'BBB+' ELSE 'AA0' END as NICE_GRADE_CUR,
            CASE WHEN MAX(PROB_FULL) > 0.3 THEN 'BBB0' WHEN MAX(PROB_FULL) > 0.1 THEN 'A0' ELSE 'AA+' END as KIS_GRADE_PREV,
            CASE WHEN MAX(PROB_FULL) > 0.3 THEN 'BB0' WHEN MAX(PROB_FULL) > 0.1 THEN 'BBB0' ELSE 'AA0' END as KIS_GRADE_CUR
        FROM corporate_panel
        WHERE V_BRANCH_CODE = ? AND CAST(BASE_YM AS VARCHAR) = ?
        GROUP BY V_BZNO
        ORDER BY PROB_FULL DESC
        LIMIT ? OFFSET ?
    """
    res = db.execute(query, [branch_code, str(base_ym), limit, offset]).df()
    return res.to_dict(orient="records")

@router.get("/{bzno}")
def get_borrower_detail(bzno: str, db=Depends(get_db)):
    query = "SELECT * FROM corporate_panel WHERE V_BZNO = ?"
    res = db.execute(query, [bzno]).df()
    if res.empty:
        return {"error": "Not found"}
    return res.to_dict(orient="records")[0]
