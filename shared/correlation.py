#!/usr/bin/env python3
"""Rolling 20d correlation between strategy returns — Phase 3.

Uses POSITION_CLOSED events: daily PnL per strategy, then pairwise correlation.
"""

from __future__ import annotations
import math
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Any

from shared import contracts as C
from shared import ledger


def _daily_pnl_by_strategy(lookback_days: int = 30) -> dict[str, dict[str, float]]:
    """Return {strategy_id: {date_str: daily_pnl}} for the lookback period."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).isoformat()
    entries = ledger.query(event_types=[C.EventType.POSITION_CLOSED], limit=500)
    by_strategy: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for e in entries:
        if e.get("timestamp", "") < cutoff:
            continue
        p = e.get("payload", {})
        sid = p.get("strategy_id", "")
        if not sid:
            continue
        date_str = e["timestamp"][:10]
        by_strategy[sid][date_str] += p.get("realized_pnl", 0.0)
    return dict(by_strategy)


def compute_correlations_20d(
    lookback_days: int = 30,
    window_days: int = 20,
) -> dict[str, float]:
    """
    Compute pairwise correlation of daily PnL over the last window_days.
    Returns dict mapping "strategy_id_a|strategy_id_b" -> correlation in [-1, 1].
    """
    daily = _daily_pnl_by_strategy(lookback_days)
    strategies = sorted(daily.keys())
    if len(strategies) < 2:
        return {}

    # Build date set for last window_days
    today = datetime.now(timezone.utc).date()
    dates = [(today - timedelta(days=i)).isoformat() for i in range(window_days)]
    date_set = set(dates)

    # Series per strategy (aligned to dates)
    series: dict[str, list[float]] = {}
    for sid in strategies:
        series[sid] = [daily[sid].get(d, 0.0) for d in dates]

    result: dict[str, float] = {}
    for i, a in enumerate(strategies):
        for b in strategies[i + 1:]:
            va = series[a]
            vb = series[b]
            n = len(va)
            mean_a = sum(va) / n
            mean_b = sum(vb) / n
            var_a = sum((x - mean_a) ** 2 for x in va) / max(n, 1)
            var_b = sum((x - mean_b) ** 2 for x in vb) / max(n, 1)
            if var_a <= 0 or var_b <= 0:
                corr = 0.0
            else:
                cov = sum((va[j] - mean_a) * (vb[j] - mean_b) for j in range(n)) / n
                corr = cov / math.sqrt(var_a * var_b)
            corr = max(-1.0, min(1.0, corr))
            key = f"{a}|{b}"
            result[key] = round(corr, 4)
    return result


def update_portfolio_heat_correlations(portfolio: dict) -> None:
    """Update portfolio.heat.correlations_20d in place and persist."""
    from shared import state_store as store
    corrs = compute_correlations_20d()
    portfolio.setdefault("heat", {})["correlations_20d"] = corrs
    store.save_portfolio(portfolio)
