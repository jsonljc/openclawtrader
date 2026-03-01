#!/usr/bin/env python3
"""
Binance Spot REST market data for paper trading.
  GET /api/v3/ticker/bookTicker?symbol=BTCUSDT  → bid/ask
  GET /api/v3/klines?symbol=BTCUSDT&interval=15m&limit=3  → candles
  GET /api/v3/time  → server clock (optional)

Kline format (index):
  0  open_time_ms, 1 open, 2 high, 3 low, 4 close, 5 volume,
  6  close_time_ms (inclusive), 7 quote_asset_volume, 8 trades, ...
"""
from __future__ import annotations

import json
import urllib.request
import urllib.error
from datetime import datetime, timezone
from typing import Any

BINANCE_BASE = "https://api.binance.com"
DEFAULT_SYMBOL = "BTCUSDT"
DEFAULT_TIMEOUT = 10


def _now_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def get_server_time() -> int | None:
    """GET /api/v3/time → serverTime in ms."""
    url = f"{BINANCE_BASE}/api/v3/time"
    try:
        with urllib.request.urlopen(url, timeout=DEFAULT_TIMEOUT) as resp:
            data = json.loads(resp.read().decode())
        return int(data.get("serverTime", 0))
    except Exception:
        return None


def get_book_ticker(symbol: str = DEFAULT_SYMBOL) -> dict | None:
    """
    GET /api/v3/ticker/bookTicker?symbol=SYMBOL.
    Returns {"bid", "ask", "mid", "spread_bps"} or None on failure.
    """
    url = f"{BINANCE_BASE}/api/v3/ticker/bookTicker?symbol={symbol}"
    try:
        with urllib.request.urlopen(url, timeout=DEFAULT_TIMEOUT) as resp:
            d = json.loads(resp.read().decode())
        bid = float(d["bidPrice"])
        ask = float(d["askPrice"])
        mid = (bid + ask) / 2.0
        spread_bps = (ask - bid) / mid * 10_000 if mid > 0 else 0.0
        return {"bid": bid, "ask": ask, "mid": mid, "spread_bps": round(spread_bps, 2)}
    except Exception:
        return None


def get_klines(
    symbol: str = DEFAULT_SYMBOL,
    interval: str = "15m",
    limit: int = 3,
) -> list[list[Any]] | None:
    """
    GET /api/v3/klines?symbol=SYMBOL&interval=15m&limit=N.
    Returns raw list-of-lists (prices are strings; caller casts).
    """
    url = f"{BINANCE_BASE}/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    try:
        with urllib.request.urlopen(url, timeout=DEFAULT_TIMEOUT) as resp:
            data = json.loads(resp.read().decode())
        return data if isinstance(data, list) else None
    except Exception:
        return None


def parse_candle(candle: list) -> dict | None:
    """
    Parse a Binance kline list into a typed dict.
    close_time_ms (index 6) is the inclusive close timestamp for the bar.
    A candle is fully closed when close_time_ms + 1 ms has elapsed.
    """
    if not candle or len(candle) < 6:
        return None
    try:
        result: dict[str, Any] = {
            "open_time_ms":  int(candle[0]),
            "open":          float(candle[1]),
            "high":          float(candle[2]),
            "low":           float(candle[3]),
            "close":         float(candle[4]),
            "volume":        float(candle[5]),
            "close_time_ms": int(candle[6]) if len(candle) > 6 else None,
        }
        return result
    except (TypeError, ValueError, IndexError):
        return None


def get_confirmed_closed_candle(
    symbol: str = DEFAULT_SYMBOL,
    interval: str = "15m",
    now_ms: int | None = None,
) -> dict | None:
    """
    [F1] Return the most recent *confirmed-closed* candle — one where:
        close_time_ms + 1000 <= now_ms
    so we never accidentally use a still-forming bar.

    Fetches 3 candles to handle the edge case where the second-to-last is still
    forming at the exact boundary.  Returns None if no confirmed candle found.

    The returned dict includes:
      close_time_ms        – raw close timestamp
      close_time_utc       – ISO8601 string (for logging / ExecutionReport)
    """
    if now_ms is None:
        now_ms = _now_ms()

    raw = get_klines(symbol=symbol, interval=interval, limit=3)
    if not raw:
        return None

    for raw_candle in reversed(raw):
        c = parse_candle(raw_candle)
        if c is None:
            continue
        close_ms = c.get("close_time_ms")
        if close_ms is None:
            continue
        if close_ms + 1000 <= now_ms:
            c["close_time_utc"] = (
                datetime.fromtimestamp(close_ms / 1000, tz=timezone.utc).isoformat()
            )
            return c

    return None


def candle_range_bps(candle: dict | None) -> float:
    """Compute (high - low) / close * 10000 for a parsed candle. Returns 0.0 if None."""
    if not candle:
        return 0.0
    close = candle.get("close", 0.0)
    if close <= 0:
        return 0.0
    return round((candle.get("high", 0.0) - candle.get("low", 0.0)) / close * 10_000, 2)


# Kept for backward compat; prefer get_confirmed_closed_candle in new code.
def get_latest_15m_candle(symbol: str = DEFAULT_SYMBOL) -> dict | None:
    """Deprecated: no close-time guarantee. Use get_confirmed_closed_candle()."""
    return get_confirmed_closed_candle(symbol=symbol)
