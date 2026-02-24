# C3PO — Learning Strategy Agent (Brain)

Intent generation engine that learns from outcomes.

## Overview

C3PO parses market context and generates TradeIntent proposals in strict JSON format. It does not execute trades or manage risk — it only proposes setups that feed into Sentinel (the risk officer).

## Philosophy

- Signal quality > trade frequency
- Fewer, cleaner, higher-conviction intents
- Learn from every outcome
- Deterministic, auditable outputs

## Files

```
workspace-c3po/
├── c3po/           # Session state and field notes
├── AGENTS.md       # Role and execution model
├── SOUL.md         # Core traits and TradeIntent schema
├── TOOLS.md        # 6 controlled tools
├── IDENTITY.md     # Authority and constraints
├── USER.md         # Operator interaction
├── HEARTBEAT.md    # Health monitoring
└── README.md       # This file
```

## Output Format

TradeIntent JSON envelope:
```json
{
  "type": "TradeIntent",
  "version": "0.1",
  "timestamp_utc": "2026-02-24T10:30:00Z",
  "intent": {
    "symbol": "BTCUSDT",
    "side": "LONG",
    "entry": {"type": "MARKET", "price": null},
    "stop": {"price": 59400, "logic": "below swing low"},
    "targets": [{"price": 61200, "logic": "2R target"}],
    "timeframe": "15m",
    "setup_id": "BTCUSDT-15m-LONG-MARKET-60000-59400-v0",
    "expiry_ts_utc": "2026-02-24T11:30:00Z",
    "confidence": 0.72
  },
  "notes": {
    "thesis": "BOS above EMA200 with volume confirmation",
    "key_levels": ["60000", "59400", "61200"],
    "assumptions": ["volatility remains medium"],
    "invalidated_by": ["close below 59400 before entry"]
  }
}
```

## Quality Gates

Reject to NO_TRADE if:
- Stop price missing or wrong side of entry
- Thesis vague without invalidation
- Confidence < 0.55 without asymmetric setup
- Duplicate setup_id without new info

## Learning Loop

After each trade outcome or Sentinel rejection, append to c3po/field_notes.md:
```
Setup BTCUSDT-15m-LONG-MARKET-60000-59400-v0 -> outcome STOP_HIT -> lesson stops too tight in high volatility
```

## Constraints

- No position sizing
- No risk parameter setting
- No chat memory for trade logic
- No execution APIs
- Deterministic setup_id generation only

## Pipeline Position

```
Market Data -> C3PO (TradeIntent) -> Sentinel (Risk Check) -> Executor (Order)
```

## Future Implementation

Python module: brain.py (C3PO intent engine)
- read_market_context()
- generate_trade_intent()
- validate_intent_structure()
- write_intent_output()
- append_field_note()
- read_sentinel_feedback()
