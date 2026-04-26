"""Daily refresh entrypoint for the Railway cron service.

Run via ``python -m pipeline.refresh`` (the ml service's CMD).
For each registered plant:
  1. Re-ingests fresh weather (Open-Meteo) and water (USGS).
  2. Rebuilds the feature matrix and the inference dataset.
  3. Runs inference, producing forecast + attributions JSONs on disk.
  4. Uploads ALL artifacts the api consumes (forecast, attributions,
     backtest results, recent labels/weather/water) into Postgres as
     BYTEA blobs. The api ships no data; everything it serves is keyed
     by ``(plant_id, artifact_type)`` in this table.

EIA-860 (global plant list) is uploaded once per run with plant_id =
``_global``.

Failure policy: if any plant fails, the script exits non-zero and the
cron simply tries again at the next scheduled run. The api keeps
serving the previous values (no same-day retry).

The backtest is rerun daily (after inference) so the History overlay
extends as new actuals land. backtest_results.parquet still ships in
the image as a fallback for the very first refresher run.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from plants import PLANTS  # noqa: E402

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[1]  # ml/ (data lives at ml/data/)
ARTIFACTS_DIR = REPO_ROOT / "data" / "artifacts"
INTERIM_DIR = REPO_ROOT / "data" / "interim"

# Sentinel plant_id for non-plant-scoped rows (must match api/app/db.py).
GLOBAL_PLANT = "_global"

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS forecast_artifacts (
    plant_id      TEXT        NOT NULL,
    artifact_type TEXT        NOT NULL,
    payload       BYTEA       NOT NULL,
    refreshed_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (plant_id, artifact_type)
);
"""

UPSERT_SQL = """
INSERT INTO forecast_artifacts (plant_id, artifact_type, payload, refreshed_at)
VALUES (%s, %s, %s, NOW())
ON CONFLICT (plant_id, artifact_type) DO UPDATE
SET payload = EXCLUDED.payload, refreshed_at = NOW();
"""


def _run(*cmd: str) -> None:
    log.info("$ %s", " ".join(cmd))
    subprocess.run(cmd, check=True)


def _refresh_plant(slug: str) -> None:
    _run(sys.executable, "-m", "pipeline.ingest_weather", "--plant", slug)
    _run(sys.executable, "-m", "pipeline.ingest_usgs", "--plant", slug)
    _run(sys.executable, "-m", "pipeline.features", "--plant", slug)
    _run(sys.executable, "-m", "pipeline.build_dataset", "--plant", slug)
    _run(sys.executable, "-m", "pipeline.inference", "--plant", slug)
    # Re-runs the full historical replay so the History overlay's right
    # edge advances daily as new actuals land. ~minutes per plant; the
    # backtest_results.parquet upload below picks up the refreshed bytes.
    _run(sys.executable, "-m", "pipeline.backtest", "--plant", slug)


def _plant_uploads(slug: str) -> list[tuple[str, Path]]:
    """The (artifact_type, source_path) pairs to push for one plant."""
    plant_artifacts = ARTIFACTS_DIR / slug
    return [
        ("forecast",         plant_artifacts / "forecast_latest.json"),
        ("attributions",     plant_artifacts / "attributions_latest.json"),
        ("backtest_metrics", plant_artifacts / "backtest_metrics.json"),
        ("backtest_results", plant_artifacts / "backtest_results.parquet"),
        ("labels",           INTERIM_DIR / f"labels_{slug}.parquet"),
        ("weather",          INTERIM_DIR / f"weather_{slug}.parquet"),
        ("water",            INTERIM_DIR / f"water_{slug}.parquet"),
    ]


def _upload_blob(
    conn: psycopg.Connection, plant_id: str, artifact_type: str, path: Path
) -> None:
    blob = path.read_bytes()
    with conn.cursor() as cur:
        cur.execute(UPSERT_SQL, (plant_id, artifact_type, blob))
    log.info(
        "  uploaded (%s, %s) %d bytes from %s",
        plant_id, artifact_type, len(blob), path.name,
    )


def _upload_plant(conn: psycopg.Connection, slug: str) -> None:
    for artifact_type, path in _plant_uploads(slug):
        _upload_blob(conn, slug, artifact_type, path)
    conn.commit()
    log.info("[%s] all artifacts uploaded to postgres", slug)


def _upload_global(conn: psycopg.Connection) -> None:
    eia = INTERIM_DIR / "eia_nuclear_plants.parquet"
    _upload_blob(conn, GLOBAL_PLANT, "eia_plants", eia)
    conn.commit()
    log.info("[%s] eia_plants uploaded", GLOBAL_PLANT)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise SystemExit(
            "DATABASE_URL not set; link the Postgres addon to this Railway service"
        )

    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(CREATE_TABLE_SQL)
        conn.commit()

        # EIA is global and rarely changes — push the baked-in snapshot
        # once per run rather than per-plant.
        try:
            _upload_global(conn)
        except Exception:  # noqa: BLE001
            log.exception("global EIA upload failed (non-fatal, continuing)")

        failures: list[str] = []
        for slug in PLANTS:
            try:
                _refresh_plant(slug)
                _upload_plant(conn, slug)
            except Exception:  # noqa: BLE001
                log.exception("[%s] refresh failed", slug)
                failures.append(slug)

    if failures:
        raise SystemExit(f"refresh failed for: {', '.join(failures)}")


if __name__ == "__main__":
    main()
