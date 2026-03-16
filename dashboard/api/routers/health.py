from fastapi import APIRouter
from dashboard.api.data_readers import read_health

router = APIRouter()


@router.get("/api/health")
def get_health():
    return read_health()
