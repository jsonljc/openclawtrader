# OpenClaw Trader
**Futures Trading System — Spec v1.1**  
**Status: Paper Trading — Phase 1 (Foundation)**

---

## System Architecture

Four deterministic agents. No LLM in the decision or execution path.

```
Watchtower ──► C3PO ──► Sentinel ──► Forge
  (health)   (signals)   (risk)    (execution)
```

| Agent | Role | Domain |
|-------|------|--------|
| **C3PO** | Portfolio Strategist | Regime scoring, strategy health, trade intents |
| **Sentinel** | Risk & Governance Officer | Hard limits, posture machine, sizing |
| **Forge** | Execution Engine | Order placement, bracket management |
| **Watchtower** | Reliability Monitor | Data integrity, reconciliation, crash recovery |

**Separation of powers:**
- C3PO → can SUGGEST (intents, weights, risk multipliers)
- Sentinel → can APPROVE / DENY / REDUCE / FREEZE / HALT
- Forge → can EXECUTE (only after approval; never decides)
- Watchtower → can FREEZE / HALT (operational kill switch)

---

## Quick Start

```bash
# One full evaluation cycle (4H bar close)
python3 run_cycle.py --mode full

# 1H lightweight refresh (regime + health, no new intents)
python3 run_cycle.py --mode refresh

# 15-min reconciliation (bracket integrity, position check)
python3 run_cycle.py --mode reconcile

# Post-crash recovery
python3 run_cycle.py --mode recovery
```

---

## Repository Structure

```
/
├── shared/                  # Core infrastructure
│   ├── contracts.py         # All data contracts (Section 5)
│   ├── ledger.py            # Append-only ledger with hash chain
│   ├── state_store.py       # Write-ahead state persistence
│   └── identifiers.py       # Deterministic ID generation
│
├── workspace-c3po/          # C3PO agent
│   ├── brain.py             # Main evaluation cycle
│   ├── regime.py            # Regime scoring engine
│   ├── health.py            # Strategy health scoring
│   ├── data_stub.py         # Market data stub (Phase 1)
│   ├── SOUL.md              # Identity and mission
│   └── TOOLS.md             # Module reference
│
├── workspace-sentinel/      # Sentinel agent
│   ├── sentinel.py          # Risk engine + posture machine
│   ├── posture.py           # Posture state machine
│   ├── SOUL.md              # Identity and mission
│   └── TOOLS.md             # Configuration reference
│
├── workspace-forge/         # Forge agent
│   ├── forge.py             # Execution engine
│   ├── paper_broker.py      # Paper trading simulator
│   ├── slippage_model.py    # Slippage estimation (spec Section 7.6)
│   ├── SOUL.md              # Identity and mission
│   └── TOOLS.md             # Execution reference
│
├── workspace-watchtower/    # Watchtower agent (NEW)
│   ├── watchtower.py        # Health checks + crash recovery
│   ├── SOUL.md              # Identity and mission
│   ├── TOOLS.md             # Monitoring reference
│   └── AGENTS.md            # Full system architecture
│
├── strategies/              # Strategy registry
│   └── trend_reclaim_4H_ES.json
│
├── parameters/              # Parameter governance
│   └── PV_0001.json         # Current parameter version
│
├── data/                    # Runtime state (gitignored)
│   ├── ledger/              # Append-only ledger
│   └── state/               # Persisted agent state
│
└── run_cycle.py             # System orchestrator
```

---

## Phased Rollout

| Phase | Scope | Status |
|-------|-------|--------|
| Phase 1 (Weeks 1–4) | 1 instrument, 1 strategy, fixed sizing, crash recovery | **DONE** |
| Phase 2 (Weeks 5–8) | Regime scaling, health scaling, Sentinel posture machine, session mgmt | **DONE** |
| Phase 3 (Weeks 9–12) | 2nd strategy, portfolio heat, correlation tracking, contract rollover | **DONE** |
| Phase 4 (Weeks 13–16) | Live data, slippage calibration, stress testing, operator alerting | Pending |

---

## Design Principles

1. Alpha is fragile and decays. The system must detect decay and respond.
2. Regime detection is probabilistic, not binary.
3. A small portfolio of uncorrelated strategies beats any single strategy.
4. Execution is deterministic, idempotent, and auditable. No LLM.
5. Risk limits are hard. No override. No exception. No "just this once."
6. The system must handle crash, disconnect, and data failure at any point.
7. Futures-specific risks (margin, gaps, rollover, liquidation) are first-class concerns.
8. Simplicity is a feature. Every parameter must justify its existence.

---

## Paper Trading Scope

- 2–3 liquid futures instruments (ES, NQ, CL or BTC/ETH perpetuals)
- 1H / 4H primary timeframes
- 2–3 strategies maximum
- Realistic slippage, fees, and margin simulation
- No real capital at risk until all phase gates are passed

---

*Spec: Futures Trading System v1.1 — 2026-02-28*
