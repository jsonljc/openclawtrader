"""Bridge between Redis signal streams and Sentinel evaluation."""
from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

_TIER_MODIFIERS = {
    "HALT": 0.0,
    "REDUCE": 0.50,
    "CAUTION": 0.75,
}

_TIER_PRIORITY = {"HALT": 0, "REDUCE": 1, "CAUTION": 2, "MONITOR": 3, "IGNORE": 4}

# Events that require human approval before automated DIRECTIONAL trades.
# Loaded lazily from ResponseMatrix on first use.
_HUMAN_REQUIRED_EVENTS: set[str] | None = None


def _get_human_required_events() -> set[str]:
    """Return set of event_types where human_required=true in any instrument."""
    global _HUMAN_REQUIRED_EVENTS
    if _HUMAN_REQUIRED_EVENTS is not None:
        return _HUMAN_REQUIRED_EVENTS
    try:
        from openclaw_trader.signals.response_matrix import ResponseMatrix
        matrix = ResponseMatrix()
        result = set()
        for event_type in matrix.events():
            responses = matrix.get_all(event_type)
            for _sym, resp in responses.items():
                if resp.get("human_required"):
                    result.add(event_type)
                    break
        _HUMAN_REQUIRED_EVENTS = result
    except Exception:
        _HUMAN_REQUIRED_EVENTS = set()
    return _HUMAN_REQUIRED_EVENTS


def check_external_signals(
    symbol: str,
    redis_client: Any | None = None,
) -> dict[str, Any]:
    """Read Redis streams and return signal modifiers for this instrument.

    Returns:
        {
            "has_signal": bool,
            "tier": str,
            "sizing_modifier": float (1.0 if no signal),
            "stop_modifier": float (1.0 or 1.25 for CAUTION),
            "halt": bool,
            "active_signals": list[dict],
            "polymarket_confidence_mod": float (1.0 default),
            "human_required": bool,
        }
    """
    default = {
        "has_signal": False,
        "tier": "NONE",
        "sizing_modifier": 1.0,
        "stop_modifier": 1.0,
        "halt": False,
        "active_signals": [],
        "polymarket_confidence_mod": 1.0,
        "human_required": False,
    }

    if redis_client is None:
        return default

    try:
        from openclaw_trader.signals.signal_publisher import read_active_signals, NEWS_STREAM, POLYMARKET_STREAM
    except ImportError:
        logger.debug("Signal publisher not available -- skipping external signals")
        return default

    try:
        news_signals = read_active_signals(redis_client, NEWS_STREAM, count=50)
        poly_signals = read_active_signals(redis_client, POLYMARKET_STREAM, count=50)
    except Exception as exc:
        logger.warning(f"Redis read failed -- skipping external signals: {exc}")
        return default

    relevant_news = [
        s for s in news_signals if symbol in s.get("instruments", [])
    ]
    relevant_poly = [
        s for s in poly_signals if symbol in s.get("instruments", [])
    ]

    if not relevant_news and not relevant_poly:
        return default

    worst_tier = "MONITOR"
    human_required = False
    hr_events = _get_human_required_events()
    for sig in relevant_news:
        tier = sig.get("tier", "MONITOR")
        if _TIER_PRIORITY.get(tier, 99) < _TIER_PRIORITY.get(worst_tier, 99):
            worst_tier = tier
        event_type = sig.get("event_type", "")
        if event_type in hr_events:
            human_required = True

    sizing_mod = _TIER_MODIFIERS.get(worst_tier, 1.0)
    stop_mod = 1.25 if worst_tier == "CAUTION" else 1.0
    is_halt = worst_tier == "HALT"

    poly_mod = 1.0
    if relevant_poly:
        try:
            from openclaw_trader.signals.polymarket_collector import compute_regime_confidence_mod
            poly_mod = compute_regime_confidence_mod(relevant_poly, instrument=symbol)
        except ImportError:
            pass

    return {
        "has_signal": True,
        "tier": worst_tier,
        "sizing_modifier": sizing_mod,
        "stop_modifier": stop_mod,
        "halt": is_halt,
        "active_signals": relevant_news + relevant_poly,
        "polymarket_confidence_mod": poly_mod,
        "human_required": human_required,
    }
