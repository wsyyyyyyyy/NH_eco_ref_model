from fastapi import APIRouter, Depends, HTTPException
from backend.database import get_db
from backend.grade_mapping import prob_to_grade

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

@router.get("/{bzno}")
def get_borrower_detail(bzno: str, db=Depends(get_db)):
    query = "SELECT * FROM corporate_panel WHERE V_BZNO = ?"
    res = db.execute(query, [bzno]).df()
    if res.empty:
        raise HTTPException(status_code=404, detail=f"Borrower {bzno} not found")
    return res.to_dict(orient="records")[0]
