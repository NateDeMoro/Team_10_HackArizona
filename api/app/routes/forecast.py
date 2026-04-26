"""GET /plants/{id}/forecast — serve the precomputed forecast JSON."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.data_loader import load_forecast
from app.schemas import ForecastResponse

router = APIRouter(prefix="/plants", tags=["forecast"])

# v1 supports a single plant; the response is precomputed by `just forecast`
# on the operator's machine.
SUPPORTED_PLANTS = frozenset({"quad_cities_1"})


@router.get("/{plant_id}/forecast", response_model=ForecastResponse)
def get_forecast(plant_id: str) -> ForecastResponse:
    if plant_id not in SUPPORTED_PLANTS:
        raise HTTPException(
            status_code=404,
            detail=f"plant_id={plant_id!r} not modeled in v1",
        )
    try:
        payload = load_forecast()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if payload.get("plant_id") != plant_id:
        raise HTTPException(
            status_code=503,
            detail=(
                f"cached forecast is for {payload.get('plant_id')!r}, "
                f"not {plant_id!r}; run `just forecast`"
            ),
        )
    return ForecastResponse.model_validate(payload)
