#!/usr/bin/env python3
"""Operator alerting — Phase 4.

Logs to OPENCLAW_ALERT_LOG (default: data/alerts.log).
Optional POST to OPENCLAW_ALERT_WEBHOOK_URL (JSON body).
"""

from __future__ import annotations
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import request

_DATA_DIR = Path(os.environ.get("OPENCLAW_DATA", Path.home() / "openclaw-trader" / "data"))
_ALERT_LOG = Path(os.environ.get("OPENCLAW_ALERT_LOG", _DATA_DIR / "alerts.log"))
_WEBHOOK_URL = os.environ.get("OPENCLAW_ALERT_WEBHOOK_URL", "").strip()


def alert(level: str, message: str, payload: dict[str, Any] | None = None) -> None:
    """
    Emit an operator alert.
    level: HALT | DEGRADED | CAUTION | DEFENSIVE | WARNING | INFO
    """
    payload = payload or {}
    now = datetime.now(timezone.utc).isoformat()
    record = {
        "ts": now,
        "level": level,
        "message": message,
        **payload,
    }
    line = json.dumps(record) + "\n"
    try:
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(_ALERT_LOG, "a") as f:
            f.write(line)
    except OSError:
        pass
    if _WEBHOOK_URL:
        try:
            req = request.Request(
                _WEBHOOK_URL,
                data=json.dumps(record).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            request.urlopen(req, timeout=5)
        except Exception:
            pass
