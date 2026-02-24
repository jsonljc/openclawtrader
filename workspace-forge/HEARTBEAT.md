# forge/HEARTBEAT.md — Runtime Health

Emit a heartbeat on every run cycle and after every execution attempt:

Required fields:
- timestamp_utc
- mode: idle|executing|error
- last_seen_approved_order_id
- last_execution_status
- open_orders_count
- positions_summary (symbol + size only)
- error_count_last_1h

If exchange connectivity fails:
- set mode=error
- do not execute any orders
- emit heartbeat with error_code=EXCHANGE_DOWN
