#!/usr/bin/env python3
"""
Data staleness guard (Institutional Risk Layer v1).
Input: snapshot (path or dict) with latest candle timestamp for the trading timeframe.
Output: { "pass": bool, "reason": str | null }.
Rule: If now_utc - last_candle_ts_utc > (timeframe_sec * 2) => BLOCK.

Usage:
    python3 staleness_guard.py --snapshot-file /tmp/c3po_snapshot.json --timeframe 15m
    python3 staleness_guard.py --snapshot-file /tmp/c3po_snapshot.json --timeframe-sec 900
"""

import argparse
import json
import sys
from datetime import datetime, timezone


def check_staleness(
    last_candle_ts_utc_sec: float,
    timeframe_sec: int,
    now_utc_sec: float | None = None,
) -> dict:
    """
    Returns {"pass": bool, "reason": str | None}.
    BLOCK if (now_utc - last_candle_ts_utc) > (timeframe_sec * 2).
    """
    now = now_utc_sec if now_utc_sec is not None else datetime.now(timezone.utc).timestamp()
    age_sec = now - last_candle_ts_utc_sec
    threshold_sec = timeframe_sec * 2
    if age_sec > threshold_sec:
        return {
            "pass": False,
            "reason": f"STALE_DATA: age_sec={age_sec:.0f} > threshold_sec={threshold_sec} (timeframe_sec*2)",
        }
    return {"pass": True, "reason": None}


TIMEFRAME_SEC = {"1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400}


def main():
    parser = argparse.ArgumentParser(description="Staleness guard for C3PO snapshot")
    parser.add_argument("--snapshot-file", required=True, help="Path to C3PO snapshot JSON")
    parser.add_argument("--timeframe", default="15m", help="Timeframe key (e.g. 15m)")
    parser.add_argument("--timeframe-sec", type=int, default=None, help="Override: timeframe in seconds")
    args = parser.parse_args()

    timeframe_sec = args.timeframe_sec or TIMEFRAME_SEC.get(args.timeframe, 900)

    try:
        with open(args.snapshot_file) as f:
            snapshot = json.load(f)
    except FileNotFoundError:
        out = {"pass": False, "reason": "snapshot_file_not_found"}
        print(json.dumps(out))
        sys.exit(1)
    except json.JSONDecodeError as e:
        out = {"pass": False, "reason": f"invalid_json:{e}"}
        print(json.dumps(out))
        sys.exit(1)

    timeframes = snapshot.get("timeframes", {})
    candles = timeframes.get(args.timeframe) if timeframes else None
    if not candles or len(candles) < 1:
        out = {"pass": False, "reason": "no_candles_for_timeframe"}
        print(json.dumps(out))
        sys.exit(1)

    # Last candle: Binance returns oldest first, so last element is most recent
    last_candle = candles[-1]
    last_ts_ms = last_candle.get("ts") or last_candle.get("close_ts", 0)
    last_candle_ts_utc_sec = last_ts_ms / 1000.0

    result = check_staleness(last_candle_ts_utc_sec, timeframe_sec)
    print(json.dumps(result))
    sys.exit(0 if result["pass"] else 1)


if __name__ == "__main__":
    main()
