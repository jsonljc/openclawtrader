#!/usr/bin/env python3
"""Health Analyzer — learns expected_hit_rate, expected_sharpe,
expected_max_dd_pct, expected_avg_slippage_ticks in strategy JSONs.

Compares realized metrics to expectations and proposes updates
so that health scoring is properly calibrated.
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

def analyze_health(
    trades: list[TradeRecord],
    strategy: dict,
    min_trades: int = 15,
) -> list[dict]:
    """Analyze health expectations and propose calibration updates.

    Args:
        trades: Closed trades for this strategy.
        strategy: Strategy JSON dict with expected_* fields.
        min_trades: Minimum trades before proposing changes.

    Returns:
        List of Adjustment dicts.
    """
    adjustments: list[dict] = []
    sid = strategy.get("strategy_id", "")

    if len(trades) < min_trades:
        return adjustments

    # --- Hit rate calibration ---
    exp_hr = strategy.get("expected_hit_rate", 0.45)
    wins = sum(1 for t in trades if t.realized_pnl > 0)
    model_hr = BetaBinomial(alpha_prior=2.0, beta_prior=2.0).update(
        successes=wins, trials=len(trades)
    )
    realized_hr = model_hr.mean()
    lo_hr, hi_hr = model_hr.ci(0.90)

    # If the 90% CI excludes the expected value, propose update
    if exp_hr < lo_hr or exp_hr > hi_hr:
        proposed_hr = round(realized_hr, 4)
        adjustments.append({
            "surface": "health",
            "param_path": f"strategy.{sid}.expected_hit_rate",
            "current_value": exp_hr,
            "proposed_value": proposed_hr,
            "confidence": round(1.0 - model_hr.ci_width(), 4),
            "sample_size": len(trades),
            "rationale": (
                f"Realized hit rate = {realized_hr:.4f} "
                f"(n={len(trades)}, CI [{lo_hr:.4f}, {hi_hr:.4f}]). "
                f"Current expectation {exp_hr} is outside the 90% credible interval."
            ),
        })

    # --- Sharpe calibration ---
    exp_sharpe = strategy.get("expected_sharpe", 0.7)
    r_values = [t.realized_r for t in trades]
    if r_values:
        model_sharpe = NormalGamma(
            mu0=exp_sharpe, kappa0=1.0, alpha0=2.0, beta0=1.0
        ).update(r_values)
        realized_mean_r = model_sharpe.mean()
        lo_s, hi_s = model_sharpe.ci(0.90)

        # Approximate Sharpe from mean R / std R
        if len(r_values) >= 2:
            import math
            r_mean = sum(r_values) / len(r_values)
            r_std = math.sqrt(
                sum((r - r_mean) ** 2 for r in r_values) / (len(r_values) - 1)
            )
            realized_sharpe = (r_mean / r_std) if r_std > 0 else 0.0
            # Annualize: ~8 trades/month * 12 months = 96/year
            trades_per_year = strategy.get("expected_trades_per_month", 8) * 12
            realized_sharpe_ann = realized_sharpe * math.sqrt(trades_per_year)

            if abs(realized_sharpe_ann - exp_sharpe) > 0.3:
                proposed_sharpe = round(realized_sharpe_ann, 2)
                adjustments.append({
                    "surface": "health",
                    "param_path": f"strategy.{sid}.expected_sharpe",
                    "current_value": exp_sharpe,
                    "proposed_value": proposed_sharpe,
                    "confidence": round(max(0.0, 1.0 - model_sharpe.ci_width() / max(abs(realized_mean_r), 0.01)), 4),
                    "sample_size": len(trades),
                    "rationale": (
                        f"Realized annualized Sharpe ≈ {realized_sharpe_ann:.2f} "
                        f"(from per-trade R: mean={r_mean:.3f}, std={r_std:.3f}, n={len(trades)}). "
                        f"Current expectation {exp_sharpe} differs by > 0.3."
                    ),
                })

    # --- Max drawdown calibration ---
    exp_dd = strategy.get("expected_max_dd_pct", 10.0)
    # Compute rolling max DD from trade PnLs
    if len(trades) >= 10:
        cumulative = 0.0
        peak = 0.0
        max_dd = 0.0
        for t in trades:
            cumulative += t.realized_pnl
            if cumulative > peak:
                peak = cumulative
            dd = (peak - cumulative) / max(peak, 1.0) * 100.0 if peak > 0 else 0.0
            if dd > max_dd:
                max_dd = dd

        if abs(max_dd - exp_dd) > 2.0:
            proposed_dd = round(max(max_dd, 3.0), 1)
            adjustments.append({
                "surface": "health",
                "param_path": f"strategy.{sid}.expected_max_dd_pct",
                "current_value": exp_dd,
                "proposed_value": proposed_dd,
                "confidence": round(min(len(trades) / 50.0, 0.9), 4),
                "sample_size": len(trades),
                "rationale": (
                    f"Realized max DD = {max_dd:.1f}% over {len(trades)} trades. "
                    f"Current expectation {exp_dd}% differs by > 2pp."
                ),
            })

    # --- Slippage calibration ---
    exp_slip = strategy.get("expected_avg_slippage_ticks", 1.0)
    slip_values = [t.slippage_ticks for t in trades if t.slippage_ticks > 0]
    if len(slip_values) >= 10:
        model_slip = NormalGamma(
            mu0=exp_slip, kappa0=1.0, alpha0=2.0, beta0=1.0
        ).update(slip_values)
        realized_slip = model_slip.mean()
        lo_sl, hi_sl = model_slip.ci(0.90)

        if exp_slip < lo_sl or exp_slip > hi_sl:
            proposed_slip = round(realized_slip, 2)
            adjustments.append({
                "surface": "health",
                "param_path": f"strategy.{sid}.expected_avg_slippage_ticks",
                "current_value": exp_slip,
                "proposed_value": proposed_slip,
                "confidence": round(max(0.0, 1.0 - model_slip.ci_width() / max(abs(realized_slip), 0.01)), 4),
                "sample_size": len(slip_values),
                "rationale": (
                    f"Realized avg slippage = {realized_slip:.2f} ticks "
                    f"(n={len(slip_values)}, CI [{lo_sl:.2f}, {hi_sl:.2f}]). "
                    f"Current expectation {exp_slip} is outside the 90% CI."
                ),
            })

    return adjustments
