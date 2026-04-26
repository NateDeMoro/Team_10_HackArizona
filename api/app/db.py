"""Postgres reader for ALL forecast/data artifacts the api serves.

The api container ships no data — every loader fetches bytes from the
forecast_artifacts table (written by the ml refresher service). JSON
artifacts are stored as utf-8 bytes; parquet artifacts as raw bytes.
A 5-min in-memory TTL cache keeps request latency down without
materially extending staleness (the refresher fires once per day).

Use when: any api route needs a piece of plant-scoped data.
"""
from __future__ import annotations

import os
import time

import psycopg

# Sentinel plant_id for artifacts that aren't plant-scoped (e.g. EIA-860).
GLOBAL_PLANT = "_global"

_TTL_SECONDS = 300

_cache: dict[tuple[str, str], tuple[float, bytes]] = {}


def _conn() -> psycopg.Connection:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL not set; link the Postgres addon to this Railway service"
        )
    return psycopg.connect(url)


def fetch_artifact(plant_id: str, artifact_type: str) -> bytes:
    """Return raw payload bytes for (plant_id, artifact_type).

    Callers decode appropriately: ``json.loads(blob.decode())`` for JSON,
    ``pd.read_parquet(io.BytesIO(blob))`` for parquet. Raises
    FileNotFoundError on cache miss or DB unreachable so the route layer
    can map both to 503.
    """
    key = (plant_id, artifact_type)
    now = time.time()
    cached = _cache.get(key)
    if cached and now - cached[0] < _TTL_SECONDS:
        return cached[1]

    # Catch the full psycopg.Error hierarchy: OperationalError (network /
    # auth / pool exhaustion) AND ProgrammingError (the table itself
    # hasn't been created yet — happens on a fresh deploy before the ml
    # refresher's first successful run, surfaces in pg logs as
    # `relation "forecast_artifacts" does not exist`). Both mean "data
    # not available" from the api's point of view, so we convert both to
    # FileNotFoundError → 503 instead of letting them propagate as 500s
    # (which Railway's gateway returns without CORS headers, surfacing
    # in Safari as the opaque "Load failed").
    try:
        with _conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT payload FROM forecast_artifacts "
                "WHERE plant_id = %s AND artifact_type = %s",
                (plant_id, artifact_type),
            )
            row = cur.fetchone()
    except psycopg.Error as exc:
        raise FileNotFoundError(
            f"postgres not ready; cannot serve {artifact_type} for {plant_id}: {exc}"
        ) from exc

    if row is None:
        raise FileNotFoundError(
            f"no {artifact_type} in postgres for {plant_id}; "
            "refresher has not run yet"
        )

    payload = bytes(row[0])
    _cache[key] = (now, payload)
    return payload
