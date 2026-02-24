# c3po/session-state.md — v0 (Compaction-Safe Snapshot)

## Identity
- agent: C3PO
- version: 0.1
- role: Strategy Brain
- contract: outputs TradeIntent only; Sentinel approves sizing/risk

## Current Scope
- primary_symbols: ["BTCUSDT"]
- secondary_symbols: []
- active_timeframes: ["15m", "1h"]
- mode: "intraday"  # intraday | swing
- data_quality: "unknown"  # unknown | partial | good

## Sentinel Interface (Read-Only)
- min_rr_required: 1.8
- max_staleness_minutes: 30
- stop_required: true
- posture: "normal"  # normal | caution | locked

## Active Hypotheses (Max 3)
1)
- thesis:
- invalidation:
- watch:

2)
- thesis:
- invalidation:
- watch:

3)
- thesis:
- invalidation:
- watch:

## Recent Decisions (Last 5)
- timestamp_utc:
  setup_id:
  symbol:
  side:
  status:  # proposed | rejected_by_sentinel | approved_by_sentinel | expired | canceled
  note:

- timestamp_utc:
  setup_id:
  symbol:
  side:
  status:
  note:

## Current Context Flags
- directional_bias: "neutral"  # long | short | neutral
- volatility_regime: "unknown"  # low | expanding | contracting | unknown
- structure: ""  # range | breakout | trend | mean_reversion | unknown

## Next Action
- next_step:
- waiting_for:
- updated_at_utc:
