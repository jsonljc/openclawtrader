"""Tests for conviction scorer — pattern match, weighted fallback, TOD, clarity."""
from __future__ import annotations

import pytest

from market_intel.conviction.scorer import compute_conviction


# ── Weights config used in tests ─────────────────────────────────────────

WEIGHTS = {
    "TRENDING": {
        "velocity_alignment": 0.25,
        "divergence_score": 0.20,
        "gex_tailwind": 0.15,
        "options_flow": 0.15,
        "signal_integration": 0.15,
        "relative_volume": 0.10,
    },
    "VOLATILE": {
        "velocity_alignment": 0.15,
        "divergence_score": 0.25,
        "gex_tailwind": 0.20,
        "options_flow": 0.20,
        "signal_integration": 0.10,
        "relative_volume": 0.10,
    },
    "NEUTRAL": {
        "velocity_alignment": 0.20,
        "divergence_score": 0.25,
        "gex_tailwind": 0.15,
        "options_flow": 0.15,
        "signal_integration": 0.15,
        "relative_volume": 0.10,
    },
}


# ── Pattern config used in tests ─────────────────────────────────────────

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


# ── Helper to build analytics with factor directions ─────────────────────

def _make_analytics(
    velocity_5m=0, velocity_15m=0, velocity_1h=0,
    divergence_score=0, gex=-10, options_flow=0,
    signal_aligned=0, signal_opposing=0,
    relative_volume=1.0, book_imbalance=0.0,
    regime_transition_detected=0,
    # Directional factors: positive = LONG bias, negative = SHORT bias
    velocity_alignment=0, gex_tailwind=0, signal_integration=0,
):
    return {
        "velocity_5m": velocity_5m,
        "velocity_15m": velocity_15m,
        "velocity_1h": velocity_1h,
        "divergence_score": divergence_score,
        "gex": gex,
        "gex_tailwind": gex_tailwind,
        "options_flow": options_flow,
        "signal_aligned": signal_aligned,
        "signal_opposing": signal_opposing,
        "signal_integration": signal_integration,
        "relative_volume": relative_volume,
        "book_imbalance": book_imbalance,
        "regime_transition_detected": regime_transition_detected,
        "velocity_alignment": velocity_alignment,
    }


# ── Tests ────────────────────────────────────────────────────────────────


