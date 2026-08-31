"""
======================================================================
EDA Pipeline — 메인 실행 스크립트
======================================================================
전체 파이프라인을 순서대로 실행합니다.

  Step 1: Raw TXT → 전처리된 Dict[str, DataFrame]
  Step 2: Dict → 월별 패널 데이터셋 (nh_panel_full.csv)
  Step 3: 패널 → EDA 분석 + HTML 리포트

실행 방법:
  python eda_pipeline/run.py
  python eda_pipeline/run.py --data-dir input --output-dir eda_pipeline/output
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from eda_pipeline.step1_load import RawLoader
from eda_pipeline.step2_integrate import PanelBuilder
from eda_pipeline.step3_eda import EDAReporter


# ── 로거 설정 ────────────────────────────────────────────────────────
def _setup_logger(log_dir: Path) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    from datetime import datetime
    log_file = log_dir / f"eda_pipeline_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-5s | %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_file, encoding="utf-8"),
        ],
    )
    return logging.getLogger("eda_pipeline")


# ── 메인 ─────────────────────────────────────────────────────────────
def main(data_dir: str, output_dir: str) -> None:
    data_path   = Path(data_dir)
    output_path = Path(output_dir)
    log_path    = _PROJECT_ROOT / "logs"

    log = _setup_logger(log_path)

    log.info("=" * 70)
    log.info("  NH 차주 데이터 EDA 파이프라인 시작")
    log.info("  입력: %s", data_path.resolve())
    log.info("  출력: %s", output_path.resolve())
    log.info("=" * 70)

    total_start = time.time()

    # ──────────────────────────────────────────────────────────────────
    # Step 1: Raw 데이터 로드 & 전처리
    # ──────────────────────────────────────────────────────────────────
    log.info("")
    log.info("[ STEP 1 ] Raw 데이터 로드 & 기초 전처리")
    t0 = time.time()

    loader = RawLoader(data_dir=data_path)
    frames = loader.load_all()

    log.info("  소요 시간: %.1fs", time.time() - t0)
    log.info("  로드된 테이블: %s", list(frames.keys()))

    # 로드 결과 요약
    for key, df in frames.items():
        log.info("    %-10s: %d rows × %d cols", key, len(df), len(df.columns))

    # ──────────────────────────────────────────────────────────────────
    # Step 2: 월별 패널 통합
    # ──────────────────────────────────────────────────────────────────
    log.info("")
    log.info("[ STEP 2 ] 월별 패널 데이터 통합")
    t0 = time.time()

    builder = PanelBuilder(frames=frames, output_dir=output_path)
    panel = builder.build()

    log.info("  소요 시간: %.1fs", time.time() - t0)
    log.info("  패널 Shape: %s", panel.shape)

    # 분리 통계
    if "SPLIT" in panel.columns:
        for split in ["TRAIN", "VALID"]:
            sub = panel[panel["SPLIT"] == split]
            default_rate = sub["IS_BUDO_IN_SPINE_YN"].mean() * 100 if "IS_BUDO_IN_SPINE_YN" in sub.columns else 0
            log.info("    %s: %d rows, 부도율: %.4f%%", split, len(sub), default_rate)

    # ──────────────────────────────────────────────────────────────────
    # Step 3: EDA
    # ──────────────────────────────────────────────────────────────────
    log.info("")
    log.info("[ STEP 3 ] EDA 분석 & HTML 리포트 생성")
    t0 = time.time()

    reporter = EDAReporter(panel=panel, output_dir=output_path)
    reporter.run()

    log.info("  소요 시간: %.1fs", time.time() - t0)

    # ──────────────────────────────────────────────────────────────────
    # 완료 요약
    # ──────────────────────────────────────────────────────────────────
    total_elapsed = time.time() - total_start
    log.info("")
    log.info("=" * 70)
    log.info("  [DONE] 전체 파이프라인 완료 — 총 소요: %.1fs", total_elapsed)
    log.info("")
    log.info("  📁 출력 파일 목록:")
    from eda_pipeline import config as _cfg
    _tr, _va = _cfg.split_paths()
    log.info("    %s  — 전체 패널 (TRAIN + VALID, spine_mode=%s)",
             _cfg.panel_path().name, _cfg.SPINE_MODE)
    log.info("    %s — 학습용 (2021~2023)", _tr.name)
    log.info("    %s — 검증용 (2024~2025-05)", _va.name)
    log.info("    eda_report.html    — EDA 분석 리포트 (브라우저에서 열기)")
    log.info("    eda_stats_summary.csv — 기술통계 요약")
    log.info("    eda_plots/         — 개별 분석 이미지")
    log.info("=" * 70)

    # 브라우저에서 HTML 열기 시도
    try:
        import webbrowser
        report_path = (output_path / "eda_report.html").resolve()
        webbrowser.open(report_path.as_uri())
        log.info("  ✅ 브라우저에서 EDA 리포트를 열었습니다.")
    except Exception:
        log.info("  (브라우저 자동 열기 실패 — 수동으로 eda_report.html을 여세요)")


# ── CLI ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="NH 차주 데이터 EDA 파이프라인")
    parser.add_argument("--data-dir",   default="input",               help="원천 TXT 파일 폴더")
    parser.add_argument("--output-dir", default="eda_pipeline/output",  help="출력 폴더")
    args = parser.parse_args()

    main(data_dir=args.data_dir, output_dir=args.output_dir)
