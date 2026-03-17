# Market Intel ("Prism") — Design Document

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:writing-plans to create the implementation plan from this design.

**Goal:** Build a standalone market intelligence daemon that connects to IB Gateway, continuously polls real-time market data (quotes, cross-market, options chains, depth of market), computes derived analytics (velocity, divergences, GEX, microstructure), and produces per-instrument directional conviction scores consumed by Brain, Sentinel, and Dashboard for higher-conviction trading.

**Architecture:** Standalone Python daemon with persistent IB Gateway connection via `ib_insync`. Three-layer design: Data Layer (polling + caching) → Analytics Layer (derived intelligence) → Conviction Layer (pattern matching + scoring). All output published to Redis. Zero LLM tokens — pure deterministic computation.

---

## 1. Architecture

```
Market Intel Daemon ("Prism")
│
├── Data Layer
│   ├── Quote Stream (5s) — ES/NQ/CL/GC/ZB + MES/MNQ/MCL/MGC
│   ├── Cross-Market Stream (10s) — VIX, DXY, TNX, HYG, XLF
│   ├── Options Scanner (60s) — front-2-month chains, ±5 strikes ATM
│   ├── Depth of Market (5s) — top 5 levels bid/ask for core futures
│   └── Tick Stream (1s) — trade-by-trade for absorption detection
│
├── Analytics Layer (computed every 10s)
│   ├── Velocity Engine — 5m/15m/1h rate-of-change + volume acceleration
│   ├── Divergence Detector — 6 cross-asset pair divergences with decay
│   ├── Options Intelligence — GEX, skew shift, unusual flow, term structure
│   ├── Microstructure — book imbalance, absorption detection
│   ├── Regime Transition Detector — regime score acceleration + GEX flip
│   ├── Signal Integrator — reads news_signals + polymarket_signals
│   └── Volume Profile — relative volume + time-of-day context
│
├── Conviction Layer
│   ├── Pattern Matcher (primary) — 15+ named conditional patterns
│   ├── Weighted Fallback (secondary) — regime-adaptive, temporally decayed
│   ├── Time-of-Day Modifier
│   ├── Clarity Score — factor agreement measure
│   └── Directional output: long/short/hold conviction per instrument
│
├── Feedback Loop — logs conviction at entry, links to trade outcome
│
└── Redis publish → Brain, Sentinel, Dashboard, Telegram
```

Graceful degradation: If Prism or IB is down, `market_intel_bridge.py` returns `conviction=None`, Brain skips conviction check, Sentinel applies no modifier. Trading continues with existing logic.

---

## 2. Data Layer — What We Poll

| Category | Symbols | Frequency | Redis Key Pattern |
|----------|---------|-----------|-------------------|
| Core Futures | ES, NQ, CL, GC, ZB, MES, MNQ, MCL, MGC | 5s | `market_intel:quotes:{sym}` |
| Cross-Market | VIX, DXY, TNX, HYG, XLF | 10s | `market_intel:cross:{sym}` |
| Options Chains | ES, NQ, CL (front-2-month, ±5 strikes ATM) | 60s | `market_intel:options:{sym}` |
| Depth of Market | ES, NQ, CL, GC, ZB (top 5 levels) | 5s | `market_intel:dom:{sym}` |
| Tick Stream | ES, NQ, CL, GC, ZB | 1s | In-memory ring buffer only |

**Quote fields:** `bid`, `ask`, `last`, `volume`, `timestamp`, `bid_size`, `ask_size`

**Options fields per strike:** `strike`, `expiry`, `call_bid`, `call_ask`, `call_vol`, `call_oi`, `put_bid`, `put_ask`, `put_vol`, `put_oi`, `call_iv`, `put_iv`

**DOM fields:** `bid_prices[5]`, `bid_sizes[5]`, `ask_prices[5]`, `ask_sizes[5]`

**Staleness:** All data gets `stale_after` = 3x poll interval. Consumers check freshness.

**IB subscription management:** ~44 simultaneous subscriptions (under 50 limit). Options chains rotate — only subscribe to the instrument Brain is actively evaluating, not all 3 simultaneously.

---

## 3. Analytics Layer — Derived Intelligence

