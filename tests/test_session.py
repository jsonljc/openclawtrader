#!/usr/bin/env python3
"""Unit tests for session.py — per-instrument session windows and boundaries.

Covers:
  - detect_intra_session(): per-instrument classification
  - is_rth(): RTH boundary checks for ES, CL, GC, ZB
  - minutes_into_session() / minutes_until_close()
  - get_session_report()
  - Weekend handling
"""

from __future__ import annotations
import sys
from datetime import datetime, timezone, timedelta, time as dtime
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "workspace-c3po"))

from session import (
    IntraSession,
    INSTRUMENT_SESSIONS,
    detect_intra_session,
    is_rth,
    minutes_into_session,
    minutes_until_close,
    get_session_report,
    get_session_modifier,
    is_any_rth,
    _resolve_session_group,
)

try:
    import zoneinfo
    ET = zoneinfo.ZoneInfo("America/New_York")
except ImportError:
    ET = timezone(timedelta(hours=-5))


def _et_to_utc(hour, minute=0, weekday=1):
    """Create a UTC datetime for a given ET time on a Tuesday (weekday=1)."""
    # 2026-03-17 is a Tuesday
    base = datetime(2026, 3, 17, hour, minute, tzinfo=ET)
    # Adjust to desired weekday (0=Mon)
    days_offset = weekday - base.weekday()
    base = base + timedelta(days=days_offset)
    return base.astimezone(timezone.utc)


# ── Symbol group routing ──

class TestSymbolGroupRouting:
    def test_es_routes_to_equity(self):
        assert _resolve_session_group("ES") == "equity_index"

    def test_nq_routes_to_equity(self):
        assert _resolve_session_group("NQ") == "equity_index"

    def test_mes_routes_to_equity(self):
        assert _resolve_session_group("MES") == "equity_index"

    def test_cl_routes_to_energy(self):
        assert _resolve_session_group("CL") == "energy"

    def test_mcl_routes_to_energy(self):
        assert _resolve_session_group("MCL") == "energy"

    def test_gc_routes_to_metals(self):
        assert _resolve_session_group("GC") == "metals"

    def test_zb_routes_to_rates(self):
        assert _resolve_session_group("ZB") == "rates"

    def test_unknown_defaults_to_equity(self):
        assert _resolve_session_group("UNKNOWN") == "equity_index"


# ── ES session boundaries ──

class TestESSession:
    def test_premarket_830(self):
        t = _et_to_utc(8, 30)
        assert detect_intra_session(t, "ES") == IntraSession.PREMARKET

    def test_us_open_932(self):
        t = _et_to_utc(9, 32)
        assert detect_intra_session(t, "ES") == IntraSession.US_OPEN

    def test_morning_drive_1030(self):
        t = _et_to_utc(10, 30)
        assert detect_intra_session(t, "ES") == IntraSession.MORNING_DRIVE

    def test_midday_1200(self):
        t = _et_to_utc(12, 0)
        assert detect_intra_session(t, "ES") == IntraSession.MIDDAY

    def test_afternoon_1400(self):
        t = _et_to_utc(14, 0)
        assert detect_intra_session(t, "ES") == IntraSession.AFTERNOON

    def test_moc_1515(self):
        t = _et_to_utc(15, 15)
        assert detect_intra_session(t, "ES") == IntraSession.MOC_CLOSE

    def test_extended_1600(self):
        t = _et_to_utc(16, 0)
        assert detect_intra_session(t, "ES") == IntraSession.EXTENDED

    def test_rth_at_932(self):
        assert is_rth(_et_to_utc(9, 32), "ES") is True

    def test_rth_at_1544(self):
        assert is_rth(_et_to_utc(15, 44), "ES") is True

    def test_not_rth_at_1545(self):
        assert is_rth(_et_to_utc(15, 45), "ES") is False

    def test_not_rth_at_930(self):
        assert is_rth(_et_to_utc(9, 30), "ES") is False


# ── CL session boundaries ──

class TestCLSession:
    def test_premarket_830(self):
        t = _et_to_utc(8, 30)
        assert detect_intra_session(t, "CL") == IntraSession.PREMARKET

    def test_us_open_900(self):
        t = _et_to_utc(9, 0)
        assert detect_intra_session(t, "CL") == IntraSession.US_OPEN

    def test_rth_at_900(self):
        assert is_rth(_et_to_utc(9, 0), "CL") is True

    def test_not_rth_at_1430(self):
        assert is_rth(_et_to_utc(14, 30), "CL") is False

    def test_rth_at_1429(self):
        assert is_rth(_et_to_utc(14, 29), "CL") is True

    def test_extended_at_1500(self):
        t = _et_to_utc(15, 0)
        assert detect_intra_session(t, "CL") == IntraSession.EXTENDED


