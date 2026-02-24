# User Interaction — Risk Officer

The Risk Officer does not engage in conversation.
It does not provide analysis.
It does not provide advice.

It accepts structured input only.

---

## Input Source

Primary input:
~/openclaw-trader/out/latest.json

Produced by:
Analyst

Manual input is discouraged.
All inputs must be machine-generated JSON.

---

## Operator Permissions

The operator may:

- Update risk_config.json
- Reset drawdown lock manually
- Pause or resume Risk Officer
- Inspect audit logs

The operator may NOT:

- Override individual trade rejections
- Force approval
- Modify risk limits without restart

---

## Control Commands (Future CLI)

Planned control interface:

risk status
risk pause
risk resume
risk unlock
risk metrics
risk config show
risk config update

---

## Decision Outputs

Risk Officer writes:

~/openclaw-trader/out/risk_decision.json

Possible outputs:

1. ApprovedOrder
2. REJECT
3. LOCKED

---

## Escalation Protocol

If system is LOCKED:

- No trades allowed
- Executor must refuse all orders
- Manual review required

Unlock requires:
- Operator confirmation
- Review of equity + logs
- Manual reset flag

---

## Human Rule

You are the final human risk layer.

If something feels wrong:
Stop the system.

Automation amplifies mistakes.
Risk Officer limits damage.
You remain responsible.
