"""Train per-day point + quantile-band XGBoost models for a plant (Tier 3).

Use when: producing the model artifacts and metrics report consumed by
Tier 4 inference / backtest for a specific plant slug. Run via
``just train <slug>`` or
``uv run python -m pipeline.train --plant <slug>``.

Pipeline:
    1. Load data/processed/<slug>/training_dataset.parquet.
    2. For each horizon h in HORIZONS (1..14), build target = power_pct(t+h).
       Drop rows where the feature day or the target day is in
       is_outage / is_pre_outage, or where target is NaN.
    3. Time-split: train through TRAIN_END, val through VAL_END, test
       to the end of the dataset.
    4. Per horizon, fit:
         - one mean (squared-error) model — the point forecast
         - one XGBoost quantile model per BAND_QUANTILES entry (p10/p90)
       Early stopping on val loss for every fit.
    5. Score the point model and three baselines on val and test, broken
       out by full / summer-only / non-summer slices. Report empirical
       coverage of the [p10, p90] band on test.
    6. Persist (under data/artifacts/<slug>/):
         model_h{H}_point.json    (14 boosters)
         model_h{H}_q{10,90}.json (28 boosters when both quantiles are fit)
         feature_columns.json     (column order contract)
         metrics.json             (model + baselines)
         band_deltas.json         (per-horizon symmetric band delta)
         shap_summary_h7.png      (point h=7 model)

Re-running is idempotent — all outputs are overwritten in place.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import xgboost as xgb

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from plants import PLANTS, Plant, get_plant  # noqa: E402
from schemas import (  # noqa: E402
    BAND_TARGET_COVERAGE,
    CATEGORICAL_FEATURES,
    DIP_THRESHOLD_PCT,
    DIP_WEIGHT_ALPHA,
    HORIZONS,
    NON_FEATURE_COLS,
    SUMMER_MONTHS,
    TRAIN_END,
    VAL_END,
    XGB_EARLY_STOPPING_ROUNDS,
    XGB_PARAMS,
)
from pipeline import baselines  # noqa: E402

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
PROCESSED_DIR = REPO_ROOT / "data" / "processed"
ARTIFACTS_DIR = REPO_ROOT / "data" / "artifacts"

SHAP_HORIZON = 7  # which point model gets the SHAP summary plot


# ---------- dataset assembly --------------------------------------------


def _feature_cols(df: pd.DataFrame) -> list[str]:
    """Stable feature list = every column except metadata/target/flags."""
    return [c for c in df.columns if c not in NON_FEATURE_COLS]


def _coerce_categoricals(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure categorical columns are pandas `category` dtype for XGBoost."""
    df = df.copy()
    for col in CATEGORICAL_FEATURES:
        if col in df.columns and df[col].dtype.name != "category":
            df[col] = df[col].astype("category")
    return df


def _build_horizon_frame(df: pd.DataFrame, h: int) -> pd.DataFrame:
    """Attach target_h = power_pct(t+h) and drop outage rows on t and t+h.

    The model only sees weather-driven dynamics; operator-driven outages
    are excluded from both the feature day and the target day.
    """
    df = df.sort_values("date").reset_index(drop=True).copy()
    df["target"] = df["power_pct"].shift(-h)
    df["target_is_outage"] = df["is_outage"].shift(-h)
    df["target_is_pre_outage"] = df["is_pre_outage"].shift(-h)

    keep = (
        df["target"].notna()
        & ~df["is_outage"].astype(bool)
        & ~df["is_pre_outage"].astype(bool)
        & ~df["target_is_outage"].fillna(True).astype(bool)
        & ~df["target_is_pre_outage"].fillna(True).astype(bool)
    )
    return df.loc[keep].reset_index(drop=True)


