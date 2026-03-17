"""Volume profile analytics: relative volume and time-of-day quality.

Pure functions — no IB or Redis dependency.
"""
from __future__ import annotations


def compute_relative_volume(current_volume: int, avg_volume_at_tod: int) -> float:
    """Compute ratio of current volume to historical average at this time-of-day.

    Returns:
        float: ratio (>1.5 = high participation, <0.7 = thin market, 0.0 if avg is zero)
    """
    if avg_volume_at_tod <= 0:
        return 0.0
    return current_volume / avg_volume_at_tod


def get_tod_quality(hour: int, minute: int) -> float:
    """Return time-of-day conviction quality multiplier (ET hours).

    Windows (from design doc Section 4.3):
      09:30-09:45 -> 0.6  (open chop)
      09:45-11:30 -> 1.0  (morning momentum)
      11:30-13:00 -> 0.7  (lunch chop)
      13:00-14:30 -> 1.0  (afternoon session)
      14:30-15:00 -> 0.8  (MOC rebalancing — default; momentum uses 1.1)
      15:00-15:45 -> 0.9  (close)
      Outside RTH -> 0.5
    """
    t = hour * 60 + minute  # minutes since midnight

    rth_open = 9 * 60 + 30   # 09:30
    open_chop_end = 9 * 60 + 45  # 09:45
    morning_end = 11 * 60 + 30   # 11:30
    lunch_end = 13 * 60          # 13:00
    afternoon_end = 14 * 60 + 30  # 14:30
    moc_end = 15 * 60            # 15:00
    close_end = 15 * 60 + 45     # 15:45

    if t < rth_open or t >= close_end:
        return 0.5
    if t < open_chop_end:
        return 0.6
    if t < morning_end:
        return 1.0
    if t < lunch_end:
        return 0.7
    if t < afternoon_end:
        return 1.0
    if t < moc_end:
        return 0.8
    # 15:00 - 15:45
    return 0.9
