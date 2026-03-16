# dashboard/api/data_readers.py
"""Shared data reading functions for dashboard API and Telegram bot."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

# Add trading root to path for shared module access
_TRADING_ROOT = Path(__file__).parent.parent.parent
if str(_TRADING_ROOT) not in sys.path:
    sys.path.insert(0, str(_TRADING_ROOT))

from shared import state_store as store


def _data_dir() -> Path:
    return Path(os.environ.get("OPENCLAW_DATA", _TRADING_ROOT / "data"))


def read_portfolio() -> dict[str, Any]:
    """Read portfolio + posture state."""
    portfolio = store.load_portfolio()
    posture_state = store.load_state("posture_state") or {}
    portfolio["posture_details"] = posture_state
    return portfolio


def read_alerts(data_dir: Path | None = None, limit: int = 20) -> list[dict]:
    """Read alerts.log, return newest first."""
    d = data_dir or _data_dir()
    alerts_path = d / "alerts.log"
    if not alerts_path.exists():
        return []
    alerts = []
    with open(alerts_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                alerts.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    # Newest first
    alerts.reverse()
    return alerts[:limit]


def read_trades(data_dir: Path | None = None, limit: int = 50) -> list[dict]:
    """Read POSITION_CLOSED events from ledger, newest first."""
    d = data_dir or _data_dir()
    ledger_path = d / "ledger.jsonl"
    if not ledger_path.exists():
        return []
    trades = []
    with open(ledger_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("event_type") == "POSITION_CLOSED":
                trades.append(entry)
    trades.reverse()
    return trades[:limit]


def read_equity_curve(data_dir: Path | None = None, days: int = 30) -> list[dict]:
    """Read DAILY_SNAPSHOT events from ledger, oldest first."""
    d = data_dir or _data_dir()
    ledger_path = d / "ledger.jsonl"
    if not ledger_path.exists():
        return []
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    snapshots = []
    with open(ledger_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("event_type") == "DAILY_SNAPSHOT":
                if entry.get("timestamp", "") >= cutoff:
                    snapshots.append(entry)
    return snapshots


def read_health() -> dict[str, dict]:
    """Read strategy registry for health/incubation data."""
    return store.load_strategy_registry()


def read_regime(data_dir: Path | None = None) -> dict[str, dict]:
    """Read intraday regime state."""
    d = data_dir or _data_dir()
    regime_path = d / "intraday_regime.json"
    if not regime_path.exists():
        return {}
    try:
        with open(regime_path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def read_signals(redis_url: str = "") -> dict[str, list]:
    """Read active signals from Redis streams."""
    url = redis_url or os.environ.get("REDIS_URL", "redis://localhost:6379")
    try:
        import redis
        rc = redis.from_url(url, decode_responses=True)
        from openclaw_trader.signals.signal_publisher import read_active_signals
        news = read_active_signals(rc, "news_signals", count=50)
        poly = read_active_signals(rc, "polymarket_signals", count=50)
        return {"news": news, "polymarket": poly}
    except Exception:
        return {"news": [], "polymarket": []}
