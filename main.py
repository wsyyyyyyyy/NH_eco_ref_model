from __future__ import annotations

import argparse
from pathlib import Path

from api_data_processing.data_collector import DataCollector, setup_logging
from api_data_processing.data_pipeline import DataPipeline, LoadStateManager


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect macro data and run transformation pipeline",
    )
    parser.add_argument(
        "--config", default="config/indicators.csv",
        help="Path to indicator config CSV",
    )
    parser.add_argument(
        "--start-date", required=True,
        help="Collection start date (e.g. 2010-01-01)",
    )
    parser.add_argument(
        "--end-date", required=True,
        help="Collection end date (e.g. 2025-12-31)",
    )
    parser.add_argument(
        "--output-dir", default="api_data_processing/output",
        help="Root output directory",
    )
    parser.add_argument(
        "--target-freq", default="M", choices=["D", "M", "Q", "A"],
        help="Target frequency for model_input (default: M=monthly)",
    )
    parser.add_argument(
        "--full-reload", action="store_true",
        help="Ignore load state and re-collect entire period",
    )
    parser.add_argument(
        "--skip-collect", action="store_true",
        help="Skip collection; only run pipeline on existing raw data",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    setup_logging()

    output_dir = Path(args.output_dir)
    raw_dir = output_dir / "raw"
    state_path = output_dir / "metadata" / "load_state.json"

    collector = DataCollector()
    config_df = collector.load_indicator_config(args.config)

    # ------------------------------------------------------------------
    # Stage 0: Collect raw data (incremental by default)
    # ------------------------------------------------------------------
    if not args.skip_collect:
        state_manager = LoadStateManager(state_path)
        if args.full_reload:
            state_manager.state.clear()  # reset → fetch full range

        collector.collect_from_config(
            config_df=config_df,
            start_date=args.start_date,
            end_date=args.end_date,
            raw_dir=raw_dir,
            state_manager=state_manager,
        )

    # ------------------------------------------------------------------
    # Stages 1-4: Pipeline  (raw → standardized → aligned → model_input)
    # ------------------------------------------------------------------
    pipeline = DataPipeline(
        raw_dir=raw_dir,
        output_dir=output_dir,
        config_df=config_df,
    )
    result_path = pipeline.run_all(target_freq=args.target_freq)

    print(f"\n[DONE] Model input → {result_path}")
    print(f"       Raw data   → {raw_dir}")
    print(f"       Metadata   → {output_dir / 'metadata'}")


if __name__ == "__main__":
    main()
