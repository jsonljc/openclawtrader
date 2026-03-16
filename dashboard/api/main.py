# dashboard/api/main.py
"""FastAPI dashboard backend."""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure trading root is importable
_TRADING_ROOT = Path(__file__).parent.parent.parent
if str(_TRADING_ROOT) not in sys.path:
    sys.path.insert(0, str(_TRADING_ROOT))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="OpenClaw Dashboard", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/api/health-check")
def health_check():
    return {"status": "ok"}
