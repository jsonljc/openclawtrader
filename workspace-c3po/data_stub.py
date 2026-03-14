#!/usr/bin/env python3
"""Synthetic market data stub for Phase 1 paper trading.

Generates realistic ES (S&P 500 futures) snapshots with all fields
required by the spec's MarketSnapshot schema (Section 5.2).

In Phase 4 this is replaced by live data integration.
"""

from __future__ import annotations
import math
import random
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))
from shared.contracts import SessionState


# ---------------------------------------------------------------------------
# CME session detection — spec Section 11.1 / 6.9
# ---------------------------------------------------------------------------

def get_session_state(now_utc: datetime | None = None) -> str:
    """
    Return the CME equity futures session state based on US/Eastern time.
    Handles DST automatically.

    Session windows (Eastern):
        CORE:       09:30–15:45
        POST_CLOSE: 15:45–16:00
        CLOSED:     16:00–18:00
        EXTENDED:   18:00–09:15
        PRE_OPEN:   09:15–09:30
    """
    try:
        import zoneinfo
        et = zoneinfo.ZoneInfo("America/New_York")
    except ImportError:
        # Fallback: approximate Eastern offset
        et = timezone(timedelta(hours=-5))

    if now_utc is None:
        now_utc = datetime.now(timezone.utc)

    now_et = now_utc.astimezone(et)

    # Weekend: CLOSED (Sat all day, Sun before 18:00 ET)
    weekday = now_et.weekday()  # 0=Mon, 6=Sun
    if weekday == 5:  # Saturday
        return SessionState.CLOSED
    if weekday == 6:  # Sunday
        if now_et.hour < 18:
            return SessionState.CLOSED

    h, m = now_et.hour, now_et.minute
    minutes = h * 60 + m

    CORE_START       = 9 * 60 + 30   # 09:30
    POST_CLOSE_START = 15 * 60 + 45  # 15:45
    CLOSED_START     = 16 * 60       # 16:00
    EXTENDED_START   = 18 * 60       # 18:00
    PRE_OPEN_START   = 9 * 60 + 15   # 09:15

    if CORE_START <= minutes < POST_CLOSE_START:
        return SessionState.CORE
    if POST_CLOSE_START <= minutes < CLOSED_START:
        return SessionState.POST_CLOSE
    if CLOSED_START <= minutes < EXTENDED_START:
        return SessionState.CLOSED
    if minutes >= EXTENDED_START or minutes < PRE_OPEN_START:
        return SessionState.EXTENDED
    # PRE_OPEN_START <= minutes < CORE_START
    return SessionState.PRE_OPEN


# ---------------------------------------------------------------------------
# Bar generation helper
# ---------------------------------------------------------------------------

def _make_bar(ts: str, price: float, atr: float, rng: random.Random) -> dict:
    """Generate a realistic OHLCV bar around a price level."""
    half_range = atr * rng.uniform(0.3, 0.8)
    o = round(price + rng.uniform(-half_range * 0.5, half_range * 0.5), 2)
    h = round(max(o, price) + rng.uniform(0, half_range), 2)
    l = round(min(o, price) - rng.uniform(0, half_range), 2)
    c = round(price + rng.uniform(-half_range * 0.3, half_range * 0.3), 2)
    v = int(rng.uniform(80_000, 180_000))
    return {"t": ts, "o": o, "h": h, "l": l, "c": c, "v": v}


# ---------------------------------------------------------------------------
# Main snapshot generator
# ---------------------------------------------------------------------------

