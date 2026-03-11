#!/usr/bin/env python3
"""Trend Day Pullback setup scanner.

Entry rules:
    - Regime = TREND (required)
    - Session = MORNING_DRIVE or AFTERNOON (best pullback windows)
    - Price made a new high/low for the day (confirms trend day)
    - Pullback to VWAP or 20-period EMA on 5m chart (within 0.3 ATR)
    - Pullback depth < 50% of prior move (shallow = strong trend)
    - Hold above VWAP (for longs) during pullback

Stop: Below pullback low (longs) / above pullback high (shorts), min 3 points
T1: Prior high/low (the level that initiated the pullback), 50% exit
T2: 1.5× the distance from pullback low to prior high
Invalidation: 5m close through VWAP on wrong side
"""

from __future__ import annotations

from typing import Any

import indicators
from shared.utils import round_to_tick


def _find_day_extremes(bars_5m: list[dict]) -> tuple[float, float]:
    """Find the session high and low from today's 5m bars."""
    if not bars_5m:
        return 0.0, 0.0
    day_high = max(b.get("h", b.get("high", 0)) for b in bars_5m)
    day_low = min(b.get("l", b.get("low", float('inf'))) for b in bars_5m)
    return day_high, day_low


def _detect_pullback(
    bars_5m: list[dict],
    side: str,
    vwap: float,
    ema_20: float,
    atr: float,
) -> dict | None:
    """
    Detect a pullback to VWAP or 20-EMA in a trending market.

    Returns pullback info dict or None if no valid pullback found.
    """
    if len(bars_5m) < 10 or atr <= 0:
        return None

    proximity_threshold = 0.3 * atr  # within 0.3 ATR of support/resistance

    # Recent bars for pullback analysis
    recent = bars_5m[-8:]  # last 8 bars (40 min window)
    current = bars_5m[-1]
    current_close = current["c"]
    current_low = current.get("l", current.get("low", current_close))
    current_high = current.get("h", current.get("high", current_close))

    if side == "BUY":
        # Look for pullback to support (VWAP or EMA20)
        support_level = max(vwap, ema_20) if vwap > 0 and ema_20 > 0 else (vwap or ema_20)
        if support_level <= 0:
            return None

        # Price must be near support (within proximity)
        dist_to_support = current_low - support_level
        if dist_to_support < -proximity_threshold or dist_to_support > proximity_threshold:
            return None  # Too far from support or broke through

        # Must still be above VWAP (hold condition)
        if vwap > 0 and current_close < vwap:
            return None

        # Find the swing high before the pullback
        swing_high = max(b.get("h", b.get("high", 0)) for b in recent)
        pullback_low = min(b.get("l", b.get("low", float('inf'))) for b in recent[-4:])

        # Check pullback depth < 50% of prior move
        move_size = swing_high - support_level
        pullback_depth = swing_high - pullback_low
        if move_size <= 0 or pullback_depth / move_size > 0.50:
            return None  # Too deep

        return {
            "swing_high": swing_high,
            "pullback_low": pullback_low,
            "support_level": support_level,
            "pullback_depth_pct": round(pullback_depth / move_size * 100, 1),
        }

    else:  # SELL
        # Look for pullback to resistance (VWAP or EMA20)
        resistance_level = min(vwap, ema_20) if vwap > 0 and ema_20 > 0 else (vwap or ema_20)
        if resistance_level <= 0:
            return None

        dist_to_resistance = resistance_level - current_high
        if dist_to_resistance < -proximity_threshold or dist_to_resistance > proximity_threshold:
            return None

        # Must still be below VWAP
        if vwap > 0 and current_close > vwap:
            return None

        swing_low = min(b.get("l", b.get("low", float('inf'))) for b in recent)
        pullback_high = max(b.get("h", b.get("high", 0)) for b in recent[-4:])

        move_size = resistance_level - swing_low
        pullback_depth = pullback_high - swing_low
        if move_size <= 0 or pullback_depth / move_size > 0.50:
            return None

        return {
            "swing_low": swing_low,
            "pullback_high": pullback_high,
            "resistance_level": resistance_level,
            "pullback_depth_pct": round(pullback_depth / move_size * 100, 1),
        }


