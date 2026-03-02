#!/usr/bin/env python3
"""Data source dispatch — Phase 4.

Uses OPENCLAW_DATA_SOURCE=stub|live|ib to choose provider.
Live: use data_live (plug in real API); fallback to stub on import/error.
IB: use data_ib (Interactive Brokers via ib_insync); fallback to stub on error.
"""

from __future__ import annotations
import logging
import os

logger = logging.getLogger(__name__)


def get_all_snapshots(force_signal: bool = False) -> dict[str, dict]:
    """Return snapshots from configured source (stub, live, or ib)."""
    src = os.environ.get("OPENCLAW_DATA_SOURCE", "stub").strip().lower()
    if src == "ib":
        try:
            from data_ib import get_all_snapshots as ib_snapshots
            return ib_snapshots(force_signal=force_signal)
        except Exception as exc:
            logger.warning("IB data fetch failed, falling back to stub: %s", exc)
            from data_stub import get_all_snapshots as stub_snapshots
            return stub_snapshots(force_signal=force_signal)
    if src == "live":
        try:
            from data_live import get_all_snapshots as live_snapshots
            return live_snapshots(force_signal=force_signal)
        except Exception:
            from data_stub import get_all_snapshots as stub_snapshots
            return stub_snapshots(force_signal=force_signal)
    from data_stub import get_all_snapshots as stub_snapshots
    return stub_snapshots(force_signal=force_signal)
