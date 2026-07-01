import os
import sys
import numpy as np
import pandas as pd
import datetime
import duckdb
import logging
import gc

# ─── 프로젝트 루트 경로 보정 ───
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_SCRIPT_DIR))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# 주요 경제 뉴스 키워드 풀
# ──────────────────────────────────────────────
SAMPLE_KEYWORDS = [
    "반도체 공급망 붕괴", "미 연준 금리 인상", "부동산 시장 과열", "원자재 가격 급등",
    "탄소중립 정책 강화", "수출 호황 지속", "가계부채 리스크", "건설경기 침체",
    "AI 산업 투자 확대", "화학물질 규제 강화", "자동차 판매 부진", "의약품 특허 만료",
    "물류 대란 장기화", "소비심리 위축", "은행 건전성 강화", "철강 수요 감소",
    "전기차 보급 가속화", "유가 폭락", "인플레이션 우려 확산", "식품 원가 상승",
]

def generate_and_save_news(seed: int = 42):
    """
    합성 뉴스 감성 데이터를 5년치(2021년~현재)로 생성 후,
    90일 이동평균 및 bfill 처리를 거쳐 DuckDB에 영구 적재합니다.
    """
    np.random.seed(seed)

    # 1. 글로벌 시계열 범위 파라미터 자동화 및 동적 확장
    start_date = "2021-01-01"
    end_date = datetime.date.today().strftime("%Y-%m-%d")
    
    log.info(f"1. 뉴스 시계열 범위 설정 완료: {start_date} ~ {end_date}")

    # 영업일 기준 날짜 생성 (주말 제외)
    biz_dates = pd.bdate_range(start=start_date, end=end_date)
    
    records = []
    for kw in SAMPLE_KEYWORDS:
        base_bias = np.random.uniform(-0.3, 0.3)
        for dt in biz_dates:
            day_of_year = dt.timetuple().tm_yday
            seasonal = 0.15 * np.sin(2 * np.pi * day_of_year / 365)
            noise = np.random.normal(0, 0.25)
            score = np.clip(base_bias + seasonal + noise, -1.0, 1.0)

            records.append({
                "date": dt.strftime("%Y-%m-%d"),
                "keyword": kw,
                "sentiment_score": round(score, 6),
            })

    # 메모리 효율을 위해 벡터화 연산 기반의 DataFrame 생성
    df = pd.DataFrame(records)
    
    log.info(f"2. 원시 데이터 생성 완료: 총 {len(df):,}건")

    # 2. 대용량 데이터 처리를 위한 90일 rolling 및 bfill 최적화
    log.info("3. 판다스 벡터화 기반 90일 이동평균(MA) 계산 및 과거 시점 bfill 결측치 방어 처리 중...")
    
    # 시계열 순서가 뒤섞이지 않도록 정렬 (bfill의 필수 전제 조건)
    df.sort_values(by=["keyword", "date"], inplace=True)
    df.reset_index(drop=True, inplace=True)
    
    # groupby transform을 이용한 고속 90영업일 롤링 평균 산출 후, 최과거 89영업일 결측치를 bfill로 대치
    df["sentiment_score_ma90"] = df.groupby("keyword")["sentiment_score"].transform(
        lambda x: x.rolling(window=90).mean().bfill()
    )
    
    nan_count = df["sentiment_score_ma90"].isna().sum()
    if nan_count > 0:
        log.warning(f"  발견된 결측치 수: {nan_count} 개 (bfill 이후에도 결측치가 남아있습니다.)")
    else:
        log.info("  결측치 0개 달성. bfill 로직이 최과거 구간에 완벽하게 적용되었습니다.")

    # 3. DuckDB 적재 및 덮어쓰기 (Overwrite) 제약 조건 준수
    log.info("4. DuckDB 데이터베이스 적재 준비...")
    db_path = os.path.join(_PROJECT_ROOT, "database", "nh_credit_risk.db")
    
    with duckdb.connect(db_path) as con:
        # CREATE OR REPLACE 구문을 활용하여 기존 테이블을 덮어쓰고 최신 데이터로 대체
        con.execute("CREATE OR REPLACE TABLE raw_daily_news_sentiment AS SELECT * FROM df")
        
    log.info(f"[NEWS_EXPANSION_SUCCESS] 시계열 범위: {start_date} ~ {end_date}")
    log.info(f"DuckDB `raw_daily_news_sentiment` 테이블 적재 완료 (총 {len(df):,}건)")
    
    # 메모리 반환
    del df
    gc.collect()

if __name__ == "__main__":
    generate_and_save_news()
