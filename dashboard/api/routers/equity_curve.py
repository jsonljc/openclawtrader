from fastapi import APIRouter, Query
from dashboard.api.data_readers import read_equity_curve

router = APIRouter()


@router.get("/api/equity-curve")
def get_equity_curve(days: int = Query(default=30, ge=1, le=365)):
    return read_equity_curve(days=days)