def detect(
    regime: dict,
    session: dict,
    structure: dict | None,
    bars_5m: list[dict],
    snapshot: dict,
    strategy: dict,
) -> dict[str, Any] | None:
    """
    Scan for a Trend Day Pullback setup.

    Returns a SetupCandidate dict or None if no valid setup.
    """
    if not structure or not bars_5m or len(bars_5m) < 15:
        return None

    # --- Regime gate: only fires in TREND ---
    regime_type = regime.get("regime_type", "NEUTRAL")
    if regime_type != "TREND":
        return None

    # --- Session gate: MORNING_DRIVE or AFTERNOON ---
    session_name = session.get("session", "CLOSED")
    if session_name not in ("MORNING_DRIVE", "AFTERNOON"):
        return None
    if not session.get("is_rth", False):
        return None

    ind = snapshot.get("indicators", {})
    atr = ind.get("atr_14_1H", 0.0) or ind.get("atr_14_4H", 10.0)
    if atr <= 0:
        return None

    vwap = structure.get("vwap", 0.0)
    last_price = ind.get("last_price", 0.0)
    if last_price <= 0:
        return None

    # Compute 20-period EMA from 5m closes
    closes_5m = [b["c"] for b in bars_5m]
    ema_20 = indicators.ema(closes_5m, 20)

    # Determine trend direction from day's price action
    day_high, day_low = _find_day_extremes(bars_5m)

    # Check for new day high/low to confirm trend day
    current_bar = bars_5m[-1]
    current_high = current_bar.get("h", current_bar.get("high", 0))
    current_low = current_bar.get("l", current_bar.get("low", float('inf')))

    # Determine side based on trend direction
    tick = strategy.get("tick_size", 0.25)
    side = None
    min_stop_pts = strategy.get("signal", {}).get("min_stop_points", 3)

    # Recent 20 bars made new high → uptrend day
    recent_20 = bars_5m[-20:] if len(bars_5m) >= 20 else bars_5m
    recent_high = max(b.get("h", b.get("high", 0)) for b in recent_20)
    recent_low = min(b.get("l", b.get("low", float('inf'))) for b in recent_20)

    # Uptrend: day high was made recently and price is above VWAP
    if recent_high == day_high and last_price > vwap and vwap > 0:
        pullback = _detect_pullback(bars_5m, "BUY", vwap, ema_20, atr)
        if pullback:
            side = "BUY"
            entry_price = last_price
            stop_price = pullback["pullback_low"] - min_stop_pts
            if entry_price - stop_price < min_stop_pts:
                stop_price = entry_price - min_stop_pts

            # T1: prior swing high
            t1_price = round_to_tick(pullback["swing_high"], tick)
            # T2: 1.5× distance from pullback low to prior high
            move_dist = pullback["swing_high"] - pullback["pullback_low"]
            t2_price = round_to_tick(pullback["pullback_low"] + 1.5 * move_dist, tick)
            target_price = t2_price

    # Downtrend: day low was made recently and price is below VWAP
    if side is None and recent_low == day_low and last_price < vwap and vwap > 0:
        pullback = _detect_pullback(bars_5m, "SELL", vwap, ema_20, atr)
        if pullback:
            side = "SELL"
            entry_price = last_price
            stop_price = pullback["pullback_high"] + min_stop_pts
            if stop_price - entry_price < min_stop_pts:
                stop_price = entry_price + min_stop_pts

            t1_price = round_to_tick(pullback["swing_low"], tick)
            move_dist = pullback["pullback_high"] - pullback["swing_low"]
            t2_price = round_to_tick(pullback["pullback_high"] - 1.5 * move_dist, tick)
            target_price = t2_price

    if side is None:
        return None

    # --- Validate R:R ---
    risk = abs(entry_price - stop_price)
    reward = abs(target_price - entry_price)
    if risk <= 0 or reward / risk < 1.0:
        return None

    return {
        "side": side,
        "entry_price": round_to_tick(entry_price, tick),
        "stop_price": round_to_tick(stop_price, tick),
        "target_price": round_to_tick(target_price, tick),
        "setup_family": "TREND_PULLBACK",
        "scale_out_plan": {
            "t1_pct": 50,
            "t1_price": t1_price,
            "t2_price": t2_price,
            "trailing_atr_multiple": 1.5,
        },
        "metadata": {
            "vwap": vwap,
            "ema_20": ema_20,
            "atr": atr,
            "day_high": day_high,
            "day_low": day_low,
            "pullback": pullback,
            "regime_type": regime_type,
            "session": session_name,
        },
    }
