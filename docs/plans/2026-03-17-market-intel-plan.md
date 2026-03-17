# Market Intel (Prism) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a standalone market intelligence daemon that connects to IB Gateway, polls real-time data, computes analytics, and produces per-instrument directional conviction scores for Brain, Sentinel, and Dashboard.

**Architecture:** Three-layer daemon (Data → Analytics → Conviction) with persistent IB connection via ib_insync. All output published to Redis HASHes. Consumers read via market_intel_bridge.py. Zero LLM tokens — pure deterministic computation. Graceful degradation when IB or Redis unavailable.

**Tech Stack:** Python 3.12, ib_insync, redis, numpy, fakeredis (testing), pytest

---

## Context

**Integration points:**
- `market_intel_bridge.py` follows `sentinel_bridge.py` pattern (default dict, try/except, graceful fallback)
- Brain `_suggest_sizing()` gets new `market_intel_mod` multiplier
- Sentinel `evaluate_intent()` gets conviction-based sizing modifier alongside signal registry
- Dashboard gets new `/api/intel` endpoint + `/intel` Telegram command
- All consumers handle `None` gracefully — if Prism is down, trading continues normally

---

## Task 1: Scaffolding and config files

**Files to create:**
- `market_intel/__init__.py`
- `market_intel/analytics/__init__.py`
- `market_intel/conviction/__init__.py`
- `market_intel/config/__init__.py`
- `market_intel/tests/__init__.py`
- `market_intel/requirements.txt`
- `market_intel/config/subscriptions.yaml`
- `market_intel/config/weights.yaml`
- `market_intel/config/patterns.yaml`

**Step 1:** Create directory structure and empty `__init__.py` files.

```bash
cd /Users/jasonljc/trading
mkdir -p market_intel/analytics market_intel/conviction market_intel/config market_intel/tests
touch market_intel/__init__.py
touch market_intel/analytics/__init__.py
touch market_intel/conviction/__init__.py
touch market_intel/config/__init__.py
touch market_intel/tests/__init__.py
```

**Step 2:** Create `market_intel/requirements.txt`.

```text
ib_insync>=0.9.86
redis>=5.0.0
numpy>=1.24.0
```

**Step 3:** Create `market_intel/config/subscriptions.yaml` with IB contract definitions.

```yaml
# IB contract definitions for all symbols polled by Market Intel
# Each entry: symbol, exchange, secType, currency, poll_interval_seconds

core_futures:
  ES:
    exchange: CME
    secType: FUT
    currency: USD
    poll_interval: 5
  NQ:
    exchange: CME
    secType: FUT
    currency: USD
    poll_interval: 5
  CL:
    exchange: NYMEX
    secType: FUT
    currency: USD
    poll_interval: 5
  GC:
    exchange: COMEX
    secType: FUT
    currency: USD
    poll_interval: 5
  ZB:
    exchange: CBOT
    secType: FUT
    currency: USD
    poll_interval: 5
  MES:
    exchange: CME
    secType: FUT
    currency: USD
    poll_interval: 5
  MNQ:
    exchange: CME
    secType: FUT
    currency: USD
    poll_interval: 5
  MCL:
    exchange: NYMEX
    secType: FUT
    currency: USD
    poll_interval: 5
  MGC:
    exchange: COMEX
    secType: FUT
    currency: USD
    poll_interval: 5

cross_market:
  VIX:
    exchange: CBOE
    secType: IND
    currency: USD
    poll_interval: 10
  DXY:
    exchange: ICE
    secType: IND
    currency: USD
    poll_interval: 10
  TNX:
    exchange: CBOE
    secType: IND
    currency: USD
    poll_interval: 10
  HYG:
    exchange: ARCA
    secType: STK
    currency: USD
    poll_interval: 10
  XLF:
    exchange: ARCA
    secType: STK
    currency: USD
    poll_interval: 10

# Options chains: front 2 months, ±5 strikes ATM, 60s poll
options_instruments:
  - ES
  - NQ
  - CL

# Depth of market: top 5 levels, 5s poll
dom_instruments:
  - ES
  - NQ
  - CL
  - GC
  - ZB

# Tick stream: trade-by-trade, 1s poll (in-memory ring buffer only)
tick_instruments:
  - ES
  - NQ
  - CL
  - GC
  - ZB

# Staleness threshold multiplier (data older than N × poll_interval flagged stale)
staleness_multiplier: 3
```

**Step 4:** Create `market_intel/config/weights.yaml` with regime-adaptive factor weights.

```yaml
# Factor weights per regime for weighted fallback scoring
# Each regime: 6 factors sum to 100%

TRENDING:
  velocity_alignment: 0.25
  divergence_score: 0.20
  gex_tailwind: 0.15
  options_flow: 0.15
  signal_integration: 0.15
  relative_volume: 0.10

VOLATILE:
  velocity_alignment: 0.15
  divergence_score: 0.25
  gex_tailwind: 0.20
  options_flow: 0.20
  signal_integration: 0.10
  relative_volume: 0.10

NEUTRAL:
  velocity_alignment: 0.20
  divergence_score: 0.25
  gex_tailwind: 0.15
  options_flow: 0.15
  signal_integration: 0.15
  relative_volume: 0.10
```

**Step 5:** Create `market_intel/config/patterns.yaml` with 15 named pattern definitions.

```yaml
# Named patterns for conviction scoring
# Each pattern: direction (LONG/SHORT/NEUTRAL), base_score (60-95), confidence (MEDIUM/HIGH), conditions list

patterns:
  TREND_ACCELERATION:
    direction: LONG  # or SHORT depending on velocity sign
    base_score: 85
    confidence: HIGH
    conditions:
      - "gex < 0"
      - "velocity_15m > velocity_5m"  # acceleration
      - "velocity_5m > 0"  # bullish trend
      - "relative_volume > 1.5"
      - "aligned_signal_count > 0"

  REGIME_FLIP:
    direction: DYNAMIC  # from regime_transition.to_regime
    base_score: 90
    confidence: HIGH
    conditions:
      - "regime_transition.detected == True"
      - "book_imbalance > 1.3 OR book_imbalance < 0.7"  # confirming direction
      - "velocity_5m aligns with new_regime"

  SMART_MONEY_DIVERGENCE:
    direction: DYNAMIC  # opposite of current price direction
    base_score: 80
    confidence: HIGH
    conditions:
      - "unusual_flow_direction != price_direction"
      - "absorption_detected == True"
      - "book_imbalance confirms unusual_flow_direction"

  MOMENTUM_EXHAUSTION:
    direction: DYNAMIC  # contrarian to current velocity
    base_score: 75
    confidence: MEDIUM
    conditions:
      - "abs(velocity_5m) > 80"
      - "gex flipping sign"  # was negative, now positive or vice versa
      - "skew_shift > 2.0"  # spiking
      - "volume_accel < 1.0"  # volume declining

  BREAKOUT_IMMINENT:
    direction: NEUTRAL  # wait for direction confirmation
    base_score: 70
    confidence: MEDIUM
    conditions:
      - "velocity_5m < 20 AND velocity_15m < 20 AND velocity_1h < 20"  # compressed
      - "book_depth < 0.5 * avg_book_depth"  # thinning
      - "iv_term_slope < 0"  # inverting (backwardation)

  FEAR_CAPITULATION:
    direction: LONG  # contrarian long at fear peak
    base_score: 78
    confidence: MEDIUM
    conditions:
      - "velocity_vix > 40"  # VIX accelerating up
      - "put_call_ratio > 1.5"
      - "velocity_5m < -60"  # ES deeply negative
      - "gex < -500"  # deeply negative

  GREED_EXHAUSTION:
    direction: SHORT  # contrarian short at greed peak
    base_score: 78
    confidence: MEDIUM
    conditions:
      - "vix < vix_20d_avg * 0.8"  # VIX at lows
      - "call_put_ratio > 1.5"
      - "velocity_5m > 60"  # ES deeply positive
      - "gex > 0 AND gex_flipping_positive"  # just flipped positive

  CROSS_ASSET_CONFIRMATION:
    direction: DYNAMIC  # from majority of divergence pairs
    base_score: 88
    confidence: HIGH
    conditions:
      - "aligned_divergence_count >= 3"  # 3+ pairs confirming same direction
      - "relative_volume > 1.0"

  INSTITUTIONAL_ACCUMULATION:
    direction: LONG  # or SHORT if selling
    base_score: 82
    confidence: HIGH
    conditions:
      - "absorption_detected == True"
      - "book_imbalance > 1.3 OR book_imbalance < 0.7"
      - "abs(velocity_5m) < 15"  # price flat
      - "volume_accel > 1.2"  # volume rising

  LIQUIDITY_VACUUM:
    direction: DYNAMIC  # current velocity direction
    base_score: 85
    confidence: HIGH
    conditions:
      - "book_depth < 0.5 * avg_book_depth"
      - "velocity_5m accelerating"  # abs(velocity_5m) > abs(velocity_15m)
      - "relative_volume > 1.3"

  TERM_STRUCTURE_SIGNAL:
    direction: DYNAMIC  # from term structure flip
    base_score: 73
    confidence: MEDIUM
    conditions:
      - "iv_term_slope flipping sign"  # contango→backwardation or vice versa
      - "gex confirming direction"

  DOLLAR_DRIVEN:
    direction: DYNAMIC  # CL/GC inverse to DXY
    base_score: 80
    confidence: HIGH
    conditions:
      - "abs(velocity_dxy) > 60"
      - "divergence_cl_dxy < -0.6 OR divergence_gc_dxy < -0.6"  # strong inverse

  CREDIT_STRESS:
    direction: SHORT  # risk-off ES setup
    base_score: 83
    confidence: HIGH
    conditions:
      - "divergence_es_hyg < -0.5"  # HYG not confirming ES
      - "velocity_tnx > 30"  # rates rising
      - "skew_shift > 1.5"  # skew widening

  NEWS_AMPLIFIER:
    direction: DYNAMIC  # from active news signal
    base_score: 92
    confidence: HIGH
    conditions:
      - "aligned_signal_count > 0"
      - "unusual_flow_direction == signal_direction"
      - "velocity_5m confirms signal_direction"

  DEAD_MARKET:
    direction: NEUTRAL  # anti-conviction, sit out
    base_score: 0  # forces hold_conviction to dominate
    confidence: LOW
    conditions:
      - "relative_volume < 0.5"
      - "abs(velocity_5m) < 10 AND abs(velocity_15m) < 10 AND abs(velocity_1h) < 10"
      - "book_depth < 0.6 * avg_book_depth"
```

No tests for scaffolding. Just create files and commit.

**Commit:**

```bash
cd /Users/jasonljc/trading
git add market_intel/
git commit -m "feat: scaffold market_intel package with config files"
```

---

## Task 2: Data layer with IB wrapper and Redis caching

**Files:**
- Create: `market_intel/data_layer.py`
- Test: `market_intel/tests/test_data_layer.py`

**Step 1:** Create `market_intel/data_layer.py` with `IBDataManager` class.

```python
"""Data layer for Market Intel — IB polling and Redis caching."""

import json
import time
from typing import Optional
from datetime import datetime, timedelta


class IBDataManager:
    """Manages IB data polling and Redis caching with staleness detection."""

    def __init__(self, ib=None, redis_client=None):
        """
        Initialize data manager.

        Args:
            ib: ib_insync.IB instance (or None for graceful degradation)
            redis_client: redis.Redis instance (or None for graceful degradation)
        """
        self.ib = ib
        self.redis = redis_client
        self.poll_intervals = {
            "quotes": 5,
            "cross_market": 10,
            "options": 60,
            "dom": 5,
            "ticks": 1,
        }
        self.staleness_multiplier = 3

    def poll_quotes(self, symbols: list[str]) -> dict:
        """
        Poll quote data for core futures.

        Args:
            symbols: List of symbols to poll (e.g., ["ES", "NQ", "CL"])

        Returns:
            Dict mapping symbol to quote data, or empty dict on error
        """
        if not self.ib:
            return {}

        quotes = {}
        try:
            for symbol in symbols:
                # In real impl: use ib.reqMktData() or ib.ticker()
                # For now, mock structure
                ticker = self._get_ticker(symbol)
                if ticker:
                    quote_data = {
                        "bid": ticker.get("bid", 0.0),
                        "ask": ticker.get("ask", 0.0),
                        "last": ticker.get("last", 0.0),
                        "volume": ticker.get("volume", 0),
                        "bid_size": ticker.get("bid_size", 0),
                        "ask_size": ticker.get("ask_size", 0),
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                    quotes[symbol] = quote_data

                    # Cache in Redis
                    if self.redis:
                        try:
                            self.redis.hset(
                                f"market_intel:quotes:{symbol}",
                                mapping={
                                    "data": json.dumps(quote_data),
                                    "timestamp": quote_data["timestamp"],
                                },
                            )
                        except Exception:
                            pass  # Redis failure doesn't stop data collection
        except Exception:
            return {}

        return quotes

    def poll_cross_market(self, symbols: list[str]) -> dict:
        """
        Poll cross-market data (VIX, DXY, TNX, HYG, XLF).

        Args:
            symbols: List of cross-market symbols

        Returns:
            Dict mapping symbol to quote data, or empty dict on error
        """
        if not self.ib:
            return {}

        cross_data = {}
        try:
            for symbol in symbols:
                ticker = self._get_ticker(symbol)
                if ticker:
                    data = {
                        "bid": ticker.get("bid", 0.0),
                        "ask": ticker.get("ask", 0.0),
                        "last": ticker.get("last", 0.0),
                        "volume": ticker.get("volume", 0),
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                    cross_data[symbol] = data

                    # Cache in Redis
                    if self.redis:
                        try:
                            self.redis.hset(
                                f"market_intel:cross:{symbol}",
                                mapping={
                                    "data": json.dumps(data),
                                    "timestamp": data["timestamp"],
                                },
                            )
                        except Exception:
                            pass
        except Exception:
            return {}

        return cross_data

    def poll_options(self, symbol: str) -> dict:
        """
        Poll options chain for given symbol (front 2 months, ±5 strikes ATM).

        Args:
            symbol: Symbol to poll options for (e.g., "ES")

        Returns:
            Dict with chain data, or empty dict on error
        """
        if not self.ib:
            return {}

        try:
            # In real impl: use ib.reqSecDefOptParams() + ib.reqMktData() for each strike
            # For now, mock structure
            chain_data = {
                "symbol": symbol,
                "strikes": [],  # List of strike dicts
                "timestamp": datetime.utcnow().isoformat(),
            }

            # Cache in Redis
            if self.redis:
                try:
                    self.redis.hset(
                        f"market_intel:options:{symbol}",
                        mapping={
                            "data": json.dumps(chain_data),
                            "timestamp": chain_data["timestamp"],
                        },
                    )
                except Exception:
                    pass

            return chain_data
        except Exception:
            return {}

    def poll_dom(self, symbols: list[str]) -> dict:
        """
        Poll depth of market (top 5 levels) for given symbols.

        Args:
            symbols: List of symbols to poll DOM for

        Returns:
            Dict mapping symbol to DOM data, or empty dict on error
        """
        if not self.ib:
            return {}

        dom_data = {}
        try:
            for symbol in symbols:
                # In real impl: use ib.reqMktDepth()
                dom = {
                    "symbol": symbol,
                    "bid_prices": [0.0] * 5,
                    "bid_sizes": [0] * 5,
                    "ask_prices": [0.0] * 5,
                    "ask_sizes": [0] * 5,
                    "timestamp": datetime.utcnow().isoformat(),
                }
                dom_data[symbol] = dom

                # Cache in Redis
                if self.redis:
                    try:
                        self.redis.hset(
                            f"market_intel:dom:{symbol}",
                            mapping={
                                "data": json.dumps(dom),
                                "timestamp": dom["timestamp"],
                            },
                        )
                    except Exception:
                        pass
        except Exception:
            return {}

        return dom_data

    def poll_ticks(self, symbols: list[str]) -> dict:
        """
        Poll trade-by-trade tick data for given symbols.

        Args:
            symbols: List of symbols to poll ticks for

        Returns:
            Dict mapping symbol to recent ticks, or empty dict on error
            (Note: ticks stored in-memory ring buffer, not Redis)
        """
        if not self.ib:
            return {}

        tick_data = {}
        try:
            for symbol in symbols:
                # In real impl: use ib.reqTickByTickData()
                ticks = {
                    "symbol": symbol,
                    "ticks": [],  # List of tick dicts
                    "timestamp": datetime.utcnow().isoformat(),
                }
                tick_data[symbol] = ticks
        except Exception:
            return {}

        return tick_data

    def get_cached(self, key: str) -> Optional[dict]:
        """
        Get cached data from Redis and check staleness.

        Args:
            key: Redis key (e.g., "market_intel:quotes:ES")

        Returns:
            Dict with cached data, or None if stale/missing/error
        """
        if not self.redis:
            return None

        try:
            cached = self.redis.hgetall(key)
            if not cached:
                return None

            # Check staleness
            data = json.loads(cached[b"data"].decode())
            if self.is_stale(data):
                return None

            return data
        except Exception:
            return None

    def is_stale(self, data: dict) -> bool:
        """
        Check if data is stale based on timestamp.

        Args:
            data: Data dict with "timestamp" field

        Returns:
            True if data is stale, False otherwise
        """
        if "timestamp" not in data:
            return True

        try:
            ts = datetime.fromisoformat(data["timestamp"])
            now = datetime.utcnow()
            age_seconds = (now - ts).total_seconds()

            # Determine poll interval from data type
            # For simplicity, use 5s as default (most aggressive)
            poll_interval = 5
            if "strikes" in data:
                poll_interval = 60  # options
            elif "bid_prices" in data:
                poll_interval = 5  # dom
            elif "ticks" in data:
                poll_interval = 1  # ticks

            stale_threshold = poll_interval * self.staleness_multiplier
            return age_seconds > stale_threshold
        except Exception:
            return True

    def _get_ticker(self, symbol: str) -> Optional[dict]:
        """
        Internal helper to get ticker from IB.

        Args:
            symbol: Symbol to get ticker for

        Returns:
            Dict with ticker data, or None on error
        """
        try:
            # In real impl: return self.ib.ticker(contract)
            # For testing, return None (will be mocked)
            return None
        except Exception:
            return None
```

