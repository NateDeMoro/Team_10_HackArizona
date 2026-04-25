"""USGS NWIS daily-values ingestion (Tier 2).

Use when: rebuilding the river-water feature table for Quad Cities. Combines
USGS gauges 05420500 (long historical record) and 05420400 (current
operational gauge) into one continuous daily series for water temperature
and streamflow. Run via `just features` or
`uv run python -m pipeline.ingest_usgs`. CLI flag `--refresh` re-pulls each
site, ignoring the on-disk cache.

Output:
- data/raw/usgs/{site}.json                 (cached per-site full-history)
- data/interim/water_quad_cities.parquet    (daily, stitched, UTC dates)
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from schemas import (  # noqa: E402
    USGS_DV_URL,
    USGS_PARAM_FLOW,
    USGS_PARAM_TEMP,
    USGS_SITE_PRIMARY,
    USGS_SITE_SECONDARY,
)

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = REPO_ROOT / "data" / "raw" / "usgs"
INTERIM_DIR = REPO_ROOT / "data" / "interim"

START_DATE = date(2005, 1, 1)
STAT_MEAN = "00003"

PARAM_TO_COL = {
    USGS_PARAM_TEMP: "water_temp_c",
    USGS_PARAM_FLOW: "streamflow_cfs",
}


def _fetch_site(site: str, refresh: bool) -> dict:
    """Pull (or reuse cached) full-history daily values for one USGS site."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    cache = RAW_DIR / f"{site}.json"

    today = datetime.now(timezone.utc).date()
    use_cache = cache.exists() and not refresh
    if use_cache:
        log.info("usgs %s: cache hit", site)
        return json.loads(cache.read_text())

    params = {
        "format": "json",
        "sites": site,
        "startDT": START_DATE.isoformat(),
        "endDT": today.isoformat(),
        "parameterCd": f"{USGS_PARAM_TEMP},{USGS_PARAM_FLOW}",
        "statCd": STAT_MEAN,
        "siteStatus": "all",
    }
    log.info("usgs %s: fetching %s to %s", site, START_DATE, today)
    resp = requests.get(USGS_DV_URL, params=params, timeout=120)
    resp.raise_for_status()
    payload = resp.json()
    cache.write_text(json.dumps(payload))
    log.info("usgs %s: cached %d bytes", site, cache.stat().st_size)
    return payload


def _payload_to_df(payload: dict, site: str) -> pd.DataFrame:
    """Flatten the NWIS waterML/JSON response into a tidy DataFrame."""
    series = payload.get("value", {}).get("timeSeries", [])
    rows: list[tuple[date, str, float]] = []
    for ts in series:
        var = ts.get("variable", {}).get("variableCode", [{}])
        param = var[0].get("value") if var else None
        if param not in PARAM_TO_COL:
            continue
        col = PARAM_TO_COL[param]
        for block in ts.get("values", []):
            for v in block.get("value", []):
                raw = v.get("value")
                if raw is None or raw == "":
                    continue
                try:
                    val = float(raw)
                except ValueError:
                    continue
                # USGS sentinel for missing is -999999.0; drop.
                if val <= -999000:
                    continue
                ts_str = v.get("dateTime", "")[:10]
                if not ts_str:
                    continue
                try:
                    d = datetime.strptime(ts_str, "%Y-%m-%d").date()
                except ValueError:
                    continue
                rows.append((d, col, val))
    if not rows:
        log.warning("usgs %s: no usable rows in payload", site)
        return pd.DataFrame(columns=["date", "water_temp_c", "streamflow_cfs", "site_id"])

    df = pd.DataFrame(rows, columns=["date", "param", "value"])
    df["date"] = pd.to_datetime(df["date"])
    # Some sites publish multiple sub-stations under one gauge; collapse with
    # mean before pivot so the wide table doesn't end up with list-valued cells.
    df = df.groupby(["date", "param"], as_index=False)["value"].mean()
    wide = df.pivot(index="date", columns="param", values="value").reset_index()
    wide.columns.name = None
    rename = {USGS_PARAM_TEMP: "water_temp_c", USGS_PARAM_FLOW: "streamflow_cfs"}
    wide = wide.rename(columns=rename)
    for col in ("water_temp_c", "streamflow_cfs"):
        if col not in wide.columns:
            wide[col] = pd.NA
    wide["site_id"] = site
    return wide[["date", "water_temp_c", "streamflow_cfs", "site_id"]]


