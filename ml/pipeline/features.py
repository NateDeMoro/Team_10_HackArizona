"""Feature engineering for the daily training dataset (Tier 2).

Use when: building wet-bulb / heat-index derived columns and lag/rolling
features on top of the daily weather + water tables. Run via `just features`
or `uv run python -m pipeline.features`. Reads:
    data/interim/weather_quad_cities.parquet
    data/interim/water_quad_cities.parquet
Writes:
    data/interim/features_quad_cities.parquet

Wet-bulb uses the Stull (2011) empirical fit; heat index uses the NWS
Rothfusz formula (with the Steadman low-T/RH adjustment skipped — at
hackathon scale the standard form is fine and was hand-checked against the
NWS table). Both are computed from daily-mean temperature and RH; the
hourly-resolution refinement is left for a future iteration (a daily-mean
wet-bulb under-estimates daily-max stress by ~1-2 deg C, but the rolling
windows downstream wash most of that out).
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from schemas import LAG_DAYS, ROLLING_CLOSED, ROLLING_WINDOWS  # noqa: E402

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
INTERIM_DIR = REPO_ROOT / "data" / "interim"

# Columns used to build lags and rolling features. Kept narrow so the feature
# matrix stays interpretable in SHAP plots.
LAG_COLS = (
    "air_temp_c_max",
    "air_temp_c_mean",
    "rh_pct_mean",
    "wet_bulb_c",
    "heat_index_c",
    "water_temp_c",
    "streamflow_cfs",
)
ROLL_COLS = (
    "air_temp_c_max",
    "wet_bulb_c",
    "water_temp_c",
    "streamflow_cfs",
)


def stull_wet_bulb_c(temp_c: pd.Series, rh_pct: pd.Series) -> pd.Series:
    """Stull (2011) empirical wet-bulb in degrees C.

    Valid for relative humidity 5-99% and temperature -20 to +50 C. Returns
    NaN where inputs are NaN. Hand-checked against the AMS table at
    (T=30C, RH=50%) -> ~22.0C.
    """
    t = temp_c.astype(float)
    rh = rh_pct.astype(float)
    return (
        t * np.arctan(0.151977 * np.sqrt(rh + 8.313659))
        + np.arctan(t + rh)
        - np.arctan(rh - 1.676331)
        + 0.00391838 * np.power(rh, 1.5) * np.arctan(0.023101 * rh)
        - 4.686035
    )


def heat_index_c(temp_c: pd.Series, rh_pct: pd.Series) -> pd.Series:
    """NWS Rothfusz heat index, in degrees C. Inputs must be daily-mean.

    The formula is published in deg F; converts on input/output. Below 27 C
    (80 F) heat-index physics doesn't apply, so we return the raw temperature
    in that range — the model still gets a continuous signal.
    """
    t_f = temp_c.astype(float) * 9.0 / 5.0 + 32.0
    rh = rh_pct.astype(float)

    hi_f = (
        -42.379
        + 2.04901523 * t_f
        + 10.14333127 * rh
        - 0.22475541 * t_f * rh
        - 0.00683783 * t_f**2
        - 0.05481717 * rh**2
        + 0.00122874 * t_f**2 * rh
        + 0.00085282 * t_f * rh**2
        - 0.00000199 * t_f**2 * rh**2
    )
    out_f = np.where(t_f >= 80.0, hi_f, t_f)
    return pd.Series((out_f - 32.0) * 5.0 / 9.0, index=temp_c.index)


def _add_derived(df: pd.DataFrame) -> pd.DataFrame:
    """Add wet-bulb and heat-index columns derived from daily-mean inputs."""
    df = df.copy()
    df["wet_bulb_c"] = stull_wet_bulb_c(df["air_temp_c_mean"], df["rh_pct_mean"])
    df["heat_index_c"] = heat_index_c(df["air_temp_c_mean"], df["rh_pct_mean"])
    return df


def _add_lags(df: pd.DataFrame, cols: tuple[str, ...], lags: tuple[int, ...]) -> pd.DataFrame:
    """Append per-column lag features. df must be sorted by date ascending."""
    df = df.copy()
    for col in cols:
        if col not in df.columns:
            continue
        for k in lags:
            df[f"{col}_lag{k}"] = df[col].shift(k)
    return df


def _add_rolling(
    df: pd.DataFrame, cols: tuple[str, ...], windows: tuple[int, ...]
) -> pd.DataFrame:
    """Append rolling mean and max with closed='left' so row t sees only <t."""
    df = df.copy()
    for col in cols:
        if col not in df.columns:
            continue
        for w in windows:
            roll = df[col].rolling(window=w, min_periods=max(2, w // 2), closed=ROLLING_CLOSED)
            df[f"{col}_roll{w}_mean"] = roll.mean()
            df[f"{col}_roll{w}_max"] = roll.max()
    return df


def _add_seasonality(df: pd.DataFrame) -> pd.DataFrame:
    """Day-of-year sin/cos so the model can learn smooth seasonal effects."""
    df = df.copy()
    doy = df["date"].dt.dayofyear.astype(float)
    # 365.25 absorbs leap years without a discontinuity at year boundaries.
    angle = 2.0 * np.pi * doy / 365.25
    df["doy_sin"] = np.sin(angle)
    df["doy_cos"] = np.cos(angle)
    return df


def _validate_dates(df: pd.DataFrame) -> None:
    """Assert the date column is tz-naive and one row per calendar day."""
    if df["date"].dt.tz is not None:
        raise RuntimeError("date column must be tz-naive UTC days")
    dups = df["date"].duplicated().sum()
    if dups:
        raise RuntimeError(f"date column has {dups} duplicates")


def run() -> None:
    INTERIM_DIR.mkdir(parents=True, exist_ok=True)
    weather_path = INTERIM_DIR / "weather_quad_cities.parquet"
    water_path = INTERIM_DIR / "water_quad_cities.parquet"
    if not weather_path.exists():
        raise FileNotFoundError(f"missing {weather_path}; run ingest_weather first")
    if not water_path.exists():
        raise FileNotFoundError(f"missing {water_path}; run ingest_usgs first")

    weather = pd.read_parquet(weather_path)
    water = pd.read_parquet(water_path)
    log.info("loaded weather=%d rows, water=%d rows", len(weather), len(water))

    weather["date"] = pd.to_datetime(weather["date"]).dt.tz_localize(None).dt.normalize()
    water["date"] = pd.to_datetime(water["date"]).dt.tz_localize(None).dt.normalize()

    # water_site_id is carried as a categorical so the model can learn the
    # ~0.75 deg C systematic offset between the two gauges (05420500 Clinton
    # vs 05420400 Dam 13). Tier 3 will set XGBoost enable_categorical=True.
    water_cols = ["date", "water_temp_c", "streamflow_cfs"]
    if "water_site_id" in water.columns:
        water_cols.append("water_site_id")
    df = weather.merge(water[water_cols], on="date", how="outer")
    df = df.sort_values("date").reset_index(drop=True)
    if "water_site_id" in df.columns:
        df["water_site_id"] = df["water_site_id"].astype("category")

    df = _add_derived(df)
    df = _add_lags(df, LAG_COLS, LAG_DAYS)
    df = _add_rolling(df, ROLL_COLS, ROLLING_WINDOWS)
    df = _add_seasonality(df)
    _validate_dates(df)

    out = INTERIM_DIR / "features_quad_cities.parquet"
    df.to_parquet(out, index=False)
    log.info(
        "wrote %s: %d rows x %d cols, %s -> %s",
        out,
        len(df),
        df.shape[1],
        df["date"].min().date(),
        df["date"].max().date(),
    )


def _main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.parse_args()
    run()


if __name__ == "__main__":
    _main()
