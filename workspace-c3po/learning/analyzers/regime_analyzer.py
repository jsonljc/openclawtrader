#!/usr/bin/env python3
"""Regime Analyzer — learns weight_trend, weight_vol, weight_corr, weight_liquidity.

Analyzes which regime drivers best predicted favorable returns and
proposes rebalancing when realized predictive power differs from weights.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from bayesian import NormalGamma
from collector import RegimeSnapshot, TradeRecord


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rank_correlation(x: list[float], y: list[float]) -> float:
    """Spearman rank correlation (simplified, no-scipy implementation)."""
    n = len(x)
    if n < 3:
        return 0.0

    def _ranks(vals: list[float]) -> list[float]:
        indexed = sorted(enumerate(vals), key=lambda t: t[1])
        ranks = [0.0] * n
        for rank, (idx, _) in enumerate(indexed, 1):
            ranks[idx] = float(rank)
        return ranks

    rx = _ranks(x)
    ry = _ranks(y)
    d_sq = sum((a - b) ** 2 for a, b in zip(rx, ry))
    return 1.0 - (6.0 * d_sq) / (n * (n * n - 1.0))


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def analyze_regime(
    snapshots: list[RegimeSnapshot],
    trades: list[TradeRecord],
    current_weights: dict[str, float],
    min_snapshots: int = 15,
) -> list[dict]:
    """Analyze regime driver weights and propose rebalancing.

    Args:
        snapshots: Regime snapshots with driver scores.
        trades: Closed trades (used to compute returns around regime observations).
        current_weights: Current driver weights from params, e.g.
            {"weight_trend": 0.35, "weight_vol": 0.30, ...}.
        min_snapshots: Minimum regime observations before proposing changes.

    Returns:
        List of Adjustment dicts.
    """
    adjustments: list[dict] = []

    if len(snapshots) < min_snapshots:
        return adjustments

    # Approximate subsequent returns by matching regime snapshots to trades
    # that occurred within 5 days of each snapshot
    drivers = ["trend", "vol", "corr", "liquidity"]
    driver_key_map = {
        "trend": "weight_trend",
        "vol": "weight_vol",
        "corr": "weight_corr",
        "liquidity": "weight_liquidity",
    }

    # Compute rank correlations between each driver score and trade outcomes
    # For each snapshot, find trades that opened near that time
    driver_outcomes: dict[str, list[tuple[float, float]]] = {d: [] for d in drivers}

    for snap in snapshots:
        snap_ts = snap.timestamp
        # Find trades that entered within 5 days of this regime snapshot
        nearby_trades = [
            t for t in trades
            if t.entry_ts >= snap_ts
            and t.entry_ts <= _offset_ts(snap_ts, days=5)
        ]
        if not nearby_trades:
            continue

        avg_r = sum(t.realized_r for t in nearby_trades) / len(nearby_trades)
        for d in drivers:
            score = snap.driver_scores.get(d, 0.0)
            driver_outcomes[d].append((score, avg_r))

    # Fit NormalGamma on each driver's predictive correlation
    for d in drivers:
        pairs = driver_outcomes[d]
        if len(pairs) < min_snapshots:
            continue

        scores = [p[0] for p in pairs]
        outcomes = [p[1] for p in pairs]
        corr = _rank_correlation(scores, outcomes)

        # Fit model on the correlation strength
        # We use NormalGamma to estimate the "true" predictive power
        # For simplicity, we treat each pair's contribution as a data point
        # representing the driver's alignment with outcomes
        contributions = [s * o for s, o in pairs]  # driver_score * realized_r
        model = NormalGamma(mu0=0.0, kappa0=1.0, alpha0=2.0, beta0=1.0).update(contributions)

        weight_key = driver_key_map[d]
        current_w = current_weights.get(weight_key, 0.25)

        # If the driver's predictive power is significantly different from its weight
        lo, hi = model.ci(0.90)
        mean_power = model.mean()

        # Normalize: compare relative predictive power to relative weight
        # If a driver contributes positively and has low weight, suggest increase
        # If it contributes negatively and has high weight, suggest decrease
        if mean_power > 0 and lo > 0 and current_w < 0.40:
            # Driver is predictive but underweighted
            proposed = round(min(current_w * 1.15, 0.50), 4)
            if proposed != current_w:
                adjustments.append({
                    "surface": "regime",
                    "param_path": f"regime.{weight_key}",
                    "current_value": current_w,
                    "proposed_value": proposed,
                    "confidence": round(1.0 - model.ci_width() / max(abs(mean_power), 0.01), 4),
                    "sample_size": len(pairs),
                    "rationale": (
                        f"Driver '{d}' shows positive predictive power "
                        f"(mean={mean_power:.3f}, CI [{lo:.3f}, {hi:.3f}], "
                        f"rank corr={corr:.3f}, n={len(pairs)}). "
                        f"Current weight {current_w:.2f} may be low — suggest {proposed:.4f}."
                    ),
                })
        elif mean_power < 0 and hi < 0 and current_w > 0.15:
            # Driver is anti-predictive but has meaningful weight
            proposed = round(max(current_w * 0.85, 0.10), 4)
            if proposed != current_w:
                adjustments.append({
                    "surface": "regime",
                    "param_path": f"regime.{weight_key}",
                    "current_value": current_w,
                    "proposed_value": proposed,
                    "confidence": round(1.0 - model.ci_width() / max(abs(mean_power), 0.01), 4),
                    "sample_size": len(pairs),
                    "rationale": (
                        f"Driver '{d}' shows negative predictive power "
                        f"(mean={mean_power:.3f}, CI [{lo:.3f}, {hi:.3f}], "
                        f"rank corr={corr:.3f}, n={len(pairs)}). "
                        f"Current weight {current_w:.2f} may be high — suggest {proposed:.4f}."
                    ),
                })

    # Ensure proposed weights would still sum to ~1.0
    # The proposer layer will normalize, but we note it in rationale
    if adjustments:
        for adj in adjustments:
            adj["rationale"] += " (Weights will be re-normalized to sum to 1.0.)"

    return adjustments


def _offset_ts(ts: str, days: int) -> str:
    """Add days to an ISO timestamp string."""
    from datetime import datetime, timezone, timedelta
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    dt += timedelta(days=days)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
