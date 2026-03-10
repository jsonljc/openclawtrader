#!/usr/bin/env python3
"""Paper trading simulator — spec Section 8.8 / 13.1.

Stateless: all simulation functions take inputs and return results.
The portfolio state lives in state_store; this module only does math.

PRNG seeds are logged to the ledger for full reproducibility.
"""

from __future__ import annotations
import math
import random
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))
from slippage_model import estimate_slippage_ticks, limit_fill_probability
from fees_model import entry_fee_usd


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REJECT_PROBABILITY   = 0.02   # 2% random reject for resilience testing
PARTIAL_PROBABILITY  = 0.10   # 10% partial fill for orders > 3 contracts
LATENCY_MIN_MS       = 100
LATENCY_MAX_MS       = 500


# ---------------------------------------------------------------------------
# Market order fill simulation — spec 8.8
# ---------------------------------------------------------------------------

def simulate_market_fill(
    side: str,                    # "BUY" or "SELL"
    price: float,                 # Current market price
    tick_size: float,
    tick_value_usd: float,
    point_value_usd: float,
    contracts: int,
    fee_per_contract_round_trip_usd: float,
    vol_pct: float,
    session: str,
    avg_book_depth: float,
    base_ticks: int = 1,
    prng_seed: int | None = None,
    is_session_boundary: bool = False,
) -> dict[str, Any]:
    """
    Simulate a market order fill with realistic slippage, noise, partial fills,
    and random rejects.

    Returns a dict with fill details; status = "FILLED", "REJECTED", or
    "PARTIALLY_FILLED".  All PRNG seeds are returned for ledger logging.
    """
    seed = prng_seed if prng_seed is not None else int(time.time() * 1000) % 2**31
    rng = random.Random(seed)

    # --- Random reject (resilience testing) ---
    reject_roll = rng.random()
    if reject_roll < REJECT_PROBABILITY:
        return {
            "status":        "REJECTED",
            "reason":        "Simulated exchange reject (resilience test)",
            "prng_seed":     seed,
            "reject_roll":   round(reject_roll, 6),
            "fill_price":    None,
            "contracts_filled": 0,
            "slippage_ticks":   0,
            "slippage_usd":     0.0,
            "fees_usd":         0.0,
            "fill_latency_ms":  0,
        }

    # --- Partial fill simulation ---
    contracts_filled = contracts
    if contracts > 3:
        partial_roll = rng.random()
        if partial_roll < PARTIAL_PROBABILITY:
            contracts_filled = rng.randint(1, contracts - 1)

    # --- Slippage calculation ---
    slip_ticks = estimate_slippage_ticks(
        contracts=contracts_filled,
        vol_pct=vol_pct,
        session=session,
        avg_book_depth=avg_book_depth,
        base_ticks=base_ticks,
        is_session_boundary=is_session_boundary,
    )

    # Noise: +/- 1 tick (seeded for reproducibility)
    noise_ticks = rng.randint(-1, 1)
    total_ticks = max(0, slip_ticks + noise_ticks)

    # Direction: BUY slips up, SELL slips down
    direction = 1 if side.upper() == "BUY" else -1
    fill_price = price + direction * total_ticks * tick_size

    fees = entry_fee_usd(contracts_filled, fee_per_contract_round_trip_usd)
    latency_ms = rng.randint(LATENCY_MIN_MS, LATENCY_MAX_MS)
    slip_usd   = round(total_ticks * tick_value_usd * contracts_filled, 2)

    status = "PARTIALLY_FILLED" if contracts_filled < contracts else "FILLED"

    return {
        "status":           status,
        "fill_price":       round(fill_price, 4),
        "contracts_filled": contracts_filled,
        "contracts_requested": contracts,
        "slippage_ticks":   total_ticks,
        "slippage_usd":     slip_usd,
        "fees_usd":         fees,
        "fill_latency_ms":  latency_ms,
        "prng_seed":        seed,
        "noise_ticks":      noise_ticks,
        "reason":           None,
    }


# ---------------------------------------------------------------------------
# Limit order fill simulation — spec 8.8
# ---------------------------------------------------------------------------

def simulate_limit_fill(
    limit_price: float,
    mid_price: float,
    tick_size: float,
    contracts: int,
    fee_per_contract_round_trip_usd: float,
    vol_pct: float,
    max_time_to_fill_sec: int = 15,
    prng_seed: int | None = None,
) -> dict[str, Any]:
    """
    Simulate a limit order fill using fill probability model.
    Limits get the exact limit price (no adverse slippage).
    """
    seed = prng_seed if prng_seed is not None else int(time.time() * 1000) % 2**31
    rng = random.Random(seed)

    prob = limit_fill_probability(limit_price, mid_price, tick_size, vol_pct)
    roll = rng.random()

    if roll > prob:
        return {
            "status":           "TIMED_OUT",
            "fill_price":       None,
            "contracts_filled": 0,
            "slippage_ticks":   0,
            "slippage_usd":     0.0,
            "fees_usd":         0.0,
            "fill_latency_ms":  max_time_to_fill_sec * 1000,
            "fill_probability": round(prob, 4),
            "prng_seed":        seed,
            "reason":           "Limit order did not fill within time limit",
        }

    # Fill delay: modelled from fill probability
    delay_bars = math.ceil(-math.log(max(roll, 1e-9)) / max(prob, 1e-9))
    fees = entry_fee_usd(contracts, fee_per_contract_round_trip_usd)

    return {
        "status":           "FILLED",
        "fill_price":       round(limit_price, 4),
        "contracts_filled": contracts,
        "contracts_requested": contracts,
        "slippage_ticks":   0,
        "slippage_usd":     0.0,
        "fees_usd":         fees,
        "fill_latency_ms":  min(delay_bars * 1000, max_time_to_fill_sec * 1000),
        "fill_probability": round(prob, 4),
        "prng_seed":        seed,
        "reason":           None,
    }


