"""Dip-focused backtest of the Tier 3 models on the held-out test split.

Use when: producing a dip-skill report on real held-out data (2023+),
or comparing q10 vs q25 downside band candidates. Run via `just backtest`
or `uv run python -m pipeline.backtest`.

Scope: this version evaluates against ERA5 actuals on the test split. The
"as-if-standing-on" historical-NWP backtest (Tier 4 plan) — pulling
archived forecast runs from Open-Meteo for 2012-07-15, 2018-07-01,
2021-08-01, 2022-07-15, 2023-08-15 and comparing to realized power — is
the next step.

Why dip-focused: the product's value prop is calling derating events.
Full-slice MAE is dominated by the ~95% of operating-day rows at full
power and is misleading as a headline metric. This report leads with
dip MAE, dip-detection precision/recall at the DIP_THRESHOLD_PCT
boundary, and per-horizon skill vs baselines on the dip slice.

Reads:
    data/processed/training_dataset.parquet
    data/artifacts/model_h{H}_point.json
    data/artifacts/model_h{H}_q{10,25}.json
Writes:
    data/artifacts/backtest_results.parquet  (per-row predictions)
    data/artifacts/backtest_report.md        (human-readable summary)
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from plants import PLANTS, Plant, get_plant  # noqa: E402
from schemas import (  # noqa: E402
    CATEGORICAL_FEATURES,
    DIP_THRESHOLD_PCT,
    HISTORICAL_BACKTEST_DATES,
    HISTORICAL_NWP_MIN_DATE,
    HORIZONS,
    NON_FEATURE_COLS,
    SUMMER_MONTHS,
    TRAIN_END,
    VAL_END,
)
from pipeline import baselines, inference  # noqa: E402

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[1]  # ml/ (data lives at ml/data/)
PROCESSED_DIR = REPO_ROOT / "data" / "processed"
ARTIFACTS_DIR = REPO_ROOT / "data" / "artifacts"


def _feature_cols(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if c not in NON_FEATURE_COLS]


def _coerce_categoricals(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for col in CATEGORICAL_FEATURES:
        if col in df.columns and df[col].dtype.name != "category":
            df[col] = df[col].astype("category")
    return df


def _build_horizon_frame(df: pd.DataFrame, h: int) -> pd.DataFrame:
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
    train_end = pd.Timestamp(TRAIN_END)
    val_end = pd.Timestamp(VAL_END)
    train = df[df["date"] <= train_end]
    val = df[(df["date"] > train_end) & (df["date"] <= val_end)]
    test = df[df["date"] > val_end]
    return train, val, test


def _load_booster(path: Path) -> xgb.XGBRegressor:
    model = xgb.XGBRegressor()
    model.load_model(str(path))
    return model


def _mae(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.mean(np.abs(y_true - y_pred)))


def _detection_metrics(
    y_true: np.ndarray, y_pred: np.ndarray, threshold: float
) -> dict[str, float]:
    """Treat dip detection as binary: actual<threshold vs predicted<threshold.

    Reports precision, recall, and F1 of the model's "this is a dip" call
    at the supplied threshold. The point of the product is to fire a
    correct alarm when a dip is coming, not minimize regression MAE.
    """
    actual = y_true < threshold
    predicted = y_pred < threshold
    tp = int(np.sum(actual & predicted))
    fp = int(np.sum(~actual & predicted))
    fn = int(np.sum(actual & ~predicted))
    tn = int(np.sum(~actual & ~predicted))
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


# ---------- main ---------------------------------------------------------


def run(plant_id: str) -> None:
    if plant_id not in PLANTS:
        raise ValueError(f"unknown plant_id={plant_id!r}; known: {sorted(PLANTS)}")
    plant_processed_dir = PROCESSED_DIR / plant_id
    plant_artifacts_dir = ARTIFACTS_DIR / plant_id

    src = plant_processed_dir / "training_dataset.parquet"
    if not src.exists():
        raise FileNotFoundError(f"missing {src}; run `just features {plant_id}` first")
    raw = pd.read_parquet(src)
    raw["date"] = pd.to_datetime(raw["date"]).dt.tz_localize(None).dt.normalize()
    raw = _coerce_categoricals(raw)

    feat_cols = _feature_cols(raw)
    deltas = inference._load_band_deltas(plant_id)  # noqa: SLF001 — internal-use helper

    rows: list[dict] = []
    horizon_blocks: dict[str, dict] = {}

    for h in HORIZONS:
        log.info("scoring horizon h=%d", h)
        frame = _build_horizon_frame(raw, h)
        train, _val, test = _split(frame)
        if len(test) == 0 or len(train) == 0:
            raise RuntimeError(f"empty test or train split for h={h}")

        X_test = test[feat_cols]
        y_test = test["target"].to_numpy(dtype=float)
        target_dates = pd.to_datetime(test["date"]) + pd.Timedelta(days=h)

        point = _load_booster(plant_artifacts_dir / f"model_h{h:02d}_point.json")
        cal_path = plant_artifacts_dir / f"calibrator_h{h:02d}.json"
        if not cal_path.exists():
            raise FileNotFoundError(
                f"missing calibrator for h={h}; run `just train {plant_id}` first"
            )
        calibrator = inference._load_calibrator(cal_path)  # noqa: SLF001
        raw_pred = point.predict(X_test)
        point_pred = inference._apply_calibrator(raw_pred, calibrator)  # noqa: SLF001
        delta_h = float(deltas[f"h{h:02d}"]["delta_pct"])
        band_low_pred = np.clip(point_pred - delta_h, 0.0, 100.0)
        band_high_pred = np.clip(point_pred + delta_h, 0.0, 100.0)

        # Baselines fit on train only, predicted at target_dates.
        clim_table = baselines.fit_climatology(train["date"], train["target"])
        pred_clim = baselines.predict_climatology(clim_table, target_dates)
        pred_persist = baselines.predict_persistence(test["power_pct"])

        # Per-row predictions go to parquet for downstream use (the UI
        # replay slider in Tier 5 reads this).
        for i, idx in enumerate(test.index):
            rows.append(
                {
                    "horizon": h,
                    "feature_date": test.loc[idx, "date"],
                    "target_date": target_dates.iloc[i],
                    "actual": float(y_test[i]),
                    "point": float(point_pred[i]),
                    "band_low": float(band_low_pred[i]),
                    "band_high": float(band_high_pred[i]),
                    "clim": float(pred_clim[i]),
                    "persist": float(pred_persist[i]),
                }
            )

        # Dip slice = rows where actual < threshold. This is what the
        # model is paid to call.
        dip_mask = y_test < DIP_THRESHOLD_PCT
        months = pd.to_datetime(test["date"]).dt.month.to_numpy()
        summer_mask = np.isin(months, SUMMER_MONTHS)
        summer_dip_mask = dip_mask & summer_mask

        block: dict[str, object] = {
            "n_test_rows": int(len(y_test)),
            "n_dip_rows": int(dip_mask.sum()),
            "n_summer_dip_rows": int(summer_dip_mask.sum()),
        }
        for slice_name, mask in (
            ("dip_events", dip_mask),
            ("summer_dip_events", summer_dip_mask),
        ):
            if mask.sum() == 0:
                block[slice_name] = None
                continue
            block[slice_name] = {
                "n": int(mask.sum()),
                "model_mae": _mae(y_test[mask], point_pred[mask]),
                "clim_mae": _mae(y_test[mask], pred_clim[mask]),
                "persist_mae": _mae(y_test[mask], pred_persist[mask]),
            }

        # Detection metrics on the full test split — precision/recall of
        # "predict dip" calls. Computed against the point and against the
        # band's lower edge (band_low fires more often than point at any
        # given threshold; sensitivity/specificity trade-off).
        block["detection"] = {
            "point": _detection_metrics(y_test, point_pred, DIP_THRESHOLD_PCT),
            "band_low": _detection_metrics(y_test, band_low_pred, DIP_THRESHOLD_PCT),
        }

        # Symmetric-band sanity: empirical coverage of [band_low, band_high]
        # on test. Should approach BAND_TARGET_COVERAGE (0.80).
        block["band"] = {
            "method": "symmetric_residual_band",
            "delta_pct": delta_h,
            "empirical_coverage": float(
                np.mean((y_test >= band_low_pred) & (y_test <= band_high_pred))
            ),
        }

        horizon_blocks[f"h{h:02d}"] = block

    # Write per-row predictions for the UI/replay layer.
    results_df = pd.DataFrame(rows)
    results_path = plant_artifacts_dir / "backtest_results.parquet"
    results_df.to_parquet(results_path, index=False)
    log.info("wrote %s (%d rows)", results_path, len(results_df))

    # Run the 5 named historical dates through inference.forecast() — this
    # exercises the conformal-calibrated q10 + q10<=point clamp the API
    # actually serves, and compares to realized power for the following 14
    # days. These are the demo highlights.
    highlights = _historical_highlights(plant_id, raw)

    # Write the human-readable report.
    plant = get_plant(plant_id)
    report = _format_report(plant, horizon_blocks, highlights)
    report_path = plant_artifacts_dir / "backtest_report.md"
    report_path.write_text(report)
    log.info("wrote %s", report_path)

    # Also stash the structured block alongside metrics.json for tooling.
    backtest_json_path = plant_artifacts_dir / "backtest_metrics.json"
    backtest_json_path.write_text(
        json.dumps(
            {"horizons": horizon_blocks, "historical_highlights": highlights},
            indent=2,
            default=float,
        )
    )
    log.info("wrote %s", backtest_json_path)


def _historical_highlights(plant_id: str, raw: pd.DataFrame) -> list[dict]:
    """Run forecast() on the named historical dates, compare to realized.

    Each entry is one (run_date, [horizons]) record with realized power
    at run_date+h for the 14 horizons that follow. ERA5-fallback dates
    (run_date < 2016) are tagged so the report can footnote the
    hindsight caveat.
    """
    label_map = (
        raw.set_index("date")["power_pct"].to_dict()
    )
    nwp_min = pd.Timestamp(HISTORICAL_NWP_MIN_DATE).date()
    out: list[dict] = []
    for d_str in HISTORICAL_BACKTEST_DATES:
        run_date = pd.Timestamp(d_str).date()
        try:
            resp = inference.forecast(plant_id, run_date)
        except LookupError as exc:
            log.warning("skipping %s: %s", d_str, exc)
            continue
        rows = []
        for hp in resp.horizons:
            actual = label_map.get(pd.Timestamp(hp.target_date), None)
            rows.append(
                {
                    "horizon_days": hp.horizon_days,
                    "target_date": hp.target_date.isoformat(),
                    "actual_pct": float(actual) if actual is not None else None,
                    "point_pct": hp.point_pct,
                    "band_low_pct": hp.band_low_pct,
                    "band_high_pct": hp.band_high_pct,
                    "alert_level": hp.alert_level,
                }
            )
        out.append(
            {
                "run_date": run_date.isoformat(),
                "source": resp.source,
                "is_pre_nwp": run_date < nwp_min,
                "rows": rows,
            }
        )
    return out


def _format_report(
    plant: Plant, blocks: dict[str, dict], highlights: list[dict] | None = None
) -> str:
    """Compose the dip-focused markdown report."""
    lines: list[str] = []
    lines.append(f"# Backtest report — {plant.display_name}, dip-focused")
    lines.append("")
    lines.append(
        f"Held-out test split (>{VAL_END}). Dip threshold: <{DIP_THRESHOLD_PCT}% "
        "of full power."
    )
    lines.append("")
    lines.append("## Dip-event MAE (model vs baselines)")
    lines.append("")
    lines.append("| h | n | model | clim | persist | beat clim? | beat pers? |")
    lines.append("|---|---|------:|-----:|--------:|:----------:|:----------:|")
    for h_key, block in blocks.items():
        de = block.get("dip_events")
        if not de:
            continue
        m, c, p = de["model_mae"], de["clim_mae"], de["persist_mae"]
        win_c = "✓" if m < c else "✗"
        win_p = "✓" if m < p else "✗"
        lines.append(
            f"| {h_key} | {de['n']} | {m:.2f} | {c:.2f} | {p:.2f} | {win_c} | {win_p} |"
        )
    lines.append("")
    lines.append("## Summer dip-event MAE")
    lines.append("")
    lines.append("| h | n | model | clim | persist |")
    lines.append("|---|---|------:|-----:|--------:|")
    for h_key, block in blocks.items():
        sde = block.get("summer_dip_events")
        if not sde:
            lines.append(f"| {h_key} | 0 | — | — | — |")
            continue
        lines.append(
            f"| {h_key} | {sde['n']} | {sde['model_mae']:.2f} | "
            f"{sde['clim_mae']:.2f} | {sde['persist_mae']:.2f} |"
        )
    lines.append("")
    lines.append(
        f"## Dip detection (point model, threshold <{DIP_THRESHOLD_PCT}%)"
    )
    lines.append("")
    lines.append("| h | tp | fp | fn | precision | recall | f1 |")
    lines.append("|---|----|----|----|----------:|-------:|---:|")
    for h_key, block in blocks.items():
        d = block["detection"]["point"]
        lines.append(
            f"| {h_key} | {d['tp']} | {d['fp']} | {d['fn']} | "
            f"{d['precision']:.2f} | {d['recall']:.2f} | {d['f1']:.2f} |"
        )
    lines.append("")
    lines.append(
        f"## Band-low alarm detection (band_low < {DIP_THRESHOLD_PCT}%)"
    )
    lines.append("")
    lines.append(
        "More-sensitive alarm: fires whenever the band's lower edge crosses "
        f"{DIP_THRESHOLD_PCT}%. Higher recall than the point alarm at the "
        "cost of more false positives — useful as a 'might-want-to-look' "
        "signal vs the point alarm's 'we-think-this-will-happen'."
    )
    lines.append("")
    lines.append("| h | tp | fp | fn | precision | recall | f1 |")
    lines.append("|---|----|----|----|----------:|-------:|---:|")
    for h_key, block in blocks.items():
        d = block["detection"]["band_low"]
        lines.append(
            f"| {h_key} | {d['tp']} | {d['fp']} | {d['fn']} | "
            f"{d['precision']:.2f} | {d['recall']:.2f} | {d['f1']:.2f} |"
        )
    lines.append("")
    lines.append("## Symmetric-band coverage (sanity)")
    lines.append("")
    lines.append(
        "Band = [point - delta_h, point + delta_h] where delta_h is the "
        "80th-percentile of |val residuals|. For a calibrated band the "
        "empirical coverage on test should approach the target (0.80)."
    )
    lines.append("")
    lines.append("| h | delta | empirical coverage |")
    lines.append("|---|------:|-------------------:|")
    for h_key, block in blocks.items():
        sub = block["band"]
        lines.append(
            f"| {h_key} | {sub['delta_pct']:.2f} | "
            f"{sub['empirical_coverage']:.2f} |"
        )
    lines.append("")

    if highlights:
        lines.append("## Historical highlights — as-if-standing-on each named date")
        lines.append("")
        lines.append(
            "Predictions below come from `inference.forecast()` — the same "
            "code path the live API serves, with [low, high] = point ± "
            "delta_h (symmetric residual band, target ~80% coverage). "
            "`actual` is the realized NRC capacity factor on the target "
            "date (null if the day was filtered as outage / pre-outage)."
        )
        lines.append("")
        for entry in highlights:
            label = entry["run_date"]
            tag = entry["source"]
            footnote = ""
            if entry.get("is_pre_nwp"):
                footnote = (
                    " — *ERA5 fallback (pre-2016 NWP archive coverage); "
                    "day-of features are observed truth, not forecast*"
                )
            lines.append(f"### {label} (source: `{tag}`){footnote}")
            lines.append("")
            lines.append("| h | target | actual | point | low | high | level |")
            lines.append("|---|--------|-------:|------:|----:|-----:|:-----:|")
            for r in entry["rows"]:
                actual_s = (
                    f"{r['actual_pct']:.1f}"
                    if r["actual_pct"] is not None
                    else "—"
                )
                lines.append(
                    f"| {r['horizon_days']} | {r['target_date']} | "
                    f"{actual_s} | {r['point_pct']:.2f} | "
                    f"{r['band_low_pct']:.2f} | {r['band_high_pct']:.2f} | "
                    f"{r['alert_level']} |"
                )
            lines.append("")
    return "\n".join(lines)


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
    run(args.plant)


if __name__ == "__main__":
    _main()
