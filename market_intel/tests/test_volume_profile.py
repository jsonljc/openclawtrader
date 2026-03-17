"""Tests for relative volume and time-of-day quality."""
from __future__ import annotations

import pytest

from market_intel.analytics.volume_profile import (
    compute_relative_volume,
    get_tod_quality,
)


class TestRelativeVolume:
    def test_high_volume(self):
        """Current >> average -> ratio > 1.5."""
        result = compute_relative_volume(current_volume=30000, avg_volume_at_tod=15000)
        assert result > 1.5

    def test_low_volume(self):
        """Current << average -> ratio < 0.7."""
        result = compute_relative_volume(current_volume=5000, avg_volume_at_tod=15000)
        assert result < 0.7

    def test_zero_average(self):
        """Average is zero -> return 0.0 to avoid division by zero."""
        result = compute_relative_volume(current_volume=1000, avg_volume_at_tod=0)
        assert result == 0.0

    def test_exact_average(self):
        """Current equals average -> ratio is 1.0."""
        result = compute_relative_volume(current_volume=10000, avg_volume_at_tod=10000)
        assert result == 1.0


class TestTodQuality:
    def test_tod_open_chop(self):
        """09:35 ET -> open chop window, quality = 0.6."""
        result = get_tod_quality(hour=9, minute=35)
        assert result == pytest.approx(0.6)

    def test_tod_morning_momentum(self):
        """10:30 ET -> morning momentum, quality = 1.0."""
        result = get_tod_quality(hour=10, minute=30)
        assert result == pytest.approx(1.0)

    def test_tod_lunch_chop(self):
        """12:00 ET -> lunch chop, quality = 0.7."""
        result = get_tod_quality(hour=12, minute=0)
        assert result == pytest.approx(0.7)

    def test_tod_outside_rth(self):
        """06:00 ET -> outside RTH, quality = 0.5."""
        result = get_tod_quality(hour=6, minute=0)
        assert result == pytest.approx(0.5)
