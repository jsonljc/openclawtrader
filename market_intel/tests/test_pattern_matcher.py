"""Tests for conditional pattern matcher."""
from __future__ import annotations

import pytest

from market_intel.conviction.pattern_matcher import match_pattern, _evaluate_condition


# ── Patterns config used in tests ────────────────────────────────────────

PATTERNS = [
    {
        "name": "TREND_ACCELERATION",
        "direction": "LONG",
        "base_score": 85,
        "confidence": "HIGH",
        "conditions": [
            "gex < 0",
            "velocity_15m > 40",
            "velocity_15m > velocity_5m",
            "relative_volume > 1.5",
        ],
    },
    {
        "name": "REGIME_FLIP",
        "direction": "LONG",
        "base_score": 80,
        "confidence": "HIGH",
        "conditions": [
            "regime_transition_detected == 1",
            "book_imbalance > 0.3",
            "velocity_5m > 10",
        ],
    },
    {
        "name": "MOMENTUM_EXHAUSTION",
        "direction": "SHORT",
        "base_score": 75,
        "confidence": "MEDIUM",
        "conditions": [
            "velocity_15m > 80",
            "gex_flipping == 1",
            "skew_shift > 2.0",
            "relative_volume < 0.8",
        ],
    },
    {
        "name": "DEAD_MARKET",
        "direction": "NEUTRAL",
        "base_score": 15,
        "confidence": "LOW",
        "conditions": [
            "relative_volume < 0.5",
            "velocity_5m < 10",
            "velocity_15m < 10",
            "velocity_1h < 10",
        ],
    },
]


# ── Pattern matching tests ───────────────────────────────────────────────


class TestPatternMatcher:
    def test_trend_acceleration_matches(self):
        """All conditions met -> returns TREND_ACCELERATION pattern."""
        analytics = {
            "gex": -30,
            "velocity_5m": 35,
            "velocity_15m": 55,
            "relative_volume": 2.0,
        }
        result = match_pattern(analytics, PATTERNS)
        assert result is not None
        assert result["name"] == "TREND_ACCELERATION"
        assert result["direction"] == "LONG"
        assert result["base_score"] == 85
        assert result["confidence"] == "HIGH"

    def test_trend_acceleration_fails(self):
        """One condition not met -> no match for that pattern."""
        analytics = {
            "gex": -30,
            "velocity_5m": 35,
            "velocity_15m": 55,
            "relative_volume": 1.2,  # below 1.5 threshold
        }
        # TREND_ACCELERATION won't match, but check no accidental match
        result = match_pattern(analytics, [PATTERNS[0]])  # only check first pattern
        assert result is None

    def test_regime_flip_matches(self):
        """Regime transition + book imbalance confirming."""
        analytics = {
            "regime_transition_detected": 1,
            "book_imbalance": 0.5,
            "velocity_5m": 20,
        }
        result = match_pattern(analytics, PATTERNS)
        assert result is not None
        assert result["name"] == "REGIME_FLIP"

    def test_momentum_exhaustion_matches(self):
        """Extreme velocity + GEX flipping + skew spiking."""
        analytics = {
            "velocity_15m": 90,
            "gex_flipping": 1,
            "skew_shift": 3.5,
            "relative_volume": 0.6,
        }
        result = match_pattern(analytics, PATTERNS)
        assert result is not None
        assert result["name"] == "MOMENTUM_EXHAUSTION"

    def test_dead_market_matches(self):
        """Low volume + low velocity = anti-conviction."""
        analytics = {
            "relative_volume": 0.3,
            "velocity_5m": 5,
            "velocity_15m": 4,
            "velocity_1h": 8,
        }
        result = match_pattern(analytics, PATTERNS)
        assert result is not None
        assert result["name"] == "DEAD_MARKET"
        assert result["base_score"] == 15

    def test_first_match_wins(self):
        """When two patterns could match, first one in list is returned."""
        # Build analytics that satisfy both TREND_ACCELERATION and REGIME_FLIP
        analytics = {
            "gex": -30,
            "velocity_5m": 35,
            "velocity_15m": 55,
            "relative_volume": 2.0,
            "regime_transition_detected": 1,
            "book_imbalance": 0.5,
        }
        result = match_pattern(analytics, PATTERNS)
        assert result is not None
        assert result["name"] == "TREND_ACCELERATION"  # first in list

    def test_no_patterns_match(self):
        """No conditions met -> returns None."""
        analytics = {
            "gex": 10,
            "velocity_5m": 5,
            "velocity_15m": 5,
            "relative_volume": 1.0,
        }
        result = match_pattern(analytics, PATTERNS)
        assert result is None


# ── Condition parser tests ───────────────────────────────────────────────


class TestConditionParser:
    def test_condition_greater_than(self):
        """'velocity_5m > 50' with 60 -> True."""
        analytics = {"velocity_5m": 60}
        assert _evaluate_condition("velocity_5m > 50", analytics) is True

    def test_condition_less_than(self):
        """'gex < 0' with -30 -> True."""
        analytics = {"gex": -30}
        assert _evaluate_condition("gex < 0", analytics) is True

    def test_condition_cross_reference(self):
        """'velocity_15m > velocity_5m' comparing two analytics fields."""
        analytics = {"velocity_15m": 55, "velocity_5m": 35}
        assert _evaluate_condition("velocity_15m > velocity_5m", analytics) is True

        analytics_reversed = {"velocity_15m": 30, "velocity_5m": 50}
        assert _evaluate_condition("velocity_15m > velocity_5m", analytics_reversed) is False
