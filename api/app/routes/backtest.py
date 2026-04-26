"""GET /plants/{id}/backtest — serve precomputed backtest results.

`as_of=YYYY-MM-DD` selects a single historical run date and returns the
14-horizon comparison (predicted vs. realized) for that run. Used by the
Tier 5 replay slider.
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException, Query

from app.data_loader import load_backtest_for_run_date
from app.schemas import BacktestResponse, BacktestRow

router = APIRouter(prefix="/plants", tags=["backtest"])

SUPPORTED_PLANTS = frozenset({"quad_cities_1"})


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
