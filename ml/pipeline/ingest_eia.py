"""EIA-860 nuclear plant metadata ingestion (Tier 2).

Use when: rebuilding the static plant metadata table consumed by Tier 5's UI
map and as a sanity reference for Quad Cities's lat/lon. Pulls the latest
released EIA-860 annual zip, extracts the Plant and Generator workbooks,
filters to nuclear units (energy_source_1 == "NUC"), aggregates to plant
level (sum nameplate_capacity_mw, count units), joins with plant metadata.
Run via `just features` or `uv run python -m pipeline.ingest_eia`.
CLI flag `--refresh` forces a re-download of the zip.

Output:
- data/raw/eia/eia860_{year}.zip            (cached source archive)
- data/interim/eia_nuclear_plants.parquet   (one row per nuclear plant)
"""
from __future__ import annotations

import argparse
import io
import logging
import sys
import zipfile
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from schemas import (  # noqa: E402
    EIA860_FALLBACK_URL,
    EIA860_URL,
    EIA860_YEAR_CANDIDATES,
)

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = REPO_ROOT / "data" / "raw" / "eia"
INTERIM_DIR = REPO_ROOT / "data" / "interim"

# EIA-860 workbooks have a one-row preamble above the column headers.
HEADER_ROW = 1


def _fetch_zip(refresh: bool) -> tuple[int, Path]:
    """Try EIA-860 zip URLs newest-first; return (year, cached path)."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    for year in EIA860_YEAR_CANDIDATES:
        cache = RAW_DIR / f"eia860_{year}.zip"
        if cache.exists() and not refresh:
            log.info("eia %d: cache hit (%d bytes)", year, cache.stat().st_size)
            return year, cache

        for url_tmpl in (EIA860_URL, EIA860_FALLBACK_URL):
            url = url_tmpl.format(year=year)
            log.info("eia %d: trying %s", year, url)
            resp = requests.get(url, timeout=300)
            if resp.status_code == 404:
                continue
            resp.raise_for_status()
            ct = resp.headers.get("content-type", "")
            if "zip" not in ct and not resp.content[:2] == b"PK":
                log.warning("eia %d: %s returned non-zip content-type %s", year, url, ct)
                continue
            cache.write_bytes(resp.content)
            log.info("eia %d: cached %d bytes from %s", year, len(resp.content), url)
            return year, cache

    raise RuntimeError(
        f"no EIA-860 zip available among years {EIA860_YEAR_CANDIDATES}"
    )


def _read_workbook(zf: zipfile.ZipFile, prefix: str, year: int) -> pd.DataFrame:
    """Read the first workbook in zf whose name starts with prefix."""
    matches = [
        n for n in zf.namelist()
        if n.startswith(prefix) and n.lower().endswith(".xlsx")
    ]
    if not matches:
        raise RuntimeError(f"eia {year}: no workbook matching prefix {prefix!r}")
    name = matches[0]
    log.info("eia %d: reading %s", year, name)
    with zf.open(name) as fh:
        data = fh.read()
    return pd.read_excel(io.BytesIO(data), header=HEADER_ROW, engine="openpyxl")


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Lowercase + strip + replace spaces; drop trailing-blank header columns."""
    df = df.copy()
    df.columns = [
        str(c).strip().lower().replace(" ", "_").replace("(", "").replace(")", "")
        for c in df.columns
    ]
    df = df.loc[:, ~df.columns.str.startswith("unnamed")]
    return df


def _build_nuclear_plants(plant: pd.DataFrame, gen: pd.DataFrame) -> pd.DataFrame:
    """Join nuclear-unit-level rows back to plant metadata; one row per plant."""
    plant = _normalize_columns(plant)
    gen = _normalize_columns(gen)

    energy_col = next(
        (c for c in gen.columns if c.startswith("energy_source_1")),
        None,
    )
    if energy_col is None:
        raise RuntimeError(f"no energy_source_1 column in generator file (cols={list(gen.columns)[:20]})")
    capacity_col = next(
        (c for c in gen.columns if "nameplate_capacity" in c),
        None,
    )
    if capacity_col is None:
        raise RuntimeError("no nameplate_capacity column in generator file")

    nuclear = gen[gen[energy_col].astype(str).str.upper() == "NUC"].copy()
    if nuclear.empty:
        raise RuntimeError("eia: no nuclear units found (energy_source_1 == NUC)")

    nuclear["plant_code"] = pd.to_numeric(nuclear["plant_code"], errors="coerce")
    nuclear[capacity_col] = pd.to_numeric(nuclear[capacity_col], errors="coerce")

    agg = (
        nuclear.groupby("plant_code", as_index=False)
        .agg(
            unit_count=("generator_id", "count"),
            total_nameplate_mw=(capacity_col, "sum"),
        )
    )

    plant["plant_code"] = pd.to_numeric(plant["plant_code"], errors="coerce")
    keep = [
        "plant_code",
        "plant_name",
        "state",
        "county",
        "latitude",
        "longitude",
        "utility_name",
        "utility_id",
    ]
    keep = [c for c in keep if c in plant.columns]
    plant_slim = plant[keep].drop_duplicates(subset=["plant_code"])

    out = agg.merge(plant_slim, on="plant_code", how="left")
    out["latitude"] = pd.to_numeric(out["latitude"], errors="coerce")
    out["longitude"] = pd.to_numeric(out["longitude"], errors="coerce")
    return out.sort_values("plant_name").reset_index(drop=True)


def run(refresh: bool = False) -> None:
    INTERIM_DIR.mkdir(parents=True, exist_ok=True)
    year, zip_path = _fetch_zip(refresh=refresh)

    with zipfile.ZipFile(zip_path) as zf:
        plant = _read_workbook(zf, prefix="2___Plant", year=year)
        gen = _read_workbook(zf, prefix="3_1_Generator", year=year)

    nuclear_plants = _build_nuclear_plants(plant, gen)
    out = INTERIM_DIR / "eia_nuclear_plants.parquet"
    nuclear_plants.to_parquet(out, index=False)
    log.info(
        "wrote %s: %d nuclear plants (EIA-860 %d)",
        out,
        len(nuclear_plants),
        year,
    )

    qc_match = nuclear_plants[
        nuclear_plants["plant_name"].astype(str).str.contains(
            "Quad Cities", case=False, na=False
        )
    ]
    if qc_match.empty:
        log.warning("Quad Cities not found in EIA-860 %d table", year)
    else:
        for _, row in qc_match.iterrows():
            log.info(
                "QC1 sanity: %s (code=%s) at (%.4f, %.4f), %d units, %.0f MW",
                row["plant_name"],
                row["plant_code"],
                row["latitude"],
                row["longitude"],
                int(row["unit_count"]),
                row["total_nameplate_mw"],
            )


def _main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Re-download the EIA-860 zip, ignoring cache.",
    )
    args = parser.parse_args()
    run(refresh=args.refresh)


if __name__ == "__main__":
    _main()
