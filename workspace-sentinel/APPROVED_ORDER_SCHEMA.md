# APPROVED_ORDER_SCHEMA.md — Sentinel v0

Authoritative ApprovedOrder shape emitted by Sentinel when a TradeIntent passes all risk checks.

```json
{
  "kind": "ApprovedOrder",
  "client_order_id": "<symbol>-<side>-<ISO8601>",
  "symbol": "BTCUSDT",
  "side": "LONG|SHORT",
  "venue": "binance",
  "instrument_type": "spot|perp",
  "order_type": "MARKET|LIMIT",
  "entry_price": <number|null>,
  "size": <number>,
  "stop_price": <number>,
  "stop_order_type": "STOP_LIMIT|STOP_MARKET",
  "targets": [{ "price": <number>, "logic": "<string>" }],
  "valid_until_ts_utc": "<ISO8601>",
  "posture": "normal|caution|locked",
  "constraints": {
    "max_slippage_bps": 30,
    "time_in_force": "IOC",
    "reduce_only_flags": false
  },
  "risk_pct": <number>,
  "approved_at": "<ISO8601>"
}
```

Forge reads from ~/openclaw-trader/out/risk_decision.json. Reject if kind != "ApprovedOrder".
