from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from backend.database import get_db, dedup_panel_sql
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
    old_prob = round(record["PROB_FULL"] * 0.15, 4)
    record["OLD_PROB"] = old_prob
    record["NICE_GRADE_PREV"] = prob_to_grade(old_prob)
    record["NICE_GRADE_CUR"] = prob_to_grade(record["PROB_FULL"])
    record["KIS_GRADE_PREV"] = prob_to_grade(old_prob)
    record["KIS_GRADE_CUR"] = prob_to_grade(record["PROB_FULL"])
    return record
