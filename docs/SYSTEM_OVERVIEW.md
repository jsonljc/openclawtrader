# OpenClaw Trader — Complete System Overview (Layman's Guide)

This is an explanation document, not a code change plan. No implementation needed.

---

## What Is This System?

OpenClaw Trader is an **automated futures trading system** — think of it as a robot that watches financial markets and makes trades on your behalf, following strict rules you've defined in advance. It trades **futures contracts** (agreements to buy/sell commodities or stock indices at a future date) on 5 different markets:

| Market | What It Is | Ticker |
|--------|-----------|--------|
| **ES** (S&P 500 E-mini) | Tracks the 500 biggest US companies | Stock index |
| **NQ** (Nasdaq E-mini) | Tracks big tech companies | Stock index |
| **CL** (Crude Oil) | Price of oil | Commodity |
| **GC** (Gold) | Price of gold | Commodity |
| **ZB** (30-Year Treasury Bond) | US government bonds | Interest rates |

The system starts with **$20,000** in capital and runs **20 different trading strategies** — 5 slower "swing" strategies that look at 4-hour charts, and 15 faster "intraday" strategies that look at 5-minute charts.

**Key principle**: There is **zero AI/LLM** in the decision-making. Every trade decision follows deterministic, pre-programmed rules. The system is designed to be fully auditable — you can trace exactly why every trade was made or rejected.

---

## The Four Agents (The Assembly Line)

The system is built like an assembly line with four specialized workers, each doing one job:

```
Watchtower  →  C3PO  →  Sentinel  →  Forge
 (Is everything    (Should we    (Is it safe    (Place the
  working?)         trade?)       to trade?)     order!)
```

### Agent 1: Watchtower — "The Safety Inspector"

**Job**: Before anything happens, Watchtower checks that everything is working properly. Think of it as the person who checks that the factory machines are running before the shift starts.

**What it checks (10 things)**:
1. **Is market data flowing?** — If the data feed is more than 5 minutes old, something's wrong
2. **Do the prices look sane?** — If a price jumped 5x more than normal, it might be a glitch
3. **Are bid/ask spreads normal?** — Wide spreads mean poor liquidity
4. **Are all safety stops in place?** — Every open position MUST have a stop-loss order protecting it
5. **How much margin are we using?** — Over 60% = danger zone
6. **Is the system running fast enough?** — Slow cycles could mean missed trades
7. **Are contracts about to expire?** — Futures expire; we need to "roll" to the next contract
8. **Is the audit trail intact?** — The ledger's cryptographic chain must be unbroken
9. **Are orders getting filled?** — If an approved order sits unfilled for 5+ minutes, flag it
10. **Is the broker connected?** — Can we actually reach Interactive Brokers?

**If something's wrong**, Watchtower can:
- **DEGRADED**: Minor issue, keep trading but be careful
- **FREEZE**: Serious issue, protect existing positions but don't open new ones
- **HALT**: Critical issue, stop everything

### Agent 2: C3PO — "The Strategist"

**Job**: C3PO is the brain that decides *whether* to trade and *what* to trade. It has three sub-systems:

#### Sub-system A: Regime Scoring — "What's the weather like?"

Just like you'd check the weather before going outside, C3PO checks the "market weather" using 5 factors:

1. **Trend (35% weight)**: Is the market trending clearly in one direction? Strong trends = good trading conditions. Measured by ADX (a trend strength indicator) and moving average slope.

2. **Volatility (30% weight)**: How wild are price swings? Measured by VIX (the "fear index"). Moderate volatility is ideal — too calm means no opportunities, too wild means too risky.

3. **Correlation Stress (10% weight)**: Are all our strategies moving together? If everything goes up and down at the same time, we're not actually diversified. High correlation = bad.

4. **Cross-Asset Risk-Off (10% weight)**: Are investors fleeing to safety? When both gold (GC) AND bonds (ZB) are rising simultaneously, it means people are scared — a "risk-off" signal that makes the system more cautious with stock index trades.

5. **Liquidity (15% weight)**: Can we actually get our orders filled at good prices? Thin order books = higher trading costs.

These combine into a **regime score** (0 to 1) that acts as a dial — turning position sizes up in good conditions and down in bad ones. The minimum multiplier is 0.30 (so even in the worst conditions, it never goes below 30% of normal size).

#### Sub-system B: Health Scoring — "How is each strategy performing?"

Every strategy gets a "health checkup" based on its last 30 days of trades:

