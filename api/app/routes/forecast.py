from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/plants", tags=["forecast"])


@router.get("/{plant_id}/forecast")
def get_forecast(plant_id: str) -> dict:
    raise HTTPException(status_code=501, detail="not implemented")
