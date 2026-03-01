---
name: edge-health
description: Weekly walk-forward backtest of trend_pullback_reclaim_v1. Produces EDGE_HEALTH.json with degrade_flag. Read by Sentinel to adjust posture.
user-invocable: true
metadata: {"openclaw":{"emoji":"📊","requires":{"bins":["python3"]}}}
---

# edge-health

## Purpose
Self-monitoring subsystem for C3PO. Runs once per week. Evaluates whether the strategy's edge is intact using a walk-forward backtest on the C3PO signal log.

**Sentinel reads `EDGE_HEALTH.json` on startup and weekly. If `degrade_flag: true`, Sentinel moves to REDUCED posture automatically.**

## Tools available
Use the `exec` tool to run scripts in `{baseDir}/scripts/`.

---

## Functions

### run_backtest
Runs a walk-forward backtest on the C3PO signal log.
- Training window: 90 days
- Test window: 30 days
- Evaluates each signal in the test window using actual price data

```
exec: python3 {baseDir}/scripts/run_backtest.py \
    --signal-log-dir ~/openclaw-trader/out/c3po-log \
    --snapshot-dir ~/openclaw-trader/out/snapshots \
    --out /tmp/backtest_result.json
```

---

### compute_edge_metrics
Computes expectancy, win rate, Sharpe, and max drawdown from backtest results.

```
exec: python3 {baseDir}/scripts/compute_edge_metrics.py \
    --backtest-file /tmp/backtest_result.json \
    --out /tmp/edge_metrics.json
```

Output contract:
```json
{
  "expectancy_r": 0.18,
  "win_rate": 0.52,
  "avg_r_winner": 1.9,
  "avg_r_loser": -1.0,
  "trade_count": 45,
  "max_drawdown_r": -4.2,
  "sharpe_approx": 1.1,
  "computed_at": "..."
}
```

---

### write_edge_health
Applies degradation rules and writes `EDGE_HEALTH.json`.

```
exec: python3 {baseDir}/scripts/write_edge_health.py \
    --metrics-file /tmp/edge_metrics.json \
    --out ~/openclaw-trader/out/EDGE_HEALTH.json
```

Degradation rules (any triggers `degrade_flag: true`):
- expectancy_r < 0.10 (edge below breakeven after costs)
- win_rate < 0.40
- max_drawdown_r < -6.0 (drawdown > 6R)
- trade_count < 10 (insufficient sample)

---

## Usage pattern

Run weekly (Sunday UTC):
1. `run_backtest`
2. `compute_edge_metrics`
3. `write_edge_health`
4. Sentinel reads `EDGE_HEALTH.json` on next run

## What this skill will NOT do
- Modify strategy parameters
- Change risk settings directly
- Execute trades
