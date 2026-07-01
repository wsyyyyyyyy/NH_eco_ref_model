from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
import requests
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .public_data_collector import PublicDataCollector

LOGGER = logging.getLogger(__name__)


@dataclass
class CollectorConfig:
    ecos_api_key: str
    request_timeout: int = 30
    sleep_seconds: float = 0.35
    max_retries: int = 5
    backoff_factor: float = 1.0
    page_size: int = 1000


class DataCollector:
    """
    Collect macroeconomic time-series data from ECOS and Yahoo Finance.

    Expected config CSV columns:
    - source: ECOS or YAHOO
    - series_name: final output column name
    - enabled: Y/N or 1/0
    - frequency: A/Q/M/W/D
    - stat_code: ECOS only
    - item_code1 ~ item_code4: ECOS only (optional)
    - ticker: Yahoo only
    - field: Yahoo only (default=Close)
    """

    ECOS_BASE_URL = "https://ecos.bok.or.kr/api"
    YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"

    def __init__(self, config: Optional[CollectorConfig] = None) -> None:
        load_dotenv()
        self.config = config or CollectorConfig(
            ecos_api_key=os.getenv("ECOS_API_KEY", ""),
            request_timeout=int(os.getenv("REQUEST_TIMEOUT", "30")),
            sleep_seconds=float(os.getenv("REQUEST_SLEEP", "0.35")),
            max_retries=int(os.getenv("MAX_RETRIES", "5")),
            backoff_factor=float(os.getenv("BACKOFF_FACTOR", "1.0")),
            page_size=int(os.getenv("ECOS_PAGE_SIZE", "1000")),
        )
        if not self.config.ecos_api_key:
            LOGGER.warning("ECOS_API_KEY is empty. ECOS collection will fail until .env is configured.")
        self.session = self._build_session()

    def _build_session(self) -> requests.Session:
        retry = Retry(
            total=self.config.max_retries,
            connect=self.config.max_retries,
            read=self.config.max_retries,
            backoff_factor=self.config.backoff_factor,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=frozenset(["GET"]),
            raise_on_status=False,
            respect_retry_after_header=True,
        )
        adapter = HTTPAdapter(max_retries=retry)
        session = requests.Session()
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        session.headers.update({"User-Agent": "raw-macro-data-collector/1.0"})
        return session

    @staticmethod
    def _normalize_frequency(freq: str) -> str:
        freq = str(freq).upper().strip()
        alias = {
            "YEAR": "A",
            "ANNUAL": "A",
            "Y": "A",
            "QUARTER": "Q",
            "QUARTERLY": "Q",
            "MONTH": "M",
            "MONTHLY": "M",
            "WEEK": "W",
            "WEEKLY": "W",
            "DAY": "D",
            "DAILY": "D",
        }
        return alias.get(freq, freq)

    @staticmethod
    def _format_date_value(raw_time: str, freq: str) -> pd.Timestamp:
        freq = DataCollector._normalize_frequency(freq)
        raw = str(raw_time)

        if freq == "A":
            return pd.to_datetime(raw, format="%Y")
        if freq == "Q":
            year, quarter = raw[:4], raw[-1]
            month_map = {"1": "03", "2": "06", "3": "09", "4": "12"}
            return pd.to_datetime(f"{year}{month_map[quarter]}01", format="%Y%m%d")
        if freq == "M":
            return pd.to_datetime(raw + "01", format="%Y%m%d")
        if freq == "W":
            # ISO week fallback: convert to week start date (Monday)
            if len(raw) == 6 and raw[:4].isdigit() and raw[4:].isdigit():
                return pd.to_datetime(raw + "-1", format="%G%V-%u")
            return pd.to_datetime(raw)
        if freq == "D":
            return pd.to_datetime(raw, format="%Y%m%d")

        return pd.to_datetime(raw)

    @staticmethod
    def _date_for_request(value: str, freq: str) -> str:
        ts = pd.to_datetime(value)
        freq = DataCollector._normalize_frequency(freq)

        if freq == "A":
            return ts.strftime("%Y")
        if freq == "Q":
            quarter = (ts.month - 1) // 3 + 1
            return f"{ts.year}Q{quarter}"
        if freq == "M":
            return ts.strftime("%Y%m")
        if freq == "W":
            return ts.strftime("%Y%m%d")
        if freq == "D":
            return ts.strftime("%Y%m%d")

        return ts.strftime("%Y%m%d")

    @staticmethod
    def _to_float(series: pd.Series) -> pd.Series:
        return pd.to_numeric(
            series.astype(str).str.replace(",", "", regex=False),
            errors="coerce"
        ).astype(float)

    def _request_json(self, url: str, params: Optional[Dict] = None) -> Dict:
        last_error = None

        for attempt in range(1, self.config.max_retries + 1):
            try:
                response = self.session.get(
                    url,
                    params=params,
                    timeout=self.config.request_timeout,
                )

                if response.status_code == 429:
                    wait_seconds = min(2 ** attempt, 30)
                    LOGGER.warning("Rate limit hit. Sleeping %.1f seconds before retry...", wait_seconds)
                    time.sleep(wait_seconds)
                    continue

                response.raise_for_status()
                data = response.json()
                self._raise_if_api_error(data)
                return data

            except (requests.RequestException, ValueError) as exc:
                last_error = exc
                wait_seconds = min((2 ** (attempt - 1)) * self.config.backoff_factor, 30)
                LOGGER.warning(
                    "Request failed (attempt=%s/%s): %s",
                    attempt,
                    self.config.max_retries,
                    exc,
                )
                time.sleep(wait_seconds)

        raise RuntimeError(f"API request failed after retries: {url}") from last_error

    @staticmethod
    def _raise_if_api_error(payload: Dict) -> None:
        for value in payload.values():
            if isinstance(value, dict) and "CODE" in value:
                code = str(value.get("CODE", ""))
                message = value.get("MESSAGE", "Unknown API error")
                if code not in {"INFO-200"} and (code.startswith("INFO-") or code.startswith("ERROR-")):
                    raise RuntimeError(f"API error: {code} - {message}")

    def fetch_ecos_data(
        self,
        stat_code: str,
        item_code: Optional[str],
        start_date: str,
        end_date: str,
        frequency: str = "M",
        item_code2: Optional[str] = None,
        item_code3: Optional[str] = None,
        item_code4: Optional[str] = None,
        series_name: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        ECOS StatisticSearch 호출 후 표준화된 DataFrame 반환.
        """
        freq = self._normalize_frequency(frequency)
        item_code1 = item_code or ""
        codes = [item_code1 or "", item_code2 or "", item_code3 or "", item_code4 or ""]
        start = self._date_for_request(start_date, freq)
        end = self._date_for_request(end_date, freq)

        rows: List[Dict] = []
        start_row = 1

        while True:
            end_row = start_row + self.config.page_size - 1

            path = "/".join(
                [
                    "StatisticSearch",
                    self.config.ecos_api_key,
                    "json",
                    "kr",
                    str(start_row),
                    str(end_row),
                    stat_code,
                    freq,
                    start,
                    end,
                    *codes,
                ]
            )
            url = f"{self.ECOS_BASE_URL}/{path}"
            payload = self._request_json(url)

            key = next((k for k in payload.keys() if k.lower() == "statisticsearch"), None)
            if not key:
                break

            data_block = payload.get(key, {})
            current_rows = data_block.get("row", []) or []
            rows.extend(current_rows)

            total_count = int(data_block.get("list_total_count", len(rows)))
            if not current_rows or len(rows) >= total_count:
                break

            start_row = end_row + 1
            time.sleep(self.config.sleep_seconds)

        if not rows:
            LOGGER.info("No ECOS data found: stat_code=%s, item_code=%s", stat_code, item_code1)
            return pd.DataFrame(columns=["date", series_name or stat_code])

        df = pd.DataFrame(rows)
        value_col = series_name or f"{stat_code}_{item_code1 or 'ALL'}"

        result = pd.DataFrame(
            {
                "date": df["TIME"].map(lambda x: self._format_date_value(x, freq)),
                value_col: self._to_float(df["DATA_VALUE"]),
            }
        )

        result = (
            result.sort_values("date")
            .drop_duplicates(subset=["date"], keep="last")
            .reset_index(drop=True)
        )
        return result

    def fetch_yahoo_data(
        self,
        ticker: str,
        start_date: str,
        end_date: str,
        frequency: str = "D",
        series_name: Optional[str] = None,
        field: str = "Close",
    ) -> pd.DataFrame:
        """
        Yahoo Finance chart endpoint 호출 (requests 기반)
        """
        start_ts = int(pd.Timestamp(start_date).timestamp())
        end_ts = int((pd.Timestamp(end_date) + pd.Timedelta(days=1)).timestamp())

        freq = self._normalize_frequency(frequency)
        interval_map = {"D": "1d", "W": "1wk", "M": "1mo"}
        interval = interval_map.get(freq, "1d")

        url = self.YAHOO_CHART_URL.format(ticker=ticker)
        params = {
            "period1": start_ts,
            "period2": end_ts,
            "interval": interval,
            "includeAdjustedClose": "true",
        }

        payload = self._request_json(url, params=params)

        chart = payload.get("chart", {})
        error = chart.get("error")
        if error:
            raise RuntimeError(f"Yahoo Finance error for {ticker}: {error}")

        result = chart.get("result", [])
        if not result:
            LOGGER.info("No Yahoo data found: ticker=%s", ticker)
            return pd.DataFrame(columns=["date", series_name or ticker])

        node = result[0]
        timestamps = node.get("timestamp", []) or []
        quote = ((node.get("indicators") or {}).get("quote") or [{}])[0]

        field_map = {
            "OPEN": "open",
            "HIGH": "high",
            "LOW": "low",
            "CLOSE": "close",
            "VOLUME": "volume",
        }
        selected_field = field_map.get(field.upper(), "close")
        values = quote.get(selected_field, []) or []
        value_col = series_name or ticker

        result_df = pd.DataFrame(
            {
                "date": pd.to_datetime(pd.Series(timestamps), unit="s").dt.normalize(),
                value_col: pd.to_numeric(pd.Series(values), errors="coerce").astype(float),
            }
        )

        result_df = (
            result_df.sort_values("date")
            .drop_duplicates(subset=["date"], keep="last")
            .reset_index(drop=True)
        )
        return result_df

    def load_indicator_config(self, config_path: str | Path) -> pd.DataFrame:
        path = Path(config_path)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")

        df = pd.read_csv(path, dtype=str, comment="#").fillna("")

        if "enabled" not in df.columns:
            df["enabled"] = "Y"

        enabled_mask = df["enabled"].astype(str).str.upper().isin(["Y", "YES", "1", "TRUE"])
        df = df.loc[enabled_mask].reset_index(drop=True)

        if df.empty:
            raise ValueError("No enabled indicators found in config file.")

        return df

    def standardize_frame(self, df: pd.DataFrame, value_columns: Optional[List[str]] = None) -> pd.DataFrame:
        out = df.copy()
        out["date"] = pd.to_datetime(out["date"], errors="coerce").dt.normalize()
        out = out.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)

        if value_columns is None:
            value_columns = [col for col in out.columns if col != "date"]

        for col in value_columns:
            out[col] = self._to_float(out[col])

        return out

    def collect_from_config(
        self,
        config_df: pd.DataFrame,
        start_date: str,
        end_date: str,
        raw_dir: Optional[str | Path] = None,
        state_manager=None,
    ) -> List[pd.DataFrame]:
        """
        Collect indicators defined in *config_df*.

        Parameters
        ----------
        raw_dir : path, optional
            If given, each indicator is saved as an individual CSV under
            this directory (``raw_dir/{series_name}.csv``).
        state_manager : LoadStateManager, optional
            If given, enables **incremental load** – only data newer than
            the last-loaded date is fetched and appended.
        """
        collected_frames: List[pd.DataFrame] = []
        save_individually = raw_dir is not None
        if save_individually:
            raw_path = Path(raw_dir)
            raw_path.mkdir(parents=True, exist_ok=True)

        public_collector = PublicDataCollector()

        for idx, row in config_df.iterrows():
            source = row.get("source", "").strip().upper()
            series_name = row.get("series_name", f"series_{idx + 1}").strip()
            frequency = row.get("frequency", "D")

            # --- Incremental: determine effective start date ---------------
            effective_start = start_date
            if state_manager is not None:
                last = state_manager.get_last_date(series_name)
                if last is not None:
                    effective_start = last
                    LOGGER.info(
                        "Incremental: %s – resuming from %s",
                        series_name, effective_start,
                    )

            try:
                LOGGER.info(
                    "Collecting (%s/%s): %s / %s  [%s → %s]",
                    idx + 1, len(config_df), source, series_name,
                    effective_start, end_date,
                )

                if source == "ECOS":
                    df = self.fetch_ecos_data(
                        stat_code=row.get("stat_code", "").strip(),
                        item_code=row.get("item_code1", "").strip(),
                        item_code2=row.get("item_code2", "").strip() or None,
                        item_code3=row.get("item_code3", "").strip() or None,
                        item_code4=row.get("item_code4", "").strip() or None,
                        start_date=effective_start,
                        end_date=end_date,
                        frequency=frequency,
                        series_name=series_name,
                    )

                elif source == "YAHOO":
                    df = self.fetch_yahoo_data(
                        ticker=row.get("ticker", "").strip(),
                        start_date=effective_start,
                        end_date=end_date,
                        frequency=frequency,
                        series_name=series_name,
                        field=row.get("field", "Close").strip(),
                    )

                elif source == "PUBLIC":
                    df = public_collector.collect(
                        indicator_name=series_name,
                        start_date=effective_start,
                        end_date=end_date,
                    )

                else:
                    raise ValueError(f"Unsupported source: {source}")

                df = self.standardize_frame(
                    df, value_columns=[c for c in df.columns if c != "date"],
                )

                # --- Save individual raw CSV & merge with existing ---------
                if save_individually:
                    df = self._save_raw_indicator(df, series_name, raw_path)

                # --- Update load state -------------------------------------
                if state_manager is not None and not df.empty:
                    last_date = df["date"].max()
                    state_manager.update(
                        series_name,
                        last_date.strftime("%Y-%m-%d")
                        if hasattr(last_date, "strftime")
                        else str(last_date),
                    )

                collected_frames.append(df)

            except Exception as exc:
                LOGGER.exception(
                    "Failed to collect indicator: %s (%s)", series_name, exc,
                )

            finally:
                time.sleep(self.config.sleep_seconds)

        # Persist load state at the end of the run
        if state_manager is not None:
            state_manager.save()

        return collected_frames

    # ------------------------------------------------------------------
    # Raw indicator persistence
    # ------------------------------------------------------------------

    @staticmethod
    def _save_raw_indicator(
        new_df: pd.DataFrame, series_name: str, raw_dir: Path,
    ) -> pd.DataFrame:
        """
        Append-or-create a per-indicator CSV under *raw_dir*.

        If the file already exists the new rows are merged (dedup by date,
        keeping the latest value).  Returns the full combined DataFrame.
        """
        file_path = raw_dir / f"{series_name}.csv"

        if file_path.exists():
            existing = pd.read_csv(file_path, parse_dates=["date"])
            combined = pd.concat([existing, new_df], ignore_index=True)
            combined = (
                combined.sort_values("date")
                .drop_duplicates(subset=["date"], keep="last")
                .reset_index(drop=True)
            )
        else:
            combined = new_df.copy()

        combined.to_csv(file_path, index=False, encoding="utf-8-sig")
        LOGGER.info("Saved raw indicator: %s (%d rows)", file_path.name, len(combined))
        return combined

    # ------------------------------------------------------------------
    # Legacy helpers (backward compatibility)
    # ------------------------------------------------------------------

    def merge_to_wide(self, frames: List[pd.DataFrame]) -> pd.DataFrame:
        """Merge list of single-column frames into a wide DataFrame."""
        if not frames:
            return pd.DataFrame(columns=["date"])

        merged = frames[0].copy()
        for frame in frames[1:]:
            merged = merged.merge(frame, on="date", how="outer")

        merged = merged.sort_values("date").reset_index(drop=True)
        merged["date"] = merged["date"].dt.strftime("%Y-%m-%d")
        return merged

    def save_raw_data(
        self, df: pd.DataFrame, output_dir: str | Path = "./output",
    ) -> Path:
        """Save a wide DataFrame to a single CSV (legacy)."""
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        file_name = f"raw_macro_data_{pd.Timestamp.now().strftime('%Y%m%d')}.csv"
        file_path = output_path / file_name

        df.to_csv(file_path, index=False, encoding="utf-8-sig")
        LOGGER.info("Saved raw data: %s", file_path)
        return file_path


def setup_logging(log_dir: str | Path = "./logs") -> None:
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    log_file = Path(log_dir) / f"collector_{pd.Timestamp.now().strftime('%Y%m%d')}.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
