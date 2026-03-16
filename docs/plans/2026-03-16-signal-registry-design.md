# OpenClaw Signal Registry — Design Document

**Date:** 2026-03-16
**Status:** Approved
**Scope:** Tier 1 signal sources integration

---

## 1. Overview

Add a real-time news, sentiment, and external data signal system to OpenClaw Trader. A single async signal daemon polls RSS feeds and the Polymarket API, filters items through a 3-layer pipeline (keyword filter, immediate action keywords, LLM classification), deduplicates, and publishes classified signals to Redis Streams. Sentinel reads these signals on every evaluation cycle to adjust posture/sizing. A new NEWS_DIRECTIONAL setup scanner generates trade candidates from directional signals.

**Key principle:** If Redis or the signal daemon is down, the existing trading system runs normally with its 18 Sentinel rules. Signals are an enhancement, not a dependency.

---

## 2. Decisions Made

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Deployment | Docker-compose on Mac, cloud VM later | Same compose file works everywhere |
| Redis integration | Direct in Sentinel with graceful fallback | Simple, no bridge process needed |
| Rollout | Tier 1 first (8 sources) | Prove value before adding complexity |
| Twitter | Skip for Tier 1 ($100/month) | RSS covers most sources; add in Tier 2 |
| Directional trades | Full spec — NEWS_DIRECTIONAL setup family | Trades go through normal intent pipeline |
| Polymarket | Full implementation (all 4 signal types) | Probability drift is highest-value signal |
| Alerting | Telegram bot | Real-time push to phone, free |
| Architecture | Single async signal daemon (Approach A) | Simplest for 8 sources, Docker auto-restart handles crashes |

---

## 3. System Architecture

```
Signal Daemon (asyncio)
  RSS Collectors (Fed, Reuters, AP, Truth Social, WH, EIA)
  Polymarket Collector
       |
       v
  Layer 1: Keyword Filter (discard 92-95%)
  Layer 2: Immediate Action (HALT/CAUTION, zero cost)
  Layer 3: LLM Classifier (Haiku, ambiguous items only)
       |
       v
  Deduplicator (Redis, 30-min TTL, hash first 80 chars)
       |
       v
  Signal Publisher
    -> Redis: news_signals stream
    -> Redis: polymarket_signals stream
    -> Telegram alerts (HALT, DIRECTIONAL, REDUCE, drift HIGH)
    -> Ledger log
       |
       v (Redis Streams)
  Existing Trading Pipeline
    Sentinel.evaluate_intent()
      check_external_signals()  <-- NEW, reads Redis
      Rule 1..18 (existing, unchanged)
      Sizing (with signal modifiers)
    NEWS_DIRECTIONAL setup scanner  <-- NEW
      reads Redis for DIRECTIONAL signals
      waits for confirmation bars
      emits SetupCandidate -> normal intent flow
```

---

## 4. Tier 1 Sources

| Source ID | URL | Type | Poll Interval | Priority |
|-----------|-----|------|--------------|----------|
| FED_PRESS_RELEASES | federalreserve.gov/feeds/press_all.xml | RSS | 30s | CRITICAL |
| FED_SPEECHES | federalreserve.gov/feeds/speeches.xml | RSS | 60s | HIGH |
| REUTERS_WORLD | feeds.reuters.com/Reuters/worldNews | RSS | 30s | CRITICAL |
| AP_BREAKING | apnews.com/rss | RSS | 30s | CRITICAL |
| TRUMP_TRUTH_SOCIAL | truthsocial.com/@realDonaldTrump.rss | RSS | 15s | CRITICAL |
| WHITE_HOUSE_OFFICIAL | whitehouse.gov/feed/ | RSS | 60s | HIGH |
| EIA_PETROLEUM | eia.gov/petroleum/supply/weekly/ | RSS | 60s | CRITICAL (Wed) |
| POLYMARKET_MONITOR | gamma-api.polymarket.com/markets | REST API | 60s | MEDIUM |

---

## 5. Signal Processing Pipeline

### Layer 1 — Keyword Filter (zero cost)

Discard if headline+summary contains none of:
```
fed, federal reserve, fomc, powell, warsh, fed chair, rate, inflation,
cpi, gdp, jobs, payroll, unemployment, recession, tariff, sanction,
war, attack, invasion, missile, explosion, oil, crude, opec, gold,
treasury, yield, bond, circuit breaker, halt, default, bankruptcy,
bank failure, fdic, china, russia, iran, ukraine, israel, taiwan,
trump, white house, executive order, emergency, eia, petroleum, inventory
```

Expected discard rate: 92-95%.

### Layer 2 — Immediate Action Keywords (zero cost)

