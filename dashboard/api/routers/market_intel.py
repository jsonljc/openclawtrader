# dashboard/api/routers/market_intel.py
"""Market intel API endpoint."""
from __future__ import annotations

from fastapi import APIRouter

from dashboard.api.data_readers import read_intel

router = APIRouter()


@router.get("/api/intel")
def get_intel():
    """Return per-instrument conviction data from Prism daemon."""
    return read_intel()