**Step 2:** Create `market_intel/tests/test_data_layer.py` with 8 tests.

```python
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
    """Fixture providing mock IB connection."""
    return MockIB()


@pytest.fixture
def fake_redis():
    """Fixture providing fake Redis client."""
    return FakeRedis()


@pytest.fixture
def manager(mock_ib, fake_redis):
    """Fixture providing IBDataManager with mocks."""
    mgr = IBDataManager(ib=mock_ib, redis_client=fake_redis)
    # Monkey-patch _get_ticker to use mock data
    def _get_ticker(symbol):
        return mock_ib.tickers.get(symbol)
    mgr._get_ticker = _get_ticker
    return mgr


def test_quote_caching(manager, fake_redis):
    """Test that poll_quotes writes to Redis HSET."""
    quotes = manager.poll_quotes(["ES"])

    assert "ES" in quotes
    assert quotes["ES"]["bid"] == 5400.0
    assert quotes["ES"]["ask"] == 5400.25

    # Check Redis
    cached = fake_redis.hgetall("market_intel:quotes:ES")
    assert cached
    data = json.loads(cached[b"data"].decode())
    assert data["bid"] == 5400.0


def test_cross_market_caching(manager, fake_redis):
    """Test that poll_cross_market writes to Redis HSET."""
    cross = manager.poll_cross_market(["VIX"])

    assert "VIX" in cross
    assert cross["VIX"]["last"] == 18.05

    # Check Redis
    cached = fake_redis.hgetall("market_intel:cross:VIX")
    assert cached
    data = json.loads(cached[b"data"].decode())
    assert data["last"] == 18.05


def test_options_caching(manager, fake_redis):
    """Test that poll_options writes to Redis HSET."""
    chain = manager.poll_options("ES")

    assert chain["symbol"] == "ES"
    assert "strikes" in chain

    # Check Redis
    cached = fake_redis.hgetall("market_intel:options:ES")
    assert cached
    data = json.loads(cached[b"data"].decode())
    assert data["symbol"] == "ES"


def test_dom_caching(manager, fake_redis):
    """Test that poll_dom writes to Redis HSET."""
    dom = manager.poll_dom(["ES"])

    assert "ES" in dom
    assert "bid_prices" in dom["ES"]

    # Check Redis
    cached = fake_redis.hgetall("market_intel:dom:ES")
    assert cached
    data = json.loads(cached[b"data"].decode())
    assert "bid_prices" in data


def test_staleness_detection(manager):
    """Test that data older than 3x poll interval is flagged stale."""
    old_data = {
        "bid": 5400.0,
        "timestamp": (datetime.utcnow() - timedelta(seconds=20)).isoformat(),
    }
    assert manager.is_stale(old_data) is True


def test_fresh_data_not_stale(manager):
    """Test that recent data is not flagged stale."""
    fresh_data = {
        "bid": 5400.0,
        "timestamp": datetime.utcnow().isoformat(),
    }
    assert manager.is_stale(fresh_data) is False


def test_no_ib_graceful(fake_redis):
    """Test that missing IB connection returns empty dict."""
    manager = IBDataManager(ib=None, redis_client=fake_redis)
    quotes = manager.poll_quotes(["ES"])
    assert quotes == {}


def test_no_redis_graceful(mock_ib):
    """Test that missing Redis connection still polls IB and returns data."""
    manager = IBDataManager(ib=mock_ib, redis_client=None)
    # Monkey-patch _get_ticker
    def _get_ticker(symbol):
        return mock_ib.tickers.get(symbol)
    manager._get_ticker = _get_ticker

    quotes = manager.poll_quotes(["ES"])
    assert "ES" in quotes
    assert quotes["ES"]["bid"] == 5400.0
```

**Test command:**

```bash
cd /Users/jasonljc/trading
python3 -m pytest market_intel/tests/test_data_layer.py -v --tb=short
```

**Commit:**

```bash
cd /Users/jasonljc/trading
git add market_intel/
git commit -m "feat: data layer with IB wrapper and Redis caching (8 tests)"
```

---

## Task 3: Velocity engine

**Files:**
- Create: `market_intel/analytics/velocity.py`
- Test: `market_intel/tests/test_velocity.py`

**Step 1:** Create `market_intel/analytics/velocity.py` with pure function.

```python
"""Velocity engine — rate-of-change computation for 5m/15m/1h windows."""

from typing import List, Dict
from datetime import datetime, timedelta


def compute_velocity(price_history: List[Dict]) -> Dict:
    """
    Compute velocity metrics from price history.

    Args:
        price_history: List of {"price": float, "volume": float, "timestamp": str}
                       entries, newest last

    Returns:
        Dict with {
            "velocity_5m": float (-100 to +100),
            "velocity_15m": float (-100 to +100),
            "velocity_1h": float (-100 to +100),
            "volume_accel": float (current 5min vol / avg 5min vol over hour)
        }
    """
    if not price_history:
        return {
            "velocity_5m": 0.0,
            "velocity_15m": 0.0,
            "velocity_1h": 0.0,
            "volume_accel": 0.0,
        }

    # Parse timestamps and sort (should already be sorted newest last)
    history = []
    for entry in price_history:
        try:
            ts = datetime.fromisoformat(entry["timestamp"])
            history.append({
                "price": entry["price"],
                "volume": entry["volume"],
                "timestamp": ts,
            })
        except Exception:
            continue

    if not history:
        return {
            "velocity_5m": 0.0,
            "velocity_15m": 0.0,
            "velocity_1h": 0.0,
            "volume_accel": 0.0,
        }

    # Current time (most recent entry)
    now = history[-1]["timestamp"]
    current_price = history[-1]["price"]

    # Compute velocities
    velocity_5m = _compute_window_velocity(history, now, minutes=5, current_price=current_price, max_pct=2.0)
    velocity_15m = _compute_window_velocity(history, now, minutes=15, current_price=current_price, max_pct=5.0)
    velocity_1h = _compute_window_velocity(history, now, minutes=60, current_price=current_price, max_pct=10.0)

    # Compute volume acceleration
    volume_accel = _compute_volume_accel(history, now)

    return {
        "velocity_5m": velocity_5m,
        "velocity_15m": velocity_15m,
        "velocity_1h": velocity_1h,
        "volume_accel": volume_accel,
    }


def _compute_window_velocity(history: List[Dict], now: datetime, minutes: int, current_price: float, max_pct: float) -> float:
    """
    Compute velocity for a specific time window.

    Args:
        history: Sorted price history
        now: Current timestamp
        minutes: Window size in minutes
        current_price: Current price
        max_pct: Maximum expected percentage change for normalization

    Returns:
        Velocity score -100 to +100
    """
    window_start = now - timedelta(minutes=minutes)

    # Find first entry in window
    window_entries = [e for e in history if e["timestamp"] >= window_start]

    if not window_entries or len(window_entries) < 2:
        return 0.0

    start_price = window_entries[0]["price"]
    if start_price == 0:
        return 0.0

    # Percentage change
    pct_change = ((current_price - start_price) / start_price) * 100.0

    # Normalize to -100..+100 scale
    normalized = (pct_change / max_pct) * 100.0

    # Cap at +/-100
    return max(-100.0, min(100.0, normalized))


def _compute_volume_accel(history: List[Dict], now: datetime) -> float:
    """
    Compute volume acceleration (current 5min vol / avg 5min vol over hour).

    Args:
        history: Sorted price history
        now: Current timestamp

    Returns:
        Volume acceleration ratio (>1.5 = surging, <0.7 = dying)
    """
    # Current 5-minute window volume
    window_5m = now - timedelta(minutes=5)
    recent_entries = [e for e in history if e["timestamp"] >= window_5m]
    current_vol = sum(e["volume"] for e in recent_entries)

    # Average 5-minute volume over last hour
    window_1h = now - timedelta(minutes=60)
    hour_entries = [e for e in history if e["timestamp"] >= window_1h]

    if not hour_entries:
        return 0.0

    # Split hour into 5-minute buckets
    buckets = []
    for i in range(12):  # 12 × 5min = 60min
        bucket_start = window_1h + timedelta(minutes=i * 5)
        bucket_end = bucket_start + timedelta(minutes=5)
        bucket_vol = sum(e["volume"] for e in hour_entries if bucket_start <= e["timestamp"] < bucket_end)
        if bucket_vol > 0:
            buckets.append(bucket_vol)

    if not buckets:
        return 0.0

    avg_vol = sum(buckets) / len(buckets)
    if avg_vol == 0:
        return 0.0

    return current_vol / avg_vol
```

**Step 2:** Create `market_intel/tests/test_velocity.py` with 8 tests.

```python
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
```

**Test command:**

```bash
cd /Users/jasonljc/trading
python3 -m pytest market_intel/tests/test_velocity.py -v --tb=short
```

**Commit:**

```bash
cd /Users/jasonljc/trading
git add market_intel/
git commit -m "feat: velocity engine with 5m/15m/1h rate-of-change (8 tests)"
```

---

## Task 4: Divergence detector

**Files:**
- Create: `market_intel/analytics/divergence.py`
- Test: `market_intel/tests/test_divergence.py`

Pure function: `compute_divergences(quotes: dict[str, dict], history: dict[str, list]) -> dict[str, float]`

Input: current quotes dict `{"ES": {"last": 5400, ...}, "VIX": {"last": 18, ...}, ...}` and recent price history per symbol.

The 6 pairs from the design:
- `es_vix`: ES vs VIX (inverse) — both rising = divergence (VIX should fall when ES rises)
- `es_nq`: ES vs NQ (correlated) — moving opposite = divergence
- `cl_dxy`: CL vs DXY (inverse)
- `gc_dxy`: GC vs DXY (inverse)
- `gc_tnx`: GC vs TNX (inverse)
- `es_hyg`: ES vs HYG (correlated)

Each scored -1.0 (bearish divergence) to +1.0 (bullish divergence), 0.0 = normal.

Logic: compute 15-min returns for both symbols. For inverse pairs: if both moving same direction, that's a divergence. For correlated pairs: if moving opposite, that's a divergence. Scale by magnitude.

**Step 1: Create `market_intel/analytics/divergence.py`**

```python
"""
Divergence detector — cross-asset relationship monitoring.

Tracks 6 key pairs:
- ES vs VIX (inverse)
- ES vs NQ (correlated)
- CL vs DXY (inverse)
- GC vs DXY (inverse)
- GC vs TNX (inverse)
- ES vs HYG (correlated)

Returns divergence scores from -1.0 (bearish) to +1.0 (bullish).
"""

import numpy as np
from typing import Dict, List


def compute_divergences(
    quotes: Dict[str, dict],
    history: Dict[str, List[float]]
) -> Dict[str, float]:
    """
    Compute cross-asset divergences.

    Args:
        quotes: Current price quotes, e.g. {"ES": {"last": 5400}, "VIX": {"last": 18}}
        history: Recent price history per symbol, e.g. {"ES": [5380, 5390, 5400]}
                 Last element should match current quote.

    Returns:
        Dict with 6 divergence scores, each in range [-1.0, +1.0]:
        - Negative = bearish divergence
        - Zero = normal relationship
        - Positive = bullish divergence
    """
    # Define the 6 pairs: (symbol1, symbol2, relationship_type)
    # relationship_type: "inverse" or "correlated"
    pairs = [
        ("ES", "VIX", "inverse"),
        ("ES", "NQ", "correlated"),
        ("CL", "DXY", "inverse"),
        ("GC", "DXY", "inverse"),
        ("GC", "TNX", "inverse"),
        ("ES", "HYG", "correlated"),
    ]

    results = {}

    for sym1, sym2, rel_type in pairs:
        key = f"{sym1.lower()}_{sym2.lower()}"

        # Check data availability
        if sym1 not in history or sym2 not in history:
            results[key] = 0.0
            continue

        hist1 = history[sym1]
        hist2 = history[sym2]

        if len(hist1) < 2 or len(hist2) < 2:
            results[key] = 0.0
            continue

        # Compute 15-min return (last price vs price from 15 min ago)
        # Assume history contains prices at regular intervals
        ret1 = _compute_return(hist1)
        ret2 = _compute_return(hist2)

        # Check for zero movement
        if abs(ret1) < 1e-6 and abs(ret2) < 1e-6:
            results[key] = 0.0
            continue

        # Compute divergence based on relationship type
        div_score = _compute_divergence_score(ret1, ret2, rel_type)

        # Cap at [-1.0, +1.0]
        results[key] = np.clip(div_score, -1.0, 1.0)

    return results


def _compute_return(prices: List[float]) -> float:
    """Compute percentage return from recent prices."""
    if len(prices) < 2:
        return 0.0

    # Use first and last price in the window
    old_price = prices[0]
    new_price = prices[-1]

    if old_price == 0:
        return 0.0

    return (new_price - old_price) / old_price


def _compute_divergence_score(ret1: float, ret2: float, rel_type: str) -> float:
    """
    Compute divergence score based on relationship type.

    For inverse pairs (e.g., ES vs VIX):
        - Both moving same direction = divergence
        - If ES up and VIX up = bearish divergence (negative score)
        - If ES down and VIX down = bullish divergence (positive score)

    For correlated pairs (e.g., ES vs NQ):
        - Moving opposite = divergence
        - If ES up and NQ down = bearish divergence (negative score)
        - If ES down and NQ up = bullish divergence (positive score)

    Returns:
        Score in approximate range [-1.0, +1.0]
        Magnitude scaled by size of returns
    """
    if rel_type == "inverse":
        # Both should move opposite. If they move together, that's a divergence.
        # Product of returns: positive = moving same direction (divergence)
        product = ret1 * ret2

        if product > 0:  # Divergence detected
            # If ret1 > 0 (asset up) and ret2 > 0 (inverse indicator also up)
            # -> bearish divergence (negative score)
            # If ret1 < 0 (asset down) and ret2 < 0 (inverse indicator also down)
            # -> bullish divergence (positive score)

            # Scale by magnitude of returns (use average)
            magnitude = (abs(ret1) + abs(ret2)) / 2.0
            # Normalize to ~[-1, +1] range (assuming returns typically < 0.1 or 10%)
            magnitude = min(magnitude * 10.0, 1.0)

            # Sign: negative ret1 means bullish divergence
            sign = -np.sign(ret1)
            return sign * magnitude
        else:
            # Normal inverse relationship
            return 0.0

    elif rel_type == "correlated":
        # Both should move together. If they move opposite, that's a divergence.
        product = ret1 * ret2

        if product < 0:  # Divergence detected (opposite directions)
            # If ret1 > 0 (asset up) and ret2 < 0 (correlated down)
            # -> bearish divergence (negative score)
            # If ret1 < 0 (asset down) and ret2 > 0 (correlated up)
            # -> bullish divergence (positive score)

            magnitude = (abs(ret1) + abs(ret2)) / 2.0
            magnitude = min(magnitude * 10.0, 1.0)

            # Sign: negative ret1 means bullish divergence
            sign = -np.sign(ret1)
            return sign * magnitude
        else:
            # Normal correlated relationship
            return 0.0

    else:
        return 0.0
```

