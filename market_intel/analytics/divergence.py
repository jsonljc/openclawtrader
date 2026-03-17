"""
Divergence detector — cross-asset relationship monitoring.

Tracks 6 key pairs:
- ES vs VIX (inverse)
- ES vs NQ (correlated)
- CL vs DXY (inverse)
- GC vs DXY (inverse)
- GC vs TNX (inverse)
- ES vs HYG (correlated)

Returns divergence scores from -1.0 (bearish) to +1.0 (bullish).
"""

import numpy as np
from typing import Dict, List


def compute_divergences(
    quotes: Dict[str, dict],
    history: Dict[str, List[float]]
) -> Dict[str, float]:
    """
    Compute cross-asset divergences.

    Args:
        quotes: Current price quotes, e.g. {"ES": {"last": 5400}, "VIX": {"last": 18}}
        history: Recent price history per symbol, e.g. {"ES": [5380, 5390, 5400]}
                 Last element should match current quote.

    Returns:
        Dict with 6 divergence scores, each in range [-1.0, +1.0]:
        - Negative = bearish divergence
        - Zero = normal relationship
        - Positive = bullish divergence
    """
    # Define the 6 pairs: (symbol1, symbol2, relationship_type)
    # relationship_type: "inverse" or "correlated"
    pairs = [
        ("ES", "VIX", "inverse"),
        ("ES", "NQ", "correlated"),
        ("CL", "DXY", "inverse"),
        ("GC", "DXY", "inverse"),
        ("GC", "TNX", "inverse"),
        ("ES", "HYG", "correlated"),
    ]

    results = {}

    for sym1, sym2, rel_type in pairs:
        key = f"{sym1.lower()}_{sym2.lower()}"

        # Check data availability
        if sym1 not in history or sym2 not in history:
            results[key] = 0.0
            continue

        hist1 = history[sym1]
        hist2 = history[sym2]

        if len(hist1) < 2 or len(hist2) < 2:
            results[key] = 0.0
            continue

        # Compute 15-min return (last price vs price from 15 min ago)
        # Assume history contains prices at regular intervals
        ret1 = _compute_return(hist1)
        ret2 = _compute_return(hist2)

        # Check for zero movement
        if abs(ret1) < 1e-6 and abs(ret2) < 1e-6:
            results[key] = 0.0
            continue

        # Compute divergence based on relationship type
        div_score = _compute_divergence_score(ret1, ret2, rel_type)

        # Cap at [-1.0, +1.0]
        results[key] = np.clip(div_score, -1.0, 1.0)

    return results


def _compute_return(prices: List[float]) -> float:
    """Compute percentage return from recent prices."""
    if len(prices) < 2:
        return 0.0

    # Use first and last price in the window
    old_price = prices[0]
    new_price = prices[-1]

    if old_price == 0:
        return 0.0

    return (new_price - old_price) / old_price


def _compute_divergence_score(ret1: float, ret2: float, rel_type: str) -> float:
    """
    Compute divergence score based on relationship type.

    For inverse pairs (e.g., ES vs VIX):
        - Both moving same direction = divergence
        - If ES up and VIX up = bearish divergence (negative score)
        - If ES down and VIX down = bullish divergence (positive score)

    For correlated pairs (e.g., ES vs NQ):
        - Moving opposite = divergence
        - If ES up and NQ down = bearish divergence (negative score)
        - If ES down and NQ up = bullish divergence (positive score)

    Returns:
        Score in approximate range [-1.0, +1.0]
        Magnitude scaled by size of returns
    """
    if rel_type == "inverse":
        # Both should move opposite. If they move together, that's a divergence.
        # Product of returns: positive = moving same direction (divergence)
        product = ret1 * ret2

        if product > 0:  # Divergence detected
            # If ret1 > 0 (asset up) and ret2 > 0 (inverse indicator also up)
            # -> bearish divergence (negative score)
            # If ret1 < 0 (asset down) and ret2 < 0 (inverse indicator also down)
            # -> bullish divergence (positive score)

            # Scale by magnitude of returns (use average)
            magnitude = (abs(ret1) + abs(ret2)) / 2.0
            # Normalize to ~[-1, +1] range (assuming returns typically < 0.1 or 10%)
            magnitude = min(magnitude * 10.0, 1.0)

            # Sign: negative ret1 means bullish divergence
            sign = -np.sign(ret1)
            return sign * magnitude
        else:
            # Normal inverse relationship
            return 0.0

    elif rel_type == "correlated":
        # Both should move together. If they move opposite, that's a divergence.
        product = ret1 * ret2

        if product < 0:  # Divergence detected (opposite directions)
            # If ret1 > 0 (asset up) and ret2 < 0 (correlated down)
            # -> bearish divergence (negative score)
            # If ret1 < 0 (asset down) and ret2 > 0 (correlated up)
            # -> bullish divergence (positive score)

            magnitude = (abs(ret1) + abs(ret2)) / 2.0
            magnitude = min(magnitude * 10.0, 1.0)

            # Sign: negative ret1 means bullish divergence
            sign = -np.sign(ret1)
            return sign * magnitude
        else:
            # Normal correlated relationship
            return 0.0

    else:
        return 0.0
