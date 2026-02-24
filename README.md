# OpenClaw — Elyra Trading Profile

A multi-agent AI trading system built on [OpenClaw](https://openclaw.ai).

## Architecture

```
C3PO (Brain) → TradeIntent → Sentinel (Risk) → ApprovedOrder → Forge (Executor) → ExecutionReport
```

| Agent | Role | Output |
|-------|------|--------|
| **C3PO** | Self-learning quant brain. Proposes trade setups. Never sizes, never executes. | `TradeIntent` |
| **Sentinel** | Deterministic risk officer. Validates + sizes every intent. | `ApprovedOrder` or `REJECT` |
| **Forge** | Deterministic executor. Places orders on Binance exactly as approved. | `ExecutionReport` |
| **Glitch** | Media/comms agent. | — |

## Directory structure

```
workspace-c3po/       # C3PO agent spec, brain.py, skills
  skills/
    market-snapshot/  # Live price + OHLCV from Binance (read-only)
    regime-features/  # ATR, volatility regime, trend/range classifiers
    memory-append/    # Append to field_notes.md, update session-state.md
  c3po/
    field_notes.md    # Append-only learning ledger
    session-state.md  # Current session state (overwritten each update)

workspace-sentinel/   # Sentinel agent spec + sentinel.py risk engine
workspace-forge/      # Forge agent spec
workspace-glitch/     # Glitch agent spec
```

## Data flow

```
~/openclaw-trader/out/latest.json        ← C3PO writes TradeIntent here
~/openclaw-trader/out/risk_decision.json ← Sentinel writes ApprovedOrder / REJECT here
forge/state.json                         ← Forge idempotency ledger (runtime only)
```

## Setup

1. Copy `openclaw.template.json` → `openclaw.json`
2. Fill in `<TELEGRAM_BOT_TOKEN_C3PO>`, `<GATEWAY_TOKEN>`, `<GATEWAY_PASSWORD>`, and token file paths
3. Place Telegram bot tokens in `secrets/`
4. Set `BINANCE_API_KEY` and `BINANCE_API_SECRET` environment variables for skills

## Environment variables required

| Variable | Used by |
|----------|---------|
| `BINANCE_API_KEY` | market-snapshot skill |
| `BINANCE_API_SECRET` | market-snapshot skill |

## Key contracts

- **TradeIntent schema**: `workspace-c3po/SOUL.md`
- **ApprovedOrder schema**: `workspace-sentinel/APPROVED_ORDER_SCHEMA.md`
- **ExecutionReport schema**: `workspace-forge/EXECUTION_REPORT_SCHEMA.md`

## Status

Dry-run ready. All inter-agent handoffs verified. Live Binance market data confirmed working.
