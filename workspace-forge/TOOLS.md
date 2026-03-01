# Forge Tools

## Core Modules

| Module | Purpose |
|--------|---------|
| `forge.py` | Execution engine: order placement, bracket management |
| `paper_broker.py` | Paper trading simulator (realistic fills) |
| `slippage_model.py` | Slippage estimation model |
| `fees_model.py` | Fee calculations |

## Execution States

```
PENDING → SENT → FILLED → COMPLETE
                        ↓
               PARTIALLY_FILLED → FILLED / CANCELLED_REMAINDER
                     ↓
              REJECTED (terminal)
              TIMED_OUT (terminal)
              EMERGENCY_FLATTENED (terminal)
```

## Paper Trading Configuration

Controlled via `PV_XXXX.json` slippage section:

| Parameter | Default | Effect |
|-----------|---------|--------|
| `base_ticks` | 1 | Base slippage on market orders |
| `vol_threshold_low` | 0.50 | Vol percentile where slippage starts rising |
| `vol_threshold_high` | 0.80 | Vol percentile where slippage spikes |
| `session_factor_extended` | 1.5× | Overnight session slippage multiplier |

Simulated resilience testing:
- 2% random reject rate
- 10% partial fill rate (orders > 3 contracts)
- 100–500ms fill latency
- All seeds logged for reproducibility

## Bracket Order Monitoring

Brackets are verified every 15-minute reconciliation cycle.

If a stop order is found missing:
1. Replace immediately
2. If replacement fails → flatten position
3. Log as `EMERGENCY_FLATTENED`
4. Alert Watchtower

## Live Trading (Future)

`forge.py` raises `NotImplementedError` for live execution. To add live support:
1. Implement exchange API client
2. Replace `PaperBroker` with live broker in `execute_approval()`
3. Test with 25% of paper size (see Paper-to-Live Transition protocol)
