"""Tests for market_intel_bridge — conviction bridge for Brain/Sentinel."""
import json
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

import pytest

from market_intel.market_intel_bridge import get_conviction, _STALE_THRESHOLD_S


def _make_redis(data: dict | None = None, symbol: str = "ES") -> MagicMock:
    """Create a mock Redis client with optional conviction data."""
    rc = MagicMock()
    if data is None:
        rc.get.return_value = None
    else:
        rc.get.return_value = json.dumps(data)
    return rc


def _fresh_ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stale_ts() -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=_STALE_THRESHOLD_S + 60)).isoformat()


def _sample_data(**overrides) -> dict:
    base = {
        "symbol": "ES",
        "long_conviction": 75,
        "short_conviction": 30,
        "hold_conviction": 70,
        "clarity": "HIGH",
        "matched_pattern": "TREND_ACCELERATION",
        "regime_transition": {"detected": False},
        "top_factors": ["velocity_15m_bullish", "gex_negative"],
        "timestamp": _fresh_ts(),
    }
    base.update(overrides)
    return base


class TestNoRedis:
    def test_no_redis_returns_default(self):
        result = get_conviction("ES", "LONG", redis_client=None)
        assert result["has_data"] is False
        assert result["conviction"] is None
        assert result["sizing_modifier"] == 1.0

    def test_no_data_returns_default(self):
        rc = _make_redis(data=None)
        result = get_conviction("ES", "LONG", redis_client=rc)
        assert result["has_data"] is False
        assert result["conviction"] is None
        assert result["sizing_modifier"] == 1.0


class TestSizingModifier:
    def test_high_conviction_full_size(self):
        rc = _make_redis(_sample_data(long_conviction=85, clarity="HIGH"))
        result = get_conviction("ES", "LONG", redis_client=rc)
        assert result["has_data"] is True
        assert result["conviction"] == 85
        assert result["sizing_modifier"] == 1.0

    def test_medium_conviction_reduced(self):
        rc = _make_redis(_sample_data(long_conviction=60, clarity="HIGH"))
        result = get_conviction("ES", "LONG", redis_client=rc)
        assert result["conviction"] == 60
        assert result["sizing_modifier"] == 0.75

    def test_low_conviction_half(self):
        rc = _make_redis(_sample_data(long_conviction=40, clarity="MEDIUM"))
        result = get_conviction("ES", "LONG", redis_client=rc)
        assert result["conviction"] == 40
        assert result["sizing_modifier"] == 0.5

    def test_very_low_conviction_quarter(self):
        rc = _make_redis(_sample_data(long_conviction=20, clarity="MEDIUM"))
        result = get_conviction("ES", "LONG", redis_client=rc)
        assert result["conviction"] == 20
        assert result["sizing_modifier"] == 0.25

    def test_low_clarity_blocks(self):
        rc = _make_redis(_sample_data(long_conviction=90, clarity="LOW"))
        result = get_conviction("ES", "LONG", redis_client=rc)
        assert result["has_data"] is True
        assert result["sizing_modifier"] == 0.0


class TestDirection:
    def test_direction_long(self):
        rc = _make_redis(_sample_data(long_conviction=80, short_conviction=25))
        result = get_conviction("ES", "LONG", redis_client=rc)
        assert result["conviction"] == 80

    def test_direction_short(self):
        rc = _make_redis(_sample_data(long_conviction=80, short_conviction=25))
        result = get_conviction("ES", "SHORT", redis_client=rc)
        assert result["conviction"] == 25


class TestStaleness:
    def test_stale_data(self):
        rc = _make_redis(_sample_data(timestamp=_stale_ts()))
        result = get_conviction("ES", "LONG", redis_client=rc)
        assert result["has_data"] is False
        assert result["sizing_modifier"] == 1.0
