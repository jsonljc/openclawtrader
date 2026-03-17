"""Signal integrator: counts aligned vs opposing signals for a given direction.

Pure functions — no IB or Redis dependency.
"""
from __future__ import annotations


def count_aligned_signals(signals: list[dict], direction: str) -> dict:
    """Count how many active signals align with vs oppose the given direction.

    Args:
        signals: List of signal dicts (from Redis). Each should have a "direction"
                 field ("LONG" or "SHORT"). Signals without a "direction" field are
                 ignored.
        direction: The direction to compare against ("LONG" or "SHORT").

    Returns:
        {"aligned": int, "opposing": int}
    """
    aligned = 0
    opposing = 0

    for sig in signals:
        sig_dir = sig.get("direction")
        if sig_dir is None:
            continue
        if sig_dir == direction:
            aligned += 1
        else:
            opposing += 1

    return {"aligned": aligned, "opposing": opposing}
