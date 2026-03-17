"""Data layer for Market Intel — IB polling and Redis caching."""

import json
import time
from typing import Optional
from datetime import datetime, timedelta


class IBDataManager:
    """Manages IB data polling and Redis caching with staleness detection."""

    def __init__(self, ib=None, redis_client=None):
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
        if not self.ib:
            return {}
        quotes = {}
        try:
            for symbol in symbols:
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
                            pass
        except Exception:
            return {}
        return quotes

    def poll_cross_market(self, symbols: list[str]) -> dict:
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
        if not self.ib:
            return {}
        try:
            chain_data = {
                "symbol": symbol,
                "strikes": [],
                "timestamp": datetime.utcnow().isoformat(),
            }
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
        if not self.ib:
            return {}
        dom_data = {}
        try:
            for symbol in symbols:
                dom = {
                    "symbol": symbol,
                    "bid_prices": [0.0] * 5,
                    "bid_sizes": [0] * 5,
                    "ask_prices": [0.0] * 5,
                    "ask_sizes": [0] * 5,
                    "timestamp": datetime.utcnow().isoformat(),
                }
                dom_data[symbol] = dom
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
        if not self.ib:
            return {}
        tick_data = {}
        try:
            for symbol in symbols:
                ticks = {
                    "symbol": symbol,
                    "ticks": [],
                    "timestamp": datetime.utcnow().isoformat(),
                }
                tick_data[symbol] = ticks
        except Exception:
            return {}
        return tick_data

    def get_cached(self, key: str) -> Optional[dict]:
        if not self.redis:
            return None
        try:
            cached = self.redis.hgetall(key)
            if not cached:
                return None
            data = json.loads(cached[b"data"].decode())
            if self.is_stale(data):
                return None
            return data
        except Exception:
            return None

    def is_stale(self, data: dict) -> bool:
        if "timestamp" not in data:
            return True
        try:
            ts = datetime.fromisoformat(data["timestamp"])
            now = datetime.utcnow()
            age_seconds = (now - ts).total_seconds()
            poll_interval = 5
            if "strikes" in data:
                poll_interval = 60
            elif "bid_prices" in data:
                poll_interval = 5
            elif "ticks" in data:
                poll_interval = 1
            stale_threshold = poll_interval * self.staleness_multiplier
            return age_seconds > stale_threshold
        except Exception:
            return True

    def _get_ticker(self, symbol: str) -> Optional[dict]:
        try:
            return None
        except Exception:
            return None
