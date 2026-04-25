"""Open-Meteo customer-archive ingestion (Tier 2).

Use when: rebuilding the daily weather feature table for Quad Cities from
Open-Meteo's paid ERA5 archive. Run via `just features` (chains all Tier 2
ingest scripts) or directly via `uv run python -m pipeline.ingest_weather`.
CLI flag `--refresh` re-fetches every year, ignoring the on-disk cache.

Output:
- data/raw/weather/{year}.parquet           (cached per-year hourly)
- data/interim/weather_quad_cities.parquet  (daily aggregated, UTC)
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from schemas import (  # noqa: E402
    OPENMETEO_ARCHIVE_URL,
    QC1_LAT,
    QC1_LON,
    WEATHER_ARCHIVE_END_LAG_DAYS,
    WEATHER_HOURLY_VARS,
)

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = REPO_ROOT / "data" / "raw" / "weather"
INTERIM_DIR = REPO_ROOT / "data" / "interim"

# Match the NRC label window so weather features cover every label day.
WEATHER_START_YEAR = 2005


def _fetch_year(
    year: int, lat: float, lon: float, apikey: str, refresh: bool
) -> pd.DataFrame:
    """Pull (or reuse cached) hourly weather for one year, return as DataFrame."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    cache = RAW_DIR / f"{year}.parquet"

    today = datetime.now(timezone.utc).date()
    end_cap = today - timedelta(days=WEATHER_ARCHIVE_END_LAG_DAYS)
    is_complete_year = date(year, 12, 31) <= end_cap

    use_cache = cache.exists() and not refresh and is_complete_year
    if use_cache:
        log.info("weather %d: cache hit", year)
        return pd.read_parquet(cache)

    start = date(year, 1, 1)
    end = min(date(year, 12, 31), end_cap)
    if end < start:
        log.info("weather %d: nothing within ERA5 latency window yet", year)
        return pd.DataFrame()

    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "hourly": ",".join(WEATHER_HOURLY_VARS),
        "timezone": "UTC",
        "apikey": apikey,
    }
    log.info(
        "weather %d: fetching %s to %s (%d hourly vars)",
        year,
        start,
        end,
        len(WEATHER_HOURLY_VARS),
    )
    resp = requests.get(OPENMETEO_ARCHIVE_URL, params=params, timeout=120)
    resp.raise_for_status()
    payload = resp.json()
    if "hourly" not in payload:
        raise RuntimeError(f"weather {year}: unexpected payload (keys={list(payload)})")

    hourly = payload["hourly"]
    df = pd.DataFrame(hourly)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df = df.sort_values("time").reset_index(drop=True)
    df.to_parquet(cache, index=False)
    log.info("weather %d: cached %d hourly rows", year, len(df))
    return df


def _aggregate_daily(hourly: pd.DataFrame) -> pd.DataFrame:
    """Collapse hourly observations to UTC calendar-day aggregates."""
    if hourly.empty:
        return hourly
    df = hourly.copy()
    df["date"] = df["time"].dt.tz_convert("UTC").dt.normalize().dt.tz_localize(None)

    # Per Project_Plan.md: min/mean/max for temp, mean for the rest, sum precip.
    aggs = {
        "temperature_2m": ["min", "mean", "max"],
        "dew_point_2m": "mean",
        "relative_humidity_2m": "mean",
        "wind_speed_10m": "mean",
        "shortwave_radiation": "mean",
        "precipitation": "sum",
        "surface_pressure": "mean",
        "cloud_cover": "mean",
    }
    grouped = df.groupby("date").agg(aggs)
    grouped.columns = [
        f"{col}_{stat}" if isinstance(stat, str) else col
        for col, stat in grouped.columns
    ]
    # Tidy the multi-stat temperature columns to match the rest of the schema.
    rename = {
        "temperature_2m_min": "air_temp_c_min",
        "temperature_2m_mean": "air_temp_c_mean",
        "temperature_2m_max": "air_temp_c_max",
        "dew_point_2m_mean": "dew_point_c_mean",
        "relative_humidity_2m_mean": "rh_pct_mean",
        "wind_speed_10m_mean": "wind_ms_mean",
        "shortwave_radiation_mean": "shortwave_w_m2_mean",
        "precipitation_sum": "precip_mm_sum",
        "surface_pressure_mean": "pressure_hpa_mean",
        "cloud_cover_mean": "cloud_pct_mean",
    }
    grouped = grouped.rename(columns=rename).reset_index()
    return grouped


def _load_apikey() -> str:
    """Read the Open-Meteo paid-plan API key. Accepts the canonical name from
    .env.example (`OPENMETEO_API_KEY`) and the underscore variant
    (`OPEN_METEO_API_KEY`) some local .env files use."""
    load_dotenv(REPO_ROOT / ".env")
    for name in ("OPENMETEO_API_KEY", "OPEN_METEO_API_KEY"):
        key = os.environ.get(name, "").strip()
        if key:
            return key
    raise RuntimeError(
        "Open-Meteo API key missing: set OPENMETEO_API_KEY in .env"
    )


def run(refresh: bool = False) -> None:
    INTERIM_DIR.mkdir(parents=True, exist_ok=True)
    apikey = _load_apikey()
    current_year = datetime.now(timezone.utc).year

    frames: list[pd.DataFrame] = []
    for year in range(WEATHER_START_YEAR, current_year + 1):
        df = _fetch_year(year, QC1_LAT, QC1_LON, apikey, refresh=refresh)
        if not df.empty:
            frames.append(df)

    if not frames:
        raise RuntimeError("no weather years successfully ingested")

    hourly = pd.concat(frames, ignore_index=True)
    hourly = hourly.drop_duplicates(subset=["time"]).sort_values("time")

    daily = _aggregate_daily(hourly)
    out = INTERIM_DIR / "weather_quad_cities.parquet"
    daily.to_parquet(out, index=False)
    log.info(
        "wrote %s: %d daily rows, %s -> %s",
        out,
        len(daily),
        daily["date"].min().date(),
        daily["date"].max().date(),
    )


def _main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Re-fetch every year, ignoring cached hourly Parquet.",
    )
    args = parser.parse_args()
    run(refresh=args.refresh)


if __name__ == "__main__":
    _main()
