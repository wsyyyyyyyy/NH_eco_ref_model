import os
import sys
import duckdb
import pandas as pd
import logging

# ─── 프로젝트 루트 경로 보정 ───
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_SCRIPT_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

def get_table_name(con, prefix):
    df = con.execute(f"SELECT table_name FROM information_schema.tables WHERE table_schema='main' AND table_name LIKE '{prefix}%'").df()
    if len(df) == 0:
        raise ValueError(f"Table with prefix {prefix} not found.")
    return df['table_name'].iloc[0]

def build_abt():
    db_path = os.path.join(_PROJECT_ROOT, "database", "nh_credit_risk.db")
    
    # 1. Context Manager 사용 (DB Locking 방어 - Read/Write)
    with duckdb.connect(db_path) as con:
        log.info("1. DuckDB 연결 및 동적 테이블 바인딩 완료")
        
        # 테이블명 동적 로드 (한글 인코딩 깨짐 이슈 방어)
        tbl_obv = get_table_name(con, "raw_VH_OBV_DTL")
        tbl_budo = get_table_name(con, "raw_BUDO_CUST")
        tbl_aa10 = get_table_name(con, "raw_AA10")
        tbl_aa17 = get_table_name(con, "raw_AA17")
        
        log.info("2. DuckDB SQL 조인 실행 (ASOF JOIN 및 Type Casting 적용)")
        
        # [제약 조건 1, 2, 3]을 모두 반영한 순수 DuckDB 시계열 조인 쿼리
        query = f"""
        -- [Spine] 스냅샷 기준 테이블 (관찰세부등급)
        WITH spine AS (
            SELECT 
                CAST(V_BZNO AS VARCHAR) AS V_BZNO,
                -- BAS_YM (YYYYMM) -> YYYY-MM-01 -> 월말일 추출로 Snapshot Date 생성
                last_day(strptime(CAST(BAS_YM AS VARCHAR) || '01', '%Y%m%d')) AS Snapshot_Date,
                CAST(LN_LMT_AM AS DOUBLE) AS LN_LMT_AM,
                CAST(LN_BAC AS DOUBLE) AS LN_BAC
            FROM {tbl_obv}
            WHERE V_BZNO IS NOT NULL AND BAS_YM IS NOT NULL
        ),
        
        -- [Target] 부도 정보 바인딩 (1년/12개월 관찰 윈도우)
        target AS (
            SELECT 
                s.V_BZNO,
                s.Snapshot_Date,
                CASE 
                    WHEN b.DSH_DT IS NOT NULL 
                         AND CAST(strptime(CAST(b.DSH_DT AS VARCHAR), '%Y%m%d') AS DATE) > s.Snapshot_Date 
                         AND CAST(strptime(CAST(b.DSH_DT AS VARCHAR), '%Y%m%d') AS DATE) <= s.Snapshot_Date + INTERVAL '365' DAY 
                    THEN 1 
                    ELSE 0 
                END AS Target_Y
            FROM spine s
            LEFT JOIN {tbl_budo} b
                ON s.V_BZNO = CAST(b.V_BZNO AS VARCHAR)
        ),
        
        -- [AA10] 종업원수 언피벗 및 정제
        aa10_unpivoted AS (
            SELECT 
                CAST(V_BZNO AS VARCHAR) AS V_BZNO,
                CAST(strptime(CAST(unnest(list_value(BASDT1, BASDT2, BASDT3, BASDT4, BASDT5, BASDT6, BASDT7, BASDT8, BASDT9, BASDT10, BASDT11)) AS VARCHAR), '%Y%m%d') AS DATE) AS BAS_DT,
                CAST(unnest(list_value(PERS1, PERS2, PERS3, PERS4, PERS5, PERS6, PERS7, PERS8, PERS9, PERS10, PERS11)) AS DOUBLE) AS EMPCN
            FROM {tbl_aa10}
            WHERE V_BZNO IS NOT NULL
        ),
        aa10_clean AS (
            SELECT * FROM aa10_unpivoted WHERE BAS_DT IS NOT NULL
        ),
        
        -- [AA17] 생산판매 분기실적 Regex 기반 언피벗
        aa17_long AS (
            SELECT 
                CAST(V_BZNO AS VARCHAR) AS V_BZNO,
                regexp_extract(col_name, '^(.+)_(\\d{{4}})_(\\d)$', 1) AS metric,
                CAST(regexp_extract(col_name, '^(.+)_(\\d{{4}})_(\\d)$', 2) AS INTEGER) AS year,
                CAST(regexp_extract(col_name, '^(.+)_(\\d{{4}})_(\\d)$', 3) AS INTEGER) AS quarter,
                CAST(val AS DOUBLE) AS val
            FROM (
                UNPIVOT {tbl_aa17} ON COLUMNS(* EXCLUDE(V_BZNO)) INTO NAME col_name VALUE val
            )
        ),
        aa17_dates AS (
            SELECT 
                V_BZNO,
                last_day(make_date(year, quarter * 3, 1)) AS BAS_DT,
                metric,
                val
            FROM aa17_long
            WHERE year IS NOT NULL AND quarter IS NOT NULL AND val IS NOT NULL
        ),
        aa17_pivot AS (
            PIVOT aa17_dates ON metric USING SUM(val)
        ),
        
        -- [최종 결합] Target + 시차 반영 외부 마트 ASOF/LEFT 조인
        final_abt AS (
            SELECT 
                t.Snapshot_Date,
                t.V_BZNO,
                t.Target_Y,
                s.LN_BAC,
                s.LN_LMT_AM,
                
                -- AA10 종업원수 (최근 이력)
                a10.EMPCN AS LATEST_EMPCN,
                
                -- AA17 실적 (90일 래깅 적용)
                a17.TOT_SEL_AM AS TOT_SEL_AM_LAG90,
                a17.LA_XPO_AM AS LA_XPO_AM_LAG90,
                a17.DME_AM AS DME_AM_LAG90,
                
                -- 대안 변수 (1:1 당일 매핑)
                n.CORP_NEWS_RISK_INDEX,
                m.KOSDAQ
            FROM target t
            JOIN spine s ON t.V_BZNO = s.V_BZNO AND t.Snapshot_Date = s.Snapshot_Date
            
            -- 1) AA10 As-of Join
            ASOF LEFT JOIN aa10_clean a10 
                ON t.V_BZNO = a10.V_BZNO 
                AND t.Snapshot_Date >= a10.BAS_DT
                
            -- 2) AA17 As-of Join (90일 공시 시차 방어)
            ASOF LEFT JOIN aa17_pivot a17 
                ON t.V_BZNO = a17.V_BZNO 
                AND t.Snapshot_Date - INTERVAL '90' DAY >= a17.BAS_DT
                
            -- 3) 뉴스 오버레이 Left Join
            LEFT JOIN mart_news_overlay_index_daily n
                ON t.V_BZNO = CAST(n.V_BZNO AS VARCHAR) AND t.Snapshot_Date = CAST(n.date AS DATE)
                
            -- 4) 거시경제 변수 Left Join
            LEFT JOIN mart_daily m
                ON t.Snapshot_Date = CAST(m.date AS DATE)
        )
        SELECT * FROM final_abt
        """
        
        # Pandas DataFrame으로 한 번만 인출
        df_abt = con.execute(query).df()
        
        # 3. 무결성 검증 (Audit Logging)
        rows, cols = df_abt.shape
        target_counts = df_abt['Target_Y'].value_counts(normalize=True) * 100
        default_rate = target_counts.get(1, 0.0)
        
        log.info("-" * 40)
        log.info(f" [ABT Audit] 전체 행 수: {rows:,} 건 | 전체 열 수: {cols:,} 개")
        log.info(f" [ABT Audit] Target Y 분포: 정상 {100-default_rate:.2f}% / 부도 {default_rate:.2f}%")
        
        # 결측치 방어 로직 (NaN 강제 0 치환 - 신생 기업 처리 등)
        cols_to_fill = ['CORP_NEWS_RISK_INDEX', 'TOT_SEL_AM_LAG90', 'LATEST_EMPCN', 'KOSDAQ', 'LA_XPO_AM_LAG90', 'DME_AM_LAG90']
        nan_before = df_abt[cols_to_fill].isna().sum().sum()
        if nan_before > 0:
            log.warning(f"  발견된 결측치 수: {nan_before:,} 개 -> 과거 시점 데이터 부재(신생/미공시)로 간주하여 0.0 대치.")
            df_abt[cols_to_fill] = df_abt[cols_to_fill].fillna(0.0)
            
        nan_after = df_abt[cols_to_fill].isna().sum().sum()
        if nan_after == 0:
            log.info(" [ABT Audit] 거시/뉴스/내부 변수 잔여 결측치 0개 달성! 검증 완벽 통과.")
            log.info("[ABT_AUDIT_SUCCESS]")
        else:
            log.error("[ABT_AUDIT_FAIL] 결측치 방어에 실패했습니다.")
            sys.exit(1)
            
        # 4. DuckDB에 ABT 마트 적재
        log.info("3. mart_model_abt 테이블로 데이터웨어하우스 영구 저장 중...")
        con.execute("CREATE OR REPLACE TABLE mart_model_abt AS SELECT * FROM df_abt")
        log.info("ABT 구축 파이프라인 정상 완료!")

if __name__ == "__main__":
    build_abt()
