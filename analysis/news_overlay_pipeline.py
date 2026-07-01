"""
analysis/news_overlay_pipeline.py
=================================
뉴스 감성 기반 차주별 리스크 오버레이 지표(Overlay Index) 산출 메인 파이프라인.

3단계 데이터 공학 아키텍처:
  ├── Phase 1: 매크로 키워드 감성 분석, 휴일 롤오버 및 90일 이동평균 평활화 (Macro Level)
  ├── Phase 2: 업종 임베딩 매칭 기반 차주별 유사도 DuckDB 정적 캐싱 (Micro Level)
  └── Phase 3: 최종 차주별 뉴스 리스크 오버레이 스코어 가중평균 산출 (Fusion Level)

설계 원칙:
  - 주말/공휴일 뉴스 익영업일 전향 롤오버 (Forward Roll-over)
  - DuckDB를 활용한 대규모 연산 부하 최적화 (SQL 기반 매크로-미크로 조인)
  - 단순 합산 방식의 왜곡을 방지하는 유사도 기반 가중 평균 점수(Weighted Average) 산출
  - 결과물은 Data Warehouse (mart_news_overlay_index_daily)에 직접 적재

Usage
-----
    # 커맨드라인 실행 (프로젝트 루트에서)
    python -m analysis.news_overlay_pipeline

    # 또는 모듈 직접 실행
    python analysis/news_overlay_pipeline.py

Author  : Data Engineering Team
Version : 2.0.0 (DuckDB Refactored)
"""

import os
import sys
import logging
import warnings
from typing import Callable
import datetime

import numpy as np
import pandas as pd
import holidays
import duckdb

# ─── 프로젝트 루트 경로 보정 ───
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_SCRIPT_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from analysis.news_overlay.config import (
    CORP_MASTER_FILE,
    NEWS_INPUT_FILE,
    OUTPUT_DIR,
    OUTPUT_FILE,
    MA_WINDOW,
    MA_MIN_PERIODS,
    EMBEDDING_DIM,
    SCORE_CLIP_MIN,
    SCORE_CLIP_MAX,
    SIMILARITY_THRESHOLD,
    CORP_FILE_SEPARATOR,
    CORP_FILE_HEADER_ROW,
    CORP_FILE_SKIP_ROWS,
    CORP_KEY_COL,
    CORP_INDUSTRY_COL,
    LOG_DIR,
    LOG_FILE,
)
from analysis.news_overlay.industry_master import get_industry_name
from database.db_migration import DB_FILE, save_mart_to_db

warnings.filterwarnings("ignore")


# ═══════════════════════════════════════════════════
# 로깅 설정
# ═══════════════════════════════════════════════════

def _setup_logging() -> logging.Logger:
    """파이프라인 전용 로거 초기화."""
    os.makedirs(LOG_DIR, exist_ok=True)

    logger = logging.getLogger("NEWS_OVERLAY")
    logger.setLevel(logging.DEBUG)

    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        "[%(asctime)s] %(levelname)-7s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    fh = logging.FileHandler(LOG_FILE, mode="w", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    return logger

log = _setup_logging()


# ═══════════════════════════════════════════════════
# Phase 1: 매크로 키워드 감성 분석, 휴일 롤오버 및 평활화
# ═══════════════════════════════════════════════════

