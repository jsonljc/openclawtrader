#!/usr/bin/env python3
"""Live market data adapter — Phase 4.

Replace the body of get_all_snapshots() with your live provider (Polygon, Alpaca,
broker API, etc.). Snapshot shape must match spec 5.2 (MarketSnapshot).

This default implementation uses the stub and marks data_source=live for testing.
Set OPENCLAW_DATA_SOURCE=live to use this path.
"""

from __future__ import annotations
from typing import Any

from data_stub import get_all_snapshots as _stub_snapshots


def get_all_snapshots(force_signal: bool = False) -> dict[str, dict]:
    """
    Return live snapshots for ES + NQ.
    Default: stub-derived with data_source=live for pipeline testing.
    Replace with real API calls for production.
    """
    snapshots = _stub_snapshots(force_signal=force_signal)
    for sym, snap in snapshots.items():
        snap["data_source"] = "live"
        snap.setdefault("data_quality", {})["source"] = "live"
    return snapshots
