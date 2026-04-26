"""GET /plants — full nuclear-plant catalog for the UI map.

v1 returns Quad Cities Unit 1 as the only fully-modeled site (`modeled=True`)
plus every other operating US nuclear plant from EIA-860 as a placeholder
(`modeled=False`) so the map can render the "scaling is the next step"
story per Tier 5 of Project_Plan.md.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.data_loader import load_eia_plants
from app.schemas import Plant

router = APIRouter(prefix="/plants", tags=["plants"])

# EIA plant_codes that the v1 model serves directly. Used to suppress the
# placeholder EIA entry so each plant appears exactly once on the map.
# Quad Cities Generating Station = EIA plant_code 880.
QC1_PLANT_CODE = 880

# Hand-curated entries for fully-modeled plants. Adding a plant here makes
# it appear on the UI map as a live (interactive) marker. Operator/river
# fields are richer than EIA-860 surfaces, hence the manual carry.
MODELED_PLANTS: dict[str, dict] = {
    "quad_cities_1": {
        "id": "quad_cities_1",
        "display_name": "Quad Cities Unit 1",
        "operator": "Constellation",
        "river": "Mississippi",
        "lat": 41.7261,
        "lon": -90.3097,
        "state": "IL",
        "plant_code": QC1_PLANT_CODE,
        "nameplate_mw": None,
        "modeled": True,
    },
}


def _placeholder_id(plant_code: int) -> str:
    return f"eia_{plant_code}"


def _build_catalog() -> list[Plant]:
    """Merge modeled plants with EIA placeholders, deduplicated by plant_code."""
    catalog: list[Plant] = [Plant.model_validate(p) for p in MODELED_PLANTS.values()]
    modeled_codes = {
        p["plant_code"] for p in MODELED_PLANTS.values() if p.get("plant_code") is not None
    }
    try:
        eia = load_eia_plants()
    except FileNotFoundError:
        # No EIA cache yet — degrade gracefully to modeled-only catalog so
        # the UI map still renders QC1 in fresh checkouts.
        return catalog
    for row in eia:
        code = row["plant_code"]
        if code in modeled_codes:
            continue
        if row.get("lat") is None or row.get("lon") is None:
            continue
        catalog.append(
            Plant(
                id=_placeholder_id(code),
                display_name=row["plant_name"],
                operator=row.get("operator"),
                river=None,
                lat=row["lat"],
                lon=row["lon"],
                state=row.get("state"),
                plant_code=code,
                nameplate_mw=row.get("nameplate_mw"),
                modeled=False,
            )
        )
    return catalog


@router.get("", response_model=list[Plant])
def list_plants() -> list[Plant]:
    return _build_catalog()


@router.get("/{plant_id}", response_model=Plant)
def get_plant(plant_id: str) -> Plant:
    for plant in _build_catalog():
        if plant.id == plant_id:
            return plant
    raise HTTPException(status_code=404, detail=f"plant_id={plant_id!r}")
