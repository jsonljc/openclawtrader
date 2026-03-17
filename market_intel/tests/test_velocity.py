"""Tests for velocity.py."""

import pytest
from datetime import datetime, timedelta
from market_intel.analytics.velocity import compute_velocity


def _make_history(base_price: float, changes: list[float], interval_minutes: int = 1) -> list[dict]:
    """
    Helper to create price history.

    Args:
        base_price: Starting price
        changes: List of percentage changes for each entry
        interval_minutes: Minutes between entries

    Returns:
        List of price history dicts
    """
    history = []
    now = datetime.utcnow()

    for i, change_pct in enumerate(changes):
        price = base_price * (1 + change_pct / 100.0)
        ts = now - timedelta(minutes=(len(changes) - i - 1) * interval_minutes)
        history.append({
            "price": price,
            "volume": 1000,  # constant volume for simplicity
            "timestamp": ts.isoformat(),
        })

    return history


def test_bullish_velocity():
    """Test that rising prices produce positive velocity scores."""
    # 5% rise over 60 minutes (1% per 12 min)
    history = _make_history(5000.0, [0, 1, 2, 3, 4, 5], interval_minutes=12)
    result = compute_velocity(history)

    assert result["velocity_5m"] > 0  # Last 5min rising
    assert result["velocity_15m"] > 0
    assert result["velocity_1h"] > 0


def test_bearish_velocity():
    """Test that falling prices produce negative velocity scores."""
    # 5% drop over 60 minutes
    history = _make_history(5000.0, [0, -1, -2, -3, -4, -5], interval_minutes=12)
    result = compute_velocity(history)

    assert result["velocity_5m"] < 0
    assert result["velocity_15m"] < 0
    assert result["velocity_1h"] < 0


def test_neutral_velocity():
    """Test that flat prices produce near-zero velocity scores."""
    # Minimal changes
    history = _make_history(5000.0, [0, 0.01, -0.01, 0.02, -0.02, 0], interval_minutes=12)
    result = compute_velocity(history)

    assert abs(result["velocity_5m"]) < 10
    assert abs(result["velocity_15m"]) < 10
    assert abs(result["velocity_1h"]) < 10


def test_capped_at_100():
    """Test that extreme upward moves are capped at +100."""
    # 20% rise (way above max_expected)
    history = _make_history(5000.0, [0, 5, 10, 15, 20], interval_minutes=15)
    result = compute_velocity(history)

    # 1h velocity should be capped at 100
    assert result["velocity_1h"] == 100.0


def test_capped_at_neg_100():
    """Test that extreme downward moves are capped at -100."""
    # 20% drop
    history = _make_history(5000.0, [0, -5, -10, -15, -20], interval_minutes=15)
    result = compute_velocity(history)

    # 1h velocity should be capped at -100
    assert result["velocity_1h"] == -100.0


def test_volume_acceleration_surging():
    """Test that high recent volume produces >1.5 acceleration."""
    now = datetime.utcnow()
    history = []

    # Low volume for first 55 minutes
    for i in range(55):
        ts = now - timedelta(minutes=55 - i)
        history.append({
            "price": 5000.0,
            "volume": 100,
            "timestamp": ts.isoformat(),
        })

    # High volume in last 5 minutes
    for i in range(5):
        ts = now - timedelta(minutes=5 - i - 1)
        history.append({
            "price": 5000.0,
            "volume": 5000,  # 50x higher
            "timestamp": ts.isoformat(),
        })

    result = compute_velocity(history)
    assert result["volume_accel"] > 1.5


def test_volume_acceleration_dying():
    """Test that low recent volume produces <0.7 acceleration."""
    now = datetime.utcnow()
    history = []

    # High volume for first 55 minutes
    for i in range(55):
        ts = now - timedelta(minutes=55 - i)
        history.append({
            "price": 5000.0,
            "volume": 5000,
            "timestamp": ts.isoformat(),
        })

    # Low volume in last 5 minutes
    for i in range(5):
        ts = now - timedelta(minutes=5 - i - 1)
        history.append({
            "price": 5000.0,
            "volume": 100,  # 1/50th of average
            "timestamp": ts.isoformat(),
        })

    result = compute_velocity(history)
    assert result["volume_accel"] < 0.7


def test_empty_history():
    """Test that empty history returns zeros."""
    result = compute_velocity([])

    assert result["velocity_5m"] == 0.0
    assert result["velocity_15m"] == 0.0
    assert result["velocity_1h"] == 0.0
    assert result["volume_accel"] == 0.0
