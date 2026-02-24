# Sentinel - Risk Officer

Deterministic capital protection engine.

## Overview

Sentinel is a pure Python rule engine that enforces strict risk controls before any trade execution. It operates between the Analyst (signal generator) and the Executor (order placer).

## Philosophy

- **No LLM logic** - Deterministic only
- **No randomness** - Pure rule enforcement
- **Fail closed** - If uncertain, reject
- **Capital preservation > opportunity**

## Files

```
workspace-sentinel/
├── risk_config.json           # Static risk parameters
├── APPROVED_ORDER_SCHEMA.md   # Authoritative ApprovedOrder shape for Forge
├── sentinel.py                # Main risk engine
└── README.md                  # This file
```

## Usage

```bash
cd ~/openclaw-elyra/workspace-sentinel
python3 sentinel.py
```

## Input

Reads from:
- `~/openclaw-trader/out/latest.json` (Analyst output)
- `workspace-sentinel/risk_config.json` (Risk parameters)

## Output

Writes to:
- `~/openclaw-trader/out/risk_decision.json` (Current decision)
- `~/openclaw-trader/out/risk-log/` (Timestamped logs)

## Decision Types

See **APPROVED_ORDER_SCHEMA.md** for the authoritative ApprovedOrder shape (client_order_id, venue, posture, constraints, etc.). Forge reads from `~/openclaw-trader/out/risk_decision.json`.

### REJECT
```json
{
  "kind": "REJECT",
  "reason": "rr_below_threshold:1.5",
  "ts_utc": "2026-02-24T02:30:00+00:00",
  "snapshot": {...}
}
```

## Risk Checks

1. Signal exists
2. Signal not stale (< 120 seconds)
3. Required fields present
4. Stop distance within bounds (0.2% - 3.0%)
5. R:R >= 1.8
6. Position size within equity limits

## Exit Codes

- `0` - Approved
- `1` - Rejected or error

## Constraints

- No OpenClaw APIs
- No chat memory
- No internet (balance stubbed at 10000.0)
- No probabilistic reasoning
- No adaptive behavior

Daily/weekly loss tracking and drawdown monitoring are specified in HEARTBEAT.md (state checks and lock conditions). Binance balance integration is planned; balance is currently stubbed.
