#!/usr/bin/env python3
"""
compute_edge_metrics.py
Computes expectancy, win rate, Sharpe, and max drawdown from backtest results.

Usage:
    python3 compute_edge_metrics.py --backtest-file /tmp/backtest_result.json
    python3 compute_edge_metrics.py --backtest-file /tmp/backtest_result.json --out /tmp/edge_metrics.json
"""

import argparse
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path


def compute_metrics(trades: list[dict]) -> dict:
    """Compute all edge quality metrics from a list of trade results."""
    valid = [t for t in trades if t.get("outcome") in ("WIN", "LOSS", "EXPIRED")]
    if not valid:
        return {
            "trade_count": 0,
            "error": "No valid trades to analyze",
        }

    wins   = [t for t in valid if t["outcome"] == "WIN"]
    losses = [t for t in valid if t["outcome"] == "LOSS"]
    expired = [t for t in valid if t["outcome"] == "EXPIRED"]

    n = len(valid)
    win_rate = len(wins) / n

    r_series = [t["r_multiple"] for t in valid]
    expectancy = sum(r_series) / n

    avg_r_winner = sum(t["r_multiple"] for t in wins) / len(wins) if wins else 0.0
    avg_r_loser  = sum(t["r_multiple"] for t in losses) / len(losses) if losses else 0.0

    # Max drawdown in R (peak-to-trough on cumulative R curve)
    cum_r = 0.0
    peak  = 0.0
    max_dd = 0.0
    for r in r_series:
        cum_r += r
        peak = max(peak, cum_r)
        dd = cum_r - peak
        max_dd = min(max_dd, dd)

    # Approximate Sharpe (R-based, not annualized)
    mean_r = expectancy
    if n > 1:
        variance = sum((r - mean_r) ** 2 for r in r_series) / (n - 1)
        std_r = variance ** 0.5
        sharpe = mean_r / std_r if std_r > 0 else 0.0
    else:
        sharpe = 0.0

    # Per-tier breakdown (support both old TIER_A/B/C and new HIGH/MED names)
    tier_breakdown = {}
    for tier in ("HIGH", "MED", "TIER_A", "TIER_B", "TIER_C"):
        tier_trades = [t for t in valid if t.get("confidence_tier") == tier]
        if tier_trades:
            tier_wins = [t for t in tier_trades if t["outcome"] == "WIN"]
            tier_breakdown[tier] = {
                "count": len(tier_trades),
                "win_rate": round(len(tier_wins) / len(tier_trades), 3),
                "expectancy_r": round(sum(t["r_multiple"] for t in tier_trades) / len(tier_trades), 3),
            }

    return {
        "trade_count": n,
        "win_count": len(wins),
        "loss_count": len(losses),
        "expired_count": len(expired),
        "win_rate": round(win_rate, 4),
        "expectancy_r": round(expectancy, 4),
        "avg_r_winner": round(avg_r_winner, 4),
        "avg_r_loser": round(avg_r_loser, 4),
        "total_r": round(sum(r_series), 3),
        "max_drawdown_r": round(max_dd, 3),
        "sharpe_approx": round(sharpe, 3),
        "tier_breakdown": tier_breakdown,
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }


def main():
    parser = argparse.ArgumentParser(description="Compute edge health metrics from backtest")
    parser.add_argument("--backtest-file", required=True)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    try:
        data = json.loads(Path(args.backtest_file).read_text())
    except FileNotFoundError:
        print(json.dumps({"error": f"File not found: {args.backtest_file}"}))
        sys.exit(1)

    trades = data.get("trades", [])
    now    = datetime.now(timezone.utc)

    metrics = compute_metrics(trades)
    metrics["backtest_period"] = data.get("period", {})
    metrics["demo_mode"]       = data.get("demo_mode", False)

    # Compute 7-day and 30-day rolling window metrics
    cutoff_7d  = now - timedelta(days=7)
    cutoff_30d = now - timedelta(days=30)

    def parse_ts(t):
        ts = t.get("ts", "")
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except Exception:
            return None

    trades_7d  = [t for t in trades if (dt := parse_ts(t)) and dt >= cutoff_7d]
    trades_30d = [t for t in trades if (dt := parse_ts(t)) and dt >= cutoff_30d]

    def simple_expectancy(tlist):
        valid = [t for t in tlist if t.get("outcome") in ("WIN", "LOSS", "EXPIRED")]
        if not valid:
            return None, 0
        return round(sum(t["r_multiple"] for t in valid) / len(valid), 4), len(valid)

    exp_7d,  cnt_7d  = simple_expectancy(trades_7d)
    exp_30d, cnt_30d = simple_expectancy(trades_30d)

    metrics["expectancy_7d_r"]    = exp_7d
    metrics["trade_count_7d"]     = cnt_7d
    metrics["expectancy_30d_r"]   = exp_30d
    metrics["trade_count_30d"]    = cnt_30d

    out = json.dumps(metrics, indent=2)
    print(out)

    if args.out:
        try:
            Path(args.out).write_text(out)
        except OSError as e:
            print(f"[edge-metrics] Warning: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
