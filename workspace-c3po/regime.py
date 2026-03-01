#!/usr/bin/env python3
"""Regime scoring engine — spec Section 6.4–6.5.

Weighted drivers: trend, vol, corr, liquidity.
Sigmoid transform → effective_regime_score → risk_multiplier.
"""

from __future__ import annotations
import math
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))
from shared import contracts as C
from shared import state_store as store


def _sigmoid(x: float, steepness: float = 10.0) -> float:
    """Map x ∈ [0,1] to [0,1] with steepness controlling slope at 0.5."""
    if steepness <= 0:
        return x
    return 1.0 / (1.0 + math.exp(-steepness * (x - 0.5)))


def _trend_score(snapshot: dict) -> tuple[float, dict]:
    """
    Trend driver: ADX + MA slope.
    Higher ADX + positive slope → higher score (trending, favorable for trend strategies).
    """
    ind = snapshot.get("indicators", {})
    adx = ind.get("adx_14", 25.0)
    ma_slope = ind.get("ma_20_slope", 0.0)

    # ADX: 0–25 = low, 25–50 = medium, 50+ = strong trend
    adx_score = min(1.0, adx / 50.0)
    # Slope: positive = bullish structure, negative = bearish
    slope_score = 0.5 + 0.5 * math.tanh(ma_slope * 100)  # maps to [0,1]
    raw = 0.6 * adx_score + 0.4 * slope_score
    raw = max(0.0, min(1.0, raw))
    return raw, {"adx": adx, "adx_score": round(adx_score, 4),
                 "ma_slope": ma_slope, "slope_score": round(slope_score, 4)}


def _vol_score(snapshot: dict) -> tuple[float, dict]:
    """
    Volatility driver: VIX percentile.
    Low vol (low percentile) = favorable; high vol = risk-off.
    Invert: low percentile → high score.
    """
    ext = snapshot.get("external", {})
    vix_pct = ext.get("vix_percentile_252d", 0.5)
    # Invert: 0.2 percentile (low vol) → 0.8 score; 0.8 percentile (high vol) → 0.2 score
    raw = 1.0 - vix_pct
    raw = max(0.0, min(1.0, raw))
    return raw, {"vix_percentile": vix_pct}


def _corr_score(snapshot: dict, portfolio: dict) -> tuple[float, dict]:
    """
    Correlation stress driver.
    High intra-cluster correlation = stress; low = favorable.
    Phase 2: use heat.correlations_20d if available; else neutral.
    """
    heat = portfolio.get("heat", {})
    corrs = heat.get("correlations_20d", {})
    if not corrs:
        return 0.5, {"corr_stress": 0.5, "note": "no correlation data"}
    max_corr = max(abs(v) for v in corrs.values()) if corrs else 0.0
    # High max_corr → low score (stress)
    raw = 1.0 - max_corr
    raw = max(0.0, min(1.0, raw))
    return raw, {"max_corr_20d": round(max_corr, 4), "pairs": len(corrs)}


def _liquidity_score(snapshot: dict) -> tuple[float, dict]:
    """
    Liquidity driver: spread + book depth.
    Tight spread, deep book → high score.
    """
    ms = snapshot.get("microstructure", {})
    spread_ticks = ms.get("spread_ticks", 1)
    depth = ms.get("avg_book_depth_contracts", 850)
    baseline = ms.get("avg_book_depth_baseline", 850)

    # Spread: 1 tick = good, 3+ = poor
    spread_score = max(0.0, 1.0 - (spread_ticks - 1) / 3.0)
    # Depth: relative to baseline
    depth_score = min(1.0, depth / max(baseline, 1))
    raw = 0.5 * spread_score + 0.5 * depth_score
    raw = max(0.0, min(1.0, raw))
    return raw, {"spread_ticks": spread_ticks, "depth": depth, "baseline": baseline}


def compute_regime(
    snapshot: dict,
    portfolio: dict,
    param_version: str = "PV_0001",
    run_id: str = "",
    asof: str | None = None,
) -> dict:
    """
    Full regime scoring per spec 6.4.
    Returns regime report with risk_multiplier for sizing.
    """
    params = store.load_params(param_version)
    rp = params.get("regime", {})
    w_trend = rp.get("weight_trend", 0.35)
    w_vol = rp.get("weight_vol", 0.30)
    w_corr = rp.get("weight_corr", 0.20)
    w_liquidity = rp.get("weight_liquidity", 0.15)
    steepness = rp.get("sigmoid_steepness", 10)
    floor = rp.get("risk_multiplier_floor", 0.30)

    asof = asof or snapshot.get("asof", "")

    # Compute each driver
    trend_raw, trend_detail = _trend_score(snapshot)
    vol_raw, vol_detail = _vol_score(snapshot)
    corr_raw, corr_detail = _corr_score(snapshot, portfolio)
    liq_raw, liq_detail = _liquidity_score(snapshot)

    # Weighted regime score
    regime_score = (
        w_trend * trend_raw +
        w_vol * vol_raw +
        w_corr * corr_raw +
        w_liquidity * liq_raw
    )
    regime_score = max(0.0, min(1.0, regime_score))

    # Confidence: based on data quality and driver agreement
    dq = snapshot.get("data_quality", {})
    stale = dq.get("is_stale", False)
    bar_age = dq.get("last_bar_age_sec", 0)
    confidence = 0.85 if not stale and bar_age < 120 else 0.60

    # Effective regime score (confidence-weighted)
    effective_regime_score = regime_score * confidence + 0.5 * (1 - confidence)
    effective_regime_score = max(0.0, min(1.0, effective_regime_score))

    # Sigmoid transform for risk multiplier
    sigmoid_out = _sigmoid(effective_regime_score, steepness)
    risk_multiplier = floor + (1.0 - floor) * sigmoid_out
    risk_multiplier = round(risk_multiplier, 4)

    # Mode hint
    if effective_regime_score < 0.35:
        mode_hint = "RISK_OFF"
    elif effective_regime_score < 0.55:
        mode_hint = "NEUTRAL"
    elif effective_regime_score < 0.75:
        mode_hint = "NEUTRAL_TO_RISK_ON"
    else:
        mode_hint = "RISK_ON"

    drivers: dict[str, Any] = {
        "trend_score":       {"raw": round(trend_raw, 4), "weight": w_trend, "detail": trend_detail},
        "vol_percentile":    {"raw": round(vol_raw, 4), "weight": w_vol, "detail": vol_detail},
        "corr_stress":       {"raw": round(corr_raw, 4), "weight": w_corr, "detail": corr_detail},
        "liquidity_score":   {"raw": round(liq_raw, 4), "weight": w_liquidity, "detail": liq_detail},
    }

    report_id = f"RR_{asof[:16].replace('-', '').replace('T', '_').replace(':', '')}" if asof else "RR"

    return C.make_regime_report(
        report_id=report_id,
        run_id=run_id,
        asof=asof,
        param_version=param_version,
        regime_score=regime_score,
        confidence=confidence,
        effective_regime_score=effective_regime_score,
        risk_multiplier=risk_multiplier,
        drivers=drivers,
        mode_hint=mode_hint,
    )
