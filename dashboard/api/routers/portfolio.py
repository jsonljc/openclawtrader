from fastapi import APIRouter
from dashboard.api.data_readers import read_portfolio

router = APIRouter()


@router.get("/api/portfolio")
def get_portfolio():
    return read_portfolio()
