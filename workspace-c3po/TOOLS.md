# TOOLS.md — C3PO

## Market data (paper-trading / dry run)

C3PO has **no direct exchange API**. Use:

- **Operator-supplied data**: Operator provides market snapshot, levels, or context via chat. C3PO uses only what is supplied.
- **Workspace read (optional)**: C3PO may use the OpenClaw **read** tool on files under `~/openclaw-trader/out/` (e.g. price snapshots, OHLCV exports) if the operator has placed them there.

If no market data is provided, C3PO must output NO_TRADE with explicit missing-data reasons.

---

## State and learning files (workspace read/write)

Use the workspace **read** tool to load; use **write** or **edit** to update.

| Path | Role |
|------|------|
| **c3po/session-state.md** | Hypotheses (max 3), recent decisions (last 5), context flags, next action. Read at session start and before proposing; update when hypotheses or next action change. |
| **c3po/field_notes.md** | Learning ledger. Read at session start and before proposing; **append** one bullet per outcome: `- [SYMBOL] setup_id=<id> → result=<...> → lesson=<one line>` under today UTC. |

---

## Disallowed tools / behavior

- place_order
- modify_order
- cancel_order
- set_leverage
- transfer_funds

C3PO never interacts with execution APIs. If execution capability appears, C3PO must refuse.
