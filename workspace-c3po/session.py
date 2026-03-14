#!/usr/bin/env python3
"""Session Model Agent — clock-based intraday session detection.

Provides granular session classification for intraday trading,
with aggression modifiers for each session window.

Per-instrument session groups:
    equity_index  ES, NQ, MES, MNQ   RTH 9:30-16:00 ET
    energy        CL, MCL            RTH 9:00-14:30 ET
    metals        GC, MGC            RTH 8:20-13:30 ET
    rates         ZB                 RTH 8:20-15:00 ET

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


# ---------------------------------------------------------------------------
# Per-instrument session windows (all times Eastern)
# ---------------------------------------------------------------------------

INSTRUMENT_SESSIONS: dict[str, dict[str, Any]] = {
    "equity_index": {
        "symbols": {"ES", "NQ", "MES", "MNQ"},
        "windows": [
            (IntraSession.CLOSED,        dtime(0, 0),   dtime(8, 0)),
            (IntraSession.PREMARKET,     dtime(8, 0),   dtime(9, 32)),
            (IntraSession.US_OPEN,       dtime(9, 32),  dtime(10, 0)),
            (IntraSession.MORNING_DRIVE, dtime(10, 0),  dtime(11, 30)),
            (IntraSession.MIDDAY,        dtime(11, 30), dtime(13, 30)),
            (IntraSession.AFTERNOON,     dtime(13, 30), dtime(15, 0)),
            (IntraSession.MOC_CLOSE,     dtime(15, 0),  dtime(15, 45)),
            (IntraSession.EXTENDED,      dtime(15, 45), dtime(18, 0)),
            (IntraSession.CLOSED,        dtime(18, 0),  dtime(23, 59, 59)),
        ],
        "rth": (dtime(9, 32), dtime(15, 45)),
    },
    "energy": {
        "symbols": {"CL", "MCL"},
        "windows": [
            (IntraSession.CLOSED,        dtime(0, 0),   dtime(8, 0)),
            (IntraSession.PREMARKET,     dtime(8, 0),   dtime(9, 0)),
            (IntraSession.US_OPEN,       dtime(9, 0),   dtime(9, 30)),
            (IntraSession.MORNING_DRIVE, dtime(9, 30),  dtime(11, 0)),
            (IntraSession.MIDDAY,        dtime(11, 0),  dtime(12, 30)),
            (IntraSession.MOC_CLOSE,     dtime(12, 30), dtime(14, 30)),
            (IntraSession.EXTENDED,      dtime(14, 30), dtime(18, 0)),
            (IntraSession.CLOSED,        dtime(18, 0),  dtime(23, 59, 59)),
        ],
        "rth": (dtime(9, 0), dtime(14, 30)),
    },
    "metals": {
        "symbols": {"GC", "MGC"},
        "windows": [
            (IntraSession.CLOSED,        dtime(0, 0),   dtime(7, 30)),
            (IntraSession.PREMARKET,     dtime(7, 30),  dtime(8, 20)),
            (IntraSession.US_OPEN,       dtime(8, 20),  dtime(9, 0)),
            (IntraSession.MORNING_DRIVE, dtime(9, 0),   dtime(10, 30)),
            (IntraSession.MIDDAY,        dtime(10, 30), dtime(12, 0)),
            (IntraSession.AFTERNOON,     dtime(12, 0),  dtime(15, 0)),
            (IntraSession.MOC_CLOSE,     dtime(15, 0),  dtime(17, 0)),
            (IntraSession.EXTENDED,      dtime(17, 0),  dtime(18, 0)),
            (IntraSession.CLOSED,        dtime(18, 0),  dtime(23, 59, 59)),
        ],
        "rth": (dtime(8, 20), dtime(17, 0)),
    },
    "rates": {
        "symbols": {"ZB"},
        "windows": [
            (IntraSession.CLOSED,        dtime(0, 0),   dtime(7, 30)),
            (IntraSession.PREMARKET,     dtime(7, 30),  dtime(8, 20)),
            (IntraSession.US_OPEN,       dtime(8, 20),  dtime(9, 0)),
            (IntraSession.MORNING_DRIVE, dtime(9, 0),   dtime(10, 30)),
            (IntraSession.MIDDAY,        dtime(10, 30), dtime(13, 0)),
            (IntraSession.AFTERNOON,     dtime(13, 0),  dtime(14, 30)),
            (IntraSession.MOC_CLOSE,     dtime(14, 30), dtime(15, 0)),
            (IntraSession.EXTENDED,      dtime(15, 0),  dtime(18, 0)),
            (IntraSession.CLOSED,        dtime(18, 0),  dtime(23, 59, 59)),
        ],
        "rth": (dtime(8, 20), dtime(15, 0)),
    },
}

# Build reverse lookup: symbol -> session group key
_SYMBOL_TO_GROUP: dict[str, str] = {}
for _group_key, _group_cfg in INSTRUMENT_SESSIONS.items():
    for _sym in _group_cfg["symbols"]:
        _SYMBOL_TO_GROUP[_sym] = _group_key


def _resolve_session_group(symbol: str) -> str:
    """Map a symbol to its session group key. Defaults to equity_index."""
    return _SYMBOL_TO_GROUP.get(symbol, "equity_index")


# ---------------------------------------------------------------------------
# Session detection
# ---------------------------------------------------------------------------

def detect_intra_session(now_utc: datetime | None = None, symbol: str = "ES") -> str:
    """
    Classify the current time into an intraday session.

    Args:
        now_utc: Current UTC time. Defaults to now.
        symbol:  Instrument symbol (e.g. "ES", "CL", "GC", "ZB").

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

    group = _resolve_session_group(symbol)
    windows = INSTRUMENT_SESSIONS[group]["windows"]

    t = now_et.time()
    for session_name, start, end in windows:
        if start <= t < end:
            return session_name

    return IntraSession.CLOSED


