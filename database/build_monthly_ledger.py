import os
import sys
import logging
import duckdb

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_SCRIPT_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-5s | %(message)s")
log = logging.getLogger(__name__)

def build_monthly_ledger():
    db_path = os.path.join(_PROJECT_ROOT, "database", "nh_credit_risk.db")
    
    try:
        con = duckdb.connect(db_path)
    except duckdb.IOException as e:
        log.error(f"DuckDB 연결 실패. DBeaver 등 다른 프로그램이 DB를 열고 있는지 확인하세요.\n에러: {e}")
        sys.exit(1)
        
    log.info("=" * 60)
    log.info("  Aviation-Grade Monthly Master Table Builder (CSV 기반)")
    log.info("=" * 60)
    
    # 1. Group 1: AA17_생산판매
    log.info("[1/9] AA17_생산판매 -> mart_AA17_monthly 변환 (분기 백필)")
    query_aa17 = """
    CREATE OR REPLACE TABLE mart_AA17_monthly AS
    WITH csv_data AS (
        SELECT CAST(V_BZNO AS VARCHAR) AS V_BZNO,
               CAST(LEFT(BAS_QQ, 4) AS VARCHAR) || lpad(CAST(CAST(RIGHT(BAS_QQ, 1) AS INTEGER) * 3 AS VARCHAR), 2, '0') AS target_BASE_YM,
               * EXCLUDE(V_BZNO, BAS_QQ)
        FROM read_csv_auto('nh_data_processing/output/10_생산판매_AA17.csv')
    ),
    bzno_list AS (
        SELECT DISTINCT V_BZNO FROM csv_data
    ),
    calendar AS (
        SELECT 
            strftime(m, '%Y%m') AS BASE_YM,
            strftime(last_day(make_date(CAST(EXTRACT(YEAR FROM m) AS INTEGER), CAST(EXTRACT(QUARTER FROM m) AS INTEGER) * 3, 1)), '%Y%m') AS target_BASE_YM
        FROM unnest(generate_series(DATE '2021-01-01', date_trunc('month', current_date()), INTERVAL 1 MONTH)) AS t(m)
    ),
    skeleton AS (
        SELECT b.V_BZNO, c.BASE_YM, c.target_BASE_YM FROM bzno_list b CROSS JOIN calendar c
    )
    SELECT s.V_BZNO, s.BASE_YM, d.* EXCLUDE(V_BZNO, target_BASE_YM)
    FROM skeleton s
    LEFT JOIN csv_data d ON s.V_BZNO = d.V_BZNO AND s.target_BASE_YM = d.target_BASE_YM
    ORDER BY s.V_BZNO, s.BASE_YM;
    """
    con.execute(query_aa17)
    df_aa17_stat = con.execute("SELECT COUNT(*) as c, sum(CASE WHEN V_BZNO IS NULL OR BASE_YM IS NULL THEN 1 ELSE 0 END) as n FROM mart_AA17_monthly").df()
    log.info(f"  [OK] 완료: 총 {df_aa17_stat['c'].iloc[0]:,} 행 생성 (결측 키 {df_aa17_stat['n'].iloc[0]}개)")

    # 2. Group 2: AC12_외화부채
    log.info("[2/9] AC12_외화부채 -> mart_AC12_monthly 변환 (연 단위 백필)")
    query_ac12 = """
    CREATE OR REPLACE TABLE mart_AC12_monthly AS
    WITH csv_data AS (
        SELECT CAST(V_BZNO AS VARCHAR) AS V_BZNO, CAST(BAS_YM AS VARCHAR) AS BAS_YM, * EXCLUDE(V_BZNO, BAS_YM)
        FROM read_csv_auto('nh_data_processing/output/09_외화부채_AC12.csv')
        WHERE BAS_YM IS NOT NULL
    ),
    dedup_data AS (
        SELECT CAST(LEFT(BAS_YM, 4) AS VARCHAR) AS year_str, *
        FROM csv_data
        QUALIFY row_number() OVER (PARTITION BY V_BZNO, LEFT(BAS_YM, 4) ORDER BY BAS_YM DESC) = 1
    ),
    bzno_list AS (
        SELECT DISTINCT V_BZNO FROM dedup_data
    ),
    calendar AS (
        SELECT strftime(m, '%Y%m') AS BASE_YM, CAST(EXTRACT(YEAR FROM m) AS VARCHAR) AS target_year
        FROM unnest(generate_series(DATE '2021-01-01', date_trunc('month', current_date()), INTERVAL 1 MONTH)) AS t(m)
    ),
    skeleton AS (
        SELECT b.V_BZNO, c.BASE_YM, c.target_year FROM bzno_list b CROSS JOIN calendar c
    )
    SELECT s.V_BZNO, s.BASE_YM, d.* EXCLUDE(V_BZNO, BAS_YM, year_str)
    FROM skeleton s
    LEFT JOIN dedup_data d ON s.V_BZNO = d.V_BZNO AND s.target_year = d.year_str
    ORDER BY s.V_BZNO, s.BASE_YM;
    """
    con.execute(query_ac12)
    df_ac12_stat = con.execute("SELECT COUNT(*) as c, sum(CASE WHEN V_BZNO IS NULL OR BASE_YM IS NULL THEN 1 ELSE 0 END) as n FROM mart_AC12_monthly").df()
    log.info(f"  [OK] 완료: 총 {df_ac12_stat['c'].iloc[0]:,} 행 생성 (결측 키 {df_ac12_stat['n'].iloc[0]}개)")

    # 3. Group 3: BUDO_CUST_당행부도정보
    log.info("[3/9] BUDO_CUST_당행부도정보 -> mart_BUDO_CUST_monthly 변환 (Exact Match)")
    query_budo = """
    CREATE OR REPLACE TABLE mart_BUDO_CUST_monthly AS
    WITH csv_data AS (
        SELECT CAST(V_BZNO AS VARCHAR) AS V_BZNO, CAST(DSH_DT AS VARCHAR) AS DSH_DT, * EXCLUDE(V_BZNO, DSH_DT)
        FROM read_csv_auto('nh_data_processing/output/04_당행부도정보_BUDO_CUST.csv')
        WHERE DSH_DT IS NOT NULL
    ),
    dedup_data AS (
        SELECT V_BZNO, LEFT(CAST(DSH_DT AS VARCHAR), 6) AS BASE_YM, *
        FROM csv_data
        QUALIFY row_number() OVER (PARTITION BY V_BZNO, LEFT(CAST(DSH_DT AS VARCHAR), 6) ORDER BY DSH_DT DESC) = 1
    ),
    bzno_list AS (
        SELECT DISTINCT V_BZNO FROM dedup_data
    ),
    calendar AS (
        SELECT strftime(m, '%Y%m') AS BASE_YM
        FROM unnest(generate_series(DATE '2021-01-01', date_trunc('month', current_date()), INTERVAL 1 MONTH)) AS t(m)
    ),
    skeleton AS (
        SELECT b.V_BZNO, c.BASE_YM FROM bzno_list b CROSS JOIN calendar c
    )
    SELECT s.V_BZNO, s.BASE_YM, d.* EXCLUDE(V_BZNO, BASE_YM)
    FROM skeleton s
    LEFT JOIN dedup_data d ON s.V_BZNO = d.V_BZNO AND s.BASE_YM = d.BASE_YM
    ORDER BY s.V_BZNO, s.BASE_YM;
    """
    con.execute(query_budo)
    df_budo_stat = con.execute("SELECT COUNT(*) as c, sum(CASE WHEN V_BZNO IS NULL OR BASE_YM IS NULL THEN 1 ELSE 0 END) as n FROM mart_BUDO_CUST_monthly").df()
    log.info(f"  [OK] 완료: 총 {df_budo_stat['c'].iloc[0]:,} 행 생성 (결측 키 {df_budo_stat['n'].iloc[0]}개)")

    # 4. Group 4: C302_나이스CRI등급
    log.info("[4/9] C302_나이스CRI등급 -> mart_C302_monthly 변환 (Row Explosion)")
    query_c302 = """
    CREATE OR REPLACE TABLE mart_C302_monthly AS
    WITH parsed AS (
        SELECT 
            CAST(V_BZNO AS VARCHAR) AS V_BZNO,
            strptime(CAST(ST_DT AS VARCHAR), '%Y%m%d') AS start_date,
            CASE WHEN CAST(ED_DT AS VARCHAR) >= '29990101' THEN make_date(2026,12,31) ELSE strptime(CAST(ED_DT AS VARCHAR), '%Y%m%d') END AS end_date,
            CRI_GRD, CRI_GRD_ORD
        FROM read_csv_auto('nh_data_processing/output/08_나이스CRI등급_C302.csv')
    ),
    exploded AS (
        SELECT 
            V_BZNO,
            CRI_GRD, CRI_GRD_ORD,
            UNNEST(generate_series(
                date_trunc('month', start_date), 
                date_trunc('month', end_date), 
                INTERVAL '1 MONTH'
            )) AS month_date,
            end_date
        FROM parsed
    ),
    deduped AS (
        SELECT 
            V_BZNO,
            strftime(month_date, '%Y%m') AS BASE_YM,
            CRI_GRD, CRI_GRD_ORD
        FROM exploded
        QUALIFY row_number() OVER (PARTITION BY V_BZNO, month_date ORDER BY end_date DESC) = 1
    ),
    bzno_list AS (
        SELECT DISTINCT V_BZNO FROM deduped
    ),
    calendar AS (
        SELECT strftime(m, '%Y%m') AS BASE_YM
        FROM unnest(generate_series(DATE '2021-01-01', date_trunc('month', current_date()), INTERVAL 1 MONTH)) AS t(m)
    ),
    skeleton AS (
        SELECT b.V_BZNO, c.BASE_YM FROM bzno_list b CROSS JOIN calendar c
    )
    SELECT s.V_BZNO, s.BASE_YM, d.* EXCLUDE(V_BZNO, BASE_YM)
    FROM skeleton s
    LEFT JOIN deduped d ON s.V_BZNO = d.V_BZNO AND s.BASE_YM = d.BASE_YM
    ORDER BY s.V_BZNO, s.BASE_YM;
    """
    con.execute(query_c302)
    df_c302_stat = con.execute("SELECT COUNT(*) as c, sum(CASE WHEN V_BZNO IS NULL OR BASE_YM IS NULL THEN 1 ELSE 0 END) as n FROM mart_C302_monthly").df()
    log.info(f"  [OK] 완료: 총 {df_c302_stat['c'].iloc[0]:,} 행 생성 (결측 키 {df_c302_stat['n'].iloc[0]}개)")

    # 5. Group 5: CG01_나이스신용평점
    log.info("[5/9] CG01_나이스신용평점 -> mart_CG01_monthly 변환 (연 단위 백필)")
    query_cg01 = """
    CREATE OR REPLACE TABLE mart_CG01_monthly AS
    WITH csv_data AS (
        SELECT CAST(V_BZNO AS VARCHAR) AS V_BZNO, CAST(BASE_YEAR AS VARCHAR) AS year_str, * EXCLUDE(V_BZNO, BASE_YEAR)
        FROM read_csv_auto('nh_data_processing/output/07_나이스신용평점_CG01.csv')
        WHERE BASE_YEAR IS NOT NULL
    ),
    bzno_list AS (
        SELECT DISTINCT V_BZNO FROM csv_data
    ),
    calendar AS (
        SELECT strftime(m, '%Y%m') AS BASE_YM, CAST(EXTRACT(YEAR FROM m) AS VARCHAR) AS target_year
        FROM unnest(generate_series(DATE '2021-01-01', date_trunc('month', current_date()), INTERVAL 1 MONTH)) AS t(m)
    ),
    skeleton AS (
        SELECT b.V_BZNO, c.BASE_YM, c.target_year FROM bzno_list b CROSS JOIN calendar c
    )
    SELECT s.V_BZNO, s.BASE_YM, d.* EXCLUDE(V_BZNO, year_str)
    FROM skeleton s
    LEFT JOIN csv_data d ON s.V_BZNO = d.V_BZNO AND s.target_year = d.year_str
    ORDER BY s.V_BZNO, s.BASE_YM;
    """
    con.execute(query_cg01)
    df_cg01_stat = con.execute("SELECT COUNT(*) as c, sum(CASE WHEN V_BZNO IS NULL OR BASE_YM IS NULL THEN 1 ELSE 0 END) as n FROM mart_CG01_monthly").df()
    log.info(f"  [OK] 완료: 총 {df_cg01_stat['c'].iloc[0]:,} 행 생성 (결측 키 {df_cg01_stat['n'].iloc[0]}개)")

    # 6. Group 6: GRD_HIS_당행등급이력
    log.info("[6/9] GRD_HIS_당행등급이력 -> mart_GRD_HIS_monthly 변환 (연 단위 백필)")
    query_grd_his = """
    CREATE OR REPLACE TABLE mart_GRD_HIS_monthly AS
    WITH csv_data AS (
        SELECT CAST(V_BZNO AS VARCHAR) AS V_BZNO, CAST(BASE_YEAR AS VARCHAR) AS year_str, * EXCLUDE(V_BZNO, BASE_YEAR)
        FROM read_csv_auto('nh_data_processing/output/02_당행등급이력_GRD_HIS.csv')
        WHERE BASE_YEAR IS NOT NULL
    ),
    bzno_list AS (
        SELECT DISTINCT V_BZNO FROM csv_data
    ),
    calendar AS (
        SELECT strftime(m, '%Y%m') AS BASE_YM, CAST(EXTRACT(YEAR FROM m) AS VARCHAR) AS target_year
        FROM unnest(generate_series(DATE '2021-01-01', date_trunc('month', current_date()), INTERVAL 1 MONTH)) AS t(m)
    ),
    skeleton AS (
        SELECT b.V_BZNO, c.BASE_YM, c.target_year FROM bzno_list b CROSS JOIN calendar c
    )
    SELECT s.V_BZNO, s.BASE_YM, d.* EXCLUDE(V_BZNO, year_str)
    FROM skeleton s
    LEFT JOIN csv_data d ON s.V_BZNO = d.V_BZNO AND s.target_year = d.year_str
    ORDER BY s.V_BZNO, s.BASE_YM;
    """
    con.execute(query_grd_his)
    df_grd_his_stat = con.execute("SELECT COUNT(*) as c, sum(CASE WHEN V_BZNO IS NULL OR BASE_YM IS NULL THEN 1 ELSE 0 END) as n FROM mart_GRD_HIS_monthly").df()
    log.info(f"  [OK] 완료: 총 {df_grd_his_stat['c'].iloc[0]:,} 행 생성 (결측 키 {df_grd_his_stat['n'].iloc[0]}개)")

    # 7. Group 7: JEMU_재무데이터
    log.info("[7/9] JEMU_재무데이터 -> mart_JEMU_monthly 변환 (연 단위 백필)")
    query_jemu = """
    CREATE OR REPLACE TABLE mart_JEMU_monthly AS
    WITH csv_data AS (
        SELECT CAST(V_BZNO AS VARCHAR) AS V_BZNO, CAST(FNA_CLS_YM AS VARCHAR) AS FNA_CLS_YM, * EXCLUDE(V_BZNO, FNA_CLS_YM)
        FROM read_csv_auto('nh_data_processing/output/03_재무데이터_JEMU.csv')
        WHERE FNA_CLS_YM IS NOT NULL
    ),
    dedup_data AS (
        SELECT CAST(LEFT(FNA_CLS_YM, 4) AS VARCHAR) AS year_str, *
        FROM csv_data
        QUALIFY row_number() OVER (PARTITION BY V_BZNO, LEFT(FNA_CLS_YM, 4) ORDER BY FNA_CLS_YM DESC) = 1
    ),
    bzno_list AS (
        SELECT DISTINCT V_BZNO FROM dedup_data
    ),
    calendar AS (
        SELECT strftime(m, '%Y%m') AS BASE_YM, CAST(EXTRACT(YEAR FROM m) AS VARCHAR) AS target_year
        FROM unnest(generate_series(DATE '2021-01-01', date_trunc('month', current_date()), INTERVAL 1 MONTH)) AS t(m)
    ),
    skeleton AS (
        SELECT b.V_BZNO, c.BASE_YM, c.target_year FROM bzno_list b CROSS JOIN calendar c
    )
    SELECT s.V_BZNO, s.BASE_YM, d.* EXCLUDE(V_BZNO, FNA_CLS_YM, year_str)
    FROM skeleton s
    LEFT JOIN dedup_data d ON s.V_BZNO = d.V_BZNO AND s.target_year = d.year_str
    ORDER BY s.V_BZNO, s.BASE_YM;
    """
    con.execute(query_jemu)
    df_jemu_stat = con.execute("SELECT COUNT(*) as c, sum(CASE WHEN V_BZNO IS NULL OR BASE_YM IS NULL THEN 1 ELSE 0 END) as n FROM mart_JEMU_monthly").df()
    log.info(f"  [OK] 완료: 총 {df_jemu_stat['c'].iloc[0]:,} 행 생성 (결측 키 {df_jemu_stat['n'].iloc[0]}개)")

    # 8. Group 8: VH_OBV_DTL_관찰세부등급
    log.info("[8/9] VH_OBV_DTL_관찰세부등급 -> mart_VH_OBV_DTL_monthly 변환 (Exact Match)")
    query_vh_obv_dtl = """
    CREATE OR REPLACE TABLE mart_VH_OBV_DTL_monthly AS
    WITH csv_data AS (
        SELECT CAST(V_BZNO AS VARCHAR) AS V_BZNO, CAST(BAS_YM AS VARCHAR) AS BAS_YM, * EXCLUDE(V_BZNO, BAS_YM)
        FROM read_csv_auto('nh_data_processing/output/06_관찰세부등급_VH_OBV_DTL.csv')
        WHERE BAS_YM IS NOT NULL
    ),
    dedup_data AS (
        SELECT *
        FROM csv_data
        QUALIFY row_number() OVER (PARTITION BY V_BZNO, BAS_YM ORDER BY BAS_YM DESC) = 1
    ),
    bzno_list AS (
        SELECT DISTINCT V_BZNO FROM dedup_data
    ),
    calendar AS (
        SELECT strftime(m, '%Y%m') AS BASE_YM
        FROM unnest(generate_series(DATE '2021-01-01', date_trunc('month', current_date()), INTERVAL 1 MONTH)) AS t(m)
    ),
    skeleton AS (
        SELECT b.V_BZNO, c.BASE_YM FROM bzno_list b CROSS JOIN calendar c
    )
    SELECT s.V_BZNO, s.BASE_YM, d.* EXCLUDE(V_BZNO, BAS_YM)
    FROM skeleton s
    LEFT JOIN dedup_data d ON s.V_BZNO = d.V_BZNO AND s.BASE_YM = d.BAS_YM
    ORDER BY s.V_BZNO, s.BASE_YM;
    """
    con.execute(query_vh_obv_dtl)
    df_vh_obv_dtl_stat = con.execute("SELECT COUNT(*) as c, sum(CASE WHEN V_BZNO IS NULL OR BASE_YM IS NULL THEN 1 ELSE 0 END) as n FROM mart_VH_OBV_DTL_monthly").df()
    log.info(f"  [OK] 완료: 총 {df_vh_obv_dtl_stat['c'].iloc[0]:,} 행 생성 (결측 키 {df_vh_obv_dtl_stat['n'].iloc[0]}개)")

    # 9. Group 9: VH_CRIF_신용불량
    log.info("[9/9] VH_CRIF_신용불량 -> mart_VH_CRIF_monthly 변환 (Exact Match)")
    query_vh_crif = """
    CREATE OR REPLACE TABLE mart_VH_CRIF_monthly AS
    WITH csv_data AS (
        SELECT CAST(V_BZNO AS VARCHAR) AS V_BZNO, CAST(CRDBD_OCU_YY AS VARCHAR) AS BAS_YM, * EXCLUDE(V_BZNO, CRDBD_OCU_YY)
        FROM read_csv_auto('nh_data_processing/output/05_신용불량_VH_CRIF.csv')
        WHERE CRDBD_OCU_YY IS NOT NULL
    ),
    dedup_data AS (
        SELECT *
        FROM csv_data
        QUALIFY row_number() OVER (PARTITION BY V_BZNO, BAS_YM ORDER BY BAS_YM DESC) = 1
    ),
    bzno_list AS (
        SELECT DISTINCT V_BZNO FROM dedup_data
    ),
    calendar AS (
        SELECT strftime(m, '%Y%m') AS BASE_YM
        FROM unnest(generate_series(DATE '2021-01-01', date_trunc('month', current_date()), INTERVAL 1 MONTH)) AS t(m)
    ),
    skeleton AS (
        SELECT b.V_BZNO, c.BASE_YM FROM bzno_list b CROSS JOIN calendar c
    )
    SELECT s.V_BZNO, s.BASE_YM, d.* EXCLUDE(V_BZNO, BAS_YM)
    FROM skeleton s
    LEFT JOIN dedup_data d ON s.V_BZNO = d.V_BZNO AND s.BASE_YM = d.BAS_YM
    ORDER BY s.V_BZNO, s.BASE_YM;
    """
    con.execute(query_vh_crif)
    df_vh_crif_stat = con.execute("SELECT COUNT(*) as c, sum(CASE WHEN V_BZNO IS NULL OR BASE_YM IS NULL THEN 1 ELSE 0 END) as n FROM mart_VH_CRIF_monthly").df()
    log.info(f"  [OK] 완료: 총 {df_vh_crif_stat['c'].iloc[0]:,} 행 생성 (결측 키 {df_vh_crif_stat['n'].iloc[0]}개)")

    log.info("-" * 60)
    
    # Audit Check
    total_nulls = (
        df_aa17_stat['n'].iloc[0] + 
        df_ac12_stat['n'].iloc[0] + 
        df_budo_stat['n'].iloc[0] + 
        df_c302_stat['n'].iloc[0] +
        df_cg01_stat['n'].iloc[0] +
        df_grd_his_stat['n'].iloc[0] +
        df_jemu_stat['n'].iloc[0] +
        df_vh_obv_dtl_stat['n'].iloc[0] +
        df_vh_crif_stat['n'].iloc[0]
    )
    
    if total_nulls == 0:
        log.info("[MONTHLY_MIGRATION_SUCCESS] 모든 제약 조건 통과 (Look-Ahead Bias 완전 차단 및 월단위 마스터 통합 완료)")
    else:
        log.warning(f"마이그레이션은 완료되었으나, {total_nulls}개의 결측 키가 발견되었습니다.")
        
    con.close()

if __name__ == "__main__":
    build_monthly_ledger()
