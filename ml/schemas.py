"""Canonical schemas shared with api/. Copied into api/app/schemas.py at build time.

Contains only the constants populated tier-by-tier. Pydantic models will land
in later tiers when the API surface is filled in.
"""

# Canonical NRC unit name for Quad Cities Unit 1. NRC files use this exact
# string from 2005-onward; matching is performed case-insensitively at parse
# time so minor whitespace drift in older files cannot break ingestion.
CANONICAL_UNIT_QC1 = "Quad Cities 1"

# Earliest year the NRC publishes daily power-status files at the canonical
# URL. 1999 was specified in the plan; in practice files only exist from 2005.
NRC_EARLIEST_YEAR = 2005

# A unit is flagged is_outage=True for every day inside a run of >=N
# consecutive calendar days at exactly 0% power. Refueling outages typically
# span 14-30 days; 5 is conservative enough to also catch unplanned trips
# while excluding single-day curtailments that are weather-driven.
OUTAGE_MIN_CONSECUTIVE_DAYS = 5

# Pre-outage / coastdown detection. Operators ramp the reactor down over
# days-to-weeks before a planned refueling outage (and end-of-cycle fuel
# reactivity drives a longer "coastdown"); these days are not weather-driven
# and must be flagged so they can be excluded from training.
#
# Algorithm (applied per unit, only to outage runs of length
# >= REFUELING_OUTAGE_MIN_DAYS — i.e. real refueling cadence, not unplanned
# trips which have no planned ramp):
#   - Look at the PRE_OUTAGE_LOOKBACK_DAYS calendar days preceding the outage.
#   - Define baseline = max(power_pct) within that lookback.
#   - Walk backward day-by-day from the outage start, flagging is_pre_outage.
#   - Stop when PRE_OUTAGE_RECOVERY_RUN_LEN consecutive days are observed at
#     >= baseline - PRE_OUTAGE_TOLERANCE_PCT (the unit returned to full
#     output, so any prior dip is not part of this outage's coastdown).
#   - Cap at the lookback boundary if no recovery is found.
REFUELING_OUTAGE_MIN_DAYS = 14
PRE_OUTAGE_LOOKBACK_DAYS = 90
PRE_OUTAGE_TOLERANCE_PCT = 2
PRE_OUTAGE_RECOVERY_RUN_LEN = 3

# Fixed minimum number of days to flag as is_pre_outage immediately before
# every refueling outage. Acts as a floor on top of the adaptive coastdown
# detection above: when the algorithm finds a longer ramp it wins; when it
# finds none (abrupt drop or pre-uprate flat baseline) this guarantees the
# refueling outage still has a pre-outage exclusion window.
PRE_OUTAGE_MIN_BUFFER_DAYS = 14

# --- Tier 2: features ----------------------------------------------------

# Quad Cities Generating Station (Cordova, IL). Single-point pull at the
# reactor footprint; the river is co-located so air-temp drift between intake
# and reactor is negligible (flagged in Project_Plan.md as a known v1 caveat).
QC1_LAT = 41.7261
QC1_LON = -90.3097

# Open-Meteo customer endpoints. The paid plan authenticates via a lowercase
# `apikey` query parameter on every request.
OPENMETEO_ARCHIVE_URL = "https://customer-archive-api.open-meteo.com/v1/archive"
OPENMETEO_FORECAST_URL = "https://customer-api.open-meteo.com/v1/forecast"
OPENMETEO_HIST_FORECAST_URL = (
    "https://customer-historical-forecast-api.open-meteo.com/v1/forecast"
)

# Hourly variables pulled from the archive. Cloud-cover is added beyond the
# Project_Plan.md list because it's a cheap proxy for shortwave at the surface
# and helps disambiguate hot-cloudy from hot-clear days.
WEATHER_HOURLY_VARS = (
    "temperature_2m",
    "dew_point_2m",
    "relative_humidity_2m",
    "wind_speed_10m",
    "shortwave_radiation",
    "precipitation",
    "surface_pressure",
    "cloud_cover",
)

# ERA5 archive latency: Open-Meteo typically lags by ~5 days. Padding to 7
# avoids requesting nulls on every fresh ingest.
WEATHER_ARCHIVE_END_LAG_DAYS = 7

# USGS NWIS daily values. 05420500 (Mississippi at Clinton, IA) is the long
# record; in 2021 USGS moved the temp sensor downstream to 05420400 which
# became the active gauge. Plan recommendation: treat as one continuous
# series, splice at the date 05420400 first reports, log overlap correlation.
USGS_SITE_PRIMARY = "05420500"   # 1999 - 2021ish
USGS_SITE_SECONDARY = "05420400"  # 2021 - present
USGS_PARAM_TEMP = "00010"        # water temperature, deg C
USGS_PARAM_FLOW = "00060"        # discharge, cubic feet/sec
USGS_DV_URL = "https://waterservices.usgs.gov/nwis/dv/"

# EIA-860 annual release. As of 2026-04 the latest fully-published archive is
# 2023; 2024 final lands mid-year. The ingest tries the newest year first and
# falls back. Released zips contain `2___Plant_Y{year}.xlsx` and
# `3_1_Generator_Y{year}.xlsx`.
EIA860_YEAR_CANDIDATES = (2024, 2023, 2022)
EIA860_URL = "https://www.eia.gov/electricity/data/eia860/archive/xls/eia860{year}.zip"
EIA860_FALLBACK_URL = "https://www.eia.gov/electricity/data/eia860/xls/eia860{year}.zip"

# Feature engineering windows. Lag windows match the inference horizons (1, 3,
# 7, 14) so the model sees the same temporal granularity at training and
# serving. Rolling windows are mean and max over each span.
LAG_DAYS = (1, 3, 7, 14)
ROLLING_WINDOWS = (7, 14, 30)

# Rolling features must use closed='left' so the row's value at date t only
# sees data strictly prior to t (no leakage from the same-day observation).
ROLLING_CLOSED = "left"
