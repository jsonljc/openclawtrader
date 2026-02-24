#!/usr/bin/env python3
"""
get_price.py
Fetches live BTCUSDT best bid/ask from Binance REST API.
Outputs a JSON object with mid price, spread in bps, timestamp, and stale flag.

Usage:
    python3 get_price.py
    python3 get_price.py --symbol ETHUSDT
    python3 get_price.py --stale-threshold-ms 5000
"""

import argparse
import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone

BINANCE_BASE = "https://api.binance.com"
STALE_THRESHOLD_MS_DEFAULT = 5000  # 5 seconds


def fetch_book_ticker(symbol: str) -> dict:
    """Fetch best bid/ask for symbol from Binance bookTicker endpoint."""
    url = f"{BINANCE_BASE}/api/v3/ticker/bookTicker?symbol={symbol}"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read().decode())
        return data
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(json.dumps({"error": f"HTTP {e.code}", "detail": body}), file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as e:
        print(json.dumps({"error": "URLError", "detail": str(e.reason)}), file=sys.stderr)
        sys.exit(1)


def fetch_server_time() -> int:
    """Fetch Binance server time in ms."""
    url = f"{BINANCE_BASE}/api/v3/time"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read().decode())
        return int(data["serverTime"])
    except Exception as e:
        print(json.dumps({"error": "Failed to fetch server time", "detail": str(e)}), file=sys.stderr)
        sys.exit(1)


def check_stale(server_time_ms: int, stale_threshold_ms: int) -> tuple[bool, float]:
    """
    Compare Binance server time to local wall clock.
    Returns (is_stale, age_ms).
    """
    now_ms = datetime.now(timezone.utc).timestamp() * 1000
    age_ms = abs(now_ms - server_time_ms)
    return age_ms > stale_threshold_ms, round(age_ms, 2)


def main():
    parser = argparse.ArgumentParser(description="Fetch BTCUSDT live price from Binance")
    parser.add_argument("--symbol", default="BTCUSDT", help="Trading pair symbol (default: BTCUSDT)")
    parser.add_argument("--stale-threshold-ms", type=int, default=STALE_THRESHOLD_MS_DEFAULT,
                        help="Max acceptable age of server time vs wall clock in ms (default: 5000)")
    args = parser.parse_args()

    symbol = args.symbol.upper()

    server_time_ms = fetch_server_time()
    ticker = fetch_book_ticker(symbol)

    bid = float(ticker["bidPrice"])
    ask = float(ticker["askPrice"])
    mid = round((bid + ask) / 2, 2)
    spread_bps = round(((ask - bid) / mid) * 10000, 4)

    is_stale, age_ms = check_stale(server_time_ms, args.stale_threshold_ms)

    ts_iso = datetime.fromtimestamp(server_time_ms / 1000, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

    output = {
        "symbol": symbol,
        "bid": bid,
        "ask": ask,
        "mid": mid,
        "spread_bps": spread_bps,
        "server_time_ms": server_time_ms,
        "ts": ts_iso,
        "age_ms": age_ms,
        "stale": is_stale,
        "stale_threshold_ms": args.stale_threshold_ms,
    }

    print(json.dumps(output, indent=2))

    # Exit code 2 on stale so callers can gate on it
    if is_stale:
        sys.exit(2)


if __name__ == "__main__":
    main()