def phase1_macro_smoothing(df_news: pd.DataFrame) -> pd.DataFrame:
    """
    [Phase 1] 휴일 뉴스 Forward Roll-over 및 90일 이동평균 평활화.

    Parameters
    ----------
    df_news : pd.DataFrame
        컬럼: [date, keyword, sentiment_score]

    Returns
    -------
    pd.DataFrame
        원본 + 파생 컬럼 `sentiment_score_ma90d` 추가, date 조정됨
    """
    log.info("=" * 60)
    log.info("Phase 1: Holiday Roll-over & 90D MA Smoothing")
    log.info("=" * 60)

    df = df_news.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"])

    # ── 한국 공휴일 및 BDay 정의 ──
    kr_holidays = holidays.KR(years=df["date"].dt.year.unique().tolist())
    # 휴일이 아닌 평일(월~금)을 영업일로 간주
    bday = pd.offsets.CustomBusinessDay(holidays=list(kr_holidays.keys()))

    # ── 휴일 롤오버(Forward Roll-over) 처리 ──
    log.info("  휴일/주말 뉴스 데이터 익영업일 전향(Roll-over) 처리 중...")
    
    def get_next_bday(d: pd.Timestamp) -> pd.Timestamp:
        # 주말(5: 토, 6: 일)이거나 공휴일인 경우 다음 영업일로 이동
        if d.weekday() >= 5 or d.date() in kr_holidays:
            return d + bday
        return d

    original_dates = df["date"].copy()
    df["date"] = df["date"].apply(get_next_bday)
    
    roll_count = (original_dates != df["date"]).sum()
    log.info(f"  총 {roll_count:,}건의 비영업일 뉴스가 익영업일로 편입됨.")

    # ── 키워드-날짜별 그룹핑 (롤오버로 인해 같은 날짜에 뉴스가 중복될 수 있음) ──
    # 같은 날짜로 이동된 뉴스들의 감성 점수는 해당 일자의 평균으로 합산/정규화
    df = df.groupby(["keyword", "date"], as_index=False)["sentiment_score"].mean()

    df = df.sort_values(["keyword", "date"]).reset_index(drop=True)

    log.info(f"  입력 건수: {len(df):,} | 키워드 수: {df['keyword'].nunique()}")
    log.info(f"  날짜 범위: {df['date'].min().date()} ~ {df['date'].max().date()}")

    # ── 90일 이동평균 연산 (벡터화) ──
    df["sentiment_score_ma90d"] = (
        df.groupby("keyword")["sentiment_score"]
        .transform(lambda s: s.rolling(window=MA_WINDOW, min_periods=MA_MIN_PERIODS).mean())
    )
    df["sentiment_score_ma90d"] = (
        df.groupby("keyword")["sentiment_score_ma90d"]
        .transform(lambda s: s.bfill())
    )
    df["sentiment_score_ma90d"] = df["sentiment_score_ma90d"].fillna(0.0)

    log.info(f"  [OK] Phase 1 Complete | sentiment_score_ma90d stats:")
    log.info(f"     mean={df['sentiment_score_ma90d'].mean():.4f}  "
             f"std={df['sentiment_score_ma90d'].std():.4f}")

    return df


# ═══════════════════════════════════════════════════
# Phase 2: 업종 임베딩 매칭 기반 차주별 유사도 DuckDB 캐싱
# ═══════════════════════════════════════════════════

def get_embedding(text: str) -> np.ndarray:
    """결정론적 해시 기반 의사(pseudo) 임베딩"""
    seed = int.from_bytes(text.encode("utf-8")[:8], byteorder="big") % (2**31)
    rng = np.random.RandomState(seed)
    vec = rng.randn(EMBEDDING_DIM).astype(np.float32)
    norm = np.linalg.norm(vec)
    return vec / norm if norm > 0 else vec

def compute_cosine_similarity(vec_a: np.ndarray, vec_b: np.ndarray) -> float:
    norm_a, norm_b = np.linalg.norm(vec_a), np.linalg.norm(vec_b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.clip(np.dot(vec_a, vec_b) / (norm_a * norm_b), 0.0, 1.0))

def load_corp_master() -> pd.DataFrame:
    log.info("  기업 마스터 파일 로드 중...")
    df_corp = pd.read_csv(
        CORP_MASTER_FILE, sep=CORP_FILE_SEPARATOR, header=CORP_FILE_HEADER_ROW,
        skiprows=CORP_FILE_SKIP_ROWS, dtype=str, engine="python", on_bad_lines="skip"
    )
    df_corp.columns = df_corp.columns.str.strip()
    df_corp = df_corp[[CORP_KEY_COL, CORP_INDUSTRY_COL]].copy()
    df_corp[CORP_INDUSTRY_COL] = df_corp[CORP_INDUSTRY_COL].str.strip()
    df_corp = df_corp.dropna(subset=[CORP_INDUSTRY_COL])
    df_corp = df_corp[df_corp[CORP_INDUSTRY_COL].str.len() > 0]
    df_corp["industry_name"] = df_corp[CORP_INDUSTRY_COL].apply(get_industry_name)
    return df_corp.reset_index(drop=True)

