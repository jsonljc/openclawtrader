#!/usr/bin/env python3
"""Pre-event suppression — macro calendar gate.

Provides an EventCalendar that loads Tier-1 and Tier-2 macro events
and checks whether trading should be suppressed for a given instrument.

Tier-1 events (FOMC, NFP, CPI): 20 min pre / 10 min post blackout.
Tier-2 events (ISM, PPI, Retail Sales, etc.): 10 min pre / 5 min post blackout.

Instrument-specific suppression:
    EIA Petroleum -> CL only
    Treasury Auction/Refunding -> ZB only
    All other events -> all instruments
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

try:
    import zoneinfo
    ET = zoneinfo.ZoneInfo("America/New_York")
except ImportError:
    ET = timezone(timedelta(hours=-5))

_REPO_ROOT = Path(__file__).parent.parent
_DATA_DIR = Path(os.environ.get("OPENCLAW_DATA", _REPO_ROOT / "data"))
_CALENDAR_PATH = _DATA_DIR / "event_calendar.json"


# ---------------------------------------------------------------------------
# Event tier definitions
# ---------------------------------------------------------------------------

TIER_1_EVENTS = frozenset({
    "FOMC", "FOMC_DECISION", "FOMC_MINUTES",
    "NFP", "NONFARM_PAYROLLS",
    "CPI", "CPI_CORE",
})

TIER_2_EVENTS = frozenset({
    "ISM_MFG", "ISM_SERVICES",
    "PPI", "PPI_CORE",
    "RETAIL_SALES",
    "GDP", "GDP_ADVANCE", "GDP_PRELIMINARY", "GDP_FINAL",
    "INITIAL_CLAIMS", "JOBLESS_CLAIMS",
    "DURABLE_GOODS",
    "PCE", "CORE_PCE",
    "EIA_PETROLEUM",
    "TREASURY_AUCTION", "TREASURY_REFUNDING",
    "FED_CHAIR_SPEECH",
    "ECB_DECISION",
})

# Instrument-specific events: event_name -> set of affected symbols
INSTRUMENT_SPECIFIC = {
    "EIA_PETROLEUM": {"CL", "MCL"},
    "TREASURY_AUCTION": {"ZB"},
    "TREASURY_REFUNDING": {"ZB"},
}

# Blackout windows (pre_minutes, post_minutes)
TIER_1_BLACKOUT = (20, 10)
TIER_2_BLACKOUT = (10, 5)


# ---------------------------------------------------------------------------
# EventCalendar
# ---------------------------------------------------------------------------

class EventCalendar:
    """Loads and queries macro event schedule for trade suppression."""

    def __init__(self, events: list[dict] | None = None):
        if events is not None:
            self._events = events
        else:
            self._events = self._load_calendar()

    @staticmethod
    def _load_calendar() -> list[dict]:
        try:
            with open(_CALENDAR_PATH) as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    def _get_tier(self, event_name: str) -> int:
        upper = event_name.upper().replace(" ", "_")
        if upper in TIER_1_EVENTS:
            return 1
        if upper in TIER_2_EVENTS:
            return 2
        return 0

    def _affects_instrument(self, event_name: str, symbol: str) -> bool:
        upper = event_name.upper().replace(" ", "_")
        if upper in INSTRUMENT_SPECIFIC:
            return symbol.upper() in INSTRUMENT_SPECIFIC[upper]
        return True  # non-specific events affect all instruments

    def check_suppression(
        self,
        now_utc: datetime | None = None,
        symbol: str = "ES",
    ) -> dict[str, Any]:
        """
        Check if trading should be suppressed for a given instrument.

        Returns:
            {
                "suppressed": bool,
                "event_name": str | None,
                "tier": int,
                "event_time": str | None,
                "blackout_start": str | None,
                "blackout_end": str | None,
                "minutes_to_event": float | None,
            }
        """
        if now_utc is None:
            now_utc = datetime.now(timezone.utc)

        for event in self._events:
            event_name = event.get("name", "")
            tier = self._get_tier(event_name)
            if tier == 0:
                continue

            if not self._affects_instrument(event_name, symbol):
                continue

            event_time_str = event.get("time_utc", "")
            try:
                event_time = datetime.fromisoformat(
                    event_time_str.replace("Z", "+00:00")
                )
            except (ValueError, AttributeError):
                continue

            pre_min, post_min = TIER_1_BLACKOUT if tier == 1 else TIER_2_BLACKOUT
            blackout_start = event_time - timedelta(minutes=pre_min)
            blackout_end = event_time + timedelta(minutes=post_min)

            if blackout_start <= now_utc <= blackout_end:
                minutes_to_event = (event_time - now_utc).total_seconds() / 60.0
                return {
                    "suppressed": True,
                    "event_name": event_name,
                    "tier": tier,
                    "event_time": event_time.isoformat(),
                    "blackout_start": blackout_start.isoformat(),
                    "blackout_end": blackout_end.isoformat(),
                    "minutes_to_event": round(minutes_to_event, 1),
                }

        return {
            "suppressed": False,
            "event_name": None,
            "tier": 0,
            "event_time": None,
            "blackout_start": None,
            "blackout_end": None,
            "minutes_to_event": None,
        }

    def upcoming_events(
        self,
        now_utc: datetime | None = None,
        hours_ahead: int = 24,
    ) -> list[dict]:
        """Return events within the next N hours."""
        if now_utc is None:
            now_utc = datetime.now(timezone.utc)
        cutoff = now_utc + timedelta(hours=hours_ahead)
        result = []
        for event in self._events:
            try:
                t = datetime.fromisoformat(
                    event.get("time_utc", "").replace("Z", "+00:00")
                )
            except (ValueError, AttributeError):
                continue
            if now_utc <= t <= cutoff:
                result.append({
                    **event,
                    "tier": self._get_tier(event.get("name", "")),
                    "minutes_until": round((t - now_utc).total_seconds() / 60.0, 1),
                })
        return sorted(result, key=lambda e: e.get("minutes_until", 0))


# Module-level singleton (lazy)
_calendar: EventCalendar | None = None


def get_calendar() -> EventCalendar:
    global _calendar
    if _calendar is None:
        _calendar = EventCalendar()
    return _calendar


def reload_calendar() -> EventCalendar:
    global _calendar
    _calendar = EventCalendar()
    return _calendar


def check_event_suppression(
    now_utc: datetime | None = None,
    symbol: str = "ES",
) -> dict[str, Any]:
    """Convenience function: check if symbol is in a blackout window."""
    return get_calendar().check_suppression(now_utc, symbol)
