#!/usr/bin/env python3
"""IB market data adapter — fetches real-time data from Interactive Brokers.

Implements get_all_snapshots() returning the exact same schema as data_stub.py
so every downstream consumer (brain, sentinel, forge, watchtower, run_eod)
works identically.

Data flow:
    IB Gateway → raw OHLCV bars → indicators.py computation → snapshot dict

Env:
    OPENCLAW_DATA (default: ~/openclaw-trader/data) — used for VIX cache

Caching:
    VIX 252-day history is expensive to fetch — cached for 24 hours in
    $OPENCLAW_DATA/vix_cache.json.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "workspace-forge"))

from data_stub import get_session_state
import indicators

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# IB contract helpers
# ---------------------------------------------------------------------------

def _make_futures_contract(symbol: str):
    """Create an IB Future contract for ES or NQ (front month, auto-resolved)."""
    from ib_insync import Future
    return Future(symbol, exchange="CME", currency="USD")


def _make_vix_index():
    """Create an IB Index contract for VIX."""
    from ib_insync import Index
    return Index("VIX", exchange="CBOE", currency="USD")


# ---------------------------------------------------------------------------
# VIX percentile cache
# ---------------------------------------------------------------------------

def _vix_cache_path() -> Path:
    data_dir = Path(os.environ.get("OPENCLAW_DATA", str(Path.home() / "openclaw-trader" / "data")))
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "vix_cache.json"


def _load_vix_cache() -> dict | None:
    """Load VIX percentile cache if fresh (< 24 hours)."""
    path = _vix_cache_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        cached_at = datetime.fromisoformat(data["cached_at"])
        age = (datetime.now(timezone.utc) - cached_at).total_seconds()
        if age < 86400:  # 24 hours
            return data
    except Exception:
        pass
    return None


def _save_vix_cache(vix: float, percentile: float) -> None:
    """Save VIX + percentile to cache."""
    try:
        path = _vix_cache_path()
        data = {
            "vix": vix,
            "vix_percentile_252d": percentile,
            "cached_at": datetime.now(timezone.utc).isoformat(),
        }
        path.write_text(json.dumps(data, indent=2))
    except Exception as exc:
        logger.warning("Failed to save VIX cache: %s", exc)


# ---------------------------------------------------------------------------
# Bar fetching
# ---------------------------------------------------------------------------

def _fetch_bars(ib, contract, bar_size: str, duration: str) -> list[dict]:
    """Fetch historical bars from IB and convert to snapshot bar format.

    Args:
        ib:        Connected IB instance.
        contract:  IB contract.
        bar_size:  e.g. '15 mins', '1 hour', '4 hours'
        duration:  e.g. '1 H', '8 H', '2 D'

    Returns:
        List of bar dicts: [{t, o, h, l, c, v}, ...]
    """
    bars = ib.reqHistoricalData(
        contract,
        endDateTime="",
        durationStr=duration,
        barSizeSetting=bar_size,
        whatToShow="TRADES",
        useRTH=False,
        formatDate=1,
    )
    ib.sleep(0)  # Allow event loop to process

    result = []
    for b in bars:
        result.append({
            "t": b.date.strftime("%Y-%m-%dT%H:%M:00Z") if hasattr(b.date, "strftime")
                 else str(b.date),
            "o": float(b.open),
            "h": float(b.high),
            "l": float(b.low),
            "c": float(b.close),
            "v": int(b.volume) if b.volume >= 0 else 0,
        })
    return result


# ---------------------------------------------------------------------------
# Microstructure (bid/ask, depth)
# ---------------------------------------------------------------------------

def _fetch_microstructure(ib, contract) -> dict:
    """Fetch Level 1 bid/ask and top-of-book depth."""
    spread_ticks = 1
    spread_bps = 0.0
    book_depth = 850
    baseline_depth = 850

    try:
        # Request market data for bid/ask
        ib.reqMktData(contract, "", False, False)
        ib.sleep(2)  # Wait for data

        ticker = ib.ticker(contract)
        if ticker and ticker.bid and ticker.ask and ticker.bid > 0:
            tick_size = 0.25  # ES/NQ standard tick
            spread_pts = ticker.ask - ticker.bid
            spread_ticks = max(1, round(spread_pts / tick_size))
            mid = (ticker.bid + ticker.ask) / 2.0
            spread_bps = round(spread_pts / mid * 10000, 2) if mid > 0 else 0.0

        # Request market depth (top 5 levels)
        ib.reqMktDepth(contract, numRows=5)
        ib.sleep(2)

        dom = ib.ticker(contract)
        if dom and dom.domBids and dom.domAsks:
            total_size = sum(d.size for d in dom.domBids[:5]) + sum(d.size for d in dom.domAsks[:5])
            book_depth = int(total_size / 2) if total_size > 0 else 850

        # Clean up subscriptions
        ib.cancelMktData(contract)
        ib.cancelMktDepth(contract)
    except Exception as exc:
        logger.warning("Microstructure fetch failed for %s: %s", contract.symbol, exc)

    return {
        "spread_ticks": spread_ticks,
        "spread_bps": spread_bps,
        "avg_book_depth_contracts": book_depth,
        "avg_book_depth_baseline": baseline_depth,
    }


# ---------------------------------------------------------------------------
# VIX data
# ---------------------------------------------------------------------------

def _fetch_vix(ib) -> dict:
    """Fetch current VIX and 252-day percentile."""
    cache = _load_vix_cache()

    vix_value = 18.0  # fallback
    vix_percentile = 0.5  # fallback

    try:
        vix_contract = _make_vix_index()

        # Current VIX value
        ib.reqMktData(vix_contract, "", False, False)
        ib.sleep(2)
        ticker = ib.ticker(vix_contract)
        if ticker and ticker.last and ticker.last > 0:
            vix_value = round(float(ticker.last), 2)
        elif ticker and ticker.close and ticker.close > 0:
            vix_value = round(float(ticker.close), 2)
        ib.cancelMktData(vix_contract)

        # 252-day percentile (use cache if available)
        if cache and abs(cache.get("vix", 0) - vix_value) < 5:
            vix_percentile = cache["vix_percentile_252d"]
        else:
            # Fetch 1 year of daily VIX closes
            vix_bars = ib.reqHistoricalData(
                vix_contract,
                endDateTime="",
                durationStr="1 Y",
                barSizeSetting="1 day",
                whatToShow="TRADES",
                useRTH=True,
                formatDate=1,
            )
            ib.sleep(0)

            if vix_bars and len(vix_bars) > 20:
                closes = [float(b.close) for b in vix_bars]
                # Percentile: fraction of historical closes below current VIX
                below = sum(1 for c in closes if c < vix_value)
                vix_percentile = round(below / len(closes), 4)

            _save_vix_cache(vix_value, vix_percentile)

    except Exception as exc:
        logger.warning("VIX fetch failed: %s", exc)
        if cache:
            vix_value = cache.get("vix", vix_value)
            vix_percentile = cache.get("vix_percentile_252d", vix_percentile)

    return {
        "vix": vix_value,
        "vix_percentile_252d": vix_percentile,
        "funding_rate": None,
    }


# ---------------------------------------------------------------------------
# Contract details (expiry)
# ---------------------------------------------------------------------------

def _fetch_contract_info(ib, contract) -> dict:
    """Fetch contract details for days-to-expiry calculation."""
    days_to_expiry = 90  # fallback
    try:
        details_list = ib.reqContractDetails(contract)
        ib.sleep(0)
        if details_list:
            # Use the first (front-month) contract
            detail = details_list[0]
            expiry_str = detail.contract.lastTradeDateOrContractMonth
            if expiry_str:
                expiry_date = datetime.strptime(expiry_str, "%Y%m%d").replace(tzinfo=timezone.utc)
                days_to_expiry = max(1, (expiry_date - datetime.now(timezone.utc)).days)
    except Exception as exc:
        logger.warning("Contract details fetch failed: %s", exc)

    return {
        "days_to_expiry": days_to_expiry,
        "is_front_month": True,
    }


# ---------------------------------------------------------------------------
# Compute indicators from bars
# ---------------------------------------------------------------------------

def _compute_indicators(
    bars_1h: list[dict],
    bars_4h: list[dict],
) -> dict:
    """Compute all technical indicators from raw bars."""
    # Extract OHLC arrays from 4H bars
    closes_4h = [b["c"] for b in bars_4h]
    highs_4h = [b["h"] for b in bars_4h]
    lows_4h = [b["l"] for b in bars_4h]

    # Extract from 1H bars
    closes_1h = [b["c"] for b in bars_1h]
    highs_1h = [b["h"] for b in bars_1h]
    lows_1h = [b["l"] for b in bars_1h]

    last_price = closes_4h[-1] if closes_4h else 0.0

    # SMA(20) and SMA(50) on 4H closes
    ma_20 = indicators.sma(closes_4h, 20)
    ma_50 = indicators.sma(closes_4h, 50)

    # MA20 slope: compute SMA(20) for last 5 points, then regress
    ma_20_series: list[float] = []
    for i in range(max(0, len(closes_4h) - 5), len(closes_4h)):
        window = closes_4h[:i + 1]
        ma_20_series.append(indicators.sma(window, 20))
    ma_20_slp = indicators.slope(ma_20_series, 5)
    # Normalize by price to get proportional slope
    if last_price > 0:
        ma_20_slp = round(ma_20_slp / last_price, 6)

    # ADX(14) on 4H
    adx_val = indicators.adx(highs_4h, lows_4h, closes_4h, 14)

    # ATR(14) on 1H and 4H
    atr_1h = indicators.atr(highs_1h, lows_1h, closes_1h, 14)
    atr_4h = indicators.atr(highs_4h, lows_4h, closes_4h, 14)

    return {
        "last_price": round(last_price, 2),
        "atr_14_1H": atr_1h,
        "atr_14_4H": atr_4h,
        "adx_14": adx_val,
        "ma_20_slope": ma_20_slp,
        "ma_20_value": round(ma_20, 2),
        "ma_50_value": round(ma_50, 2),
    }


# ---------------------------------------------------------------------------
# Data quality assessment
# ---------------------------------------------------------------------------

def _assess_data_quality(
    bars_1h: list[dict],
    bars_4h: list[dict],
) -> dict:
    """Evaluate data completeness and freshness."""
    now = datetime.now(timezone.utc)
    last_bar_age_sec = 999

    # Try to parse the most recent bar timestamp
    if bars_1h:
        try:
            last_ts_str = bars_1h[-1]["t"]
            if last_ts_str.endswith("Z"):
                last_ts_str = last_ts_str[:-1] + "+00:00"
            last_ts = datetime.fromisoformat(last_ts_str)
            last_bar_age_sec = int((now - last_ts).total_seconds())
        except Exception:
            pass

    is_stale = last_bar_age_sec > 900

    return {
        "bars_expected_1H": 24,
        "bars_received_1H": len(bars_1h),
        "bars_expected_4H": 6,
        "bars_received_4H": len(bars_4h),
        "last_bar_age_sec": last_bar_age_sec,
        "is_stale": is_stale,
        "data_source": "ib",
    }


# ---------------------------------------------------------------------------
# Single-symbol snapshot
# ---------------------------------------------------------------------------

def get_market_snapshot(
    ib,
    symbol: str,
    force_signal: bool = False,
) -> dict[str, Any]:
    """
    Fetch a complete market snapshot from IB for one symbol.
    Schema matches data_stub.get_market_snapshot() exactly.

    Args:
        ib:           Connected ib_insync.IB instance.
        symbol:       "ES" or "NQ".
        force_signal: Ignored for IB (real data doesn't support forcing).

    Returns:
        MarketSnapshot dict.
    """
    now = datetime.now(timezone.utc)
    contract = _make_futures_contract(symbol)

    # Qualify the contract so IB resolves to the front-month
    qualified = ib.qualifyContracts(contract)
    if qualified:
        contract = qualified[0]

    # Fetch bars at multiple timeframes
    bars_5m = _fetch_bars(ib, contract, "5 mins", "1 D")
    bars_15m = _fetch_bars(ib, contract, "15 mins", "1 H")
    bars_1h = _fetch_bars(ib, contract, "1 hour", "2 D")
    bars_4h = _fetch_bars(ib, contract, "4 hours", "10 D")

    # Compute indicators from bars
    ind = _compute_indicators(bars_1h, bars_4h)

    # Microstructure
    micro = _fetch_microstructure(ib, contract)

    # VIX
    external = _fetch_vix(ib)

    # Contract info
    contract_info = _fetch_contract_info(ib, contract)

    # Session state (reuse production-ready DST logic from data_stub)
    session = get_session_state(now)

    # Data quality
    dq = _assess_data_quality(bars_1h, bars_4h)

    snap_id = f"MS_{now.strftime('%Y%m%d_%H%M')}"

    return {
        "snapshot_id": snap_id,
        "asof": now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        "symbol": symbol,
        "session_state": session,
        "bars": {
            "5m": bars_5m,
            "15m": bars_15m,
            "1H": bars_1h,
            "4H": bars_4h,
        },
        "indicators": ind,
        "microstructure": micro,
        "external": external,
        "contract": contract_info,
        "data_quality": dq,
    }


# ---------------------------------------------------------------------------
# Multi-symbol entry point (matches data_stub.get_all_snapshots signature)
# ---------------------------------------------------------------------------

def get_all_snapshots(force_signal: bool = False) -> dict[str, dict]:
    """
    Fetch snapshots for ES and NQ from Interactive Brokers.

    This is the drop-in replacement for data_stub.get_all_snapshots().
    On connection failure, returns None (caller should fall back to stub).

    Args:
        force_signal: Ignored for IB data (real markets can't be forced).

    Returns:
        {"ES": {snapshot}, "NQ": {snapshot}} or raises on IB error.
    """
    from ib_gateway import get_connection

    ib = get_connection()

    snapshots = {}
    for symbol in ("ES", "NQ"):
        try:
            snap = get_market_snapshot(ib, symbol, force_signal=force_signal)
            snapshots[symbol] = snap
            logger.info("IB snapshot fetched for %s", symbol)
        except Exception as exc:
            logger.error("Failed to fetch IB snapshot for %s: %s", symbol, exc)
            raise

    return snapshots
