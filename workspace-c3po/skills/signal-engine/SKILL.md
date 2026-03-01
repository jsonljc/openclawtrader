---
name: signal-engine
description: Evaluate trend_pullback_reclaim_v1 signal against regime and snapshot. Returns scored TradeIntent candidate or NO_TRADE. No network calls. No execution.
user-invocable: true
metadata: {"openclaw":{"emoji":"🎯","requires":{"bins":["python3"]}}}
---

# signal-engine

## Purpose
Applies the `trend_pullback_reclaim_v1` strategy rules to the current regime object and OHLCV snapshot.
Three sequential gates: session filter → 6-condition evaluator → confidence scorer.
All three must pass for C3PO to emit a TradeIntent.

## Dependency
Requires:
- Valid (non-stale) snapshot from `market-snapshot` at `/tmp/c3po_snapshot.json`
- Regime object output from `regime-features`

## Tools available
Use the `exec` tool to run scripts in `{baseDir}/scripts/`.

---

## Gate 1 — session_filter

Hard gate. Must be called first. Blocks trading during low-liquidity UTC windows.

```
exec: python3 {baseDir}/scripts/session_filter.py
exec: python3 {baseDir}/scripts/session_filter.py --hour <UTC_HOUR>
```

Output contract:
```json
{
  "status": "PASS",
  "hour_utc": 14,
  "session": "london_ny_overlap",
  "reason": null
}
```
or:
```json
{
  "status": "BLOCK",
  "hour_utc": 22,
  "session": "dead_zone",
  "reason": "Low liquidity window — no new signals"
}
```

Exit codes: `0` = PASS, `1` = BLOCK

---

## Gate 2 — evaluate_signal

Checks all 6 required conditions for `trend_pullback_reclaim_v1`.

```
exec: python3 {baseDir}/scripts/evaluate_signal.py \
    --snapshot-file /tmp/c3po_snapshot.json \
    --regime-file /tmp/c3po_regime.json \
    --side LONG
```

Arguments:
- `--snapshot-file` — path to market snapshot
- `--regime-file` — path to composed regime object from regime-features
- `--side` — `LONG` or `SHORT` (operator or C3PO proposes direction)

Output contract:
```json
{
  "side": "LONG",
  "conditions_met": 6,
  "conditions_required": 6,
  "pass": true,
  "conditions": {
    "htf_trend_aligned":    { "pass": true,  "detail": "4h TREND_DOWN, side=LONG → fail" },
    "ltf_trending":         { "pass": true,  "detail": "15m ADX=28.4 > 20" },
    "ema_cross_aligned":    { "pass": true,  "detail": "15m EMA cross bullish" },
    "regime_tradeable":     { "pass": true,  "detail": "NORMAL volatility" },
    "pullback_to_ema":      { "pass": true,  "detail": "price within 0.5x ATR of EMA21" },
    "reclaim_candle":       { "pass": true,  "detail": "close above EMA21" }
  },
  "entry_price": 63100.0,
  "stop_price": 62600.0,
  "stop_logic": "Below swing low — 1x ATR buffer",
  "target_1": 64100.0,
  "target_2": 64600.0,
  "atr_15m": 480.0,
  "evaluated_at": "2025-01-15T14:23:10.000Z"
}
```

Exit codes: `0` = all 6 pass, `1` = fewer than 6 conditions met, `2` = data error

---

## Gate 3 — score_signal

Scores the signal 0–100 and assigns a confidence tier.

```
exec: python3 {baseDir}/scripts/score_signal.py \
    --eval-file /tmp/c3po_eval.json \
    --regime-file /tmp/c3po_regime.json
```

Output contract:
```json
{
  "score": 78,
  "tier": "TIER_B",
  "size_multiplier": 0.75,
  "pass": true,
  "breakdown": {
    "htf_alignment":    { "points": 25, "max": 25, "reason": "Strong 4h trend alignment" },
    "adx_strength":     { "points": 15, "max": 20, "reason": "ADX 28 — moderate trend" },
    "volatility_regime":{ "points": 15, "max": 15, "reason": "NORMAL regime" },
    "pullback_quality": { "points": 10, "max": 15, "reason": "Shallow pullback to EMA" },
    "ema_distance":     { "points": 8,  "max": 10, "reason": "Close near EMA, not extended" },
    "session_quality":  { "points": 5,  "max": 15, "reason": "London session, acceptable" }
  },
  "scored_at": "2025-01-15T14:23:11.000Z"
}
```

Tiers:
- `TIER_A`: 80–100 → size_multiplier 1.0
- `TIER_B`: 65–79 → size_multiplier 0.75
- `TIER_C`: 50–64 → size_multiplier 0.5
- `BLOCK`: <50 → size_multiplier 0.0 → NO_TRADE, never forwarded to Sentinel

Exit codes: `0` = score ≥ 50, `1` = score < 50 (BLOCK), `2` = data error

---

## Usage pattern

Always call in this order:
1. `session_filter` — if BLOCK, stop immediately and emit NO_TRADE
2. `evaluate_signal --side LONG` and `evaluate_signal --side SHORT` — pick best passing side (or neither)
3. `score_signal` — if <50, emit NO_TRADE

Results feed directly into `brain.py` to build the TradeIntent.

## What this skill will NOT do
- Fetch market data
- Size positions (that is Sentinel's job)
- Place orders
- Override Sentinel