**Step 2: Create `market_intel/tests/test_divergence.py`**

```python
"""
Tests for divergence detector.
"""

import pytest
from market_intel.analytics.divergence import compute_divergences


def test_es_vix_divergence_bullish():
    """ES down, VIX also down -> bullish divergence (positive score)."""
    quotes = {
        "ES": {"last": 5200},
        "VIX": {"last": 16},
    }
    history = {
        "ES": [5400, 5300, 5200],  # Down 3.7%
        "VIX": [18, 17, 16],        # Down 11.1%
    }

    result = compute_divergences(quotes, history)

    assert "es_vix" in result
    # Both down = bullish divergence for ES
    assert result["es_vix"] > 0.3


def test_es_vix_normal():
    """ES up, VIX down -> normal inverse relationship (score ~0)."""
    quotes = {
        "ES": {"last": 5400},
        "VIX": {"last": 16},
    }
    history = {
        "ES": [5200, 5300, 5400],  # Up
        "VIX": [18, 17, 16],        # Down
    }

    result = compute_divergences(quotes, history)

    assert "es_vix" in result
    # Normal inverse relationship
    assert abs(result["es_vix"]) < 0.1


def test_cl_dxy_divergence():
    """CL up, DXY also up -> divergence (bearish for CL)."""
    quotes = {
        "CL": {"last": 75},
        "DXY": {"last": 104},
    }
    history = {
        "CL": [70, 72, 75],    # Up
        "DXY": [100, 102, 104], # Up
    }

    result = compute_divergences(quotes, history)

    assert "cl_dxy" in result
    # Both up = bearish divergence for CL
    assert result["cl_dxy"] < -0.3


def test_correlated_pair_divergence():
    """ES up, NQ down -> divergence (bearish for ES)."""
    quotes = {
        "ES": {"last": 5400},
        "NQ": {"last": 18000},
    }
    history = {
        "ES": [5200, 5300, 5400],  # Up
        "NQ": [18800, 18400, 18000], # Down
    }

    result = compute_divergences(quotes, history)

    assert "es_nq" in result
    # Opposite directions = bearish divergence
    assert result["es_nq"] < -0.3


def test_no_data_returns_zeros():
    """Missing symbols return 0.0."""
    quotes = {
        "ES": {"last": 5400},
    }
    history = {
        "ES": [5300, 5350, 5400],
    }

    result = compute_divergences(quotes, history)

    # All pairs involving missing symbols should be 0.0
    assert result["es_vix"] == 0.0
    assert result["cl_dxy"] == 0.0
    assert result["gc_dxy"] == 0.0


def test_all_pairs_computed():
    """Verify all 6 pairs are present in output."""
    quotes = {
        "ES": {"last": 5400},
        "VIX": {"last": 18},
        "NQ": {"last": 18500},
        "CL": {"last": 75},
        "GC": {"last": 2200},
        "DXY": {"last": 103},
        "TNX": {"last": 4.2},
        "HYG": {"last": 78},
    }
    history = {
        sym: [quotes[sym]["last"] - 10, quotes[sym]["last"] - 5, quotes[sym]["last"]]
        for sym in quotes
    }

    result = compute_divergences(quotes, history)

    expected_keys = ["es_vix", "es_nq", "cl_dxy", "gc_dxy", "gc_tnx", "es_hyg"]
    for key in expected_keys:
        assert key in result


def test_capped_at_bounds():
    """Extreme divergence values are capped at +/-1.0."""
    quotes = {
        "ES": {"last": 6000},
        "VIX": {"last": 40},
    }
    history = {
        "ES": [5000, 5500, 6000],  # Up 20%
        "VIX": [20, 30, 40],        # Up 100%
    }

    result = compute_divergences(quotes, history)

    # Should be capped at -1.0 (bearish divergence)
    assert result["es_vix"] >= -1.0
    assert result["es_vix"] <= 1.0


def test_flat_market_zero():
    """No movement in either symbol -> all zeros."""
    quotes = {
        "ES": {"last": 5400},
        "VIX": {"last": 18},
        "NQ": {"last": 18500},
        "CL": {"last": 75},
        "GC": {"last": 2200},
        "DXY": {"last": 103},
        "TNX": {"last": 4.2},
        "HYG": {"last": 78},
    }
    history = {
        sym: [quotes[sym]["last"], quotes[sym]["last"], quotes[sym]["last"]]
        for sym in quotes
    }

    result = compute_divergences(quotes, history)

    # All flat -> all zeros
    for score in result.values():
        assert score == 0.0
```

**Tests (8):**
- `test_es_vix_divergence_bullish` — ES down, VIX also down -> positive (bullish divergence)
- `test_es_vix_normal` — ES up, VIX down -> ~0 (normal inverse)
- `test_cl_dxy_divergence` — CL up, DXY also up -> negative (bearish divergence)
- `test_correlated_pair_divergence` — ES up, NQ down -> negative (bearish divergence)
- `test_no_data_returns_zeros` — missing symbols -> 0.0
- `test_all_pairs_computed` — verify all 6 keys present
- `test_capped_at_bounds` — extreme values capped at +/-1.0
- `test_flat_market_zero` — no movement -> all zeros

**Test command:** `cd /Users/jasonljc/trading && python3 -m pytest market_intel/tests/test_divergence.py -v --tb=short`

**Commit:** `cd /Users/jasonljc/trading && git add market_intel/ && git commit -m "feat: divergence detector for 6 cross-asset pairs (8 tests)"`

---

## Task 5: Options intelligence

**Files:**
- Create: `market_intel/analytics/options_intel.py`
- Test: `market_intel/tests/test_options_intel.py`

Four pure functions:

1. `compute_gex(chain: list[dict]) -> float` — sum of (OI x gamma x contract_multiplier x spot) for calls minus puts. Positive = mean-reversion tailwind, negative = trend tailwind. Normalize to -100..+100 range.

2. `compute_skew(chain: list[dict], historical_skew: float) -> dict` — 25-delta put IV minus 25-delta call IV (approximate using +/-2 strikes from ATM). Return `{"skew": float, "skew_shift": float}` where shift = current - historical average.

3. `detect_unusual_flow(chain: list[dict]) -> list[dict]` — find strikes where volume/OI > 2.0. Return list of `{"strike": float, "type": "call"|"put", "vol_oi_ratio": float, "volume": int}`.

4. `compute_term_structure(front_iv: float, back_iv: float) -> dict` — `{"slope": float, "state": "contango"|"backwardation"|"flat"}`. slope = front - back. Negative = contango (normal, mean-reversion). Positive = backwardation (fear, trend-following).

Options chain entries have these fields: `{"strike": float, "expiry": str, "call_vol": int, "call_oi": int, "call_iv": float, "put_vol": int, "put_oi": int, "put_iv": float}`.

**Step 1: Create `market_intel/analytics/options_intel.py`**

```python
"""
Options intelligence — GEX, skew, unusual flow, term structure.

Four analytics:
1. GEX (gamma exposure) — dealer positioning
2. Skew — put vs call implied volatility
3. Unusual flow — volume spikes
4. Term structure — front vs back month IV
"""

import numpy as np
from typing import Dict, List


def compute_gex(chain: List[dict], spot: float = None) -> float:
    """
    Compute gamma exposure (GEX).

    GEX = sum of (OI × gamma × multiplier × spot) for calls minus puts

    Positive GEX = heavy call gamma near spot -> mean-reversion regime
    Negative GEX = heavy put gamma -> trend-following regime

    Args:
        chain: List of option entries with keys: strike, call_oi, put_oi
               Optional: call_gamma, put_gamma (defaults to simplified approximation)
        spot: Current underlying price (defaults to ATM strike approximation)

    Returns:
        GEX score normalized to [-100, +100]
    """
    if not chain:
        return 0.0

    # Approximate spot from chain if not provided
    if spot is None:
        strikes = [opt["strike"] for opt in chain]
        spot = np.median(strikes)

    # Contract multiplier (standard for equity options = 100)
    multiplier = 100

    call_gex_total = 0.0
    put_gex_total = 0.0

    for opt in chain:
        strike = opt["strike"]
        call_oi = opt.get("call_oi", 0)
        put_oi = opt.get("put_oi", 0)

        # Simplified gamma approximation (actual gamma requires more inputs)
        # Gamma peaks ATM and decays with distance from spot
        # Use normalized distance: gamma ∝ exp(-0.5 * ((K-S)/S)^2 / sigma^2)
        # Simplified: gamma ∝ 1 / (1 + abs(K - S) / S)
        moneyness = abs(strike - spot) / spot
        gamma_approx = 1.0 / (1.0 + moneyness * 5.0)  # Decay factor = 5

        # GEX contribution
        call_gex_total += call_oi * gamma_approx * multiplier * spot
        put_gex_total += put_oi * gamma_approx * multiplier * spot

    # Net GEX (calls are positive for dealers = negative gamma for market)
    # Dealers are short calls, long puts typically
    # Positive net call OI = dealers short gamma = suppresses vol
    net_gex = call_gex_total - put_gex_total

    # Normalize to [-100, +100] range
    # Typical GEX magnitude is in billions for SPX
    # For ES options, scale to ~1B as typical
    scale_factor = 1e9
    normalized = (net_gex / scale_factor) * 100.0

    return np.clip(normalized, -100.0, 100.0)


def compute_skew(chain: List[dict], historical_skew: float) -> Dict[str, float]:
    """
    Compute put/call IV skew.

    Skew = 25-delta put IV - 25-delta call IV (approximate using strikes ~2 away from ATM)

    Args:
        chain: List of option entries with keys: strike, call_iv, put_iv
        historical_skew: Historical average skew for comparison

    Returns:
        {"skew": current_skew, "skew_shift": current - historical}
    """
    if not chain or len(chain) < 3:
        return {"skew": 0.0, "skew_shift": 0.0}

    # Sort by strike
    sorted_chain = sorted(chain, key=lambda x: x["strike"])

    # Find ATM (middle strike)
    mid_idx = len(sorted_chain) // 2

    # Approximate 25-delta options as +/-2 strikes from ATM
    put_idx = max(0, mid_idx - 2)
    call_idx = min(len(sorted_chain) - 1, mid_idx + 2)

    put_iv = sorted_chain[put_idx].get("put_iv", 0.0)
    call_iv = sorted_chain[call_idx].get("call_iv", 0.0)

    # Skew = put IV - call IV (typically positive, puts trade at premium)
    current_skew = put_iv - call_iv

    # Skew shift = current - historical
    skew_shift = current_skew - historical_skew

    return {
        "skew": current_skew,
        "skew_shift": skew_shift,
    }


def detect_unusual_flow(chain: List[dict]) -> List[dict]:
    """
    Detect unusual option flow (volume spikes relative to open interest).

    Flags strikes where volume/OI > 2.0.

    Args:
        chain: List of option entries with keys: strike, call_vol, call_oi, put_vol, put_oi

    Returns:
        List of unusual flow alerts:
        [{"strike": float, "type": "call"|"put", "vol_oi_ratio": float, "volume": int}, ...]
    """
    unusual = []

    for opt in chain:
        strike = opt["strike"]

        # Check calls
        call_vol = opt.get("call_vol", 0)
        call_oi = opt.get("call_oi", 0)
        if call_oi > 0:
            call_ratio = call_vol / call_oi
            if call_ratio > 2.0:
                unusual.append({
                    "strike": strike,
                    "type": "call",
                    "vol_oi_ratio": round(call_ratio, 2),
                    "volume": call_vol,
                })

        # Check puts
        put_vol = opt.get("put_vol", 0)
        put_oi = opt.get("put_oi", 0)
        if put_oi > 0:
            put_ratio = put_vol / put_oi
            if put_ratio > 2.0:
                unusual.append({
                    "strike": strike,
                    "type": "put",
                    "vol_oi_ratio": round(put_ratio, 2),
                    "volume": put_vol,
                })

    # Sort by vol/OI ratio descending
    unusual.sort(key=lambda x: x["vol_oi_ratio"], reverse=True)

    return unusual


def compute_term_structure(front_iv: float, back_iv: float) -> Dict[str, any]:
    """
    Compute IV term structure.

    Slope = front IV - back IV
    - Negative slope (contango): normal market, mean-reversion regime
    - Positive slope (backwardation): fear/uncertainty, trend-following regime
    - Flat: neutral

    Args:
        front_iv: Front month (near expiry) implied volatility
        back_iv: Back month (far expiry) implied volatility

    Returns:
        {"slope": float, "state": "contango"|"backwardation"|"flat"}
    """
    slope = front_iv - back_iv

    # Classify state
    if slope < -1.0:
        state = "contango"
    elif slope > 1.0:
        state = "backwardation"
    else:
        state = "flat"

    return {
        "slope": round(slope, 2),
        "state": state,
    }
```

**Step 2: Create `market_intel/tests/test_options_intel.py`**

```python
"""
Tests for options intelligence analytics.
"""

import pytest
from market_intel.analytics.options_intel import (
    compute_gex,
    compute_skew,
    detect_unusual_flow,
    compute_term_structure,
)


def test_positive_gex():
    """More call OI near ATM -> positive GEX."""
    chain = [
        {"strike": 5300, "call_oi": 100, "put_oi": 50},
        {"strike": 5350, "call_oi": 500, "put_oi": 100},  # ATM
        {"strike": 5400, "call_oi": 200, "put_oi": 80},
    ]

    gex = compute_gex(chain, spot=5350)

    # Net positive call OI -> positive GEX
    assert gex > 0


def test_negative_gex():
    """More put OI -> negative GEX."""
    chain = [
        {"strike": 5300, "call_oi": 50, "put_oi": 300},
        {"strike": 5350, "call_oi": 100, "put_oi": 500},  # ATM
        {"strike": 5400, "call_oi": 80, "put_oi": 200},
    ]

    gex = compute_gex(chain, spot=5350)

    # Net positive put OI -> negative GEX
    assert gex < 0


def test_gex_empty_chain():
    """Empty chain returns 0.0."""
    gex = compute_gex([])
    assert gex == 0.0


def test_skew_normal():
    """Puts slightly higher IV than calls -> positive skew."""
    chain = [
        {"strike": 5300, "call_iv": 15.0, "put_iv": 18.0},
        {"strike": 5350, "call_iv": 16.0, "put_iv": 19.0},
        {"strike": 5400, "call_iv": 17.0, "put_iv": 20.0},
    ]
    historical_skew = 3.0

    result = compute_skew(chain, historical_skew)

    # Put IV > call IV at OTM strikes
    assert result["skew"] > 2.0


def test_skew_shift_positive():
    """Skew higher than historical -> positive shift."""
    chain = [
        {"strike": 5300, "call_iv": 15.0, "put_iv": 20.0},
        {"strike": 5350, "call_iv": 16.0, "put_iv": 21.0},
        {"strike": 5400, "call_iv": 17.0, "put_iv": 22.0},
    ]
    historical_skew = 3.0

    result = compute_skew(chain, historical_skew)

    # Current skew ~5, historical 3 -> shift ~+2
    assert result["skew_shift"] > 1.0


def test_unusual_flow_detected():
    """Strike with vol/OI > 2 flagged."""
    chain = [
        {"strike": 5300, "call_vol": 100, "call_oi": 200, "put_vol": 50, "put_oi": 100},
        {"strike": 5350, "call_vol": 500, "call_oi": 100, "put_vol": 60, "put_oi": 120},  # Unusual call flow
        {"strike": 5400, "call_vol": 80, "call_oi": 150, "put_vol": 300, "put_oi": 100},  # Unusual put flow
    ]

    unusual = detect_unusual_flow(chain)

    # Should detect 2 unusual strikes
    assert len(unusual) == 2

    # Check call flow at 5350
    call_alert = next((u for u in unusual if u["strike"] == 5350 and u["type"] == "call"), None)
    assert call_alert is not None
    assert call_alert["vol_oi_ratio"] == 5.0

    # Check put flow at 5400
    put_alert = next((u for u in unusual if u["strike"] == 5400 and u["type"] == "put"), None)
    assert put_alert is not None
    assert put_alert["vol_oi_ratio"] == 3.0


def test_no_unusual_flow():
    """All normal activity -> empty list."""
    chain = [
        {"strike": 5300, "call_vol": 100, "call_oi": 200, "put_vol": 50, "put_oi": 100},
        {"strike": 5350, "call_vol": 150, "call_oi": 200, "put_vol": 60, "put_oi": 120},
        {"strike": 5400, "call_vol": 80, "call_oi": 150, "put_vol": 100, "put_oi": 200},
    ]

    unusual = detect_unusual_flow(chain)

    # No vol/OI > 2.0
    assert len(unusual) == 0


def test_term_structure_contango():
    """Front < back -> contango (mean-reversion regime)."""
    front_iv = 15.0
    back_iv = 18.0

    result = compute_term_structure(front_iv, back_iv)

    assert result["slope"] < 0
    assert result["state"] == "contango"


def test_term_structure_backwardation():
    """Front > back -> backwardation (fear/trend regime)."""
    front_iv = 22.0
    back_iv = 16.0

    result = compute_term_structure(front_iv, back_iv)

    assert result["slope"] > 0
    assert result["state"] == "backwardation"


def test_term_structure_flat():
    """Front ~= back -> flat."""
    front_iv = 17.5
    back_iv = 17.0

    result = compute_term_structure(front_iv, back_iv)

    assert result["state"] == "flat"
```

