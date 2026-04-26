"""Canonical schemas shared with api/. Copied into api/app/schemas.py at build time.

Holds the constants populated tier-by-tier plus the Pydantic response models
that define the API surface. Both ml/ and api/ import from this file so the
contract has a single source of truth.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

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

# --- Tier 3: model ------------------------------------------------------

# Forecast horizons in days. One model is trained per horizon; the target
# for horizon h on row at date t is power_pct at t+h (literal value-at-
# horizon, not min-over-window). A full daily curve out to 14 days lets
# the API derive operator summaries (predicted minimum + day on which it
# occurs, p10 worst-case bound) from a single inference call.
HORIZONS = tuple(range(1, 15))  # 1..14 inclusive

# Downside-only quantile band. The product cares about derating risk —
# how bad could it get — so we train q10 ("1-in-10 worst case") as the
# single downside band and skip the upside entirely. An upper band tells
# operators nothing actionable for this use case. q25 was evaluated as
# an alternative but added no independent signal once both were
# conformally calibrated; q10's higher recall is more operationally
# valuable (missing a dip is worse than firing a false alarm).
# p50 is intentionally not trained: the unconditional median of
# power_pct is 100 (~75% of operating-day rows), which mode-collapses
# the median objective. The dip-weighted point model is our central
# estimate.
BAND_QUANTILES = (0.10,)

# Time-based splits. Plan called for train 1999-2018 / val 2019-2021 /
# test 2022+ but NRC data only starts 2005 (see NRC_EARLIEST_YEAR), so the
# windows are shifted forward to keep ~3yr val and ~2-3yr test. End dates
# are inclusive.
TRAIN_END = "2019-12-31"
VAL_END = "2022-12-31"
# Test runs from VAL_END+1 to the latest available row in the dataset.

# Columns excluded from the feature matrix. `date` and `unit` are metadata;
# `power_pct` is the source for targets; `is_outage`/`is_pre_outage` are
# used only to filter training rows (model sees weather-driven dynamics
# only — at inference these flags are surfaced separately in the API).
NON_FEATURE_COLS = (
    "date",
    "unit",
    "power_pct",
    "is_outage",
    "is_pre_outage",
)

# Categorical features for XGBoost (enable_categorical=True). Only
# water_site_id today; the model can learn the ~0.75 deg C systematic
# offset between USGS gauges 05420500 and 05420400.
CATEGORICAL_FEATURES = ("water_site_id",)

# XGBoost hyperparameters. Modest depth + many rounds + early stopping on
# val gives a strong baseline without tuning. Same params for every
# (horizon, quantile) model — separate tuning per cell isn't worth the
# hackathon time and risks overfitting the val set.
XGB_PARAMS = {
    "n_estimators": 1500,
    "max_depth": 6,
    "learning_rate": 0.05,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "min_child_weight": 4,
    "reg_lambda": 1.0,
    "tree_method": "hist",
    "enable_categorical": True,
    "random_state": 42,
}
XGB_EARLY_STOPPING_ROUNDS = 50

# Summer months for the "summer-only" honesty slice in metrics.json. June
# through September captures the heatwave window for the upper Mississippi
# without bleeding into shoulder seasons.
SUMMER_MONTHS = (6, 7, 8, 9)

# A test row is a "dip event" when the realized power_pct at t+h falls
# below this threshold. Persistence wins MAE on the heavy 100% mode of
# the target distribution, so the operationally meaningful comparison is
# performance on rows where the plant actually derates — that's where
# the model has to earn its keep. Also doubles as the upper boundary of
# the UI "watch" tier (any prediction below 95 gets at least a yellow
# badge).
DIP_THRESHOLD_PCT = 95

# Stricter UI threshold for the red "alert" badge. The dip-weighted point
# model clusters predictions in the 92-97 range on most days, so a single
# threshold at 95 fires on ~99% of days and is operationally useless. The
# two-tier scheme (green ≥95, yellow 90-95, red <90) cuts the red-alert
# rate to ~40% of days while still capturing the genuinely dip-likely
# forecasts. Per-date analysis on the 2023+ test split: at T=90 the model
# fires red on 422/1027 days and catches 13 of 26 actual sub-95% dips;
# the remaining ~13 dips appear as yellow watches rather than reds.
UI_ALERT_THRESHOLD_PCT = 90

# Base temperature (deg C) for the cumulative-heat-dose features
# (heat_dose_7d / heat_dose_14d): rolling sum of max(0, air_temp_c_max -
# HEAT_DOSE_BASE_C) over the prior N days. 25C corresponds roughly to the
# threshold above which once-through-cooling thermal-discharge limits start
# to matter for upper-Mississippi reactors.
HEAT_DOSE_BASE_C = 25.0

# Sample-weight multiplier applied during XGBoost training to up-weight dip
# rows so the squared-error mean model stops regressing to the 100% mode.
# Weight for a target y is 1 + DIP_WEIGHT_ALPHA * max(0, (100 - y) / 5):
# a full-power row gets weight 1, a 95% row gets weight ~1+alpha, a 70% row
# ~1+6*alpha. Applied to the POINT model only — weighting the quantile fits
# distorts the natural distribution and blows up band width. Tier 4 split-
# conformal calibration handles band coverage on top of unweighted quantile
# fits.
DIP_WEIGHT_ALPHA = 0.5

# --- Tier 4: inference and backtest -------------------------------------

# Target empirical coverage for the symmetric uncertainty band around
# the point forecast. delta_h is the (BAND_TARGET_COVERAGE)-th percentile
# of |point - actual| on val; we publish [point - delta_h, point +
# delta_h] expecting ~80% of realized actuals to land inside that span.
# Symmetric (rather than one-sided downside) because the dip-weighted
# point already incorporates the lower-tail signal — the natural
# residual distribution centered on it is roughly symmetric, and a band
# representing "typical model uncertainty" is more honest than a band
# claiming additional downside the point estimate hasn't already priced.
BAND_TARGET_COVERAGE = 0.80

# Named historical run dates highlighted in the backtest report. Each
# date pulls archived NWP from the Open-Meteo historical-forecast endpoint
# when within coverage (2016-01-01 onward). Pre-2016 dates fall back to
# ERA5 archive values for the day-of feature row, with the source labeled
# in the report so the hindsight caveat is explicit. 2012-07-15 is the
# only fallback among the named dates.
HISTORICAL_BACKTEST_DATES = (
    "2012-07-15",  # Midwest heatwave (ERA5 fallback — pre-NWP archive)
    "2018-07-01",
    "2021-08-01",
    "2022-07-15",
    "2023-08-15",
)
HISTORICAL_NWP_MIN_DATE = "2016-01-01"


# --- API contract -------------------------------------------------------

ForecastSource = Literal["live", "historical_nwp", "era5_fallback"]
AlertLevel = Literal["operational", "watch", "alert"]


class HorizonPrediction(BaseModel):
    """One day's prediction within a multi-horizon forecast."""

    horizon_days: int = Field(..., ge=1, le=14)
    target_date: date
    point_pct: float = Field(..., description="Dip-weighted point estimate, 0-100.")
    band_low_pct: float = Field(
        ...,
        description=(
            "Lower edge of the symmetric uncertainty band: point - delta_h, "
            "where delta_h is the per-horizon 80th-percentile of "
            "|point - actual| on val. Clamped to [0, 100]."
        ),
    )
    band_high_pct: float = Field(
        ...,
        description=(
            "Upper edge of the symmetric uncertainty band: point + delta_h. "
            "Together with band_low_pct forms an ~80% prediction interval."
        ),
    )
    alert_level: AlertLevel = Field(
        ...,
        description=(
            "UI badge tier. 'operational' = point >= 95 (green), 'watch' = "
            "90 <= point < 95 (yellow, marginal), 'alert' = point < 90 "
            "(red, model predicts a real dip). The two-tier split keeps "
            "the red-alert rate ~40% of days instead of ~99% under a "
            "single 95% threshold."
        ),
    )


