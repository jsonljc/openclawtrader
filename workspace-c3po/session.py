#!/usr/bin/env python3
"""Session Model Agent — clock-based intraday session detection.

Provides granular session classification for intraday trading,
with aggression modifiers for each session window.

Sessions (all times Eastern):
    PREMARKET       8:00 - 9:30    0.4x  (thin liquidity, no entries normally)
    US_OPEN         9:30 - 10:00   0.8x  (volatile open, reduced size)
    MORNING_DRIVE   10:00 - 11:30  1.0x  (prime trading window)
    MIDDAY          11:30 - 13:30  0.5x  (lunch chop, minimal activity)
    AFTERNOON       13:30 - 15:00  0.9x  (second wind, good setups)
    MOC_CLOSE       15:00 - 16:00  0.5x  (MOC imbalances, reduced)
    EXTENDED        16:00 - 18:00  0.2x  (post-market, avoid)
    CLOSED          18:00 - 8:00   0.0x  (market closed / globex overnight)

Reuses contract_calendar.py for timezone handling patterns.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta, time as dtime
from typing import Any

try:
    import zoneinfo
    ET = zoneinfo.ZoneInfo("America/New_York")
except ImportError:
    ET = timezone(timedelta(hours=-5))


# ---------------------------------------------------------------------------
# Session constants
# ---------------------------------------------------------------------------

class IntraSession:
    """Intraday session names."""
    PREMARKET     = "PREMARKET"
    US_OPEN       = "US_OPEN"
    MORNING_DRIVE = "MORNING_DRIVE"
    MIDDAY        = "MIDDAY"
    AFTERNOON     = "AFTERNOON"
    MOC_CLOSE     = "MOC_CLOSE"
    EXTENDED      = "EXTENDED"
    CLOSED        = "CLOSED"

    # Sessions where new entries are allowed
    TRADEABLE = frozenset({US_OPEN, MORNING_DRIVE, MIDDAY, AFTERNOON, MOC_CLOSE})

    # Sessions where entries are suppressed by default
    SUPPRESSED = frozenset({PREMARKET, EXTENDED, CLOSED})


# Aggression modifier per session
SESSION_MODIFIERS: dict[str, float] = {
    IntraSession.PREMARKET:     0.4,
    IntraSession.US_OPEN:       0.8,
    IntraSession.MORNING_DRIVE: 1.0,
    IntraSession.MIDDAY:        0.5,
    IntraSession.AFTERNOON:     0.9,
    IntraSession.MOC_CLOSE:     0.5,
    IntraSession.EXTENDED:      0.2,
    IntraSession.CLOSED:        0.0,
}

# Session time windows (Eastern) — (start_hour, start_min, end_hour, end_min)
_SESSION_WINDOWS: list[tuple[str, dtime, dtime]] = [
    (IntraSession.CLOSED,        dtime(0, 0),   dtime(8, 0)),
    (IntraSession.PREMARKET,     dtime(8, 0),   dtime(9, 30)),
    (IntraSession.US_OPEN,       dtime(9, 30),  dtime(10, 0)),
    (IntraSession.MORNING_DRIVE, dtime(10, 0),  dtime(11, 30)),
    (IntraSession.MIDDAY,        dtime(11, 30), dtime(13, 30)),
    (IntraSession.AFTERNOON,     dtime(13, 30), dtime(15, 0)),
    (IntraSession.MOC_CLOSE,     dtime(15, 0),  dtime(16, 0)),
    (IntraSession.EXTENDED,      dtime(16, 0),  dtime(18, 0)),
    (IntraSession.CLOSED,        dtime(18, 0),  dtime(23, 59, 59)),
]


# ---------------------------------------------------------------------------
# Session detection
# ---------------------------------------------------------------------------

def detect_intra_session(now_utc: datetime | None = None) -> str:
    """
    Classify the current time into an intraday session.

    Args:
        now_utc: Current UTC time. Defaults to now.

    Returns:
        IntraSession constant string.
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)

    now_et = now_utc.astimezone(ET)
    weekday = now_et.weekday()  # 0=Mon, 6=Sun

    # Weekend: CLOSED
    if weekday == 5:  # Saturday
        return IntraSession.CLOSED
    if weekday == 6:  # Sunday
        if now_et.time() < dtime(18, 0):
            return IntraSession.CLOSED
        # Sunday 18:00+ = globex open, treat as PREMARKET for next day
        return IntraSession.CLOSED  # Still pre-open for Sunday night

    t = now_et.time()
    for session_name, start, end in _SESSION_WINDOWS:
        if start <= t < end:
            return session_name

    return IntraSession.CLOSED


def get_session_modifier(session: str) -> float:
    """Return the aggression modifier for a given session."""
    return SESSION_MODIFIERS.get(session, 0.0)


def is_rth(now_utc: datetime | None = None) -> bool:
    """Is the market currently in Regular Trading Hours (9:30-16:00 ET)?"""
    session = detect_intra_session(now_utc)
    return session in (
        IntraSession.US_OPEN,
        IntraSession.MORNING_DRIVE,
        IntraSession.MIDDAY,
        IntraSession.AFTERNOON,
        IntraSession.MOC_CLOSE,
    )


def minutes_into_session(now_utc: datetime | None = None) -> int:
    """Minutes elapsed since RTH open (9:30 ET). Returns 0 if pre-open."""
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    now_et = now_utc.astimezone(ET)
    rth_open = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
    if now_et < rth_open:
        return 0
    return int((now_et - rth_open).total_seconds() / 60)


def minutes_until_close(now_utc: datetime | None = None) -> int:
    """Minutes remaining until RTH close (16:00 ET). Returns 0 if after close."""
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    now_et = now_utc.astimezone(ET)
    rth_close = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
    if now_et >= rth_close:
        return 0
    return int((rth_close - now_et).total_seconds() / 60)


def get_session_report(now_utc: datetime | None = None) -> dict[str, Any]:
    """
    Full session context report.

    Returns:
        {session, modifier, is_rth, minutes_into_session, minutes_until_close}
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    session = detect_intra_session(now_utc)
    return {
        "session": session,
        "modifier": get_session_modifier(session),
        "is_rth": is_rth(now_utc),
        "minutes_into_session": minutes_into_session(now_utc),
        "minutes_until_close": minutes_until_close(now_utc),
        "is_tradeable": session in IntraSession.TRADEABLE,
    }