### 3.1 Velocity Engine
- Rolling deltas across 3 windows: 5-min, 15-min, 1-hour
- Per symbol: price change %, volume acceleration (current vs 20-bar avg), bid/ask pressure ratio
- Output: `velocity_5m`, `velocity_15m`, `velocity_1h` — each float -100 to +100

### 3.2 Divergence Detector
Six key cross-asset relationships monitored:
- ES vs VIX (inverse) — VIX not confirming ES move
- ES vs NQ (correlated) — sector rotation signal
- CL vs DXY (inverse) — supply-driven vs dollar-driven
- GC vs DXY (inverse) — fear bid vs dollar strength
- GC vs TNX (inverse) — real rate repricing
- ES vs HYG (correlated) — credit stress

Each pair scored -1.0 (strong divergence bearish) to +1.0 (strong divergence bullish), 0.0 = normal correlation. Temporal decay: 30-minute half-life.

### 3.3 Options Intelligence
- **GEX (Gamma Exposure):** Estimated from OI × gamma per strike. Positive = mean-reversion tailwind, negative = trend tailwind.
- **Skew shift:** 25-delta put IV minus 25-delta call IV, tracked as delta from 5-day average.
- **Unusual flow:** Strikes where `volume / open_interest > 2.0` flagged with direction.
- **Term structure slope:** Front-month IV minus second-month IV. Contango = calm (mean-reversion favored). Backwardation = fear (trend-following favored).

### 3.4 Microstructure
- **Book imbalance ratio:** `sum(bid_sizes[0:5]) / sum(ask_sizes[0:5])`. >1.3 = buy pressure, <0.7 = sell pressure.
- **Absorption detection:** Large resting orders (top-of-book size > 3x average) getting filled without price moving = institutional accumulation/distribution.

### 3.5 Regime Transition Detector
- Tracks rate-of-change of existing regime score from `intraday_regime.json`
- Detects threshold crossings: regime score accelerating toward TRENDING/VOLATILE/NEUTRAL boundary
- GEX sign flip (negative → positive or vice versa) as confirmation
- Output: `{detected: bool, from_regime: str, to_regime: str, confidence: float}`

### 3.6 Signal Integrator
- Reads active signals from Redis streams (`news_signals`, `polymarket_signals`)
- Counts aligned vs opposing signals relative to each direction
- Output: `aligned_signal_count`, `opposing_signal_count` per instrument per direction

### 3.7 Volume Profile
- Current session volume vs historical average volume at this time-of-day
- Relative volume ratio: >1.5 = high participation, <0.7 = thin market
- Output: `relative_volume` float per instrument

All analytics cached in Redis as `market_intel:analytics:{sym}` HSET.

---

## 4. Conviction Layer — Pattern Matching + Scoring

### 4.1 Pattern Matcher (Primary)
15+ named patterns, each a set of specific conditions. If a pattern matches, its conviction score and direction are used directly (no weighted fallback).

Initial patterns:
1. **TREND_ACCELERATION** — negative GEX + velocity accelerating (15m > 5m trend) + relative volume > 1.5 + aligned signal
2. **REGIME_FLIP** — regime transition detected + book imbalance confirming new direction + velocity aligning
3. **SMART_MONEY_DIVERGENCE** — options unusual flow opposing price direction + absorption detected at key level
4. **MOMENTUM_EXHAUSTION** — extreme velocity (>80) + GEX flipping sign + skew spiking + volume declining
5. **BREAKOUT_IMMINENT** — velocity compressed (5m/15m/1h all <20) + book thinning + vol term structure inverting
6. **FEAR_CAPITULATION** — VIX accelerating up + put/call ratio >1.5 + ES velocity deeply negative + GEX deeply negative (contrarian long)
7. **GREED_EXHAUSTION** — VIX at lows + call/put ratio >1.5 + ES velocity deeply positive + GEX flipping positive (contrarian short)
8. **CROSS_ASSET_CONFIRMATION** — 3+ divergence pairs all confirming same direction + relative volume > 1.0
9. **INSTITUTIONAL_ACCUMULATION** — absorption detected + book imbalance + price flat + volume rising
10. **LIQUIDITY_VACUUM** — book depth < 50% of average + velocity accelerating = fast move incoming
11. **TERM_STRUCTURE_SIGNAL** — IV term structure slope flipping sign + GEX confirming
12. **DOLLAR_DRIVEN** — DXY velocity >60 + CL/GC diverging from dollar as expected = high conviction commodity trade
13. **CREDIT_STRESS** — HYG diverging from ES + TNX rising + skew widening = risk-off setup
14. **NEWS_AMPLIFIER** — active news signal + options flow confirming + velocity confirming = compound conviction
15. **DEAD_MARKET** — relative volume <0.5 + velocity <10 all timeframes + book thin = anti-conviction, sit out