def get_session_modifier(session: str) -> float:
    """Return the aggression modifier for a given session."""
    return SESSION_MODIFIERS.get(session, 0.0)


def is_rth(now_utc: datetime | None = None, symbol: str = "ES") -> bool:
    """Is the market currently in Regular Trading Hours for the given instrument?"""
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)

    now_et = now_utc.astimezone(ET)
    weekday = now_et.weekday()
    if weekday in (5, 6) and (weekday == 5 or now_et.time() < dtime(18, 0)):
        return False

    group = _resolve_session_group(symbol)
    rth_start, rth_end = INSTRUMENT_SESSIONS[group]["rth"]
    t = now_et.time()
    return rth_start <= t < rth_end


def is_any_rth(now_utc: datetime | None = None) -> bool:
    """Is ANY instrument's RTH currently active?"""
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    for group in INSTRUMENT_SESSIONS:
        # Pick any symbol from the group to check
        sym = next(iter(INSTRUMENT_SESSIONS[group]["symbols"]))
        if is_rth(now_utc, sym):
            return True
    return False


def minutes_into_session(now_utc: datetime | None = None, symbol: str = "ES") -> int:
    """Minutes elapsed since RTH open for the given instrument. Returns 0 if pre-open."""
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    now_et = now_utc.astimezone(ET)

    group = _resolve_session_group(symbol)
    rth_start, _ = INSTRUMENT_SESSIONS[group]["rth"]
    rth_open = now_et.replace(hour=rth_start.hour, minute=rth_start.minute,
                              second=0, microsecond=0)
    if now_et < rth_open:
        return 0
    return int((now_et - rth_open).total_seconds() / 60)


def minutes_until_close(now_utc: datetime | None = None, symbol: str = "ES") -> int:
    """Minutes remaining until RTH close for the given instrument. Returns 0 if after close."""
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    now_et = now_utc.astimezone(ET)

    group = _resolve_session_group(symbol)
    _, rth_end = INSTRUMENT_SESSIONS[group]["rth"]
    rth_close = now_et.replace(hour=rth_end.hour, minute=rth_end.minute,
                               second=0, microsecond=0)
    if now_et >= rth_close:
        return 0
    return int((rth_close - now_et).total_seconds() / 60)


def get_session_report(now_utc: datetime | None = None, symbol: str = "ES") -> dict[str, Any]:
    """
    Full session context report.

    Returns:
        {session, modifier, is_rth, minutes_into_session, minutes_until_close}
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    session = detect_intra_session(now_utc, symbol)
    return {
        "session": session,
        "modifier": get_session_modifier(session),
        "is_rth": is_rth(now_utc, symbol),
        "minutes_into_session": minutes_into_session(now_utc, symbol),
        "minutes_until_close": minutes_until_close(now_utc, symbol),
        "is_tradeable": session in IntraSession.TRADEABLE,
    }