def ensure_lookup_industry_keyword_sim(
    con: duckdb.DuckDBPyConnection,
    unique_keywords: list[str],
    unique_industries: list[str],
    embedding_fn: Callable[[str], np.ndarray] | None = None
) -> None:
    """
    [Phase 2] DuckDB에 `lookup_industry_keyword_sim` 정적 테이블을 구성.
    이미 존재하면 연산을 스킵 (연산 부하 0).
    """
    log.info("")
    log.info("=" * 60)
    log.info("Phase 2: DuckDB Static Similarity Lookup (Caching)")
    log.info("=" * 60)

    # 테이블 존재 여부 확인
    tables = con.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'main' AND table_name = 'lookup_industry_keyword_sim'").fetchall()
    
    if tables:
        log.info("  [SKIP] 'lookup_industry_keyword_sim' 테이블이 이미 존재합니다. 유사도 연산을 생략합니다.")
        return

    log.info("  [COMPUTE] 유사도 매스터 테이블이 없습니다. 최초 1회 생성 연산을 시작합니다...")
    if embedding_fn is None:
        embedding_fn = get_embedding

    kw_embeddings = {kw: embedding_fn(kw) for kw in unique_keywords}
    ind_embeddings = {ind: embedding_fn(ind) for ind in unique_industries}

    sim_records = []
    for kw in unique_keywords:
        kw_vec = kw_embeddings[kw]
        for ind in unique_industries:
            sim = compute_cosine_similarity(kw_vec, ind_embeddings[ind])
            sim_records.append({
                "keyword": kw,
                "industry_name": ind,
                "similarity_weight": round(sim, 6)
            })

    df_sim_matrix = pd.DataFrame(sim_records)
    
    # DuckDB에 테이블 영구 저장
    con.execute("CREATE TABLE lookup_industry_keyword_sim AS SELECT * FROM df_sim_matrix")
    con.execute("CREATE INDEX idx_lookup_sim_kw ON lookup_industry_keyword_sim(keyword)")
    con.execute("CREATE INDEX idx_lookup_sim_ind ON lookup_industry_keyword_sim(industry_name)")
    
    log.info(f"  [OK] 매스터 생성 완료: {len(df_sim_matrix):,} 건의 유사도 조합이 DuckDB에 캐싱되었습니다.")


# ═══════════════════════════════════════════════════
# Phase 3: 최종 차주별 리스크 스코어 가중평균 산출
# ═══════════════════════════════════════════════════

