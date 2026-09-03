import os
import sys

import duckdb
from fastapi import Request

# ── [2026-09-03] DB 경로를 config 에서 을는다 ──────────────────────────
#   초판은 `database/portal.duckdb` 를 하드코딩했는데 **이 체크아웃에는 그 파일이
#   없다.** 그래서 backend 는 여기서 IOException 으로 죽었다 (백업 DB 에도 없었으므로
#   이 저장소에서 backend 가 동작한 적이 없다).
#   `eda_pipeline.config` 가 DB 경로의 정본이다 — 경로를 두 곳에 두면 갈라진다.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

try:
    from eda_pipeline import config as _cfg
    DB_PATH = str(_cfg.require_db("v2"))
except Exception as _exc:                                         # noqa: BLE001
    # config 를 못 읽으면 종전 경로로 떨어진다. 조용히 넘기지 않고 이유를 남긴다.
    DB_PATH = os.path.join(_ROOT, "database", "portal_v2.duckdb")
    print(f"[database] config 로 DB 경로를 정하지 못해 기본값을 쓴다: {_exc}",
          file=sys.stderr)

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
