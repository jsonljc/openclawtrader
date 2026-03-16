# dashboard/api/main.py
"""FastAPI dashboard backend."""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure trading root is importable
_TRADING_ROOT = Path(__file__).parent.parent.parent
if str(_TRADING_ROOT) not in sys.path:
    sys.path.insert(0, str(_TRADING_ROOT))

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from dashboard.api.telegram_bot import setup_telegram_bot


@asynccontextmanager
async def lifespan(app: FastAPI):
    await setup_telegram_bot(app)
    yield


app = FastAPI(title="OpenClaw Dashboard", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


from dashboard.api.routers import portfolio, signals, alerts, trades, equity_curve, health, regime

app.include_router(portfolio.router)
app.include_router(signals.router)
app.include_router(alerts.router)
app.include_router(trades.router)
app.include_router(equity_curve.router)
app.include_router(health.router)
app.include_router(regime.router)


@app.get("/api/health-check")
def health_check():
    return {"status": "ok"}
