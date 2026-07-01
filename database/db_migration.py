"""
database/db_migration.py
========================
DuckDB 기반 통합 데이터웨어하우스 마이그레이션 스크립트.

기존의 엑셀/CSV/TXT 원장 관리 방식을 탈피하여:
  1. input/ 폴더 내 모든 데이터 파일을 DuckDB 개별 테이블로 자동 적재
  2. 가공 완료 분석 마트(output)를 DuckDB 테이블로 이관
  3. 주요 식별자 컬럼에 인덱스 생성 및 적재 검증 로그 출력

Usage
-----
    python -m database.db_migration                      # 전체 마이그레이션
    python -m database.db_migration --input-only          # 원장만 적재
    python -m database.db_migration --mart-only           # 마트만 적재
    python -m database.db_migration --verify-only         # 검증만 실행

Author  : Data Engineering Team
Version : 1.0.0
"""

import os
import sys
import re
import gc
import glob
import time
import logging
from typing import Optional

import pandas as pd
import duckdb

# ──────────────────────────────────────────────
# 프로젝트 루트 경로 보정
# ──────────────────────────────────────────────
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_SCRIPT_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# ══════════════════════════════════════════════════
# 설정 상수
# ══════════════════════════════════════════════════

# DuckDB 데이터베이스 파일 경로
DB_DIR = os.path.join(_PROJECT_ROOT, "database")
DB_FILE = os.path.join(DB_DIR, "nh_credit_risk.db")

# 원천 데이터 입력 경로
INPUT_DIR = os.path.join(_PROJECT_ROOT, "input")

# 가공 마트 출력 경로들
MART_DIRS = {
    "analysis_output": os.path.join(_PROJECT_ROOT, "analysis", "output"),
    "news_overlay_output": os.path.join(_PROJECT_ROOT, "analysis", "news_overlay", "output"),
    "api_output": os.path.join(_PROJECT_ROOT, "api_data_processing", "output"),
}

# 로그 설정
LOG_DIR = os.path.join(DB_DIR, "logs")
LOG_FILE = os.path.join(LOG_DIR, "db_migration.log")

# 인덱싱 대상 컬럼 (테이블에 존재할 경우에만 생성)
INDEX_COLUMNS = ["V_BZNO", "BAS_YM", "BAS_DT", "BASDT1", "FNA_CLS_YM", "DSH_DT"]

# TXT 파일 파싱 설정
TXT_SEPARATOR = "|"
TXT_SKIP_ROWS = [1]  # 한글 설명 행 스킵
TXT_HEADER_ROW = 0   # 영문 헤더 행

# 지원 파일 확장자
EXCEL_EXTENSIONS = {".xlsx", ".xls"}
TEXT_EXTENSIONS = {".txt", ".csv"}
ALL_DATA_EXTENSIONS = EXCEL_EXTENSIONS | TEXT_EXTENSIONS

# 적재 제외 파일 패턴 (비데이터 파일)
EXCLUDE_PATTERNS = [
    r"^headers",
    r"^meta_out",
    r"^samples",
    r"^domain",
    r"^columns",
    r"^\.~",          # 임시 파일
    r"~\$",           # 엑셀 잠금 파일
    r"^monitor_weak", # 로그 파일
]


# ══════════════════════════════════════════════════
# 로깅 설정
# ══════════════════════════════════════════════════

