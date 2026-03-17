"""Tests for data_layer.py."""

import json
import pytest
from datetime import datetime, timedelta
from fakeredis import FakeRedis
from market_intel.data_layer import IBDataManager


class MockIB:
    """Mock IB connection for testing."""

    def __init__(self, should_fail=False):
        self.should_fail = should_fail
        self.tickers = {
            "ES": {
                "bid": 5400.0,
                "ask": 5400.25,
                "last": 5400.25,
                "volume": 100000,
                "bid_size": 10,
                "ask_size": 8,
            },
            "VIX": {
                "bid": 18.0,
                "ask": 18.1,
                "last": 18.05,
                "volume": 50000,
            },
        }

    def ticker(self, contract):
        if self.should_fail:
            raise Exception("IB connection failed")
        symbol = getattr(contract, "symbol", "ES")
        return self.tickers.get(symbol, {})


@pytest.fixture
def mock_ib():
    return MockIB()

@pytest.fixture
def fake_redis():
    return FakeRedis()

@pytest.fixture
def manager(mock_ib, fake_redis):
    mgr = IBDataManager(ib=mock_ib, redis_client=fake_redis)
    def _get_ticker(symbol):
        return mock_ib.tickers.get(symbol)
    mgr._get_ticker = _get_ticker
    return mgr


def test_quote_caching(manager, fake_redis):
    quotes = manager.poll_quotes(["ES"])
    assert "ES" in quotes
    assert quotes["ES"]["bid"] == 5400.0
    assert quotes["ES"]["ask"] == 5400.25
    cached = fake_redis.hgetall("market_intel:quotes:ES")
    assert cached
    data = json.loads(cached[b"data"].decode())
    assert data["bid"] == 5400.0

def test_cross_market_caching(manager, fake_redis):
    cross = manager.poll_cross_market(["VIX"])
    assert "VIX" in cross
    assert cross["VIX"]["last"] == 18.05
    cached = fake_redis.hgetall("market_intel:cross:VIX")
    assert cached
    data = json.loads(cached[b"data"].decode())
    assert data["last"] == 18.05

def test_options_caching(manager, fake_redis):
    chain = manager.poll_options("ES")
    assert chain["symbol"] == "ES"
    assert "strikes" in chain
    cached = fake_redis.hgetall("market_intel:options:ES")
    assert cached
    data = json.loads(cached[b"data"].decode())
    assert data["symbol"] == "ES"

def test_dom_caching(manager, fake_redis):
    dom = manager.poll_dom(["ES"])
    assert "ES" in dom
    assert "bid_prices" in dom["ES"]
    cached = fake_redis.hgetall("market_intel:dom:ES")
    assert cached
    data = json.loads(cached[b"data"].decode())
    assert "bid_prices" in data

def test_staleness_detection(manager):
    old_data = {
        "bid": 5400.0,
        "timestamp": (datetime.utcnow() - timedelta(seconds=20)).isoformat(),
    }
    assert manager.is_stale(old_data) is True

def test_fresh_data_not_stale(manager):
    fresh_data = {
        "bid": 5400.0,
        "timestamp": datetime.utcnow().isoformat(),
    }
    assert manager.is_stale(fresh_data) is False

def test_no_ib_graceful(fake_redis):
    manager = IBDataManager(ib=None, redis_client=fake_redis)
    quotes = manager.poll_quotes(["ES"])
    assert quotes == {}

def test_no_redis_graceful(mock_ib):
    manager = IBDataManager(ib=mock_ib, redis_client=None)
    def _get_ticker(symbol):
        return mock_ib.tickers.get(symbol)
    manager._get_ticker = _get_ticker
    quotes = manager.poll_quotes(["ES"])
    assert "ES" in quotes
    assert quotes["ES"]["bid"] == 5400.0
