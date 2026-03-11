#!/usr/bin/env python3
"""Structure Agent — computes intraday structural levels.

Provides:
    - Session VWAP (volume-weighted average price, rolling)
    - Opening Range (high/low of 9:30-9:45 ET)
    - Initial Balance (high/low of 9:30-10:30 ET)
    - Prior day OHLC
    - Overnight (globex) high/low
    - Gap size and direction

All pure Python. Uses existing indicators.py patterns.
Reuses data_ib.py bar format: {t, o, h, l, c, v}.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta, time as dtime
from typing import Any


from shared.utils import round_to_tick

try:
    import zoneinfo
    ET = zoneinfo.ZoneInfo("America/New_York")
except ImportError:
    ET = timezone(timedelta(hours=-5))


# ---------------------------------------------------------------------------
# Per-instrument session definitions
# ---------------------------------------------------------------------------

_STRUCTURE_SESSIONS = {
    "equity_index": {"rth": (dtime(9, 30), dtime(16, 0)),  "or_end": dtime(9, 45),  "ib_end": dtime(10, 30)},
    "energy":       {"rth": (dtime(9, 0),  dtime(14, 30)), "or_end": dtime(9, 15),  "ib_end": dtime(10, 0)},
    "metals":       {"rth": (dtime(8, 20), dtime(13, 30)), "or_end": dtime(8, 35),  "ib_end": dtime(9, 20)},
    "rates":        {"rth": (dtime(8, 20), dtime(15, 0)),  "or_end": dtime(8, 35),  "ib_end": dtime(9, 20)},
}

_SYMBOL_TO_STRUCT_GROUP: dict[str, str] = {}
for _grp, _syms in {
    "equity_index": {"ES", "NQ", "MES", "MNQ"},
    "energy":       {"CL", "MCL"},
    "metals":       {"GC", "MGC"},
    "rates":        {"ZB"},
}.items():
    for _s in _syms:
        _SYMBOL_TO_STRUCT_GROUP[_s] = _grp


def _get_session_cfg(symbol: str) -> dict:
    """Return session config for a symbol, defaulting to equity_index."""
    group = _SYMBOL_TO_STRUCT_GROUP.get(symbol, "equity_index")
    return _STRUCTURE_SESSIONS[group]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class StructureLevels:
    """All computed structural levels for the current session."""
    vwap: float = 0.0
    vwap_upper_1sd: float = 0.0
    vwap_lower_1sd: float = 0.0

    or_high: float = 0.0
    or_low: float = 0.0
    or_width: float = 0.0
    or_complete: bool = False

    ib_high: float = 0.0
    ib_low: float = 0.0
    ib_width: float = 0.0
    ib_complete: bool = False

    prior_day_open: float = 0.0
    prior_day_high: float = 0.0
    prior_day_low: float = 0.0
    prior_day_close: float = 0.0

    overnight_high: float = 0.0
    overnight_low: float = 0.0

    gap_size: float = 0.0
    gap_direction: str = "NONE"  # "UP", "DOWN", "NONE"

    def to_dict(self) -> dict[str, Any]:
        return {
            "vwap": self.vwap,
            "vwap_upper_1sd": self.vwap_upper_1sd,
            "vwap_lower_1sd": self.vwap_lower_1sd,
            "or_high": self.or_high,
            "or_low": self.or_low,
            "or_width": self.or_width,
            "or_complete": self.or_complete,
            "ib_high": self.ib_high,
            "ib_low": self.ib_low,
            "ib_width": self.ib_width,
            "ib_complete": self.ib_complete,
            "prior_day_open": self.prior_day_open,
            "prior_day_high": self.prior_day_high,
            "prior_day_low": self.prior_day_low,
            "prior_day_close": self.prior_day_close,
            "overnight_high": self.overnight_high,
            "overnight_low": self.overnight_low,
            "gap_size": self.gap_size,
            "gap_direction": self.gap_direction,
        }


# ---------------------------------------------------------------------------
# VWAP computation
# ---------------------------------------------------------------------------

@dataclass
class VWAPState:
    """Rolling VWAP accumulator for the session."""
    cum_pv: float = 0.0   # cumulative (price * volume)
    cum_vol: float = 0.0  # cumulative volume
    cum_pv2: float = 0.0  # cumulative (price^2 * volume) for std dev

    def update(self, typical_price: float, volume: float) -> None:
        self.cum_pv += typical_price * volume
        self.cum_vol += volume
        self.cum_pv2 += (typical_price ** 2) * volume

    @property
    def vwap(self) -> float:
        if self.cum_vol <= 0:
            return 0.0
        return self.cum_pv / self.cum_vol

    @property
    def std_dev(self) -> float:
        if self.cum_vol <= 0:
            return 0.0
        mean = self.vwap
        variance = (self.cum_pv2 / self.cum_vol) - (mean ** 2)
        return variance ** 0.5 if variance > 0 else 0.0


# ---------------------------------------------------------------------------
# Bar timestamp parsing
# ---------------------------------------------------------------------------

def _parse_bar_time(bar: dict) -> datetime | None:
    """Parse bar timestamp to timezone-aware datetime."""
    ts = bar.get("t", "")
    if not ts:
        return None
    try:
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


def _to_et(dt: datetime) -> datetime:
    """Convert datetime to Eastern time."""
    return dt.astimezone(ET)


def _is_rth(dt_et: datetime, symbol: str = "ES") -> bool:
    """Is this bar during Regular Trading Hours?"""
    cfg = _get_session_cfg(symbol)
    t = dt_et.time()
    rth_start, rth_end = cfg["rth"]
    return rth_start <= t < rth_end


def _is_or_period(dt_et: datetime, symbol: str = "ES") -> bool:
    """Is this bar in the Opening Range period?"""
    cfg = _get_session_cfg(symbol)
    t = dt_et.time()
    rth_start = cfg["rth"][0]
    return rth_start <= t < cfg["or_end"]


def _is_ib_period(dt_et: datetime, symbol: str = "ES") -> bool:
    """Is this bar in the Initial Balance period?"""
    cfg = _get_session_cfg(symbol)
    t = dt_et.time()
    rth_start = cfg["rth"][0]
    return rth_start <= t < cfg["ib_end"]


# ---------------------------------------------------------------------------
# Main computation
# ---------------------------------------------------------------------------

def compute_structure(
    bars_5m: list[dict],
    bars_daily: list[dict] | None = None,
    now_utc: datetime | None = None,
    symbol: str = "ES",
    tick_size: float = 0.25,
) -> StructureLevels:
    """
    Compute all structural levels from 5-minute bars.

    Args:
        bars_5m:     List of 5m bars [{t, o, h, l, c, v}, ...] covering today + overnight.
        bars_daily:  Optional daily bars for prior day OHLC. If None, inferred from 5m bars.
        now_utc:     Current UTC time. Defaults to now.
        symbol:      Instrument symbol for session time lookup.
        tick_size:   Tick size for price rounding.

    Returns:
        StructureLevels with all computed values.
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    now_et = _to_et(now_utc)
    today = now_et.date()

    levels = StructureLevels()
    vwap_state = VWAPState()

    # Separate bars into today's RTH, overnight, and prior day
    rth_bars: list[dict] = []
    overnight_bars: list[dict] = []
    prior_day_bars: list[dict] = []
    or_bars: list[dict] = []
    ib_bars: list[dict] = []

    for bar in bars_5m:
        dt = _parse_bar_time(bar)
        if dt is None:
            continue
        dt_et = _to_et(dt)
        bar_date = dt_et.date()

        if bar_date == today:
            if _is_rth(dt_et, symbol):
                rth_bars.append(bar)
                # VWAP: accumulate during RTH
                typical = (bar["h"] + bar["l"] + bar["c"]) / 3.0
                volume = bar.get("v", 0)
                if volume > 0:
                    vwap_state.update(typical, volume)

                if _is_or_period(dt_et, symbol):
                    or_bars.append(bar)
                if _is_ib_period(dt_et, symbol):
                    ib_bars.append(bar)
            else:
                # Pre-market / overnight for today
                overnight_bars.append(bar)
        elif bar_date == today - timedelta(days=1):
            if _is_rth(dt_et, symbol):
                prior_day_bars.append(bar)
            else:
                overnight_bars.append(bar)
        else:
            # Older overnight bars
            overnight_bars.append(bar)

    # --- VWAP ---
    levels.vwap = round_to_tick(vwap_state.vwap, tick_size)
    sd = vwap_state.std_dev
    levels.vwap_upper_1sd = round_to_tick(levels.vwap + sd, tick_size)
    levels.vwap_lower_1sd = round_to_tick(levels.vwap - sd, tick_size)

    # --- Opening Range ---
    if or_bars:
        levels.or_high = max(b["h"] for b in or_bars)
        levels.or_low = min(b["l"] for b in or_bars)
        levels.or_width = round_to_tick(levels.or_high - levels.or_low, tick_size)
        # OR is complete if we're past OR end time
        levels.or_complete = now_et.time() >= _get_session_cfg(symbol)["or_end"]

    # --- Initial Balance ---
    if ib_bars:
        levels.ib_high = max(b["h"] for b in ib_bars)
        levels.ib_low = min(b["l"] for b in ib_bars)
        levels.ib_width = round_to_tick(levels.ib_high - levels.ib_low, tick_size)
        levels.ib_complete = now_et.time() >= _get_session_cfg(symbol)["ib_end"]

    # --- Prior Day OHLC ---
    if bars_daily and len(bars_daily) >= 2:
        prev = bars_daily[-2]  # second to last = prior day
        levels.prior_day_open = prev.get("o", 0.0)
        levels.prior_day_high = prev.get("h", 0.0)
        levels.prior_day_low = prev.get("l", 0.0)
        levels.prior_day_close = prev.get("c", 0.0)
    elif prior_day_bars:
        levels.prior_day_open = prior_day_bars[0]["o"]
        levels.prior_day_high = max(b["h"] for b in prior_day_bars)
        levels.prior_day_low = min(b["l"] for b in prior_day_bars)
        levels.prior_day_close = prior_day_bars[-1]["c"]

    # --- Overnight (Globex) High/Low ---
    if overnight_bars:
        levels.overnight_high = max(b["h"] for b in overnight_bars)
        levels.overnight_low = min(b["l"] for b in overnight_bars)

    # --- Gap ---
    if levels.prior_day_close > 0 and rth_bars:
        today_open = rth_bars[0]["o"]
        levels.gap_size = round_to_tick(today_open - levels.prior_day_close, tick_size)
        if levels.gap_size > 0:
            levels.gap_direction = "UP"
        elif levels.gap_size < 0:
            levels.gap_direction = "DOWN"
        else:
            levels.gap_direction = "NONE"

    return levels


def get_nearest_structure_level(
    price: float,
    levels: StructureLevels,
    side: str = "LONG",
) -> float | None:
    """
    Find the nearest structural level in the trade's favor direction.

    For LONG: nearest resistance above (or_high, ib_high, overnight_high, prior_day_high)
    For SHORT: nearest support below (or_low, ib_low, overnight_low, prior_day_low)

    Returns the nearest level, or None if no valid level found.
    """
    if side == "LONG":
        candidates = [
            levels.or_high, levels.ib_high,
            levels.overnight_high, levels.prior_day_high,
            levels.vwap_upper_1sd,
        ]
        valid = [l for l in candidates if l > price and l > 0]
        return min(valid) if valid else None
    else:
        candidates = [
            levels.or_low, levels.ib_low,
            levels.overnight_low, levels.prior_day_low,
            levels.vwap_lower_1sd,
        ]
        valid = [l for l in candidates if l < price and l > 0]
        return max(valid) if valid else None
