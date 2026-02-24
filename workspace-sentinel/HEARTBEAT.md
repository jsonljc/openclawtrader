# Risk Officer — Heartbeat

Purpose:
Continuous health verification and system state monitoring.

Risk Officer must remain predictable, isolated, and within constraints.

---

## Heartbeat Interval

Default: every 60 seconds

Checks:

1. latest.json exists
2. latest.json timestamp freshness (< 120 seconds)
3. risk_config.json exists and is valid
4. Account balance API reachable
5. Daily loss within threshold
6. Weekly loss within threshold
7. Drawdown from high-water mark < 10%
8. No more than max_open_trades active
9. Risk decision file writable
10. No corrupted logs

If any check fails → SYSTEM_LOCK

---

## State File

Risk Officer maintains:

~/openclaw-trader/risk-officer/state.json

Example:

{
  "status": "ACTIVE",
  "equity": 10000.0,
  "daily_loss_pct": 0.4,
  "weekly_loss_pct": 1.2,
  "drawdown_pct": 2.1,
  "open_trades": 0,
  "last_check": "2026-02-24T02:10:00Z"
}

If locked:

{
  "status": "LOCKED",
  "reason": "Daily loss limit breached",
  "locked_at": "2026-02-24T02:12:11Z"
}

---

## Lock Conditions

System enters LOCKED state if:

- Daily loss exceeds max_daily_loss_pct
- Weekly loss exceeds max_weekly_loss_pct
- Equity drawdown > 10%
- Missing balance data
- Repeated API failures
- Corrupted signal input
- More than 3 consecutive execution failures

LOCKED state blocks all approvals.

---

## Unlock Procedure

Manual only.

Operator must:

1. Inspect logs
2. Reset state.json
3. Confirm risk limits
4. Explicitly restart Risk Officer

No automatic unlock.

---

## Logging

All heartbeat checks append to:

~/openclaw-trader/out/risk-heartbeat.log

Format:

[ts] STATUS=ACTIVE equity=... dd=... daily=... weekly=...

If LOCK:

[ts] STATUS=LOCKED reason=...

---

## Design Philosophy

Heartbeat is not optimization.
Heartbeat is survival monitoring.

If uncertain → lock.
If inconsistent → lock.
If missing data → lock.

Risk Officer prefers downtime over risk exposure.
