#!/usr/bin/env python3
"""
get_ohlcv.py
Fetches OHLCV candles for multiple timeframes from Binance REST API.
Writes a JSON snapshot file and also prints to stdout.

Usage:
    python3 get_ohlcv.py
    python3 get_ohlcv.py --timeframes 1m 5m 15m 1h 4h --limit 100
    python3 get_ohlcv.py --symbol BTCUSDT --out /tmp/snapshot.json
    python3 get_ohlcv.py --stale-threshold-ms 5000
"""

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone

BINANCE_BASE = "https://api.binance.com"
STALE_THRESHOLD_MS_DEFAULT = 5000

VALID_INTERVALS = {"1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d", "3d", "1w", "1M"}


def fetch_klines(symbol: str, interval: str, limit: int) -> list:
    """Fetch klines (OHLCV) from Binance for a single timeframe."""
    url = f"{BINANCE_BASE}/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            raw = json.loads(resp.read().decode())
        candles = []
        for k in raw:
            candles.append({
                "ts": int(k[0]),
                "o": float(k[1]),
                "h": float(k[2]),
                "l": float(k[3]),
                "c": float(k[4]),
                "v": float(k[5]),
                "close_ts": int(k[6]),
            })
        return candles
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(json.dumps({"error": f"HTTP {e.code} on {interval}", "detail": body}), file=sys.stderr)
        return []
    except urllib.error.URLError as e:
        print(json.dumps({"error": f"URLError on {interval}", "detail": str(e.reason)}), file=sys.stderr)
        return []


def fetch_server_time() -> int:
    url = f"{BINANCE_BASE}/api/v3/time"
    with urllib.request.urlopen(url, timeout=5) as resp:
        return int(json.loads(resp.read().decode())["serverTime"])


def check_stale(server_time_ms: int, threshold_ms: int) -> tuple[bool, float]:
    now_ms = datetime.now(timezone.utc).timestamp() * 1000
    age_ms = abs(now_ms - server_time_ms)
    return age_ms > threshold_ms, round(age_ms, 2)


def main():
    parser = argparse.ArgumentParser(description="Fetch multi-timeframe OHLCV from Binance")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--timeframes", nargs="+", default=["1m", "5m", "15m", "1h", "4h"])
    parser.add_argument("--limit", type=int, default=100,
                        help="Candles per timeframe (max 500)")
    parser.add_argument("--out", default=None,
                        help="Optional path to write JSON snapshot file")
    parser.add_argument("--stale-threshold-ms", type=int, default=STALE_THRESHOLD_MS_DEFAULT)
    args = parser.parse_args()

    symbol = args.symbol.upper()
    limit = min(args.limit, 500)

    invalid = [tf for tf in args.timeframes if tf not in VALID_INTERVALS]
    if invalid:
        print(json.dumps({"error": f"Invalid timeframes: {invalid}"}), file=sys.stderr)
        sys.exit(1)

    server_time_ms = fetch_server_time()
    is_stale, age_ms = check_stale(server_time_ms, args.stale_threshold_ms)

    fetched_at = datetime.fromtimestamp(
        datetime.now(timezone.utc).timestamp(), tz=timezone.utc
    ).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

    timeframes_data = {}
    errors = {}

    for tf in args.timeframes:
        candles = fetch_klines(symbol, tf, limit)
        timeframes_data[tf] = candles
        if not candles:
            errors[tf] = "empty or failed"
        time.sleep(0.05)

    output = {
        "symbol": symbol,
        "fetched_at": fetched_at,
        "server_time_ms": server_time_ms,
        "age_ms": age_ms,
        "stale": is_stale,
        "stale_threshold_ms": args.stale_threshold_ms,
        "limit": limit,
        "timeframes": timeframes_data,
    }

    if errors:
        output["errors"] = errors

    json_out = json.dumps(output, indent=2)
    print(json_out)

    out_path = args.out if args.out else "/tmp/c3po_snapshot.json"

    try:
        with open(out_path, "w") as f:
            f.write(json_out)
        print(f"[market-snapshot] Snapshot written to {out_path}", file=sys.stderr)
    except OSError as e:
        print(f"[market-snapshot] Warning: could not write snapshot file: {e}", file=sys.stderr)

    if is_stale:
        print(f"[market-snapshot] WARNING: Snapshot is stale (age={age_ms}ms > threshold={args.stale_threshold_ms}ms)",
              file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
