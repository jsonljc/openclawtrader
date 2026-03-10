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
_TELEGRAM_BOT_TOKEN = os.environ.get("OPENCLAW_TELEGRAM_BOT_TOKEN", "").strip()
_TELEGRAM_CHAT_ID = os.environ.get("OPENCLAW_TELEGRAM_CHAT_ID", "").strip()


def _send_telegram(level: str, message: str, payload: dict[str, Any]) -> None:
    """Send alert to Telegram bot. Never raises — alerting must never crash trading."""
    if not _TELEGRAM_BOT_TOKEN or not _TELEGRAM_CHAT_ID:
        return
    emoji = {
        "HALT": "\U0001f6a8",        # rotating light
        "DEFENSIVE": "\u26a0\ufe0f", # warning
        "CAUTION": "\u26a1",         # lightning
        "WARNING": "\U0001f4cb",     # clipboard
        "INFO": "\u2139\ufe0f",      # info
        "RECOVERY": "\u2705",        # check mark
    }.get(level, "\U0001f4cc")       # pushpin
    text = f"{emoji} *{level}*\n{message}"
    if payload:
        for k, v in payload.items():
            text += f"\n\u2022 {k}: `{v}`"
    url = f"https://api.telegram.org/bot{_TELEGRAM_BOT_TOKEN}/sendMessage"
    data = json.dumps({
        "chat_id": _TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
    }).encode()
    try:
        req = request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
        request.urlopen(req, timeout=10)
    except Exception:
        pass  # Never let alerting crash the trading system


def alert(level: str, message: str, payload: dict[str, Any] | None = None) -> None:
    """
    Emit an operator alert.
    level: HALT | DEGRADED | CAUTION | DEFENSIVE | WARNING | INFO | RECOVERY
    Logs to file, optionally sends to webhook and Telegram.
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
    # Telegram
    _send_telegram(level, message, payload)
