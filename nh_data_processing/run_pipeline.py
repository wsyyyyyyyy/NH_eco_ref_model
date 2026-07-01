"""
NH Credit Data Processing – 실행 스크립트
=========================================
Usage:
    python -m nh_data_processing.run_pipeline
    python nh_data_processing/run_pipeline.py
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

# ── 프로젝트 루트를 sys.path에 추가 (직접 실행 대응) ──
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from nh_data_processing.pipeline import CreditDataPipeline

# ──────────────────────────────────────────────────────
# 설정
# ──────────────────────────────────────────────────────
DATA_DIR = _project_root / "input"
OUTPUT_DIR = _project_root / "nh_data_processing" / "output"


def setup_logging() -> None:
    log_dir = _project_root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    import pandas as pd
    log_file = log_dir / f"nh_pipeline_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-5s | %(name)s | %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def main() -> None:
    setup_logging()
    logger = logging.getLogger(__name__)

    logger.info("=" * 60)
    logger.info("NH Credit Scoring Data Processing Pipeline")
    logger.info("  DATA_DIR  : %s", DATA_DIR)
    logger.info("  OUTPUT_DIR: %s", OUTPUT_DIR)
    logger.info("=" * 60)

    pipeline = CreditDataPipeline(
        data_dir=DATA_DIR,
        output_dir=OUTPUT_DIR,
    )
    results = pipeline.run()

    # 결과 요약 리포트
    logger.info("")
    logger.info("=" * 60)
    logger.info("  Processing Summary")
    logger.info("=" * 60)
    logger.info("%-25s %10s %8s", "Dataset", "Rows", "Cols")
    logger.info("-" * 45)
    for key, df in results.items():
        logger.info("%-25s %10d %8d", key, len(df), len(df.columns))
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
