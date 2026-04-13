from __future__ import annotations

from datetime import datetime
from typing import Any


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _is_long_side(side: Any) -> bool | None:
    normalized = str(side).upper()
    if normalized in {"BUY", "LONG"}:
        return True
    if normalized in {"SELL", "SHORT"}:
        return False
    return None


def classify_blocked_trade_outcome(blocked: dict[str, Any], bars_5m: list[dict[str, Any]]) -> str:
    blocked_ts = _parse_timestamp(blocked.get("bar_ts"))
    if blocked_ts is None:
        return "unresolved"

    is_long = _is_long_side(blocked.get("side"))
    if is_long is None:
        return "unresolved"

    stop_price = blocked.get("stop_price")
    target_price = blocked.get("target_price")
    if not isinstance(stop_price, (int, float)) or not isinstance(target_price, (int, float)):
        return "unresolved"

    for bar in bars_5m:
        bar_ts = _parse_timestamp(bar.get("t"))
        if bar_ts is None or bar_ts <= blocked_ts:
            continue

        high = bar.get("h")
        low = bar.get("l")
        if not isinstance(high, (int, float)) or not isinstance(low, (int, float)):
            continue

        if is_long:
            if low <= stop_price:
                return "good_block"
            if high >= target_price:
                return "bad_block"
        else:
            if high >= stop_price:
                return "good_block"
            if low <= target_price:
                return "bad_block"

    return "unresolved"


def build_scorecard(blocked_events: list[dict[str, Any]], bars_5m: list[dict[str, Any]]) -> dict[str, int]:
    outcomes = [classify_blocked_trade_outcome(event, bars_5m) for event in blocked_events]
    return {
        "blocked_good": outcomes.count("good_block"),
        "blocked_bad": outcomes.count("bad_block"),
        "blocked_unresolved": outcomes.count("unresolved"),
    }