class TestConvictionScorer:
    def test_pattern_match_used(self):
        """When a pattern matches, its base_score is used as conviction."""
        analytics = _make_analytics(
            gex=-30, velocity_5m=35, velocity_15m=55, relative_volume=2.0,
        )
        result = compute_conviction(
            analytics=analytics, regime="TRENDING",
            hour=10, minute=30,
            patterns_config=PATTERNS, weights_config=WEIGHTS,
        )
        assert result["matched_pattern"] == "TREND_ACCELERATION"
        assert result["long_conviction"] == 85
        assert result["clarity"] == "HIGH"

    def test_weighted_fallback(self):
        """No pattern matches -> uses weighted calculation."""
        analytics = _make_analytics(
            velocity_alignment=60, divergence_score=40,
            gex_tailwind=50, options_flow=30,
            signal_integration=20, relative_volume=1.2,
        )
        result = compute_conviction(
            analytics=analytics, regime="TRENDING",
            hour=10, minute=30,
            patterns_config=PATTERNS, weights_config=WEIGHTS,
        )
        assert result["matched_pattern"] is None
        # Should have non-zero conviction from weighted sum
        assert result["long_conviction"] > 0 or result["short_conviction"] > 0

    def test_trending_regime_weights(self):
        """In TRENDING regime, velocity_alignment has highest weight (25%)."""
        # High velocity alignment but low everything else
        analytics = _make_analytics(
            velocity_alignment=80, divergence_score=10,
            gex_tailwind=10, options_flow=10,
            signal_integration=10, relative_volume=1.0,
        )
        trending_result = compute_conviction(
            analytics=analytics, regime="TRENDING",
            hour=10, minute=30,
            patterns_config=[], weights_config=WEIGHTS,
        )
        volatile_result = compute_conviction(
            analytics=analytics, regime="VOLATILE",
            hour=10, minute=30,
            patterns_config=[], weights_config=WEIGHTS,
        )
        # TRENDING weights velocity higher, so conviction should be higher
        trending_score = trending_result["long_conviction"] + trending_result["short_conviction"]
        volatile_score = volatile_result["long_conviction"] + volatile_result["short_conviction"]
        assert trending_score >= volatile_score

    def test_volatile_regime_weights(self):
        """In VOLATILE regime, divergence_score has highest weight (25%)."""
        # High divergence but low velocity
        analytics = _make_analytics(
            velocity_alignment=10, divergence_score=80,
            gex_tailwind=10, options_flow=10,
            signal_integration=10, relative_volume=1.0,
        )
        volatile_result = compute_conviction(
            analytics=analytics, regime="VOLATILE",
            hour=10, minute=30,
            patterns_config=[], weights_config=WEIGHTS,
        )
        trending_result = compute_conviction(
            analytics=analytics, regime="TRENDING",
            hour=10, minute=30,
            patterns_config=[], weights_config=WEIGHTS,
        )
        volatile_score = volatile_result["long_conviction"] + volatile_result["short_conviction"]
        trending_score = trending_result["long_conviction"] + trending_result["short_conviction"]
        assert volatile_score >= trending_score

    def test_tod_suppression(self):
        """Lunch chop (12:00) reduces conviction via TOD modifier."""
        analytics = _make_analytics(
            velocity_alignment=60, divergence_score=60,
            gex_tailwind=60, options_flow=60,
            signal_integration=60, relative_volume=1.5,
        )
        morning = compute_conviction(
            analytics=analytics, regime="TRENDING",
            hour=10, minute=30,  # morning momentum = 1.0
            patterns_config=[], weights_config=WEIGHTS,
        )
        lunch = compute_conviction(
            analytics=analytics, regime="TRENDING",
            hour=12, minute=0,  # lunch chop = 0.7
            patterns_config=[], weights_config=WEIGHTS,
        )
        # Lunch conviction should be lower
        assert lunch["long_conviction"] <= morning["long_conviction"]

    def test_tod_boost(self):
        """Morning momentum (10:00) applies full multiplier (1.0)."""
        analytics = _make_analytics(
            velocity_alignment=50, divergence_score=50,
            gex_tailwind=50, options_flow=50,
            signal_integration=50, relative_volume=1.0,
        )
        result = compute_conviction(
            analytics=analytics, regime="TRENDING",
            hour=10, minute=0,
            patterns_config=[], weights_config=WEIGHTS,
        )
        # No suppression at 10:00 (modifier = 1.0)
        assert result["long_conviction"] > 0 or result["short_conviction"] > 0

    def test_clarity_high(self):
        """Most factors agree on direction -> HIGH clarity."""
        analytics = _make_analytics(
            velocity_alignment=70, divergence_score=65,
            gex_tailwind=60, options_flow=55,
            signal_integration=50, relative_volume=1.5,
        )
        result = compute_conviction(
            analytics=analytics, regime="TRENDING",
            hour=10, minute=30,
            patterns_config=[], weights_config=WEIGHTS,
        )
        assert result["clarity"] == "HIGH"

    def test_clarity_low(self):
        """Factors disagree violently -> LOW clarity."""
        # Mix of strong positive and strong negative factors
        analytics = _make_analytics(
            velocity_alignment=80, divergence_score=-70,
            gex_tailwind=-60, options_flow=75,
            signal_integration=-65, relative_volume=1.0,
        )
        result = compute_conviction(
            analytics=analytics, regime="TRENDING",
            hour=10, minute=30,
            patterns_config=[], weights_config=WEIGHTS,
        )
        assert result["clarity"] == "LOW"

    def test_directional_output(self):
        """Long and short conviction computed separately."""
        analytics = _make_analytics(
            velocity_alignment=60, divergence_score=50,
            gex_tailwind=40, options_flow=30,
            signal_integration=20, relative_volume=1.0,
        )
        result = compute_conviction(
            analytics=analytics, regime="TRENDING",
            hour=10, minute=30,
            patterns_config=[], weights_config=WEIGHTS,
        )
        assert "long_conviction" in result
        assert "short_conviction" in result
        assert "hold_conviction" in result
        assert isinstance(result["long_conviction"], int)
        assert isinstance(result["short_conviction"], int)
        assert isinstance(result["hold_conviction"], int)
        assert 0 <= result["long_conviction"] <= 100
        assert 0 <= result["short_conviction"] <= 100
        assert 0 <= result["hold_conviction"] <= 100

    def test_outside_rth(self):
        """Outside RTH -> conviction reduced by 0.5 modifier."""
        analytics = _make_analytics(
            velocity_alignment=60, divergence_score=60,
            gex_tailwind=60, options_flow=60,
            signal_integration=60, relative_volume=1.5,
        )
        rth = compute_conviction(
            analytics=analytics, regime="TRENDING",
            hour=10, minute=30,  # morning = 1.0
            patterns_config=[], weights_config=WEIGHTS,
        )
        outside = compute_conviction(
            analytics=analytics, regime="TRENDING",
            hour=6, minute=0,  # outside RTH = 0.5
            patterns_config=[], weights_config=WEIGHTS,
        )
        assert outside["long_conviction"] <= rth["long_conviction"]
        # Outside RTH should be roughly half
        if rth["long_conviction"] > 0:
            ratio = outside["long_conviction"] / rth["long_conviction"]
            assert ratio <= 0.6  # allow some rounding slack