class ForecastResponse(BaseModel):
    """Full 14-day forecast response — one HorizonPrediction per day."""

    plant_id: str
    run_date: date
    source: ForecastSource = Field(
        ...,
        description=(
            "Where the day-of feature values came from: 'live' for "
            "real-time forecast, 'historical_nwp' for archived NWP runs "
            "(2016+), 'era5_fallback' for older dates."
        ),
    )
    horizons: list[HorizonPrediction]


class BacktestRow(BaseModel):
    """One (run_date, horizon) entry in a backtest replay."""

    horizon_days: int = Field(..., ge=1, le=14)
    run_date: date
    target_date: date
    actual_pct: float | None = Field(
        None,
        description=(
            "Realized capacity factor; null if the target day is in the "
            "future or filtered out (outage / pre-outage)."
        ),
    )
    point_pct: float
    band_low_pct: float
    band_high_pct: float


class BacktestResponse(BaseModel):
    """All horizons for a single as_of run date."""

    plant_id: str
    as_of: date
    source: ForecastSource
    rows: list[BacktestRow]


class Plant(BaseModel):
    """Catalog entry for one nuclear plant on the UI map.

    `modeled=True` means the v1 forecast pipeline serves real predictions
    for this plant. `modeled=False` plants are placeholder pins from
    EIA-860 used to communicate "scaling is the next step" — clicking
    them in the UI should surface a "model coming soon" affordance.
    """

    id: str
    display_name: str
    operator: str | None = None
    river: str | None = None
    lat: float
    lon: float
    state: str | None = None
    plant_code: int | None = Field(
        None,
        description="EIA-860 plant_code; null for hand-curated entries.",
    )
    nameplate_mw: float | None = None
    modeled: bool


class ActualPoint(BaseModel):
    """One realized day of capacity factor for the historical-actuals chart."""

    date: date
    power_pct: float | None = Field(
        None,
        description=(
            "Realized capacity factor (0-100). Null when the unit is in a "
            "refueling outage or pre-outage coastdown — those days are "
            "filtered so the chart shows weather-driven dynamics only."
        ),
    )
    is_outage: bool


