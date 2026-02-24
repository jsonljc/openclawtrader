# forge/MEMORY.md — State Model

Forge does not keep narrative memory.

Persisted state only:
- executed_client_order_ids (for idempotency)
- last_N_execution_reports (N=50)
- last_known_open_orders snapshot (optional)
- last_known_positions snapshot (optional)

Write discipline (required for crash safety):
- Before calling exchange.place_order(): write client_order_id with status="in_flight" to forge/state.json.
- After stop is confirmed live: update status to "stop_live".
- After ExecutionReport is emitted: update status to "executed" or "failed".
- On startup: any client_order_id with status="in_flight" must be reconciled against open exchange orders before Forge resumes. If the exchange shows the order exists → treat as executed and do not re-place. If not found → treat as failed and emit ExecutionReport.

Compaction rule:
- keep last 7 days of execution reports or last 200 reports (whichever smaller)
- keep idempotency set for 30 days (or configurable)
