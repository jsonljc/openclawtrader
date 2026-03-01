# AGENTS.md — System Architecture v1.1

## Agent Roster

| Agent | Role | Domain | Can |
|-------|------|---------|-----|
| C3PO | Portfolio Strategist | Signal generation, regime, health | SUGGEST |
| Sentinel | Risk & Governance Officer | Risk limits, posture, sizing | APPROVE / DENY / REDUCE / FREEZE / HALT |
| Forge | Execution Engine | Order placement, brackets | EXECUTE (approved only) |
| Watchtower | Reliability Monitor | Data integrity, system health | FREEZE / HALT |

## Separation of Powers (Invariants)

- Forge **never** executes without a valid `approval_id`
- Sentinel **never** generates trade ideas
- C3PO **never** places orders or modifies positions
- Watchtower **never** generates trade ideas or approvals
- No agent can override another agent's domain

## System Flow

```
Watchtower ─── confirms data health, system health, connectivity
     │
     │ SystemHealth {HEALTHY | DEGRADED | HALT}
     ▼
C3PO ──────── computes regime, strategy health, emits intents
     │
     │ RegimeReport + StrategyHealth[] + TradeIntent[]
     ▼
Sentinel ───── validates against risk rules, applies posture
     │
     │ RiskDecision[]
     ▼
Forge ──────── executes approved orders, returns receipts
     │
     │ ExecutionReceipt[]
     ▼
Feedback Loop
  • Receipts → Sentinel  (execution quality, missed opportunity tracking)
  • Receipts → C3PO      (strategy health update)
  • Receipts → Watchtower (reconciliation)
```

## Cadence

| Event | Trigger | Agents |
|-------|---------|--------|
| Full evaluation | 4H bar close | Watchtower → C3PO → Sentinel → Forge |
| Lightweight refresh | 1H bar close | C3PO (regime + health only) |
| Shock response | Watchtower alert | Sentinel → Forge (flatten if required) |
| Reconciliation | Every 15 min | Watchtower |
| Session boundary | Per schedule | Sentinel + C3PO (overnight hold) |
| Contract rollover | T-5 days | Watchtower → C3PO → Sentinel → Forge |
| Daily close | End of day | Portfolio snapshot, health recalc |

## State Persistence

All state written to disk before actions. Write-ahead persistence.

| State | Store | Recovery |
|-------|-------|----------|
| Strategy registry | `data/state/strategy_registry.json` | Load on startup |
| Portfolio state | `data/state/portfolio.json` | Reconcile with exchange |
| Intent/approval/receipt ledger | `data/ledger/ledger.jsonl` | Replay non-terminal entries |
| Sentinel posture | `data/state/posture_state.json` | Load on startup (HALT preserved) |
| Parameters | `parameters/PV_XXXX.json` | Load current version |

## Ledger

Append-only. Hash chain. Never modified. Tamper-detectable.

Entry format: `ledger_seq | timestamp | event_type | run_id | ref_id | payload | checksum`
