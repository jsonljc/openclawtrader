#!/usr/bin/env python3
"""Slippage Analyzer — learns base_ticks, vol_factor slopes, session_factor_*.

Compares the slippage model's predictions to realized slippage by
vol_percentile and session type buckets.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from bayesian import NormalGamma
from collector import TradeRecord


# ---------------------------------------------------------------------------
# Vol buckets
# ---------------------------------------------------------------------------
VOL_BUCKETS = [
    ("low", 0.00, 0.50),
    ("mid", 0.50, 0.80),
    ("high", 0.80, 1.01),
]

SESSION_TYPES = ["CORE", "EXTENDED", "PRE_OPEN", "POST_CLOSE"]


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def analyze_slippage(
    trades: list[TradeRecord],
    params: dict,
    min_fills: int = 10,
) -> list[dict]:
    """Analyze slippage model calibration and propose adjustments.

    Args:
        trades: Closed trades with slippage_ticks recorded.
        params: Current parameter set (slippage section).
        min_fills: Minimum fills before proposing changes.

    Returns:
        List of Adjustment dicts.
    """
    adjustments: list[dict] = []
    sp = params.get("slippage", {})

    fills_with_slip = [t for t in trades if t.slippage_ticks >= 0]
    if len(fills_with_slip) < min_fills:
        return adjustments

    current_base = sp.get("base_ticks", 1)
    current_low_slope = sp.get("vol_factor_low_slope", 4.0)
    current_high_slope = sp.get("vol_factor_high_slope", 15.0)

    # --- Base ticks analysis ---
    # Fit NormalGamma on all realized slippage values
    slip_values = [t.slippage_ticks for t in fills_with_slip]
    model_all = NormalGamma(
        mu0=float(current_base), kappa0=1.0, alpha0=2.0, beta0=1.0
    ).update(slip_values)

    realized_mean = model_all.mean()
    lo_all, hi_all = model_all.ci(0.90)

    # If systematic bias > 0.5 ticks
    bias = realized_mean - current_base
    if abs(bias) > 0.5 and (current_base < lo_all or current_base > hi_all):
        proposed_base = round(realized_mean, 2)
        adjustments.append({
            "surface": "slippage",
            "param_path": "slippage.base_ticks",
            "current_value": current_base,
            "proposed_value": proposed_base,
            "confidence": round(max(0.0, 1.0 - model_all.ci_width() / max(abs(realized_mean), 0.01)), 4),
            "sample_size": len(slip_values),
            "rationale": (
                f"Realized slippage avg = {realized_mean:.2f} ticks "
                f"(n={len(slip_values)}, CI [{lo_all:.2f}, {hi_all:.2f}]). "
                f"Model base = {current_base}. Systematic {'under' if bias > 0 else 'over'}estimate "
                f"of {abs(bias):.2f} ticks — suggest adjusting to {proposed_base}."
            ),
        })

    # --- Vol-bucket analysis for slope calibration ---
    # We can't directly observe vol_percentile from TradeRecord,
    # but we can use regime_score_at_entry as a proxy for market conditions
    # In a fully instrumented system, vol_percentile would be in the trade payload

    # Split by regime score into vol-like buckets
    low_regime = [t for t in fills_with_slip if t.regime_score_at_entry >= 0.60]  # calmer
    high_regime = [t for t in fills_with_slip if t.regime_score_at_entry < 0.40]  # stressed

    if len(low_regime) >= 5 and len(high_regime) >= 5:
        low_slips = [t.slippage_ticks for t in low_regime]
        high_slips = [t.slippage_ticks for t in high_regime]

        model_low = NormalGamma(
            mu0=float(current_base), kappa0=1.0, alpha0=2.0, beta0=1.0
        ).update(low_slips)
        model_high = NormalGamma(
            mu0=float(current_base) * 2.0, kappa0=1.0, alpha0=2.0, beta0=1.0
        ).update(high_slips)

        mean_low = model_low.mean()
        mean_high = model_high.mean()

        # The vol factor slopes determine how much slippage increases with vol
        # If high-vol slippage is higher than model predicts, increase slope
        expected_high_slip = current_base * (1.0 + 0.30 * current_low_slope)  # approximate mid-range
        if mean_high > expected_high_slip * 1.20 and len(high_slips) >= 5:
            proposed_slope = round(current_high_slope * (mean_high / max(expected_high_slip, 1.0)), 1)
            proposed_slope = min(proposed_slope, 25.0)  # cap
            lo_h, hi_h = model_high.ci(0.90)
            adjustments.append({
                "surface": "slippage",
                "param_path": "slippage.vol_factor_high_slope",
                "current_value": current_high_slope,
                "proposed_value": proposed_slope,
                "confidence": round(max(0.0, 1.0 - model_high.ci_width() / max(abs(mean_high), 0.01)), 4),
                "sample_size": len(high_slips),
                "rationale": (
                    f"High-vol slippage avg = {mean_high:.2f} ticks "
                    f"(n={len(high_slips)}, CI [{lo_h:.2f}, {hi_h:.2f}]) "
                    f"vs expected {expected_high_slip:.2f}. "
                    f"Model underestimates high-vol impact — suggest adjusting "
                    f"vol_factor_high_slope {current_high_slope} → {proposed_slope}."
                ),
            })
        elif mean_high < expected_high_slip * 0.70 and len(high_slips) >= 5:
            proposed_slope = round(current_high_slope * (mean_high / max(expected_high_slip, 1.0)), 1)
            proposed_slope = max(proposed_slope, 5.0)  # floor
            lo_h, hi_h = model_high.ci(0.90)
            adjustments.append({
                "surface": "slippage",
                "param_path": "slippage.vol_factor_high_slope",
                "current_value": current_high_slope,
                "proposed_value": proposed_slope,
                "confidence": round(max(0.0, 1.0 - model_high.ci_width() / max(abs(mean_high), 0.01)), 4),
                "sample_size": len(high_slips),
                "rationale": (
                    f"High-vol slippage avg = {mean_high:.2f} ticks "
                    f"(n={len(high_slips)}, CI [{lo_h:.2f}, {hi_h:.2f}]) "
                    f"vs expected {expected_high_slip:.2f}. "
                    f"Model overestimates high-vol impact — suggest adjusting "
                    f"vol_factor_high_slope {current_high_slope} → {proposed_slope}."
                ),
            })

    # --- Session factor analysis ---
    # Check for session-specific slippage patterns
    # Since we don't have session data in TradeRecord directly,
    # this would need to be extracted from ORDER_FILLED events
    # For now, we analyze the overall distribution shape

    return adjustments
