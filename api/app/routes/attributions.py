"""GET /plants/{id}/attributions — SHAP attributions for the latest forecast.

Returns one HorizonAttribution per horizon (1..14). The UI defaults to
showing horizon_days == 7 (the headline forecast) but all horizons are
served so a future drill-down can switch horizons without a second
request. Attributions are precomputed by `just forecast` and persisted
as data/artifacts/attributions_latest.json — the api container does not
import xgboost or run SHAP at request time.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.data_loader import load_attributions
from app.schemas import AttributionsResponse

router = APIRouter(prefix="/plants", tags=["attributions"])

SUPPORTED_PLANTS = frozenset({"quad_cities_1"})


@router.get("/{plant_id}/attributions", response_model=AttributionsResponse)
def get_attributions(plant_id: str) -> AttributionsResponse:
    if plant_id not in SUPPORTED_PLANTS:
        raise HTTPException(
            status_code=404,
            detail=f"plant_id={plant_id!r} not modeled in v1",
        )
    try:
        payload = load_attributions()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if payload.get("plant_id") != plant_id:
        raise HTTPException(
            status_code=503,
            detail=(
                f"cached attributions are for {payload.get('plant_id')!r}, "
                f"not {plant_id!r}; run `just forecast`"
            ),
        )
    return AttributionsResponse.model_validate(payload)