**Tests (10):**
- `test_positive_gex` — more call OI near ATM -> positive
- `test_negative_gex` — more put OI -> negative
- `test_gex_empty_chain` — returns 0.0
- `test_skew_normal` — puts slightly higher IV than calls
- `test_skew_shift_positive` — skew higher than historical -> positive shift
- `test_unusual_flow_detected` — strike with vol/OI > 2 flagged
- `test_no_unusual_flow` — all normal activity -> empty list
- `test_term_structure_contango` — front < back -> contango
- `test_term_structure_backwardation` — front > back -> backwardation
- `test_term_structure_flat` — front ~= back -> flat

**Test command:** `cd /Users/jasonljc/trading && python3 -m pytest market_intel/tests/test_options_intel.py -v --tb=short`

**Commit:** `cd /Users/jasonljc/trading && git add market_intel/ && git commit -m "feat: options intelligence — GEX, skew, unusual flow, term structure (10 tests)"`

---

### Task 6: Microstructure (book imbalance + absorption)

**Files:**
- Create: `market_intel/analytics/__init__.py`
- Create: `market_intel/analytics/microstructure.py`
- Create: `market_intel/tests/test_microstructure.py`

**Step 1: Ensure directory structure**

```bash
mkdir -p /Users/jasonljc/trading/market_intel/analytics /Users/jasonljc/trading/market_intel/tests
touch /Users/jasonljc/trading/market_intel/__init__.py /Users/jasonljc/trading/market_intel/analytics/__init__.py /Users/jasonljc/trading/market_intel/tests/__init__.py
```

**Step 2: Write the failing tests**

File: `market_intel/tests/test_microstructure.py`

```python
"""Tests for book imbalance and absorption detection."""
from __future__ import annotations

import pytest

from market_intel.analytics.microstructure import book_imbalance, detect_absorption


# ── Book Imbalance ───────────────────────────────────────────────────────


class TestBookImbalance:
    def test_buy_pressure(self):
        """Bid sizes >> ask sizes -> positive value (buy pressure)."""
        dom = {
            "bid_sizes": [200, 180, 160, 140, 120],
            "ask_sizes": [50, 40, 30, 20, 10],
        }
        result = book_imbalance(dom)
        assert result > 0.0, f"Expected positive, got {result}"
        assert result <= 1.0

    def test_sell_pressure(self):
        """Ask sizes >> bid sizes -> negative value (sell pressure)."""
        dom = {
            "bid_sizes": [50, 40, 30, 20, 10],
            "ask_sizes": [200, 180, 160, 140, 120],
        }
        result = book_imbalance(dom)
        assert result < 0.0, f"Expected negative, got {result}"
        assert result >= -1.0

    def test_balanced(self):
        """Similar sizes on both sides -> near zero."""
        dom = {
            "bid_sizes": [100, 100, 100, 100, 100],
            "ask_sizes": [100, 100, 100, 100, 100],
        }
        result = book_imbalance(dom)
        assert -0.1 <= result <= 0.1, f"Expected near zero, got {result}"

    def test_empty_dom(self):
        """Empty or missing sizes -> 0.0."""
        assert book_imbalance({"bid_sizes": [], "ask_sizes": []}) == 0.0
        assert book_imbalance({}) == 0.0


# ── Absorption Detection ────────────────────────────────────────────────


class TestAbsorption:
    def test_absorption_detected(self):
        """Large resting bid absorbing many sell trades without price moving."""
        dom = {
            "bid_sizes": [500, 40, 30, 20, 10],  # top-of-book 500 vs avg 120
            "ask_sizes": [50, 40, 30, 20, 10],
            "bid_prices": [100.00, 99.75, 99.50, 99.25, 99.00],
            "ask_prices": [100.25, 100.50, 100.75, 101.00, 101.25],
        }
        ticks = [
            {"price": 100.00, "size": 20, "side": "SELL", "timestamp": "2026-03-17T10:30:00Z"},
            {"price": 100.00, "size": 15, "side": "SELL", "timestamp": "2026-03-17T10:30:01Z"},
            {"price": 100.00, "size": 25, "side": "SELL", "timestamp": "2026-03-17T10:30:02Z"},
            {"price": 100.00, "size": 30, "side": "SELL", "timestamp": "2026-03-17T10:30:03Z"},
            {"price": 100.00, "size": 18, "side": "SELL", "timestamp": "2026-03-17T10:30:04Z"},
        ]
        result = detect_absorption(ticks, dom)
        assert result["detected"] is True
        assert result["side"] == "BUY"
        assert result["level"] == 100.00
        assert result["strength"] > 0.0

    def test_no_absorption(self):
        """Normal trading — no large resting orders."""
        dom = {
            "bid_sizes": [40, 35, 30, 25, 20],
            "ask_sizes": [50, 40, 30, 20, 10],
            "bid_prices": [100.00, 99.75, 99.50, 99.25, 99.00],
            "ask_prices": [100.25, 100.50, 100.75, 101.00, 101.25],
        }
        ticks = [
            {"price": 100.00, "size": 10, "side": "SELL", "timestamp": "2026-03-17T10:30:00Z"},
            {"price": 100.25, "size": 5, "side": "BUY", "timestamp": "2026-03-17T10:30:01Z"},
        ]
        result = detect_absorption(ticks, dom)
        assert result["detected"] is False
        assert result["side"] is None
        assert result["level"] is None

    def test_absorption_sell_side(self):
        """Large resting ask absorbing many buy trades without price moving."""
        dom = {
            "bid_sizes": [50, 40, 30, 20, 10],
            "ask_sizes": [600, 40, 30, 20, 10],  # top-of-book 600 vs avg 140
            "bid_prices": [100.00, 99.75, 99.50, 99.25, 99.00],
            "ask_prices": [100.25, 100.50, 100.75, 101.00, 101.25],
        }
        ticks = [
            {"price": 100.25, "size": 25, "side": "BUY", "timestamp": "2026-03-17T10:30:00Z"},
            {"price": 100.25, "size": 30, "side": "BUY", "timestamp": "2026-03-17T10:30:01Z"},
            {"price": 100.25, "size": 20, "side": "BUY", "timestamp": "2026-03-17T10:30:02Z"},
            {"price": 100.25, "size": 35, "side": "BUY", "timestamp": "2026-03-17T10:30:03Z"},
        ]
        result = detect_absorption(ticks, dom)
        assert result["detected"] is True
        assert result["side"] == "SELL"
        assert result["level"] == 100.25

    def test_empty_ticks(self):
        """No ticks -> not detected."""
        dom = {
            "bid_sizes": [500, 40, 30, 20, 10],
            "ask_sizes": [50, 40, 30, 20, 10],
            "bid_prices": [100.00, 99.75, 99.50, 99.25, 99.00],
            "ask_prices": [100.25, 100.50, 100.75, 101.00, 101.25],
        }
        result = detect_absorption([], dom)
        assert result["detected"] is False


```

**Step 3: Run tests to verify they fail**

```bash
cd /Users/jasonljc/trading && python3 -m pytest market_intel/tests/test_microstructure.py -v --tb=short
```

Expected: ModuleNotFoundError

**Step 4: Implement microstructure.py**

File: `market_intel/analytics/microstructure.py`

```python
"""Microstructure analytics: book imbalance and absorption detection.

Pure functions — no IB or Redis dependency.
"""
from __future__ import annotations


def book_imbalance(dom: dict) -> float:
    """Compute normalized book imbalance from depth-of-market data.

    Returns a float in [-1.0, +1.0]:
      - Positive: buy pressure (bid_sizes dominate)
      - Negative: sell pressure (ask_sizes dominate)
      - 0.0: balanced or empty data

    Raw ratio thresholds: >1.3 = buy pressure, <0.7 = sell pressure.
    Normalized linearly: ratio mapped from [0.0, 2.0] to [-1.0, +1.0],
    clamped to bounds.
    """
    bid_sizes = dom.get("bid_sizes", [])
    ask_sizes = dom.get("ask_sizes", [])

    total_bid = sum(bid_sizes)
    total_ask = sum(ask_sizes)

    if total_bid == 0 and total_ask == 0:
        return 0.0

    if total_ask == 0:
        return 1.0  # infinite bid dominance

    ratio = total_bid / total_ask

    # Normalize: ratio 1.0 -> 0.0, ratio 2.0+ -> +1.0, ratio 0.0 -> -1.0
    normalized = (ratio - 1.0)
    return max(-1.0, min(1.0, normalized))


def detect_absorption(ticks: list[dict], dom: dict) -> dict:
    """Detect absorption: large resting order absorbing trades without price moving.

    Absorption criteria:
    1. Top-of-book size on one side > 3x the average size across all levels on that side
    2. Multiple trades hit that level (same price) without price breaking through
    3. Strength = total absorbed volume / resting order size

    Args:
        ticks: List of trade ticks with price, size, side, timestamp.
        dom: Depth of market with bid_sizes, ask_sizes, bid_prices, ask_prices.

    Returns:
        {"detected": bool, "side": "BUY"|"SELL"|None, "level": float|None, "strength": float}
    """
    result = {"detected": False, "side": None, "level": None, "strength": 0.0}

    if not ticks:
        return result

    bid_sizes = dom.get("bid_sizes", [])
    ask_sizes = dom.get("ask_sizes", [])
    bid_prices = dom.get("bid_prices", [])
    ask_prices = dom.get("ask_prices", [])

    if not bid_sizes or not ask_sizes:
        return result

    # Check bid side for absorption (large bid absorbing sells)
    bid_absorption = _check_side_absorption(
        top_size=bid_sizes[0],
        all_sizes=bid_sizes,
        top_price=bid_prices[0] if bid_prices else None,
        ticks=ticks,
        aggressor_side="SELL",
        resting_side="BUY",
    )

    # Check ask side for absorption (large ask absorbing buys)
    ask_absorption = _check_side_absorption(
        top_size=ask_sizes[0],
        all_sizes=ask_sizes,
        top_price=ask_prices[0] if ask_prices else None,
        ticks=ticks,
        aggressor_side="BUY",
        resting_side="SELL",
    )

    # Return the stronger absorption if both detected
    if bid_absorption["detected"] and ask_absorption["detected"]:
        return bid_absorption if bid_absorption["strength"] >= ask_absorption["strength"] else ask_absorption
    if bid_absorption["detected"]:
        return bid_absorption
    if ask_absorption["detected"]:
        return ask_absorption

    return result


def _check_side_absorption(
    top_size: int,
    all_sizes: list[int],
    top_price: float | None,
    ticks: list[dict],
    aggressor_side: str,
    resting_side: str,
) -> dict:
    """Check one side of the book for absorption."""
    result = {"detected": False, "side": None, "level": None, "strength": 0.0}

    if top_price is None or len(all_sizes) < 2:
        return result

    avg_size = sum(all_sizes) / len(all_sizes)

    # Criterion 1: top-of-book > 3x average
    if top_size <= avg_size * 3:
        return result

    # Criterion 2: multiple aggressor trades at the resting price
    hits_at_level = [
        t for t in ticks
        if t.get("price") == top_price and t.get("side") == aggressor_side
    ]

    if len(hits_at_level) < 3:
        return result

    # Criterion 3: compute strength = total absorbed volume / resting size
    total_absorbed = sum(t.get("size", 0) for t in hits_at_level)
    strength = total_absorbed / top_size if top_size > 0 else 0.0

    return {
        "detected": True,
        "side": resting_side,
        "level": top_price,
        "strength": round(strength, 4),
    }
```

**Step 5: Run tests and verify they pass**

```bash
cd /Users/jasonljc/trading && PYTHONPATH=market_intel:$PYTHONPATH python3 -m pytest market_intel/tests/test_microstructure.py -v --tb=short
```

**Step 6: Commit**

```bash
cd /Users/jasonljc/trading && git add market_intel/ && git commit -m "feat: microstructure analytics — book imbalance and absorption detection"
```

---

### Task 7: Volume profile + regime transition + signal integrator

**Files:**
- Create: `market_intel/analytics/volume_profile.py`
- Create: `market_intel/analytics/regime_transition.py`
- Create: `market_intel/analytics/signal_integrator.py`
- Create: `market_intel/tests/test_volume_profile.py`
- Create: `market_intel/tests/test_regime_transition.py`
- Create: `market_intel/tests/test_signal_integrator.py`

**Step 1: Write the volume profile tests**

File: `market_intel/tests/test_volume_profile.py`

```python
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
```

**Step 2: Write the regime transition tests**

File: `market_intel/tests/test_regime_transition.py`

```python
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
```

**Step 3: Write the signal integrator tests**

File: `market_intel/tests/test_signal_integrator.py`

```python
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
```

**Step 4: Run tests to verify they fail**

```bash
cd /Users/jasonljc/trading && PYTHONPATH=market_intel:$PYTHONPATH python3 -m pytest market_intel/tests/test_volume_profile.py market_intel/tests/test_regime_transition.py market_intel/tests/test_signal_integrator.py -v --tb=short
```

Expected: ModuleNotFoundError

**Step 5: Implement volume_profile.py**

File: `market_intel/analytics/volume_profile.py`

