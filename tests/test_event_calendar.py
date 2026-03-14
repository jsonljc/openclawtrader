#!/usr/bin/env python3
"""Unit tests for shared/event_calendar.py — event suppression logic.

Covers:
  - EventCalendar: Tier-1/Tier-2 classification
  - check_suppression(): blackout windows, instrument-specific routing
  - upcoming_events(): time window filtering
"""

from __future__ import annotations
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from shared.event_calendar import (
    EventCalendar,
    TIER_1_EVENTS,
    TIER_2_EVENTS,
    TIER_1_BLACKOUT,
    TIER_2_BLACKOUT,
    INSTRUMENT_SPECIFIC,
)


def _utc(year=2026, month=3, day=14, hour=12, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def _events(*items):
    return [{"name": n, "time_utc": t.isoformat()} for n, t in items]


# ── Tier classification ──

class TestTierClassification:
    def test_fomc_is_tier1(self):
        cal = EventCalendar(events=[])
        assert cal._get_tier("FOMC") == 1

    def test_nfp_is_tier1(self):
        cal = EventCalendar(events=[])
        assert cal._get_tier("NFP") == 1

    def test_cpi_is_tier1(self):
        cal = EventCalendar(events=[])
        assert cal._get_tier("CPI") == 1

    def test_ism_is_tier2(self):
        cal = EventCalendar(events=[])
        assert cal._get_tier("ISM_MFG") == 2

    def test_eia_is_tier2(self):
        cal = EventCalendar(events=[])
        assert cal._get_tier("EIA_PETROLEUM") == 2

    def test_unknown_is_tier0(self):
        cal = EventCalendar(events=[])
        assert cal._get_tier("RANDOM_EVENT") == 0


# ── Tier-1 blackout windows ──

class TestTier1Blackout:
    def test_suppressed_20min_before_fomc(self):
        event_time = _utc(hour=18, minute=0)
        cal = EventCalendar(events=_events(("FOMC", event_time)))
        now = event_time - timedelta(minutes=15)
        result = cal.check_suppression(now, "ES")
        assert result["suppressed"] is True
        assert result["tier"] == 1

    def test_suppressed_10min_after_fomc(self):
        event_time = _utc(hour=18, minute=0)
        cal = EventCalendar(events=_events(("FOMC", event_time)))
        now = event_time + timedelta(minutes=5)
        result = cal.check_suppression(now, "ES")
        assert result["suppressed"] is True

    def test_not_suppressed_25min_before_fomc(self):
        event_time = _utc(hour=18, minute=0)
        cal = EventCalendar(events=_events(("FOMC", event_time)))
        now = event_time - timedelta(minutes=25)
        result = cal.check_suppression(now, "ES")
        assert result["suppressed"] is False

    def test_not_suppressed_15min_after_fomc(self):
        event_time = _utc(hour=18, minute=0)
        cal = EventCalendar(events=_events(("FOMC", event_time)))
        now = event_time + timedelta(minutes=15)
        result = cal.check_suppression(now, "ES")
        assert result["suppressed"] is False


# ── Tier-2 blackout windows ──

class TestTier2Blackout:
    def test_suppressed_5min_before_ism(self):
        event_time = _utc(hour=14, minute=0)
        cal = EventCalendar(events=_events(("ISM_MFG", event_time)))
        now = event_time - timedelta(minutes=5)
        result = cal.check_suppression(now, "ES")
        assert result["suppressed"] is True
        assert result["tier"] == 2

    def test_not_suppressed_15min_before_ism(self):
        event_time = _utc(hour=14, minute=0)
        cal = EventCalendar(events=_events(("ISM_MFG", event_time)))
        now = event_time - timedelta(minutes=15)
        result = cal.check_suppression(now, "ES")
        assert result["suppressed"] is False

    def test_not_suppressed_10min_after_ism(self):
        event_time = _utc(hour=14, minute=0)
        cal = EventCalendar(events=_events(("ISM_MFG", event_time)))
        now = event_time + timedelta(minutes=10)
        result = cal.check_suppression(now, "ES")
        assert result["suppressed"] is False


# ── Instrument-specific suppression ──

class TestInstrumentSpecific:
    def test_eia_suppresses_cl(self):
        event_time = _utc(hour=14, minute=30)
        cal = EventCalendar(events=_events(("EIA_PETROLEUM", event_time)))
        now = event_time - timedelta(minutes=5)
        result = cal.check_suppression(now, "CL")
        assert result["suppressed"] is True

    def test_eia_does_not_suppress_es(self):
        event_time = _utc(hour=14, minute=30)
        cal = EventCalendar(events=_events(("EIA_PETROLEUM", event_time)))
        now = event_time - timedelta(minutes=5)
        result = cal.check_suppression(now, "ES")
        assert result["suppressed"] is False

    def test_eia_suppresses_mcl(self):
        event_time = _utc(hour=14, minute=30)
        cal = EventCalendar(events=_events(("EIA_PETROLEUM", event_time)))
        now = event_time - timedelta(minutes=5)
        result = cal.check_suppression(now, "MCL")
        assert result["suppressed"] is True

    def test_treasury_suppresses_zb(self):
        event_time = _utc(hour=17, minute=0)
        cal = EventCalendar(events=_events(("TREASURY_AUCTION", event_time)))
        now = event_time - timedelta(minutes=5)
        result = cal.check_suppression(now, "ZB")
        assert result["suppressed"] is True

    def test_treasury_does_not_suppress_es(self):
        event_time = _utc(hour=17, minute=0)
        cal = EventCalendar(events=_events(("TREASURY_AUCTION", event_time)))
        now = event_time - timedelta(minutes=5)
        result = cal.check_suppression(now, "ES")
        assert result["suppressed"] is False

    def test_cpi_suppresses_all_instruments(self):
        event_time = _utc(hour=12, minute=30)
        cal = EventCalendar(events=_events(("CPI", event_time)))
        now = event_time - timedelta(minutes=10)
        for sym in ("ES", "NQ", "CL", "GC", "ZB"):
            result = cal.check_suppression(now, sym)
            assert result["suppressed"] is True, f"{sym} should be suppressed during CPI"


# ── Result structure ──

class TestResultStructure:
    def test_suppressed_result_fields(self):
        event_time = _utc(hour=12, minute=30)
        cal = EventCalendar(events=_events(("NFP", event_time)))
        now = event_time - timedelta(minutes=10)
        result = cal.check_suppression(now, "ES")
        assert "suppressed" in result
        assert "event_name" in result
        assert "tier" in result
        assert "minutes_to_event" in result
        assert result["event_name"] == "NFP"

    def test_not_suppressed_result_fields(self):
        cal = EventCalendar(events=[])
        result = cal.check_suppression(_utc(), "ES")
        assert result["suppressed"] is False
        assert result["event_name"] is None
        assert result["tier"] == 0


# ── upcoming_events ──

class TestUpcomingEvents:
    def test_returns_events_within_window(self):
        now = _utc(hour=10)
        events = _events(
            ("NFP", _utc(hour=12, minute=30)),
            ("CPI", _utc(hour=8)),  # in the past
        )
        cal = EventCalendar(events=events)
        upcoming = cal.upcoming_events(now, hours_ahead=6)
        assert len(upcoming) == 1
        assert upcoming[0]["name"] == "NFP"

    def test_sorted_by_time(self):
        now = _utc(hour=10)
        events = _events(
            ("PPI", _utc(hour=14)),
            ("NFP", _utc(hour=12, minute=30)),
        )
        cal = EventCalendar(events=events)
        upcoming = cal.upcoming_events(now, hours_ahead=6)
        assert upcoming[0]["name"] == "NFP"
        assert upcoming[1]["name"] == "PPI"

    def test_empty_when_no_events(self):
        cal = EventCalendar(events=[])
        upcoming = cal.upcoming_events(_utc())
        assert len(upcoming) == 0

    def test_minutes_until_computed(self):
        now = _utc(hour=10)
        events = _events(("NFP", _utc(hour=12, minute=30)))
        cal = EventCalendar(events=events)
        upcoming = cal.upcoming_events(now, hours_ahead=4)
        assert upcoming[0]["minutes_until"] == pytest.approx(150.0, abs=0.1)


# ── Edge cases ──

class TestEdgeCases:
    def test_invalid_time_format_skipped(self):
        events = [{"name": "FOMC", "time_utc": "not-a-date"}]
        cal = EventCalendar(events=events)
        result = cal.check_suppression(_utc(), "ES")
        assert result["suppressed"] is False

    def test_empty_calendar(self):
        cal = EventCalendar(events=[])
        result = cal.check_suppression(_utc(), "ES")
        assert result["suppressed"] is False

    def test_at_exact_blackout_boundary(self):
        event_time = _utc(hour=12, minute=30)
        cal = EventCalendar(events=_events(("FOMC", event_time)))
        # Exactly at blackout_start (20 min before)
        now = event_time - timedelta(minutes=20)
        result = cal.check_suppression(now, "ES")
        assert result["suppressed"] is True
        # Exactly at blackout_end (10 min after)
        now = event_time + timedelta(minutes=10)
        result = cal.check_suppression(now, "ES")
        assert result["suppressed"] is True
