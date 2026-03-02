#!/usr/bin/env python3
"""Data collection layer — harvest structured data from the ledger.

Reads POSITION_CLOSED, REGIME_COMPUTED, MISSED_OPPORTUNITY, and
INTENT_DENIED events and converts them into analysis-ready dataclasses.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared import ledger
from shared import contracts as C


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class TradeRecord:
    """Structured trade record from a POSITION_CLOSED event."""

    strategy_id: str
    symbol: str
    side: str
    entry_price: float
    exit_price: float
    stop_price: float
    tp_price: float
    stop_dist: float
    tp_dist: float
    realized_pnl: float
    realized_r: float          # pnl / risk_at_stop
    slippage_ticks: float
    bars_held: int
    contracts: int
    regime_score_at_entry: float
    health_score_at_entry: float
    posture_at_entry: str
    entry_ts: str
    exit_ts: str
    trigger: str               # STOP / TP / MANUAL / OVERNIGHT


@dataclass
class RegimeSnapshot:
    """Structured regime observation from a REGIME_COMPUTED event."""

    timestamp: str
    regime_score: float
    risk_multiplier: float
    driver_scores: dict[str, float]   # trend, vol, corr, liquidity
    subsequent_1d_return: float | None = None
    subsequent_5d_return: float | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _since_iso(lookback_days: int) -> str:
    """Return ISO timestamp for `lookback_days` ago."""
    dt = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _parse_ts(ts: str) -> datetime:
    """Parse ISO timestamp from ledger entries."""
    ts = ts.replace("Z", "+00:00")
    return datetime.fromisoformat(ts)


def _safe_float(val: Any, default: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _safe_int(val: Any, default: int = 0) -> int:
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Collection functions
# ---------------------------------------------------------------------------

def collect_trades(
    strategy_id: str | None = None,
    lookback_days: int = 90,
) -> list[TradeRecord]:
    """Harvest closed trades from POSITION_CLOSED ledger events.

    Args:
        strategy_id: Filter to specific strategy. None = all strategies.
        lookback_days: How far back to look (default 90 days).

    Returns:
        List of TradeRecord sorted by exit_ts ascending.
    """
    pf = {"strategy_id": strategy_id} if strategy_id else None
    events = ledger.query(
        event_types=[C.EventType.POSITION_CLOSED],
        payload_filter=pf,
    )

    cutoff = _since_iso(lookback_days)
    records: list[TradeRecord] = []

    for ev in events:
        ts = ev.get("timestamp", "")
        if ts < cutoff:
            continue

        p = ev.get("payload", {})
        entry_price = _safe_float(p.get("entry_price"))
        exit_price = _safe_float(p.get("exit_price"))
        stop_price = _safe_float(p.get("stop_price"))
        tp_price = _safe_float(p.get("tp_price"))

        # Compute stop/TP distances
        side = p.get("side", "LONG")
        if side == "LONG":
            stop_dist = abs(entry_price - stop_price) if stop_price else 0.0
            tp_dist = abs(tp_price - entry_price) if tp_price else 0.0
        else:
            stop_dist = abs(stop_price - entry_price) if stop_price else 0.0
            tp_dist = abs(entry_price - tp_price) if tp_price else 0.0

        realized_pnl = _safe_float(p.get("realized_pnl"))
        # R-multiple: PnL divided by risk at stop
        contracts = _safe_int(p.get("contracts"), 1)
        point_value = _safe_float(p.get("point_value_usd", 50.0))
        risk_at_stop = stop_dist * contracts * point_value if stop_dist > 0 else 1.0
        realized_r = realized_pnl / risk_at_stop if risk_at_stop != 0 else 0.0

        records.append(TradeRecord(
            strategy_id=p.get("strategy_id", ""),
            symbol=p.get("symbol", ""),
            side=side,
            entry_price=entry_price,
            exit_price=exit_price,
            stop_price=stop_price,
            tp_price=tp_price,
            stop_dist=round(stop_dist, 4),
            tp_dist=round(tp_dist, 4),
            realized_pnl=round(realized_pnl, 2),
            realized_r=round(realized_r, 4),
            slippage_ticks=_safe_float(p.get("slippage_ticks")),
            bars_held=_safe_int(p.get("bars_held")),
            contracts=contracts,
            regime_score_at_entry=_safe_float(p.get("regime_score_at_entry")),
            health_score_at_entry=_safe_float(p.get("health_score_at_entry")),
            posture_at_entry=p.get("posture_at_entry", "NORMAL"),
            entry_ts=p.get("entry_ts", ts),
            exit_ts=p.get("exit_ts", ts),
            trigger=p.get("trigger", "UNKNOWN"),
        ))

    records.sort(key=lambda r: r.exit_ts)
    return records


def collect_regime_snapshots(
    lookback_days: int = 90,
) -> list[RegimeSnapshot]:
    """Harvest regime observations from REGIME_COMPUTED events.

    Subsequent returns are left as None — they need to be joined
    from price data by the caller if needed.
    """
    events = ledger.query(event_types=[C.EventType.REGIME_COMPUTED])
    cutoff = _since_iso(lookback_days)
    snapshots: list[RegimeSnapshot] = []

    for ev in events:
        ts = ev.get("timestamp", "")
        if ts < cutoff:
            continue

        p = ev.get("payload", {})
        drivers = p.get("drivers", {})
        driver_scores = {
            "trend": _safe_float(drivers.get("trend", {}).get("score",
                                 drivers.get("trend_score"))),
            "vol": _safe_float(drivers.get("vol", {}).get("score",
                               drivers.get("vol_score"))),
            "corr": _safe_float(drivers.get("corr", {}).get("score",
                                drivers.get("corr_score"))),
            "liquidity": _safe_float(drivers.get("liquidity", {}).get("score",
                                     drivers.get("liquidity_score"))),
        }

        snapshots.append(RegimeSnapshot(
            timestamp=ts,
            regime_score=_safe_float(p.get("regime_score")),
            risk_multiplier=_safe_float(p.get("risk_multiplier")),
            driver_scores=driver_scores,
        ))

    snapshots.sort(key=lambda s: s.timestamp)
    return snapshots


def collect_missed_opportunities(
    strategy_id: str | None = None,
    lookback_days: int = 90,
) -> list[dict]:
    """Harvest missed opportunities from MISSED_OPPORTUNITY events.

    Returns raw payload dicts for flexible downstream analysis.
    """
    pf = {"strategy_id": strategy_id} if strategy_id else None
    events = ledger.query(
        event_types=[C.EventType.MISSED_OPPORTUNITY],
        payload_filter=pf,
    )
    cutoff = _since_iso(lookback_days)
    return [
        ev.get("payload", {})
        for ev in events
        if ev.get("timestamp", "") >= cutoff
    ]


def collect_denied_intents(
    strategy_id: str | None = None,
    lookback_days: int = 90,
) -> list[dict]:
    """Harvest denied intents from INTENT_DENIED events.

    Returns raw payload dicts including denial reasons.
    """
    pf = {"strategy_id": strategy_id} if strategy_id else None
    events = ledger.query(
        event_types=[C.EventType.INTENT_DENIED],
        payload_filter=pf,
    )
    cutoff = _since_iso(lookback_days)
    return [
        ev.get("payload", {})
        for ev in events
        if ev.get("timestamp", "") >= cutoff
    ]