```python
"""Volume profile analytics: relative volume and time-of-day quality.

Pure functions — no IB or Redis dependency.
"""
from __future__ import annotations


def compute_relative_volume(current_volume: int, avg_volume_at_tod: int) -> float:
    """Compute ratio of current volume to historical average at this time-of-day.

    Returns:
        float: ratio (>1.5 = high participation, <0.7 = thin market, 0.0 if avg is zero)
    """
    if avg_volume_at_tod <= 0:
        return 0.0
    return current_volume / avg_volume_at_tod


def get_tod_quality(hour: int, minute: int) -> float:
    """Return time-of-day conviction quality multiplier (ET hours).

    Windows (from design doc Section 4.3):
      09:30-09:45 -> 0.6  (open chop)
      09:45-11:30 -> 1.0  (morning momentum)
      11:30-13:00 -> 0.7  (lunch chop)
      13:00-14:30 -> 1.0  (afternoon session)
      14:30-15:00 -> 0.8  (MOC rebalancing — default; momentum uses 1.1)
      15:00-15:45 -> 0.9  (close)
      Outside RTH -> 0.5
    """
    t = hour * 60 + minute  # minutes since midnight

    rth_open = 9 * 60 + 30   # 09:30
    open_chop_end = 9 * 60 + 45  # 09:45
    morning_end = 11 * 60 + 30   # 11:30
    lunch_end = 13 * 60          # 13:00
    afternoon_end = 14 * 60 + 30  # 14:30
    moc_end = 15 * 60            # 15:00
    close_end = 15 * 60 + 45     # 15:45

    if t < rth_open or t >= close_end:
        return 0.5
    if t < open_chop_end:
        return 0.6
    if t < morning_end:
        return 1.0
    if t < lunch_end:
        return 0.7
    if t < afternoon_end:
        return 1.0
    if t < moc_end:
        return 0.8
    # 15:00 - 15:45
    return 0.9
```

**Step 6: Implement regime_transition.py**

File: `market_intel/analytics/regime_transition.py`

```python
"""Regime transition detector: detects when regime score is accelerating toward a boundary.

Pure functions — no IB or Redis dependency.
"""
from __future__ import annotations

# Regime boundaries (consistent with brain.py regime classification)
_TRENDING_THRESHOLD = 70
_VOLATILE_THRESHOLD = 70  # on the volatile axis; here we use score direction
_NEUTRAL_UPPER = 65       # below this = NEUTRAL


def detect_regime_transition(regime_history: list[dict]) -> dict:
    """Detect if regime score is accelerating toward a regime boundary.

    Args:
        regime_history: Recent regime entries, oldest first.
            Each: {"score": int, "regime_type": str, "timestamp": str}

    Returns:
        {"detected": bool, "from_regime": str|None, "to_regime": str|None, "confidence": float}
    """
    no_transition = {
        "detected": False,
        "from_regime": None,
        "to_regime": None,
        "confidence": 0.0,
    }

    if len(regime_history) < 3:
        return no_transition

    scores = [entry["score"] for entry in regime_history]
    current_regime = regime_history[-1]["regime_type"]

    # Compute velocity (first derivative) and acceleration (second derivative)
    deltas = [scores[i + 1] - scores[i] for i in range(len(scores) - 1)]

    # Average velocity over recent points
    avg_velocity = sum(deltas) / len(deltas)

    # Check acceleration: is the velocity increasing?
    if len(deltas) >= 2:
        accel = deltas[-1] - deltas[0]
    else:
        accel = 0.0

    # Project where score is heading
    latest_score = scores[-1]
    projected_score = latest_score + avg_velocity * 2  # project 2 intervals ahead

    # Determine if crossing a boundary
    target_regime = _classify_score(projected_score)

    if target_regime == current_regime:
        return no_transition

    # Must have consistent directional movement (not oscillating)
    if avg_velocity > 0 and projected_score <= latest_score:
        return no_transition
    if avg_velocity < 0 and projected_score >= latest_score:
        return no_transition

    # Require meaningful velocity (not just noise)
    if abs(avg_velocity) < 3.0:
        return no_transition

    # Confidence based on velocity magnitude and acceleration agreement
    velocity_factor = min(abs(avg_velocity) / 15.0, 1.0)
    accel_factor = 1.0 if (accel > 0 and avg_velocity > 0) or (accel < 0 and avg_velocity < 0) else 0.5
    confidence = round(velocity_factor * accel_factor, 2)

    return {
        "detected": True,
        "from_regime": current_regime,
        "to_regime": target_regime,
        "confidence": confidence,
    }


def _classify_score(score: float) -> str:
    """Classify a regime score into a regime type."""
    if score >= _TRENDING_THRESHOLD:
        return "TRENDING"
    if score <= 100 - _TRENDING_THRESHOLD:  # low scores = VOLATILE
        return "VOLATILE"
    return "NEUTRAL"
```

**Step 7: Implement signal_integrator.py**

File: `market_intel/analytics/signal_integrator.py`

```python
"""Signal integrator: counts aligned vs opposing signals for a given direction.

Pure functions — no IB or Redis dependency.
"""
from __future__ import annotations


def count_aligned_signals(signals: list[dict], direction: str) -> dict:
    """Count how many active signals align with vs oppose the given direction.

    Args:
        signals: List of signal dicts (from Redis). Each should have a "direction"
                 field ("LONG" or "SHORT"). Signals without a "direction" field are
                 ignored.
        direction: The direction to compare against ("LONG" or "SHORT").

    Returns:
        {"aligned": int, "opposing": int}
    """
    aligned = 0
    opposing = 0

    for sig in signals:
        sig_dir = sig.get("direction")
        if sig_dir is None:
            continue
        if sig_dir == direction:
            aligned += 1
        else:
            opposing += 1

    return {"aligned": aligned, "opposing": opposing}
```

**Step 8: Run tests and verify they pass**

```bash
cd /Users/jasonljc/trading && PYTHONPATH=market_intel:$PYTHONPATH python3 -m pytest market_intel/tests/test_volume_profile.py market_intel/tests/test_regime_transition.py market_intel/tests/test_signal_integrator.py -v --tb=short
```

**Step 9: Commit**

```bash
cd /Users/jasonljc/trading && git add market_intel/ && git commit -m "feat: volume profile, regime transition detector, and signal integrator analytics"
```

---

### Task 8: Temporal decay

**Files:**
- Create: `market_intel/conviction/__init__.py`
- Create: `market_intel/conviction/decay.py`
- Create: `market_intel/tests/test_decay.py`

**Step 1: Ensure directory structure**

```bash
mkdir -p /Users/jasonljc/trading/market_intel/conviction
touch /Users/jasonljc/trading/market_intel/conviction/__init__.py
```

**Step 2: Write the failing tests**

File: `market_intel/tests/test_decay.py`

```python
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
```

**Step 3: Run tests to verify they fail**

```bash
cd /Users/jasonljc/trading && PYTHONPATH=market_intel:$PYTHONPATH python3 -m pytest market_intel/tests/test_decay.py -v --tb=short
```

Expected: ModuleNotFoundError

**Step 4: Implement decay.py**

File: `market_intel/conviction/decay.py`

```python
"""Temporal decay for signal and analytics values.

Pure function — no IB or Redis dependency.
"""
from __future__ import annotations

from datetime import datetime, timezone


def apply_decay(
    value: float,
    onset_time: str,
    half_life_minutes: float,
    now: str | None = None,
) -> float:
    """Apply exponential decay to a value based on elapsed time.

    Formula: value * (0.5 ** (elapsed_minutes / half_life_minutes))

    Args:
        value: The raw score to decay.
        onset_time: ISO timestamp when the signal/value originated.
        half_life_minutes: Time in minutes for the value to halve.
        now: Current ISO timestamp. If None, uses datetime.now(UTC).

    Returns:
        The decayed value (same sign as input, magnitude decreased).
    """
    if value == 0.0:
        return 0.0

    onset_dt = datetime.fromisoformat(onset_time.replace("Z", "+00:00"))

    if now is not None:
        now_dt = datetime.fromisoformat(now.replace("Z", "+00:00"))
    else:
        now_dt = datetime.now(timezone.utc)

    elapsed_seconds = (now_dt - onset_dt).total_seconds()
    elapsed_minutes = max(elapsed_seconds / 60.0, 0.0)

    decay_factor = 0.5 ** (elapsed_minutes / half_life_minutes)
    return value * decay_factor
```

**Step 5: Run tests and verify they pass**

```bash
cd /Users/jasonljc/trading && PYTHONPATH=market_intel:$PYTHONPATH python3 -m pytest market_intel/tests/test_decay.py -v --tb=short
```

**Step 6: Commit**

```bash
cd /Users/jasonljc/trading && git add market_intel/ && git commit -m "feat: temporal decay for conviction factor values"
```

---

### Task 9: Pattern matcher

**Files:**
- Create: `market_intel/conviction/pattern_matcher.py`
- Create: `market_intel/tests/test_pattern_matcher.py`

**Step 1: Write the failing tests**

File: `market_intel/tests/test_pattern_matcher.py`

```python
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
```

**Step 2: Run tests to verify they fail**

```bash
cd /Users/jasonljc/trading && PYTHONPATH=market_intel:$PYTHONPATH python3 -m pytest market_intel/tests/test_pattern_matcher.py -v --tb=short
```

Expected: ModuleNotFoundError

**Step 3: Implement pattern_matcher.py**

File: `market_intel/conviction/pattern_matcher.py`

```python
"""Pattern matcher: evaluates named conditional patterns against analytics data.

Uses a simple condition parser (no eval()) to check each condition.
All conditions in a pattern must be true for a match.
Returns the FIRST matching pattern (ordered by priority in config).

Pure functions — no IB or Redis dependency.
"""
from __future__ import annotations

import re
from typing import Any

# Supported operators
_OPERATORS = {
    ">=": lambda a, b: a >= b,
    "<=": lambda a, b: a <= b,
    ">": lambda a, b: a > b,
    "<": lambda a, b: a < b,
    "==": lambda a, b: a == b,
}

# Regex: lhs  operator  rhs
# Operator must be matched longest-first (>= before >)
_CONDITION_RE = re.compile(
    r"^\s*(\S+)\s*(>=|<=|>|<|==)\s*(\S+)\s*$"
)


def match_pattern(analytics: dict, patterns_config: list[dict]) -> dict | None:
    """Find the first pattern whose conditions are all satisfied by analytics.

    Args:
        analytics: Dict of current analytics values (e.g., {"gex": -30, "velocity_5m": 55}).
        patterns_config: List of pattern dicts, each with:
            - name: str
            - direction: "LONG" | "SHORT" | "NEUTRAL" | "BOTH"
            - base_score: int (0-100)
            - confidence: "HIGH" | "MEDIUM" | "LOW"
            - conditions: list[str] — e.g., ["gex < 0", "velocity_15m > velocity_5m"]

    Returns:
        {"name": str, "direction": str, "base_score": int, "confidence": str} or None
    """
    for pattern in patterns_config:
        conditions = pattern.get("conditions", [])
        if all(_evaluate_condition(cond, analytics) for cond in conditions):
            return {
                "name": pattern["name"],
                "direction": pattern["direction"],
                "base_score": pattern["base_score"],
                "confidence": pattern["confidence"],
            }
    return None


def _evaluate_condition(condition: str, analytics: dict) -> bool:
    """Evaluate a single condition string against analytics.

    Supports:
      - "field > 50"            (compare field to literal number)
      - "field >= other_field"  (compare two analytics fields)
      - "field == 1"            (equality with number)

    Returns False if a referenced field is missing from analytics.
    """
    match = _CONDITION_RE.match(condition)
    if not match:
        return False

    lhs_key, op, rhs_token = match.groups()

    # Resolve left-hand side — must be an analytics key
    if lhs_key not in analytics:
        return False
    lhs_val = analytics[lhs_key]

    # Resolve right-hand side — either a literal number or another analytics key
    rhs_val = _resolve_value(rhs_token, analytics)
    if rhs_val is None:
        return False

    return _OPERATORS[op](lhs_val, rhs_val)


def _resolve_value(token: str, analytics: dict) -> float | None:
    """Resolve a token to a numeric value: literal number or analytics key lookup."""
    # Try parsing as a number first
    try:
        return float(token)
    except ValueError:
        pass

    # Try as an analytics key
    if token in analytics:
        val = analytics[token]
        if isinstance(val, (int, float)):
            return float(val)

    return None
```

**Step 4: Run tests and verify they pass**

```bash
cd /Users/jasonljc/trading && PYTHONPATH=market_intel:$PYTHONPATH python3 -m pytest market_intel/tests/test_pattern_matcher.py -v --tb=short
```

**Step 5: Commit**

```bash
cd /Users/jasonljc/trading && git add market_intel/ && git commit -m "feat: pattern matcher with condition parser for conviction patterns"
```

---

### Task 10: Conviction scorer (weighted fallback + TOD + clarity)

**Files:**
- Create: `market_intel/conviction/scorer.py`
- Create: `market_intel/tests/test_scorer.py`

**Step 1: Write the failing tests**

File: `market_intel/tests/test_scorer.py`

```python
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
```

**Step 2: Run tests to verify they fail**

```bash
cd /Users/jasonljc/trading && PYTHONPATH=market_intel:$PYTHONPATH python3 -m pytest market_intel/tests/test_scorer.py -v --tb=short
```

Expected: ModuleNotFoundError

**Step 3: Implement scorer.py**

File: `market_intel/conviction/scorer.py`

```python
"""Conviction scorer: pattern match → weighted fallback → TOD → clarity.

Produces per-instrument directional conviction scores.
Pure functions — no IB or Redis dependency.
"""
from __future__ import annotations

from datetime import datetime, timezone

from market_intel.analytics.volume_profile import get_tod_quality
from market_intel.analytics.regime_transition import detect_regime_transition
from market_intel.conviction.pattern_matcher import match_pattern


# Factor names used in weighted fallback (must match keys in weights config and analytics dict)
_FACTOR_NAMES = [
    "velocity_alignment",
    "divergence_score",
    "gex_tailwind",
    "options_flow",
    "signal_integration",
    "relative_volume",
]


def compute_conviction(
    analytics: dict,
    regime: str,
    hour: int,
    minute: int,
    patterns_config: list[dict],
    weights_config: dict,
) -> dict:
    """Compute directional conviction scores for an instrument.

    Logic:
    1. Try pattern matcher. If match -> use pattern's base_score and direction.
    2. If no match -> weighted fallback using regime-specific weights.
    3. Apply time-of-day modifier.
    4. Compute clarity from factor agreement.
    5. Compute long_conviction, short_conviction, hold_conviction.

    Args:
        analytics: Dict of current analytics values.
        regime: Current regime type ("TRENDING", "VOLATILE", "NEUTRAL").
        hour: Current hour (ET).
        minute: Current minute.
        patterns_config: List of pattern dicts for pattern_matcher.
        weights_config: Dict of regime -> factor weights.

    Returns:
        Conviction output dict per design doc Section 4.5.
    """
    tod_modifier = get_tod_quality(hour, minute)
    now_iso = datetime.now(timezone.utc).isoformat()

    # Step 1: Try pattern match
    matched = match_pattern(analytics, patterns_config)

    if matched is not None:
        long_raw, short_raw = _scores_from_pattern(matched)
        clarity = matched["confidence"]
        top_factors = [f"pattern:{matched['name']}"]
        opposing_factors: list[str] = []
    else:
        # Step 2: Weighted fallback
        regime_weights = weights_config.get(regime, weights_config.get("NEUTRAL", {}))
        long_raw, short_raw, top_factors, opposing_factors = _weighted_fallback(
            analytics, regime_weights
        )
        clarity = _compute_clarity(analytics, _FACTOR_NAMES)

    # Step 3: Apply TOD modifier
    long_score = int(max(0, min(100, long_raw * tod_modifier)))
    short_score = int(max(0, min(100, short_raw * tod_modifier)))

    # Step 5: Hold conviction = average, biased toward the dominant direction
    if long_score >= short_score:
        hold_score = int((long_score * 0.7 + short_score * 0.3))
    else:
        hold_score = int((short_score * 0.7 + long_score * 0.3))
    hold_score = max(0, min(100, hold_score))

    # Regime transition info
    regime_history = analytics.get("regime_history", [])
    if isinstance(regime_history, list) and len(regime_history) >= 3:
        regime_transition = detect_regime_transition(regime_history)
    else:
        regime_transition = {"detected": False, "from_regime": None, "to_regime": None, "confidence": 0.0}

    return {
        "long_conviction": long_score,
        "short_conviction": short_score,
        "hold_conviction": hold_score,
        "clarity": clarity,
        "matched_pattern": matched["name"] if matched else None,
        "regime_transition": regime_transition,
        "top_factors": top_factors,
        "opposing_factors": opposing_factors,
        "relative_volume": analytics.get("relative_volume", 0.0),
        "timestamp": now_iso,
    }


def _scores_from_pattern(matched: dict) -> tuple[float, float]:
    """Convert a matched pattern to long/short raw scores."""
    score = matched["base_score"]
    direction = matched["direction"]

    if direction == "LONG":
        return float(score), float(max(0, 100 - score))
    elif direction == "SHORT":
        return float(max(0, 100 - score)), float(score)
    else:
        # NEUTRAL or BOTH — equal low conviction both ways
        return float(score), float(score)


def _weighted_fallback(
    analytics: dict, regime_weights: dict
) -> tuple[float, float, list[str], list[str]]:
    """Compute conviction from weighted factor sum.

    Each factor value in analytics is expected to be a float:
      - Positive values indicate LONG bias
      - Negative values indicate SHORT bias
      - Magnitude indicates strength (0-100 scale)

    Returns:
        (long_raw, short_raw, top_factors, opposing_factors)
    """
    long_sum = 0.0
    short_sum = 0.0
    top_factors: list[str] = []
    opposing_factors: list[str] = []

    for factor_name in _FACTOR_NAMES:
        weight = regime_weights.get(factor_name, 0.0)
        value = analytics.get(factor_name, 0.0)

        if not isinstance(value, (int, float)):
            continue

        weighted = abs(value) * weight

        if value > 0:
            long_sum += weighted
            if abs(value) > 20:
                top_factors.append(f"{factor_name}_long")
        elif value < 0:
            short_sum += weighted
            if abs(value) > 20:
                top_factors.append(f"{factor_name}_short")

    return long_sum, short_sum, top_factors, opposing_factors


def _compute_clarity(analytics: dict, factor_names: list[str]) -> str:
    """Compute clarity based on factor agreement.

    HIGH: >70% of factors agree on direction
    MEDIUM: 50-70% agreement
    LOW: <50% agreement
    """
    positive = 0
    negative = 0
    total = 0

    for name in factor_names:
        val = analytics.get(name, 0.0)
        if not isinstance(val, (int, float)):
            continue
        if val == 0.0:
            continue
        total += 1
        if val > 0:
            positive += 1
        else:
            negative += 1

    if total == 0:
        return "LOW"

    dominant = max(positive, negative)
    agreement = dominant / total

    if agreement > 0.70:
        return "HIGH"
    elif agreement >= 0.50:
        return "MEDIUM"
    else:
        return "LOW"
```