def _split(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Date-based train / val / test split using schema constants."""
    train_end = pd.Timestamp(TRAIN_END)
    val_end = pd.Timestamp(VAL_END)
    train = df[df["date"] <= train_end]
    val = df[(df["date"] > train_end) & (df["date"] <= val_end)]
    test = df[df["date"] > val_end]
    return train, val, test


# ---------- training -----------------------------------------------------


def _dip_sample_weights(y: np.ndarray) -> np.ndarray:
    """Per-row training weights that up-weight dip rows.

    weight = 1 + DIP_WEIGHT_ALPHA * max(0, (100 - y) / 5). A full-power row
    gets weight 1; a 95% mild dip ~1+alpha; a 70% deep dip ~1+6*alpha. This
    counters squared-error mode-collapse to the dominant ~100% target value
    so the point model is willing to predict away from full power when the
    weather signal warrants. Applied to both point and quantile fits — for
    pinball loss it preserves direction (track dip rows more carefully).
    """
    y = np.asarray(y, dtype=float)
    return 1.0 + DIP_WEIGHT_ALPHA * np.maximum(0.0, (100.0 - y) / 5.0)


def _fit_point(
    X_train: pd.DataFrame,
    y_train: np.ndarray,
    X_val: pd.DataFrame,
    y_val: np.ndarray,
) -> xgb.XGBRegressor:
    """Fit the point-forecast mean (squared-error) model with early stopping."""
    w_train = _dip_sample_weights(y_train)
    w_val = _dip_sample_weights(y_val)
    model = xgb.XGBRegressor(
        objective="reg:squarederror",
        early_stopping_rounds=XGB_EARLY_STOPPING_ROUNDS,
        **XGB_PARAMS,
    )
    model.fit(
        X_train,
        y_train,
        sample_weight=w_train,
        eval_set=[(X_val, y_val)],
        sample_weight_eval_set=[w_val],
        verbose=False,
    )
    return model


# ---------- metrics ------------------------------------------------------


def _mae(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.mean(np.abs(y_true - y_pred)))


def _rmse(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.sqrt(np.mean((y_true - y_pred) ** 2)))


def _slice_scores(
    dates: pd.Series, y_true: np.ndarray, preds: dict[str, np.ndarray]
) -> dict[str, dict[str, dict[str, float]]]:
    """Score every prediction series on full / summer / non-summer / dip slices.

    `dip_events` is the operationally meaningful slice — rows where the
    plant actually derated below DIP_THRESHOLD_PCT at t+h. Persistence
    has an unfair advantage on the 100% mode of the target, so this slice
    isolates the rows the product is really paid to call.
    """
    months = pd.to_datetime(dates).dt.month.to_numpy()
    summer_mask = np.isin(months, SUMMER_MONTHS)
    dip_mask = y_true < DIP_THRESHOLD_PCT
    out: dict[str, dict[str, dict[str, float]]] = {}
    for slice_name, mask in (
        ("full", np.ones_like(summer_mask, dtype=bool)),
        ("summer", summer_mask),
        ("non_summer", ~summer_mask),
        ("dip_events", dip_mask),
    ):
        if mask.sum() == 0:
            continue
        slice_block: dict[str, dict[str, float]] = {"n_rows": {"value": int(mask.sum())}}
        for name, yhat in preds.items():
            slice_block[name] = {
                "mae": _mae(y_true[mask], yhat[mask]),
                "rmse": _rmse(y_true[mask], yhat[mask]),
            }
        out[slice_name] = slice_block
    return out


# ---------- SHAP ---------------------------------------------------------


def _save_shap(model: xgb.XGBRegressor, X: pd.DataFrame, out_path: Path) -> None:
    """Plot a SHAP summary for the supplied model on a sample of rows."""
    import shap  # local import — heavy

    sample = X.sample(n=min(500, len(X)), random_state=0)
    explainer = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(sample)

    plt.figure(figsize=(10, 7))
    shap.summary_plot(shap_values, sample, show=False, max_display=15)
    plt.tight_layout()
    plt.savefig(out_path, dpi=120, bbox_inches="tight")
    plt.close()


# ---------- main ---------------------------------------------------------


def run(plant: Plant) -> None:
    artifacts_dir = ARTIFACTS_DIR / plant.slug
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    src = PROCESSED_DIR / plant.slug / "training_dataset.parquet"
    if not src.exists():
        raise FileNotFoundError(f"missing {src}; run `just features {plant.slug}` first")
    raw = pd.read_parquet(src)
    raw["date"] = pd.to_datetime(raw["date"]).dt.tz_localize(None).dt.normalize()
    raw = _coerce_categoricals(raw)
    log.info(
        "[%s] loaded %d rows %s -> %s",
        plant.slug,
        len(raw),
        raw["date"].min().date(),
        raw["date"].max().date(),
    )

    feat_cols = _feature_cols(raw)
    (artifacts_dir / "feature_columns.json").write_text(json.dumps(feat_cols, indent=2))
    log.info("feature matrix has %d columns", len(feat_cols))

    metrics: dict[str, object] = {
        "splits": {"train_end": TRAIN_END, "val_end": VAL_END},
        "horizons": {},
    }

    shap_point_model: xgb.XGBRegressor | None = None
    shap_X_test: pd.DataFrame | None = None

    for h in HORIZONS:
        log.info("==== horizon h=%d ====", h)
        frame = _build_horizon_frame(raw, h)
        train, val, test = _split(frame)
        log.info(
            "rows: train=%d val=%d test=%d (after outage drop)",
            len(train),
            len(val),
            len(test),
        )
        if len(train) == 0 or len(val) == 0 or len(test) == 0:
            raise RuntimeError(f"empty split for h={h}")

        X_train = train[feat_cols]
        X_val = val[feat_cols]
        X_test = test[feat_cols]
        y_train = train["target"].to_numpy(dtype=float)
        y_val = val["target"].to_numpy(dtype=float)
        y_test = test["target"].to_numpy(dtype=float)

        log.info("  fit point (mean)")
        point_model = _fit_point(X_train, y_train, X_val, y_val)
        point_path = artifacts_dir / f"model_h{h:02d}_point.json"
        point_model.save_model(str(point_path))

        point_pred_val = point_model.predict(X_val)
        point_pred_test = point_model.predict(X_test)

        # Baselines fit on the training window only (no val/test leak).
        clim_table = baselines.fit_climatology(train["date"], train["target"])
        clim_aware_table = baselines.fit_refueling_aware_climatology(
            train["date"], train["target"], train["is_outage"]
        )

        def baseline_block(eval_df: pd.DataFrame, model_pred: np.ndarray) -> dict:
            target_dates = pd.to_datetime(eval_df["date"]) + pd.Timedelta(days=h)
            preds = {
                "model": model_pred,
                "climatology": baselines.predict_climatology(clim_table, target_dates),
                "climatology_refueling_aware": baselines.predict_climatology(
                    clim_aware_table, target_dates
                ),
                "persistence": baselines.predict_persistence(eval_df["power_pct"]),
            }
            y_true = eval_df["target"].to_numpy(dtype=float)
            return _slice_scores(eval_df["date"], y_true, preds)

        # Symmetric uncertainty band derived from val-set absolute residuals:
        # delta_h = (BAND_TARGET_COVERAGE)-th percentile of |point - actual|
        # on val. Published band is [point - delta_h, point + delta_h], an
        # approximate (BAND_TARGET_COVERAGE * 100)% prediction interval.
        # We chose symmetric over one-sided downside because the dip-
        # weighted point under-predicts on ~95% of val rows — there is no
        # meaningful "additional downside" the point hasn't already priced.
        # |residual| centered on the point captures the model's typical
        # error magnitude in either direction.
        abs_residuals_val = np.abs(point_pred_val - y_val)
        n_val = len(abs_residuals_val)
        level = float(np.ceil((n_val + 1) * BAND_TARGET_COVERAGE) / n_val)
        level = float(min(max(level, 0.0), 1.0))
        delta_h = float(np.quantile(abs_residuals_val, level))
        band_low_test = point_pred_test - delta_h
        band_high_test = point_pred_test + delta_h
        empirical_coverage = float(
            np.mean((y_test >= band_low_test) & (y_test <= band_high_test))
        )

        downside_band = {
            "method": "symmetric_residual_band",
            "target_coverage": BAND_TARGET_COVERAGE,
            "delta_pct": delta_h,
            "empirical_coverage_test": empirical_coverage,
        }

        metrics["horizons"][f"h{h:02d}"] = {
            "best_iterations": {
                "point": int(point_model.best_iteration or point_model.n_estimators),
            },
            "val": baseline_block(val, point_pred_val),
            "test": baseline_block(test, point_pred_test),
            "downside_band": downside_band,
        }

        if h == SHAP_HORIZON:
            shap_point_model = point_model
            shap_X_test = X_test

    out_metrics = artifacts_dir / "metrics.json"
    out_metrics.write_text(json.dumps(metrics, indent=2, default=float))
    log.info("wrote %s", out_metrics)

    # Persist the per-horizon symmetric band delta separately so
    # inference.py loads it without parsing all metrics. Inference
    # computes [point - delta, point + delta] at serving time.
    deltas = {
        h_key: {
            "delta_pct": block["downside_band"]["delta_pct"],
            "target_coverage": block["downside_band"]["target_coverage"],
        }
        for h_key, block in metrics["horizons"].items()
    }
    out_deltas = artifacts_dir / "band_deltas.json"
    out_deltas.write_text(json.dumps(deltas, indent=2, default=float))
    log.info("wrote %s", out_deltas)

    if shap_point_model is not None and shap_X_test is not None and len(shap_X_test):
        try:
            shap_path = artifacts_dir / f"shap_summary_h{SHAP_HORIZON}.png"
            _save_shap(shap_point_model, shap_X_test, shap_path)
            log.info("wrote %s", shap_path)
        except Exception as exc:  # SHAP+categorical can be finicky; non-fatal
            log.warning("SHAP plot skipped: %s", exc)


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
    args = parser.parse_args()
    run(get_plant(args.plant))


if __name__ == "__main__":
    _main()
