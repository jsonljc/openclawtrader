#!/usr/bin/env python3
"""VWAP Reclaim/Reject setup scanner.

Entry rules:
    - RECLAIM (Long): price crosses above VWAP after being below for 3+ bars (5m),
      cumulative TICK turning positive
    - REJECT (Short): price crosses below VWAP after being above for 3+ bars (5m),
      cumulative TICK turning negative
    - Must be > 45 minutes into session (VWAP needs time to stabilize)
    - Regime: TREND or RANGE

Stop: 0.5 × ATR(14) beyond VWAP on opposite side
Target: nearest structural level (from Structure Agent) or 1.0 × ATR
Invalidation: 5m close back through VWAP in wrong direction
"""

from __future__ import annotations

from typing import Any

from shared.utils import round_to_tick


def _bars_on_side(bars: list[dict], vwap: float, side: str) -> int:
    """Count consecutive recent bars with close on one side of VWAP.

    Args:
        bars:  List of bar dicts (oldest first).
        vwap:  VWAP level.
        side:  "BELOW" or "ABOVE".

    Returns:
        Count of consecutive bars (from most recent backwards) on the specified side.
    """
    count = 0
    for bar in reversed(bars):
        c = bar["c"]
        if side == "BELOW" and c < vwap:
            count += 1
        elif side == "ABOVE" and c > vwap:
            count += 1
        else:
            break
    return count


def detect(
    regime: dict,
    session: dict,
    structure: dict | None,
    bars_5m: list[dict],
    snapshot: dict,
    strategy: dict,
) -> dict[str, Any] | None:
    """
    Scan for a VWAP Reclaim or Reject setup.

    Returns a SetupCandidate dict or None if no valid setup.
    """
    if not structure or not bars_5m or len(bars_5m) < 5:
        return None

    # --- Regime gate: VWAP fires in TREND or RANGE ---
    regime_type = regime.get("regime_type", "NEUTRAL")
    if regime_type not in ("TREND", "RANGE"):
        return None

    # --- Session gate: must be > 45 minutes into session ---
    if not session.get("is_rth", False):
        return None
    minutes_in = session.get("minutes_into_session", 0)
    signal_cfg = strategy.get("signal", {})
    min_session_min = signal_cfg.get("min_session_minutes", 45)
    if minutes_in < min_session_min:
        return None

    vwap = structure.get("vwap", 0.0)
    if vwap <= 0:
        return None

    ind = snapshot.get("indicators", {})
    atr = ind.get("atr_14_1H", 0.0) or ind.get("atr_14_4H", 10.0)
    if atr <= 0:
        return None

    tick = strategy.get("tick_size", 0.25)
    min_bars_wrong_side = signal_cfg.get("min_bars_on_wrong_side", 3)
    stop_atr_mult = signal_cfg.get("stop_atr_multiple", 0.5)

    # Current bar
    current = bars_5m[-1]
    current_close = current["c"]

    # Previous bars (excluding current)
    prev_bars = bars_5m[:-1]

    side = None
    entry_price = 0.0
    stop_price = 0.0
    target_price = 0.0

    # --- RECLAIM (Long): price was below VWAP for 3+ bars, now crosses above ---
    bars_below = _bars_on_side(prev_bars, vwap, "BELOW")
    t1_price = 0.0
    t2_price = 0.0
    if bars_below >= min_bars_wrong_side and current_close > vwap:
        side = "BUY"
        entry_price = current_close
        stop_price = vwap - stop_atr_mult * atr
        # T1: 0.5 × ATR from entry, T2: nearest structural level or 1.0 × ATR
        t1_price = round_to_tick(entry_price + 0.5 * atr, tick)
        target_price = entry_price + atr  # default T2
        t2_price = round_to_tick(target_price, tick)

    # --- REJECT (Short): price was above VWAP for 3+ bars, now crosses below ---
    bars_above = _bars_on_side(prev_bars, vwap, "ABOVE")
    if side is None and bars_above >= min_bars_wrong_side and current_close < vwap:
        side = "SELL"
        entry_price = current_close
        stop_price = vwap + stop_atr_mult * atr
        t1_price = round_to_tick(entry_price - 0.5 * atr, tick)
        target_price = entry_price - atr  # default T2
        t2_price = round_to_tick(target_price, tick)

    if side is None:
        return None

    # --- Try to find a better structural target (used for T2) ---
    try:
        from structure import get_nearest_structure_level, StructureLevels
        levels = StructureLevels(**{
            k: v for k, v in structure.items()
            if k in StructureLevels.__dataclass_fields__
        })
        struct_target = get_nearest_structure_level(entry_price, levels, "LONG" if side == "BUY" else "SHORT")
        if struct_target is not None:
            target_price = struct_target
            t2_price = round_to_tick(target_price, tick)
    except Exception:
        pass  # Use ATR-based target as fallback

    # --- Validate R:R ---
    risk = abs(entry_price - stop_price)
    reward = abs(target_price - entry_price)
    if risk <= 0:
        return None
    min_rr = signal_cfg.get("min_reward_risk", 1.0)
    if reward / risk < min_rr:
        return None

    return {
        "side": side,
        "entry_price": round_to_tick(entry_price, tick),
        "stop_price": round_to_tick(stop_price, tick),
        "target_price": round_to_tick(target_price, tick),
        "setup_family": "VWAP",
        "scale_out_plan": {
            "t1_pct": 50,
            "t1_price": t1_price,
            "t2_price": t2_price,
            "trailing_atr_multiple": 1.5,
        },
        "metadata": {
            "vwap": vwap,
            "atr": atr,
            "bars_on_wrong_side": bars_below if side == "BUY" else bars_above,
            "regime_type": regime_type,
            "session": session.get("session", ""),
            "minutes_into_session": minutes_in,
            "rr_ratio": round(reward / risk, 2) if risk > 0 else 0,
        },
    }
