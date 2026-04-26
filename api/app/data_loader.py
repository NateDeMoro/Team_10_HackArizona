"""Read precomputed forecast/backtest artifacts from data/artifacts.

The api/ container does not invoke the ML pipeline at request time. The
demo flow is: `just forecast` (refreshes data/artifacts/forecast_latest.json)
and `just backtest` (refreshes data/artifacts/backtest_results.parquet)
on the operator's machine, then the api serves the cached artifacts.
This keeps the api container free of Open-Meteo secrets, XGBoost, and
pandas-driven feature pipelines at request time.
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


def forecast_path() -> Path:
    return ARTIFACTS_DIR / "forecast_latest.json"


def backtest_results_path() -> Path:
    return ARTIFACTS_DIR / "backtest_results.parquet"


def backtest_metrics_path() -> Path:
    return ARTIFACTS_DIR / "backtest_metrics.json"


@lru_cache(maxsize=1)
def load_forecast() -> dict:
    p = forecast_path()
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


def load_backtest_for_run_date(run_date: date) -> list[dict]:
    """Return all (horizon, prediction, actual) rows for a given run date.

    Reads the per-row backtest parquet with a lightweight pandas import
    only when called — keeps the cold start cheap when callers only need
    the forecast endpoint.
    """
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
