from fastapi import APIRouter, Query
from dashboard.api.data_readers import read_trades

router = APIRouter()


@router.get("/api/trades")
def get_trades(limit: int = Query(default=50, ge=1, le=200)):
    return read_trades(limit=limit)