def phase3_risk_overlay_score(
    con: duckdb.DuckDBPyConnection,
    df_news_smoothed: pd.DataFrame,
    df_corp: pd.DataFrame
) -> pd.DataFrame:
    """
    [Phase 3] DuckDB SQL 엔진을 통한 가중 평균 기반 스코어 산출.

    수식: CORP_NEWS_RISK_INDEX = SUM(sentiment * weight) / SUM(weight)
    """
    log.info("")
    log.info("=" * 60)
    log.info("Phase 3: Weighted Average Scoring via DuckDB SQL")
    log.info("=" * 60)

    # df_news_smoothed, df_corp는 DuckDB가 메모리에서 바로 접근 가능
    # df_corp에 있는 V_BZNO, industry_name
    # df_news_smoothed에 있는 date, keyword, sentiment_score_ma90d
    # lookup_industry_keyword_sim에 있는 keyword, industry_name, similarity_weight
    
    log.info("  SQL LEFT JOIN 및 가중평균 연산 수행 중...")
    
    query = f"""
    SELECT 
        n.date,
        c.{CORP_KEY_COL},
        c.industry_name,
        -- 분모가 0이 되는 것을 방지 (NULLIF)
        COALESCE(
            SUM(n.sentiment_score_ma90d * l.similarity_weight) 
            / NULLIF(SUM(l.similarity_weight), 0), 
        0.0) AS CORP_NEWS_RISK_INDEX,
        COUNT(DISTINCT n.keyword) AS active_keyword_count
    FROM df_corp AS c
    LEFT JOIN lookup_industry_keyword_sim AS l
        ON c.industry_name = l.industry_name AND l.similarity_weight >= {SIMILARITY_THRESHOLD}
    LEFT JOIN df_news_smoothed AS n
        ON l.keyword = n.keyword
    GROUP BY n.date, c.{CORP_KEY_COL}, c.industry_name
    """
    
    df_result = con.execute(query).df()
    
    # ── 스코어 클리핑 (-1.0 ~ +1.0) ──
    df_result["CORP_NEWS_RISK_INDEX"] = df_result["CORP_NEWS_RISK_INDEX"].clip(
        lower=SCORE_CLIP_MIN,
        upper=SCORE_CLIP_MAX,
    )
    
    # 날짜 결측치 제거 (뉴스 없는 경우 방어)
    df_result = df_result.dropna(subset=["date"])
    df_result = df_result.sort_values([CORP_KEY_COL, "date"]).reset_index(drop=True)

    log.info(f"  [OK] Phase 3 Complete | result rows: {len(df_result):,}")
    log.info(f"     CORP_NEWS_RISK_INDEX stats:")
    log.info(f"     mean={df_result['CORP_NEWS_RISK_INDEX'].mean():.6f}  "
             f"std={df_result['CORP_NEWS_RISK_INDEX'].std():.6f}")

    return df_result


# ═══════════════════════════════════════════════════
# 메인 오케스트레이터
# ═══════════════════════════════════════════════════

def run_pipeline(
    news_csv_path: str | None = None,
    embedding_fn: Callable[[str], np.ndarray] | None = None,
    max_corp_sample: int | None = None,
) -> pd.DataFrame:
    log.info("=" * 60)
    log.info("  News Sentiment Risk Overlay Pipeline (DuckDB) START")
    log.info("=" * 60)
    log.info("")

    news_path = news_csv_path or NEWS_INPUT_FILE
    if not os.path.exists(news_path):
        from analysis.news_overlay.generate_sample_data import save_sample_news
        save_sample_news()

    df_news = pd.read_csv(news_path, encoding="utf-8-sig")
    df_smoothed = phase1_macro_smoothing(df_news)

    df_corp = load_corp_master()
    if max_corp_sample is not None and len(df_corp) > max_corp_sample:
        df_corp = df_corp.head(max_corp_sample)

    unique_keywords = df_smoothed["keyword"].unique().tolist()
    unique_industries = df_corp["industry_name"].unique().tolist()

    with duckdb.connect(DB_FILE) as con:
        # Phase 2
        ensure_lookup_industry_keyword_sim(con, unique_keywords, unique_industries, embedding_fn)
        
        # Phase 3
        df_result = phase3_risk_overlay_score(con, df_smoothed, df_corp)

    # Phase 4 (Save to DuckDB Mart)
    log.info("")
    log.info("=" * 60)
    log.info("Saving Results to Data Warehouse (MART)")
    log.info("=" * 60)
    
    # DB에 적재 (mart_news_overlay_index_daily)
    save_mart_to_db(df_result, "news_overlay_index_daily", replace=True)
    
    # 텍스트 파일로도 백업 저장 (요구사항 유지)
    df_out = df_result.copy()
    df_out["date"] = df_out["date"].dt.strftime("%Y-%m-%d")
    df_out.to_csv(OUTPUT_FILE, index=False, encoding="utf-8-sig")

    log.info("  [OK] Pipeline COMPLETED SUCCESSFULLY")
    return df_result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--news-csv", type=str, default=None)
    parser.add_argument("--max-corp", type=int, default=500)
    args = parser.parse_args()

    max_corp = args.max_corp if args.max_corp > 0 else None
    result_df = run_pipeline(news_csv_path=args.news_csv, max_corp_sample=max_corp)
    print(result_df.head())
