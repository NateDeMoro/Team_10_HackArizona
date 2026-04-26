"""NRC daily power-status ingestion (Tier 1).

Use when: rebuilding the label timeseries for a given plant from the NRC
public daily power-status reports. Run end-to-end via
``just ingest-labels <slug>`` from the repo root, or
``uv run python -m pipeline.ingest_nrc --plant <slug>``.
CLI flag ``--refresh`` forces re-download of every cached year.

Output:
- data/raw/nrc/{year}.txt                       (cached per-year source files,
                                                 shared across plants)
- data/interim/nrc_power_status.parquet         (all units, all years)
- data/interim/labels_<slug>.parquet            (this plant only, with
                                                 is_outage / is_pre_outage)
- ml/notebooks/figures/<slug>_power_history.png (sanity plot)
"""
from __future__ import annotations

import argparse
import logging
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import requests

# Allow `python -m pipeline.ingest_nrc` to import sibling modules at ml/.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from plants import PLANTS, Plant, get_plant  # noqa: E402
from schemas import (  # noqa: E402
    NRC_EARLIEST_YEAR,
    OUTAGE_MIN_CONSECUTIVE_DAYS,
    PRE_OUTAGE_LOOKBACK_DAYS,
    PRE_OUTAGE_MIN_BUFFER_DAYS,
    PRE_OUTAGE_RECOVERY_RUN_LEN,
    PRE_OUTAGE_TOLERANCE_PCT,
    REFUELING_OUTAGE_MIN_DAYS,
)

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = REPO_ROOT / "data" / "raw" / "nrc"
INTERIM_DIR = REPO_ROOT / "data" / "interim"
FIGURES_DIR = REPO_ROOT / "ml" / "notebooks" / "figures"

NRC_URL = (
    "https://www.nrc.gov/reading-rm/doc-collections/event-status/"
    "reactor-status/{year}/{year}PowerStatus.txt"
)

MIN_PARSE_RATE = 0.95  # Acceptance bar from the project plan.


def _unit_matcher(unit_name: str) -> re.Pattern[str]:
    """Build a case-insensitive, whitespace-tolerant regex for the canonical
    unit string. Used only to validate that the unit appears in the file —
    the actual filter is an equality check after normalization.
    """
    parts = re.split(r"\s+", unit_name.strip())
    pattern = r"^\s*" + r"\s*".join(re.escape(p) for p in parts) + r"\s*$"
    return re.compile(pattern, re.IGNORECASE)


def _fetch_year(year: int, refresh: bool) -> Path | None:
    """Download (or reuse cached) NRC power-status file for a single year.

    Returns the cache path, or None if the year is unavailable upstream.
    """
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    cache = RAW_DIR / f"{year}.txt"

    current_year = datetime.now(timezone.utc).year
    use_cache = cache.exists() and not refresh and year != current_year
    if use_cache:
        log.info("nrc %d: cache hit (%d bytes)", year, cache.stat().st_size)
        return cache

    url = NRC_URL.format(year=year)
    log.info("nrc %d: fetching %s", year, url)
    resp = requests.get(url, timeout=60)
    if resp.status_code == 404:
        log.warning("nrc %d: 404 (year unavailable upstream)", year)
        return None
    resp.raise_for_status()
    if not resp.text.lstrip().lower().startswith("reportdt"):
        log.warning("nrc %d: response missing expected header; skipping", year)
        return None
    cache.write_text(resp.text)
    log.info("nrc %d: cached %d bytes", year, len(resp.text))
    return cache


