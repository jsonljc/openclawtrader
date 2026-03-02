#!/usr/bin/env python3
"""Sentinel Analyzer — learns max_risk_per_trade_pct, max_slippage_ticks.

Analyzes denial rates and risk utilization to calibrate sentinel limits.
Sentinel limits can only be loosened by max 10% per proposal;
tightening has no limit.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from bayesian import BetaBinomial, NormalGamma
from collector import TradeRecord


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def analyze_sentinel(
    trades: list[TradeRecord],
    denied_intents: list[dict],
    exec_quality: dict,
    params: dict,
    min_events: int = 10,
) -> list[dict]:
    """Analyze sentinel limits and propose adjustments.

    Args:
        trades: Closed trades (to check if denied trades would have been profitable).
        denied_intents: INTENT_DENIED payloads.
        exec_quality: From state_store.load_exec_quality().
        params: Current parameter set (sentinel section).
        min_events: Minimum events before proposing changes.

    Returns:
        List of Adjustment dicts.
    """
    adjustments: list[dict] = []
    sp = params.get("sentinel", {})

    # --- Slippage limit analysis ---
    current_max_slip = sp.get("max_slippage_ticks", 4)

    # Count denials due to slippage
    slip_denials = [
        d for d in denied_intents
        if "slippage" in str(d.get("denial_reasons", d.get("reason", ""))).lower()
        or "max_slippage" in str(d.get("failed_checks", "")).lower()
    ]

    total_intents = len(trades) + len(denied_intents)
    if total_intents >= min_events and len(slip_denials) > 0:
        denial_rate = len(slip_denials) / total_intents

        model = BetaBinomial(2.0, 2.0).update(
            successes=len(slip_denials), trials=total_intents
        )
        lo, hi = model.ci(0.90)

        # If denial rate > 30% and we have enough data
        if denial_rate > 0.30 and lo > 0.20:
            # Check realized slippage to see if limit is realistic
            realized_slips = [t.slippage_ticks for t in trades if t.slippage_ticks > 0]
            if realized_slips:
                avg_realized = sum(realized_slips) / len(realized_slips)
                max_realized = max(realized_slips)

                # Only loosen by max 10%
                proposed = round(min(current_max_slip * 1.10, max_realized + 1), 1)
                if proposed > current_max_slip:
                    adjustments.append({
                        "surface": "sentinel",
                        "param_path": "sentinel.max_slippage_ticks",
                        "current_value": current_max_slip,
                        "proposed_value": proposed,
                        "confidence": round(1.0 - model.ci_width(), 4),
                        "sample_size": total_intents,
                        "rationale": (
                            f"Slippage denial rate = {denial_rate:.0%} "
                            f"({len(slip_denials)}/{total_intents}, CI [{lo:.2f}, {hi:.2f}]). "
                            f"Realized slippage avg = {avg_realized:.1f}, max = {max_realized:.1f} ticks. "
                            f"Limit of {current_max_slip} may be too tight — "
                            f"suggest loosening to {proposed} (max 10% increase)."
                        ),
                    })
        elif denial_rate < 0.05 and len(trades) >= min_events:
            # Very few denials — check if limit can be tightened
            realized_slips = [t.slippage_ticks for t in trades if t.slippage_ticks > 0]
            if realized_slips:
                p95 = sorted(realized_slips)[int(len(realized_slips) * 0.95)]
                if p95 < current_max_slip * 0.60:
                    proposed = round(max(p95 + 1, 2), 1)
                    if proposed < current_max_slip:
                        adjustments.append({
                            "surface": "sentinel",
                            "param_path": "sentinel.max_slippage_ticks",
                            "current_value": current_max_slip,
                            "proposed_value": proposed,
                            "confidence": round(min(len(realized_slips) / 50.0, 0.9), 4),
                            "sample_size": len(realized_slips),
                            "rationale": (
                                f"Slippage denial rate < 5%, 95th pctile realized = {p95:.1f} ticks "
                                f"(well below limit of {current_max_slip}). "
                                f"Suggest tightening to {proposed}."
                            ),
                        })

    # --- Risk per trade analysis ---
    current_max_risk = sp.get("max_risk_per_trade_pct", 1.0)

    if len(trades) >= min_events:
        # Check if all trades use far less than the limit
        # We can't directly measure risk_pct from TradeRecord, but we can check
        # if the limit is binding or not from denial patterns
        risk_denials = [
            d for d in denied_intents
            if "risk_per_trade" in str(d.get("denial_reasons", d.get("reason", ""))).lower()
            or "max_risk" in str(d.get("failed_checks", "")).lower()
        ]

        if len(risk_denials) > 0 and total_intents >= min_events:
            risk_denial_rate = len(risk_denials) / total_intents
            model_risk = BetaBinomial(2.0, 2.0).update(
                successes=len(risk_denials), trials=total_intents
            )
            lo_r, hi_r = model_risk.ci(0.90)

            if risk_denial_rate > 0.20 and lo_r > 0.10:
                # Only loosen by max 10%
                proposed_risk = round(min(current_max_risk * 1.10, 2.0), 4)
                if proposed_risk > current_max_risk:
                    adjustments.append({
                        "surface": "sentinel",
                        "param_path": "sentinel.max_risk_per_trade_pct",
                        "current_value": current_max_risk,
                        "proposed_value": proposed_risk,
                        "confidence": round(1.0 - model_risk.ci_width(), 4),
                        "sample_size": total_intents,
                        "rationale": (
                            f"Risk-per-trade denial rate = {risk_denial_rate:.0%} "
                            f"({len(risk_denials)}/{total_intents}, CI [{lo_r:.2f}, {hi_r:.2f}]). "
                            f"Current limit {current_max_risk}% may be constraining — "
                            f"suggest loosening to {proposed_risk}% (max 10% increase)."
                        ),
                    })

    return adjustments
