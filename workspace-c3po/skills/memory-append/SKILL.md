---
name: memory-append
description: Append a one-line lesson to c3po/field_notes.md and update session-state.md. Logging only. C3PO reads field_notes at session start to apply lessons.
user-invocable: true
metadata: {"openclaw":{"emoji":"📓","requires":{"bins":["python3"]}}}
---

# memory-append

## Purpose
Structured logging of C3PO observations, regime calls, and post-trade notes.

- `field_notes.md` is **append-only**. C3PO reads it at session start and before proposing (to apply lessons). It is also available for human operator review.
- `session-state.md` is **overwrite-on-update**. It represents current state only.

## Tools available
Use the `exec` tool to run scripts in `{baseDir}/scripts/`.

---

## Functions

### append_field_note
Appends a single timestamped line to `c3po/field_notes.md`.

```
exec: python3 {baseDir}/scripts/append_field_note.py --type <TYPE> --note "<note text>"
```

Arguments:
- `--type` — one of: `REGIME`, `SIGNAL`, `MISS`, `FALSE_POSITIVE`, `STALE_SKIP`, `HALT`, `OBSERVATION`, `ERROR`
- `--note` — max 200 characters, plain text, no quotes or special chars
- `--notes-file` — override path to `field_notes.md` (optional)

Output: JSON confirmation echoed to stdout.

File format (append-only):
```
2025-01-15T14:23:10Z | REGIME          | ELEVATED vol on 1h, ADX 78th pct, TREND_DOWN 4h — skipped long bias
2025-01-15T14:25:01Z | FALSE_POSITIVE  | 15m TREND_UP reversed within 2 candles — low ADX confidence flag missed
2025-01-15T14:30:00Z | STALE_SKIP      | Snapshot stale 8.2s, skipped regime computation
```

Rules:
- Never overwrite or edit existing lines
- Never delete the file
- If file does not exist, create it with a header line first
- Max file size: 5MB. If exceeded, rotate to `field_notes_archive_<date>.md`

---

### update_session_state
Writes (overwrites) the current session state to `c3po/session-state.md`.

```
exec: python3 {baseDir}/scripts/update_session_state.py --state-json '<json_string>'
```

State schema:
```json
{
  "session_id": "c3po-20250115-001",
  "started_at": "2025-01-15T14:00:00Z",
  "last_updated": "2025-01-15T14:23:10Z",
  "snapshots_fetched": 12,
  "stale_skips": 1,
  "regime_calls": 11,
  "signals_generated": 3,
  "signals_passed_to_sentinel": 2,
  "signals_rejected_by_sentinel": 1,
  "current_regime": "ELEVATED",
  "current_htf_bias": "BEARISH",
  "tradeable": true,
  "halt_reason": null
}
```

Read current state (print only, no writes):
```
exec: python3 {baseDir}/scripts/update_session_state.py --read
```

This file is overwritten on every update — it represents current state only. Historical data lives in `field_notes.md`.

---

## Mandatory call pattern

Call `append_field_note` in these situations (non-exhaustive):
- After every regime classification
- On every stale snapshot skip
- When `tradeable` flips from `true` → `false` or back
- After any signal is generated (whether passed to Sentinel or not)
- When Sentinel rejects a signal (log the reason if surfaced)
- On any halt or error condition

Call `update_session_state` after every `append_field_note` call.

Do not batch notes. One event = one append call.

## What this skill will NOT do
- Influence any trading decision
- Write to any file outside `c3po/`
- Delete or modify existing log entries
