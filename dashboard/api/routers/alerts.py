from fastapi import APIRouter, Query
from dashboard.api.data_readers import read_alerts

router = APIRouter()


@router.get("/api/alerts")
def get_alerts(limit: int = Query(default=20, ge=1, le=100)):
    return read_alerts(limit=limit)
