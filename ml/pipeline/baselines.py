"""Reference baselines for the Tier 3 model evaluation.

Use when: producing the floor that the XGBoost models must beat in
metrics.json. Three baselines are exposed, each as a fit/predict pair
operating on the same row-aligned arrays the model uses:

    climatology(train)              -> day-of-year mean of power_pct
    persistence()                   -> y_hat(t+h) = power_pct(t)
    refueling_aware_climatology(...) -> climatology over non-outage rows

`refueling_aware_climatology` is what the plan refers to as the
"refueling-aware" baseline; since our training filter already drops
outage / pre-outage rows it collapses to "climatology of operating
days" — the honest comparison for the model's learned target.

All baselines return numpy float arrays the same length as the supplied
evaluation index. Rows whose target is NaN must be filtered by the
caller before scoring.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)


def _doy(dates: pd.Series) -> np.ndarray:
    """Day-of-year, 1-366. Used as the climatology lookup key."""
    return pd.to_datetime(dates).dt.dayofyear.to_numpy()


def fit_climatology(train_dates: pd.Series, train_power: pd.Series) -> dict[int, float]:
    """Return {doy -> mean(power_pct)} computed on the training window.

    Missing day-of-year keys (e.g. leap day if absent) fall back to the
    overall train mean at predict time.
    """
    df = pd.DataFrame({"doy": _doy(train_dates), "y": train_power.to_numpy()})
    df = df.dropna(subset=["y"])
    means = df.groupby("doy")["y"].mean().to_dict()
    overall = float(df["y"].mean())
    means["__overall__"] = overall  # sentinel for unseen doy
    return means


def predict_climatology(
    table: dict[int, float], target_dates: pd.Series
) -> np.ndarray:
    """Look up climatology mean for each target date.

    `target_dates` is the *date the prediction is for* (i.e. t+h), not the
    feature row date. Falls back to the overall train mean for any doy
    that wasn't seen in training.
    """
    overall = table["__overall__"]
    doys = _doy(target_dates)
    return np.array([table.get(int(d), overall) for d in doys], dtype=float)


def predict_persistence(current_power: pd.Series) -> np.ndarray:
    """Trivially y_hat(t+h) = power_pct(t). Same array regardless of horizon.

    `current_power` must align row-by-row with the eval index — i.e. it is
    power_pct *at the feature row's date*, not at the target date.
    """
    return current_power.to_numpy(dtype=float)


def fit_refueling_aware_climatology(
    train_dates: pd.Series,
    train_power: pd.Series,
    train_is_outage: pd.Series,
) -> dict[int, float]:
    """Climatology computed only over non-outage training rows.

    Identical math to `fit_climatology` after the outage rows are
    dropped — exposed as a separate function so the metrics report can
    label the baseline correctly. With the Tier 3 training filter that
    already excludes is_outage/is_pre_outage rows, this typically lands
    very close to the plain climatology; reported for transparency.
    """
    mask = ~train_is_outage.astype(bool).to_numpy()
    return fit_climatology(train_dates[mask], train_power[mask])
