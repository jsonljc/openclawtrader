#!/usr/bin/env python3
"""Signal Analyzer — learns adx_min, stop_atr_multiple, tp_atr_multiple.

Buckets trades by signal quality indicators, fits Bayesian models,
and proposes adjustments when expectancies differ significantly.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add repo root so we can import shared.*
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
# Add learning package root so we can import bayesian, collector
sys.path.insert(0, str(Path(__file__).parent.parent))

from bayesian import BetaBinomial, NormalGamma
from collector import TradeRecord


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def analyze_signals(
    trades: list[TradeRecord],
    strategy: dict,
    min_trades: int = 10,
) -> list[dict]:
    """Analyze signal parameters and propose adjustments.

    Args:
        trades: Closed trades for this strategy.
        strategy: Strategy JSON dict (contains signal.adx_min, etc.).
        min_trades: Minimum trades before proposing changes.

    Returns:
        List of Adjustment dicts with keys:
        surface, param_path, current_value, proposed_value,
        confidence, sample_size, rationale.
    """
    adjustments: list[dict] = []

    if len(trades) < min_trades:
        return adjustments

    signal_cfg = strategy.get("signal", {})
    sid = strategy.get("strategy_id", "")
    current_adx_min = signal_cfg.get("adx_min", 25)
    current_stop_mult = signal_cfg.get("stop_atr_multiple", 1.5)
    current_tp_mult = signal_cfg.get("tp_atr_multiple", 2.5)

    # --- Stop ATR multiple analysis ---
    # If most losses hit stop with <= 1 bar held, stops may be too tight
    stop_losses = [t for t in trades if t.trigger == "STOP"]
    if len(stop_losses) >= 5:
        quick_stops = [t for t in stop_losses if t.bars_held <= 1]
        quick_ratio = len(quick_stops) / len(stop_losses)

        model = BetaBinomial(alpha_prior=2.0, beta_prior=2.0).update(
            successes=len(quick_stops), trials=len(stop_losses)
        )
        lo, hi = model.ci(0.90)

        if lo > 0.40:  # >40% of stops are quick — stops likely too tight
            proposed = round(current_stop_mult * 1.12, 2)
            adjustments.append({
                "surface": "signal",
                "param_path": f"strategy.{sid}.stop_atr_multiple",
                "current_value": current_stop_mult,
                "proposed_value": proposed,
                "confidence": round(1.0 - model.ci_width(), 4),
                "sample_size": len(stop_losses),
                "rationale": (
                    f"{len(quick_stops)}/{len(stop_losses)} stop-outs hit within 1 bar "
                    f"(rate {quick_ratio:.0%}, CI [{lo:.2f}, {hi:.2f}]). "
                    f"Stops may be too tight — suggest widening {current_stop_mult} → {proposed}."
                ),
            })

    # --- TP ATR multiple analysis ---
    # If price often runs well past TP, consider widening
    tp_hits = [t for t in trades if t.trigger == "TP"]
    if len(tp_hits) >= 5:
        tp_r_values = [t.realized_r for t in tp_hits]
        model_r = NormalGamma(mu0=1.5, kappa0=1.0, alpha0=2.0, beta0=1.0).update(
            tp_r_values
        )
        mean_r = model_r.mean()

        # If average R on TP hits is very close to the TP/stop ratio, room to widen
        expected_r = current_tp_mult / current_stop_mult
        if mean_r > expected_r * 0.90:
            proposed = round(current_tp_mult * 1.10, 2)
            lo_r, hi_r = model_r.ci(0.90)
            adjustments.append({
                "surface": "signal",
                "param_path": f"strategy.{sid}.tp_atr_multiple",
                "current_value": current_tp_mult,
                "proposed_value": proposed,
                "confidence": round(
                    max(0.0, 1.0 - model_r.ci_width() / max(abs(mean_r), 0.01)), 4
                ),
                "sample_size": len(tp_hits),
                "rationale": (
                    f"TP hits avg {mean_r:.2f}R (CI [{lo_r:.2f}, {hi_r:.2f}]), close to max "
                    f"{expected_r:.2f}R. Price may run past TP — suggest widening "
                    f"{current_tp_mult} → {proposed}."
                ),
            })

    # --- ADX minimum analysis ---
    # Check if low-quality trades (by regime score proxy) drag down results
    wins = [t for t in trades if t.realized_pnl > 0]
    overall_hit = BetaBinomial(2.0, 2.0).update(len(wins), len(trades))

    low_r_trades = [t for t in trades if t.realized_r < -0.5]
    high_r_trades = [t for t in trades if t.realized_r > 0.5]

    if len(low_r_trades) >= 5 and len(high_r_trades) >= 5:
        low_regime = [
            t.regime_score_at_entry for t in low_r_trades
            if t.regime_score_at_entry > 0
        ]
        high_regime = [
            t.regime_score_at_entry for t in high_r_trades
            if t.regime_score_at_entry > 0
        ]

        if low_regime and high_regime:
            avg_low = sum(low_regime) / len(low_regime)
            avg_high = sum(high_regime) / len(high_regime)

            if avg_low < avg_high - 0.1:
                proposed = min(current_adx_min + 3, 40)
                adjustments.append({
                    "surface": "signal",
                    "param_path": f"strategy.{sid}.adx_min",
                    "current_value": current_adx_min,
                    "proposed_value": proposed,
                    "confidence": round(
                        overall_hit.mean() * (1.0 - overall_hit.ci_width()), 4
                    ),
                    "sample_size": len(trades),
                    "rationale": (
                        f"Losing trades (R < -0.5, n={len(low_r_trades)}) had avg regime score "
                        f"{avg_low:.2f} vs winners (R > 0.5, n={len(high_r_trades)}) at "
                        f"{avg_high:.2f}. Tightening ADX filter "
                        f"{current_adx_min} → {proposed} to reject weaker setups."
                    ),
                })

    return adjustments