def _setup_logging() -> logging.Logger:
    """마이그레이션 전용 로거 초기화."""
    os.makedirs(LOG_DIR, exist_ok=True)

    logger = logging.getLogger("DB_MIGRATION")
    logger.setLevel(logging.DEBUG)

    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        "[%(asctime)s] %(levelname)-7s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 콘솔
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    # 파일
    fh = logging.FileHandler(LOG_FILE, mode="w", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    return logger


log = _setup_logging()


# ══════════════════════════════════════════════════
# 유틸리티 함수
# ══════════════════════════════════════════════════

def sanitize_table_name(filename: str) -> str:
    """
    파일명에서 DuckDB 테이블 이름으로 사용할 수 있는 안전한 식별자를 생성.

    파일명 예: '가상사업자_UPCHE_TOT_기업정보v.txt' -> 'raw_UPCHE_TOT'
              '01_기업정보_UPCHE_TOT.xlsx' -> 'raw_01_UPCHE_TOT'
              'Metadata Registry.xlsx' -> 'raw_Metadata_Registry'

    Parameters
    ----------
    filename : str
        확장자 포함 파일명

    Returns
    -------
    str
        DuckDB 테이블 이름 (접두사 'raw_' 포함)
    """
    # 확장자 제거
    name = os.path.splitext(filename)[0]

    # '가상사업자_' 접두사 제거 (원천 데이터 파일 공통 패턴)
    name = re.sub(r"^가상사업자_", "", name)

    # 후미 'v' 제거 (예: '기업정보v' -> '기업정보')
    name = re.sub(r"v$", "", name)

    # 공백을 언더스코어로
    name = name.replace(" ", "_")

    # DuckDB 식별자에 허용되지 않는 특수문자 제거
    name = re.sub(r"[^\w가-힣]", "_", name)

    # 연속 언더스코어 정리
    name = re.sub(r"_{2,}", "_", name).strip("_")

    # 접두사 추가 (원장 테이블 구분)
    return f"raw_{name}"


def sanitize_mart_table_name(filepath: str, prefix: str = "mart") -> str:
    """
    가공 마트 파일 경로에서 테이블 이름 생성.

    Parameters
    ----------
    filepath : str
        파일 전체 경로
    prefix : str
        테이블 접두사

    Returns
    -------
    str
        DuckDB 테이블 이름
    """
    filename = os.path.basename(filepath)
    name = os.path.splitext(filename)[0]

    # 특수문자 → 언더스코어
    name = re.sub(r"[^\w가-힣]", "_", name)
    name = re.sub(r"_{2,}", "_", name).strip("_")

    return f"{prefix}_{name}"


def is_excluded_file(filename: str) -> bool:
    """적재 제외 대상 파일인지 판별."""
    base = os.path.splitext(filename)[0]
    for pattern in EXCLUDE_PATTERNS:
        if re.search(pattern, base, re.IGNORECASE):
            return True
    return False


def load_data_file(filepath: str) -> Optional[pd.DataFrame]:
    """
    파일 확장자에 따라 적절한 로더로 데이터를 읽어 DataFrame으로 반환.

    - .xlsx/.xls  -> pd.read_excel
    - .txt        -> pd.read_csv (pipe-delimited, 한글 설명 행 스킵)
    - .csv        -> pd.read_csv (comma-delimited)

    Parameters
    ----------
    filepath : str
        파일 전체 경로

    Returns
    -------
    pd.DataFrame or None
        읽기 실패 시 None
    """
    ext = os.path.splitext(filepath)[1].lower()

    try:
        if ext in EXCEL_EXTENSIONS:
            df = pd.read_excel(filepath, engine="openpyxl" if ext == ".xlsx" else None)

        elif ext == ".txt":
            # 파이프 구분자 TXT 파일 (헤더행 + 한글설명행 구조)
            df = pd.read_csv(
                filepath,
                sep=TXT_SEPARATOR,
                header=TXT_HEADER_ROW,
                skiprows=TXT_SKIP_ROWS,
                dtype=str,
                engine="python",
                on_bad_lines="skip",
                encoding="utf-8",
            )
            # 후미 빈 컬럼 제거 (파이프 구분자 끝에 | 가 추가되는 경우)
            df = df.loc[:, ~df.columns.str.match(r"^Unnamed")]
            df.columns = [c.strip() for c in df.columns]

        elif ext == ".csv":
            # 일반 CSV
            try:
                df = pd.read_csv(filepath, encoding="utf-8-sig")
            except UnicodeDecodeError:
                df = pd.read_csv(filepath, encoding="cp949")

        else:
            log.warning(f"  [SKIP] Unsupported extension: {ext} -> {filepath}")
            return None

        # #N/A 행 제거 (원천 데이터의 오류 행)
        if df.columns[0] in df.columns:
            first_col = df.columns[0]
            df = df[~df[first_col].astype(str).str.startswith("#N/A", na=False)]

        return df

    except Exception as e:
        log.error(f"  [ERROR] Failed to load: {filepath} -> {e}")
        return None


def format_size(bytes_val: int) -> str:
    """바이트 수를 읽기 쉬운 단위로 변환."""
    if bytes_val < 1024:
        return f"{bytes_val} B"
    elif bytes_val < 1024 ** 2:
        return f"{bytes_val / 1024:.1f} KB"
    elif bytes_val < 1024 ** 3:
        return f"{bytes_val / 1024 ** 2:.1f} MB"
    else:
        return f"{bytes_val / 1024 ** 3:.2f} GB"


# ══════════════════════════════════════════════════
# [기능 1] input 폴더 원장 일괄 적재 (Ingestion)
# ══════════════════════════════════════════════════

def ingest_input_files(con: duckdb.DuckDBPyConnection) -> dict[str, int]:
    """
    input/ 폴더 내 모든 데이터 파일을 DuckDB 테이블로 일괄 적재.

    Parameters
    ----------
    con : duckdb.DuckDBPyConnection
        활성 DuckDB 커넥션

    Returns
    -------
    dict[str, int]
        {테이블명: 레코드수} 딕셔너리
    """
    log.info("=" * 70)
    log.info("[Feature 1] INPUT Raw Data Ingestion")
    log.info("=" * 70)

    if not os.path.isdir(INPUT_DIR):
        log.error(f"  Input directory not found: {INPUT_DIR}")
        return {}

    # 데이터 파일 스캔
    all_files = sorted(os.listdir(INPUT_DIR))
    data_files = [
        f for f in all_files
        if os.path.splitext(f)[1].lower() in ALL_DATA_EXTENSIONS
        and not is_excluded_file(f)
    ]

    log.info(f"  Scanned {len(all_files)} files, {len(data_files)} data files to ingest")
    log.info("")

    results: dict[str, int] = {}

    for idx, filename in enumerate(data_files, 1):
        filepath = os.path.join(INPUT_DIR, filename)
        file_size = os.path.getsize(filepath)
        table_name = sanitize_table_name(filename)

        log.info(f"  [{idx}/{len(data_files)}] {filename}")
        log.info(f"           Size: {format_size(file_size)} -> Table: {table_name}")

        t0 = time.time()

        # 데이터 로드
        df = load_data_file(filepath)
        if df is None or df.empty:
            log.warning(f"           [SKIP] Empty or failed to load")
            continue

        row_count = len(df)
        col_count = len(df.columns)

        # DuckDB 테이블 생성 (CREATE OR REPLACE)
        try:
            con.execute(f'CREATE OR REPLACE TABLE "{table_name}" AS SELECT * FROM df')
            elapsed = time.time() - t0
            results[table_name] = row_count
            log.info(f"           [OK] {row_count:,} rows x {col_count} cols ({elapsed:.2f}s)")
        except Exception as e:
            log.error(f"           [ERROR] DuckDB write failed: {e}")

        # 메모리 누수 방지: DataFrame 명시적 해제
        del df
        gc.collect()

    log.info("")
    log.info(f"  [DONE] Input ingestion complete: {len(results)} tables loaded")
    return results


# ══════════════════════════════════════════════════
# [기능 2] 가공 마트 DuckDB 이관 (Mart Migration)
# ══════════════════════════════════════════════════

def migrate_marts(con: duckdb.DuckDBPyConnection) -> dict[str, int]:
    """
    가공 완료된 분석 마트(output CSV/Excel)를 DuckDB 테이블로 이관.
    엑셀/CSV 저장 코드를 전면 폐기하고 DuckDB 내부 테이블로 즉시 Write.

    Parameters
    ----------
    con : duckdb.DuckDBPyConnection
        활성 DuckDB 커넥션

    Returns
    -------
    dict[str, int]
        {테이블명: 레코드수}
    """
    log.info("")
    log.info("=" * 70)
    log.info("[Feature 2] Analysis Mart Migration")
    log.info("=" * 70)

    results: dict[str, int] = {}

    for source_label, mart_dir in MART_DIRS.items():
        if not os.path.isdir(mart_dir):
            log.info(f"  [{source_label}] Directory not found, skipping: {mart_dir}")
            continue

        # 해당 디렉토리의 CSV/XLSX 파일 수집
        mart_files = []
        for ext in ["*.csv", "*.xlsx", "*.xls"]:
            mart_files.extend(glob.glob(os.path.join(mart_dir, ext)))

        if not mart_files:
            log.info(f"  [{source_label}] No data files found")
            continue

        log.info(f"  [{source_label}] {len(mart_files)} files found in {mart_dir}")

        for filepath in sorted(mart_files):
            filename = os.path.basename(filepath)
            table_name = sanitize_mart_table_name(filepath, prefix="mart")
            file_size = os.path.getsize(filepath)

            log.info(f"    -> {filename} ({format_size(file_size)}) -> {table_name}")

            t0 = time.time()

            df = load_data_file(filepath)
            if df is None or df.empty:
                log.warning(f"       [SKIP] Empty or failed")
                continue

            row_count = len(df)

            try:
                con.execute(f'CREATE OR REPLACE TABLE "{table_name}" AS SELECT * FROM df')
                elapsed = time.time() - t0
                results[table_name] = row_count
                log.info(f"       [OK] {row_count:,} rows ({elapsed:.2f}s)")
            except Exception as e:
                log.error(f"       [ERROR] {e}")

            del df
            gc.collect()

    log.info("")
    log.info(f"  [DONE] Mart migration complete: {len(results)} tables loaded")
    return results


# ══════════════════════════════════════════════════
# [기능 3] 인덱싱 및 검증
# ══════════════════════════════════════════════════

def create_indexes(con: duckdb.DuckDBPyConnection) -> int:
    """
    주요 식별자 컬럼에 대해 DuckDB 인덱스를 자동 생성.

    Parameters
    ----------
    con : duckdb.DuckDBPyConnection
        활성 DuckDB 커넥션

    Returns
    -------
    int
        생성된 인덱스 수
    """
    log.info("")
    log.info("=" * 70)
    log.info("[Feature 3-1] Auto-Indexing Key Columns")
    log.info("=" * 70)

    # 전체 테이블 목록 조회
    tables = con.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'").fetchall()
    table_names = [t[0] for t in tables]

    index_count = 0

    for table_name in sorted(table_names):
        # 테이블 컬럼 목록 조회
        cols_result = con.execute(
            f"SELECT column_name FROM information_schema.columns "
            f"WHERE table_schema = 'main' AND table_name = '{table_name}'"
        ).fetchall()
        existing_cols = {c[0] for c in cols_result}

        # 인덱싱 대상 컬럼 필터
        target_cols = [c for c in INDEX_COLUMNS if c in existing_cols]

        for col in target_cols:
            idx_name = f"idx_{table_name}_{col}"
            try:
                con.execute(f'CREATE INDEX IF NOT EXISTS "{idx_name}" ON "{table_name}" ("{col}")')
                index_count += 1
                log.debug(f"  [INDEX] {idx_name}")
            except Exception as e:
                # DuckDB는 일부 타입에 인덱스를 지원하지 않을 수 있음
                log.debug(f"  [INDEX-SKIP] {idx_name}: {e}")

    log.info(f"  [DONE] {index_count} indexes created across {len(table_names)} tables")
    return index_count


def verify_database(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """
    DuckDB 내 모든 테이블 목록과 레코드 수를 검증하여 출력.

    Parameters
    ----------
    con : duckdb.DuckDBPyConnection
        활성 DuckDB 커넥션

    Returns
    -------
    pd.DataFrame
        테이블별 검증 결과
    """
    log.info("")
    log.info("=" * 70)
    log.info("[Feature 3-2] Database Verification Report")
    log.info("=" * 70)

    # 테이블 목록 조회
    tables = con.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'main' ORDER BY table_name"
    ).fetchall()

    if not tables:
        log.warning("  No tables found in database!")
        return pd.DataFrame()

    report_rows = []
    total_rows = 0

    for (table_name,) in tables:
        try:
            row_count = con.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()[0]
            col_count = con.execute(
                f"SELECT COUNT(*) FROM information_schema.columns "
                f"WHERE table_schema = 'main' AND table_name = '{table_name}'"
            ).fetchone()[0]
        except Exception as e:
            row_count = -1
            col_count = -1
            log.error(f"  [ERROR] Failed to count {table_name}: {e}")

        # 테이블 타입 판별
        if table_name.startswith("raw_"):
            ttype = "RAW"
        elif table_name.startswith("mart_"):
            ttype = "MART"
        else:
            ttype = "OTHER"

        report_rows.append({
            "type": ttype,
            "table_name": table_name,
            "row_count": row_count,
            "col_count": col_count,
        })
        total_rows += max(row_count, 0)

    df_report = pd.DataFrame(report_rows)

    # 깔끔한 테이블 형태 출력
    log.info("")
    log.info(f"  {'Type':<6} {'Table Name':<50} {'Rows':>12} {'Cols':>6}")
    log.info(f"  {'----':<6} {'----------':<50} {'----':>12} {'----':>6}")

    for _, row in df_report.iterrows():
        status = "[OK]" if row["row_count"] > 0 else "[EMPTY]"
        log.info(
            f"  {row['type']:<6} {row['table_name']:<50} "
            f"{row['row_count']:>12,} {row['col_count']:>6}  {status}"
        )

    log.info(f"  {'----':<6} {'----------':<50} {'----':>12} {'----':>6}")
    log.info(f"  {'TOTAL':<6} {len(report_rows):<50} {total_rows:>12,}")
    log.info("")

    # DB 파일 크기 정보
    if os.path.exists(DB_FILE):
        db_size = os.path.getsize(DB_FILE)
        log.info(f"  Database file: {DB_FILE}")
        log.info(f"  Database size: {format_size(db_size)}")

    return df_report


# ══════════════════════════════════════════════════
# 마이그레이션 오케스트레이터
# ══════════════════════════════════════════════════

def run_migration(
    do_input: bool = True,
    do_mart: bool = True,
    do_verify: bool = True,
) -> dict:
    """
    전체 마이그레이션 파이프라인 오케스트레이션.

    DuckDB 커넥션은 컨텍스트 매니저 내에서만 실행하여
    파일 Lock 및 동시성 에러를 방지.

    Parameters
    ----------
    do_input : bool
        원장(input) 적재 실행 여부
    do_mart : bool
        마트(output) 이관 실행 여부
    do_verify : bool
        검증 리포트 실행 여부

    Returns
    -------
    dict
        마이그레이션 결과 요약
    """
    os.makedirs(DB_DIR, exist_ok=True)

    log.info("=" * 70)
    log.info("  DuckDB Data Warehouse Migration START")
    log.info(f"  Database: {DB_FILE}")
    log.info("=" * 70)
    log.info("")

    t_start = time.time()
    summary = {
        "raw_tables": {},
        "mart_tables": {},
        "index_count": 0,
        "report": None,
    }

    # 컨텍스트 매니저로 DuckDB 커넥션 캡슐화
    # 파일 Lock 및 동시성 에러 방지
    with duckdb.connect(DB_FILE) as con:

        # [기능 1] 원장 적재
        if do_input:
            summary["raw_tables"] = ingest_input_files(con)

        # [기능 2] 마트 이관
        if do_mart:
            summary["mart_tables"] = migrate_marts(con)

        # [기능 3] 인덱싱 + 검증
        if do_input or do_mart:
            summary["index_count"] = create_indexes(con)

        if do_verify:
            summary["report"] = verify_database(con)

    elapsed_total = time.time() - t_start

    log.info("")
    log.info("=" * 70)
    log.info(f"  Migration COMPLETED SUCCESSFULLY ({elapsed_total:.1f}s)")
    log.info(f"  RAW tables: {len(summary['raw_tables'])}")
    log.info(f"  MART tables: {len(summary['mart_tables'])}")
    log.info(f"  Indexes created: {summary['index_count']}")
    log.info("=" * 70)

    return summary


# ══════════════════════════════════════════════════
# 편의 함수: 마트 즉시 저장
# ══════════════════════════════════════════════════

def save_mart_to_db(
    df: pd.DataFrame,
    table_name: str,
    replace: bool = True,
) -> int:
    """
    가공 완료된 DataFrame을 DuckDB 마트 테이블로 즉시 저장.
    기존 엑셀/CSV 저장 코드 대신 이 함수를 호출하여 사용.

    Parameters
    ----------
    df : pd.DataFrame
        저장할 데이터프레임
    table_name : str
        테이블 이름 (mart_ 접두사 자동 추가 가능)
    replace : bool
        True이면 기존 테이블 덮어쓰기

    Returns
    -------
    int
        적재된 레코드 수

    Examples
    --------
    >>> from database.db_migration import save_mart_to_db
    >>> save_mart_to_db(df_result, "final_macro_vars")
    14
    """
    if not table_name.startswith("mart_"):
        table_name = f"mart_{table_name}"

    os.makedirs(DB_DIR, exist_ok=True)

    with duckdb.connect(DB_FILE) as con:
        if replace:
            con.execute(f'CREATE OR REPLACE TABLE "{table_name}" AS SELECT * FROM df')
        else:
            con.execute(f'CREATE TABLE IF NOT EXISTS "{table_name}" AS SELECT * FROM df')

        row_count = len(df)
        log.info(f"[DB_SAVE] {table_name}: {row_count:,} rows saved to DuckDB")

    return row_count


def query_db(sql: str) -> pd.DataFrame:
    """
    DuckDB에 SQL 쿼리를 실행하고 결과를 DataFrame으로 반환.

    Parameters
    ----------
    sql : str
        실행할 SQL 문

    Returns
    -------
    pd.DataFrame
        쿼리 결과

    Examples
    --------
    >>> from database.db_migration import query_db
    >>> df = query_db("SELECT * FROM raw_UPCHE_TOT LIMIT 10")
    """
    with duckdb.connect(DB_FILE, read_only=True) as con:
        return con.execute(sql).df()


# ══════════════════════════════════════════════════
# 엔트리포인트
# ══════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="DuckDB Data Warehouse Migration Script"
    )
    parser.add_argument(
        "--input-only", action="store_true",
        help="Only ingest input raw data files",
    )
    parser.add_argument(
        "--mart-only", action="store_true",
        help="Only migrate analysis mart outputs",
    )
    parser.add_argument(
        "--verify-only", action="store_true",
        help="Only run verification report",
    )
    args = parser.parse_args()

    if args.input_only:
        run_migration(do_input=True, do_mart=False, do_verify=True)
    elif args.mart_only:
        run_migration(do_input=False, do_mart=True, do_verify=True)
    elif args.verify_only:
        run_migration(do_input=False, do_mart=False, do_verify=True)
    else:
        run_migration(do_input=True, do_mart=True, do_verify=True)
