"""Bridge between Redis conviction data and Brain/Sentinel consumers."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# Conviction → sizing modifier mapping
_SIZING_MAP = [
    (70, 1.0),    # >70 → full size
    (50, 0.75),   # 50-70 → reduced
    (30, 0.5),    # 30-50 → half
    (0, 0.25),    # <30 → quarter
]

# Data older than this many seconds is considered stale
_STALE_THRESHOLD_S = 120  # 2 minutes (quotes polled every 5-10s, conviction every 10s)


def _default_result() -> dict[str, Any]:
    return {
        "has_data": False,
        "conviction": None,
        "hold_conviction": None,
        "clarity": None,
        "matched_pattern": None,
        "regime_transition": {},
        "sizing_modifier": 1.0,
        "factors": [],
        "timestamp": None,
    }


def _conviction_to_sizing(conviction: int, clarity: str | None) -> float:
    """Map conviction score to sizing modifier. LOW clarity blocks entry."""
    if clarity == "LOW":
        return 0.0
    for threshold, modifier in _SIZING_MAP:
        if conviction > threshold:
            return modifier
    return 0.25


def get_conviction(
    symbol: str,
    direction: str = "LONG",
    redis_client: Any | None = None,
) -> dict[str, Any]:
    """Return conviction data for the given instrument and direction.

    Reads from Redis key ``market_intel:conviction:{symbol}``.
    Returns a safe default when Redis is unavailable or data is missing/stale.
    """
    result = _default_result()

    if redis_client is None:
        return result

    try:
        raw = redis_client.get(f"market_intel:conviction:{symbol}")
        if raw is None:
            return result

        data = json.loads(raw)

        # Staleness check
        ts_str = data.get("timestamp")
        if ts_str:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            age_s = (datetime.now(timezone.utc) - ts).total_seconds()
            if age_s > _STALE_THRESHOLD_S:
                logger.debug("market_intel stale for %s (%.0fs old)", symbol, age_s)
                return result

        # Direction-specific conviction
        dir_key = "long_conviction" if direction.upper() == "LONG" else "short_conviction"
        conviction = data.get(dir_key)
        if conviction is None:
            return result

        clarity = data.get("clarity")
        sizing_mod = _conviction_to_sizing(conviction, clarity)

        result.update({
            "has_data": True,
            "conviction": conviction,
            "hold_conviction": data.get("hold_conviction"),
            "clarity": clarity,
            "matched_pattern": data.get("matched_pattern"),
            "regime_transition": data.get("regime_transition", {}),
            "sizing_modifier": sizing_mod,
            "factors": data.get("top_factors", []),
            "timestamp": ts_str,
        })

    except Exception as exc:
        logger.warning("market_intel bridge error for %s: %s", symbol, exc)
        return _default_result()

    return result