Each pattern specifies: `direction` (LONG/SHORT/NEUTRAL), `base_score` (60-95), `confidence` (MEDIUM/HIGH).

### 4.2 Weighted Fallback (Secondary)
When no pattern matches, compute score from weighted factors.

| Factor | TRENDING wt | VOLATILE wt | NEUTRAL wt |
|--------|-------------|-------------|------------|
| Velocity alignment | 25% | 15% | 20% |
| Divergence score | 20% | 25% | 25% |
| GEX tailwind | 15% | 20% | 15% |
| Options flow | 15% | 20% | 15% |
| Signal integration | 15% | 10% | 15% |
| Relative volume | 10% | 10% | 10% |

All factors temporally decayed: velocity half-life 15 min, divergences 30 min, GEX 2 hours, options flow 1 hour.

### 4.3 Time-of-Day Modifier
- 09:30-09:45 ET (open chop): conviction × 0.6
- 09:45-11:30 ET (morning momentum): conviction × 1.0
- 11:30-13:00 ET (lunch chop): conviction × 0.7
- 13:00-14:30 ET (afternoon session): conviction × 1.0
- 14:30-15:00 ET (MOC rebalancing): conviction × 0.8 for mean-reversion, × 1.1 for momentum
- 15:00-15:45 ET (close): conviction × 0.9
- Outside RTH: conviction × 0.5

### 4.4 Clarity Score
Measures factor agreement:
- HIGH: >70% of factors agree on direction, all data fresh
- MEDIUM: 50-70% agreement or some stale data
- LOW: <50% agreement (factors violently disagree) or >30% data stale/missing

**LOW clarity = anti-conviction.** Brain should refuse new entries. Sentinel should deny.

### 4.5 Output per Instrument

Published to Redis `market_intel:conviction:{sym}`:
```json
{
  "symbol": "ES",
  "long_conviction": 82,
  "short_conviction": 23,
  "hold_conviction": 75,
  "clarity": "HIGH",
  "matched_pattern": "TREND_ACCELERATION",
  "regime_transition": {"detected": false, "from": null, "to": null},
  "top_factors": ["velocity_15m_bullish", "gex_negative", "vix_confirming"],
  "opposing_factors": ["skew_rising"],
  "relative_volume": 1.35,
  "timestamp": "2026-03-17T10:30:00Z"
}
```

---

## 5. Consumer Integration

### 5.1 market_intel_bridge.py
Same pattern as `sentinel_bridge.py`. Single function:

```python
def get_conviction(symbol: str, direction: str, redis_client=None) -> dict:
    """Returns conviction data for the given instrument and direction."""
    # Returns: {conviction: int, clarity: str, pattern: str|None,
    #           hold_conviction: int, regime_transition: dict,
    #           has_data: bool, sizing_modifier: float}
```

Graceful fallback: no Redis or no data → `{has_data: False, conviction: None, sizing_modifier: 1.0}`

