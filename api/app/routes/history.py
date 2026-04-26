"""GET /plants/{id}/history — month-of-year realized capacity factor.

Powers the History calendar view: the operator picks any (year, month)
the labels dataset covers and the chart renders that single month's
realized capacity factor with refueling outages shown as a red floor and
each dip classified as weather-dependent or non-weather-dependent based
on whether the model also predicted a dip.
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException, Query

from app.data_loader import SUPPORTED_PLANTS, load_history_month
from app.schemas import HistoryPoint, HistoryResponse

router = APIRouter(prefix="/plants", tags=["history"])

EARLIEST_YEAR = 2005


@router.get("/{plant_id}/history", response_model=HistoryResponse)
def get_history(
    plant_id: str,
    year: int = Query(..., ge=EARLIEST_YEAR, le=date.today().year),
    month: int = Query(..., ge=1, le=12),
) -> HistoryResponse:
    if plant_id not in SUPPORTED_PLANTS:
        raise HTTPException(
            status_code=404,
            detail=f"plant_id={plant_id!r} not modeled in v1",
        )
    try:
        rows = load_history_month(plant_id, year, month)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return HistoryResponse(
        plant_id=plant_id,
        year=year,
        month=month,
        points=[HistoryPoint(**r) for r in rows],
    )
