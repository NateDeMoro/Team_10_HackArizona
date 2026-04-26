"""All forecast/backtest/feature data is pulled from Postgres.

The api container ships no data files. The ml refresher service runs on
a daily cron, regenerates everything (forecast, attributions, backtest
results, interim parquets, EIA snapshot), and pushes the bytes into the
``forecast_artifacts`` table. Every loader here fetches from PG via
``app.db.fetch_artifact`` (which has its own 5-min TTL cache).

``SUPPORTED_PLANTS`` is the route-layer allowlist — add new slugs once
the refresher is producing artifacts for them.
"""
from __future__ import annotations

import io
import json
from datetime import date

import pandas as pd

from app.db import GLOBAL_PLANT, fetch_artifact

# Plants the api will serve. A slug is "supported" once `just train`,
# `just backtest`, and a successful refresher run have produced its
# artifact set in postgres. Adding a new slug here is the only api-side
# change needed to expose another plant.
SUPPORTED_PLANTS = frozenset({"quad_cities_1", "byron_1"})


def _ensure_supported(slug: str) -> None:
    """Raise ValueError for slugs not in SUPPORTED_PLANTS — route layer
    converts this into a 404 with a helpful detail."""
    if slug not in SUPPORTED_PLANTS:
        raise ValueError(
            f"plant_id={slug!r} not modeled; supported: {sorted(SUPPORTED_PLANTS)}"
        )


def _fetch_json(slug: str, artifact_type: str) -> dict:
    return json.loads(fetch_artifact(slug, artifact_type).decode("utf-8"))


def _fetch_parquet(slug: str, artifact_type: str) -> pd.DataFrame:
    return pd.read_parquet(io.BytesIO(fetch_artifact(slug, artifact_type)))


# ---------- forecast + attributions (refreshed daily) -------------------


def load_forecast(slug: str) -> dict:
    _ensure_supported(slug)
    return _fetch_json(slug, "forecast")


def load_attributions(slug: str) -> dict:
    _ensure_supported(slug)
    return _fetch_json(slug, "attributions")


# ---------- backtest (rebuilt daily by the refresher) ------------------


def load_backtest_metrics(slug: str) -> dict:
    _ensure_supported(slug)
    return _fetch_json(slug, "backtest_metrics")


def load_backtest_for_run_date(slug: str, run_date: date) -> list[dict]:
    """Return all (horizon, prediction, actual) rows for a given run date."""
    _ensure_supported(slug)
    df = _fetch_parquet(slug, "backtest_results")
    df["feature_date"] = pd.to_datetime(df["feature_date"]).dt.date
    df["target_date"] = pd.to_datetime(df["target_date"]).dt.date
    sub = df[df["feature_date"] == run_date]
    return sub.sort_values("horizon").to_dict(orient="records")


def load_backtest_series(slug: str, horizon: int, days: int) -> list[dict]:
    """Trailing window of (target_date, actual, point) rows for one horizon.

    Used by the History overlay to show what the model would have
    predicted on each historical day. Indexed by target_date (when the
    forecast was *for*) rather than feature_date (when the run was made),
    since the History chart's x-axis is target dates.
    """
    _ensure_supported(slug)
    df = _fetch_parquet(slug, "backtest_results")[
        ["horizon", "target_date", "actual", "point"]
    ]
    sub = df[df["horizon"] == horizon].copy()
    sub["target_date"] = pd.to_datetime(sub["target_date"]).dt.date
    sub = sub.sort_values("target_date").tail(days)
    return [
        {
            "date": r["target_date"],
            "actual_pct": (
                float(r["actual"]) if r.get("actual") is not None and pd.notna(r.get("actual")) else None
            ),
            "point_pct": float(r["point"]),
        }
        for r in sub.to_dict(orient="records")
    ]


def load_backtest_dates(slug: str) -> list[date]:
    """Sorted unique run_dates available in the backtest parquet.

    Powers the replay slider's valid range. The parquet is rewritten by
    the refresher; the db.py TTL cache keeps repeat reads cheap.
    """
    _ensure_supported(slug)
    df = _fetch_parquet(slug, "backtest_results")[["feature_date"]]
    dates = pd.to_datetime(df["feature_date"]).dt.date.unique().tolist()
    return sorted(dates)


# ---------- recent observed data (refreshed daily) ----------------------


def load_recent_actuals(slug: str, days: int) -> list[dict]:
    """Return the most recent N days of realized capacity factor.

    Outage and pre-outage rows are returned with `power_pct=None` so the
    chart can render a gap rather than a misleading 0%.
    """
    _ensure_supported(slug)
    df = _fetch_parquet(slug, "labels")
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df = df.sort_values("date").tail(days)
    rows: list[dict] = []
    for r in df.to_dict(orient="records"):
        is_outage = bool(r.get("is_outage")) or bool(r.get("is_pre_outage"))
        power = r.get("power_pct")
        rows.append(
            {
                "date": r["date"],
                "power_pct": float(power) if power is not None and not is_outage else None,
                "is_outage": is_outage,
            }
        )
    return rows