class ActualsResponse(BaseModel):
    """Trailing window of realized actuals for the forecast chart."""

    plant_id: str
    days: int
    points: list[ActualPoint]


class WeatherInputPoint(BaseModel):
    """One day's weather/water inputs for the sparkline panel."""

    date: date
    air_temp_c_max: float | None = None
    water_temp_c: float | None = None
    streamflow_cfs: float | None = None


class InputsResponse(BaseModel):
    """Recent weather and water inputs feeding the model."""

    plant_id: str
    points: list[WeatherInputPoint]


class FeatureContribution(BaseModel):
    """Per-feature SHAP contribution for one horizon's prediction."""

    feature: str
    value: float | None = Field(
        None,
        description=(
            "Raw feature value at run_date. Null for categorical or "
            "missing values (XGBoost handles missingness natively)."
        ),
    )
    contribution_pct: float = Field(
        ...,
        description=(
            "Signed SHAP value in capacity-factor percentage points. "
            "Sums (with baseline_pct) to point_pct exactly."
        ),
    )


class HorizonAttribution(BaseModel):
    """Top-N feature attributions for one forecast horizon."""

    horizon_days: int = Field(..., ge=1, le=14)
    baseline_pct: float = Field(
        ...,
        description="Booster bias term — the model's mean prediction.",
    )
    point_pct: float
    top_features: list[FeatureContribution]


class AttributionsResponse(BaseModel):
    """SHAP attributions for the latest precomputed forecast.

    One entry per horizon (1..14). The UI defaults to showing
    horizon_days == 7 (the headline forecast), but all horizons are
    served so a future drill-down can switch horizons without a
    second request.
    """

    plant_id: str
    run_date: date
    horizons: list[HorizonAttribution]


class BriefingRiskDay(BaseModel):
    """One flagged horizon in the LLM-generated briefing."""

    target_date: date
    horizon_days: int = Field(..., ge=1, le=14)
    point_pct: float
    alert_level: AlertLevel
    explanation: str


class BriefingResponse(BaseModel):
    """Plain-English forecast briefing produced by Gemma 3 27B on Bedrock.

    Generated daily during the ml refresh from the just-written forecast +
    attributions context. Text only; the UI re-uses ForecastResponse for
    visuals so any numeric drift stays bounded to the chart.
    """

    plant_id: str
    run_date: date
    generated_at: datetime
    model_id: str
    headline: str
    risk_days: list[BriefingRiskDay]
    drivers: list[str]
    outlook: str
    fallback: bool = False


class BacktestDatesResponse(BaseModel):
    """Valid as_of values for the replay slider.

    `dates` is the full sorted set of run_dates the backtest parquet
    covers (~1000 days on the 2023+ test split). `highlights` is the
    subset called out in the report — historical dates with documented
    heatwave context. The UI can render these as labeled tick marks.
    """

    plant_id: str
    dates: list[date]
    highlights: list[date]


class BacktestSeriesPoint(BaseModel):
    """One realized + predicted pair at a single date for one horizon."""

    date: date
    actual_pct: float | None = None
    point_pct: float


class BacktestSeriesResponse(BaseModel):
    """Trailing window of (date, actual, predicted) at one fixed horizon.

    Powers the History view's "what would the model have predicted"
    overlay: a single bulk request returns the full series so the chart
    can render without one round trip per scrub.
    """

    plant_id: str
    horizon_days: int
    points: list[BacktestSeriesPoint]


DipCategory = Literal[
    "operational",
    "weather_dependent",
    "non_weather_dependent",
    "refueling",
    "post_refuel_recovery",
]


class HistoryPoint(BaseModel):
    """One day in the History month view.

    `power_pct` is forced to 0 on refueling/pre-outage days (rather than
    null) so the calendar chart can render an explicit "Refueling" red
    band at the floor instead of a confusing gap.
    """

    date: date
    power_pct: float = Field(
        ...,
        description=(
            "Realized capacity factor (0-100). 0 on refueling/pre-outage "
            "days."
        ),
    )
    is_outage: bool
    prediction_pct: float | None = Field(
        None,
        description=(
            "Backtested point prediction at horizon=7 for this date, if "
            "available."
        ),
    )
    dip_category: DipCategory = Field(
        ...,
        description=(
            "operational / weather_dependent / non_weather_dependent / "
            "refueling / post_refuel_recovery. non_weather_dependent flags "
            "days where the model predicted no dip (>=95) but realization "
            "fell below 90. post_refuel_recovery flags sub-95 days between "
            "the end of an outage and the first day the plant returns to "
            ">=95, so reactor ramp-back doesn't read as a weather dip."
        ),
    )


class HistoryResponse(BaseModel):
    """All days in a single calendar year for the History view."""

    plant_id: str
    year: int
    points: list[HistoryPoint]
