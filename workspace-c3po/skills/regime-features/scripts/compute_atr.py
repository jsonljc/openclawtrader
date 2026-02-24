#!/usr/bin/env python3
"""
compute_atr.py
Computes ATR(14) for each timeframe in a C3PO snapshot file.
Uses Wilder's smoothing (standard ATR definition).

Usage:
    python3 compute_atr.py --snapshot-file /tmp/c3po_snapshot.json
    python3 compute_atr.py --snapshot-file /tmp/c3po_snapshot.json --period 14
"""

import argparse
import json
import sys
from datetime import datetime, timezone


def compute_true_ranges(candles: list) -> list:
    """
    True Range = max(H-L, |H-prev_close|, |L-prev_close|)
    First candle has no prev_close, so TR = H - L.
    """
    trs = []
    for i, c in enumerate(candles):
        h, l, close = c["h"], c["l"], c["c"]
        if i == 0:
            tr = h - l
        else:
            prev_close = candles[i - 1]["c"]
            tr = max(h - l, abs(h - prev_close), abs(l - prev_close))
        trs.append(tr)
    return trs


def wilder_atr(trs: list, period: int) -> float | None:
    """
    Wilder's smoothed ATR.
    First ATR = simple average of first `period` TRs.
    Subsequent: ATR = (prev_ATR * (period-1) + current_TR) / period
    Returns None if not enough data.
    """
    if len(trs) < period:
        return None

    atr = sum(trs[:period]) / period

    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period

    return atr


def main():
    parser = argparse.ArgumentParser(description="Compute ATR(14) across timeframes")
    parser.add_argument("--snapshot-file", required=True, help="Path to C3PO snapshot JSON")
    parser.add_argument("--period", type=int, default=14, help="ATR period (default: 14)")
    args = parser.parse_args()

    try:
        with open(args.snapshot_file) as f:
            snapshot = json.load(f)
    except FileNotFoundError:
        print(json.dumps({"error": f"Snapshot file not found: {args.snapshot_file}"}), file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"Invalid JSON in snapshot: {e}"}), file=sys.stderr)
        sys.exit(1)

    if snapshot.get("stale"):
        print(json.dumps({
            "error": "STALE_SNAPSHOT",
            "reason": "Snapshot is marked stale. Refusing to compute regime features.",
            "age_ms": snapshot.get("age_ms"),
        }))
        sys.exit(2)

    timeframes = snapshot.get("timeframes", {})
    if not timeframes:
        print(json.dumps({"error": "No timeframes found in snapshot"}), file=sys.stderr)
        sys.exit(1)

    period = args.period
    results = {}

    for tf, candles in timeframes.items():
        if not candles or len(candles) < period:
            results[tf] = {
                "value": None,
                "atr_pct": None,
                "error": f"Insufficient candles: {len(candles)} < {period}",
            }
            continue

        trs = compute_true_ranges(candles)
        atr_value = wilder_atr(trs, period)

        if atr_value is None:
            results[tf] = {"value": None, "atr_pct": None, "error": "ATR computation failed"}
            continue

        last_close = candles[-1]["c"]
        atr_pct = round((atr_value / last_close) * 100, 4) if last_close > 0 else None

        results[tf] = {
            "value": round(atr_value, 4),
            "atr_pct": atr_pct,
            "last_close": last_close,
            "candle_count": len(candles),
            "period": period,
        }

    computed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

    output = {
        "symbol": snapshot.get("symbol", "UNKNOWN"),
        "snapshot_ts": snapshot.get("fetched_at"),
        "computed_at": computed_at,
        "atr": results,
    }

    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
