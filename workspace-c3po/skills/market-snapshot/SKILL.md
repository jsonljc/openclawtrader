---
name: market-snapshot
description: Fetch live BTCUSD price and multi-timeframe OHLCV from Binance. Includes staleness check. Read-only. No execution.
user-invocable: true
metadata: {"openclaw":{"emoji":"📡","requires":{"bins":["python3"],"env":["BINANCE_API_KEY","BINANCE_API_SECRET"]},"primaryEnv":"BINANCE_API_KEY"}}
---

# market-snapshot

## Purpose
Fetch a timestamped, staleness-checked market snapshot for BTCUSD. This skill is **read-only**. It never places orders or touches balances.

## Tools available
Use the `exec` tool to run the Python scripts in `{baseDir}/scripts/`.

## Functions

### get_price
Returns the current mid-price and bid/ask spread.

```
exec: python3 {baseDir}/scripts/get_price.py
```

Output contract:
```json
{
  "symbol": "BTCUSDT",
  "bid": 68100.00,
  "ask": 68105.50,
  "mid": 68102.75,
  "spread_bps": 0.8,
  "ts": "2025-01-15T14:23:01.123Z",
  "stale": false
}
```

`stale: true` is set if the exchange timestamp is >5 seconds behind wall clock.

---

### get_ohlcv
Fetches OHLCV candles for multiple timeframes in one call.

```
exec: python3 {baseDir}/scripts/get_ohlcv.py --timeframes 1m 5m 15m 1h 4h --limit 100
```

Output contract:
```json
{
  "symbol": "BTCUSDT",
  "fetched_at": "2025-01-15T14:23:01.123Z",
  "stale": false,
  "timeframes": {
    "1m":  [{"ts": 1736951381000, "o": 68100, "h": 68150, "l": 68080, "c": 68120, "v": 12.34}],
    "5m":  [],
    "15m": [],
    "1h":  [],
    "4h":  []
  }
}
```

Arguments:
- `--timeframes` — space-separated list (default: `1m 5m 15m 1h 4h`)
- `--limit` — candles per timeframe (default: `100`, max: `500`)
- `--out` — optional path to write snapshot file (default: `/tmp/c3po_snapshot.json`)

---

### staleness_check (helper)
Call this before using any snapshot for a decision. Returns `ok` or `stale` with age in ms.

```
exec: python3 {baseDir}/scripts/staleness_check.py --ts <ISO_TIMESTAMP>
```

Rule: if `stale: true` is returned, **do not pass this snapshot to regime_features or any decision logic**. Log the stale event and retry once. If still stale, halt and surface to operator.

---

## Usage pattern

Always call in this order:
1. `get_price` — confirm market is live
2. `staleness_check` on the returned `ts`
3. `get_ohlcv` — fetch candles needed for analysis
4. Pass the full snapshot object downstream to `regime-features`

Never cache a snapshot across agent turns. Each turn requires a fresh fetch.

## Exit codes
- `0` — fresh, ok
- `2` — stale (do not proceed with downstream analysis)
- `1` — error (network, parse, or auth failure)

## What this skill will NOT do
- Place orders
- Read or write account balance
- Modify any state file
