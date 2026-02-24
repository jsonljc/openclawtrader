#!/usr/bin/env python3
"""
classify_trend_range.py
Classifies each timeframe as TREND_UP / TREND_DOWN / RANGE using:
  - EMA(9) vs EMA(21) crossover direction
  - ADX(14) threshold at 20

HTF bias is derived from the 4h timeframe (or highest available).

Usage:
    python3 classify_trend_range.py --snapshot-file /tmp/c3po_snapshot.json
    python3 classify_trend_range.py --snapshot-file /tmp/c3po_snapshot.json --adx-threshold 20
"""

import argparse
import json
import sys
from datetime import datetime, timezone


def ema(values: list, period: int) -> list:
    """Compute EMA series. Returns list aligned with input (None-padded start)."""
    if len(values) < period:
        return [None] * len(values)

    k = 2.0 / (period + 1)
    result = [None] * (period - 1)

    seed = sum(values[:period]) / period
    result.append(seed)

    for v in values[period:]:
        result.append(result[-1] * (1 - k) + v * k)

    return result


def compute_adx(candles: list, period: int = 14) -> list:
    """Compute ADX series using Wilder's smoothing. Returns list (None until enough data)."""
    if len(candles) < period + 1:
        return [None] * len(candles)

    dm_plus = []
    dm_minus = []
    trs = []

    for i in range(1, len(candles)):
        high = candles[i]["h"]
        low = candles[i]["l"]
        prev_high = candles[i - 1]["h"]
        prev_low = candles[i - 1]["l"]
        prev_close = candles[i - 1]["c"]

        up_move = high - prev_high
        down_move = prev_low - low

        dm_plus.append(up_move if up_move > down_move and up_move > 0 else 0.0)
        dm_minus.append(down_move if down_move > up_move and down_move > 0 else 0.0)

        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)

    def wilder_smooth(data, p):
        if len(data) < p:
            return []
        s = sum(data[:p])
        result = [s]
        for v in data[p:]:
            s = s - (s / p) + v
            result.append(s)
        return result

    smooth_tr = wilder_smooth(trs, period)
    smooth_dm_plus = wilder_smooth(dm_plus, period)
    smooth_dm_minus = wilder_smooth(dm_minus, period)

    min_len = min(len(smooth_tr), len(smooth_dm_plus), len(smooth_dm_minus))

    dx_list = []
    for i in range(min_len):
        atr_val = smooth_tr[i]
        if atr_val == 0:
            dx_list.append(0.0)
        else:
            dip = 100 * smooth_dm_plus[i] / atr_val
            dim = 100 * smooth_dm_minus[i] / atr_val
            denom = dip + dim
            dx_list.append(100 * abs(dip - dim) / denom if denom != 0 else 0.0)

    adx_smooth = wilder_smooth(dx_list, period)

    pad = len(candles) - len(adx_smooth)
    return [None] * pad + [round(v, 4) for v in adx_smooth]


def classify_timeframe(candles: list, adx_threshold: float, fast_period: int = 9, slow_period: int = 21):
    """Returns classification dict for a single timeframe."""
    if len(candles) < slow_period + 14:
        return {
            "type": "UNKNOWN",
            "adx": None,
            "ema_cross": "unknown",
            "confidence": "LOW",
            "error": f"Insufficient candles: {len(candles)}",
        }

    closes = [c["c"] for c in candles]

    ema_fast = ema(closes, fast_period)
    ema_slow = ema(closes, slow_period)
    adx_series = compute_adx(candles)

    last_ema_fast = next((v for v in reversed(ema_fast) if v is not None), None)
    last_ema_slow = next((v for v in reversed(ema_slow) if v is not None), None)
    last_adx = next((v for v in reversed(adx_series) if v is not None), None)

    if last_ema_fast is None or last_ema_slow is None or last_adx is None:
        return {
            "type": "UNKNOWN",
            "adx": None,
            "ema_cross": "unknown",
            "confidence": "LOW",
            "error": "Could not compute indicators",
        }

    if last_ema_fast > last_ema_slow * 1.0001:
        ema_cross = "bullish"
    elif last_ema_fast < last_ema_slow * 0.9999:
        ema_cross = "bearish"
    else:
        ema_cross = "neutral"

    if last_adx < adx_threshold:
        trend_type = "RANGE"
    elif ema_cross == "bullish":
        trend_type = "TREND_UP"
    elif ema_cross == "bearish":
        trend_type = "TREND_DOWN"
    else:
        trend_type = "RANGE"

    if last_adx > 25 and ema_cross in ("bullish", "bearish"):
        confidence = "HIGH"
    elif last_adx >= adx_threshold and ema_cross in ("bullish", "bearish"):
        confidence = "MEDIUM"
    else:
        confidence = "LOW"

    return {
        "type": trend_type,
        "adx": round(last_adx, 2),
        "ema_fast": round(last_ema_fast, 2),
        "ema_slow": round(last_ema_slow, 2),
        "ema_cross": ema_cross,
        "confidence": confidence,
    }


HTF_PREFERENCE = ["1w", "3d", "1d", "4h", "1h", "2h"]


def derive_htf_bias(classifications: dict) -> str:
    for tf in HTF_PREFERENCE:
        if tf in classifications:
            t = classifications[tf].get("type", "UNKNOWN")
            if t == "TREND_UP":
                return "BULLISH"
            elif t == "TREND_DOWN":
                return "BEARISH"
            elif t == "RANGE":
                return "NEUTRAL"
    return "UNKNOWN"


def main():
    parser = argparse.ArgumentParser(description="Classify trend/range across timeframes")
    parser.add_argument("--snapshot-file", required=True)
    parser.add_argument("--adx-threshold", type=float, default=20.0,
                        help="ADX level below which market is considered ranging (default: 20)")
    parser.add_argument("--fast-ema", type=int, default=9)
    parser.add_argument("--slow-ema", type=int, default=21)
    args = parser.parse_args()

    try:
        with open(args.snapshot_file) as f:
            snapshot = json.load(f)
    except FileNotFoundError:
        print(json.dumps({"error": f"Snapshot file not found: {args.snapshot_file}"}), file=sys.stderr)
        sys.exit(1)

    if snapshot.get("stale"):
        print(json.dumps({"error": "STALE_SNAPSHOT", "reason": "Refusing to classify stale snapshot"}))
        sys.exit(2)

    timeframes = snapshot.get("timeframes", {})
    classifications = {}

    for tf, candles in timeframes.items():
        classifications[tf] = classify_timeframe(
            candles,
            args.adx_threshold,
            args.fast_ema,
            args.slow_ema,
        )

    htf_bias = derive_htf_bias(classifications)
    computed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

    any_low_confidence = any(
        c.get("confidence") == "LOW"
        for tf, c in classifications.items()
        if tf in ("15m", "1h", "4h")
    )

    output = {
        "symbol": snapshot.get("symbol", "UNKNOWN"),
        "snapshot_ts": snapshot.get("fetched_at"),
        "computed_at": computed_at,
        "classifications": classifications,
        "htf_bias": htf_bias,
        "adx_threshold": args.adx_threshold,
        "tradeable": not any_low_confidence,
        "low_confidence_warning": any_low_confidence,
    }

    print(json.dumps(output, indent=2))

    if any_low_confidence:
        print("[classify-trend-range] WARNING: LOW confidence on one or more key timeframes", file=sys.stderr)
        sys.exit(3)


if __name__ == "__main__":
    main()
