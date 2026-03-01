#!/usr/bin/env python3
"""Data source dispatch — Phase 4.

Uses OPENCLAW_DATA_SOURCE=stub|live to choose provider.
Live: use data_live (plug in real API); fallback to stub on import/error.
"""

from __future__ import annotations
import os


def get_all_snapshots(force_signal: bool = False) -> dict[str, dict]:
    """Return snapshots from configured source (stub or live)."""
    src = os.environ.get("OPENCLAW_DATA_SOURCE", "stub").strip().lower()
    if src == "live":
        try:
            from data_live import get_all_snapshots as live_snapshots
            return live_snapshots(force_signal=force_signal)
        except Exception:
            from data_stub import get_all_snapshots as stub_snapshots
            return stub_snapshots(force_signal=force_signal)
    from data_stub import get_all_snapshots as stub_snapshots
    return stub_snapshots(force_signal=force_signal)
