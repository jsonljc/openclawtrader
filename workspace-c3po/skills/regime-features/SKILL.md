---
name: regime-features
description: Compute ATR, volatility regime, and trend/range classifier from a market snapshot. Pure analysis, no I/O, no execution.
user-invocable: true
metadata: {"openclaw":{"emoji":"🧠","requires":{"bins":["python3"]}}}
---

# regime-features

## Purpose
Transforms raw OHLCV data from `market-snapshot` into structured regime features. **No network calls. No writes. No execution.** Input → computation → output object only.

## Dependency
Requires a valid (non-stale) snapshot from `market-snapshot`. Do not call this skill with a stale snapshot (`stale: true`). If snapshot is stale, abort and surface to operator.

## Tools available
Use the `exec` tool to run scripts in `{baseDir}/scripts/`.

---

## Functions

### compute_atr
Computes ATR(14) across all available timeframes using Wilder's smoothing.

```
exec: python3 {baseDir}/scripts/compute_atr.py --snapshot-file <path_to_snapshot.json>
```

Output contract:
```json
{
  "atr": {
    "1m":  { "value": 18.50, "atr_pct": 0.027 },
    "5m":  { "value": 42.10, "atr_pct": 0.062 },
    "15m": { "value": 87.30, "atr_pct": 0.128 },
    "1h":  { "value": 210.50, "atr_pct": 0.309 },
    "4h":  { "value": 480.20, "atr_pct": 0.705 }
  },
  "computed_at": "2025-01-15T14:23:05.000Z"
}
```

`atr_pct` = ATR / close price × 100. Used downstream for position sizing in Sentinel.

---

### compute_volatility_regime
Classifies current volatility as `LOW`, `NORMAL`, `ELEVATED`, or `EXTREME` based on ATR percentile over a rolling 20-period window.

```
exec: python3 {baseDir}/scripts/compute_volatility_regime.py --snapshot-file <path_to_snapshot.json>
```

Output contract:
```json
{
  "regime": "ELEVATED",
  "atr_percentile": 78.4,
  "reference_timeframe": "1h",
  "thresholds": { "LOW": 25, "NORMAL": 60, "ELEVATED": 85, "EXTREME": 100 },
  "computed_at": "2025-01-15T14:23:06.000Z"
}
```

Regime definitions (1h ATR percentile):
- `LOW` — < 25th percentile
- `NORMAL` — 25–60th
- `ELEVATED` — 60–85th
- `EXTREME` — > 85th → Sentinel should reduce posture automatically

---

### classify_trend_range
Returns a trend/range classification for each timeframe using EMA cross (9/21) and ADX(14).

```
exec: python3 {baseDir}/scripts/classify_trend_range.py --snapshot-file <path_to_snapshot.json>
```

Output contract:
```json
{
  "classifications": {
    "15m": { "type": "TREND_UP",   "adx": 32.1, "ema_cross": "bullish", "confidence": "HIGH" },
    "1h":  { "type": "RANGE",      "adx": 18.4, "ema_cross": "neutral", "confidence": "MEDIUM" },
    "4h":  { "type": "TREND_DOWN", "adx": 28.7, "ema_cross": "bearish", "confidence": "HIGH" }
  },
  "htf_bias": "BEARISH",
  "computed_at": "2025-01-15T14:23:07.000Z"
}
```

Classification logic:
- ADX < 20 → `RANGE`
- ADX ≥ 20 + EMA bullish → `TREND_UP`
- ADX ≥ 20 + EMA bearish → `TREND_DOWN`
- `htf_bias` derived from 4h classification — used by Sentinel for directional gating

Confidence levels:
- `HIGH` — ADX > 25 and unambiguous EMA cross
- `MEDIUM` — ADX 20–25 or EMA cross recent
- `LOW` — conflicting signals; C3PO should output NO_TRADE

---

## Full regime object (composed output)
After running all three functions, compose and write to a temp file for Sentinel:

```json
{
  "snapshot_ts": "<from market-snapshot>",
  "stale": false,
  "atr": { ... },
  "volatility_regime": { ... },
  "trend_classification": { ... },
  "regime_summary": {
    "tradeable": true,
    "reason": "NORMAL volatility, TREND_UP on 15m, BEARISH htf_bias — counter-trend caution",
    "suggested_posture": "REDUCED"
  }
}
```

`tradeable: false` must be set when:
- Any timeframe returns `stale: true`
- Volatility regime is `EXTREME`
- ADX confidence is `LOW` on the trading timeframe

## Exit codes
- `0` — ok
- `2` — stale snapshot rejected
- `3` — EXTREME volatility (halt gate)
- `1` — computation error

## What this skill will NOT do
- Fetch market data itself
- Place orders or read balances
- Write to `field_notes.md` (that is `memory-append`'s job)
- Make sizing decisions (that is Sentinel's job)