**Step 4: Run tests and verify they pass**

```bash
cd /Users/jasonljc/trading && PYTHONPATH=market_intel:$PYTHONPATH python3 -m pytest market_intel/tests/test_scorer.py -v --tb=short
```

**Step 5: Run ALL tests from Tasks 6-10 together**

```bash
cd /Users/jasonljc/trading && PYTHONPATH=market_intel:$PYTHONPATH python3 -m pytest market_intel/tests/test_microstructure.py market_intel/tests/test_volume_profile.py market_intel/tests/test_regime_transition.py market_intel/tests/test_signal_integrator.py market_intel/tests/test_decay.py market_intel/tests/test_pattern_matcher.py market_intel/tests/test_scorer.py -v --tb=short
```

**Step 6: Commit**

```bash
cd /Users/jasonljc/trading && git add market_intel/ && git commit -m "feat: conviction scorer with pattern matching, weighted fallback, TOD modifier, and clarity"
```
# Market Intel (Prism) Implementation Plan — Tasks 11-15

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Wire up the Prism conviction output to the rest of the trading system: bridge for consumers, feedback loop for outcome tracking, main daemon orchestrator, Brain/Sentinel integration, and Dashboard/Telegram integration.

**Test command:** `cd /Users/jasonljc/trading && python -m pytest market_intel/tests/ tests/ dashboard/api/tests/ -v`

---

### Task 11: Market intel bridge

**Files:**
- Create: `market_intel/market_intel_bridge.py`
- Create: `market_intel/tests/test_bridge.py`

**Step 1: Write `market_intel/market_intel_bridge.py`**

Follow the exact pattern from `openclaw_trader/signals/sentinel_bridge.py`. Single function, graceful degradation, try/except everything.

```python
# market_intel/market_intel_bridge.py
"""Bridge between Redis conviction data and Brain/Sentinel consumers."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# Conviction → sizing modifier mapping
_SIZING_MAP = [
    (70, 1.0),    # >70 → full size
    (50, 0.75),   # 50-70 → reduced
    (30, 0.5),    # 30-50 → half
    (0, 0.25),    # <30 → quarter
]

# Data older than this many seconds is considered stale
_STALE_THRESHOLD_S = 120  # 2 minutes (quotes polled every 5-10s, conviction every 10s)


def _default_result() -> dict[str, Any]:
    return {
        "has_data": False,
        "conviction": None,
        "hold_conviction": None,
        "clarity": None,
        "matched_pattern": None,
        "regime_transition": {},
        "sizing_modifier": 1.0,
        "factors": [],
        "timestamp": None,
    }


def _conviction_to_sizing(conviction: int, clarity: str | None) -> float:
    """Map conviction score to sizing modifier. LOW clarity blocks entry."""
    if clarity == "LOW":
        return 0.0
    for threshold, modifier in _SIZING_MAP:
        if conviction > threshold:
            return modifier
    return 0.25


def get_conviction(
    symbol: str,
    direction: str = "LONG",
    redis_client: Any | None = None,
) -> dict[str, Any]:
    """Return conviction data for the given instrument and direction.

    Reads from Redis key ``market_intel:conviction:{symbol}``.
    Returns a safe default when Redis is unavailable or data is missing/stale.
    """
    result = _default_result()

    if redis_client is None:
        return result

    try:
        raw = redis_client.get(f"market_intel:conviction:{symbol}")
        if raw is None:
            return result

        data = json.loads(raw)

        # Staleness check
        ts_str = data.get("timestamp")
        if ts_str:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            age_s = (datetime.now(timezone.utc) - ts).total_seconds()
            if age_s > _STALE_THRESHOLD_S:
                logger.debug("market_intel stale for %s (%.0fs old)", symbol, age_s)
                return result

        # Direction-specific conviction
        dir_key = "long_conviction" if direction.upper() == "LONG" else "short_conviction"
        conviction = data.get(dir_key)
        if conviction is None:
            return result

        clarity = data.get("clarity")
        sizing_mod = _conviction_to_sizing(conviction, clarity)

        result.update({
            "has_data": True,
            "conviction": conviction,
            "hold_conviction": data.get("hold_conviction"),
            "clarity": clarity,
            "matched_pattern": data.get("matched_pattern"),
            "regime_transition": data.get("regime_transition", {}),
            "sizing_modifier": sizing_mod,
            "factors": data.get("top_factors", []),
            "timestamp": ts_str,
        })

    except Exception as exc:
        logger.warning("market_intel bridge error for %s: %s", symbol, exc)
        return _default_result()

    return result
```

**Step 2: Write tests**

```python
# market_intel/tests/test_bridge.py
"""Tests for market_intel_bridge — conviction bridge for Brain/Sentinel."""
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Ensure market_intel is importable
_MI_ROOT = Path(__file__).parent.parent
if str(_MI_ROOT) not in sys.path:
    sys.path.insert(0, str(_MI_ROOT))

from market_intel_bridge import get_conviction, _STALE_THRESHOLD_S


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
```

**Step 3: Run tests and commit**

```bash
cd /Users/jasonljc/trading && python -m pytest market_intel/tests/test_bridge.py -v
git add market_intel/market_intel_bridge.py market_intel/tests/test_bridge.py
git commit -m "feat(prism): market intel bridge with conviction-to-sizing mapping"
```

---

### Task 12: Feedback loop

**Files:**
- Create: `market_intel/feedback.py`
- Create: `market_intel/tests/test_feedback.py`

**Step 1: Write `market_intel/feedback.py`**

```python
# market_intel/feedback.py
"""Conviction feedback loop — log snapshots at entry, link to trade outcomes."""
from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _default_ledger_path() -> Path:
    return Path(os.environ.get("OPENCLAW_DATA", _REPO_ROOT / "data")) / "ledger.jsonl"


def _next_seq(ledger_path: Path) -> int:
    """Return next ledger sequence number."""
    seq = 0
    if ledger_path.exists():
        with open(ledger_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    seq = max(seq, entry.get("ledger_seq", 0))
                except json.JSONDecodeError:
                    continue
    return seq + 1


def log_conviction_at_entry(
    position_id: str,
    symbol: str,
    conviction_data: dict,
    ledger_path: Path | None = None,
) -> None:
    """Append a CONVICTION_SNAPSHOT event to the ledger JSONL file.

    Parameters
    ----------
    position_id : str
        The position ID to link this snapshot to.
    symbol : str
        Instrument symbol (ES, NQ, etc.).
    conviction_data : dict
        Full conviction dict from ``get_conviction()``.
    ledger_path : Path, optional
        Override ledger file location (default: ``$OPENCLAW_DATA/ledger.jsonl``).
    """
    path = ledger_path or _default_ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    event = {
        "ledger_seq": _next_seq(path),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_type": "CONVICTION_SNAPSHOT",
        "run_id": str(uuid.uuid4())[:8],
        "ref_id": position_id,
        "payload": {
            "symbol": symbol,
            **conviction_data,
        },
    }

    with open(path, "a") as f:
        f.write(json.dumps(event) + "\n")


def link_outcome(
    position_id: str,
    realized_pnl: float,
    ledger_path: Path | None = None,
) -> dict | None:
    """Find the CONVICTION_SNAPSHOT for a position and return combined data.

    Parameters
    ----------
    position_id : str
        The position ID to search for.
    realized_pnl : float
        The realized PnL of the closed position.
    ledger_path : Path, optional
        Override ledger file location.

    Returns
    -------
    dict or None
        ``{"conviction_at_entry": int, "pattern": str|None, "realized_pnl": float}``
        or ``None`` if no snapshot found.
    """
    path = ledger_path or _default_ledger_path()
    if not path.exists():
        return None

    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if (
                entry.get("event_type") == "CONVICTION_SNAPSHOT"
                and entry.get("ref_id") == position_id
            ):
                payload = entry.get("payload", {})
                return {
                    "conviction_at_entry": payload.get("conviction"),
                    "pattern": payload.get("matched_pattern"),
                    "realized_pnl": realized_pnl,
                }

    return None
```

**Step 2: Write tests**

```python
# market_intel/tests/test_feedback.py
"""Tests for feedback loop — conviction snapshots and outcome linking."""
import json
import sys
from pathlib import Path

import pytest

_MI_ROOT = Path(__file__).parent.parent
if str(_MI_ROOT) not in sys.path:
    sys.path.insert(0, str(_MI_ROOT))

from feedback import log_conviction_at_entry, link_outcome


@pytest.fixture
def ledger_file(tmp_path):
    return tmp_path / "ledger.jsonl"


def _sample_conviction(**overrides):
    base = {
        "has_data": True,
        "conviction": 75,
        "hold_conviction": 70,
        "clarity": "HIGH",
        "matched_pattern": "TREND_ACCELERATION",
        "regime_transition": {"detected": False},
        "sizing_modifier": 1.0,
        "factors": ["velocity_15m_bullish"],
        "timestamp": "2026-03-17T10:30:00+00:00",
    }
    base.update(overrides)
    return base


class TestLogConvictionSnapshot:
    def test_log_conviction_snapshot(self, ledger_file):
        log_conviction_at_entry("POS_001", "ES", _sample_conviction(), ledger_path=ledger_file)
        assert ledger_file.exists()
        lines = [json.loads(l) for l in ledger_file.read_text().strip().split("\n")]
        assert len(lines) == 1
        assert lines[0]["event_type"] == "CONVICTION_SNAPSHOT"
        assert lines[0]["ref_id"] == "POS_001"

    def test_snapshot_has_required_fields(self, ledger_file):
        log_conviction_at_entry("POS_002", "NQ", _sample_conviction(), ledger_path=ledger_file)
        entry = json.loads(ledger_file.read_text().strip())
        assert "ledger_seq" in entry
        assert "timestamp" in entry
        assert entry["payload"]["symbol"] == "NQ"
        assert entry["payload"]["conviction"] == 75
        assert entry["payload"]["matched_pattern"] == "TREND_ACCELERATION"

    def test_log_to_custom_path(self, tmp_path):
        custom = tmp_path / "subdir" / "custom_ledger.jsonl"
        log_conviction_at_entry("POS_003", "CL", _sample_conviction(), ledger_path=custom)
        assert custom.exists()
        entry = json.loads(custom.read_text().strip())
        assert entry["ref_id"] == "POS_003"


class TestLinkOutcome:
    def test_link_outcome_found(self, ledger_file):
        log_conviction_at_entry("POS_010", "ES", _sample_conviction(conviction=82, matched_pattern="REGIME_FLIP"), ledger_path=ledger_file)
        result = link_outcome("POS_010", realized_pnl=500.0, ledger_path=ledger_file)
        assert result is not None
        assert result["conviction_at_entry"] == 82
        assert result["pattern"] == "REGIME_FLIP"
        assert result["realized_pnl"] == 500.0

    def test_link_outcome_not_found(self, ledger_file):
        log_conviction_at_entry("POS_010", "ES", _sample_conviction(), ledger_path=ledger_file)
        result = link_outcome("POS_999", realized_pnl=100.0, ledger_path=ledger_file)
        assert result is None

    def test_multiple_snapshots(self, ledger_file):
        log_conviction_at_entry("POS_A", "ES", _sample_conviction(conviction=60), ledger_path=ledger_file)
        log_conviction_at_entry("POS_B", "NQ", _sample_conviction(conviction=85, matched_pattern="BREAKOUT_IMMINENT"), ledger_path=ledger_file)
        log_conviction_at_entry("POS_C", "CL", _sample_conviction(conviction=40), ledger_path=ledger_file)
        result = link_outcome("POS_B", realized_pnl=-200.0, ledger_path=ledger_file)
        assert result is not None
        assert result["conviction_at_entry"] == 85
        assert result["pattern"] == "BREAKOUT_IMMINENT"
        assert result["realized_pnl"] == -200.0
```

**Step 3: Run tests and commit**

```bash
cd /Users/jasonljc/trading && python -m pytest market_intel/tests/test_feedback.py -v
git add market_intel/feedback.py market_intel/tests/test_feedback.py
git commit -m "feat(prism): feedback loop — conviction snapshots and outcome linking"
```

---

### Task 13: Main daemon (prism.py)

**Files:**
- Create: `market_intel/prism.py`
- Create: `market_intel/tests/test_prism.py`

**Step 1: Write `market_intel/prism.py`**

