#!/usr/bin/env python3
"""Append-only ledger with SHA-256 hash chain — spec Section 3.4.

Each entry's checksum covers:
    previous_checksum | timestamp | event_type | json(payload, sort_keys=True)

The ledger is never modified; only appended to.
"""

from __future__ import annotations
import fcntl
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

_DATA_DIR = Path(os.environ.get("OPENCLAW_DATA", Path.home() / "openclaw-trader" / "data"))
_LEDGER_PATH = _DATA_DIR / "ledger.jsonl"
_lock = Lock()

# Cached tail state to avoid O(n) _read_tail() on every append
_cached_last_seq: int | None = None
_cached_last_checksum: str | None = None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _ensure_dir() -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)


def _compute_checksum(prev: str, timestamp: str, event_type: str, payload: dict) -> str:
    raw = f"{prev}|{timestamp}|{event_type}|{json.dumps(payload, sort_keys=True)}"
    return "sha256:" + hashlib.sha256(raw.encode()).hexdigest()


def _read_tail() -> tuple[int, str]:
    """Return (last_seq, last_checksum). Returns (0, 'genesis') if empty."""
    if not _LEDGER_PATH.exists():
        return 0, "genesis"
    last_seq, last_checksum = 0, "genesis"
    with open(_LEDGER_PATH) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
                last_seq = e.get("ledger_seq", last_seq)
                last_checksum = e.get("checksum", last_checksum)
            except json.JSONDecodeError:
                continue
    return last_seq, last_checksum


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def append(event_type: str, run_id: str, ref_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Append one event to the ledger and return the completed entry."""
    global _cached_last_seq, _cached_last_checksum
    _ensure_dir()
    with _lock:
        with open(_LEDGER_PATH, "a") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                # Use cached values if available, otherwise read tail
                if _cached_last_seq is not None and _cached_last_checksum is not None:
                    last_seq, prev_checksum = _cached_last_seq, _cached_last_checksum
                else:
                    last_seq, prev_checksum = _read_tail()
                ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
                seq = last_seq + 1
                checksum = _compute_checksum(prev_checksum, ts, event_type, payload)
                entry: dict[str, Any] = {
                    "ledger_seq": seq,
                    "timestamp":  ts,
                    "event_type": event_type,
                    "run_id":     run_id,
                    "ref_id":     ref_id,
                    "payload":    payload,
                    "checksum":   checksum,
                }
                fh.write(json.dumps(entry) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
                # Update cache
                _cached_last_seq = seq
                _cached_last_checksum = checksum
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)
        return entry


def query(
    event_types: list[str] | None = None,
    ref_id: str | None = None,
    run_id: str | None = None,
    payload_filter: dict[str, Any] | None = None,
    since_seq: int = 0,
    limit: int = 10_000,
) -> list[dict[str, Any]]:
    """Read ledger entries matching all supplied filters, in order."""
    if not _LEDGER_PATH.exists():
        return []
    type_set = set(event_types) if event_types else None
    results: list[dict[str, Any]] = []
    with open(_LEDGER_PATH) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if e.get("ledger_seq", 0) <= since_seq:
                continue
            if type_set and e.get("event_type") not in type_set:
                continue
            if ref_id and e.get("ref_id") != ref_id:
                continue
            if run_id and e.get("run_id") != run_id:
                continue
            if payload_filter:
                p = e.get("payload", {})
                if any(p.get(k) != v for k, v in payload_filter.items()):
                    continue
            results.append(e)
            if len(results) >= limit:
                break
    return results


def verify_integrity() -> tuple[bool, str]:
    """Verify the complete SHA-256 hash chain. Returns (ok, message)."""
    if not _LEDGER_PATH.exists():
        return True, "Ledger empty — OK"
    prev = "genesis"
    count = 0
    with open(_LEDGER_PATH) as fh:
        for line_no, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                return False, f"Line {line_no}: invalid JSON"
            expected = _compute_checksum(prev, e["timestamp"], e["event_type"], e["payload"])
            if e.get("checksum") != expected:
                return False, f"Hash chain broken at ledger_seq={e.get('ledger_seq', '?')} (line {line_no})"
            prev = e["checksum"]
            count += 1
    return True, f"Ledger integrity OK ({count} entries)"


def get_last_seq() -> int:
    seq, _ = _read_tail()
    return seq