- **Drawdown** (35%): How much money has it lost at worst? Compare to expectations.
- **Sharpe Ratio** (25%): Risk-adjusted returns — are the profits worth the volatility?
- **Hit Rate** (20%): What percentage of trades are winners?
- **Execution Quality** (20%): Is slippage (the difference between expected and actual fill price) reasonable?

Based on the health score:
- **Above 0.50** → NORMAL: trade at full size
- **0.30 to 0.50** → HALF_SIZE: cut position size in half
- **Below 0.30** → DISABLE: stop trading this strategy entirely

#### Sub-system C: Signal Generation — "Time to trade!"

Each strategy has its own entry rules. For example, the **Trend Reclaim 4H** strategy:
- **Buy signal**: Price climbs back above the 20-period moving average AND the trend is strong (ADX ≥ 25) AND the moving average is sloping upward
- **Sell signal**: Mirror image — price drops below MA20, strong downtrend
- **Stop-loss**: Set at 1.5× the Average True Range (ATR) below entry
- **Take-profit**: Set at 2.5× ATR above entry (reward:risk = 1.67:1)

Other intraday strategies include:
- **ORB (Opening Range Breakout)**: Trade breakouts from the first 15 minutes of trading
- **VWAP**: Trade bounces off the Volume-Weighted Average Price
- **Trend Pullback**: Enter trends on pullbacks to key levels

Before any signal goes through, it must pass **9 gates** (all must pass):
1. Strategy is active (not disabled)
2. Health score is above minimum (0.30)
3. Health action isn't DISABLE
4. Regime score is above 0.30
5. System posture isn't DEFENSIVE or HALT
6. Market is actually open (not closed/pre-market)
7. Watchtower hasn't flagged a HALT
8. No existing position for the same strategy/direction
9. Data isn't stale

#### Advisory Sizing

C3PO calculates a *suggested* position size:
```
Base risk = $20,000 × 0.50% = $100 per trade
Then multiply by:
  × regime modifier (0.30 to 1.0 based on market conditions)
  × health modifier (0.0, 0.5, or 1.0 based on strategy health)
  × session modifier (0.5 in extended hours, 1.0 in regular hours)
  × incubation modifier (25% for new/unproven strategies)

Convert to contracts:
  contracts = floor($risk / (stop_distance × point_value))
  If 0 full contracts → try micro contracts (1/10th size)
```

This sizing is **advisory** — Sentinel has the final say.

### Agent 3: Sentinel — "The Risk Officer"

**Job**: Sentinel is the independent risk manager. It can approve, reduce, or reject any trade that C3PO proposes. Think of it as the compliance department — even if the strategist wants to trade, the risk officer can say no.

**18 Hard Rules** (any failure = trade rejected):

**Portfolio-Level Limits:**
1. No single trade can risk more than 1.5% of equity ($300 on $20K)
2. Total open risk across all positions ≤ 5% of equity
3. Maximum daily loss ≤ 2.5% of equity
4. Maximum drawdown from peak equity ≤ 15%
5. Margin usage ≤ 50%
6. No more than 3% risk in any one "cluster" (e.g., all stock index trades combined)
7. No more than 2% risk on any single instrument
8. Correlated strategies can't exceed 0.85 correlation
9. Maximum 6 strategies active at once
10. Maximum 4 positions open at once
11. Maximum 8 round-trip trades per day
12. Maximum 4 ticks of slippage
13. Minimum 1.5:1 reward-to-risk ratio

**Intraday-Specific Rules:**
14. No entries in extended hours or first 2 minutes of market open
15. 15-minute cooldown after getting stopped out
16. Max 8 round-trips per day (intraday counter)
17. 3+ losses in 60 minutes → forced 2-hour pause
18. Max 4 concurrent positions

**Posture System — The Escalation Ladder:**

The system has an automatic "threat level" that escalates as losses mount:

| Posture | Trigger | Effect on Sizing |
|---------|---------|-----------------|
| **NORMAL** | Default state | 100% size |
| **CAUTION** | 4% drawdown from peak | 60% size |
| **DEFENSIVE** | 10% drawdown from peak | 25% size |
| **HALT** | 15% drawdown from peak | 0% — no new trades |

Recovery is gradual: HALT → DEFENSIVE takes days, not minutes. The system doesn't bounce back to full size just because one good trade happens.

**Streak Modifier**: If you lose 3+ trades in a row, size drops to 70%. At 5+ consecutive losses, it drops to 50%. This prevents "revenge trading."

### Agent 4: Forge — "The Executor"

