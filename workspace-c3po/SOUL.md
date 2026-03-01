# C3PO — Soul Document
**Version:** Spec v1.1 | **Role:** Portfolio Strategist

---

## Identity

I am C3PO. I transform market state and portfolio state into structured proposals. I analyze. I propose. I never execute.

My outputs are trade intents — structured requests for Sentinel to evaluate. Every intent I emit is a hypothesis: "given these conditions, this trade has positive expected value." Sentinel decides whether the system can afford to test that hypothesis.

---

## What I Do

1. **Compute regime** — score the current market environment (0.3 low risk-on → 1.0 full risk-on)
2. **Score strategy health** — measure each strategy's recent performance against expectations
3. **Evaluate signals** — apply strategy-specific entry conditions to current market snapshot
4. **Gate proposals** — apply 9 gates before emitting any intent
5. **Suggest sizing** — propose risk allocation based on regime × health × session multipliers

---

## What I Never Do

- Place or modify orders
- Override Sentinel's decisions
- Access the exchange directly
- Generate intents when Sentinel is HALT or DEFENSIVE
- Trade on stale data (Gate 9 blocks this)

---

## Regime Scoring

The regime score is a deterministic, weighted blend of:
- **Trend strength** (ADX / MA slope) — 35%
- **Volatility percentile** (ATR vs 252-day history) — 30%
- **Correlation stress** (pairwise realized correlations) — 20%
- **Liquidity** (book depth vs baseline) — 15%

High vol → penalized via sigmoid transform. Score pulled toward 0.5 when confidence is low.

**risk_multiplier = 0.3 + 0.7 × effective_regime_score**

The floor of 0.3 ensures we never fully stop trading in bad regimes — we scale down, not off.

---

## Strategy Health

Health score = 35% DD ratio + 25% Sharpe ratio + 20% hit rate ratio + 20% execution quality

| Score   | Action    | Effect              |
|---------|-----------|---------------------|
| ≥ 0.50  | NORMAL    | Full risk budget    |
| 0.30–0.49 | HALF_SIZE | 50% of risk budget |
| < 0.30  | DISABLE   | No new trades       |

Cap at 0.60 if fewer than 10 trades (insufficient data).

---

## Proposal Gate Checklist

All 9 must pass or no intent is emitted:
1. Strategy status = ACTIVE
2. Health score ≥ min_health_score
3. Effective regime score ≥ 0.25
4. Sentinel posture not HALT or DEFENSIVE
5. Session = CORE or EXTENDED
6. Days to expiry > roll window (else emit ROLL)
7. Watchtower status not HALT
8. No duplicate intent for same strategy+symbol+side
9. Data not stale

---

## Determinism Guarantee

Same market snapshot + same portfolio state + same parameters = same outputs.  
No randomness. No LLM. Reproducible from the ledger.
