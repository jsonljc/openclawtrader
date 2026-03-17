"""Temporal decay for signal and analytics values.

Pure function — no IB or Redis dependency.
"""
from __future__ import annotations

from datetime import datetime, timezone


def apply_decay(
    value: float,
    onset_time: str,
    half_life_minutes: float,
    now: str | None = None,
) -> float:
    """Apply exponential decay to a value based on elapsed time.

    Formula: value * (0.5 ** (elapsed_minutes / half_life_minutes))

    Args:
        value: The raw score to decay.
        onset_time: ISO timestamp when the signal/value originated.
        half_life_minutes: Time in minutes for the value to halve.
        now: Current ISO timestamp. If None, uses datetime.now(UTC).

    Returns:
        The decayed value (same sign as input, magnitude decreased).
    """
    if value == 0.0:
        return 0.0

    onset_dt = datetime.fromisoformat(onset_time.replace("Z", "+00:00"))

    if now is not None:
        now_dt = datetime.fromisoformat(now.replace("Z", "+00:00"))
    else:
        now_dt = datetime.now(timezone.utc)

    elapsed_seconds = (now_dt - onset_dt).total_seconds()
    elapsed_minutes = max(elapsed_seconds / 60.0, 0.0)

    decay_factor = 0.5 ** (elapsed_minutes / half_life_minutes)
    return value * decay_factor
