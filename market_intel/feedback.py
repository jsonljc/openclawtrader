"""Conviction feedback loop — log snapshots at entry, link to trade outcomes."""
from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _default_ledger_path() -> Path:
    return Path(os.environ.get("OPENCLAW_DATA", _REPO_ROOT / "data")) / "ledger.jsonl"


def _next_seq(ledger_path: Path) -> int:
    """Return next ledger sequence number."""
    seq = 0
    if ledger_path.exists():
        with open(ledger_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    seq = max(seq, entry.get("ledger_seq", 0))
                except json.JSONDecodeError:
                    continue
    return seq + 1


def log_conviction_at_entry(
    position_id: str,
    symbol: str,
    conviction_data: dict,
    ledger_path: Path | None = None,
) -> None:
    """Append a CONVICTION_SNAPSHOT event to the ledger JSONL file."""
    path = ledger_path or _default_ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    event = {
        "ledger_seq": _next_seq(path),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_type": "CONVICTION_SNAPSHOT",
        "run_id": str(uuid.uuid4())[:8],
        "ref_id": position_id,
        "payload": {
            "symbol": symbol,
            **conviction_data,
        },
    }

    with open(path, "a") as f:
        f.write(json.dumps(event) + "\n")


def link_outcome(
    position_id: str,
    realized_pnl: float,
    ledger_path: Path | None = None,
) -> dict | None:
    """Find the CONVICTION_SNAPSHOT for a position and return combined data."""
    path = ledger_path or _default_ledger_path()
    if not path.exists():
        return None

    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if (
                entry.get("event_type") == "CONVICTION_SNAPSHOT"
                and entry.get("ref_id") == position_id
            ):
                payload = entry.get("payload", {})
                return {
                    "conviction_at_entry": payload.get("conviction"),
                    "pattern": payload.get("matched_pattern"),
                    "realized_pnl": realized_pnl,
                }

    return None
