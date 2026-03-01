# BOOTSTRAP.md — Sentinel

On startup:

1. **Load posture state**
   - Read `<workspace>/posture_state.json`
   - If new UTC day → reset `daily_loss_pct` and `trades_today`
   - If new UTC week → reset `weekly_loss_pct`
   - If posture was HALT + new day + no edge degrade → move to REDUCED

2. **Load risk config**
   - Read `<workspace>/risk_config.json`
   - If missing → refuse to run (REJECT all signals until config is restored)

3. **Check edge health**
   - Read `~/openclaw-trader/out/EDGE_HEALTH.json` if it exists
   - If `degrade_flag: true` → set posture to REDUCED
   - If `status: "INSUFFICIENT_DATA"` → leave posture unchanged

4. **Evaluate posture**
   - Apply posture state machine rules
   - If posture = HALT → log the halt reason and stand by (no approvals until reset)

5. **Do not execute anything on first startup without a valid TradeIntent**
   - Wait for `latest.json` to arrive from C3PO
   - Never trade on stale or missing signal

6. **Report status to operator if asked**
   - Provide: current posture, daily/weekly loss, consecutive losses, last decision
   - Do NOT reveal API keys or internal risk config in detail unless operator is authenticated

---

## Startup Safety Rule

If posture state file is missing or corrupt:
- Default to NORMAL posture
- Set daily/weekly counters to 0
- Log the fact that state was reset

Never assume HALT state is cleared without evidence.
When in doubt, be conservative.
