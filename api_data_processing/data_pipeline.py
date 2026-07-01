"""
Data Pipeline: raw → standardized → calendar_aligned → model_input

Transforms per-indicator raw CSVs through a multi-stage pipeline
to produce model-ready wide tables aligned to standard calendar frequencies.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Load State Manager  (증분 적재용)
# ---------------------------------------------------------------------------

class LoadStateManager:
    """Track last-loaded date per indicator for incremental collection."""

    def __init__(self, state_path: str | Path) -> None:
        self.state_path = Path(state_path)
        self.state: Dict[str, dict] = self._load()

    def _load(self) -> dict:
        if self.state_path.exists():
            with open(self.state_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.state_path, "w", encoding="utf-8") as f:
            json.dump(self.state, f, indent=2, ensure_ascii=False)

    def get_last_date(self, series_name: str) -> Optional[str]:
        entry = self.state.get(series_name)
        if entry:
            return entry.get("last_date")
        return None

    def update(self, series_name: str, last_date: str) -> None:
        self.state[series_name] = {
            "last_date": last_date,
            "last_updated": pd.Timestamp.now().isoformat(),
        }


# ---------------------------------------------------------------------------
# Metadata Generator
# ---------------------------------------------------------------------------

class MetadataManager:
    """Generate and maintain indicator metadata from config + actual data."""

    @staticmethod
    def generate(
        config_df: pd.DataFrame,
        standardized_dir: Path,
        output_path: Path,
    ) -> pd.DataFrame:
        records: List[dict] = []

        for _, row in config_df.iterrows():
            series = row.get("series_name", "").strip()
            if not series:
                continue

            record = {
                "series_name": series,
                "source": row.get("source", "").strip(),
                "frequency": row.get("frequency", "").strip(),
                "stat_code": row.get("stat_code", "").strip(),
                "item_code1": row.get("item_code1", "").strip(),
                "ticker": row.get("ticker", "").strip(),
                "field": row.get("field", "").strip(),
                "data_start": None,
                "data_end": None,
                "record_count": 0,
                "nan_count": 0,
            }

            std_path = standardized_dir / f"{series}.csv"
            if std_path.exists():
                try:
                    df = pd.read_csv(std_path, parse_dates=["date"])
                    if not df.empty:
                        value_cols = [c for c in df.columns if c != "date"]
                        record["data_start"] = df["date"].min().strftime("%Y-%m-%d")
                        record["data_end"] = df["date"].max().strftime("%Y-%m-%d")
                        record["record_count"] = len(df)
                        if value_cols:
                            record["nan_count"] = int(df[value_cols[0]].isna().sum())
                except Exception:
                    pass

            records.append(record)

        meta_df = pd.DataFrame(records)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        meta_df.to_csv(output_path, index=False, encoding="utf-8-sig")
        LOGGER.info("Metadata saved: %s (%d indicators)", output_path, len(meta_df))
        return meta_df


# ---------------------------------------------------------------------------
# Data Pipeline
# ---------------------------------------------------------------------------

class DataPipeline:
    """
    Multi-stage transformation pipeline.

    Stages
    ------
    1. standardize     – clean dates, numeric coercion, NaN marking
    2. calendar_align  – group by frequency, align to standard calendar
    3. build_model_input – resample all to target freq, merge wide table
    4. generate_metadata – produce indicator_metadata.csv
    """

    FREQ_MAP = {
        "D": {"name": "daily",     "resample": "B",  "order": 0},
        "M": {"name": "monthly",   "resample": "ME", "order": 1},
        "Q": {"name": "quarterly", "resample": "QE", "order": 2},
        "A": {"name": "annual",    "resample": "YE", "order": 3},
    }

    def __init__(
        self,
        raw_dir: str | Path,
        output_dir: str | Path,
        config_df: pd.DataFrame,
    ) -> None:
        self.raw_dir = Path(raw_dir)
        self.output_dir = Path(output_dir)
        self.config_df = config_df

        self.standardized_dir = self.output_dir / "standardized"
        self.aligned_dir = self.output_dir / "calendar_aligned"
        self.model_dir = self.output_dir / "model_input"
        self.metadata_dir = self.output_dir / "metadata"

        for d in (self.standardized_dir, self.aligned_dir,
                  self.model_dir, self.metadata_dir):
            d.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run_all(self, target_freq: str = "M") -> Path:
        """Execute all pipeline stages and return model-input path."""
        LOGGER.info("=== Pipeline Stage 1: standardize ===")
        self.standardize()

        LOGGER.info("=== Pipeline Stage 2: calendar_align ===")
        self.calendar_align()

        LOGGER.info("=== Pipeline Stage 3: model_input (target=%s) ===", target_freq)
        result_path = self.build_model_input(target_freq=target_freq)

        LOGGER.info("=== Pipeline Stage 4: metadata ===")
        MetadataManager.generate(
            self.config_df,
            self.standardized_dir,
            self.metadata_dir / "indicator_metadata.csv",
        )

        return result_path

    # ------------------------------------------------------------------
    # Stage 1 – Standardize
    # ------------------------------------------------------------------

    def standardize(self) -> None:
        """Clean dates, coerce values to float, mark missing as NaN."""
        for raw_file in sorted(self.raw_dir.glob("*.csv")):
            try:
                df = pd.read_csv(raw_file)
                if df.empty or "date" not in df.columns:
                    continue

                df["date"] = pd.to_datetime(df["date"], errors="coerce")
                df = df.dropna(subset=["date"])

                for col in (c for c in df.columns if c != "date"):
                    df[col] = pd.to_numeric(
                        df[col].astype(str).str.replace(",", "", regex=False),
                        errors="coerce",
                    )

                df = (
                    df.sort_values("date")
                    .drop_duplicates(subset=["date"], keep="last")
                    .reset_index(drop=True)
                )

                out = self.standardized_dir / raw_file.name
                df.to_csv(out, index=False, encoding="utf-8-sig")
                LOGGER.info("Standardized: %s (%d rows)", raw_file.stem, len(df))

            except Exception as exc:
                LOGGER.exception("Standardize failed: %s – %s", raw_file.name, exc)

    # ------------------------------------------------------------------
    # Stage 2 – Calendar Align
    # ------------------------------------------------------------------

    def calendar_align(self) -> None:
        """Group indicators by frequency and align to calendar dates."""
        freq_lookup = self._build_freq_lookup()

        # Group standardized frames by frequency
        freq_groups: Dict[str, List[pd.DataFrame]] = {}
        for std_file in sorted(self.standardized_dir.glob("*.csv")):
            series_name = std_file.stem
            freq = freq_lookup.get(series_name, "D")

            df = pd.read_csv(std_file, parse_dates=["date"])
            if df.empty:
                continue

            freq_groups.setdefault(freq, []).append(df)

        # Merge and align per frequency
        for freq, frames in freq_groups.items():
            info = self.FREQ_MAP.get(freq, self.FREQ_MAP["D"])

            merged = frames[0].copy()
            for frame in frames[1:]:
                merged = merged.merge(frame, on="date", how="outer")
            merged = merged.sort_values("date").reset_index(drop=True)

            # Align to standard calendar grid
            merged = merged.set_index("date")
            if freq == "D":
                bdays = pd.bdate_range(merged.index.min(), merged.index.max())
                merged = merged.reindex(bdays)
                merged.index.name = "date"
            else:
                merged = merged.resample(info["resample"]).last()

            merged = merged.reset_index()

            out = self.aligned_dir / f"{info['name']}.csv"
            merged.to_csv(out, index=False, encoding="utf-8-sig")
            ncols = len(merged.columns) - 1
            LOGGER.info(
                "Aligned [%s]: %d rows × %d series → %s",
                info["name"], len(merged), ncols, out.name,
            )

    # ------------------------------------------------------------------
    # Stage 3 – Model Input
    # ------------------------------------------------------------------

    def build_model_input(self, target_freq: str = "M") -> Path:
        """
        Resample all frequency tables to *target_freq* and merge.

        Rules
        -----
        - Higher freq → target : last observation per period
        - Same freq             : keep as-is
        - Lower freq → target  : forward-fill
        """
        target_info = self.FREQ_MAP.get(target_freq, self.FREQ_MAP["M"])
        target_order = target_info["order"]
        target_rule = target_info["resample"]

        all_frames: List[pd.DataFrame] = []

        for freq_key, info in self.FREQ_MAP.items():
            aligned_path = self.aligned_dir / f"{info['name']}.csv"
            if not aligned_path.exists():
                continue

            df = pd.read_csv(aligned_path, parse_dates=["date"])
            if df.empty:
                continue

            src_order = info["order"]

            if src_order < target_order:
                # Higher freq → downsample (last value per target period)
                df = df.set_index("date").resample(target_rule).last().reset_index()
                LOGGER.info("Downsampled %s → %s: %d rows",
                            info["name"], target_info["name"], len(df))

            elif src_order > target_order:
                # Lower freq → upsample + forward-fill
                df = df.set_index("date").resample(target_rule).ffill().reset_index()
                LOGGER.info("Upsampled %s → %s (ffill): %d rows",
                            info["name"], target_info["name"], len(df))

            all_frames.append(df)

        if not all_frames:
            LOGGER.warning("No data available for model input")
            result = pd.DataFrame(columns=["date"])
        else:
            result = all_frames[0].copy()
            for frame in all_frames[1:]:
                result = result.merge(frame, on="date", how="outer")
            result = result.sort_values("date").reset_index(drop=True)

        result["date"] = pd.to_datetime(result["date"]).dt.strftime("%Y-%m-%d")

        out_path = self.model_dir / f"model_input_{target_info['name']}.csv"
        result.to_csv(out_path, index=False, encoding="utf-8-sig")
        LOGGER.info(
            "Model input: %s (%d rows × %d cols)",
            out_path.name, len(result), len(result.columns),
        )
        return out_path

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_freq_lookup(self) -> Dict[str, str]:
        lookup: Dict[str, str] = {}
        for _, row in self.config_df.iterrows():
            series = row.get("series_name", "").strip()
            freq = row.get("frequency", "D").strip().upper()
            if series:
                lookup[series] = freq
        return lookup
