"""GET /plants/{id}/briefing — plain-English forecast briefing.

Serves the precomputed briefing JSON the ml refresher generates daily via
Bedrock (Gemma 3 27B). The api container does not call Bedrock — it
returns cached bytes from postgres. A 503 surfaces when the artifact is
missing (e.g., a fresh plant before its first refresher run, or a
sustained Bedrock outage that wiped the prior payload).
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.data_loader import SUPPORTED_PLANTS, load_briefing
from app.schemas import BriefingResponse

router = APIRouter(prefix="/plants", tags=["briefing"])


@router.get("/{plant_id}/briefing", response_model=BriefingResponse)
def get_briefing(plant_id: str) -> BriefingResponse:
    if plant_id not in SUPPORTED_PLANTS:
        raise HTTPException(
            status_code=404,
            detail=f"plant_id={plant_id!r} not modeled in v1",
        )
    try:
        payload = load_briefing(plant_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if payload.get("plant_id") != plant_id:
        raise HTTPException(
            status_code=503,
            detail=(
                f"cached briefing is for {payload.get('plant_id')!r}, "
                f"not {plant_id!r}; rerun the ml refresher"
            ),
        )
    return BriefingResponse.model_validate(payload)
