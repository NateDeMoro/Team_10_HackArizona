"""GET /plants/{id}/backtest — serve precomputed backtest results.

`as_of=YYYY-MM-DD` selects a single historical run date and returns the
14-horizon comparison (predicted vs. realized) for that run. The
companion `/backtest/dates` endpoint returns the full set of valid
as_of values plus the named heatwave highlights, so the Tier 5 replay
slider can render its valid range and tick marks without probing the
backtest endpoint.
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException, Query

from app.data_loader import load_backtest_dates, load_backtest_for_run_date
from app.schemas import BacktestDatesResponse, BacktestResponse, BacktestRow

router = APIRouter(prefix="/plants", tags=["backtest"])

SUPPORTED_PLANTS = frozenset({"quad_cities_1"})

# Named historical run dates highlighted in the backtest report. Mirrors
# HISTORICAL_BACKTEST_DATES in schemas.py — duplicated here as `date`
# objects to keep the api container free of the ml/ schemas constants
# block (which carries pipeline-only tunables).
HISTORICAL_HIGHLIGHTS: tuple[date, ...] = (
    date(2012, 7, 15),
    date(2018, 7, 1),
    date(2021, 8, 1),
    date(2022, 7, 15),
    date(2023, 8, 15),
)


@router.get("/{plant_id}/backtest/dates", response_model=BacktestDatesResponse)
def get_backtest_dates(plant_id: str) -> BacktestDatesResponse:
    if plant_id not in SUPPORTED_PLANTS:
        raise HTTPException(
            status_code=404,
            detail=f"plant_id={plant_id!r} not modeled in v1",
        )
    try:
        dates = load_backtest_dates()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    available = set(dates)
    highlights = [d for d in HISTORICAL_HIGHLIGHTS if d in available]
    return BacktestDatesResponse(
        plant_id=plant_id,
        dates=dates,
        highlights=highlights,
    )


@router.get("/{plant_id}/backtest", response_model=BacktestResponse)
def get_backtest(
    plant_id: str,
    as_of: date = Query(..., description="Run date to replay (YYYY-MM-DD)"),
) -> BacktestResponse:
    if plant_id not in SUPPORTED_PLANTS:
        raise HTTPException(
            status_code=404,
            detail=f"plant_id={plant_id!r} not modeled in v1",
        )
    try:
        records = load_backtest_for_run_date(as_of)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not records:
        raise HTTPException(
            status_code=404,
            detail=f"no backtest entries for as_of={as_of}",
        )
    rows = [
        BacktestRow(
            horizon_days=int(r["horizon"]),
            run_date=as_of,
            target_date=r["target_date"],
            actual_pct=float(r["actual"]) if r.get("actual") is not None else None,
            point_pct=float(r["point"]),
            band_low_pct=float(r["band_low"]),
            band_high_pct=float(r["band_high"]),
        )
        for r in records
    ]
    return BacktestResponse(
        plant_id=plant_id,
        as_of=as_of,
        source="historical_nwp" if as_of.year >= 2016 else "era5_fallback",
        rows=rows,
    )
