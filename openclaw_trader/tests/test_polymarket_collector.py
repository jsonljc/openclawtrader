"""Tests for Polymarket collector drift and anomaly detection."""
import pytest
from datetime import datetime, timezone, timedelta
from openclaw_trader.signals.polymarket_collector import (
    PolymarketCollector,
    detect_drift,
    detect_liquidity_spike,
    compute_regime_confidence_mod,
)


class TestDetectDrift:
    def test_drift_above_15pp_fires(self):
        now = datetime.now(timezone.utc)
        snapshots = [
            {"probability": 0.40, "timestamp": (now - timedelta(hours=3)).isoformat()},
            {"probability": 0.50, "timestamp": (now - timedelta(hours=2)).isoformat()},
            {"probability": 0.60, "timestamp": (now - timedelta(hours=1)).isoformat()},
        ]
        result = detect_drift(snapshots, current_prob=0.60)
        assert result is not None
        assert result["drift_magnitude"] == pytest.approx(20.0, abs=0.1)

    def test_drift_above_25pp_is_high(self):
        now = datetime.now(timezone.utc)
        snapshots = [
            {"probability": 0.30, "timestamp": (now - timedelta(hours=3)).isoformat()},
        ]
        result = detect_drift(snapshots, current_prob=0.60)
        assert result is not None
        assert result["drift_magnitude"] == pytest.approx(30.0, abs=0.1)
        assert result["strength"] == "HIGH"

    def test_drift_below_15pp_no_signal(self):
        now = datetime.now(timezone.utc)
        snapshots = [
            {"probability": 0.45, "timestamp": (now - timedelta(hours=3)).isoformat()},
        ]
        result = detect_drift(snapshots, current_prob=0.50)
        assert result is None

    def test_empty_snapshots_no_signal(self):
        result = detect_drift([], current_prob=0.50)
        assert result is None

    def test_negative_drift_detected(self):
        now = datetime.now(timezone.utc)
        snapshots = [
            {"probability": 0.70, "timestamp": (now - timedelta(hours=3)).isoformat()},
        ]
        result = detect_drift(snapshots, current_prob=0.50)
        assert result is not None
        assert result["drift_magnitude"] == pytest.approx(-20.0, abs=0.1)


class TestLiquiditySpike:
    def test_spike_above_25k(self):
        result = detect_liquidity_spike(
            previous_liquidity=100_000, current_liquidity=130_000
        )
        assert result is not None
        assert result["strength"] == "MEDIUM"

    def test_spike_above_100k_is_high(self):
        result = detect_liquidity_spike(
            previous_liquidity=100_000, current_liquidity=210_000
        )
        assert result is not None
        assert result["strength"] == "HIGH"

    def test_no_spike_below_25k(self):
        result = detect_liquidity_spike(
            previous_liquidity=100_000, current_liquidity=120_000
        )
        assert result is None


class TestRegimeConfidenceMod:
    def test_two_high_same_direction_boost(self):
        signals = [
            {"strength": "HIGH", "direction": "YES", "instruments": ["ES"]},
            {"strength": "HIGH", "direction": "YES", "instruments": ["ES"]},
        ]
        mod = compute_regime_confidence_mod(signals, instrument="ES")
        assert mod == pytest.approx(1.2)

    def test_two_high_opposing_reduce(self):
        signals = [
            {"strength": "HIGH", "direction": "NO", "instruments": ["ES"]},
            {"strength": "HIGH", "direction": "NO", "instruments": ["ES"]},
        ]
        mod = compute_regime_confidence_mod(
            signals, instrument="ES", current_direction="YES"
        )
        assert mod == pytest.approx(0.8)

    def test_one_signal_no_mod(self):
        signals = [
            {"strength": "HIGH", "direction": "YES", "instruments": ["ES"]},
        ]
        mod = compute_regime_confidence_mod(signals, instrument="ES")
        assert mod == pytest.approx(1.0)

    def test_medium_strength_ignored(self):
        signals = [
            {"strength": "MEDIUM", "direction": "YES", "instruments": ["ES"]},
            {"strength": "MEDIUM", "direction": "YES", "instruments": ["ES"]},
        ]
        mod = compute_regime_confidence_mod(signals, instrument="ES")
        assert mod == pytest.approx(1.0)