def _stitch(primary: pd.DataFrame, secondary: pd.DataFrame) -> pd.DataFrame:
    """Stitch the two sites into one series. Primary wins where both report."""
    if primary.empty and secondary.empty:
        raise RuntimeError("both USGS sites returned no data")

    if not primary.empty and not secondary.empty:
        overlap = primary.merge(
            secondary,
            on="date",
            suffixes=("_p", "_s"),
            how="inner",
        )
        for col in ("water_temp_c", "streamflow_cfs"):
            cp = f"{col}_p"
            cs = f"{col}_s"
            both = overlap[[cp, cs]].dropna()
            if len(both) >= 30:
                corr = both.corr().iloc[0, 1]
                diff = (both[cp] - both[cs]).abs().mean()
                log.info(
                    "stitch overlap %s: n=%d, corr=%.3f, mean|p-s|=%.3f",
                    col,
                    len(both),
                    corr,
                    diff,
                )
            else:
                log.info(
                    "stitch overlap %s: insufficient overlap (n=%d)", col, len(both)
                )
    elif primary.empty:
        log.warning("stitch: primary site %s empty; secondary only", USGS_SITE_PRIMARY)
    elif secondary.empty:
        log.warning(
            "stitch: secondary site %s empty; primary only", USGS_SITE_SECONDARY
        )

    merged = primary.merge(
        secondary,
        on="date",
        suffixes=("_p", "_s"),
        how="outer",
    )
    out = pd.DataFrame({"date": merged["date"]})
    for col in ("water_temp_c", "streamflow_cfs"):
        cp = f"{col}_p"
        cs = f"{col}_s"
        if cp in merged.columns and cs in merged.columns:
            out[col] = merged[cp].combine_first(merged[cs])
        elif cp in merged.columns:
            out[col] = merged[cp]
        else:
            out[col] = merged[cs]

    # Provenance: site that supplied water_temp_c on each row (primary wins).
    if "site_id_p" in merged.columns and "site_id_s" in merged.columns:
        primary_has_temp = merged["water_temp_c_p"].notna() if "water_temp_c_p" in merged.columns else False
        out["water_site_id"] = merged["site_id_p"].where(primary_has_temp, merged["site_id_s"])
    return out.sort_values("date").reset_index(drop=True)


def _coverage_report(df: pd.DataFrame) -> None:
    """Print coverage by year and by month for water_temp_c."""
    if df.empty:
        log.warning("water table empty; nothing to report")
        return
    df = df.copy()
    df["year"] = df["date"].dt.year
    df["month"] = df["date"].dt.month
    log.info("USGS water coverage:")
    by_year = df.groupby("year").agg(
        n=("date", "count"),
        temp_nonnull=("water_temp_c", lambda s: s.notna().mean()),
        flow_nonnull=("streamflow_cfs", lambda s: s.notna().mean()),
    )
    for y, row in by_year.iterrows():
        log.info(
            "  %d: n=%d temp=%.0f%% flow=%.0f%%",
            y,
            int(row["n"]),
            row["temp_nonnull"] * 100,
            row["flow_nonnull"] * 100,
        )
    by_month = df.groupby("month")["water_temp_c"].apply(lambda s: s.notna().mean())
    log.info("water_temp_c null-rate by month (sensor downtime check):")
    for m, frac in by_month.items():
        log.info("  month %02d: %.0f%% non-null", m, frac * 100)


def run(refresh: bool = False) -> None:
    INTERIM_DIR.mkdir(parents=True, exist_ok=True)

    primary_payload = _fetch_site(USGS_SITE_PRIMARY, refresh=refresh)
    secondary_payload = _fetch_site(USGS_SITE_SECONDARY, refresh=refresh)
    primary = _payload_to_df(primary_payload, USGS_SITE_PRIMARY)
    secondary = _payload_to_df(secondary_payload, USGS_SITE_SECONDARY)
    log.info(
        "usgs %s rows: %d; usgs %s rows: %d",
        USGS_SITE_PRIMARY,
        len(primary),
        USGS_SITE_SECONDARY,
        len(secondary),
    )

    stitched = _stitch(primary, secondary)
    out = INTERIM_DIR / "water_quad_cities.parquet"
    stitched.to_parquet(out, index=False)
    log.info(
        "wrote %s: %d rows, %s -> %s",
        out,
        len(stitched),
        stitched["date"].min().date() if len(stitched) else "n/a",
        stitched["date"].max().date() if len(stitched) else "n/a",
    )
    _coverage_report(stitched)


def _main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Re-pull both gauges, ignoring the cache.",
    )
    args = parser.parse_args()
    run(refresh=args.refresh)


if __name__ == "__main__":
    _main()
