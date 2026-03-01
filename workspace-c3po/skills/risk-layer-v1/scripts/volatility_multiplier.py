#!/usr/bin/env python3
"""
Volatility shock sizing reducer (Institutional Risk Layer v1).
Input: ATR_15m, ATR_15m_baseline (e.g. ATR_15m_sma20 or baseline value).
Output: multiplier float + reason.
Default rule: ratio = ATR_15m / ATR_15m_baseline; if ratio >= 2.5 => multiplier = 0.6, else 1.0.

Usage:
    python3 volatility_multiplier.py --atr 1200 --atr-baseline 500
    python3 volatility_multiplier.py --atr 1200 --atr-baseline 500 --ratio-threshold 2.5 --vol-mult 0.6
"""

import argparse
import json
import sys


def compute_multiplier(
    atr_15m: float,
    atr_15m_baseline: float,
    ratio_threshold: float = 2.5,
    vol_multiplier: float = 0.6,
) -> dict:
    """
    Returns {"multiplier": float, "reason": str}.
    If atr_15m_baseline <= 0, returns multiplier 1.0 and reason "invalid_baseline".
    """
    if atr_15m_baseline <= 0:
        return {"multiplier": 1.0, "reason": "invalid_baseline"}
    ratio = atr_15m / atr_15m_baseline
    if ratio >= ratio_threshold:
        return {
            "multiplier": vol_multiplier,
            "reason": f"volatility_ratio={ratio:.2f} >= {ratio_threshold}",
            "ratio": ratio,
        }
    return {"multiplier": 1.0, "reason": None, "ratio": ratio}


def main():
    parser = argparse.ArgumentParser(description="Volatility multiplier for size_mult")
    parser.add_argument("--atr", type=float, required=True, help="ATR(15m) current value")
    parser.add_argument("--atr-baseline", type=float, required=True, help="ATR(15m) baseline (e.g. SMA20 of ATR)")
    parser.add_argument("--ratio-threshold", type=float, default=2.5, help="Ratio above which to reduce size")
    parser.add_argument("--vol-mult", type=float, default=0.6, help="Multiplier when ratio >= threshold")
    args = parser.parse_args()

    result = compute_multiplier(
        args.atr,
        args.atr_baseline,
        ratio_threshold=args.ratio_threshold,
        vol_multiplier=args.vol_mult,
    )
    print(json.dumps(result))
    sys.exit(0)


if __name__ == "__main__":
    main()