```python
# market_intel/prism.py
"""Prism — Market Intel daemon. Polls IB, computes analytics, publishes conviction to Redis."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_MI_ROOT = Path(__file__).parent
if str(_MI_ROOT) not in sys.path:
    sys.path.insert(0, str(_MI_ROOT))

# Optional imports — daemon degrades gracefully
try:
    import redis as _redis_mod
    _HAS_REDIS = True
except ImportError:
    _HAS_REDIS = False

try:
    from ib_insync import IB
    _HAS_IB = True
except ImportError:
    _HAS_IB = False

# Analytics engines (imported lazily in _run_analytics_cycle)
_ANALYTICS_ENGINES: list | None = None

# Symbols for options rotation
_OPTIONS_SYMBOLS = ["ES", "NQ", "CL"]
_CORE_SYMBOLS = ["ES", "NQ", "CL", "GC", "ZB"]


class PrismDaemon:
    """Market intel daemon orchestrator.

    Connects to IB Gateway and Redis, runs polling loops for quotes,
    cross-market data, and options chains, computes analytics, scores
    conviction, and publishes results to Redis.
    """

    def __init__(
        self,
        ib_host: str = "127.0.0.1",
        ib_port: int = 4002,
        ib_client_id: int = 10,
        redis_url: str = "redis://localhost:6379",
    ):
        self.ib_host = ib_host
        self.ib_port = ib_port
        self.ib_client_id = ib_client_id
        self.redis_url = redis_url

        self._ib: Any = None
        self._rc: Any = None
        self._dm: Any = None  # IBDataManager instance
        self._running = False
        self._options_index = 0  # rotation index for options subscriptions
        self._ib_connected = False

    async def start(self) -> None:
        """Connect IB + Redis and start all polling loops."""
        self._running = True

        # Connect Redis
        if _HAS_REDIS:
            try:
                self._rc = _redis_mod.from_url(self.redis_url, decode_responses=True)
                self._rc.ping()
                logger.info("Redis connected: %s", self.redis_url)
            except Exception as exc:
                logger.warning("Redis connection failed: %s — continuing without publish", exc)
                self._rc = None

        # Connect IB
        if _HAS_IB:
            try:
                self._ib = IB()
                await self._ib.connectAsync(self.ib_host, self.ib_port, clientId=self.ib_client_id)
                self._ib_connected = True
                self._ib.disconnectedEvent += self._on_ib_disconnect
                logger.info("IB connected: %s:%d (client %d)", self.ib_host, self.ib_port, self.ib_client_id)
            except Exception as exc:
                logger.warning("IB connection failed: %s — running with stale data", exc)
                self._ib = None
                self._ib_connected = False

        # Create data manager
        try:
            from data_layer import IBDataManager
            self._dm = IBDataManager(ib=self._ib, redis_client=self._rc)
            logger.info("IBDataManager initialised")
        except ImportError:
            logger.warning("data_layer not importable — no polling")

        # Start polling tasks
        tasks = [
            asyncio.create_task(self._run_quote_poller(), name="quote_poller"),
            asyncio.create_task(self._run_cross_poller(), name="cross_poller"),
            asyncio.create_task(self._run_options_poller(), name="options_poller"),
            asyncio.create_task(self._run_analytics_cycle(), name="analytics"),
            asyncio.create_task(self._run_conviction_cycle(), name="conviction"),
        ]

        logger.info("Prism daemon started — %d polling tasks", len(tasks))
        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            logger.info("Prism daemon tasks cancelled")

    async def stop(self) -> None:
        """Disconnect IB and clean up."""
        self._running = False
        if self._ib and self._ib_connected:
            try:
                self._ib.disconnect()
                logger.info("IB disconnected")
            except Exception:
                pass
        self._ib = None
        self._ib_connected = False
        self._rc = None
        logger.info("Prism daemon stopped")

    def _on_ib_disconnect(self) -> None:
        """Handle unexpected IB disconnection."""
        logger.warning("IB disconnected unexpectedly — data will be marked stale")
        self._ib_connected = False

    async def _run_quote_poller(self) -> None:
        """Poll core futures quotes every 5 seconds."""
        while self._running:
            try:
                if self._ib_connected and self._ib:
                    await self._poll_quotes()
            except Exception as exc:
                logger.error("Quote poll error: %s", exc)
            await asyncio.sleep(5)

    async def _run_cross_poller(self) -> None:
        """Poll cross-market data every 10 seconds."""
        while self._running:
            try:
                if self._ib_connected and self._ib:
                    await self._poll_cross_market()
            except Exception as exc:
                logger.error("Cross-market poll error: %s", exc)
            await asyncio.sleep(10)

    async def _run_options_poller(self) -> None:
        """Poll options chains every 60 seconds, rotating symbols."""
        while self._running:
            try:
                if self._ib_connected and self._ib:
                    sym = _OPTIONS_SYMBOLS[self._options_index % len(_OPTIONS_SYMBOLS)]
                    await self._poll_options(sym)
                    self._options_index += 1
            except Exception as exc:
                logger.error("Options poll error: %s", exc)
            await asyncio.sleep(60)

    async def _run_analytics_cycle(self) -> None:
        """Run all analytics engines every 10 seconds."""
        while self._running:
            try:
                await self._compute_analytics()
            except Exception as exc:
                logger.error("Analytics cycle error: %s", exc)
            await asyncio.sleep(10)

    async def _run_conviction_cycle(self) -> None:
        """Run conviction scorer every 10 seconds (after analytics)."""
        # Initial delay to let analytics populate first
        await asyncio.sleep(2)
        while self._running:
            try:
                await self._compute_conviction()
            except Exception as exc:
                logger.error("Conviction cycle error: %s", exc)
            await asyncio.sleep(10)

    async def _poll_quotes(self) -> None:
        """Poll quotes for core futures via IBDataManager."""
        if not self._dm:
            return
        # IBDataManager.poll_quotes handles IB calls + Redis caching internally
        self._dm.poll_quotes(_CORE_SYMBOLS)

    async def _poll_cross_market(self) -> None:
        """Poll cross-market symbols via IBDataManager."""
        if not self._dm:
            return
        self._dm.poll_cross_market(["VIX", "DXY", "TNX", "HYG", "XLF"])

    async def _poll_options(self, symbol: str) -> None:
        """Poll options chain for a single symbol via IBDataManager."""
        if not self._dm:
            return
        self._dm.poll_options(symbol)

    async def _compute_analytics(self) -> None:
        """Run all analytics engines and publish results to Redis."""
        try:
            from analytics.velocity import compute_velocity
            from analytics.divergence import compute_divergences
            from analytics.volume_profile import compute_volume_profile
        except ImportError:
            return

        for sym in _CORE_SYMBOLS:
            analytics = {}
            try:
                if self._rc:
                    raw = self._rc.get(f"market_intel:quotes:{sym}")
                    if raw:
                        analytics["velocity"] = compute_velocity(json.loads(raw), sym)
            except Exception:
                pass
            try:
                if self._rc:
                    analytics["divergences"] = compute_divergences(sym, self._rc)
            except Exception:
                pass
            try:
                if self._rc:
                    analytics["volume_profile"] = compute_volume_profile(sym, self._rc)
            except Exception:
                pass

            if self._rc and analytics:
                self._rc.set(
                    f"market_intel:analytics:{sym}",
                    json.dumps(analytics),
                    ex=30,
                )

    async def _compute_conviction(self) -> None:
        """Run conviction scorer for all symbols and publish to Redis."""
        try:
            from conviction.scorer import compute_conviction
        except ImportError:
            return

        for sym in _CORE_SYMBOLS:
            try:
                analytics_raw = self._rc.get(f"market_intel:analytics:{sym}") if self._rc else None
                analytics = json.loads(analytics_raw) if analytics_raw else {}
                conviction = compute_conviction(sym, analytics)
                if self._rc and conviction:
                    self._rc.set(
                        f"market_intel:conviction:{sym}",
                        json.dumps(conviction),
                        ex=30,
                    )
            except Exception as exc:
                logger.debug("Conviction compute failed for %s: %s", sym, exc)

    async def _poll_cycle(self) -> None:
        """Run one full cycle: poll data, compute analytics, compute conviction.

        Primarily used for testing.
        """
        if self._ib_connected and self._ib:
            await self._poll_quotes()
            await self._poll_cross_market()
        await self._compute_analytics()
        await self._compute_conviction()


def main() -> None:
    """Entry point — reads config from env vars and runs the daemon."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    ib_host = os.environ.get("IB_HOST", "127.0.0.1")
    ib_port = int(os.environ.get("IB_PORT", "4002"))
    ib_client_id = int(os.environ.get("IB_CLIENT_ID", "10"))
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")

    daemon = PrismDaemon(
        ib_host=ib_host,
        ib_port=ib_port,
        ib_client_id=ib_client_id,
        redis_url=redis_url,
    )

    loop = asyncio.new_event_loop()

    def _shutdown(sig, frame):
        logger.info("Received signal %s — shutting down", sig)
        loop.create_task(daemon.stop())

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    try:
        loop.run_until_complete(daemon.start())
    except KeyboardInterrupt:
        loop.run_until_complete(daemon.stop())
    finally:
        loop.close()


if __name__ == "__main__":
    main()
```

**Step 2: Write tests**

```python
# market_intel/tests/test_prism.py
"""Tests for PrismDaemon — main orchestrator."""
import asyncio
import json
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_MI_ROOT = Path(__file__).parent.parent
if str(_MI_ROOT) not in sys.path:
    sys.path.insert(0, str(_MI_ROOT))

from prism import PrismDaemon, _OPTIONS_SYMBOLS


class TestDaemonCreation:
    def test_daemon_creates(self):
        d = PrismDaemon()
        assert d.ib_host == "127.0.0.1"
        assert d.ib_port == 4002
        assert d.ib_client_id == 10
        assert d.redis_url == "redis://localhost:6379"
        assert d._running is False

    def test_env_var_config(self):
        env = {
            "IB_HOST": "10.0.0.5",
            "IB_PORT": "7497",
            "IB_CLIENT_ID": "20",
            "REDIS_URL": "redis://redis-host:6380",
        }
        with patch.dict(os.environ, env):
            d = PrismDaemon(
                ib_host=os.environ["IB_HOST"],
                ib_port=int(os.environ["IB_PORT"]),
                ib_client_id=int(os.environ["IB_CLIENT_ID"]),
                redis_url=os.environ["REDIS_URL"],
            )
            assert d.ib_host == "10.0.0.5"
            assert d.ib_port == 7497
            assert d.ib_client_id == 20
            assert d.redis_url == "redis://redis-host:6380"


class TestPollCycle:
    @pytest.mark.asyncio
    async def test_poll_cycle_computes(self):
        """Mock IB data flows through analytics and conviction, published to Redis."""
        d = PrismDaemon()
        d._running = True
        d._ib_connected = False  # Skip IB polling
        d._rc = MagicMock()
        d._rc.get.return_value = None  # No cached data yet

        # _poll_cycle should not raise even with no data
        await d._poll_cycle()

        # Verify it attempted to read analytics from Redis
        assert d._rc.get.called

    @pytest.mark.asyncio
    async def test_graceful_ib_disconnect(self):
        """IB disconnect sets flag; daemon continues running."""
        d = PrismDaemon()
        d._running = True
        d._ib_connected = True
        d._ib = MagicMock()

        # Simulate disconnect event
        d._on_ib_disconnect()

        assert d._ib_connected is False
        assert d._running is True  # Daemon still running

    @pytest.mark.asyncio
    async def test_options_rotation(self):
        """Options poller rotates through ES, NQ, CL."""
        d = PrismDaemon()
        symbols_polled = []

        for i in range(6):
            sym = _OPTIONS_SYMBOLS[d._options_index % len(_OPTIONS_SYMBOLS)]
            symbols_polled.append(sym)
            d._options_index += 1

        # Should cycle: ES, NQ, CL, ES, NQ, CL
        assert symbols_polled == ["ES", "NQ", "CL", "ES", "NQ", "CL"]


class TestShutdown:
    @pytest.mark.asyncio
    async def test_shutdown_clean(self):
        """stop() disconnects IB and clears state."""
        d = PrismDaemon()
        d._running = True
        d._ib_connected = True
        d._ib = MagicMock()
        d._rc = MagicMock()

        await d.stop()

        assert d._running is False
        assert d._ib_connected is False
        assert d._ib is None
        assert d._rc is None
        # IB disconnect was called
```

**Step 3: Run tests and commit**

```bash
cd /Users/jasonljc/trading && python -m pytest market_intel/tests/test_prism.py -v
git add market_intel/prism.py market_intel/tests/test_prism.py
git commit -m "feat(prism): main daemon orchestrator with polling loops and shutdown"
```

---

### Task 14: Brain + Sentinel integration

**Files:**
- Modify: `shared/contracts.py` — add `CONVICTION_SNAPSHOT` event type
- Modify: `workspace-c3po/brain.py`
- Modify: `workspace-sentinel/sentinel.py`
- Modify: `tests/test_brain.py` — add 3 new tests
- Modify: `tests/test_sentinel.py` — add 3 new tests

**Step 1: Add `CONVICTION_SNAPSHOT` event type to `shared/contracts.py`**

In the `EventType` class, after `POLYMARKET_SIGNAL` (line 51), add:

```python
    CONVICTION_SNAPSHOT       = "CONVICTION_SNAPSHOT"
```

This event type is used by `market_intel_bridge.py` (Task 12) to log conviction snapshots to the ledger.

**Step 2: Modify `workspace-c3po/brain.py` — add market intel to `_suggest_sizing()`**

At the top of `workspace-c3po/brain.py`, after the existing imports (~line 15), add the import guard:

```python
# Optional: Market Intel bridge for conviction-based sizing.
try:
    import redis as _redis_mod_intel
    from market_intel_bridge import get_conviction as _get_conviction
    _HAS_INTEL = True
except ImportError:
    _HAS_INTEL = False
```

In function `_suggest_sizing()`, after the `incub_mod` computation (line 239: `incub_mod = ...`), add:

```python
    # Market intel modifier (conviction-based sizing)
    market_intel_mod = 1.0
    if _HAS_INTEL:
        try:
            _rc = _redis_mod_intel.from_url(
                os.environ.get("REDIS_URL", "redis://localhost:6379"),
                decode_responses=True,
            )
            _sym = strategy.get("symbol", "ES")
            _dir = signal.get("direction", "LONG")
            _intel = _get_conviction(_sym, _dir, redis_client=_rc)
            if _intel["has_data"]:
                if _intel.get("clarity") == "LOW":
                    return None  # Anti-conviction: skip this signal
                market_intel_mod = _intel.get("sizing_modifier", 1.0)
        except Exception:
            pass  # Market intel unavailable — continue with normal sizing
```

Then update the `final_risk_usd` line (line 241) from:

```python
    final_risk_usd = base_risk_usd * regime_mod * health_mod * session_mod * incub_mod
```

to:

```python
    final_risk_usd = base_risk_usd * regime_mod * health_mod * session_mod * incub_mod * market_intel_mod
```

Also update the `risk_pct_after_health` in the return dict (line 267) from:

```python
        "risk_pct_after_health":   round(base_risk_pct * regime_mod * health_mod * session_mod * incub_mod, 4),
```

to:

```python
        "risk_pct_after_health":   round(base_risk_pct * regime_mod * health_mod * session_mod * incub_mod * market_intel_mod, 4),
```

**Step 3: Modify `workspace-sentinel/sentinel.py` — add market intel check in `evaluate_intent()`**

At the top of `workspace-sentinel/sentinel.py`, after the existing signal import guard (line 33: `_HAS_SIGNALS = False`), add:

```python
# Optional: Market Intel bridge for conviction-based sizing.
try:
    from market_intel_bridge import get_conviction as _get_market_conviction
    _HAS_INTEL = True
except ImportError:
    _HAS_INTEL = False
```

In function `evaluate_intent()`, after the external signals section (line 669: `pass  # Redis/signals unavailable`), add:

```python
    # --- Market intel conviction modifier ---
    _intel_mod = 1.0
    try:
        if _HAS_INTEL:
            _r_intel = locals().get("_r") or _redis_mod.from_url(
                os.environ.get("REDIS_URL", "redis://localhost:6379"),
                decode_responses=True,
            )
            _intel = _get_market_conviction(
                intent.get("symbol", "ES"),
                intent.get("side", "LONG"),
                redis_client=_r_intel,
            )
            if _intel["has_data"]:
                if _intel.get("clarity") == "LOW" and intent.get("intent_type") == C.IntentType.ENTRY:
                    approval_id = IDs.make_approval_id()
                    deny = _deny(intent, approval_id, run_id, "MARKET_INTEL_LOW_CLARITY", sp, posture=posture)
                    ledger.append(C.EventType.INTENT_DENIED, run_id, intent.get("intent_id", ""), deny)
                    return deny
                _intel_mod = _intel.get("sizing_modifier", 1.0)
    except Exception:
        pass  # Market intel unavailable — continue with normal rules
```

Then update the final sizing line (line 820) from:

```python
    final_risk_usd *= _signal_mod
```

to:

```python
    final_risk_usd *= _signal_mod * _intel_mod
```

**Step 4: Add 3 tests to `tests/test_brain.py`**

Append these tests at the end of the file, inside an existing or new test class:

