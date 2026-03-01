# HEARTBEAT.md — Sentinel

Purpose:
Continuous health verification and system state monitoring.

Sentinel must remain predictable, isolated, and within constraints at all times.

---

## Heartbeat Interval

Default: every 60 seconds (or on each trade cycle trigger)

Checks:

1. `~/openclaw-trader/out/latest.json` exists
2. `latest.json` timestamp freshness (< 120 seconds)
3. `<workspace>/risk_config.json` exists and is valid
4. Account balance API reachable (or equity stub loaded)
5. Daily loss within threshold (< 2.0%)
6. Weekly loss within threshold (< 4.0%)
7. Drawdown from peak < **6.0%**
8. No more than 1 open trade
9. Risk decision file writable
10. No corrupted logs

If any check fails → SYSTEM_LOCK

---

## State File

Sentinel maintains posture state in:

```
<workspace>/posture_state.json
```

Example (NORMAL):
```json
{
  "posture": "NORMAL",
  "daily_loss_pct": 0.4,
  "daily_loss_reset_date": "2026-02-24",
  "weekly_loss_pct": 1.2,
  "weekly_loss_reset_week": "2026-W08",
  "peak_equity_pct": 100.0,
  "consecutive_losses": 0,
  "last_updated_utc": "2026-02-24T02:10:00Z",
  "halt_reason": null,
  "trades_today": 1,
  "edge_health_degrade": false
}
```

Example (HALT):
```json
{
  "posture": "HALT",
  "halt_reason": "daily_loss=2.10% >= 2.0%",
  ...
}
```

---

## Lock Conditions

Sentinel enters HALT posture if ANY of:

- Daily loss ≥ 2.0%
- Weekly loss ≥ 4.0%
- Drawdown from peak ≥ **6.0%**
- Consecutive losses ≥ 3
- Missing balance data (stub mode only)
- Corrupted signal input

HALT posture blocks all approvals until the next UTC day reset or manual unlock.

---

## Unlock Procedure

**Automatic:** New UTC day resets daily counters; HALT → REDUCED if edge is healthy.
**Manual:** Operator edits `posture_state.json` and sets `"posture": "NORMAL"`.

---

## Logging

All decisions append to:
```
~/openclaw-trader/out/risk-log/risk-log-<date>.jsonl
```

Format:
```
{"kind": "ApprovedOrder"|"REJECT", "ts_utc": "...", "reason": "...", ...}
```

---

## Edge Health Integration

Sentinel reads `~/openclaw-trader/out/EDGE_HEALTH.json` on startup.
If `degrade_flag: true` → posture moves to REDUCED (not HALT).
If `status: "INSUFFICIENT_DATA"` → posture unchanged.

---

## Design Philosophy

Heartbeat is not optimization.
Heartbeat is survival monitoring.

If uncertain → HALT.
If inconsistent → HALT.
If missing data → REJECT (not necessarily HALT).

Sentinel prefers a missed trade over a bad one.
