#!/usr/bin/env python3
"""Deterministic ID generators — spec Section 4.

All IDs include a UTC timestamp and a per-process monotonic counter so
they are globally unique and sort chronologically.
"""

from __future__ import annotations
from datetime import datetime, timezone
import os
from threading import Lock

_counters: dict[str, int] = {}
_lock = Lock()


def _stamp() -> str:
    """YYYYMMDD_HHMMSS_mmm in UTC (includes seconds + milliseconds)."""
    now = datetime.now(timezone.utc)
    ms = now.microsecond // 1000
    return now.strftime("%Y%m%d_%H%M%S") + f"_{ms:03d}"


def _seq(prefix: str) -> int:
    with _lock:
        _counters[prefix] = _counters.get(prefix, 0) + 1
        return _counters[prefix]


_pid = os.getpid()


def make_run_id() -> str:
    """RUN_YYYYMMDD_HHMMSS_mmm_PID_NNNN — unique per evaluation cycle."""
    return f"RUN_{_stamp()}_{_pid}_{_seq('RUN'):04d}"


def make_intent_id() -> str:
    """TI_YYYYMMDD_HHMMSS_mmm_PID_NNNN"""
    return f"TI_{_stamp()}_{_pid}_{_seq('TI'):04d}"


def make_approval_id() -> str:
    """AP_YYYYMMDD_HHMMSS_mmm_PID_NNNN"""
    return f"AP_{_stamp()}_{_pid}_{_seq('AP'):04d}"


def make_execution_id() -> str:
    """EX_YYYYMMDD_HHMMSS_mmm_PID_NNNN"""
    return f"EX_{_stamp()}_{_pid}_{_seq('EX'):04d}"


def make_idempotency_key(approval_id: str, attempt: int = 1) -> str:
    """IK_{approval_id}_{attempt}"""
    return f"IK_{approval_id}_{attempt}"


def make_position_id() -> str:
    """POS_YYYYMMDD_HHMMSS_mmm_PID_NNNN"""
    return f"POS_{_stamp()}_{_pid}_{_seq('POS'):04d}"


def make_order_id(prefix: str = "ORD") -> str:
    """ORD_STOP_YYYYMMDD_HHMMSS_mmm_PID_NNNN"""
    return f"{prefix}_{_stamp()}_{_pid}_{_seq(prefix):04d}"


def reset_counters() -> None:
    """Reset all sequence counters. Use only in tests."""
    with _lock:
        _counters.clear()
