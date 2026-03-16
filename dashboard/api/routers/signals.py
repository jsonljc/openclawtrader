from fastapi import APIRouter
from dashboard.api.data_readers import read_signals

router = APIRouter()


@router.get("/api/signals")
def get_signals():
    return read_signals()
