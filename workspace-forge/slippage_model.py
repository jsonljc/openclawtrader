#!/usr/bin/env python3
"""Slippage model for futures paper trading — spec Section 7.6.

Covers:
- Market order slippage estimation (volume, vol, session factors)
- Limit order fill probability
- Expected value (EV) ratio check
"""

from __future__ import annotations
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from shared.contracts import SessionState


# ---------------------------------------------------------------------------
# Market order slippage estimation — spec 7.6
# ---------------------------------------------------------------------------

def estimate_slippage_ticks(
    contracts: int,
    vol_pct: float,
    session: str,
    avg_book_depth: float,
    base_ticks: int = 1,
    is_session_boundary: bool = False,
) -> int:
    """
    Estimate market-order slippage in ticks.

    Args:
        contracts:          Number of contracts in the order.
        vol_pct:            Current vol percentile [0, 1].
        session:            One of SessionState constants.
        avg_book_depth:     Avg visible contracts on best levels.
        base_ticks:         Baseline slippage (default 1).
        is_session_boundary: True if within first/last 15 min of CORE session.

    Returns:
        Estimated slippage in ticks (integer, always >= 1).
    """
    # Volume factor: large orders relative to book depth increase slippage
    depth = max(avg_book_depth, 1.0)
    volume_factor = max(1.0, contracts / (depth * 0.01))

    # Volatility factor (piecewise per spec)
    if vol_pct < 0.50:
        vol_factor = 1.0
    elif vol_pct < 0.80:
        vol_factor = 1.0 + (vol_pct - 0.50) * 4.0   # 1.0 → 2.2
    else:
        vol_factor = 2.2 + (vol_pct - 0.80) * 15.0  # 2.2 → 5.2 at extreme

    # Session factor
    if is_session_boundary:
        session_factor = 2.0   # first/last 15 min of CORE
    elif session == SessionState.EXTENDED:
        session_factor = 1.5
    elif session == SessionState.PRE_OPEN:
        session_factor = 3.0
    elif session == SessionState.POST_CLOSE:
        session_factor = 2.0
    else:
        session_factor = 1.0   # CORE normal hours

    raw = base_ticks * volume_factor * vol_factor * session_factor
    return max(1, math.ceil(raw))


def slippage_usd(slippage_ticks: int, tick_value_usd: float, contracts: int) -> float:
    """Convert tick slippage to USD cost."""
    return round(slippage_ticks * tick_value_usd * contracts, 2)


# ---------------------------------------------------------------------------
# Limit order fill probability — spec 7.6
# ---------------------------------------------------------------------------

def limit_fill_probability(
    limit_price: float,
    mid_price: float,
    tick_size: float,
    vol_pct: float,
) -> float:
    """
    Probability that a limit order fills within the current bar.

    Args:
        limit_price:  The limit order price.
        mid_price:    Current mid-market price.
        tick_size:    Minimum price increment.
        vol_pct:      Current vol percentile [0, 1].

    Returns:
        Fill probability in [0.10, 0.99].
    """
    distance_ticks = abs(limit_price - mid_price) / max(tick_size, 1e-9)

    base_prob = 0.95  # at the mid
    decay_prob = base_prob * math.exp(-0.05 * distance_ticks)

    # Higher vol → price moves more → higher chance of reaching the limit
    vol_adj = 1.0 + (vol_pct - 0.5) * 0.3
    prob = decay_prob * vol_adj

    return max(0.10, min(0.99, prob))


# ---------------------------------------------------------------------------
# Expected value check — spec 7.6 / 7.5 Rule 11
# ---------------------------------------------------------------------------

def compute_ev_ratio(
    tp_distance_ticks: float,
    stop_distance_ticks: float,
    slippage_ticks: int,
) -> float:
    """
    EV ratio = (TP distance - slippage) / (stop distance + slippage).
    Must be >= ev_ratio_min (typically 0.5) to trade.
    """
    numerator   = max(0.0, tp_distance_ticks - slippage_ticks)
    denominator = stop_distance_ticks + slippage_ticks
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)
