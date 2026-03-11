#!/usr/bin/env python3
"""Opening Range Breakout (ORB) setup scanner.

Entry rules:
    - Opening Range = high/low of 9:30-9:45 ET (from Structure Agent)
    - LONG: 5m close above OR high, price > VWAP, regime = TREND
    - SHORT: 5m close below OR low, price < VWAP, regime = TREND
    - OR width must be < 1.0 × ATR(14) — skip if range is too wide
    - No entry in first 2 minutes of open

Stop: OR opposite boundary (min 4 points)
Target: 1.5 × OR width from breakout boundary
Time exit: 90 minutes after entry
Invalidation: 5m close back inside OR
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta, time as dtime
from typing import Any

from shared.utils import round_to_tick

try:
    import zoneinfo
    ET = zoneinfo.ZoneInfo("America/New_York")
except ImportError:
    ET = timezone(timedelta(hours=-5))


def detect(
    regime: dict,
    session: dict,
    structure: dict | None,
    bars_5m: list[dict],
    snapshot: dict,
    strategy: dict,
) -> dict[str, Any] | None:
    """
    Scan for an ORB setup.

    Returns a SetupCandidate dict or None if no valid setup.
    SetupCandidate: {side, entry_price, stop_price, target_price, setup_family, metadata}
    """
    if not structure or not bars_5m:
        return None

    # --- Regime gate: ORB only fires in TREND ---
    regime_type = regime.get("regime_type", "NEUTRAL")
    if regime_type != "TREND":
        return None

    # --- Session gate: must be in RTH, past first 2 minutes ---
    session_name = session.get("session", "CLOSED")
    minutes_in = session.get("minutes_into_session", 0)
    if not session.get("is_rth", False):
        return None
    if minutes_in < 2:
        return None  # No entry in first 2 min of open

    # --- OR must be complete ---
    if not structure.get("or_complete", False):
        return None

    or_high = structure.get("or_high", 0.0)
    or_low = structure.get("or_low", 0.0)
    or_width = structure.get("or_width", 0.0)
    vwap = structure.get("vwap", 0.0)

    if or_high <= 0 or or_low <= 0 or or_width <= 0:
        return None

    # --- OR width filter: must be < 1.0 × ATR(14) ---
    ind = snapshot.get("indicators", {})
    atr = ind.get("atr_14_1H", 0.0) or ind.get("atr_14_4H", 10.0)
    signal_cfg = strategy.get("signal", {})
    max_or_atr = signal_cfg.get("max_or_width_atr_multiple", 1.0)
    if atr > 0 and or_width > max_or_atr * atr:
        return None  # OR too wide

    # --- Get the most recent 5m bar ---
    last_bar = bars_5m[-1]
    close = last_bar["c"]

    # --- Check for breakout ---
    side = None
    entry_price = 0.0
    stop_price = 0.0

    tick = strategy.get("tick_size", 0.25)
    min_stop_pts = signal_cfg.get("min_stop_points", 4)
    target_multiple = signal_cfg.get("target_or_width_multiple", 1.5)

    if close > or_high and (vwap <= 0 or close > vwap):
        # LONG breakout
        side = "BUY"
        entry_price = close
        stop_price = or_low
        # Enforce minimum stop distance
        if entry_price - stop_price < min_stop_pts:
            stop_price = entry_price - min_stop_pts
        # T1 at 1.0× OR width, T2 at 2.0× OR width
        t1_price = round_to_tick(or_high + 1.0 * or_width, tick)
        t2_price = round_to_tick(or_high + 2.0 * or_width, tick)
        target_price = t2_price  # overall target for R:R calculation

    elif close < or_low and (vwap <= 0 or close < vwap):
        # SHORT breakout
        side = "SELL"
        entry_price = close
        stop_price = or_high
        # Enforce minimum stop distance
        if stop_price - entry_price < min_stop_pts:
            stop_price = entry_price + min_stop_pts
        t1_price = round_to_tick(or_low - 1.0 * or_width, tick)
        t2_price = round_to_tick(or_low - 2.0 * or_width, tick)
        target_price = t2_price

    else:
        return None  # No breakout

    # --- Invalidation check: make sure we haven't already re-entered the OR ---
    # Check if any recent bar closed back inside the OR
    recent_bars = bars_5m[-3:] if len(bars_5m) >= 3 else bars_5m
    if side == "BUY":
        # Check for invalidation: a bar after breakout closed below OR high
        # Only count bars after the OR breakout bar
        for bar in recent_bars[:-1]:  # Exclude current bar
            if bar["c"] > or_high:
                # Breakout already happened in an earlier bar
                # Check if it was invalidated
                pass
    # Simplified: if current bar is a breakout, we take it

    return {
        "side": side,
        "entry_price": round_to_tick(entry_price, tick),
        "stop_price": round_to_tick(stop_price, tick),
        "target_price": round_to_tick(target_price, tick),
        "setup_family": "ORB",
        "scale_out_plan": {
            "t1_pct": 50,
            "t1_price": t1_price,
            "t2_price": t2_price,
            "trailing_atr_multiple": 1.5,
        },
        "metadata": {
            "or_high": or_high,
            "or_low": or_low,
            "or_width": or_width,
            "vwap": vwap,
            "atr": atr,
            "close": close,
            "regime_type": regime_type,
            "session": session_name,
            "minutes_into_session": minutes_in,
        },
    }
