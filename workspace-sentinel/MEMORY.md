# MEMORY.md — Sentinel

## Memory Model

Sentinel does NOT keep conversational memory or narrative logs.

All state is structured and persisted in files only.

---

## Persisted State

| File | Contents | Reset cadence |
|------|----------|---------------|
| `posture_state.json` | Posture, daily/weekly loss, consecutive losses, peak equity | Daily (loss counters), Weekly (weekly loss) |
| `risk_config.json` | Static risk rules (risk %, loss limits, R:R) | Manual operator change only |
| `risk-log/risk-log-<date>.jsonl` | Full audit trail of every approval/rejection | Never deleted automatically |

---

## What Sentinel Remembers

- Current posture (NORMAL / REDUCED / HALT)
- Today's accumulated loss %
- This week's accumulated loss %
- Peak equity % (for drawdown tracking)
- Consecutive loss count
- Whether edge health is degraded

---

## What Sentinel Does NOT Remember

- Chat history
- Operator names or preferences
- Past market analysis
- C3PO's reasoning or thesis
- Any signal content beyond what is in the current `latest.json`

---

## Compaction Rule

Sentinel has no LLM memory to compact.

If OpenClaw compacts this agent's context:
- Re-read `posture_state.json` on next run
- Re-read `risk_config.json` on next run
- All numerical state comes from files, not from conversation history

---

## Audit Log Retention

Keep risk-log files for minimum 90 days.
These are the primary audit trail for:
- Trade approvals
- Rejection reasons
- Posture transitions
- Drawdown events

Do not delete them without operator consent.
