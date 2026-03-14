#!/usr/bin/env python3
"""Slippage tracker — separate micro vs full contract slippage statistics.

Logs every fill with contract_type field (micro/full) and maintains
rolling statistics per contract type. Alerts if micro avg > 2x full avg.
"""

from __future__ import annotations

import os
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).parent.parent
_DATA_DIR = Path(os.environ.get("OPENCLAW_DATA", _REPO_ROOT / "data"))
_SLIPPAGE_PATH = _DATA_DIR / "slippage_tracker.json"

# Micro symbol mapping
_MICRO_SYMBOLS = frozenset({"MES", "MNQ", "MCL", "MGC"})
_FULL_TO_MICRO = {"ES": "MES", "NQ": "MNQ", "CL": "MCL", "GC": "MGC"}

MAX_RECORDS = 200  # Keep last N fill records per contract type
ROLLING_WINDOW = 50  # Compute avg over last N


def _is_micro(symbol: str) -> bool:
    return symbol.upper() in _MICRO_SYMBOLS


def contract_type_for_symbol(symbol: str) -> str:
    return "micro" if _is_micro(symbol) else "full"


def _load_tracker() -> dict:
    try:
        with open(_SLIPPAGE_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {
            "micro": {"fills": [], "avg_slippage_ticks": 0.0, "count": 0},
            "full": {"fills": [], "avg_slippage_ticks": 0.0, "count": 0},
        }


def _save_tracker(data: dict) -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _SLIPPAGE_PATH.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    tmp.rename(_SLIPPAGE_PATH)


def record_fill(
    symbol: str,
    strategy_id: str,
    slippage_ticks: float,
    slippage_usd: float,
    contracts: int,
    fill_price: float,
    side: str,
    run_id: str = "",
) -> dict[str, Any]:
    """
    Record a fill with slippage data, categorized by contract type.

    Returns:
        {
            "contract_type": "micro" | "full",
            "alert": bool,
            "alert_message": str | None,
            "micro_avg": float,
            "full_avg": float,
        }
    """
    ct = contract_type_for_symbol(symbol)
    tracker = _load_tracker()

    fill_record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "contract_type": ct,
        "strategy_id": strategy_id,
        "slippage_ticks": round(slippage_ticks, 4),
        "slippage_usd": round(slippage_usd, 2),
        "contracts": contracts,
        "fill_price": fill_price,
        "side": side,
        "run_id": run_id,
    }

    bucket = tracker.setdefault(ct, {"fills": [], "avg_slippage_ticks": 0.0, "count": 0})
    bucket["fills"].append(fill_record)
    bucket["fills"] = bucket["fills"][-MAX_RECORDS:]
    bucket["count"] = bucket.get("count", 0) + 1

    # Compute rolling average
    recent = [f["slippage_ticks"] for f in bucket["fills"][-ROLLING_WINDOW:]]
    bucket["avg_slippage_ticks"] = round(sum(recent) / len(recent), 4) if recent else 0.0

    _save_tracker(tracker)

    # Check alert condition: micro avg > 2x full avg
    micro_avg = tracker.get("micro", {}).get("avg_slippage_ticks", 0.0)
    full_avg = tracker.get("full", {}).get("avg_slippage_ticks", 0.0)

    alert = False
    alert_message = None
    if full_avg > 0 and micro_avg > 2.0 * full_avg:
        micro_count = len(tracker.get("micro", {}).get("fills", []))
        if micro_count >= 10:  # need enough data
            alert = True
            alert_message = (
                f"Micro slippage ({micro_avg:.2f} ticks) > 2x full ({full_avg:.2f} ticks) "
                f"over last {ROLLING_WINDOW} fills"
            )

    return {
        "contract_type": ct,
        "alert": alert,
        "alert_message": alert_message,
        "micro_avg": micro_avg,
        "full_avg": full_avg,
    }


def get_stats() -> dict[str, Any]:
    """Return current slippage statistics by contract type."""
    tracker = _load_tracker()
    return {
        "micro": {
            "avg_slippage_ticks": tracker.get("micro", {}).get("avg_slippage_ticks", 0.0),
            "total_fills": tracker.get("micro", {}).get("count", 0),
        },
        "full": {
            "avg_slippage_ticks": tracker.get("full", {}).get("avg_slippage_ticks", 0.0),
            "total_fills": tracker.get("full", {}).get("count", 0),
        },
    }
