"""Read precomputed forecast/backtest artifacts from data/artifacts.

The api/ container does not invoke the ML pipeline at request time. The
demo flow is: `just forecast` (refreshes data/artifacts/forecast_latest.json
and attributions_latest.json) and `just backtest` (refreshes
data/artifacts/backtest_results.parquet) on the operator's machine, then
the api serves the cached artifacts. This keeps the api container free of
Open-Meteo secrets, XGBoost, and pandas-driven feature pipelines at
request time, with one exception: the recent-actuals, inputs, and
backtest readers do a lightweight pandas read against interim parquet
when called.
"""
from __future__ import annotations

import json
from datetime import date
from functools import lru_cache
from pathlib import Path

# Resolve repo root from this file's location:
#   api/app/data_loader.py -> ../../../ = repo root
REPO_ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS_DIR = REPO_ROOT / "data" / "artifacts"
INTERIM_DIR = REPO_ROOT / "data" / "interim"

# v1 API serves a single plant. The slug picks which subdirectory under
# data/artifacts/ and which slug-suffixed interim files this container
# reads. The training pipeline already supports arbitrary slugs; multi-
# plant API integration is a separate task.
PLANT_SLUG = "quad_cities_1"
_PLANT_ARTIFACTS_DIR = ARTIFACTS_DIR / PLANT_SLUG


def forecast_path() -> Path:
    return _PLANT_ARTIFACTS_DIR / "forecast_latest.json"


def attributions_path() -> Path:
    return _PLANT_ARTIFACTS_DIR / "attributions_latest.json"


def backtest_results_path() -> Path:
    return _PLANT_ARTIFACTS_DIR / "backtest_results.parquet"


def backtest_metrics_path() -> Path:
    return _PLANT_ARTIFACTS_DIR / "backtest_metrics.json"


def eia_plants_path() -> Path:
    return INTERIM_DIR / "eia_nuclear_plants.parquet"


def labels_path() -> Path:
    return INTERIM_DIR / f"labels_{PLANT_SLUG}.parquet"


def weather_path() -> Path:
    return INTERIM_DIR / f"weather_{PLANT_SLUG}.parquet"


def water_path() -> Path:
    return INTERIM_DIR / f"water_{PLANT_SLUG}.parquet"


@lru_cache(maxsize=1)
def load_forecast() -> dict:
    p = forecast_path()
    if not p.exists():
        raise FileNotFoundError(
            f"missing {p}; run `just forecast` to refresh"
        )
    return json.loads(p.read_text())


@lru_cache(maxsize=1)
def load_attributions() -> dict:
    p = attributions_path()
    if not p.exists():
        raise FileNotFoundError(
            f"missing {p}; run `just forecast` to refresh"
        )
    return json.loads(p.read_text())


@lru_cache(maxsize=1)
def load_backtest_metrics() -> dict:
    p = backtest_metrics_path()
    if not p.exists():
        raise FileNotFoundError(
            f"missing {p}; run `just backtest` to refresh"
        )
    return json.loads(p.read_text())


@lru_cache(maxsize=1)
def load_eia_plants() -> list[dict]:
    """Return all nuclear plants from EIA-860 as plain dicts.

    Sorted by display name for stable map ordering. The route layer is
    responsible for stamping the canonical id (`eia_<plant_code>`) and
    overlaying any hand-curated entries (e.g. QC1 with operator/river
    detail EIA does not surface).
    """
    p = eia_plants_path()
    if not p.exists():
        raise FileNotFoundError(
            f"missing {p}; run `just features` to refresh"
        )
    import pandas as pd

    df = pd.read_parquet(p)
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


def load_recent_actuals(days: int) -> list[dict]:
    """Return the most recent N days of realized capacity factor.

    Outage and pre-outage rows are returned with `power_pct=None` so the
    chart can render a gap rather than a misleading 0%.
    """
    import pandas as pd

    p = labels_path()
    if not p.exists():
        raise FileNotFoundError(
            f"missing {p}; run `just ingest-labels` to refresh"
        )
    df = pd.read_parquet(p)
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


def load_recent_inputs(days: int) -> list[dict]:
    """Join the trailing N days of weather + water inputs for sparklines."""
    import pandas as pd

    wp = weather_path()
    rp = water_path()
    if not wp.exists() or not rp.exists():
        raise FileNotFoundError(
            "missing weather or water parquet; run `just features` to refresh"
        )
    weather = pd.read_parquet(wp)[["date", "air_temp_c_max"]]
    water = pd.read_parquet(rp)[["date", "water_temp_c", "streamflow_cfs"]]
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


def load_backtest_for_run_date(run_date: date) -> list[dict]:
    """Return all (horizon, prediction, actual) rows for a given run date."""
    import pandas as pd

    p = backtest_results_path()
    if not p.exists():
        raise FileNotFoundError(
            f"missing {p}; run `just backtest` to refresh"
        )
    df = pd.read_parquet(p)
    df["feature_date"] = pd.to_datetime(df["feature_date"]).dt.date
    df["target_date"] = pd.to_datetime(df["target_date"]).dt.date
    sub = df[df["feature_date"] == run_date]
    return sub.sort_values("horizon").to_dict(orient="records")


@lru_cache(maxsize=1)
def load_backtest_dates() -> list[date]:
    """Sorted unique run_dates available in the backtest parquet.

    Powers the replay slider's valid range. Cached because the parquet
    is rewritten only by `just backtest`, not at request time.
    """
    import pandas as pd

    p = backtest_results_path()
    if not p.exists():
        raise FileNotFoundError(
            f"missing {p}; run `just backtest` to refresh"
        )
    df = pd.read_parquet(p, columns=["feature_date"])
    dates = pd.to_datetime(df["feature_date"]).dt.date.unique().tolist()
    return sorted(dates)
