import duckdb
import os
from fastapi import Request

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'database', 'portal.duckdb')

def get_db():
    # In DuckDB, multiple read-only connections are fully supported.
    # We yield a connection per request.
    conn = duckdb.connect(DB_PATH, read_only=True)
    try:
        yield conn
    finally:
        conn.close()


def dedup_panel_sql(where_sql: str = "") -> str:
    """SQL for corporate_panel with duplicate (V_BZNO, BASE_YM) rows collapsed
    to one (the highest-PROB_FULL variant). An upstream pipeline join fan-out
    left ~6-12% of rows duplicated (up to ~289x for a single company/month),
    which silently inflates COUNT(*)-based totals/percentages and biases
    aggregate means. `where_sql` (e.g. "WHERE BASE_YM = ?") is pushed inside
    the window so only the relevant slice is scanned/ranked."""
    return f"""(
        SELECT * FROM (
            SELECT *, ROW_NUMBER() OVER (PARTITION BY V_BZNO, BASE_YM ORDER BY PROB_FULL DESC) AS _rn
            FROM corporate_panel
            {where_sql}
        ) WHERE _rn = 1
    )"""
