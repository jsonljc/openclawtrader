#!/usr/bin/env python3
"""Intraday Regime Classifier — 3-type regime detection.

Classifies the current intraday environment into one of:
    TREND    — directional movement, ADX > 25, price far from VWAP
    RANGE    — mean-reverting, narrow IB, price oscillating around VWAP
    NEUTRAL  — ambiguous, neither clearly trending nor ranging

Each regime type has an aggression modifier that multiplies sizing.
Regime is re-classified every 15 minutes during the intraday loop.

Uses weighted scoring with existing indicators (ADX, ATR, VWAP)
following the same sigmoid pattern as regime.py.
"""

from __future__ import annotations

import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))
from shared import state_store as store

import indicators


# ---------------------------------------------------------------------------
# Regime types
# ---------------------------------------------------------------------------

class IntradayRegime:
    TREND   = "TREND"
    RANGE   = "RANGE"
    NEUTRAL = "NEUTRAL"


# Aggression modifiers per regime
REGIME_MODIFIERS: dict[str, float] = {
    IntradayRegime.TREND:   1.1,
    IntradayRegime.RANGE:   0.8,
    IntradayRegime.NEUTRAL: 0.5,
}

# Setup compatibility matrix
# Maps (setup_family, regime_type) → allowed
REGIME_SETUP_COMPAT: dict[tuple[str, str], bool] = {
    ("ORB",              IntradayRegime.TREND):   True,
    ("ORB",              IntradayRegime.RANGE):   False,
    ("ORB",              IntradayRegime.NEUTRAL): False,
    ("VWAP",             IntradayRegime.TREND):   True,
    ("VWAP",             IntradayRegime.RANGE):   True,
    ("VWAP",             IntradayRegime.NEUTRAL): False,
    ("TREND_PULLBACK",   IntradayRegime.TREND):   True,
    ("TREND_PULLBACK",   IntradayRegime.RANGE):   False,
    ("TREND_PULLBACK",   IntradayRegime.NEUTRAL): False,
}


def is_setup_compatible(setup_family: str, regime_type: str) -> bool:
    """Check if a setup family is allowed in the given regime."""
    return REGIME_SETUP_COMPAT.get((setup_family, regime_type), False)


# ---------------------------------------------------------------------------
# Scoring functions
# ---------------------------------------------------------------------------

def _trend_signal(snapshot: dict, structure: dict) -> tuple[float, dict]:
    """
    TREND detection score (0-1).
    High ADX + price far from VWAP + directional TICK → trending.
    """
    ind = snapshot.get("indicators", {})
    adx = ind.get("adx_14", 20.0)
    last_price = ind.get("last_price", 0.0)
    atr = ind.get("atr_14_1H", 0.0) or ind.get("atr_14_4H", 10.0)

    vwap = structure.get("vwap", last_price) if structure else last_price

    # ADX score: > 25 = trending, > 40 = strong trend
    adx_score = min(1.0, max(0.0, (adx - 15) / 35.0))

    # Distance from VWAP in ATR units
    vwap_dist = abs(last_price - vwap) / atr if atr > 0 else 0.0
    vwap_score = min(1.0, vwap_dist / 2.0)  # 1 ATR from VWAP = 0.5, 2+ ATR = 1.0

    # MA slope as directional confirmation
    ma_slope = ind.get("ma_20_slope", 0.0)
    slope_score = min(1.0, abs(ma_slope) * 500)  # Normalized

    # Weighted trend score
    raw = 0.50 * adx_score + 0.30 * vwap_score + 0.20 * slope_score
    raw = max(0.0, min(1.0, raw))

    detail = {
        "adx": adx, "adx_score": round(adx_score, 3),
        "vwap_dist_atr": round(vwap_dist, 3), "vwap_score": round(vwap_score, 3),
        "ma_slope": ma_slope, "slope_score": round(slope_score, 3),
    }
    return raw, detail


