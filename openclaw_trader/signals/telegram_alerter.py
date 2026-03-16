"""Telegram Bot API alerter for news and Polymarket signals."""
from __future__ import annotations

import os
import time
import urllib.request
import urllib.parse
import json
from typing import Any

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
MAX_MESSAGES_PER_HOUR = 20
_RATE_LIMIT_KEY = "openclaw:telegram_rate"

# In-memory fallback when Redis is unavailable.
_SEND_LOG: list[float] = []

# Optional Redis client set by init_redis() for persistent rate limiting.
_redis_client = None


def init_redis(redis_client) -> None:
    """Set a Redis client for persistent rate limiting across restarts."""
    global _redis_client
    _redis_client = redis_client


def _rate_ok() -> bool:
    if _redis_client:
        try:
            count = _redis_client.incr(_RATE_LIMIT_KEY)
            if count == 1:
                _redis_client.expire(_RATE_LIMIT_KEY, 3600)
            return count <= MAX_MESSAGES_PER_HOUR
        except Exception:
            pass  # Fall through to in-memory
    now = time.time()
    cutoff = now - 3600
    _SEND_LOG[:] = [t for t in _SEND_LOG if t > cutoff]
    return len(_SEND_LOG) < MAX_MESSAGES_PER_HOUR


def send_message(text: str, token: str = "", chat_id: str = "") -> bool:
    tk = token or BOT_TOKEN
    cid = chat_id or CHAT_ID
    if not tk or not cid:
        return False
    if not _rate_ok():
        return False

    url = f"https://api.telegram.org/bot{tk}/sendMessage"
    payload = json.dumps({
        "chat_id": cid,
        "text": text,
        "parse_mode": "HTML",
    }).encode()

    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            _SEND_LOG.append(time.time())
            return resp.status == 200
    except Exception:
        return False


def format_news_alert(signal: dict[str, Any]) -> str | None:
    tier = signal.get("tier", "MONITOR")
    if tier not in ("HALT", "DIRECTIONAL_LONG", "DIRECTIONAL_SHORT", "REDUCE"):
        return None

    source = signal.get("source_id", "UNKNOWN")
    headline = signal.get("headline", "")
    instruments = signal.get("instruments", [])

    if tier == "HALT":
        instr_text = " ".join(instruments)
        return (
            f"<b>HALT</b> -- {signal.get('event_type', source)}\n"
            f"Source: {source}\n"
            f"<i>{headline}</i>\n"
            f"Instruments blocked: {instr_text}\n"
            f"Action: New entries blocked. Stops tightened."
        )
    elif tier in ("DIRECTIONAL_LONG", "DIRECTIONAL_SHORT"):
        direction = "LONG" if "LONG" in tier else "SHORT"
        sym = instruments[0] if instruments else "?"
        return (
            f"<b>DIRECTIONAL_{direction}</b> -- {sym}\n"
            f"Source: {source}\n"
            f"<i>{headline}</i>\n"
            f"Waiting for confirmation bar..."
        )
    elif tier == "REDUCE":
        return (
            f"<b>REDUCE</b>\n"
            f"Source: {source}\n"
            f"<i>{headline}</i>\n"
            f"Sizing cut to 50% on: {', '.join(instruments)}"
        )
    return None


def format_polymarket_alert(signal: dict[str, Any]) -> str | None:
    sig_type = signal.get("type", "")
    strength = signal.get("strength", "LOW")

    if sig_type == "PROBABILITY_DRIFT" and strength == "HIGH":
        drift = signal.get("drift_magnitude", 0)
        market = signal.get("market_question", "")
        instruments = signal.get("instruments", [])
        return (
            f"<b>POLYMARKET DRIFT</b>\n"
            f"Market: {market}\n"
            f"Drift: {drift:+.0f}pp in &lt;4 hours\n"
            f"Instruments: {', '.join(instruments)}"
        )
    elif sig_type == "FRESH_WALLET":
        market = signal.get("market_question", "")
        value = signal.get("value_usd", 0)
        return (
            f"<b>POLYMARKET FRESH WALLET</b>\n"
            f"Market: {market}\n"
            f"Trade size: ${value:,.0f}"
        )
    return None