def _parse_year(path: Path, year: int, sentinel_matcher: re.Pattern[str]) -> pd.DataFrame:
    """Parse one cached NRC file. Logs and skips malformed rows.

    Asserts >=95% of non-blank, non-header lines parse cleanly and that the
    sentinel unit (the active plant being ingested) appears at least once.
    """
    raw_lines = path.read_text().splitlines()
    rows: list[tuple[date, str, int]] = []
    skipped = 0
    total = 0
    for ln in raw_lines:
        s = ln.strip()
        if not s:
            continue
        if s.lower().startswith("reportdt"):
            continue
        total += 1
        parts = s.split("|")
        if len(parts) != 3:
            skipped += 1
            continue
        date_s, unit_s, power_s = (p.strip() for p in parts)
        try:
            # 2005-2010 use "12/31/2005"; 2011+ use "12/31/2011 12:00:00 AM".
            if " " in date_s:
                dt = datetime.strptime(date_s, "%m/%d/%Y %I:%M:%S %p").date()
            else:
                dt = datetime.strptime(date_s, "%m/%d/%Y").date()
            power = int(power_s)
        except ValueError:
            skipped += 1
            continue
        if not unit_s:
            skipped += 1
            continue
        rows.append((dt, unit_s, power))

    if total == 0:
        raise RuntimeError(f"nrc {year}: file contained no data rows")
    parse_rate = (total - skipped) / total
    log.info(
        "nrc %d: parsed %d rows, skipped %d (%.2f%% parse rate)",
        year,
        total - skipped,
        skipped,
        parse_rate * 100,
    )
    if parse_rate < MIN_PARSE_RATE:
        raise RuntimeError(
            f"nrc {year}: parse rate {parse_rate:.3f} below {MIN_PARSE_RATE}"
        )

    df = pd.DataFrame(rows, columns=["date", "unit", "power_pct"])
    if not df["unit"].str.match(sentinel_matcher).any():
        raise RuntimeError(
            f"nrc {year}: sentinel unit pattern {sentinel_matcher.pattern!r} not found"
        )
    return df


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    """Coerce dtypes, dedupe, sort. Treat dates as tz-naive UTC calendar days."""
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    df["unit"] = df["unit"].str.strip()
    df["power_pct"] = df["power_pct"].astype("int16")
    before = len(df)
    df = df.drop_duplicates(subset=["date", "unit"], keep="last")
    if len(df) != before:
        log.info("dropped %d duplicate (date, unit) rows", before - len(df))
    return df.sort_values(["unit", "date"]).reset_index(drop=True)


def _add_is_outage(df: pd.DataFrame, min_days: int) -> pd.DataFrame:
    """Flag every row inside a run of >=min_days consecutive 0% days per unit."""
    df = df.copy()
    df["is_outage"] = False
    for unit, g in df.groupby("unit", sort=False):
        zero = g["power_pct"].eq(0).to_numpy()
        # Identify contiguous runs of zeros and mark those >= min_days.
        i = 0
        n = len(zero)
        flags = [False] * n
        while i < n:
            if zero[i]:
                j = i
                while j < n and zero[j]:
                    j += 1
                if j - i >= min_days:
                    for k in range(i, j):
                        flags[k] = True
                i = j
            else:
                i += 1
        df.loc[g.index, "is_outage"] = flags
    return df


def _add_is_pre_outage(
    df: pd.DataFrame,
    refuel_min: int,
    lookback: int,
    tolerance: int,
    recovery_run: int,
    min_buffer: int,
) -> pd.DataFrame:
    """Flag days inside the coastdown ramp preceding each refueling outage.

    Operates per unit on a date-sorted view. Only outage runs of length
    >= refuel_min trigger lookback (short runs are unplanned trips with no
    planned ramp). Within the lookback window, the unit's recent peak power
    defines the baseline; days within `tolerance` of that baseline for
    `recovery_run` consecutive days mark the end of the ramp walking
    backward — anything earlier belongs to a prior fuel cycle.
    """
    df = df.copy()
    df["is_pre_outage"] = False
    for unit in df["unit"].unique():
        mask = df["unit"] == unit
        sub = df.loc[mask].sort_values("date")
        idx = sub.index.to_numpy()
        is_out = sub["is_outage"].to_numpy()
        power = sub["power_pct"].to_numpy()
        n = len(sub)
        flags = [False] * n
        i = 0
        while i < n:
            if is_out[i]:
                j = i
                while j < n and is_out[j]:
                    j += 1
                if j - i >= refuel_min and i > 0:
                    lb_start = max(0, i - lookback)
                    baseline = int(power[lb_start:i].max())
                    threshold = baseline - tolerance
                    consecutive = 0
                    ramp_oldest = lb_start  # default: walk hits the cap
                    for k in range(i - 1, lb_start - 1, -1):
                        if power[k] >= threshold:
                            consecutive += 1
                            if consecutive >= recovery_run:
                                # Recovered: oldest pre-outage day is the one
                                # immediately AFTER the recovery run.
                                ramp_oldest = k + recovery_run
                                break
                        else:
                            consecutive = 0
                    # Apply the fixed minimum buffer: even if the adaptive
                    # walk found no ramp, every refueling outage gets at
                    # least min_buffer days flagged.
                    ramp_oldest = min(ramp_oldest, max(0, i - min_buffer))
                    for k in range(ramp_oldest, i):
                        flags[k] = True
                i = j
            else:
                i += 1
        df.loc[idx, "is_pre_outage"] = flags
    return df