```python
# ---------------------------------------------------------------------------
# Market Intel integration
# ---------------------------------------------------------------------------
class TestMarketIntelIntegration:
    """Tests for market intel conviction modifier in _suggest_sizing."""

    def test_market_intel_mod_applied(self, monkeypatch):
        """Mock bridge returns 0.75 → sizing reduced by 25%."""
        import workspace_c3po.brain as brain_mod

        monkeypatch.setattr(brain_mod, "_HAS_INTEL", True)
        mock_get = MagicMock(return_value={
            "has_data": True,
            "conviction": 60,
            "clarity": "MEDIUM",
            "sizing_modifier": 0.75,
        })
        monkeypatch.setattr(brain_mod, "_get_conviction", mock_get)
        mock_redis = MagicMock()
        mock_redis_cls = MagicMock(return_value=mock_redis)
        monkeypatch.setattr(brain_mod, "_redis_mod_intel", MagicMock(from_url=mock_redis_cls))

        # Build minimal inputs for _suggest_sizing
        strategy = _base_strategy()
        health = {"score": 100}
        regime = {"regime_type": "NEUTRAL", "score": 50}
        snap = _base_snap()
        signal = {"direction": "LONG", "stop_distance_pts": 10.0}
        result = brain_mod._suggest_sizing(strategy, health, regime, snap, signal, 100000.0)
        # With 0.75 modifier the final_risk_usd should be lower
        assert result is not None
        assert result["final_risk_usd"] > 0

    def test_low_clarity_skips_signal(self, monkeypatch):
        """Mock bridge clarity=LOW → _suggest_sizing returns None."""
        import workspace_c3po.brain as brain_mod

        monkeypatch.setattr(brain_mod, "_HAS_INTEL", True)
        mock_get = MagicMock(return_value={
            "has_data": True,
            "conviction": 90,
            "clarity": "LOW",
            "sizing_modifier": 0.0,
        })
        monkeypatch.setattr(brain_mod, "_get_conviction", mock_get)
        mock_redis_cls = MagicMock(return_value=MagicMock())
        monkeypatch.setattr(brain_mod, "_redis_mod_intel", MagicMock(from_url=mock_redis_cls))

        strategy = _base_strategy()
        health = {"score": 100}
        regime = {"regime_type": "NEUTRAL", "score": 50}
        snap = _base_snap()
        signal = {"direction": "LONG", "stop_distance_pts": 10.0}
        result = brain_mod._suggest_sizing(strategy, health, regime, snap, signal, 100000.0)
        assert result is None

    def test_no_intel_normal_sizing(self, monkeypatch):
        """_HAS_INTEL=False → sizing unchanged (market_intel_mod=1.0)."""
        import workspace_c3po.brain as brain_mod

        monkeypatch.setattr(brain_mod, "_HAS_INTEL", False)

        strategy = _base_strategy()
        health = {"score": 100}
        regime = {"regime_type": "NEUTRAL", "score": 50}
        snap = _base_snap()
        signal = {"direction": "LONG", "stop_distance_pts": 10.0}
        result = brain_mod._suggest_sizing(strategy, health, regime, snap, signal, 100000.0)
        assert result is not None
        assert result["final_risk_usd"] > 0
```

> **Note:** The test uses existing `_base_strategy()` and `_base_snap()` helper fixtures already defined in `tests/test_brain.py`. If those helpers use different names, adapt accordingly — check existing test helpers in the file.

**Step 5: Add 3 tests to `tests/test_sentinel.py`**

Append these tests at the end of the file:

```python
# ---------------------------------------------------------------------------
# Market Intel integration
# ---------------------------------------------------------------------------
class TestMarketIntelIntegration:
    """Tests for market intel conviction modifier in evaluate_intent."""

    def test_intel_sizing_modifier(self, monkeypatch, tmp_path):
        """Mock bridge returns conviction 60 → _intel_mod=0.75 applied to sizing."""
        import workspace_sentinel.sentinel as sentinel_mod

        monkeypatch.setattr(sentinel_mod, "_HAS_INTEL", True)
        mock_get = MagicMock(return_value={
            "has_data": True,
            "conviction": 60,
            "clarity": "MEDIUM",
            "sizing_modifier": 0.75,
        })
        monkeypatch.setattr(sentinel_mod, "_get_market_conviction", mock_get)

        intent = _entry_intent()
        portfolio = _base_portfolio()
        params = _base_params()
        snap = _base_snap()
        result = evaluate_intent(intent, portfolio, params, snap)
        # Should be approved (not denied) with reduced sizing
        assert result.get("decision") in ("APPROVE", "DENY")

    def test_intel_low_clarity_denies(self, monkeypatch, tmp_path):
        """Mock bridge clarity=LOW → DENY for ENTRY intents."""
        import workspace_sentinel.sentinel as sentinel_mod

        monkeypatch.setattr(sentinel_mod, "_HAS_INTEL", True)
        monkeypatch.setattr(sentinel_mod, "_HAS_SIGNALS", True)
        mock_redis_cls = MagicMock(return_value=MagicMock())
        monkeypatch.setattr(sentinel_mod, "_redis_mod", MagicMock(from_url=mock_redis_cls))
        mock_get = MagicMock(return_value={
            "has_data": True,
            "conviction": 90,
            "clarity": "LOW",
            "sizing_modifier": 0.0,
        })
        monkeypatch.setattr(sentinel_mod, "_get_market_conviction", mock_get)

        intent = _entry_intent()
        portfolio = _base_portfolio()
        params = _base_params()
        snap = _base_snap()
        result = evaluate_intent(intent, portfolio, params, snap)
        assert result["decision"] == "DENY"
        assert "MARKET_INTEL_LOW_CLARITY" in result.get("deny_reason", "")

    def test_intel_unavailable_continues(self, monkeypatch, tmp_path):
        """Exception in bridge → _intel_mod=1.0, trade proceeds normally."""
        import workspace_sentinel.sentinel as sentinel_mod

        monkeypatch.setattr(sentinel_mod, "_HAS_INTEL", True)
        monkeypatch.setattr(sentinel_mod, "_HAS_SIGNALS", True)
        mock_redis_cls = MagicMock(return_value=MagicMock())
        monkeypatch.setattr(sentinel_mod, "_redis_mod", MagicMock(from_url=mock_redis_cls))
        mock_get = MagicMock(side_effect=Exception("Redis down"))
        monkeypatch.setattr(sentinel_mod, "_get_market_conviction", mock_get)

        intent = _entry_intent()
        portfolio = _base_portfolio()
        params = _base_params()
        snap = _base_snap()
        result = evaluate_intent(intent, portfolio, params, snap)
        # Should proceed normally (APPROVE or rule-based DENY, not intel DENY)
        assert "MARKET_INTEL" not in result.get("deny_reason", "")
```

> **Note:** These tests use existing helpers (`_entry_intent()`, `_base_portfolio()`, `_base_params()`, `_base_snap()`) already defined in `tests/test_sentinel.py`. Adapt names to match actual helpers in the file.

**Step 6: Add `check_hold_conviction()` to `workspace-sentinel/sentinel.py`**

Add a standalone function to Sentinel that checks hold_conviction for existing positions and flags stop tightening or early exit. This is called from the cycle orchestrator during position management, not from `evaluate_intent()`.

After the `evaluate_intent()` function, add:

```python
def check_hold_conviction(position: dict, redis_client=None) -> dict:
    """Check if hold conviction warrants tightening stops or early exit.

    Called by the cycle orchestrator for each open position.
    - hold_conviction < 25 → tighten stop (move to 0.5x ATR from current price)
    - hold_conviction < 15 → flag for early exit
    """
    result = {"action": "HOLD", "tighten_stop": False, "flag_exit": False}
    if not _HAS_INTEL or redis_client is None:
        return result
    try:
        _intel = _get_market_conviction(
            position.get("symbol", "ES"),
            position.get("side", "LONG"),
            redis_client=redis_client,
        )
        if _intel["has_data"]:
            hold = _intel.get("hold_conviction")
            if hold is not None:
                if hold < 15:
                    result["action"] = "FLAG_EXIT"
                    result["flag_exit"] = True
                    result["tighten_stop"] = True
                elif hold < 25:
                    result["action"] = "TIGHTEN"
                    result["tighten_stop"] = True
    except Exception:
        pass
    return result
```

**Step 7: Add 3 tests for `check_hold_conviction()` to `tests/test_sentinel.py`**

Append after the `TestMarketIntelIntegration` class:

```python
class TestHoldConviction:
    """Tests for check_hold_conviction() position management."""

    def test_hold_above_25_no_action(self, monkeypatch):
        """hold_conviction >= 25 → HOLD, no tightening."""
        import workspace_sentinel.sentinel as sentinel_mod
        from workspace_sentinel.sentinel import check_hold_conviction

        monkeypatch.setattr(sentinel_mod, "_HAS_INTEL", True)
        mock_get = MagicMock(return_value={
            "has_data": True,
            "hold_conviction": 60,
            "conviction": 70,
            "clarity": "HIGH",
            "sizing_modifier": 1.0,
        })
        monkeypatch.setattr(sentinel_mod, "_get_market_conviction", mock_get)

        position = {"symbol": "ES", "side": "LONG"}
        result = check_hold_conviction(position, redis_client=MagicMock())
        assert result["action"] == "HOLD"
        assert result["tighten_stop"] is False
        assert result["flag_exit"] is False

    def test_hold_below_25_tighten(self, monkeypatch):
        """hold_conviction < 25 → TIGHTEN stop."""
        import workspace_sentinel.sentinel as sentinel_mod
        from workspace_sentinel.sentinel import check_hold_conviction

        monkeypatch.setattr(sentinel_mod, "_HAS_INTEL", True)
        mock_get = MagicMock(return_value={
            "has_data": True,
            "hold_conviction": 20,
            "conviction": 30,
            "clarity": "MEDIUM",
            "sizing_modifier": 0.5,
        })
        monkeypatch.setattr(sentinel_mod, "_get_market_conviction", mock_get)

        position = {"symbol": "NQ", "side": "SHORT"}
        result = check_hold_conviction(position, redis_client=MagicMock())
        assert result["action"] == "TIGHTEN"
        assert result["tighten_stop"] is True
        assert result["flag_exit"] is False

    def test_hold_below_15_flag_exit(self, monkeypatch):
        """hold_conviction < 15 → FLAG_EXIT with stop tightening."""
        import workspace_sentinel.sentinel as sentinel_mod
        from workspace_sentinel.sentinel import check_hold_conviction

        monkeypatch.setattr(sentinel_mod, "_HAS_INTEL", True)
        mock_get = MagicMock(return_value={
            "has_data": True,
            "hold_conviction": 10,
            "conviction": 15,
            "clarity": "LOW",
            "sizing_modifier": 0.0,
        })
        monkeypatch.setattr(sentinel_mod, "_get_market_conviction", mock_get)

        position = {"symbol": "CL", "side": "LONG"}
        result = check_hold_conviction(position, redis_client=MagicMock())
        assert result["action"] == "FLAG_EXIT"
        assert result["tighten_stop"] is True
        assert result["flag_exit"] is True
```

**Step 8: Run tests and commit**

```bash
cd /Users/jasonljc/trading && python -m pytest tests/test_brain.py tests/test_sentinel.py -v
git add shared/contracts.py workspace-c3po/brain.py workspace-sentinel/sentinel.py tests/test_brain.py tests/test_sentinel.py
git commit -m "feat(prism): integrate market intel bridge into Brain and Sentinel sizing"
```

---

### Task 15: Dashboard + Telegram integration

**Files:**
- Create: `dashboard/api/routers/market_intel.py`
- Modify: `dashboard/api/data_readers.py` — add `read_intel()`
- Modify: `dashboard/api/main.py` — register market_intel router
- Modify: `dashboard/api/telegram_bot.py` — add `format_intel()` + `/intel` command
- Modify: `dashboard/api/tests/test_routes.py` — add 1 test
- Modify: `dashboard/api/tests/test_telegram_bot.py` — add 1 test

**Step 1: Add `read_intel()` to `dashboard/api/data_readers.py`**

At the end of `dashboard/api/data_readers.py` (after `read_signals()`), add:

```python
def read_intel(redis_url: str = "") -> dict[str, dict]:
    """Read conviction data for all instruments from Redis."""
    url = redis_url or os.environ.get("REDIS_URL", "redis://localhost:6379")
    symbols = ["ES", "NQ", "CL", "GC", "ZB"]
    result = {}
    try:
        import redis
        rc = redis.from_url(url, decode_responses=True)
        for sym in symbols:
            raw = rc.get(f"market_intel:conviction:{sym}")
            if raw:
                try:
                    result[sym] = json.loads(raw)
                except json.JSONDecodeError:
                    continue
    except Exception:
        pass
    return result
```

**Step 2: Create `dashboard/api/routers/market_intel.py`**

```python
# dashboard/api/routers/market_intel.py
"""Market intel API endpoint."""
from __future__ import annotations

from fastapi import APIRouter

from dashboard.api.data_readers import read_intel

router = APIRouter()


@router.get("/api/intel")
def get_intel():
    """Return per-instrument conviction data from Prism daemon."""
    return read_intel()
```

**Step 3: Modify `dashboard/api/main.py` — register router**

After line 36 (`from dashboard.api.routers import portfolio, signals, alerts, trades, equity_curve, health, regime`), add `market_intel` to the import:

```python
from dashboard.api.routers import portfolio, signals, alerts, trades, equity_curve, health, regime, market_intel
```

After line 44 (`app.include_router(regime.router)`), add:

```python
app.include_router(market_intel.router)
```

**Step 4: Modify `dashboard/api/telegram_bot.py` — add `format_intel()` and `/intel` command**

Add `read_intel` to the import at the top (line 8):

```python
from dashboard.api.data_readers import (
    read_portfolio, read_alerts, read_trades, read_signals, read_health, read_regime, read_intel,
)
```

After `format_regime()` function (before `async def setup_telegram_bot`), add the `format_intel()` function:

```python
def format_intel() -> str:
    """Format market intel conviction data for Telegram."""
    try:
        intel = read_intel()
        if not intel:
            return "No market intel data available"
        lines = []
        for sym, data in sorted(intel.items()):
            long_c = data.get("long_conviction", "?")
            short_c = data.get("short_conviction", "?")
            clarity = data.get("clarity", "?")
            pattern = data.get("matched_pattern", "-")
            lines.append(f"{sym}: L:{long_c} S:{short_c} [{clarity}] {pattern or '-'}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error reading intel: {e}"
```

Inside `setup_telegram_bot()`, after `cmd_regime` handler (line 199), add the `/intel` command handler:

```python
        async def cmd_intel(update: Update, context: ContextTypes.DEFAULT_TYPE):
            await update.message.reply_text(format_intel())
```

After line 207 (`tg_app.add_handler(CommandHandler("regime", cmd_regime, filters=chat_filter))`), add:

```python
        tg_app.add_handler(CommandHandler("intel", cmd_intel, filters=chat_filter))
```

**Step 5: Add test to `dashboard/api/tests/test_routes.py`**

Append this test at the end of the file:

```python
class TestIntelRoute:
    def test_intel_route_returns_empty(self, client):
        """No Redis → empty dict, 200 OK."""
        resp = client.get("/api/intel")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)
```

> **Note:** Uses the existing `client` fixture (FastAPI TestClient) already defined in `test_routes.py`.

**Step 6: Add test to `dashboard/api/tests/test_telegram_bot.py`**

Append this test at the end of the file:

```python
class TestFormatIntel:
    def test_intel_format(self, monkeypatch):
        """format_intel() returns formatted string with conviction data."""
        from dashboard.api import telegram_bot

        mock_data = {
            "ES": {
                "long_conviction": 82,
                "short_conviction": 23,
                "clarity": "HIGH",
                "matched_pattern": "TREND_ACCELERATION",
            },
            "NQ": {
                "long_conviction": 55,
                "short_conviction": 45,
                "clarity": "MEDIUM",
                "matched_pattern": None,
            },
        }
        monkeypatch.setattr(telegram_bot, "read_intel", lambda: mock_data)

        result = telegram_bot.format_intel()
        assert "ES: L:82 S:23 [HIGH] TREND_ACCELERATION" in result
        assert "NQ: L:55 S:45 [MEDIUM] -" in result
```

**Step 7: Run tests and commit**

```bash
cd /Users/jasonljc/trading && python -m pytest dashboard/api/tests/ -v
git add dashboard/api/routers/market_intel.py dashboard/api/data_readers.py dashboard/api/main.py dashboard/api/telegram_bot.py dashboard/api/tests/
git commit -m "feat(prism): dashboard API /intel endpoint + Telegram /intel command"
```
