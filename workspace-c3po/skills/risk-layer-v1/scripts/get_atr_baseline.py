#!/usr/bin/env python3
"""
Output ATR_15m and ATR_15m_baseline (SMA of last N ATR values) for volatility_multiplier.
Reads C3PO snapshot and optionally regime ATR. Baseline = mean of last baseline_window ATR(14) values.
"""

import argparse
import json
import sys
from pathlib import Path


def compute_true_ranges(candles: list) -> list:
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


def wilder_atr_at_i(trs: list, period: int, end_i: int) -> float | None:
    """ATR(period) ending at index end_i (inclusive)."""
    if end_i < period - 1 or end_i >= len(trs):
        return None
    atr = sum(trs[end_i - period + 1 : end_i + 1]) / period
    for j in range(end_i - period + 1 + 1, end_i + 1):
        atr = (atr * (period - 1) + trs[j]) / period
    return atr


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot-file", required=True)
    parser.add_argument("--timeframe", default="15m")
    parser.add_argument("--period", type=int, default=14)
    parser.add_argument("--baseline-window", type=int, default=20)
    parser.add_argument("--regime-file", default=None, help="Optional: use atr from regime for current")
    args = parser.parse_args()

    try:
        with open(args.snapshot_file) as f:
            snapshot = json.load(f)
    except Exception as e:
        print(json.dumps({"error": str(e), "atr_15m": None, "atr_15m_baseline": None}))
        sys.exit(1)

    timeframes = snapshot.get("timeframes", {})
    candles = timeframes.get(args.timeframe, [])
    if not candles or len(candles) < args.period + args.baseline_window:
        # Fallback: use regime file for current ATR and baseline = current (no reduction)
        if args.regime_file and Path(args.regime_file).exists():
            try:
                with open(args.regime_file) as f:
                    regime = json.load(f)
                atr_tf = regime.get("atr", {}).get(args.timeframe, {})
                atr_15m = atr_tf.get("value")
                if atr_15m is not None:
                    print(json.dumps({"atr_15m": atr_15m, "atr_15m_baseline": atr_15m, "reason": "insufficient_candles"}))
                    sys.exit(0)
            except Exception:
                pass
        print(json.dumps({"atr_15m": None, "atr_15m_baseline": None, "error": "insufficient_candles"}))
        sys.exit(1)

    trs = compute_true_ranges(candles)
    atr_values = []
    for i in range(args.period - 1, len(trs)):
        a = wilder_atr_at_i(trs, args.period, i)
        if a is not None:
            atr_values.append(a)
    if not atr_values:
        print(json.dumps({"atr_15m": None, "atr_15m_baseline": None}))
        sys.exit(1)

    atr_15m = atr_values[-1]
    last_n = atr_values[-args.baseline_window :]
    atr_15m_baseline = sum(last_n) / len(last_n) if last_n else atr_15m

    out = {"atr_15m": round(atr_15m, 4), "atr_15m_baseline": round(atr_15m_baseline, 4)}
    print(json.dumps(out))
    sys.exit(0)


if __name__ == "__main__":
    main()
