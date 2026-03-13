#!/usr/bin/env python3
"""Strategy health scoring — spec Section 6.6.

Weighted components: DD, Sharpe, hit rate, execution quality.
Outputs: health_score, action (NORMAL/HALF_SIZE/DISABLE), stats.
"""

from __future__ import annotations
import math
import statistics
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))
from shared import contracts as C
from shared import ledger
from shared import state_store as store


def evaluate_strategy_health(
    strategy: dict,
    param_version: str = "PV_0001",
    asof: str | None = None,
) -> dict:
    """
    Compute strategy health from POSITION_CLOSED events (last 30 days).
    Returns health report with action for sizing modifier.
    """
    strategy_id = strategy.get("strategy_id", "")
    params = store.load_params(param_version)
    hp = params.get("health", {})
    now = asof or datetime.now(timezone.utc).isoformat()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()

    closes = [
        e for e in ledger.query(event_types=[C.EventType.POSITION_CLOSED], limit=500)
        if e.get("payload", {}).get("strategy_id") == strategy_id
        and e.get("timestamp", "") >= cutoff
    ]

    n = len(closes)
    min_trades = hp.get("min_trades_for_full_health", 10)

    if n < 3:
        health_score = 0.60
        capped = True
        action = C.HealthAction.NORMAL
        stats: dict[str, Any] = {
            "realized_dd_pct": 0.0,
            "expected_dd_pct": strategy.get("expected_max_dd_pct", 10.0),
            "realized_sharpe_30d": 0.0,
            "expected_sharpe": strategy.get("expected_sharpe", 0.7),
            "realized_hit_rate_30d": 0.0,
            "expected_hit_rate": strategy.get("expected_hit_rate", 0.45),
            "avg_slippage_ticks_30d": 1.0,
            "expected_slippage_ticks": strategy.get("expected_avg_slippage_ticks", 1.0),
            "trade_count_30d": n,
            "profit_factor_30d": 1.0,
            "avg_win_loss_ratio": 1.0,
            "consecutive_losses_current": 0,
            "consecutive_losses_max_30d": 0,
        }
    else:
        pnls = [e["payload"].get("realized_pnl", 0.0) for e in closes]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        hit_rate = len(wins) / n
        avg_win = sum(wins) / len(wins) if wins else 0.0
        avg_loss = abs(sum(losses) / len(losses)) if losses else 0.01
        wl_ratio = avg_win / avg_loss

        std = statistics.stdev(pnls) if len(pnls) > 1 else 0.01
        mean = statistics.mean(pnls)
        sharpe = (mean / std * math.sqrt(252 / 30)) if std > 0 else 0.0

        pf = abs(sum(wins)) / abs(sum(losses)) if losses else 2.0

        # Use actual portfolio equity as base for drawdown calculation
        base_equity = store.load_portfolio()["account"]["equity_usd"]
        equity = base_equity
        peak = base_equity
        max_dd = 0.0
        for p in pnls:
            equity += p
            peak = max(peak, equity)
            dd = (peak - equity) / peak * 100.0 if peak > 0 else 0.0
            max_dd = max(max_dd, dd)

        consec = 0
        max_consec = 0
        for p in pnls:
            if p < 0:
                consec += 1
                max_consec = max(max_consec, consec)
            else:
                consec = 0

        exp_dd = strategy.get("expected_max_dd_pct", 10.0)
        exp_sharpe = strategy.get("expected_sharpe", 1.2)
        exp_hr = strategy.get("expected_hit_rate", 0.45)
        exp_slip = strategy.get("expected_avg_slippage_ticks", 1.0)

        exec_quality_raw = store.load_exec_quality().get(strategy_id, {})
        avg_slip_30d = exec_quality_raw.get("avg_realized_slippage_ticks_20", 1.0)

        dd_ratio = max(0.0, min(1.0, 1.0 - max_dd / exp_dd)) if exp_dd > 0 else 1.0
        sharpe_rat = max(0.0, min(1.0, sharpe / exp_sharpe)) if exp_sharpe > 0 else 0.5
        hr_ratio = max(0.0, min(1.0, hit_rate / exp_hr)) if exp_hr > 0 else 0.5
        eq_ratio = max(0.0, min(1.0, 1.0 - (avg_slip_30d - exp_slip) / (exp_slip + 0.001)))

        w = hp
        health_score = (
            w.get("weight_dd", 0.35) * dd_ratio
            + w.get("weight_sharpe", 0.25) * sharpe_rat
            + w.get("weight_hit_rate", 0.20) * hr_ratio
            + w.get("weight_execution", 0.20) * eq_ratio
        )
        capped = n < min_trades
        if capped:
            health_score = min(health_score, 0.60)

        disable_thresh = hp.get("disable_threshold", 0.30)
        half_thresh = hp.get("half_size_threshold", 0.50)
        if health_score < disable_thresh:
            action = C.HealthAction.DISABLE
        elif health_score < half_thresh:
            action = C.HealthAction.HALF_SIZE
        else:
            action = C.HealthAction.NORMAL

        stats = {
            "realized_dd_pct": round(max_dd, 4),
            "expected_dd_pct": exp_dd,
            "realized_sharpe_30d": round(sharpe, 4),
            "expected_sharpe": exp_sharpe,
            "realized_hit_rate_30d": round(hit_rate, 4),
            "expected_hit_rate": exp_hr,
            "avg_slippage_ticks_30d": round(avg_slip_30d, 2),
            "expected_slippage_ticks": exp_slip,
            "trade_count_30d": n,
            "profit_factor_30d": round(pf, 4),
            "avg_win_loss_ratio": round(wl_ratio, 4),
            "consecutive_losses_current": consec,
            "consecutive_losses_max_30d": max_consec,
        }

    return C.make_health_report(
        strategy_id=strategy_id,
        asof=now,
        param_version=param_version,
        health_score=health_score,
        health_score_capped=capped,
        action=action,
        components={},
        stats=stats,
    )
