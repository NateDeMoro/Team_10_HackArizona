"""USGS NWIS daily-values ingestion (Tier 2).

Use when: rebuilding the river-water feature table for a given plant. The
plant registry (``ml/plants.py``) declares which USGS site numbers carry
water temperature (``usgs_temp_sites``) and which carry streamflow
(``usgs_flow_sites``); this module pulls each declared site, picks the
best-available value per (date, parameter), and emits a single tidy
parquet keyed by date.

Most plants use the same gauge for both parameters
(``usgs_temp_sites == usgs_flow_sites``), in which case the gauge cache
is fetched once. Plants that need a stitch (Quad Cities: 05420500 +
05420400) declare both gauges and the earlier site wins on overlap; the
later site fills in where the earlier series ends. Plants that need
separate gauges per parameter (e.g., a tidal-estuary site with no
discharge metric) just declare different lists.

Run via ``just features <slug>`` or
``uv run python -m pipeline.ingest_usgs --plant <slug>``.

Output:
- data/raw/usgs/{site}.json                   (cached per-site full-history;
                                               shared across plants since site
                                               numbers are globally unique)
- data/interim/water_<slug>.parquet           (daily, stitched, UTC dates)
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
from plants import PLANTS, Plant, get_plant  # noqa: E402
from schemas import (  # noqa: E402
    USGS_DV_URL,
    USGS_PARAM_FLOW,
    USGS_PARAM_TEMP,
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


def _fetch_site(site: str, params: tuple[str, ...], refresh: bool) -> dict:
    """Pull (or reuse cached) full-history daily values for one USGS site.

    The cache is keyed on site number alone; ``params`` only affects the
    initial fetch. If a downstream caller needs a parameter not in the
    cached payload they should pass ``refresh=True``.
    """
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    cache = RAW_DIR / f"{site}.json"

    today = datetime.now(timezone.utc).date()
    use_cache = cache.exists() and not refresh
    if use_cache:
        log.info("usgs %s: cache hit", site)
        return json.loads(cache.read_text())

    query = {
        "format": "json",
        "sites": site,
        "startDT": START_DATE.isoformat(),
        "endDT": today.isoformat(),
        "parameterCd": ",".join(params),
        "statCd": STAT_MEAN,
        "siteStatus": "all",
    }
    log.info("usgs %s: fetching %s to %s", site, START_DATE, today)
    resp = requests.get(USGS_DV_URL, params=query, timeout=120)
    resp.raise_for_status()
    payload = resp.json()
    cache.write_text(json.dumps(payload))
    log.info("usgs %s: cached %d bytes", site, cache.stat().st_size)
    return payload


def _payload_to_long(payload: dict, site: str) -> pd.DataFrame:
    """Flatten the NWIS waterML/JSON response into long form (date, param, value, site_id).

    Rows are filtered to the parameters this module understands
    (PARAM_TO_COL); other parameters are dropped silently.
    """
    series = payload.get("value", {}).get("timeSeries", [])
    rows: list[tuple[date, str, float]] = []
    for ts in series:
        var = ts.get("variable", {}).get("variableCode", [{}])
        param = var[0].get("value") if var else None
        if param not in PARAM_TO_COL:
            continue
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
                rows.append((d, param, val))
    if not rows:
        log.warning("usgs %s: no usable rows in payload", site)
        return pd.DataFrame(columns=["date", "param", "value", "site_id"])
    df = pd.DataFrame(rows, columns=["date", "param", "value"])
    df["date"] = pd.to_datetime(df["date"])
    # Some sites publish multiple sub-stations under one gauge; collapse with
    # mean before the downstream pivot.
    df = df.groupby(["date", "param"], as_index=False)["value"].mean()
    df["site_id"] = site
    return df


def _stitch_param(
    long_frames: list[pd.DataFrame],
    sites: tuple[str, ...],
    param: str,
    column: str,
) -> pd.DataFrame:
    """Stitch one parameter across the supplied site-priority order.

    Earlier sites win; later sites fill in where earlier ones are missing.
    Returns a wide frame with columns ``date``, ``column``, and (only for
    the temp parameter) ``site_id`` carrying the gauge that supplied each
    row's value.
    """
    if not sites:
        return pd.DataFrame(columns=["date", column])
    per_site: dict[str, pd.DataFrame] = {}
    for s, frame in zip(sites, long_frames, strict=True):
        sub = frame[frame["param"] == param][["date", "value", "site_id"]]
        if sub.empty:
            log.info("stitch %s: site %s has no %s rows", param, s, column)
        per_site[s] = sub.copy()

    # Combine in priority order: each site fills only the date rows the
    # earlier-priority sites left empty.
    combined: pd.DataFrame | None = None
    for s in sites:
        sub = per_site[s].rename(columns={"value": column}).drop_duplicates("date")
        if combined is None:
            combined = sub
            continue
        if sub.empty:
            continue
        # Pull in dates the running combined doesn't already have.
        missing = sub[~sub["date"].isin(combined["date"])]
        combined = pd.concat([combined, missing], ignore_index=True)

    if combined is None:
        return pd.DataFrame(columns=["date", column])

    # Log overlap stats when more than one site contributed something.
    if len(sites) >= 2:
        overlap_dates: set | None = None
        for s in sites:
            sub = per_site[s]
            if sub.empty:
                continue
            ds = set(sub["date"])
            overlap_dates = ds if overlap_dates is None else overlap_dates & ds
        if overlap_dates and len(overlap_dates) >= 30:
            stack = []
            for s in sites:
                sub = per_site[s]
                if sub.empty:
                    continue
                hit = sub[sub["date"].isin(overlap_dates)][["date", "value"]].rename(
                    columns={"value": s}
                )
                stack.append(hit)
            if len(stack) >= 2:
                merged = stack[0]
                for piece in stack[1:]:
                    merged = merged.merge(piece, on="date", how="inner")
                cols = [c for c in merged.columns if c != "date"]
                if len(cols) >= 2:
                    base = merged[cols[0]]
                    for other in cols[1:]:
                        diff = (base - merged[other]).abs().mean()
                        corr = base.corr(merged[other])
                        log.info(
                            "stitch overlap %s: %s vs %s n=%d corr=%.3f mean|diff|=%.3f",
                            column,
                            cols[0],
                            other,
                            len(merged),
                            corr,
                            diff,
                        )

    return combined.sort_values("date").reset_index(drop=True)


def _coverage_report(df: pd.DataFrame) -> None:
    """Print per-year temp / flow coverage for the stitched table."""
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


def run(plant: Plant, refresh: bool = False) -> None:
    INTERIM_DIR.mkdir(parents=True, exist_ok=True)

    # Fetch every distinct site once; some plants share a gauge across
    # parameters (Byron) and some don't (a tidal-estuary plant might).
    all_sites = tuple(dict.fromkeys((*plant.usgs_temp_sites, *plant.usgs_flow_sites)))
    site_long: dict[str, pd.DataFrame] = {}
    for site in all_sites:
        params = (USGS_PARAM_TEMP, USGS_PARAM_FLOW)
        payload = _fetch_site(site, params=params, refresh=refresh)
        site_long[site] = _payload_to_long(payload, site)
        log.info("usgs %s: long-form rows=%d", site, len(site_long[site]))

    temp_frames = [site_long[s] for s in plant.usgs_temp_sites]
    flow_frames = [site_long[s] for s in plant.usgs_flow_sites]
    temp = _stitch_param(temp_frames, plant.usgs_temp_sites, USGS_PARAM_TEMP, "water_temp_c")
    flow = _stitch_param(flow_frames, plant.usgs_flow_sites, USGS_PARAM_FLOW, "streamflow_cfs")

    # Provenance: site that supplied the temperature value on each row.
    # The model uses ``water_site_id`` as a categorical so XGBoost can
    # learn small per-gauge offsets.
    if "site_id" in temp.columns:
        temp = temp.rename(columns={"site_id": "water_site_id"})
    flow_to_merge = flow.drop(columns=[c for c in ("site_id",) if c in flow.columns])

    merged = temp.merge(flow_to_merge, on="date", how="outer").sort_values("date").reset_index(drop=True)
    if "water_site_id" not in merged.columns:
        merged["water_site_id"] = pd.NA
    merged = merged[["date", "water_temp_c", "streamflow_cfs", "water_site_id"]]

    out = INTERIM_DIR / f"water_{plant.slug}.parquet"
    merged.to_parquet(out, index=False)
    log.info(
        "wrote %s: %d rows, %s -> %s",
        out,
        len(merged),
        merged["date"].min().date() if len(merged) else "n/a",
        merged["date"].max().date() if len(merged) else "n/a",
    )
    _coverage_report(merged)


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
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Re-pull every gauge for the plant, ignoring the cache.",
    )
    args = parser.parse_args()
    run(get_plant(args.plant), refresh=args.refresh)


if __name__ == "__main__":
    _main()
