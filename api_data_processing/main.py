"""
======================================================================
거시 지표 수집 · 변환 진입점
======================================================================
사용:
    python -m api_data_processing.main --target-freq M
    python -m api_data_processing.main --target-freq D --skip-collect

impute_data.py 는 여기서 호출하지 않는다. 월간(M)/일별(D) 산출물이 모두
있어야 _vol_m 을 만들 수 있으므로, 두 파이프라인이 끝난 뒤 따로 실행한다.

    python api_data_processing/impute_data.py

배경: 이 프로젝트에는 거시 수집 스크립트가 없어 172개 거시 변수의 출처·수집일·
산출식이 재현 불가능했다. 그 결함을 메우는 것이 이 모듈의 목적이므로,
경로를 하드코딩하지 않고 실패를 조용히 넘기지 않는다.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from api_data_processing.data_collector import DataCollector, setup_logging
from api_data_processing.data_pipeline import DataPipeline, LoadStateManager

LOGGER = logging.getLogger(__name__)

_PKG_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG = _PKG_DIR / "config" / "indicators.csv"
DEFAULT_OUTPUT = _PKG_DIR / "output"

# start-date 는 2020-01-01 이다. 2021-01-01 이 아니다.
# impute_data 의 Phase 5 가 shift(12) warm-up 구간으로 상위 12행을 절단하므로,
# 2021-01 부터 수집하면 유효 구간이 2022-01 부터가 되어 패널(2021-01~2025-05)의
# 앞 12개월이 비게 된다.
DEFAULT_START = "2020-01-01"
DEFAULT_END = "2026-05-31"


def _parse_args(argv=None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        prog="python -m api_data_processing.main",
        description="ECOS / Yahoo / KOSIS 거시 지표 수집 및 변환",
    )
    ap.add_argument("--start-date", default=DEFAULT_START,
                    help=f"수집 시작일 (기본 {DEFAULT_START}. Phase 5 12행 절단 보정용)")
    ap.add_argument("--end-date", default=DEFAULT_END, help=f"수집 종료일 (기본 {DEFAULT_END})")
    ap.add_argument("--target-freq", default="M", choices=["D", "M", "Q", "A"],
                    help="변환 대상 주기 (기본 M)")
    ap.add_argument("--skip-collect", action="store_true",
                    help="수집을 생략하고 기존 raw 로 파이프라인만 실행")
    ap.add_argument("--config", default=str(DEFAULT_CONFIG), help="지표 설정 CSV")
    ap.add_argument("--output-dir", default=str(DEFAULT_OUTPUT), help="산출물 디렉터리")
    ap.add_argument("--incremental", action="store_true",
                    help="LoadStateManager 로 증분 수집 (기본 off)")
    ap.add_argument("--log-level", default="INFO",
                    choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return ap.parse_args(argv)


def _log_config_summary(config_df: pd.DataFrame) -> None:
    LOGGER.info("지표 설정 %d개 (enabled)", len(config_df))
    for col in ("source", "frequency"):
        if col in config_df.columns:
            counts = config_df[col].value_counts().to_dict()
            LOGGER.info("  %-9s %s", col, counts)


def _warn_missing_keys(config_df: pd.DataFrame, collector: DataCollector) -> None:
    """키가 없으면 시작 시점에 무엇이 전부 실패할지 알린다."""
    import os
    sources = config_df["source"].str.upper() if "source" in config_df.columns else pd.Series([])
    if not collector.config.ecos_api_key:
        n = int((sources == "ECOS").sum())
        LOGGER.warning("ECOS_API_KEY 없음 -> ECOS 지표 %d개가 전부 실패한다. "
                       ".env 를 설정할 것.", n)
    if not os.getenv("KOSIS_API_KEY", ""):
        n = int((sources == "PUBLIC").sum())
        LOGGER.warning("KOSIS_API_KEY 없음 -> PUBLIC 지표 %d개가 전부 실패한다. "
                       ".env 를 설정할 것.", n)


def _collected_names(frames: list) -> set:
    """수집 결과 프레임에서 지표명을 추출한다 (date 외 컬럼)."""
    names = set()
    for f in frames:
        if isinstance(f, pd.DataFrame) and not f.empty:
            names.update(c for c in f.columns if c != "date")
    return names


def _report_collection(config_df: pd.DataFrame, frames: list, raw_dir: Path) -> list:
    """수집 성공/실패를 지표 단위로 나열하고 실패 목록을 반환한다."""
    expected = list(config_df["series_name"])
    got = _collected_names(frames)
    # raw 파일이 남았으면 성공으로 본다 (증분 수집 시 frames 가 비어 있을 수 있다)
    on_disk = {p.stem for p in raw_dir.glob("*.csv")} if raw_dir.exists() else set()
    ok = [s for s in expected if s in got or s in on_disk]
    failed = [s for s in expected if s not in got and s not in on_disk]

    LOGGER.info("수집 성공 %d / %d", len(ok), len(expected))
    if failed:
        LOGGER.error("수집 실패 %d개:", len(failed))
        for s in failed:
            row = config_df.loc[config_df["series_name"] == s].iloc[0]
            LOGGER.error("    %-28s source=%-6s freq=%-2s stat_code=%s ticker=%s",
                         s, row.get("source", ""), row.get("frequency", ""),
                         row.get("stat_code", ""), row.get("ticker", ""))
    return failed


def _clip_to_range(path: Path, start_date: str, end_date: str) -> None:
    """산출물을 --start-date ~ --end-date 로 잘라낸다.

    수집기는 각 원천의 '가용한 최신 시점'까지 받아오므로 --end-date 를 넘긴
    구간이 붙는다. 그 마지막 달은 거래일이 며칠 없어 월내 변동성(_vol_m)을
    낼 수 없고, impute_data 의 NaN assert 를 깨뜨린다.
      실측: 2026-06 은 유효 거래일 1건 -> _vol_m 23개 컬럼 전부 NaN
            2026-05 는 18건 -> 정상
    CLI 로 받은 기간을 산출물이 지키도록 여기서 맞춘다.
    """
    if not path or not path.exists():
        return
    df = pd.read_csv(path)
    date_col = "date" if "date" in df.columns else df.columns[0]
    d = pd.to_datetime(df[date_col], errors="coerce")
    keep = (d >= pd.Timestamp(start_date)) & (d <= pd.Timestamp(end_date))
    if keep.all():
        return
    LOGGER.info("기간 절단: %d행 -> %d행 (%s ~ %s 밖 %d행 제거)",
                len(df), int(keep.sum()), start_date, end_date, int((~keep).sum()))
    for x in sorted(set(d[~keep].dt.strftime("%Y-%m"))):
        LOGGER.info("    제거: %s", x)
    df.loc[keep].to_csv(path, index=False)


def _log_output_summary(path: Path) -> None:
    if not path or not Path(path).exists():
        LOGGER.error("산출물이 생성되지 않았다: %s", path)
        return
    df = pd.read_csv(path)
    date_col = "date" if "date" in df.columns else df.columns[0]
    d = pd.to_datetime(df[date_col], errors="coerce")
    LOGGER.info("산출물: %s", path)
    LOGGER.info("  shape = %d행 x %d컬럼", df.shape[0], df.shape[1])
    LOGGER.info("  기간  = %s ~ %s", d.min(), d.max())


def main(argv=None) -> int:
    args = _parse_args(argv)
    setup_logging(args.log_level)

    config_path = Path(args.config)
    output_dir = Path(args.output_dir)
    raw_dir = output_dir / "raw"
    output_dir.mkdir(parents=True, exist_ok=True)

    LOGGER.info("=" * 70)
    LOGGER.info("거시 지표 수집/변환  target_freq=%s  %s ~ %s",
                args.target_freq, args.start_date, args.end_date)
    LOGGER.info("  config     : %s", config_path)
    LOGGER.info("  output-dir : %s", output_dir)
    LOGGER.info("=" * 70)

    collector = DataCollector()
    config_df = collector.load_indicator_config(config_path)
    _log_config_summary(config_df)
    _warn_missing_keys(config_df, collector)

    failed: list = []
    if args.skip_collect:
        LOGGER.info("--skip-collect: 수집 생략, 기존 raw 사용 (%s)", raw_dir)
        if not raw_dir.exists() or not any(raw_dir.glob("*.csv")):
            LOGGER.error("raw 디렉터리가 비어 있다. --skip-collect 없이 먼저 수집할 것.")
            return 1
    else:
        state = LoadStateManager(output_dir / "load_state.json") if args.incremental else None
        frames = collector.collect_from_config(
            config_df, args.start_date, args.end_date,
            raw_dir=raw_dir, state_manager=state,
        )
        if state is not None:
            state.save()
        failed = _report_collection(config_df, frames, raw_dir)

    pipeline = DataPipeline(raw_dir=raw_dir, output_dir=output_dir, config_df=config_df)
    result_path = pipeline.run_all(target_freq=args.target_freq)
    _clip_to_range(Path(result_path) if result_path else None,
                   args.start_date, args.end_date)
    _log_output_summary(Path(result_path) if result_path else None)

    n_raw = len(list(raw_dir.glob("*.csv"))) if raw_dir.exists() else 0
    LOGGER.info("raw 파일 %d개 (%s)", n_raw, raw_dir)

    if failed:
        LOGGER.error("=" * 70)
        LOGGER.error("실패 지표 %d개로 종료한다 (exit 1): %s", len(failed), failed)
        LOGGER.error("=" * 70)
        return 1

    LOGGER.info("완료. impute_data 는 따로 실행할 것: "
                "python api_data_processing/impute_data.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
