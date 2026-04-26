"""Plant registry — single source of truth for per-plant configuration.

Use when: looking up coordinates, USGS gauges, NRC unit names, or display
metadata for a modeled plant. All pipeline scripts take ``--plant <slug>``
and dispatch through this registry rather than reading constants from
``schemas.py`` directly.

Adding a new plant:
    1. Add a ``Plant(...)`` entry to ``PLANTS`` below.
    2. Run the pipeline targets for the slug:
       ``just ingest-labels <slug>`` -> ``just features <slug>`` ->
       ``just train <slug>``. Cached raw weather and USGS data is
       namespaced per plant where it depends on plant-specific URLs
       (weather coords) and shared otherwise (USGS site cache).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class Plant:
    """Per-plant configuration consumed by the data and training pipeline.

    Attributes
    ----------
    slug
        Snake-case identifier used in CLI args, filenames, and artifact
        directory names. Stable across pipeline runs — once set, never
        rename without migrating artifacts.
    nrc_unit_name
        Exact unit string in the NRC daily-power-status files. Verified at
        ingest time by an equality check after whitespace normalization.
    display_name
        Human-readable name for UI / reports.
    operator
        Operating utility (e.g., Constellation Energy, NPPD).
    state, river
        Geographic context shown on the map and in reports.
    lat, lon
        Plant coordinates. Used as the Open-Meteo single-point query
        location and for surfacing map pins.
    usgs_temp_sites
        USGS NWIS site numbers carrying water temperature (param 00010).
        Multiple sites are stitched in order — earlier sites are primary
        and later sites fill in where the earlier series is missing.
    usgs_flow_sites
        USGS NWIS site numbers carrying discharge (param 00060). Often
        the same as ``usgs_temp_sites``; plants on tidal estuaries or near
        dams may need a separate gauge for streamflow.
    """

    slug: str
    nrc_unit_name: str
    display_name: str
    operator: str
    state: str
    river: str
    lat: float
    lon: float
    usgs_temp_sites: tuple[str, ...]
    usgs_flow_sites: tuple[str, ...]


PLANTS: Mapping[str, Plant] = {
    "quad_cities_1": Plant(
        slug="quad_cities_1",
        nrc_unit_name="Quad Cities 1",
        display_name="Quad Cities Unit 1",
        operator="Constellation Energy",
        state="IL",
        river="Mississippi River",
        lat=41.7261,
        lon=-90.3097,
        # 05420500 (Mississippi at Clinton, IA) is the long historical
        # record; in 2021 USGS moved the temp sensor downstream to 05420400
        # (L&D 13). Treated as one continuous series — primary first wins
        # on overlap, secondary fills the post-2021 gap.
        usgs_temp_sites=("05420500", "05420400"),
        usgs_flow_sites=("05420500", "05420400"),
    ),
    "byron_1": Plant(
        slug="byron_1",
        nrc_unit_name="Byron 1",
        display_name="Byron Unit 1",
        operator="Constellation Energy",
        state="IL",
        river="Rock River",
        lat=42.0747,
        lon=-89.2811,
        # 05440700 (Rock River AT Byron, IL) — single gauge ~4mi from the
        # plant, serving both temp (continuous 2012-07-04 -> present, ~360
        # days/yr from 2015) and discharge (continuous 2000-05-02 ->
        # present). No stitch required.
        usgs_temp_sites=("05440700",),
        usgs_flow_sites=("05440700",),
    ),
}


def get_plant(slug: str) -> Plant:
    """Return the Plant with ``slug``, or raise with a clear hint.

    Use when: any pipeline script needs to dispatch on ``--plant``.
    """
    try:
        return PLANTS[slug]
    except KeyError as exc:
        choices = ", ".join(sorted(PLANTS))
        raise KeyError(
            f"unknown plant slug {slug!r}; known slugs: {choices}"
        ) from exc
