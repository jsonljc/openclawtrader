"""Tests for temporal decay of signal values."""
from __future__ import annotations

import pytest

from market_intel.conviction.decay import apply_decay


class TestApplyDecay:
    def test_no_decay_when_fresh(self):
        """onset_time equals now -> full value returned."""
        now = "2026-03-17T10:30:00Z"
        result = apply_decay(value=80.0, onset_time=now, half_life_minutes=15.0, now=now)
        assert result == pytest.approx(80.0)

    def test_half_value_at_half_life(self):
        """Elapsed equals half_life -> value / 2."""
        onset = "2026-03-17T10:00:00Z"
        now = "2026-03-17T10:15:00Z"  # 15 min later
        result = apply_decay(value=80.0, onset_time=onset, half_life_minutes=15.0, now=now)
        assert result == pytest.approx(40.0)

    def test_quarter_at_two_half_lives(self):
        """Elapsed equals 2x half_life -> value / 4."""
        onset = "2026-03-17T10:00:00Z"
        now = "2026-03-17T10:30:00Z"  # 30 min later
        result = apply_decay(value=80.0, onset_time=onset, half_life_minutes=15.0, now=now)
        assert result == pytest.approx(20.0)

    def test_near_zero_when_old(self):
        """Elapsed equals 10x half_life -> near zero."""
        onset = "2026-03-17T10:00:00Z"
        now = "2026-03-17T12:30:00Z"  # 150 min later = 10 half-lives at 15 min
        result = apply_decay(value=80.0, onset_time=onset, half_life_minutes=15.0, now=now)
        assert abs(result) < 0.1  # 80 * 0.5^10 = 0.078

    def test_negative_value_decays(self):
        """Negative values decay toward zero (magnitude decreases)."""
        onset = "2026-03-17T10:00:00Z"
        now = "2026-03-17T10:15:00Z"  # 1 half-life
        result = apply_decay(value=-60.0, onset_time=onset, half_life_minutes=15.0, now=now)
        assert result == pytest.approx(-30.0)

    def test_zero_value_stays_zero(self):
        """Zero input always returns zero."""
        onset = "2026-03-17T10:00:00Z"
        now = "2026-03-17T10:15:00Z"
        result = apply_decay(value=0.0, onset_time=onset, half_life_minutes=15.0, now=now)
        assert result == 0.0