def _range_signal(snapshot: dict, structure: dict) -> tuple[float, dict]:
    """
    RANGE detection score (0-1).
    Low ADX + narrow IB + price near VWAP → ranging.
    """
    ind = snapshot.get("indicators", {})
    adx = ind.get("adx_14", 20.0)
    last_price = ind.get("last_price", 0.0)
    atr = ind.get("atr_14_1H", 0.0) or ind.get("atr_14_4H", 10.0)

    vwap = structure.get("vwap", last_price) if structure else last_price
    ib_width = structure.get("ib_width", 0.0) if structure else 0.0

    # Low ADX score: ADX < 20 = strong range signal
    low_adx_score = max(0.0, min(1.0, (30 - adx) / 20.0))

    # Narrow IB relative to ATR: IB < 0.7 ATR = range day
    ib_ratio = ib_width / atr if atr > 0 else 1.0
    narrow_ib_score = max(0.0, min(1.0, (1.0 - ib_ratio) / 0.5))

    # Price near VWAP
    vwap_dist = abs(last_price - vwap) / atr if atr > 0 else 0.0
    near_vwap_score = max(0.0, min(1.0, 1.0 - vwap_dist))

    raw = 0.40 * low_adx_score + 0.30 * narrow_ib_score + 0.30 * near_vwap_score
    raw = max(0.0, min(1.0, raw))

    detail = {
        "adx": adx, "low_adx_score": round(low_adx_score, 3),
        "ib_width": ib_width, "ib_ratio": round(ib_ratio, 3),
        "narrow_ib_score": round(narrow_ib_score, 3),
        "vwap_dist": round(vwap_dist, 3), "near_vwap_score": round(near_vwap_score, 3),
    }
    return raw, detail


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------

def classify_regime(
    snapshot: dict,
    structure: dict | None = None,
    session: dict | None = None,
) -> dict[str, Any]:
    """
    Classify the current intraday regime.

    Args:
        snapshot:   Market snapshot (bars, indicators, external, etc.)
        structure:  Structure levels dict (from structure.py)
        session:    Session report dict (from session.py)

    Returns:
        Regime report dict with:
            regime_type, trend_score, range_score, confidence,
            aggression_modifier, risk_multiplier, drivers
    """
    structure = structure or {}
    session = session or {}

    trend_raw, trend_detail = _trend_signal(snapshot, structure)
    range_raw, range_detail = _range_signal(snapshot, structure)

    # Classification: highest score wins, with minimum thresholds
    TREND_THRESHOLD = 0.55
    RANGE_THRESHOLD = 0.50

    if trend_raw >= TREND_THRESHOLD and trend_raw > range_raw:
        raw_regime = IntradayRegime.TREND
        confidence = trend_raw
    elif range_raw >= RANGE_THRESHOLD and range_raw > trend_raw:
        raw_regime = IntradayRegime.RANGE
        confidence = range_raw
    else:
        raw_regime = IntradayRegime.NEUTRAL
        confidence = 1.0 - max(trend_raw, range_raw)

    # 3-bar confirmation: regime transitions must be confirmed by 3 consecutive
    # bars in the new regime before acting on it (APEX spec)
    regime_state = store.load_state("intraday_regime_confirmation") or {}
    prev_regime = regime_state.get("regime", IntradayRegime.NEUTRAL)
    pending_regime = regime_state.get("pending_regime")
    confirmation_bars = regime_state.get("confirmation_bars", 0)

    if raw_regime != prev_regime:
        if pending_regime == raw_regime:
            confirmation_bars += 1
        else:
            pending_regime = raw_regime
            confirmation_bars = 1

        if confirmation_bars >= 3:
            # Confirmed transition
            regime_type = raw_regime
            regime_state["regime"] = raw_regime
            regime_state["pending_regime"] = None
            regime_state["confirmation_bars"] = 0
        else:
            # Not yet confirmed — keep previous regime
            regime_type = prev_regime
            regime_state["pending_regime"] = pending_regime
            regime_state["confirmation_bars"] = confirmation_bars
    else:
        regime_type = prev_regime
        regime_state["pending_regime"] = None
        regime_state["confirmation_bars"] = 0
        regime_state["regime"] = prev_regime

    store.save_state("intraday_regime_confirmation", regime_state)

    aggression = REGIME_MODIFIERS.get(regime_type, 0.5)

    # Session modifier (reduce aggression in unfavorable sessions)
    session_mod = session.get("modifier", 1.0)
    effective_aggression = aggression * session_mod

    # Risk multiplier for sentinel compatibility
    risk_multiplier = max(0.3, min(1.2, effective_aggression))

    return {
        "regime_type": regime_type,
        "trend_score": round(trend_raw, 4),
        "range_score": round(range_raw, 4),
        "confidence": round(confidence, 4),
        "aggression_modifier": round(aggression, 4),
        "session_modifier": round(session_mod, 4),
        "effective_aggression": round(effective_aggression, 4),
        "risk_multiplier": round(risk_multiplier, 4),
        "drivers": {
            "trend": trend_detail,
            "range": range_detail,
        },
        "classified_at": datetime.now(timezone.utc).isoformat(),
    }
