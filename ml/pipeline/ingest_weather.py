"""Open-Meteo weather ingestion: ERA5 archive + live overlay (Tier 2).

Use when: rebuilding the daily weather feature table for a given plant.
Two endpoints are combined per run:

  1. Customer ERA5 archive — full history back to 2005, lags real time
     by ~7 days.
  2. Customer forecast endpoint — recent past (~10d) + near future
     (~16d) of NWP-driven values, spliced over any archive-empty dates
     so today's row is populated for live inference.

Run via ``just features <slug>`` (chains all Tier 2 ingest scripts) or
directly via ``uv run python -m pipeline.ingest_weather --plant <slug>``.
``--refresh`` re-fetches every archive year. ``--skip-live`` disables
the forecast splice (use during backtest rebuilds so the historical
record stays ERA5-only).

Output:
- data/raw/weather/<slug>/{year}.parquet     (cached per-year hourly,
                                              namespaced per plant since
                                              the lat/lon differs)
- data/interim/weather_<slug>.parquet        (daily aggregated, UTC)
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
from plants import PLANTS, Plant, get_plant  # noqa: E402
from schemas import (  # noqa: E402
    OPENMETEO_ARCHIVE_URL,
    OPENMETEO_FORECAST_URL,
    WEATHER_ARCHIVE_END_LAG_DAYS,
    WEATHER_HOURLY_VARS,
)

# Live overlay window. The ERA5 archive lags ~7 days; we pull
# `past_days` from the forecast endpoint to cover that gap and
# `forecast_days` of forward NWP for any future-dated feature rows. The
# Open-Meteo forecast endpoint accepts past_days up to 92 and
# forecast_days up to 16, so 10 + 16 is well within limits and gives a
# couple-day cushion against day-boundary races.
LIVE_PAST_DAYS = 10
LIVE_FORECAST_DAYS = 16

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[1]  # ml/ (data lives at ml/data/)
RAW_DIR = REPO_ROOT / "data" / "raw" / "weather"
INTERIM_DIR = REPO_ROOT / "data" / "interim"

# Match the NRC label window so weather features cover every label day.
WEATHER_START_YEAR = 2005


def _fetch_year(
    year: int,
    plant_slug: str,
    lat: float,
    lon: float,
    apikey: str,
    refresh: bool,
) -> pd.DataFrame:
    """Pull (or reuse cached) hourly weather for one year, return as DataFrame.

    Cache is namespaced per plant slug since lat/lon differs between plants.
    """
    cache_dir = RAW_DIR / plant_slug
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache = cache_dir / f"{year}.parquet"

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
        "weather %s %d: fetching %s to %s (%d hourly vars)",
        plant_slug,
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


def _fetch_live(
    plant_slug: str, lat: float, lon: float, apikey: str
) -> pd.DataFrame:
    """Pull a recent-past + near-future window from Open-Meteo's forecast
    endpoint. Returns hourly rows with the same columns as the archive
    fetch so the daily-aggregation pipeline is shared.

    Use when: filling the ~7-day ERA5 archive gap so inference can
    anchor at today rather than at the lagging archive max. Not cached
    — always fresh per refresher run.
    """
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": ",".join(WEATHER_HOURLY_VARS),
        "past_days": LIVE_PAST_DAYS,
        "forecast_days": LIVE_FORECAST_DAYS,
        "timezone": "UTC",
        "apikey": apikey,
    }
    log.info(
        "weather %s live: fetching past=%d, forecast=%d (%d hourly vars)",
        plant_slug,
        LIVE_PAST_DAYS,
        LIVE_FORECAST_DAYS,
        len(WEATHER_HOURLY_VARS),
    )
    resp = requests.get(OPENMETEO_FORECAST_URL, params=params, timeout=120)
    resp.raise_for_status()
    payload = resp.json()
    if "hourly" not in payload:
        raise RuntimeError(f"weather live: unexpected payload (keys={list(payload)})")
    hourly = payload["hourly"]
    df = pd.DataFrame(hourly)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df = df.sort_values("time").reset_index(drop=True)
    log.info("weather live: fetched %d hourly rows", len(df))
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
    # Walks up from cwd to find a .env (works for both `cd ml && python -m`
    # locally and the Railway container where env vars are injected directly).
    load_dotenv()
    for name in ("OPENMETEO_API_KEY", "OPEN_METEO_API_KEY"):
        key = os.environ.get(name, "").strip()
        if key:
            return key
    raise RuntimeError(
        "Open-Meteo API key missing: set OPENMETEO_API_KEY in .env"
    )


def run(plant: Plant, refresh: bool = False, skip_live: bool = False) -> None:
    INTERIM_DIR.mkdir(parents=True, exist_ok=True)
    apikey = _load_apikey()
    current_year = datetime.now(timezone.utc).year

    frames: list[pd.DataFrame] = []
    for year in range(WEATHER_START_YEAR, current_year + 1):
        df = _fetch_year(
            year,
            plant_slug=plant.slug,
            lat=plant.lat,
            lon=plant.lon,
            apikey=apikey,
            refresh=refresh,
        )
        if not df.empty:
            frames.append(df)

    if not frames:
        raise RuntimeError("no weather years successfully ingested")

    hourly = pd.concat(frames, ignore_index=True)
    hourly = hourly.drop_duplicates(subset=["time"]).sort_values("time")

    daily = _aggregate_daily(hourly)

    # Splice in live forecast/recent-past values to cover the ERA5
    # archive lag and extend a few days into the future. Without this
    # the most recent ~7 daily rows have NaN weather and inference falls
    # back to a stale anchor date. Live overlay wins on rows it covers
    # since archive rows there are NaN-only anyway; for any same-date
    # collision the live value replaces archive (negligible drift in
    # practice and the live value is the "as of now" truth the demo
    # cares about).
    if not skip_live:
        try:
            live_hourly = _fetch_live(plant.slug, plant.lat, plant.lon, apikey)
            live_daily = _aggregate_daily(live_hourly)
            if not live_daily.empty:
                live_dates = set(live_daily["date"].unique())
                daily = pd.concat(
                    [daily[~daily["date"].isin(live_dates)], live_daily],
                    ignore_index=True,
                ).sort_values("date").reset_index(drop=True)
                log.info(
                    "weather live overlay: %d daily rows merged (%s -> %s)",
                    len(live_daily),
                    live_daily["date"].min().date(),
                    live_daily["date"].max().date(),
                )
        except Exception:  # noqa: BLE001
            log.exception("live overlay failed; serving archive-only weather")

    out = INTERIM_DIR / f"weather_{plant.slug}.parquet"
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
        "--plant",
        required=True,
        choices=sorted(PLANTS),
        help="Plant slug from ml/plants.py.",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Re-fetch every year, ignoring cached hourly Parquet.",
    )
    parser.add_argument(
        "--skip-live",
        action="store_true",
        help=(
            "Do not splice the Open-Meteo forecast endpoint over the "
            "archive. Useful for backtest rebuilds that should depend "
            "only on ERA5."
        ),
    )
    args = parser.parse_args()
    run(get_plant(args.plant), refresh=args.refresh, skip_live=args.skip_live)


if __name__ == "__main__":
    _main()