### 5.2 Brain Integration
- During signal evaluation, calls `get_conviction(symbol, signal_direction)`
- `clarity == LOW` → skip signal (anti-conviction, don't trade)
- `matched_pattern` → use pattern's base sizing recommendation
- No pattern → conviction score as sizing multiplier on advisory size
- Regime transition detected → boost weight of strategies aligned with new regime

### 5.3 Sentinel Integration
- New entry sizing modifier based on conviction:
  - `>70 → 1.0x` (full size)
  - `50-70 → 0.75x`
  - `30-50 → 0.5x`
  - `<30 → 0.25x`
  - `clarity == LOW → deny entry` (like HALT)
- Existing positions: reads `hold_conviction` each cycle
  - `<25 → tighten stop` (move to 0.5x ATR from current price)
  - `<15 → flag for early exit`

### 5.4 Dashboard Integration
- New "Market Intel" panel on Live Overview: per-instrument conviction, active pattern, clarity, regime transition alerts
- New API endpoint: `GET /api/intel` → conviction data for all instruments
- New Telegram command: `/intel` → per-instrument conviction snapshot

### 5.5 Feedback Loop
- On every trade entry: log full conviction snapshot + all factor values to ledger as `CONVICTION_SNAPSHOT` event
- On `POSITION_CLOSED`: link outcome (P&L, duration) to the entry conviction snapshot via `position_id`
- Monthly export: pattern hit rate, average P&L by conviction bucket, factor correlation with outcomes
- Used for manual weight recalibration (automated ML recalibration deferred to v2)

---

## 6. IB Subscription Management

IB allows ~50 simultaneous market data subscriptions.

| Category | Count | Always Active |
|----------|-------|---------------|
| Core futures (9) | 9 | Yes |
| Cross-market (5) | 5 | Yes |
| Depth of market (5) | 5 | Yes |
| Tick stream (5) | 5 | Yes — uses same subscription as quotes |
| Options chains | ~20 per instrument | Rotated — 1 instrument at a time |

Total active: ~24 always + ~20 rotating = ~44, under 50 limit.

Options rotation: subscribe to the instrument Brain is currently evaluating. Default rotation cycle: ES → NQ → CL → ES (20s each) when no active evaluation. On-demand: when Brain requests conviction for a specific instrument, prioritize that instrument's options subscription.

---

## 7. File Structure

```
market_intel/
├── prism.py              # Main daemon: IB connection, event loop, orchestration
├── data_layer.py          # Quote/cross/options/DOM/tick polling and Redis caching
├── analytics/
│   ├── velocity.py        # Rate-of-change engine (5m/15m/1h)
│   ├── divergence.py      # Cross-asset divergence detector
│   ├── options_intel.py   # GEX, skew, unusual flow, term structure
│   ├── microstructure.py  # Book imbalance, absorption detection
│   ├── regime_transition.py  # Regime score acceleration detector
│   ├── signal_integrator.py  # Reads news/polymarket signals
│   └── volume_profile.py # Relative volume + time-of-day
├── conviction/
│   ├── pattern_matcher.py # 15+ named patterns with conditions
│   ├── scorer.py          # Weighted fallback + temporal decay
│   ├── time_of_day.py     # TOD conviction modifier
│   └── clarity.py         # Factor agreement scoring
├── market_intel_bridge.py # Consumer interface (get_conviction)
├── feedback.py            # Conviction logging + outcome linking
├── config/
│   ├── patterns.yaml      # Pattern definitions (conditions, scores)
│   ├── weights.yaml       # Factor weights per regime
│   └── subscriptions.yaml # IB contract definitions + rotation config
├── tests/
│   ├── test_velocity.py
│   ├── test_divergence.py
│   ├── test_options_intel.py
│   ├── test_microstructure.py
│   ├── test_pattern_matcher.py
│   ├── test_scorer.py
│   ├── test_conviction.py
│   ├── test_bridge.py
│   └── test_data_layer.py
└── requirements.txt       # ib_insync, redis, numpy
```

---

## 8. Resource Usage

| Resource | Usage | Cost |
|----------|-------|------|
| LLM tokens | Zero — pure deterministic math | $0 |
| IB market data | Already connected, options may need OPRA ($1.50/mo) | ~$0-2/mo |
| Redis | ~50KB per instrument, same existing instance | $0 |
| CPU | Lightweight math every 5-10s | Negligible |
| Memory | ~100MB for tick ring buffers + analytics cache | Negligible |

---

## 9. Testing Strategy

- ~60-80 unit tests covering all analytics engines and conviction scoring
- Mock IB data via `ib_insync` test utilities or fixture data
- Mock Redis via `fakeredis`
- Pattern matcher tests: verify each of the 15 patterns fires correctly given specific input conditions
- Integration tests: end-to-end from mock IB data → Redis → bridge → conviction output
- Feedback loop tests: verify conviction snapshots logged and linked to trade outcomes
- No frontend tests for v1 — visual verification of dashboard panel
