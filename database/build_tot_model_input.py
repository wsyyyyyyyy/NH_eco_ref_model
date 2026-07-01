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

def build_tot_model_input():
    db_path = os.path.join(_PROJECT_ROOT, "database", "nh_credit_risk.db")
    
    try:
        con = duckdb.connect(db_path)
    except duckdb.IOException as e:
        log.error(f"DuckDB 연결 실패. DBeaver 등 다른 프로그램이 DB를 열고 있는지 확인하세요.\n에러: {e}")
        sys.exit(1)

    log.info("=" * 60)
    log.info("  Building Final Monthly Model Input: nh_data_monthly.csv")
    log.info("=" * 60)

    # 1. 202401 ~ 202604 캘린더 생성
    # 2. UPCHE_TOT 데이터와 크로스 조인하여 Skeleton 생성
    # 3. 9개 테이블과 LEFT JOIN
    
    output_path = "nh_data_processing/output/nh_data_monthly.csv"
    
    query = f"""
    COPY (
        WITH upche_data AS (
            SELECT CAST(V_BZNO AS VARCHAR) AS V_BZNO, * EXCLUDE(V_BZNO)
            FROM read_csv_auto('nh_data_processing/output/01_기업정보_UPCHE_TOT.csv')
        ),
        calendar AS (
            SELECT strftime(m, '%Y%m') AS BASE_YM
            FROM unnest(generate_series(DATE '2024-01-01', DATE '2026-04-01', INTERVAL 1 MONTH)) AS t(m)
        ),
        skeleton AS (
            SELECT u.*, c.BASE_YM
            FROM upche_data u CROSS JOIN calendar c
        )
        SELECT 
            s.*,
            t1.* EXCLUDE(V_BZNO, BASE_YM),
            t2.* EXCLUDE(V_BZNO, BASE_YM),
            t3.* EXCLUDE(V_BZNO, BASE_YM),
            t4.* EXCLUDE(V_BZNO, BASE_YM),
            t5.* EXCLUDE(V_BZNO, BASE_YM),
            t6.* EXCLUDE(V_BZNO, BASE_YM),
            t7.* EXCLUDE(V_BZNO, BASE_YM),
            t8.* EXCLUDE(V_BZNO, BASE_YM),
            t9.* EXCLUDE(V_BZNO, BASE_YM)
        FROM skeleton s
        LEFT JOIN mart_AA17_monthly t1 ON s.V_BZNO = t1.V_BZNO AND s.BASE_YM = t1.BASE_YM
        LEFT JOIN mart_AC12_monthly t2 ON s.V_BZNO = t2.V_BZNO AND s.BASE_YM = t2.BASE_YM
        LEFT JOIN mart_BUDO_CUST_monthly t3 ON s.V_BZNO = t3.V_BZNO AND s.BASE_YM = t3.BASE_YM
        LEFT JOIN mart_C302_monthly t4 ON s.V_BZNO = t4.V_BZNO AND s.BASE_YM = t4.BASE_YM
        LEFT JOIN mart_CG01_monthly t5 ON s.V_BZNO = t5.V_BZNO AND s.BASE_YM = t5.BASE_YM
        LEFT JOIN mart_GRD_HIS_monthly t6 ON s.V_BZNO = t6.V_BZNO AND s.BASE_YM = t6.BASE_YM
        LEFT JOIN mart_JEMU_monthly t7 ON s.V_BZNO = t7.V_BZNO AND s.BASE_YM = t7.BASE_YM
        LEFT JOIN mart_VH_CRIF_monthly t8 ON s.V_BZNO = t8.V_BZNO AND s.BASE_YM = t8.BASE_YM
        LEFT JOIN mart_VH_OBV_DTL_monthly t9 ON s.V_BZNO = t9.V_BZNO AND s.BASE_YM = t9.BASE_YM
        ORDER BY s.V_BZNO, s.BASE_YM
    ) TO '{output_path}' WITH (HEADER, DELIMITER ',');
    """

    log.info("쿼리 실행 중 (결합 및 파일 내보내기)...")
    con.execute(query)
    log.info(f"완료: {output_path} 생성됨")
    
    con.close()

if __name__ == "__main__":
    build_tot_model_input()
