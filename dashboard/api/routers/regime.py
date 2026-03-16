from fastapi import APIRouter
from dashboard.api.data_readers import read_regime

router = APIRouter()


@router.get("/api/regime")
def get_regime():
    return read_regime()
