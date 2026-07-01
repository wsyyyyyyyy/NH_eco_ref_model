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
