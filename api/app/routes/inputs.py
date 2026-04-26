"""GET /plants/{id}/inputs — recent weather and water sparkline data.

Powers the Tier 5 detail page's "weather inputs" panel: small sparklines
for max air temperature, water temperature, and streamflow over the
forecast window. ERA5 archive lags ~7 days, so the trailing series can
trail the current date by a few days; the UI should label its x-axis
with actual observation dates rather than counting back from today.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.data_loader import SUPPORTED_PLANTS, load_recent_inputs
from app.schemas import InputsResponse, WeatherInputPoint

router = APIRouter(prefix="/plants", tags=["inputs"])


@router.get("/{plant_id}/inputs", response_model=InputsResponse)
def get_inputs(
    plant_id: str,
    days: int = Query(30, ge=1, le=180, description="Trailing window length"),
) -> InputsResponse:
    if plant_id not in SUPPORTED_PLANTS:
        raise HTTPException(
            status_code=404,
            detail=f"plant_id={plant_id!r} not modeled in v1",
        )
    try:
        rows = load_recent_inputs(plant_id, days)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return InputsResponse(
        plant_id=plant_id,
        points=[WeatherInputPoint(**r) for r in rows],
    )
