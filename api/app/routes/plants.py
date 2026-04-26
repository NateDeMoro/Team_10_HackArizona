"""GET /plants — list plants. v1 returns just Quad Cities 1 as the only
fully-modeled site; the rest are placeholders the UI greys out and labels
"model coming soon" per the Tier 5 plan.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/plants", tags=["plants"])

# Single source of truth for the v1 plant catalog. Adding a plant here
# makes it appear on the UI map; the `modeled` flag determines whether
# the marker is interactive vs greyed-out.
PLANTS: dict[str, dict] = {
    "quad_cities_1": {
        "id": "quad_cities_1",
        "display_name": "Quad Cities Unit 1",
        "operator": "Constellation",
        "river": "Mississippi",
        "lat": 41.7261,
        "lon": -90.3097,
        "modeled": True,
    },
}


@router.get("")
def list_plants() -> list[dict]:
    return list(PLANTS.values())


@router.get("/{plant_id}")
def get_plant(plant_id: str) -> dict:
    plant = PLANTS.get(plant_id)
    if plant is None:
        raise HTTPException(status_code=404, detail=f"plant_id={plant_id!r}")
    return plant