# ── GC session boundaries ──

class TestGCSession:
    def test_premarket_800(self):
        t = _et_to_utc(8, 0)
        assert detect_intra_session(t, "GC") == IntraSession.PREMARKET

    def test_us_open_820(self):
        t = _et_to_utc(8, 20)
        assert detect_intra_session(t, "GC") == IntraSession.US_OPEN

    def test_rth_at_820(self):
        assert is_rth(_et_to_utc(8, 20), "GC") is True

    def test_rth_at_1659(self):
        assert is_rth(_et_to_utc(16, 59), "GC") is True

    def test_not_rth_at_1700(self):
        assert is_rth(_et_to_utc(17, 0), "GC") is False

    def test_moc_at_1530(self):
        t = _et_to_utc(15, 30)
        assert detect_intra_session(t, "GC") == IntraSession.MOC_CLOSE


# ── ZB session boundaries ──

class TestZBSession:
    def test_us_open_820(self):
        t = _et_to_utc(8, 20)
        assert detect_intra_session(t, "ZB") == IntraSession.US_OPEN

    def test_rth_at_820(self):
        assert is_rth(_et_to_utc(8, 20), "ZB") is True

    def test_not_rth_at_1500(self):
        assert is_rth(_et_to_utc(15, 0), "ZB") is False

    def test_rth_at_1459(self):
        assert is_rth(_et_to_utc(14, 59), "ZB") is True

    def test_moc_at_1445(self):
        t = _et_to_utc(14, 45)
        assert detect_intra_session(t, "ZB") == IntraSession.MOC_CLOSE


# ── Weekend handling ──

class TestWeekend:
    def test_saturday_is_closed(self):
        sat = _et_to_utc(12, 0, weekday=5)
        assert detect_intra_session(sat, "ES") == IntraSession.CLOSED

    def test_sunday_morning_is_closed(self):
        sun = _et_to_utc(12, 0, weekday=6)
        assert detect_intra_session(sun, "ES") == IntraSession.CLOSED

    def test_saturday_not_rth(self):
        sat = _et_to_utc(10, 0, weekday=5)
        assert is_rth(sat, "ES") is False


# ── minutes_into_session / minutes_until_close ──

class TestMinutes:
    def test_minutes_into_session_es(self):
        t = _et_to_utc(10, 32)  # 60 min after ES open (9:32)
        mins = minutes_into_session(t, "ES")
        assert mins == 60

    def test_minutes_before_open_is_zero(self):
        t = _et_to_utc(8, 0)
        assert minutes_into_session(t, "ES") == 0

    def test_minutes_until_close_es(self):
        t = _et_to_utc(14, 45)  # 60 min before ES close (15:45)
        mins = minutes_until_close(t, "ES")
        assert mins == 60

    def test_after_close_is_zero(self):
        t = _et_to_utc(16, 0)
        assert minutes_until_close(t, "ES") == 0

    def test_minutes_into_session_cl(self):
        t = _et_to_utc(10, 0)  # 60 min after CL open (9:00)
        mins = minutes_into_session(t, "CL")
        assert mins == 60


# ── get_session_report ──

class TestSessionReport:
    def test_report_structure(self):
        t = _et_to_utc(10, 0)
        report = get_session_report(t, "ES")
        assert "session" in report
        assert "modifier" in report
        assert "is_rth" in report
        assert "is_tradeable" in report
        assert "minutes_into_session" in report
        assert "minutes_until_close" in report

    def test_tradeable_during_morning(self):
        t = _et_to_utc(10, 30)
        report = get_session_report(t, "ES")
        assert report["is_tradeable"] is True

    def test_not_tradeable_premarket(self):
        t = _et_to_utc(8, 30)
        report = get_session_report(t, "ES")
        assert report["is_tradeable"] is False


# ── Session modifiers ──

class TestSessionModifiers:
    def test_morning_drive_is_full(self):
        assert get_session_modifier(IntraSession.MORNING_DRIVE) == 1.0

    def test_midday_is_half(self):
        assert get_session_modifier(IntraSession.MIDDAY) == 0.5

    def test_closed_is_zero(self):
        assert get_session_modifier(IntraSession.CLOSED) == 0.0


# ── is_any_rth ──

class TestIsAnyRTH:
    def test_during_es_rth(self):
        t = _et_to_utc(10, 0)
        assert is_any_rth(t) is True

    def test_late_night_no_rth(self):
        t = _et_to_utc(1, 0)
        assert is_any_rth(t) is False