**HALT triggers** (action applied before LLM, LLM runs concurrently):
```
circuit breaker activated, trading halted, emergency fed meeting,
nuclear launch, nuclear strike, bank run, fdic receivership,
war declared, market closed, debt ceiling default, invasion began,
coup successful, exchange closed
```

**CAUTION triggers** (action applied before LLM):
```
tariff (from Trump/WH source), oil field attack, strait of hormuz,
bank failure, going concern, chapter 11
```

### Layer 3 — LLM Classification (Haiku)

- Model: `claude-haiku-4-5-20251001`
- Input: ~150 tokens (headline + 150-char summary + source-specific prompt)
- Output: ~80 tokens JSON (tier, direction, instruments, confidence)
- Timeout: 3 seconds — fallback to CAUTION on timeout
- Source-specific prompt templates (Fed, geopolitical, energy)
- Expected volume: 3-8 items/hour normal, 20-40 on event days
- Estimated cost: ~$0.05/day normal, ~$0.50 on busy days

### Deduplication

- Hash first 80 characters of headline
- Store in Redis with 30-minute TTL
- Same story from multiple sources processed only once
- Expected duplicate reduction: 60-70%

### Processing Order

1. Dedup check -> discard if seen
2. Layer 1 keyword filter -> discard if irrelevant
3. Layer 2 immediate action -> apply HALT/CAUTION instantly
4. Layer 3 LLM -> classify ambiguous items (concurrent with Layer 2 action)
5. Publish to Redis stream + Telegram alert + ledger log

---

## 6. Sentinel Integration

### check_external_signals()

Added at start of `evaluate_intent()` in sentinel.py, before existing 18 rules.

1. Connect to Redis, read last 50 entries from `news_signals` and `polymarket_signals`
2. Filter to unexpired signals (`timestamp + duration_minutes > now`)
3. For each active signal affecting current intent's instrument:
   - **HALT** -> deny intent immediately
   - **REDUCE** -> sizing modifier 0.50
   - **CAUTION** -> sizing modifier 0.75, stop distance +25%
   - **DIRECTIONAL** -> no action (handled by setup scanner)
   - **MONITOR** -> log only
4. Multiple signals: take most conservative (HALT > REDUCE > CAUTION)
5. Redis unreachable -> skip entirely, log warning, run normal 18 rules

**Design constraints:**
- Posture modifier is per-evaluation, not persisted. Re-evaluated every cycle.
- Does NOT replace event_calendar.py (Gate 6.5). That handles pre-event suppression. This handles post-event reaction. They complement each other.
- Signal modifiers stack with existing posture/streak/vol modifiers, floored at `risk_multiplier_floor` (0.30).

### Polymarket Regime Confidence Modifier

- 2+ HIGH strength signals same direction, same instrument, past 2 hours -> regime confidence x 1.2
- 2+ HIGH strength signals opposing current position -> regime confidence x 0.8
- Applied via optional `external_confidence_mod` field on regime report dict
- Feeds into sizing only, never creates a trade by itself

---

## 7. NEWS_DIRECTIONAL Setup Scanner

New file: `workspace-c3po/setups/news_directional.py`
New setup family: `NEWS_DIRECTIONAL`
Called by `run_intraday.py` `_scan_setups()` alongside ORB, VWAP, TREND_PULLBACK.

### Logic

1. Each 5-min cycle, read `news_signals` from Redis for DIRECTIONAL_LONG/SHORT signals
2. Check confirmation bar requirement:
   - Standard events: 1 completed 5-min bar, closing in expected direction, volume > 20-bar average
   - Geopolitical events: 2 completed 5-min bars
   - Indecisive bar (body < 30% of range): skip, do not retry
3. If confirmed, emit SetupCandidate:
   - `entry_price`: current market price
   - `stop_price`: 0.75x ATR (tighter than normal 1.5x)
   - `sizing`: 50% of normal (hardcoded, not overridable)
4. Candidate goes through `score_opportunity()` and Sentinel's 18 rules

### Section 16 Entry Rules (enforced in scanner)

1. No entry on initial spike — confirmation bar required
2. Confirmation bar — direction + volume + body >30% check
3. Reduced sizing always — 50% hardcoded
4. Tighter stops — 0.75x ATR
5. Second-order instruments wait — GC/ZB wait for ES on Fed news; NQ waits for ES on China
6. No entries near session close — 30-min buffer
7. Sentinel runs all rules — SetupCandidate goes through normal intent flow
8. One news trade per event — track signal_id, skip if already traded

### Strategy Configs

5 new strategy JSONs: `NEWS_ES.json`, `NEWS_NQ.json`, `NEWS_CL.json`, `NEWS_GC.json`, `NEWS_ZB.json`
All start as INCUBATING with 25% protective sizing (stacks with 50% news reduction = 12.5% effective).

---

## 8. Polymarket Collector

