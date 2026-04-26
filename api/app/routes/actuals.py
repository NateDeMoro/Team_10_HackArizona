"""GET /plants/{id}/actuals — trailing realized capacity factor.

Used by the Tier 5 forecast chart to render the last N days of
historical actuals to the left of the "now" line. Outage and
pre-outage days are returned with `power_pct=None` so the chart
shows a gap instead of a misleading 0%.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.data_loader import SUPPORTED_PLANTS, load_recent_actuals
from app.schemas import ActualPoint, ActualsResponse

router = APIRouter(prefix="/plants", tags=["actuals"])


@router.get("/{plant_id}/actuals", response_model=ActualsResponse)
def get_actuals(
    plant_id: str,
    days: int = Query(30, ge=1, le=365, description="Trailing window length"),
) -> ActualsResponse:
    if plant_id not in SUPPORTED_PLANTS:
        raise HTTPException(
            status_code=404,
            detail=f"plant_id={plant_id!r} not modeled in v1",
        )
    try:
        rows = load_recent_actuals(plant_id, days)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return ActualsResponse(
        plant_id=plant_id,
        days=days,
        points=[ActualPoint(**r) for r in rows],
    )
