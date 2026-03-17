"""Tests for regime transition detection."""
from __future__ import annotations

import pytest

from market_intel.analytics.regime_transition import detect_regime_transition


class TestRegimeTransition:
    def test_transition_detected(self):
        """Scores accelerating from NEUTRAL toward TRENDING threshold."""
        history = [
            {"score": 40, "regime_type": "NEUTRAL", "timestamp": "2026-03-17T10:00:00Z"},
            {"score": 50, "regime_type": "NEUTRAL", "timestamp": "2026-03-17T10:10:00Z"},
            {"score": 62, "regime_type": "NEUTRAL", "timestamp": "2026-03-17T10:20:00Z"},
            {"score": 73, "regime_type": "NEUTRAL", "timestamp": "2026-03-17T10:30:00Z"},
        ]
        result = detect_regime_transition(history)
        assert result["detected"] is True
        assert result["from_regime"] == "NEUTRAL"
        assert result["to_regime"] == "TRENDING"
        assert result["confidence"] > 0.0

    def test_no_transition(self):
        """Stable scores within same regime -> no transition."""
        history = [
            {"score": 50, "regime_type": "NEUTRAL", "timestamp": "2026-03-17T10:00:00Z"},
            {"score": 51, "regime_type": "NEUTRAL", "timestamp": "2026-03-17T10:10:00Z"},
            {"score": 49, "regime_type": "NEUTRAL", "timestamp": "2026-03-17T10:20:00Z"},
            {"score": 50, "regime_type": "NEUTRAL", "timestamp": "2026-03-17T10:30:00Z"},
        ]
        result = detect_regime_transition(history)
        assert result["detected"] is False

    def test_already_in_regime(self):
        """Scores stable within TRENDING -> no transition."""
        history = [
            {"score": 78, "regime_type": "TRENDING", "timestamp": "2026-03-17T10:00:00Z"},
            {"score": 80, "regime_type": "TRENDING", "timestamp": "2026-03-17T10:10:00Z"},
            {"score": 79, "regime_type": "TRENDING", "timestamp": "2026-03-17T10:20:00Z"},
            {"score": 81, "regime_type": "TRENDING", "timestamp": "2026-03-17T10:30:00Z"},
        ]
        result = detect_regime_transition(history)
        assert result["detected"] is False

    def test_insufficient_history(self):
        """Fewer than 3 data points -> not detected."""
        history = [
            {"score": 40, "regime_type": "NEUTRAL", "timestamp": "2026-03-17T10:00:00Z"},
            {"score": 65, "regime_type": "NEUTRAL", "timestamp": "2026-03-17T10:10:00Z"},
        ]
        result = detect_regime_transition(history)
        assert result["detected"] is False
        assert result["from_regime"] is None
        assert result["to_regime"] is None
        assert result["confidence"] == 0.0
