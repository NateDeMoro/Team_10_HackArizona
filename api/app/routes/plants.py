from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/plants", tags=["plants"])


@router.get("")
def list_plants() -> list[dict]:
    raise HTTPException(status_code=501, detail="not implemented")


@router.get("/{plant_id}")
def get_plant(plant_id: str) -> dict:
    raise HTTPException(status_code=501, detail="not implemented")