def _coverage_report(df_unit: pd.DataFrame, label: str) -> float:
    """Log year-by-year coverage for the plant's labels; return overall fraction."""
    if df_unit.empty:
        return 0.0
    start = df_unit["date"].min().date()
    end = df_unit["date"].max().date()
    expected = pd.date_range(start, end, freq="D")
    have = df_unit.set_index("date").reindex(expected)
    overall = have["power_pct"].notna().mean()
    log.info(
        "%s coverage: %d / %d days (%.2f%%) from %s to %s",
        label,
        have["power_pct"].notna().sum(),
        len(expected),
        overall * 100,
        start,
        end,
    )
    by_year = (
        have.assign(year=have.index.year)
        .groupby("year")["power_pct"]
        .agg(lambda s: s.notna().mean())
    )
    for y, frac in by_year.items():
        log.info("  %d: %.2f%%", y, frac * 100)
    return float(overall)


def _render_sanity_plot(df_unit: pd.DataFrame, display_name: str, out: Path) -> None:
    """Render the per-plant capacity-factor sanity plot to PNG."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(14, 4))
    ax.plot(df_unit["date"], df_unit["power_pct"], linewidth=0.6, color="#1f3b73")
    pre = df_unit[df_unit["is_pre_outage"]]
    if not pre.empty:
        ax.scatter(
            pre["date"],
            pre["power_pct"],
            s=4,
            color="#e67e22",
            label="is_pre_outage (coastdown)",
        )
    outages = df_unit[df_unit["is_outage"]]
    if not outages.empty:
        ax.scatter(
            outages["date"],
            outages["power_pct"],
            s=2,
            color="#c0392b",
            label=f"is_outage (>={OUTAGE_MIN_CONSECUTIVE_DAYS}d at 0%)",
        )
    if not pre.empty or not outages.empty:
        ax.legend(loc="lower left", fontsize=8)
    ax.set_title(f"{display_name} — daily power output (% of full)")
    ax.set_xlabel("Date (UTC)")
    ax.set_ylabel("Power %")
    ax.set_ylim(-5, 110)
    ax.grid(True, linewidth=0.3, alpha=0.5)
    fig.tight_layout()
    fig.savefig(out, dpi=120)
    plt.close(fig)
    log.info("wrote sanity plot: %s", out)


def run(plant: Plant, refresh: bool = False) -> None:
    INTERIM_DIR.mkdir(parents=True, exist_ok=True)
    current_year = datetime.now(timezone.utc).year
    matcher = _unit_matcher(plant.nrc_unit_name)

    frames: list[pd.DataFrame] = []
    for year in range(NRC_EARLIEST_YEAR, current_year + 1):
        path = _fetch_year(year, refresh=refresh)
        if path is None:
            continue
        frames.append(_parse_year(path, year, matcher))

    if not frames:
        raise RuntimeError("no NRC years successfully ingested")

    all_units = _normalize(pd.concat(frames, ignore_index=True))
    all_units = _add_is_outage(all_units, OUTAGE_MIN_CONSECUTIVE_DAYS)
    all_units = _add_is_pre_outage(
        all_units,
        refuel_min=REFUELING_OUTAGE_MIN_DAYS,
        lookback=PRE_OUTAGE_LOOKBACK_DAYS,
        tolerance=PRE_OUTAGE_TOLERANCE_PCT,
        recovery_run=PRE_OUTAGE_RECOVERY_RUN_LEN,
        min_buffer=PRE_OUTAGE_MIN_BUFFER_DAYS,
    )

    out_all = INTERIM_DIR / "nrc_power_status.parquet"
    all_units.to_parquet(out_all, index=False)
    log.info(
        "wrote %s: %d rows, %d units, %s -> %s",
        out_all,
        len(all_units),
        all_units["unit"].nunique(),
        all_units["date"].min().date(),
        all_units["date"].max().date(),
    )

    sub = all_units[all_units["unit"].str.match(matcher)].copy()
    sub["unit"] = plant.nrc_unit_name
    if sub["unit"].nunique() != 1:
        raise RuntimeError(f"unit filter for {plant.slug} resolved to multiple units")
    out_unit = INTERIM_DIR / f"labels_{plant.slug}.parquet"
    sub.to_parquet(out_unit, index=False)
    log.info("wrote %s: %d rows", out_unit, len(sub))

    coverage = _coverage_report(sub, plant.display_name)
    if coverage < 0.99:
        log.warning(
            "%s coverage %.2f%% below 99%% acceptance bar",
            plant.display_name,
            coverage * 100,
        )

    fig_path = FIGURES_DIR / f"{plant.slug}_power_history.png"
    _render_sanity_plot(sub, plant.display_name, fig_path)


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
        help="Re-download every year, ignoring the on-disk cache.",
    )
    args = parser.parse_args()
    run(get_plant(args.plant), refresh=args.refresh)


if __name__ == "__main__":
    _main()
