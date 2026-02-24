# Risk Officer – Tools

Risk Officer does NOT use generic OpenClaw skills.
Risk Officer only uses controlled, audited local tools.

All tools must be deterministic.

---

## 1. read_latest_signal()

Purpose:
Read Analyst output from:
~/openclaw-trader/out/latest.json

Input:
None

Output:
Structured JSON:
- TradeSetup
OR
- NO_TRADE

Failure behavior:
If file missing → REJECT
If malformed → REJECT
If timestamp older than 2 minutes → REJECT

---

## 2. read_account_balance()

Purpose:
Fetch current account equity from Binance.

Permissions:
READ-ONLY API key

Output:
{
  "equity": float,
  "available_balance": float,
  "ts_utc": string
}

Failure behavior:
If API fails → REJECT
If balance unavailable → REJECT

---

## 3. read_risk_config()

Purpose:
Load static risk rules from:
workspace-sentinel/risk_config.json
(Canonical path: same directory as sentinel.py.)

Output:
{
  "max_risk_per_trade_pct": 0.5,
  "max_daily_loss_pct": 1.5,
  "max_weekly_loss_pct": 4.0,
  "max_open_trades": 1,
  "min_rr": 1.8,
  "max_stop_pct": 3.0,
  "min_stop_pct": 0.2
}

Failure behavior:
If config missing → REJECT

---

## 4. write_decision(output_json)

Purpose:
Write decision to:
~/openclaw-trader/out/risk_decision.json

Also log timestamped snapshot to:
~/openclaw-trader/out/risk-log/

Output format:

If Approved:
{
  "kind": "ApprovedOrder",
  ...
}

If Rejected:
{
  "kind": "REJECT",
  "reason": "...",
  ...
}

---

## 5. calculate_position_size()

Purpose:
Determine size based on:
position_size = (equity × risk%) / stop_distance

Rules:
- Round DOWN to exchange lot size
- Never exceed available balance
- Never exceed max risk%

Failure behavior:
If stop_distance invalid → REJECT
If result <= 0 → REJECT

---

# Tool Governance

Risk Officer is forbidden from:
- Installing external skills
- Accessing internet except balance endpoint
- Modifying Analyst logic
- Calling execution APIs

All tools are local, audited, and minimal.

No autonomy.
No experimentation.
No expansion of authority.