def load_history_year(slug: str, year: int) -> list[dict]:
    """Every calendar day in `year` with realization, horizon-7
    backtest prediction (if any), and a dip category.

    Refueling / pre-outage rows surface as power_pct=0 with is_outage=True
    so the chart can render an explicit "Refueling" red floor instead of
    a gap. Dip category combines actual + prediction:
      - refueling: is_outage row
      - non_weather_dependent: power < 90 and prediction >= 95 (model
        saw no weather signal but reality dipped)
      - weather_dependent: any other sub-95 day, including pre-2023
        dates with no backtest prediction to make a claim either way
      - operational: power >= 95 and not in outage
    """
    _ensure_supported(slug)
    df = _fetch_parquet(slug, "labels")
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df = df[df["date"].apply(lambda d: d.year == year)].sort_values("date")

    pred_by_date: dict[date, float] = {}
    try:
        bdf = _fetch_parquet(slug, "backtest_results")[
            ["horizon", "target_date", "point"]
        ]
        bdf = bdf[bdf["horizon"] == 7].copy()
        bdf["target_date"] = pd.to_datetime(bdf["target_date"]).dt.date
        bdf = bdf[bdf["target_date"].apply(lambda d: d.year == year)]
        for r in bdf.to_dict(orient="records"):
            pred_by_date[r["target_date"]] = float(r["point"])
    except FileNotFoundError:
        pass

    rows: list[dict] = []
    for r in df.to_dict(orient="records"):
        is_outage = bool(r.get("is_outage")) or bool(r.get("is_pre_outage"))
        raw_power = r.get("power_pct")
        prediction = pred_by_date.get(r["date"])
        if is_outage:
            power_pct = 0.0
            category = "refueling"
        else:
            power_pct = (
                float(raw_power)
                if raw_power is not None and not pd.isna(raw_power)
                else 0.0
            )
            if power_pct >= 95:
                category = "operational"
            elif power_pct < 90 and prediction is not None and prediction >= 95:
                category = "non_weather_dependent"
            else:
                category = "weather_dependent"
        rows.append(
            {
                "date": r["date"],
                "power_pct": power_pct,
                "is_outage": is_outage,
                "prediction_pct": prediction,
                "dip_category": category,
            }
        )
    return rows


def load_recent_inputs(slug: str, days: int) -> list[dict]:
    """Join the trailing N days of weather + water inputs for sparklines."""
    _ensure_supported(slug)
    weather = _fetch_parquet(slug, "weather")[["date", "air_temp_c_max"]]
    water = _fetch_parquet(slug, "water")[["date", "water_temp_c", "streamflow_cfs"]]
    df = weather.merge(water, on="date", how="outer").sort_values("date").tail(days)
    df["date"] = pd.to_datetime(df["date"]).dt.date

    def _f(v: object) -> float | None:
        if v is None or pd.isna(v):
            return None
        return float(v)

    return [
        {
            "date": r["date"],
            "air_temp_c_max": _f(r.get("air_temp_c_max")),
            "water_temp_c": _f(r.get("water_temp_c")),
            "streamflow_cfs": _f(r.get("streamflow_cfs")),
        }
        for r in df.to_dict(orient="records")
    ]


# ---------- global EIA-860 snapshot (refreshed daily, single row) -------


def load_eia_plants() -> list[dict]:
    """Return all nuclear plants from EIA-860 as plain dicts.

    Sorted by display name for stable map ordering. The route layer is
    responsible for stamping the canonical id (`eia_<plant_code>`) and
    overlaying any hand-curated entries (e.g. QC1 with operator/river
    detail EIA does not surface).
    """
    df = _fetch_parquet(GLOBAL_PLANT, "eia_plants")
    df = df.sort_values("plant_name")
    rows: list[dict] = []
    for r in df.to_dict(orient="records"):
        plant_code_raw = r.get("plant_code")
        if plant_code_raw is None or pd.isna(plant_code_raw):
            continue
        rows.append(
            {
                "plant_code": int(plant_code_raw),
                "plant_name": str(r.get("plant_name") or "").strip(),
                "state": (str(r.get("state")).strip() if r.get("state") else None),
                "lat": float(r.get("latitude")) if r.get("latitude") is not None else None,
                "lon": float(r.get("longitude")) if r.get("longitude") is not None else None,
                "operator": (
                    str(r.get("utility_name")).strip() if r.get("utility_name") else None
                ),
                "nameplate_mw": (
                    float(r.get("total_nameplate_mw"))
                    if r.get("total_nameplate_mw") is not None
                    and not pd.isna(r.get("total_nameplate_mw"))
                    else None
                ),
            }
        )
    return rows