### Monitored Markets

Keyword matching per instrument:
- **ES/NQ:** fed rate, federal reserve, recession, gdp, inflation, cpi, s&p
- **CL:** oil price, crude, opec, iran, saudi, energy
- **GC:** gold price, inflation, fed rate, dollar
- **ZB:** fed rate, treasury, yield, interest rate, debt ceiling

### Signal Types

| Signal | Detection | Threshold | HIGH Threshold | Action |
|--------|-----------|-----------|----------------|--------|
| LARGE_TRADE | Single trade size | > $10K | > $50K | MONITOR |
| FRESH_WALLET | Wallet age + trade size | < 7 days AND > $5K | — | MONITOR + Telegram |
| LIQUIDITY_SPIKE | Liquidity delta per poll | > $25K | > $100K | MONITOR; CAUTION if within 4hrs of FOMC |
| PROBABILITY_DRIFT | Price change over 4-hour window | > 15pp | > 25pp | CAUTION per drift map |

### Drift Tracking

Rolling window of probability snapshots (last 4 hours) per market in Redis. Each poll:
1. Record current probability + timestamp
2. Compare to oldest snapshot in window
3. If delta exceeds threshold -> publish to `polymarket_signals`

### Drift Response Map

- Fed rate cut probability UP -> GC CAUTION (watch LONG), ZB CAUTION (watch LONG)
- Fed rate cut probability DOWN -> GC CAUTION (watch SHORT), ZB CAUTION (watch SHORT)
- Recession probability UP -> ES REDUCE, NQ REDUCE, GC DIRECTIONAL_LONG, ZB DIRECTIONAL_LONG

### Limitation

Polymarket public API may not expose individual wallet ages or trade-level data. LARGE_TRADE and FRESH_WALLET may need WebSocket feed or deferral to Tier 2.

---

## 9. Telegram Alerting

### Setup

Telegram bot via @BotFather. Credentials in env vars:
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

### Alert Rules

| Signal Tier | Alert? |
|-------------|--------|
| HALT | Yes, immediately |
| DIRECTIONAL | Yes |
| REDUCE | Yes |
| CAUTION | No (logged only) |
| MONITOR | No |
| Polymarket PROBABILITY_DRIFT HIGH | Yes |
| Polymarket FRESH_WALLET | Yes |
| Daemon health (crash/restart) | Yes |

### Rate Limiting

Max 20 messages per hour. If exceeded, batch remaining into summary message.

---

## 10. File Structure

```
openclaw_trader/
  signals/
    __init__.py
    base_collector.py          # Abstract base: poll(), parse(), interval
    rss_collector.py           # feedparser-based RSS/Atom polling
    scrape_collector.py        # Stub for Tier 2 (OPEC, USTR, etc.)
    polymarket_collector.py    # REST API + drift detection
    keyword_filter.py          # Layer 1 relevance + Layer 2 immediate action
    llm_classifier.py          # Layer 3 Haiku classification
    deduplicator.py            # Redis hash-based 30-min dedup
    response_matrix.py         # Load + query NEWS_RESPONSE_MAP.yaml
    signal_publisher.py        # Redis Stream writer
    telegram_alerter.py        # Telegram Bot API (HTTP POST, no library)
    signal_daemon.py           # Main asyncio loop
    sentinel_bridge.py         # check_external_signals() for Sentinel
  config/
    NEWS_RESPONSE_MAP.yaml     # Section 17 response map
    sources_tier1.yaml         # Source definitions (URLs, intervals, priority)
    keywords.yaml              # Layer 1 + Layer 2 keyword lists
  tests/
    test_keyword_filter.py
    test_llm_classifier.py
    test_deduplicator.py
    test_response_matrix.py
    test_polymarket_collector.py
    test_news_directional.py
```

### Changes to Existing Files

- `workspace-sentinel/sentinel.py` — add `check_external_signals()` in `evaluate_intent()`
- `workspace-c3po/setups/news_directional.py` — new setup scanner
- `run_intraday.py` — import and call `news_directional.detect()` in `_scan_setups()`
- `strategies/` — 5 new strategy JSONs (NEWS_ES, NEWS_NQ, NEWS_CL, NEWS_GC, NEWS_ZB)
- `requirements.txt` — add feedparser, redis, anthropic, aiohttp, beautifulsoup4, fakeredis
- `shared/contracts.py` — add EventType.NEWS_SIGNAL, EventType.POLYMARKET_SIGNAL

### Docker

```yaml
services:
  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]
    volumes: ["redis_data:/data"]
  signal-daemon:
    build: .
    command: python -m openclaw_trader.signals.signal_daemon
    depends_on: [redis]
    env_file: .env
    restart: unless-stopped
  trading:
    build: .
    command: python run_intraday.py --mode loop
    depends_on: [redis]
    env_file: .env
    restart: unless-stopped
volumes:
  redis_data:
```

