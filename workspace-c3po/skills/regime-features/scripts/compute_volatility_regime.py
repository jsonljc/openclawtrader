#!/usr/bin/env python3
"""
compute_volatility_regime.py
Classifies current volatility regime as LOW / NORMAL / ELEVATED / EXTREME
using the current ATR vs a rolling 20-period ATR percentile on the reference timeframe.

Regime thresholds (ATR percentile):
  LOW      < 25th
  NORMAL   25–60th
  ELEVATED 60–85th
  EXTREME  > 85th

Usage:
    python3 compute_volatility_regime.py --snapshot-file /tmp/c3po_snapshot.json
    python3 compute_volatility_regime.py --snapshot-file /tmp/c3po_snapshot.json --ref-timeframe 1h --window 20
"""

import argparse
import json
import sys
from datetime import datetime, timezone


REGIME_THRESHOLDS = {
    "LOW": 25,
    "NORMAL": 60,
    "ELEVATED": 85,
    "EXTREME": 100,
}


def compute_true_ranges(candles: list) -> list:
    trs = []
    for i, c in enumerate(candles):
        h, l = c["h"], c["l"]
        if i == 0:
            trs.append(h - l)
        else:
            prev_close = candles[i - 1]["c"]
            trs.append(max(h - l, abs(h - prev_close), abs(l - prev_close)))
    return trs


def wilder_atr_series(trs: list, period: int = 14) -> list:
    """
    Returns a list of ATR values (one per candle after seed period).
    Used to build the rolling distribution.
    """
    if len(trs) < period:
        return []

    atr = sum(trs[:period]) / period
    series = [atr]

    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
        series.append(atr)

    return series


def atr_percentile_rank(atr_series: list, window: int) -> tuple[float, float]:
    """
    Returns (current_atr, percentile_rank) for current ATR
    relative to the last `window` ATR values.
    """
    if len(atr_series) < 2:
        return atr_series[-1] if atr_series else 0.0, 50.0

    window_data = atr_series[-window:]
    current_atr = atr_series[-1]

    rank = sum(1 for v in window_data if v <= current_atr) / len(window_data) * 100
    return current_atr, round(rank, 2)


def classify_regime(pct_rank: float) -> str:
    if pct_rank < REGIME_THRESHOLDS["LOW"]:
        return "LOW"
    elif pct_rank < REGIME_THRESHOLDS["NORMAL"]:
        return "NORMAL"
    elif pct_rank < REGIME_THRESHOLDS["ELEVATED"]:
        return "ELEVATED"
    else:
        return "EXTREME"


def main():
    parser = argparse.ArgumentParser(description="Classify volatility regime from OHLCV snapshot")
    parser.add_argument("--snapshot-file", required=True)
    parser.add_argument("--ref-timeframe", default="1h",
                        help="Reference timeframe for regime classification (default: 1h)")
    parser.add_argument("--window", type=int, default=20,
                        help="Rolling window for ATR percentile (default: 20)")
    parser.add_argument("--atr-period", type=int, default=14)
    args = parser.parse_args()

    try:
        with open(args.snapshot_file) as f:
            snapshot = json.load(f)
    except FileNotFoundError:
        print(json.dumps({"error": f"Snapshot file not found: {args.snapshot_file}"}), file=sys.stderr)
        sys.exit(1)

    if snapshot.get("stale"):
        print(json.dumps({
            "error": "STALE_SNAPSHOT",
            "reason": "Refusing to compute volatility regime from stale snapshot.",
        }))
        sys.exit(2)

    timeframes = snapshot.get("timeframes", {})
    ref_tf = args.ref_timeframe

    if ref_tf not in timeframes:
        print(json.dumps({
            "error": f"Reference timeframe '{ref_tf}' not found in snapshot",
            "available": list(timeframes.keys()),
        }), file=sys.stderr)
        sys.exit(1)

    candles = timeframes[ref_tf]
    min_candles = args.atr_period + args.window
    if len(candles) < min_candles:
        print(json.dumps({
            "error": f"Insufficient candles for regime. Need {min_candles}, got {len(candles)}",
        }), file=sys.stderr)
        sys.exit(1)

    trs = compute_true_ranges(candles)
    atr_series = wilder_atr_series(trs, args.atr_period)

    current_atr, pct_rank = atr_percentile_rank(atr_series, args.window)
    regime = classify_regime(pct_rank)

    computed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

    output = {
        "regime": regime,
        "atr_percentile": pct_rank,
        "current_atr": round(current_atr, 4),
        "reference_timeframe": ref_tf,
        "window": args.window,
        "atr_period": args.atr_period,
        "candle_count": len(candles),
        "thresholds": REGIME_THRESHOLDS,
        "tradeable": regime != "EXTREME",
        "computed_at": computed_at,
        "snapshot_ts": snapshot.get("fetched_at"),
    }

    if regime == "EXTREME":
        output["halt_reason"] = "EXTREME volatility regime — Sentinel must reduce posture or halt"

    print(json.dumps(output, indent=2))

    # Exit 3 on EXTREME so callers can gate on it
    if regime == "EXTREME":
        sys.exit(3)


if __name__ == "__main__":
    main()
