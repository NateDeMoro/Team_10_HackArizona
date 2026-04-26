"""Join features onto labels into the final training Parquet (Tier 2).

Use when: producing the canonical training table the model trains on for
a given plant. Left-joins the engineered features onto the full label
timeseries (including is_outage and is_pre_outage flags), preserving
every label day. Filtering decisions for outage / pre-outage days are
deferred to Tier 3. Run via ``just features <slug>`` or
``uv run python -m pipeline.build_dataset --plant <slug>``.

Reads:
    data/interim/labels_<slug>.parquet
    data/interim/features_<slug>.parquet
Writes:
    data/processed/<slug>/training_dataset.parquet
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from plants import PLANTS, Plant, get_plant  # noqa: E402

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
INTERIM_DIR = REPO_ROOT / "data" / "interim"
PROCESSED_DIR = REPO_ROOT / "data" / "processed"


def _coverage_report(df: pd.DataFrame) -> None:
    """Print non-null fraction per column, and per-year for the top weather/water cols."""
    log.info("training_dataset coverage (non-null fraction):")
    overall = df.notna().mean().sort_values(ascending=False)
    for col, frac in overall.items():
        log.info("  %-40s %.0f%%", col, frac * 100)

    spotlight = [
        c for c in (
            "power_pct",
            "air_temp_c_max",
            "wet_bulb_c",
            "water_temp_c",
            "streamflow_cfs",
        )
        if c in df.columns
    ]
    if not spotlight:
        return
    df = df.copy()
    df["year"] = df["date"].dt.year
    log.info("by-year non-null for spotlight columns:")
    by_year = df.groupby("year")[spotlight].apply(lambda g: g.notna().mean())
    for y, row in by_year.iterrows():
        parts = " ".join(f"{c}={row[c]*100:.0f}%" for c in spotlight)
        log.info("  %d: %s", y, parts)


def run(plant: Plant) -> None:
    plant_processed_dir = PROCESSED_DIR / plant.slug
    plant_processed_dir.mkdir(parents=True, exist_ok=True)

    labels_path = INTERIM_DIR / f"labels_{plant.slug}.parquet"
    features_path = INTERIM_DIR / f"features_{plant.slug}.parquet"
    if not labels_path.exists():
        raise FileNotFoundError(f"missing {labels_path}; run ingest_nrc first")
    if not features_path.exists():
        raise FileNotFoundError(f"missing {features_path}; run features first")

    labels = pd.read_parquet(labels_path)
    features = pd.read_parquet(features_path)

    labels["date"] = pd.to_datetime(labels["date"]).dt.tz_localize(None).dt.normalize()
    features["date"] = pd.to_datetime(features["date"]).dt.tz_localize(None).dt.normalize()

    if labels["date"].dt.tz is not None or features["date"].dt.tz is not None:
        raise RuntimeError("date columns must be tz-naive after normalization")

    if labels["unit"].nunique() != 1 or labels["unit"].iloc[0] != plant.nrc_unit_name:
        raise RuntimeError(
            f"labels file must contain exactly {plant.nrc_unit_name!r} rows"
        )

    df = labels.merge(features, on="date", how="left").sort_values("date").reset_index(drop=True)

    if df["date"].duplicated().any():
        raise RuntimeError("training dataset has duplicate date rows after join")

    out = plant_processed_dir / "training_dataset.parquet"
    df.to_parquet(out, index=False)
    log.info(
        "wrote %s: %d rows x %d cols, %s -> %s",
        out,
        len(df),
        df.shape[1],
        df["date"].min().date(),
        df["date"].max().date(),
    )
    _coverage_report(df)


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