### Environment Variables (.env, not committed)

```
REDIS_URL=redis://redis:6379
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
ANTHROPIC_API_KEY=...
```

---

## 11. Testing Strategy

### Unit Tests (no Redis or network required)

| Test File | Coverage |
|-----------|----------|
| test_keyword_filter.py | Layer 1 >90% discard; Layer 2 HALT on all keywords; CAUTION triggers; case insensitivity |
| test_llm_classifier.py | Prompt template selection; JSON parse; timeout fallback to CAUTION; malformed response |
| test_deduplicator.py | 30-min block; different headlines pass; 80-char hash; expiry allows reprocess |
| test_response_matrix.py | All Section 17 events return correct actions; unknown event returns MONITOR |
| test_polymarket_collector.py | Drift at >15pp; no fire below; HIGH at >25pp; liquidity spike; confidence modifier |
| test_news_directional.py | Confirmation bar logic; indecisive skip; 2-bar geo wait; 50% sizing; 0.75x ATR; session buffer; one-trade-per-event; second-order wait |

### Mocking

- Redis: `fakeredis` (in-memory)
- LLM: mock `anthropic` client with canned JSON
- RSS: fixture XML files
- Polymarket: fixture JSON files
- Test isolation: `@pytest.fixture(autouse=True)` with `tmp_path` (existing pattern)

### Integration Tests (require Redis, run in Docker)

| Test | Coverage |
|------|----------|
| RSS to Redis | RSS XML -> rss_collector -> signal in news_signals within 5s |
| Polymarket drift | Probability snapshots -> drift signal in polymarket_signals |
| Sentinel reads signals | HALT signal -> evaluate_intent() denies intent |
| NEWS_DIRECTIONAL E2E | DIRECTIONAL signal + confirming bar -> SetupCandidate with 50% sizing, 0.75x ATR |

---

## 12. Response Map Reference (Section 17)

Full instrument response map stored in `config/NEWS_RESPONSE_MAP.yaml`.
Key events and responses:

| Event | ES | NQ | CL | GC | ZB |
|-------|----|----|----|----|-----|
| FED_RATE_CUT_SURPRISE | LONG | LONG | REDUCE | LONG | LONG |
| FED_RATE_HIKE_SURPRISE | SHORT | SHORT | REDUCE | SHORT | SHORT |
| NFP_STRONG_BEAT | LONG | LONG | IGNORE | SHORT | SHORT |
| NFP_STRONG_MISS | SHORT | SHORT | IGNORE | LONG | LONG |
| CPI_HOT | SHORT | SHORT | CAUTION | LONG | SHORT |
| CPI_COOL | LONG | LONG | CAUTION | SHORT | LONG |
| TRUMP_NEW_TARIFF | SHORT | SHORT | CAUTION | LONG | LONG |
| TRUMP_TARIFF_ROLLBACK | LONG | LONG | IGNORE | SHORT | SHORT |
| MIDDLE_EAST_ESCALATION | HALT | HALT | LONG | LONG | LONG |
| MIDDLE_EAST_CEASEFIRE | LONG | LONG | SHORT | SHORT | IGNORE |
| OPEC_PRODUCTION_CUT | IGNORE | IGNORE | LONG | IGNORE | IGNORE |
| OPEC_PRODUCTION_INCREASE | IGNORE | IGNORE | SHORT | IGNORE | IGNORE |
| BANK_FAILURE_MAJOR | HALT | HALT | HALT | LONG | LONG |
| NUCLEAR_ANY_REFERENCE | HALT | HALT | HALT | HALT | HALT |

Bar confirmation: 1 bar standard, 2 bars geopolitical. All directional at 50% sizing, 0.75x ATR stops.

---

## 13. Tier 2/3 Sources (future)

**Tier 2 (add after Tier 1 proves itself):**
BLS data RSS, BEA data RSS, ISM PMI (scrape), USTR (scrape), Commerce Dept (scrape), OPEC (scrape), Al Jazeera RSS, Times of Israel RSS, Kyiv Independent RSS, SCMP RSS, Twitter API ($100/month)

**Tier 3 (nice-to-have):**
USGS earthquakes, NHC hurricanes, FDIC, SEC 8-K, ECB, BOE, BOJ, BIS, Kitco, World Gold Council, IEA

---

## 14. Costs

| Item | Cost |
|------|------|
| Redis (Docker) | Free |
| Telegram bot | Free |
| RSS feeds | Free |
| Polymarket API | Free |
| Haiku LLM classification | ~$0.05-0.50/day |
| Cloud VM (when ready) | ~$20-40/month |
| Twitter API (Tier 2) | $100/month |
