"""Microstructure analytics: book imbalance and absorption detection.

Pure functions — no IB or Redis dependency.
"""
from __future__ import annotations


def book_imbalance(dom: dict) -> float:
    """Compute normalized book imbalance from depth-of-market data.

    Returns a float in [-1.0, +1.0]:
      - Positive: buy pressure (bid_sizes dominate)
      - Negative: sell pressure (ask_sizes dominate)
      - 0.0: balanced or empty data

    Raw ratio thresholds: >1.3 = buy pressure, <0.7 = sell pressure.
    Normalized linearly: ratio mapped from [0.0, 2.0] to [-1.0, +1.0],
    clamped to bounds.
    """
    bid_sizes = dom.get("bid_sizes", [])
    ask_sizes = dom.get("ask_sizes", [])

    total_bid = sum(bid_sizes)
    total_ask = sum(ask_sizes)

    if total_bid == 0 and total_ask == 0:
        return 0.0

    if total_ask == 0:
        return 1.0  # infinite bid dominance

    ratio = total_bid / total_ask

    # Normalize: ratio 1.0 -> 0.0, ratio 2.0+ -> +1.0, ratio 0.0 -> -1.0
    normalized = (ratio - 1.0)
    return max(-1.0, min(1.0, normalized))


def detect_absorption(ticks: list[dict], dom: dict) -> dict:
    """Detect absorption: large resting order absorbing trades without price moving.

    Absorption criteria:
    1. Top-of-book size on one side > 3x the average size across all levels on that side
    2. Multiple trades hit that level (same price) without price breaking through
    3. Strength = total absorbed volume / resting order size

    Args:
        ticks: List of trade ticks with price, size, side, timestamp.
        dom: Depth of market with bid_sizes, ask_sizes, bid_prices, ask_prices.

    Returns:
        {"detected": bool, "side": "BUY"|"SELL"|None, "level": float|None, "strength": float}
    """
    result = {"detected": False, "side": None, "level": None, "strength": 0.0}

    if not ticks:
        return result

    bid_sizes = dom.get("bid_sizes", [])
    ask_sizes = dom.get("ask_sizes", [])
    bid_prices = dom.get("bid_prices", [])
    ask_prices = dom.get("ask_prices", [])

    if not bid_sizes or not ask_sizes:
        return result

    # Check bid side for absorption (large bid absorbing sells)
    bid_absorption = _check_side_absorption(
        top_size=bid_sizes[0],
        all_sizes=bid_sizes,
        top_price=bid_prices[0] if bid_prices else None,
        ticks=ticks,
        aggressor_side="SELL",
        resting_side="BUY",
    )

    # Check ask side for absorption (large ask absorbing buys)
    ask_absorption = _check_side_absorption(
        top_size=ask_sizes[0],
        all_sizes=ask_sizes,
        top_price=ask_prices[0] if ask_prices else None,
        ticks=ticks,
        aggressor_side="BUY",
        resting_side="SELL",
    )

    # Return the stronger absorption if both detected
    if bid_absorption["detected"] and ask_absorption["detected"]:
        return bid_absorption if bid_absorption["strength"] >= ask_absorption["strength"] else ask_absorption
    if bid_absorption["detected"]:
        return bid_absorption
    if ask_absorption["detected"]:
        return ask_absorption

    return result


def _check_side_absorption(
    top_size: int,
    all_sizes: list[int],
    top_price: float | None,
    ticks: list[dict],
    aggressor_side: str,
    resting_side: str,
) -> dict:
    """Check one side of the book for absorption."""
    result = {"detected": False, "side": None, "level": None, "strength": 0.0}

    if top_price is None or len(all_sizes) < 2:
        return result

    avg_size = sum(all_sizes) / len(all_sizes)

    # Criterion 1: top-of-book > 3x average
    if top_size <= avg_size * 3:
        return result

    # Criterion 2: multiple aggressor trades at the resting price
    hits_at_level = [
        t for t in ticks
        if t.get("price") == top_price and t.get("side") == aggressor_side
    ]

    if len(hits_at_level) < 3:
        return result

    # Criterion 3: compute strength = total absorbed volume / resting size
    total_absorbed = sum(t.get("size", 0) for t in hits_at_level)
    strength = total_absorbed / top_size if top_size > 0 else 0.0

    return {
        "detected": True,
        "side": resting_side,
        "level": top_price,
        "strength": round(strength, 4),
    }