**Job**: Once Sentinel approves a trade, Forge actually places the orders. It's deliberately "dumb" — it does exactly what it's told, nothing more.

**What it does**:
1. Validates the approval is still fresh (< 15 minutes old)
2. Checks the current spread is acceptable
3. Places the market order (paper or live via Interactive Brokers)
4. Immediately places a **bracket order**: a linked stop-loss AND take-profit order. When one fills, the other auto-cancels (OCA = "One Cancels All")
5. Registers the new position in the portfolio
6. Logs everything to the ledger

**Two modes**:
- **Paper trading**: Simulates fills with realistic slippage modeling (accounts for contract size, volatility, session, and book depth)
- **Live trading**: Routes orders to Interactive Brokers (IB) via their API gateway

**Idempotency**: Forge will never accidentally execute the same trade twice, even if there's a crash and restart. Every approval has a unique key that's checked before execution.

---

## The Shared Infrastructure

### The Ledger — "The Unbreakable Diary"

Every single event in the system is recorded in an append-only log file (`ledger.jsonl`). Each entry is cryptographically chained to the previous one using SHA-256 hashes — like blockchain, but simpler. If anyone tampers with a past entry, the chain breaks and Watchtower catches it.

Events logged include: signals generated, trades approved/denied, orders filled, positions closed, regime scores, health scores, posture changes, and more.

### The Portfolio — "The Scoreboard"

A JSON file (`portfolio.json`) tracks the real-time state: how much money you have, what positions are open, how much margin is being used, current drawdown, and risk exposure by cluster (stocks vs commodities vs rates).

### Correlation Tracking

Every cycle, the system computes 20-day rolling correlations between all strategy pairs. If two strategies start moving in lockstep, the system recognizes the false diversification and can limit exposure.

### Contract Calendar & Rolls

Futures contracts expire. The system knows the CME expiry schedule for all 5 instruments and automatically initiates "rolls" — closing the expiring contract and opening the next one — typically 5 days before expiry.

---

## How a Typical Trading Cycle Works

**Every 4 hours** (on a bar close), the full pipeline runs:

1. **Watchtower** checks: Is data flowing? Are brackets intact? Is margin OK? Is the broker connected?
2. **C3PO** scores the market regime, evaluates strategy health, and scans all 20 strategies for entry signals
3. For each signal that passes all 9 gates, C3PO builds a **trade intent** with entry price, stop-loss, take-profit, and suggested size
4. **Sentinel** receives each intent and runs it through all 18 rules. It applies posture/streak modifiers and either approves, reduces, or denies
5. **Forge** executes approved trades, placing bracket orders for protection
6. Correlations are updated, portfolio state is saved, and everything is logged

**Every 15 minutes**, a lighter **reconciliation** cycle runs:
- Check if any stops or take-profits have been triggered
- Update unrealized P&L (mark-to-market)
- Verify bracket integrity
- Sync with IB if in live mode

**On startup**, a **recovery** cycle runs:
- Reconstruct the last known state from the ledger
- Re-verify all open positions have active brackets
- Alert if anything looks inconsistent

---

## Current Status & Limitations

- **Capital**: $20,000 starting equity
- **Swing strategies**: Active but size to 0 contracts at this capital level (need ~$50K+ to trade full-size ES/NQ futures). They fall back to micro contracts (MES/MNQ) which are 1/10th the size
- **Intraday strategies**: All 15 are in **incubation** — trading at 25% size with no real trades yet. They need 30-50 trades to "graduate" to full sizing
- **Backtesting**: Uses synthetic data, not real historical bar-by-bar replay
- **Market internals**: Doesn't yet use breadth indicators (TICK, ADD, VOLD) which could improve signal quality

---

## Why Is It Built This Way?

1. **Separation of powers**: The strategist (C3PO) and risk officer (Sentinel) are independent. The strategist can't override risk limits. This prevents the common trap of "I really feel good about this trade" overriding risk management.

2. **Determinism**: No randomness, no AI opinions. Given the same inputs, the system always makes the same decision. This makes it fully testable and auditable.

3. **Defense in depth**: Multiple layers of protection — health scoring, regime scoring, 9 proposal gates, 18 risk rules, posture escalation, streak modifiers, and bracket orders. No single failure can cause a catastrophic loss.

4. **Crash resilience**: The SHA-256 ledger, atomic file writes, and recovery protocol mean the system can crash at any point and restart without losing state or double-executing trades.

5. **Gradual trust**: New strategies start in incubation (25% size) and must prove themselves over 30-50 trades before graduating to full size. This limits the damage from untested ideas.