def get_market_snapshot(
    symbol: str = "ES",
    base_price: float = 5_060.0,
    seed: int | None = None,
    force_signal: bool = False,
    session_override: str | None = None,
) -> dict[str, Any]:
    """
    Generate a synthetic MarketSnapshot conforming to spec 5.2.

    Args:
        symbol:          Instrument symbol.
        base_price:      Approximate current price level.
        seed:            PRNG seed for reproducible data.
        force_signal:    If True, force the signal conditions to be met.
        session_override: Override the session state detection.

    Returns:
        Full MarketSnapshot dict.
    """
    now = datetime.now(timezone.utc)
    if seed is None:
        seed = int(now.timestamp()) // 900  # Changes every 15 min

    rng = random.Random(seed)

    # Per-instrument price drift and ATR ranges
    _INSTRUMENT_PARAMS = {
        "ES": {"drift": 30, "atr_1h": (10.0, 18.0), "tick": 0.25, "round_dp": 2},
        "NQ": {"drift": 120, "atr_1h": (40.0, 70.0), "tick": 0.25, "round_dp": 2},
        "CL": {"drift": 3, "atr_1h": (0.30, 0.60), "tick": 0.01, "round_dp": 2},
        "GC": {"drift": 30, "atr_1h": (5.0, 12.0), "tick": 0.10, "round_dp": 2},
        "ZB": {"drift": 2, "atr_1h": (0.25, 0.50), "tick": 0.03125, "round_dp": 5},
    }
    ip = _INSTRUMENT_PARAMS.get(symbol, _INSTRUMENT_PARAMS["ES"])

    # Price drift: small random walk around base_price
    price = round(base_price + rng.uniform(-ip["drift"], ip["drift"]), ip["round_dp"])
    atr_1h = round(rng.uniform(*ip["atr_1h"]), 4)
    atr_4h = round(atr_1h * rng.uniform(2.5, 3.5), 4)

    session = session_override or get_session_state(now)

    # --- Trend indicators ---
    # MA20 below price → bullish setup (price reclaim above MA20)
    if force_signal:
        ma20 = round(price - rng.uniform(5, 15), 2)  # price above MA20
        adx = round(rng.uniform(26, 40), 1)           # ADX > 25
        ma_slope = round(rng.uniform(0.001, 0.003), 4)
    else:
        ma20 = round(price + rng.uniform(-20, 20), 2)
        adx = round(rng.uniform(15, 35), 1)
        ma_slope = round(rng.uniform(-0.002, 0.002), 4)
    ma50 = round(ma20 - rng.uniform(10, 30), 2)

    # --- VIX & vol percentile ---
    vix = round(rng.uniform(14.0, 25.0), 1)
    vix_pct = round(min(1.0, max(0.0, (vix - 10) / 30)), 4)

    # --- Book ---
    baseline_depth = 850
    book_depth = int(baseline_depth * rng.uniform(0.7, 1.3))
    spread_ticks = rng.choice([1, 1, 1, 2, 2])
    spread_bps = round(spread_ticks * ip["tick"] / price * 10000, 2)

    # --- Contract expiry ---
    days_to_expiry = max(1, (datetime(2026, 6, 20, tzinfo=timezone.utc) - now).days)

    # --- Bar timestamp helpers ---
    def bar_ts(delta_hours: int) -> str:
        t = now - timedelta(hours=delta_hours)
        t = t.replace(minute=0, second=0, microsecond=0)
        return t.strftime("%Y-%m-%dT%H:%M:00Z")

    def bar_ts_15m(delta_quarters: int) -> str:
        slot = now.minute // 15
        t = now.replace(minute=slot * 15, second=0, microsecond=0) - timedelta(minutes=15 * delta_quarters)
        return t.strftime("%Y-%m-%dT%H:%M:00Z")

    # 5-minute bar timestamp helper — when force_signal, place bars during RTH
    # so structure.py can compute OR/IB/VWAP levels properly.
    if force_signal:
        # Simulate bars starting at 09:30 ET today, every 5 min for 4 hours
        try:
            import zoneinfo as _zi
            _et = _zi.ZoneInfo("America/New_York")
        except ImportError:
            _et = timezone(timedelta(hours=-5))
        rth_start = datetime(now.year, now.month, now.day, 9, 30, tzinfo=_et)
        def bar_ts_5m(delta_5min: int) -> str:
            # delta_5min counts backward from most recent (bar 0 = 4h after open)
            bar_idx = 47 - delta_5min  # 0..47, where 47 is most recent
            t = rth_start + timedelta(minutes=5 * bar_idx)
            return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:00Z")
    else:
        def bar_ts_5m(delta_5min: int) -> str:
            slot = now.minute // 5
            t = now.replace(minute=slot * 5, second=0, microsecond=0) - timedelta(minutes=5 * delta_5min)
            return t.strftime("%Y-%m-%dT%H:%M:00Z")

    # Daily bar timestamp helper
    def bar_ts_1d(delta_days: int) -> str:
        t = now - timedelta(days=delta_days)
        return t.strftime("%Y-%m-%dT00:00:00Z")

    # Generate bars: 6× 1H, 4× 4H, 4× 15m, 48× 5m (4 hours), 5× 1D
    bars_1h = [_make_bar(bar_ts(i), price + rng.uniform(-atr_1h, atr_1h), atr_1h, rng)
               for i in range(5, -1, -1)]
    bars_4h = [_make_bar(bar_ts(i * 4), price + rng.uniform(-atr_4h, atr_4h), atr_4h, rng)
               for i in range(3, -1, -1)]
    bars_15m = [_make_bar(bar_ts_15m(i), price + rng.uniform(-atr_1h * 0.4, atr_1h * 0.4), atr_1h * 0.35, rng)
                for i in range(3, -1, -1)]
    bars_5m = [_make_bar(bar_ts_5m(i), price + rng.uniform(-atr_1h * 0.25, atr_1h * 0.25), atr_1h * 0.2, rng)
               for i in range(47, -1, -1)]
    bars_1d = [_make_bar(bar_ts_1d(i), price + rng.uniform(-atr_4h * 1.5, atr_4h * 1.5), atr_4h * 1.2, rng)
               for i in range(4, -1, -1)]

    # Latest close aligns with price
    bars_1h[-1]["c"]  = price
    bars_15m[-1]["c"] = price
    bars_5m[-1]["c"]  = price
    bars_1d[-1]["c"]  = price

    snap_id = f"MS_{now.strftime('%Y%m%d_%H%M')}"

    return {
        "snapshot_id":   snap_id,
        "asof":          now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        "symbol":        symbol,
        "session_state": session,
        "bars": {
            "5m":  bars_5m,
            "15m": bars_15m,
            "1H":  bars_1h,
            "4H":  bars_4h,
            "1D":  bars_1d,
        },
        "indicators": {
            "last_price":     price,
            "atr_14_1H":      atr_1h,
            "atr_14_4H":      atr_4h,
            "adx_14":         adx,
            "ma_20_slope":    ma_slope,
            "ma_20_value":    ma20,
            "ma_50_value":    ma50,
        },
        "microstructure": {
            "spread_ticks":              spread_ticks,
            "spread_bps":                spread_bps,
            "avg_book_depth_contracts":  book_depth,
            "avg_book_depth_baseline":   baseline_depth,
        },
        "external": {
            "vix":                vix,
            "vix_percentile_252d": vix_pct,
            "funding_rate":       None,
        },
        "contract": {
            "days_to_expiry": days_to_expiry,
            "is_front_month": True,
        },
        "data_quality": {
            "bars_expected_1H": 24,
            "bars_received_1H": 6,
            "bars_expected_4H": 6,
            "bars_received_4H": 4,
            "last_bar_age_sec": rng.randint(1, 30),
            "is_stale":         False,
        },
    }


def get_all_snapshots(force_signal: bool = False) -> dict[str, dict]:
    """Return snapshots for all active symbols (ES, NQ, CL, GC, ZB)."""
    session_override = SessionState.CORE if force_signal else None
    return {
        "ES": get_market_snapshot(
            "ES",
            base_price=5_060.0,
            force_signal=force_signal,
            session_override=session_override,
        ),
        "NQ": get_market_snapshot(
            "NQ",
            base_price=21_000.0,
            force_signal=force_signal,
            session_override=session_override,
        ),
        "CL": get_market_snapshot(
            "CL",
            base_price=75.0,
            force_signal=force_signal,
            session_override=session_override,
        ),
        "GC": get_market_snapshot(
            "GC",
            base_price=2_700.0,
            force_signal=force_signal,
            session_override=session_override,
        ),
        "ZB": get_market_snapshot(
            "ZB",
            base_price=120.0,
            force_signal=force_signal,
            session_override=session_override,
        ),
    }
