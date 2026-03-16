"""Publish classified signals to Redis Streams and ledger."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from redis import Redis

_ROOT = str(Path(__file__).parent.parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
from shared import contracts as C
from shared import ledger

NEWS_STREAM = "news_signals"
POLYMARKET_STREAM = "polymarket_signals"


def publish_news_signal(
    redis_client: "Redis",
    source_id: str,
    headline: str,
    summary: str,
    tier: str,
    direction: str | None,
    confidence: float,
    instruments: list[str],
    duration_minutes: int = 30,
    classification: str = "KEYWORD",
    source_url: str = "",
    event_type: str | None = None,
    run_id: str = "",
) -> str:
    """Publish a news signal to Redis Stream. Returns the stream entry ID."""
    now = datetime.now(timezone.utc).isoformat()
    fields = {
        "source_id": source_id,
        "headline": headline[:200],
        "summary": summary[:300],
        "tier": tier,
        "direction": direction or "",
        "confidence": str(confidence),
        "instruments": json.dumps(instruments),
        "duration_minutes": str(duration_minutes),
        "classification": classification,
        "source_url": source_url,
        "event_type": event_type or "",
        "timestamp": now,
    }
    entry_id = redis_client.xadd(NEWS_STREAM, fields, maxlen=1000)

    ledger.append(C.EventType.NEWS_SIGNAL, run_id or "SIGNAL_DAEMON", source_id, {
        "source_id": source_id,
        "headline": headline[:200],
        "tier": tier,
        "direction": direction,
        "instruments": instruments,
        "confidence": confidence,
        "event_type": event_type,
    })

    return entry_id


def publish_polymarket_signal(
    redis_client: "Redis",
    signal_type: str,
    market_question: str,
    instruments: list[str],
    direction: str | None = None,
    strength: str = "MEDIUM",
    value_usd: float | None = None,
    drift_magnitude: float | None = None,
    duration_minutes: int = 120,
    run_id: str = "",
) -> str:
    """Publish a Polymarket signal to Redis Stream."""
    now = datetime.now(timezone.utc)
    fields = {
        "type": signal_type,
        "market_question": market_question[:150],
        "instruments": json.dumps(instruments),
        "direction": direction or "",
        "strength": strength,
        "value_usd": str(value_usd) if value_usd is not None else "",
        "drift_magnitude": str(drift_magnitude) if drift_magnitude is not None else "",
        "timestamp": now.isoformat(),
        "expires_at": (now + timedelta(minutes=duration_minutes)).isoformat(),
        "duration_minutes": str(duration_minutes),
    }
    entry_id = redis_client.xadd(POLYMARKET_STREAM, fields, maxlen=500)

    ledger.append(C.EventType.POLYMARKET_SIGNAL, run_id or "SIGNAL_DAEMON", signal_type, {
        "type": signal_type,
        "market_question": market_question[:150],
        "instruments": instruments,
        "strength": strength,
        "drift_magnitude": drift_magnitude,
    })

    return entry_id


def read_active_signals(
    redis_client: "Redis",
    stream: str = NEWS_STREAM,
    count: int = 50,
) -> list[dict[str, Any]]:
    """Read recent signals from a Redis Stream, filtering expired ones."""
    now = datetime.now(timezone.utc)
    entries = redis_client.xrevrange(stream, count=count)
    active = []
    for entry_id, fields in entries:
        decoded = {}
        for k, v in fields.items():
            key = k.decode() if isinstance(k, bytes) else k
            val = v.decode() if isinstance(v, bytes) else v
            decoded[key] = val

        try:
            ts = datetime.fromisoformat(decoded.get("timestamp", ""))
            duration = int(decoded.get("duration_minutes", "30"))
            if (now - ts).total_seconds() > duration * 60:
                continue
        except (ValueError, TypeError):
            continue

        try:
            decoded["instruments"] = json.loads(decoded.get("instruments", "[]"))
        except json.JSONDecodeError:
            decoded["instruments"] = []

        for field in ("confidence", "value_usd", "drift_magnitude"):
            if decoded.get(field):
                try:
                    decoded[field] = float(decoded[field])
                except ValueError:
                    pass

        decoded["_entry_id"] = entry_id
        active.append(decoded)

    return active
