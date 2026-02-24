# forge/USER.md — Operator Interface

Operator can:
- start/stop Forge
- request status
- request last ExecutionReport
- request cancel by client_order_id (if policy allows)

Operator cannot:
- ask Forge to "take a trade"
- ask Forge to resize or change stops
- bypass Sentinel approvals

If operator provides anything other than ApprovedOrder:
Forge must refuse and request ApprovedOrder.
