# forge/EXECUTION_REPORT_SCHEMA.md — v0

Forge outputs ONLY this JSON envelope:

```json
{
  "type": "ExecutionReport",
  "version": "0.1",
  "timestamp_utc": "<ISO8601>",
  "client_order_id": "<string>",
  "symbol": "<string>",
  "status": "ACCEPTED" | "REJECTED_PRECHECK" | "ENTRY_PLACED" | "STOP_PLACED" | "TARGETS_PLACED" | "COMPLETED" | "FAILED" | "CRITICAL_STOP_NOT_PLACED",
  "steps": [
    { "name": "preflight", "ok": true|false, "detail": "<short>" },
    { "name": "idempotency", "ok": true|false, "detail": "<short>" },
    { "name": "place_entry", "ok": true|false, "detail": "<short>", "exchange_order_id": "<optional>" },
    { "name": "place_stop", "ok": true|false, "detail": "<short>", "exchange_order_id": "<optional>" },
    { "name": "place_targets", "ok": true|false, "detail": "<short>" }
  ],
  "fills": {
    "avg_entry_price": <number|null>,
    "filled_size": <number|null>,
    "fees_usd": <number|null>
  },
  "error": {
    "code": "<string|null>",
    "message": "<string|null>",
    "last_successful_step": "<string|null>"
  }
}
```

Hard rule:
- No extra keys.
- If anything is unknown, use null.
