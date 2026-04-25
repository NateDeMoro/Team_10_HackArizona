from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/plants", tags=["backtest"])


@router.get("/{plant_id}/backtest")
def get_backtest(plant_id: str, as_of: str) -> dict:
    raise HTTPException(status_code=501, detail="not implemented")
