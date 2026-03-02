#!/usr/bin/env python3
"""Overnight Analyzer — learns flatten_vol_pct_threshold, partial_exit_profit_progress.

Tracks positions held overnight vs flattened and compares next-day gap impact.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from bayesian import BetaBinomial, NormalGamma
from collector import TradeRecord


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _classify_trigger(trigger: str) -> str:
    """Classify exit trigger into overnight-relevant categories."""
    trigger_upper = trigger.upper()
    if "OVERNIGHT" in trigger_upper or "FLATTEN" in trigger_upper:
        return "FLATTENED"
    return "HELD"


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def analyze_overnight(
    trades: list[TradeRecord],
    params: dict,
    min_trades: int = 15,
) -> list[dict]:
    """Analyze overnight hold policy and propose adjustments.

    Args:
        trades: Closed trades (includes overnight-related exits).
        params: Current parameter set (overnight section).
        min_trades: Minimum trades before proposing changes.

    Returns:
        List of Adjustment dicts.
    """
    adjustments: list[dict] = []
    op = params.get("overnight", {})

    if len(trades) < min_trades:
        return adjustments

    current_vol_threshold = op.get("flatten_vol_pct_threshold", 0.80)
    current_partial_progress = op.get("partial_exit_profit_progress", 0.50)

    # Classify trades by overnight handling
    flattened = [t for t in trades if _classify_trigger(t.trigger) == "FLATTENED"]
    held_overnight = [t for t in trades if t.bars_held > 1]  # multi-bar = likely held overnight

    # --- Vol threshold analysis ---
    # Trades flattened overnight: were they actually at risk of adverse gaps?
    if len(flattened) >= 5:
        # If flattened trades had mostly positive R (would have been fine to hold),
        # the vol threshold may be too conservative
        flat_winners = sum(1 for t in flattened if t.realized_r > 0)
        model_flat = BetaBinomial(2.0, 2.0).update(
            successes=flat_winners, trials=len(flattened)
        )
        flat_win_rate = model_flat.mean()
        lo, hi = model_flat.ci(0.90)

        if flat_win_rate > 0.60 and lo > 0.45:
            # Most flattened trades were winning — vol threshold may be too aggressive
            proposed = round(min(current_vol_threshold + 0.05, 0.95), 2)
            if proposed > current_vol_threshold:
                adjustments.append({
                    "surface": "overnight",
                    "param_path": "overnight.flatten_vol_pct_threshold",
                    "current_value": current_vol_threshold,
                    "proposed_value": proposed,
                    "confidence": round(1.0 - model_flat.ci_width(), 4),
                    "sample_size": len(flattened),
                    "rationale": (
                        f"{flat_winners}/{len(flattened)} overnight-flattened trades were winning "
                        f"(rate {flat_win_rate:.2f}, CI [{lo:.2f}, {hi:.2f}]). "
                        f"Vol threshold {current_vol_threshold} may be too conservative — "
                        f"suggest raising to {proposed}."
                    ),
                })
        elif flat_win_rate < 0.30 and hi < 0.45:
            # Most flattened trades were losing — good that we flattened,
            # consider being even more aggressive
            proposed = round(max(current_vol_threshold - 0.05, 0.60), 2)
            if proposed < current_vol_threshold:
                adjustments.append({
                    "surface": "overnight",
                    "param_path": "overnight.flatten_vol_pct_threshold",
                    "current_value": current_vol_threshold,
                    "proposed_value": proposed,
                    "confidence": round(1.0 - model_flat.ci_width(), 4),
                    "sample_size": len(flattened),
                    "rationale": (
                        f"Only {flat_winners}/{len(flattened)} overnight-flattened trades were winning "
                        f"(rate {flat_win_rate:.2f}, CI [{lo:.2f}, {hi:.2f}]). "
                        f"Flattening was correct — consider lowering threshold "
                        f"{current_vol_threshold} → {proposed} to flatten earlier."
                    ),
                })

    # --- Partial exit progress analysis ---
    # Check if partial exits at current threshold are beneficial
    # Trades with positive R where trigger wasn't TP — these were partial exits or manual
    partial_candidates = [
        t for t in trades
        if t.realized_r > 0 and t.trigger not in ("TP", "STOP")
    ]

    if len(partial_candidates) >= 5 and len(held_overnight) >= 5:
        # Compare R-multiples of partial-exited vs fully held
        partial_r = [t.realized_r for t in partial_candidates]
        held_r = [t.realized_r for t in held_overnight if t.realized_r > 0]

        if partial_r and held_r:
            model_partial = NormalGamma(
                mu0=0.5, kappa0=1.0, alpha0=2.0, beta0=1.0
            ).update(partial_r)
            model_held = NormalGamma(
                mu0=0.5, kappa0=1.0, alpha0=2.0, beta0=1.0
            ).update(held_r)

            mean_partial = model_partial.mean()
            mean_held = model_held.mean()

            if mean_partial < mean_held * 0.70:
                # Partial exits are capturing less profit — loosen threshold
                proposed = round(min(current_partial_progress + 0.10, 0.80), 2)
                if proposed > current_partial_progress:
                    lo_p, hi_p = model_partial.ci(0.90)
                    lo_h, hi_h = model_held.ci(0.90)
                    adjustments.append({
                        "surface": "overnight",
                        "param_path": "overnight.partial_exit_profit_progress",
                        "current_value": current_partial_progress,
                        "proposed_value": proposed,
                        "confidence": round(max(0.0, min(
                            1.0 - model_partial.ci_width() / max(abs(mean_partial), 0.01),
                            0.9
                        )), 4),
                        "sample_size": len(partial_candidates) + len(held_r),
                        "rationale": (
                            f"Partial exits avg R = {mean_partial:.2f} (CI [{lo_p:.2f}, {hi_p:.2f}]) "
                            f"vs held avg R = {mean_held:.2f} (CI [{lo_h:.2f}, {hi_h:.2f}]). "
                            f"Partial exits may be cutting winners too early — "
                            f"suggest raising progress threshold {current_partial_progress} → {proposed}."
                        ),
                    })

    return adjustments