# ---------------------------------------------------------------------------
# Bracket trigger check — spec 8.7 Invariants
# ---------------------------------------------------------------------------

def check_bracket_triggers(
    positions: list[dict],
    bars_by_symbol: dict[str, list[dict]],
    tick_size_by_symbol: dict[str, float] = None,
    atr_by_symbol: dict[str, float] = None,
) -> list[dict]:
    """
    Check all open positions against current bar data for:
      - Stop-loss / take-profit triggers (full close)
      - T1 scale-out triggers (partial close)
      - Trailing stop updates and triggers
      - Time exits (bars_held >= max_hold_bars)

    Args:
        positions:         List of position dicts from portfolio.
        bars_by_symbol:    {symbol: [bar_dict, ...]} — use 15m or 5m bars.
        tick_size_by_symbol: Optional override for tick sizes.
        atr_by_symbol:     {symbol: atr_value} for trailing stop computation.

    Returns:
        List of triggered events: [{position_id, trigger, exit_price, position, ...}]
        Events with trigger "T1" are partial closes; others are full closes.
    """
    triggered: list[dict] = []
    atr_by_symbol = atr_by_symbol or {}

    for pos in positions:
        symbol     = pos.get("symbol", "")
        side       = pos.get("side", "LONG")
        stop_price = pos.get("stop_price")
        tp_price   = pos.get("take_profit_price")
        pos_id     = pos.get("position_id")

        bracket_status = pos.get("bracket_status", {})
        stop_status = bracket_status.get("stop_status", "ACTIVE")
        tp_status   = bracket_status.get("tp_status", "ACTIVE")

        sop = pos.get("scale_out_plan") or {}
        t1_price = sop.get("t1_price")
        t2_price = sop.get("t2_price")
        t1_filled = sop.get("t1_filled", False)

        bars = bars_by_symbol.get(symbol, [])
        if not bars:
            continue

        # Increment bars_held
        pos["bars_held"] = pos.get("bars_held", 0) + 1

        # Use the most recent bar for trigger check
        bar = bars[-1]
        bar_low  = bar.get("l", bar.get("low", None))
        bar_high = bar.get("h", bar.get("high", None))
        bar_close = bar.get("c", bar.get("close", None))

        if bar_low is None or bar_high is None:
            continue

        trigger = None
        exit_price = None

        # --- Trailing stop update (runs every cycle after T1 filled) ---
        if t1_filled:
            atr_val = atr_by_symbol.get(symbol, 0.0)
            trail_mult = sop.get("trailing_atr_multiple", 1.5)
            if atr_val > 0:
                if side == "LONG":
                    new_trail = round(bar_high - (trail_mult * atr_val), 2)
                    if new_trail > (stop_price or 0):
                        pos["stop_price"] = new_trail
                        stop_price = new_trail
                        sop["trailing_stop"] = new_trail
                elif side == "SHORT":
                    new_trail = round(bar_low + (trail_mult * atr_val), 2)
                    if new_trail < (stop_price or float('inf')):
                        pos["stop_price"] = new_trail
                        stop_price = new_trail
                        sop["trailing_stop"] = new_trail

        # --- Check triggers in priority order ---
        if side == "LONG":
            # Stop hit (before T1 = full close, after T1 = trailing stop on remaining)
            if stop_status == "ACTIVE" and stop_price is not None and bar_low <= stop_price:
                if t1_filled:
                    trigger = "TRAILING_STOP"
                else:
                    trigger = "STOP"
                exit_price = stop_price
                if bar_low < stop_price:
                    bar_open = bar.get("o", bar.get("open", stop_price))
                    if bar_open < stop_price:
                        exit_price = bar_open

            # T1 check (before T2/TP)
            elif sop and t1_price is not None and not t1_filled and bar_high >= t1_price:
                trigger = "T1"
                exit_price = t1_price

            # T2 check (after T1 filled)
            elif sop and t2_price is not None and t1_filled and bar_high >= t2_price:
                trigger = "T2"
                exit_price = t2_price

            # Original TP (fallback if no scale-out plan)
            elif tp_status == "ACTIVE" and tp_price is not None and not sop and bar_high >= tp_price:
                trigger = "TAKE_PROFIT"
                exit_price = tp_price

        elif side == "SHORT":
            # Stop hit
            if stop_status == "ACTIVE" and stop_price is not None and bar_high >= stop_price:
                if t1_filled:
                    trigger = "TRAILING_STOP"
                else:
                    trigger = "STOP"
                exit_price = stop_price
                bar_open = bar.get("o", bar.get("open", stop_price))
                if bar_open > stop_price:
                    exit_price = bar_open

            # T1 check
            elif sop and t1_price is not None and not t1_filled and bar_low <= t1_price:
                trigger = "T1"
                exit_price = t1_price

            # T2 check
            elif sop and t2_price is not None and t1_filled and bar_low <= t2_price:
                trigger = "T2"
                exit_price = t2_price

            # Original TP
            elif tp_status == "ACTIVE" and tp_price is not None and not sop and bar_low <= tp_price:
                trigger = "TAKE_PROFIT"
                exit_price = tp_price

        # --- Time exit ---
        if trigger is None:
            bars_held = pos.get("bars_held", 0)
            max_hold = pos.get("max_hold_bars", 999)
            if bars_held >= max_hold:
                trigger = "TIME_EXIT"
                exit_price = bar_close

        if trigger:
            triggered.append({
                "position_id": pos_id,
                "symbol":      symbol,
                "trigger":     trigger,
                "exit_price":  exit_price,
                "bar":         bar,
                "position":    pos,
            })

    return triggered
