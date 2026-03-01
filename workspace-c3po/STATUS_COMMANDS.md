# STATUS_COMMANDS.md — C3PO Telegram Status Console

## Overview

When you receive a Telegram message that is a status command (see table below),
your ONLY job is to run `status_console.py` and reply with its output verbatim.
Do NOT add commentary, analysis, hedging, or market opinions.
Do NOT trigger any trade pipeline (run_cycle, brain.py, sentinel.py, forge.py).
Do NOT write to any file in `~/openclaw-trader/out/`.

This is a READ-ONLY operation.

---

## Command Recognition

Normalize the inbound message:
1. Strip leading/trailing whitespace
2. Convert to lowercase
3. Remove leading `/` if present

Then match against this table:

| Normalized text       | Script argument | Function called     |
|-----------------------|-----------------|---------------------|
| `status`              | `status`        | `build_status()`    |
| `report`              | `status`        | `build_status()`    |
| `paper status`        | `status`        | `build_status()`    |
| `risk`                | `status`        | `build_status()`    |
| `position`            | `status`        | `build_status()`    |
| `detail`              | `detail`        | `build_detail()`    |
| `lasttrade`           | `lasttrade`     | `build_lasttrade()` |
| `last trade`          | `lasttrade`     | `build_lasttrade()` |

If no match → reply exactly: `Commands: status | detail | lasttrade | /report`

> **IMPORTANT — `/status` collision**: The openclaw framework intercepts `/status` as a built-in
> system diagnostics command BEFORE messages reach C3PO. If you send `/status`, you will get
> openclaw's gateway status, not the trading status.
>
> Use instead:
> - Plain text `status` (no slash) — passes through to C3PO
> - `/report` — registered Telegram slash command that is NOT reserved by openclaw

---

## How to Execute

**Preferred (if shell/bash tool is available):**

```bash
python3 ~/.openclaw-elyra/workspace-c3po/status_console.py status
python3 ~/.openclaw-elyra/workspace-c3po/status_console.py detail
python3 ~/.openclaw-elyra/workspace-c3po/status_console.py lasttrade
```

Reply with the stdout output verbatim. Do not edit, summarize, or add to it.

**Fallback (if only file read tools are available):**

Read these files and format the reply using the templates below:

| Command    | Files to read |
|------------|---------------|
| `status`   | `~/openclaw-trader/out/execution_report.json`, `~/.openclaw-elyra/workspace-sentinel/posture_state.json`, `~/.openclaw-elyra/workspace-forge/forge/paper_positions.json`, today's `~/openclaw-trader/out/paper_ledger_YYYY-MM-DD.jsonl` |
| `detail`   | All of the above + `~/openclaw-trader/out/latest.json`, `~/openclaw-trader/out/execution_quality.json` |
| `lasttrade`| `~/openclaw-trader/out/paper_ledger_YYYY-MM-DD.jsonl` (last line) |

---

## STATUS Template (fallback format)

```
📊 OpenClaw Status  [YYYY-MM-DD HH:MM UTC]
Mode: PAPER | LIVE | UNKNOWN
Posture: NORMAL | REDUCED | HALT [| halt=<reason>]
Position: NONE | OPEN <SIDE> <QTY> BTC
  entry=<price>  stop=<price>  tp=<price>
Last action: <STATUS> (<exit_reason>) @ <datetime> [<short_id>]
Today PnL: $<+/-N.NN> USD  |  trades=<N>
Daily loss: <N>%  |  consec losses=<N>
```

If any file is missing, show `(missing)` for that field. Never crash or omit.

---

## Mode Detection (for fallback)

1. Check `execution_report.json` → `.kind` field: `"PAPER"` → PAPER, `"LIVE"` → LIVE
2. Check if `paper_ledger_YYYY-MM-DD.jsonl` exists today → PAPER
3. Otherwise → UNKNOWN

---

## Hard Constraints

- **Never call** `run_cycle.py`, `brain.py`, `sentinel.py`, `forge.py`, or `paper_broker.py` in response to a status command.
- **Never write** to `~/openclaw-trader/out/` or any workspace file.
- **Never** interpret a status command as a request for a trade.
- If the user says "status" and also includes market data in the same message, handle them as two separate requests: first reply with status, then offer to analyze.
