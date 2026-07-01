"""
news_overlay/config.py
======================
뉴스 리스크 오버레이 파이프라인 전역 설정 상수.
운영계/개발계 환경 분리 및 파라미터 일원 관리를 위해 독립 모듈로 격리.
"""

import os

# ──────────────────────────────────────────────
# 1. 경로 설정 (Path Configuration)
# ──────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 원천 기업 마스터 파일 (파이프 구분자)
CORP_MASTER_FILE = os.path.join(BASE_DIR, "input", "가상사업자_UPCHE_TOT_기업정보v.txt")

# 뉴스 데이터 입력 경로 (일별 CSV)
NEWS_INPUT_DIR = os.path.join(BASE_DIR, "analysis", "news_overlay", "input")
NEWS_INPUT_FILE = os.path.join(NEWS_INPUT_DIR, "daily_news_sentiment.csv")

# 결과물 저장 디렉토리 (물리적 격리 저장)
OUTPUT_DIR = os.path.join(BASE_DIR, "analysis", "news_overlay", "output")
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "news_overlay_index_daily.csv")

# ──────────────────────────────────────────────
# 2. Phase 1 - 이동평균 평활화 파라미터
# ──────────────────────────────────────────────
MA_WINDOW = 90          # 90영업일 이동평균 윈도우
MA_MIN_PERIODS = 1      # 윈도우 초기 최소 관측치 (NaN 방지)

# ──────────────────────────────────────────────
# 3. Phase 2 - 임베딩 / 유사도 파라미터
# ──────────────────────────────────────────────
EMBEDDING_DIM = 384     # 문장 임베딩 차원 수 (all-MiniLM-L6-v2 기준)
SIMILARITY_THRESHOLD = 0.25  # 유사도 하한 필터 (Cut-off)

# ──────────────────────────────────────────────
# 4. Phase 3 - 최종 스코어 파라미터
# ──────────────────────────────────────────────
SCORE_CLIP_MIN = -1.0   # 최종 리스크 지표 하한 (가장 위험)
SCORE_CLIP_MAX = 1.0    # 최종 리스크 지표 상한 (가장 우량)

# ──────────────────────────────────────────────
# 5. 기업 마스터 파일 파싱 설정
# ──────────────────────────────────────────────
CORP_FILE_SEPARATOR = "|"
CORP_FILE_HEADER_ROW = 0       # 영문 헤더 행 (V_BZNO, STD_INDS_CFC ...)
CORP_FILE_SKIP_ROWS = [1]      # 한글 설명 행 스킵
CORP_KEY_COL = "V_BZNO"        # 차주(기업) 고유키
CORP_INDUSTRY_COL = "STD_INDS_CFC"  # 표준산업분류 5자리 코드

# ──────────────────────────────────────────────
# 6. 로깅 설정
# ──────────────────────────────────────────────
LOG_DIR = os.path.join(OUTPUT_DIR, "logs")
LOG_FILE = os.path.join(LOG_DIR, "news_overlay_pipeline.log")
