#!/usr/bin/env python3
"""
write_edge_health.py
Applies degradation rules to edge metrics and writes EDGE_HEALTH.json.
Sentinel reads this file on startup and weekly to adjust posture.

Degradation rules per spec §6.2:
  INSUFFICIENT_DATA : trade_count_30d < 30 → degrade_flag stays false, posture unchanged
  DEGRADE triggers  : expectancy_30d_r < 0
                      OR (expectancy_7d_r < -0.5 AND trade_count_7d > 10)

Commission / slippage are baked into the R multiples by the backtest.

Usage:
    python3 write_edge_health.py --metrics-file /tmp/edge_metrics.json
    python3 write_edge_health.py --metrics-file /tmp/edge_metrics.json \
                                  --out ~/openclaw-trader/out/EDGE_HEALTH.json
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_OUT = Path.home() / "openclaw-trader" / "out" / "EDGE_HEALTH.json"

MIN_TRADES_30D = 30   # §6 — minimum sample before degrade rules apply


def evaluate_degradation(metrics: dict) -> tuple[bool, str, list[str]]:
    """
    Returns (degrade_flag, status, reasons).
    status: "INSUFFICIENT_DATA" | "DEGRADED" | "HEALTHY"
    """
    trade_count_30d  = metrics.get("trade_count_30d",  metrics.get("trade_count", 0))
    expectancy_30d_r = metrics.get("expectancy_30d_r", metrics.get("expectancy_r"))
    expectancy_7d_r  = metrics.get("expectancy_7d_r")
    trade_count_7d   = metrics.get("trade_count_7d", 0)

    # Gate: insufficient data → don't set degrade flag
    if trade_count_30d < MIN_TRADES_30D:
        return (
            False,
            "INSUFFICIENT_DATA",
            [f"Only {trade_count_30d} trades in 30d window (need {MIN_TRADES_30D}) — posture unchanged"]
        )

    reasons = []

    # Primary degrade rule: 30d expectancy negative
    if expectancy_30d_r is not None and expectancy_30d_r < 0:
        reasons.append(
            f"expectancy_30d_r={expectancy_30d_r:.3f}R < 0 — edge below breakeven"
        )

    # Secondary degrade rule: short-term collapse with sufficient sample
    if (expectancy_7d_r is not None
            and expectancy_7d_r < -0.5
            and trade_count_7d > 10):
        reasons.append(
            f"expectancy_7d_r={expectancy_7d_r:.3f}R < -0.5R "
            f"with trade_count_7d={trade_count_7d} > 10"
        )

    if reasons:
        return True, "DEGRADED", reasons
    return False, "HEALTHY", []


def recommend_posture(metrics: dict, status: str) -> str:
    """Recommend posture based on edge health status."""
    if status == "INSUFFICIENT_DATA":
        return "UNCHANGED"
    exp_30d = metrics.get("expectancy_30d_r", metrics.get("expectancy_r", 0.0))
    exp_7d  = metrics.get("expectancy_7d_r")
    if exp_30d is not None and exp_30d < 0:
        return "REDUCED"
    if exp_7d is not None and exp_7d < -0.5:
        return "REDUCED"
    return "NORMAL"


def main():
    parser = argparse.ArgumentParser(description="Write EDGE_HEALTH.json for Sentinel")
    parser.add_argument("--metrics-file", required=True)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args()

    try:
        metrics = json.loads(Path(args.metrics_file).read_text())
    except FileNotFoundError:
        print(json.dumps({"error": f"Metrics file not found: {args.metrics_file}"}))
        sys.exit(1)

    degrade_flag, status, reasons = evaluate_degradation(metrics)
    recommended_posture            = recommend_posture(metrics, status)

    ts = datetime.now(timezone.utc).isoformat()
    output = {
        "schema_version":      "0.1",
        "generated_at":        ts,
        "generated_at_utc":     ts,
        "status":              status,
        "symbol":              "GLOBAL",
        "period":              metrics.get("backtest_period", {}),
        "demo_mode":           metrics.get("demo_mode", False),
        "metrics": {
            "trade_count":      metrics.get("trade_count"),
            "trade_count_30d":  metrics.get("trade_count_30d"),
            "trade_count_7d":   metrics.get("trade_count_7d"),
            "expectancy_r":     metrics.get("expectancy_r"),
            "expectancy_30d_r": metrics.get("expectancy_30d_r"),
            "expectancy_7d_r":  metrics.get("expectancy_7d_r"),
            "win_rate":         metrics.get("win_rate"),
            "avg_r_winner":     metrics.get("avg_r_winner"),
            "avg_r_loser":      metrics.get("avg_r_loser"),
            "max_drawdown_r":   metrics.get("max_drawdown_r"),
            "sharpe_approx":    metrics.get("sharpe_approx"),
        },
        "tier_breakdown":      metrics.get("tier_breakdown", {}),
        "degrade_flag":        degrade_flag,
        "degrade_reason":      reasons if degrade_flag else None,
        "recommended_posture": recommended_posture,
    }

    out_str = json.dumps(output, indent=2)
    print(out_str)

    out_path = Path(args.out).expanduser()
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(out_str)
        print(f"[edge-health] Written to {out_path}", file=sys.stderr)
    except OSError as e:
        print(f"[edge-health] Warning: could not write {out_path}: {e}", file=sys.stderr)

    if status == "INSUFFICIENT_DATA":
        print(f"[edge-health] INSUFFICIENT_DATA — posture unchanged", file=sys.stderr)
    elif degrade_flag:
        print(f"[edge-health] DEGRADE FLAG SET: {reasons}", file=sys.stderr)
        print(f"[edge-health] Recommended posture: {recommended_posture}", file=sys.stderr)
    else:
        print(f"[edge-health] HEALTHY — recommended posture: {recommended_posture}", file=sys.stderr)


if __name__ == "__main__":
    main()
