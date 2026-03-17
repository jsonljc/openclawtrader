"""Tests for signal integrator — counts aligned vs opposing signals."""
from __future__ import annotations

import pytest

from market_intel.analytics.signal_integrator import count_aligned_signals


class TestSignalIntegrator:
    def test_all_aligned(self):
        """3 signals all matching direction -> aligned=3, opposing=0."""
        signals = [
            {"id": "s1", "direction": "LONG", "event_type": "TARIFF"},
            {"id": "s2", "direction": "LONG", "event_type": "OIL_SUPPLY"},
            {"id": "s3", "direction": "LONG", "event_type": "FED_DOVISH"},
        ]
        result = count_aligned_signals(signals, direction="LONG")
        assert result["aligned"] == 3
        assert result["opposing"] == 0

    def test_mixed(self):
        """2 aligned, 1 opposing."""
        signals = [
            {"id": "s1", "direction": "LONG", "event_type": "TARIFF"},
            {"id": "s2", "direction": "SHORT", "event_type": "FED_HAWKISH"},
            {"id": "s3", "direction": "LONG", "event_type": "OIL_SUPPLY"},
        ]
        result = count_aligned_signals(signals, direction="LONG")
        assert result["aligned"] == 2
        assert result["opposing"] == 1

    def test_no_signals(self):
        """Empty list -> 0, 0."""
        result = count_aligned_signals([], direction="LONG")
        assert result["aligned"] == 0
        assert result["opposing"] == 0

    def test_no_direction_in_signal(self):
        """Signals without 'direction' field are ignored."""
        signals = [
            {"id": "s1", "event_type": "MONITOR"},
            {"id": "s2", "direction": "LONG", "event_type": "TARIFF"},
            {"id": "s3", "event_type": "HALT"},
        ]
        result = count_aligned_signals(signals, direction="LONG")
        assert result["aligned"] == 1
        assert result["opposing"] == 0
