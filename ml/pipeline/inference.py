"""Forecast for a given run date — live or historical (Tier 4).

Use when: producing a 14-day forecast at a specific anchor date, either
for the live demo (`run_date == today`) or for the backtest replay (any
historical date in the test span). Run via `just forecast` to refresh
the precomputed JSON the API serves, or import `forecast(...)` directly
from a backtest driver.

Architecture note: the trained per-horizon models consume features only
at the *run date* (and lags/rolling backwards). They do not consume
NWP-forecast values for t+1..t+14 as inputs. So inference at a given
run_date reduces to: build one feature row at that date, push it through
all 14 point boosters, derive the symmetric uncertainty band as
[point - delta_h, point + delta_h] where delta_h is the per-horizon
80th-percentile of |val residuals| persisted at train time.

The day-of feature values come from cached parquet built by the Tier 2
pipeline. For run_date >= 2016 the source is tagged "historical_nwp" —
ERA5 archive values for day-0 are within ~0.5C of the matching NWP day-0
forecast for QC1, so for our architecture they are operationally
equivalent. For run_date < 2016 (pre-NWP archive) the source is tagged
"era5_fallback" to make the hindsight caveat explicit. For run_date >=
today the source is "live"; the caller is expected to have refreshed
the feature cache via `just features` before calling.

Reads:
    data/processed/training_dataset.parquet
    data/artifacts/feature_columns.json
    data/artifacts/band_deltas.json
    data/artifacts/model_h{H}_point.json
Writes (when invoked from CLI):
    data/artifacts/forecast_latest.json       (precomputed response for the API)
    data/artifacts/attributions_latest.json   (per-horizon SHAP top features)
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from plants import get_plant  # noqa: E402
from schemas import (  # noqa: E402
    CATEGORICAL_FEATURES,
    DIP_THRESHOLD_PCT,
    AlertLevel,
    AttributionsResponse,
    FeatureContribution,
    ForecastResponse,
    ForecastSource,
    HISTORICAL_NWP_MIN_DATE,
    HORIZONS,
    HorizonAttribution,
    HorizonPrediction,
    UI_ALERT_THRESHOLD_PCT,
)

# Number of top SHAP-contribution features surfaced per horizon. The UI
# renders the top 5 by default but we serialize 10 so a future drill-down
# can show more without a fresh `just forecast` run.
ATTRIBUTION_TOP_N = 10

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
PROCESSED_DIR = REPO_ROOT / "data" / "processed"
ARTIFACTS_DIR = REPO_ROOT / "data" / "artifacts"

# v1 inference is single-plant: the live JSON the API serves comes from
# this slug. Multi-plant API integration is a separate task; the training
# pipeline already supports any registered plant slug.
PLANT_QC1 = "quad_cities_1"
_PLANT = get_plant(PLANT_QC1)
_PLANT_PROCESSED_DIR = PROCESSED_DIR / _PLANT.slug
_PLANT_ARTIFACTS_DIR = ARTIFACTS_DIR / _PLANT.slug


def _load_features() -> pd.DataFrame:
    src = _PLANT_PROCESSED_DIR / "training_dataset.parquet"
    if not src.exists():
        raise FileNotFoundError(
            f"missing {src}; run `just features {PLANT_QC1}` to refresh the cache"
        )
    df = pd.read_parquet(src)
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None).dt.normalize()
    for col in CATEGORICAL_FEATURES:
        if col in df.columns and df[col].dtype.name != "category":
            df[col] = df[col].astype("category")
    return df


def _load_feature_columns() -> list[str]:
    p = _PLANT_ARTIFACTS_DIR / "feature_columns.json"
    return json.loads(p.read_text())


def _load_band_deltas() -> dict[str, dict[str, float]]:
    p = _PLANT_ARTIFACTS_DIR / "band_deltas.json"
    return json.loads(p.read_text())


def _load_booster(path: Path) -> xgb.XGBRegressor:
    m = xgb.XGBRegressor()
    m.load_model(str(path))
    return m


def _classify_alert_level(point_pct: float) -> AlertLevel:
    """Map a point prediction to a UI badge tier.

    Two thresholds: DIP_THRESHOLD_PCT (95) is the watch boundary,
    UI_ALERT_THRESHOLD_PCT (90) is the red-alert boundary. Driven by point
    only — the published symmetric band is shown on the chart visually
    but does not change the badge.
    """
    if point_pct < UI_ALERT_THRESHOLD_PCT:
        return "alert"
    if point_pct < DIP_THRESHOLD_PCT:
        return "watch"
    return "operational"


def _classify_source(run_date: date) -> ForecastSource:
    """Tag the source based on run_date relative to NWP coverage and today.

    See module docstring for the equivalence argument: ERA5 day-0 ≈ NWP
    day-0 for QC1 in our architecture, so cached ERA5 values for run_date
    >= 2016 are tagged "historical_nwp". The hindsight caveat is real for
    pre-2016 dates so those are tagged "era5_fallback".
    """
    today = datetime.now(UTC).date()
    if run_date >= today:
        return "live"
    nwp_min = datetime.fromisoformat(HISTORICAL_NWP_MIN_DATE).date()
    if run_date >= nwp_min:
        return "historical_nwp"
    return "era5_fallback"


def forecast(plant_id: str, run_date: date) -> ForecastResponse:
    """Produce a 14-day forecast anchored at run_date.

    Raises FileNotFoundError if the feature cache is missing the run_date
    row — caller should run `just features` first.
    """
    if plant_id != PLANT_QC1:
        raise ValueError(f"only {PLANT_QC1!r} is supported in v1; got {plant_id!r}")

    feat_cols = _load_feature_columns()
    deltas = _load_band_deltas()
    df = _load_features()

    run_ts = pd.Timestamp(run_date)
    row_mask = df["date"] == run_ts
    if not row_mask.any():
        avail_max = df["date"].max().date()
        raise LookupError(
            f"no feature row for run_date={run_date}; cache covers up to "
            f"{avail_max}. Run `just features` to refresh."
        )

    X_run = df.loc[row_mask, feat_cols].iloc[[0]].copy()

    horizons: list[HorizonPrediction] = []
    for h in HORIZONS:
        point_path = _PLANT_ARTIFACTS_DIR / f"model_h{h:02d}_point.json"
        if not point_path.exists():
            raise FileNotFoundError(
                f"missing model artifact for h={h}; run `just train {PLANT_QC1}` first"
            )
        point_model = _load_booster(point_path)
        point_pred = float(point_model.predict(X_run)[0])

        # Symmetric uncertainty band: [point - delta_h, point + delta_h].
        # delta_h is the per-horizon 80th-percentile of |val residuals|.
        h_key = f"h{h:02d}"
        delta_h = float(deltas[h_key]["delta_pct"])

        point_clamped = float(np.clip(point_pred, 0.0, 100.0))
        band_low = float(np.clip(point_clamped - delta_h, 0.0, 100.0))
        band_high = float(np.clip(point_clamped + delta_h, 0.0, 100.0))

        alert_level: AlertLevel = _classify_alert_level(point_clamped)

        horizons.append(
            HorizonPrediction(
                horizon_days=h,
                target_date=(run_ts + pd.Timedelta(days=h)).date(),
                point_pct=point_clamped,
                band_low_pct=band_low,
                band_high_pct=band_high,
                alert_level=alert_level,
            )
        )

    return ForecastResponse(
        plant_id=plant_id,
        run_date=run_date,
        source=_classify_source(run_date),
        horizons=horizons,
    )


def attributions(plant_id: str, run_date: date) -> AttributionsResponse:
    """Per-horizon SHAP attributions for the run_date feature row.

    Uses XGBoost's built-in tree SHAP via `pred_contribs=True` — exact
    decomposition, no external `shap` dependency. Each horizon model is
    decomposed separately because they were trained on the same feature
    matrix but learn different (target -> feature) relationships.

    Returns the top-N features by absolute contribution per horizon, in
    capacity-factor percentage points. baseline + sum(all contributions)
    equals the unclamped point prediction; the top-N subset is what the
    UI renders, so the running sum may not exactly match point_pct.
    """
    if plant_id != PLANT_QC1:
        raise ValueError(f"only {PLANT_QC1!r} is supported in v1; got {plant_id!r}")

    feat_cols = _load_feature_columns()
    df = _load_features()

    run_ts = pd.Timestamp(run_date)
    row_mask = df["date"] == run_ts
    if not row_mask.any():
        avail_max = df["date"].max().date()
        raise LookupError(
            f"no feature row for run_date={run_date}; cache covers up to "
            f"{avail_max}. Run `just features` to refresh."
        )

    X_run = df.loc[row_mask, feat_cols].iloc[[0]].copy()
    # Capture raw values for surfacing alongside contributions. Categorical
    # features serialize as None — the UI does not need to render their
    # internal codes.
    raw_values: dict[str, float | None] = {}
    for col in feat_cols:
        v = X_run[col].iloc[0]
        if pd.isna(v) or X_run[col].dtype.name == "category":
            raw_values[col] = None
        else:
            raw_values[col] = float(v)

    horizons: list[HorizonAttribution] = []
    dmat = xgb.DMatrix(X_run, enable_categorical=True)
    for h in HORIZONS:
        point_path = _PLANT_ARTIFACTS_DIR / f"model_h{h:02d}_point.json"
        if not point_path.exists():
            raise FileNotFoundError(
                f"missing model artifact for h={h}; run `just train {PLANT_QC1}` first"
            )
        booster = _load_booster(point_path).get_booster()
        # contribs shape: (1, n_features + 1); last column is the bias.
        contribs = booster.predict(dmat, pred_contribs=True)[0]
        baseline = float(contribs[-1])
        feat_contribs = contribs[:-1]
        # Rank features by absolute contribution; emit signed value so the
        # UI can color positive (push up) vs negative (push down) bars.
        order = np.argsort(np.abs(feat_contribs))[::-1][:ATTRIBUTION_TOP_N]
        top: list[FeatureContribution] = []
        for idx in order:
            name = feat_cols[idx]
            top.append(
                FeatureContribution(
                    feature=name,
                    value=raw_values.get(name),
                    contribution_pct=float(feat_contribs[idx]),
                )
            )
        # Reconstruct the unclamped point prediction so the UI can show
        # baseline -> point delta and warn if the top-N covers a small
        # share of the total movement.
        point_unclamped = float(baseline + feat_contribs.sum())
        horizons.append(
            HorizonAttribution(
                horizon_days=h,
                baseline_pct=baseline,
                point_pct=point_unclamped,
                top_features=top,
            )
        )

    return AttributionsResponse(
        plant_id=plant_id,
        run_date=run_date,
        horizons=horizons,
    )


def _latest_complete_run_date(df: pd.DataFrame) -> date:
    """Most recent date for which the day-of weather features are populated.

    Open-Meteo's ERA5 archive lags real time by ~5-7 days, so the last few
    cached rows have NaN for `air_temp_c_max`. Inferring on those produces
    nonsense (the model is given a row with most weather features missing).
    For live demo use, anchor at the latest date that has a real same-day
    weather observation — features.py will always populate air_temp_c_max
    when the underlying ingest succeeded.
    """
    if "air_temp_c_max" not in df.columns:
        return df["date"].max().date()
    populated = df.loc[df["air_temp_c_max"].notna(), "date"]
    if len(populated) == 0:
        return df["date"].max().date()
    return populated.max().date()


def run() -> None:
    """CLI entrypoint: precompute today's forecast and persist as JSON.

    Tier 4 serving model: this writes data/artifacts/forecast_latest.json
    which the FastAPI route reads and returns. `just forecast` regenerates
    it manually before demo time so the api/ container needs no Open-Meteo
    secrets at request time.
    """
    today = datetime.now(UTC).date()
    df = _load_features()
    run_date = _latest_complete_run_date(df)
    if run_date < today:
        log.warning(
            "ERA5 archive lag: anchoring run_date at %s (today=%s). Run "
            "`just features` to refresh — current-day air temp lands a "
            "few days behind real time.",
            run_date,
            today,
        )

    resp = forecast(PLANT_QC1, run_date)
    out = _PLANT_ARTIFACTS_DIR / "forecast_latest.json"
    out.write_text(resp.model_dump_json(indent=2))
    log.info("wrote %s (run_date=%s, source=%s)", out, run_date, resp.source)

    attr = attributions(PLANT_QC1, run_date)
    attr_out = _PLANT_ARTIFACTS_DIR / "attributions_latest.json"
    attr_out.write_text(attr.model_dump_json(indent=2))
    log.info("wrote %s (run_date=%s)", attr_out, run_date)


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
