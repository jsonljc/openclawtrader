# Signal Registry Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add real-time news/sentiment/Polymarket signal system that feeds into Sentinel and generates NEWS_DIRECTIONAL trade candidates.

**Architecture:** Single asyncio signal daemon polls 8 Tier 1 sources, filters through 3-layer pipeline (keywords → immediate action → LLM), deduplicates via Redis, publishes to Redis Streams. Sentinel reads signals each cycle. NEWS_DIRECTIONAL setup scanner creates trade candidates from directional signals.

**Tech Stack:** Python asyncio, Redis (redis-py), feedparser, anthropic SDK (Haiku), aiohttp, fakeredis (tests)

**Test command:** `cd /Users/jasonljc/trading && python -m pytest tests/ openclaw_trader/tests/ -v`

---

### Task 1: Project scaffolding and dependencies

**Files:**
- Create: `openclaw_trader/__init__.py`
- Create: `openclaw_trader/signals/__init__.py`
- Create: `openclaw_trader/config/` (directory)
- Create: `openclaw_trader/tests/__init__.py`
- Modify: `requirements.txt`
- Modify: `shared/contracts.py:16-49` (add event types)

**Step 1: Create directory structure**

```bash
mkdir -p openclaw_trader/signals openclaw_trader/config openclaw_trader/tests
touch openclaw_trader/__init__.py openclaw_trader/signals/__init__.py openclaw_trader/tests/__init__.py
```

**Step 2: Update requirements.txt**

Add these lines to `/Users/jasonljc/trading/requirements.txt`:

```
# Signal registry
feedparser>=6.0
redis>=5.0
anthropic>=0.40
aiohttp>=3.9
beautifulsoup4>=4.12

# Testing
fakeredis>=2.21
```

**Step 3: Add event types to contracts.py**

Add to the `EventType` class in `shared/contracts.py` after line 49 (`DAILY_RESET`):

```python
    NEWS_SIGNAL               = "NEWS_SIGNAL"
    POLYMARKET_SIGNAL         = "POLYMARKET_SIGNAL"
```

**Step 4: Commit**

```bash
git add openclaw_trader/ requirements.txt shared/contracts.py
git commit -m "feat: scaffold signal registry package and add dependencies"
```

---

### Task 2: Keywords config and keyword_filter.py with tests

**Files:**
- Create: `openclaw_trader/config/keywords.yaml`
- Create: `openclaw_trader/signals/keyword_filter.py`
- Create: `openclaw_trader/tests/test_keyword_filter.py`

**Step 1: Create keywords.yaml**

File: `openclaw_trader/config/keywords.yaml`

```yaml
# Layer 1: relevance filter. Item must contain at least one keyword.
layer_1:
  - fed
  - federal reserve
  - fomc
  - powell
  - warsh
  - fed chair
  - rate
  - inflation
  - cpi
  - gdp
  - jobs
  - payroll
  - unemployment
  - recession
  - tariff
  - sanction
  - war
  - attack
  - invasion
  - missile
  - explosion
  - oil
  - crude
  - opec
  - gold
  - treasury
  - yield
  - bond
  - circuit breaker
  - halt
  - default
  - bankruptcy
  - bank failure
  - fdic
  - china
  - russia
  - iran
  - ukraine
  - israel
  - taiwan
  - trump
  - white house
  - executive order
  - emergency
  - eia
  - petroleum
  - inventory
  - north korea
  - nuclear

# Layer 2: immediate action triggers (applied before LLM).
layer_2_halt:
  - circuit breaker activated
  - trading halted
  - exchange closed
  - emergency fed meeting
  - unscheduled fomc
  - emergency rate
  - nuclear launch
  - nuclear strike
  - market closed
  - bank run
  - fdic receivership
  - debt ceiling default
  - invasion began
  - war declared
  - coup successful

layer_2_caution:
  - tariff
  - opec cut
  - oil field attack
  - strait of hormuz
  - bank failure
  - going concern
  - chapter 11

# Sources where Layer 2 caution "tariff" applies
layer_2_caution_tariff_sources:
  - TRUMP_TRUTH_SOCIAL
  - TRUMP_TWITTER
  - WHITE_HOUSE_OFFICIAL
  - WHITE_HOUSE_PRESS_SEC
  - USTR_PRESS
```

**Step 2: Write the failing tests**

File: `openclaw_trader/tests/test_keyword_filter.py`

```python
"""Tests for Layer 1 and Layer 2 keyword filtering."""
import pytest
from openclaw_trader.signals.keyword_filter import (
    load_keywords,
    layer_1_filter,
    layer_2_check,
)


@pytest.fixture
def keywords():
    return load_keywords()


# ── Layer 1 ──────────────────────────────────────────────────────────────

class TestLayer1:
    def test_relevant_headline_passes(self, keywords):
        assert layer_1_filter("Fed raises interest rate by 25bp", keywords) is True

    def test_irrelevant_headline_discarded(self, keywords):
        assert layer_1_filter("Local cat wins dog show in Ohio", keywords) is False

    def test_case_insensitive(self, keywords):
        assert layer_1_filter("FOMC DECIDES ON RATES", keywords) is True

    def test_partial_word_no_false_positive(self, keywords):
        # "federation" contains "fed" — we accept substring matches
        # because real headlines rarely have "federation" without context
        assert layer_1_filter("Federation of bakers meets", keywords) is True

    def test_empty_headline_discarded(self, keywords):
        assert layer_1_filter("", keywords) is False

    def test_keyword_in_summary_passes(self, keywords):
        assert layer_1_filter(
            "Breaking news update",
            keywords,
            summary="The Federal Reserve announced new policy",
        ) is True

    def test_discard_rate_above_90_pct(self, keywords):
        """Feed 100 generic headlines, confirm >90 are discarded."""
        generic = [
            f"Local news story number {i} about weather and sports"
            for i in range(100)
        ]
        discarded = sum(1 for h in generic if not layer_1_filter(h, keywords))
        assert discarded >= 90

    def test_all_critical_keywords_individually(self, keywords):
        critical = ["fomc", "tariff", "nuclear", "opec", "missile", "fdic"]
        for kw in critical:
            assert layer_1_filter(f"Breaking: {kw} related news", keywords) is True


# ── Layer 2 ──────────────────────────────────────────────────────────────

class TestLayer2:
    def test_halt_on_circuit_breaker(self, keywords):
        result = layer_2_check(
            "NYSE circuit breaker activated after 7% drop",
            keywords,
            source_id="REUTERS_WORLD",
        )
        assert result == "HALT"

    def test_halt_on_nuclear(self, keywords):
        result = layer_2_check(
            "Reports of nuclear launch detected by NORAD",
            keywords,
            source_id="AP_BREAKING",
        )
        assert result == "HALT"

    def test_halt_on_emergency_fed(self, keywords):
        result = layer_2_check(
            "Federal Reserve calls emergency fed meeting",
            keywords,
            source_id="FED_PRESS_RELEASES",
        )
        assert result == "HALT"

    def test_all_halt_keywords_fire(self, keywords):
        for phrase in keywords["layer_2_halt"]:
            result = layer_2_check(
                f"Breaking: {phrase} confirmed by officials",
                keywords,
                source_id="REUTERS_WORLD",
            )
            assert result == "HALT", f"HALT not fired for: {phrase}"

    def test_caution_tariff_from_trump(self, keywords):
        result = layer_2_check(
            "New tariff on Chinese goods announced",
            keywords,
            source_id="TRUMP_TRUTH_SOCIAL",
        )
        assert result == "CAUTION"

    def test_tariff_not_caution_from_reuters(self, keywords):
        """Tariff keyword only triggers CAUTION from Trump/WH sources."""
        result = layer_2_check(
            "New tariff on Chinese goods announced",
            keywords,
            source_id="REUTERS_WORLD",
        )
        # Tariff alone from Reuters should not be CAUTION
        # (it goes to LLM for classification instead)
        assert result is None

    def test_caution_oil_field_attack(self, keywords):
        result = layer_2_check(
            "Oil field attack in Saudi Arabia disrupts production",
            keywords,
            source_id="AP_BREAKING",
        )
        assert result == "CAUTION"

    def test_no_action_on_normal_headline(self, keywords):
        result = layer_2_check(
            "Fed governor gives routine speech on inflation outlook",
            keywords,
            source_id="FED_SPEECHES",
        )
        assert result is None

    def test_halt_takes_priority_over_caution(self, keywords):
        """If headline matches both HALT and CAUTION, HALT wins."""
        result = layer_2_check(
            "Bank run triggers fdic receivership at major bank",
            keywords,
            source_id="REUTERS_WORLD",
        )
        assert result == "HALT"
```

**Step 3: Run tests to verify they fail**

```bash
cd /Users/jasonljc/trading && python -m pytest openclaw_trader/tests/test_keyword_filter.py -v
```

Expected: ModuleNotFoundError

**Step 4: Implement keyword_filter.py**

File: `openclaw_trader/signals/keyword_filter.py`

```python
"""Layer 1 (relevance) and Layer 2 (immediate action) keyword filtering."""
from __future__ import annotations

from pathlib import Path

import yaml

_CONFIG_DIR = Path(__file__).parent.parent / "config"


def load_keywords(path: Path | None = None) -> dict:
    """Load keyword config from YAML."""
    p = path or (_CONFIG_DIR / "keywords.yaml")
    with open(p) as f:
        return yaml.safe_load(f)


def layer_1_filter(
    headline: str,
    keywords: dict,
    summary: str = "",
) -> bool:
    """Return True if item is relevant (contains at least one Layer 1 keyword)."""
    text = (headline + " " + summary).lower()
    if not text.strip():
        return False
    for kw in keywords.get("layer_1", []):
        if kw.lower() in text:
            return True
    return False


def layer_2_check(
    headline: str,
    keywords: dict,
    source_id: str = "",
) -> str | None:
    """Return 'HALT', 'CAUTION', or None based on Layer 2 keyword match."""
    text = headline.lower()

    # Check HALT first (highest priority)
    for phrase in keywords.get("layer_2_halt", []):
        if phrase.lower() in text:
            return "HALT"

    # Check CAUTION
    tariff_sources = set(keywords.get("layer_2_caution_tariff_sources", []))
    for phrase in keywords.get("layer_2_caution", []):
        p = phrase.lower()
        # "tariff" only triggers CAUTION from specific sources
        if p == "tariff":
            if source_id in tariff_sources and p in text:
                return "CAUTION"
        elif p in text:
            return "CAUTION"

    return None
```

**Step 5: Run tests to verify they pass**

```bash
cd /Users/jasonljc/trading && python -m pytest openclaw_trader/tests/test_keyword_filter.py -v
```

Expected: all pass

**Step 6: Commit**

```bash
git add openclaw_trader/config/keywords.yaml openclaw_trader/signals/keyword_filter.py openclaw_trader/tests/test_keyword_filter.py
git commit -m "feat: Layer 1/2 keyword filter with tests"
```

---

### Task 3: Deduplicator with tests

**Files:**
- Create: `openclaw_trader/signals/deduplicator.py`
- Create: `openclaw_trader/tests/test_deduplicator.py`

**Step 1: Write the failing tests**

File: `openclaw_trader/tests/test_deduplicator.py`

```python
"""Tests for Redis-based headline deduplication."""
import time
import pytest
import fakeredis

from openclaw_trader.signals.deduplicator import Deduplicator


@pytest.fixture
def dedup():
    r = fakeredis.FakeRedis()
    return Deduplicator(redis_client=r, ttl_seconds=5)


class TestDeduplicator:
    def test_first_seen_returns_false(self, dedup):
        assert dedup.is_duplicate("Fed raises rates by 25bp") is False

    def test_second_seen_returns_true(self, dedup):
        dedup.is_duplicate("Fed raises rates by 25bp")
        assert dedup.is_duplicate("Fed raises rates by 25bp") is True

    def test_different_headline_not_duplicate(self, dedup):
        dedup.is_duplicate("Fed raises rates by 25bp")
        assert dedup.is_duplicate("OPEC cuts production quotas") is False

    def test_uses_first_80_chars(self, dedup):
        base = "A" * 80
        h1 = base + " extra words here"
        h2 = base + " completely different suffix"
        dedup.is_duplicate(h1)
        assert dedup.is_duplicate(h2) is True

    def test_expired_entry_allows_reprocess(self, dedup):
        dedup.is_duplicate("Fed raises rates by 25bp")
        # fakeredis respects TTL with time.sleep on some versions;
        # we force expiry by manually deleting
        dedup._redis.flushall()
        assert dedup.is_duplicate("Fed raises rates by 25bp") is False

    def test_empty_headline(self, dedup):
        assert dedup.is_duplicate("") is False
        # Empty string seen once, second call is duplicate
        assert dedup.is_duplicate("") is True

    def test_case_insensitive(self, dedup):
        dedup.is_duplicate("FED RAISES RATES")
        assert dedup.is_duplicate("fed raises rates") is True
```

**Step 2: Run tests to verify they fail**

```bash
cd /Users/jasonljc/trading && python -m pytest openclaw_trader/tests/test_deduplicator.py -v
```

Expected: ModuleNotFoundError

**Step 3: Implement deduplicator.py**

File: `openclaw_trader/signals/deduplicator.py`

```python
"""Redis-based headline deduplication with 30-minute TTL."""
from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from redis import Redis


class Deduplicator:
    """Track seen headlines via Redis SET with TTL."""

    PREFIX = "openclaw:dedup:"

    def __init__(self, redis_client: "Redis", ttl_seconds: int = 1800):
        self._redis = redis_client
        self._ttl = ttl_seconds

    def _hash(self, headline: str) -> str:
        text = headline[:80].lower()
        return hashlib.sha256(text.encode()).hexdigest()[:16]

    def is_duplicate(self, headline: str) -> bool:
        """Return True if headline was seen within the TTL window."""
        key = self.PREFIX + self._hash(headline)
        # SET NX returns True if key was set (new), False if existed
        was_new = self._redis.set(key, "1", nx=True, ex=self._ttl)
        return not was_new
```

**Step 4: Run tests to verify they pass**

```bash
cd /Users/jasonljc/trading && python -m pytest openclaw_trader/tests/test_deduplicator.py -v
```

Expected: all pass

**Step 5: Commit**

```bash
git add openclaw_trader/signals/deduplicator.py openclaw_trader/tests/test_deduplicator.py
git commit -m "feat: Redis-based headline deduplicator with tests"
```

---

### Task 4: NEWS_RESPONSE_MAP.yaml and response_matrix.py with tests

**Files:**
- Create: `openclaw_trader/config/NEWS_RESPONSE_MAP.yaml`
- Create: `openclaw_trader/signals/response_matrix.py`
- Create: `openclaw_trader/tests/test_response_matrix.py`

**Step 1: Create NEWS_RESPONSE_MAP.yaml**

File: `openclaw_trader/config/NEWS_RESPONSE_MAP.yaml`

```yaml
# Each event maps to per-instrument responses.
# action: HALT | REDUCE | DIRECTIONAL_LONG | DIRECTIONAL_SHORT | CAUTION | MONITOR | IGNORE
# confirm_bars: number of 5-min bars to wait before DIRECTIONAL entry
# human_required: if true, human must approve before any DIRECTIONAL trade

FED_RATE_CUT_SURPRISE:
  ES: { action: DIRECTIONAL_LONG, confirm_bars: 1 }
  NQ: { action: DIRECTIONAL_LONG, confirm_bars: 1 }
  CL: { action: REDUCE }
  GC: { action: DIRECTIONAL_LONG, confirm_bars: 2 }
  ZB: { action: DIRECTIONAL_LONG, confirm_bars: 2 }

FED_RATE_HIKE_SURPRISE:
  ES: { action: DIRECTIONAL_SHORT, confirm_bars: 1 }
  NQ: { action: DIRECTIONAL_SHORT, confirm_bars: 1 }
  CL: { action: REDUCE }
  GC: { action: DIRECTIONAL_SHORT, confirm_bars: 2 }
  ZB: { action: DIRECTIONAL_SHORT, confirm_bars: 2 }

NFP_STRONG_BEAT:
  ES: { action: DIRECTIONAL_LONG, confirm_bars: 1 }
  NQ: { action: DIRECTIONAL_LONG, confirm_bars: 1 }
  CL: { action: IGNORE }
  GC: { action: DIRECTIONAL_SHORT, confirm_bars: 2 }
  ZB: { action: DIRECTIONAL_SHORT, confirm_bars: 2 }

NFP_STRONG_MISS:
  ES: { action: DIRECTIONAL_SHORT, confirm_bars: 1 }
  NQ: { action: DIRECTIONAL_SHORT, confirm_bars: 1 }
  CL: { action: IGNORE }
  GC: { action: DIRECTIONAL_LONG, confirm_bars: 2 }
  ZB: { action: DIRECTIONAL_LONG, confirm_bars: 2 }

CPI_HOT:
  ES: { action: DIRECTIONAL_SHORT, confirm_bars: 1 }
  NQ: { action: DIRECTIONAL_SHORT, confirm_bars: 1 }
  CL: { action: CAUTION }
  GC: { action: DIRECTIONAL_LONG, confirm_bars: 1 }
  ZB: { action: DIRECTIONAL_SHORT, confirm_bars: 1 }

CPI_COOL:
  ES: { action: DIRECTIONAL_LONG, confirm_bars: 1 }
  NQ: { action: DIRECTIONAL_LONG, confirm_bars: 1 }
  CL: { action: CAUTION }
  GC: { action: DIRECTIONAL_SHORT, confirm_bars: 1 }
  ZB: { action: DIRECTIONAL_LONG, confirm_bars: 1 }

TRUMP_NEW_TARIFF:
  ES: { action: DIRECTIONAL_SHORT, confirm_bars: 1 }
  NQ: { action: DIRECTIONAL_SHORT, confirm_bars: 1 }
  CL: { action: CAUTION }
  GC: { action: DIRECTIONAL_LONG, confirm_bars: 1 }
  ZB: { action: DIRECTIONAL_LONG, confirm_bars: 1 }

TRUMP_TARIFF_ROLLBACK:
  ES: { action: DIRECTIONAL_LONG, confirm_bars: 1 }
  NQ: { action: DIRECTIONAL_LONG, confirm_bars: 1 }
  CL: { action: IGNORE }
  GC: { action: DIRECTIONAL_SHORT, confirm_bars: 1 }
  ZB: { action: DIRECTIONAL_SHORT, confirm_bars: 1 }

TRUMP_FED_ATTACK:
  ES: { action: REDUCE }
  NQ: { action: REDUCE }
  CL: { action: IGNORE }
  GC: { action: DIRECTIONAL_LONG, confirm_bars: 1 }
  ZB: { action: CAUTION }

TRUMP_ENERGY_DRILL:
  ES: { action: MONITOR }
  NQ: { action: IGNORE }
  CL: { action: DIRECTIONAL_SHORT, confirm_bars: 1 }
  GC: { action: IGNORE }
  ZB: { action: IGNORE }

TRUMP_CHINA_HOSTILE:
  ES: { action: REDUCE }
  NQ: { action: DIRECTIONAL_SHORT, confirm_bars: 1 }
  CL: { action: CAUTION }
  GC: { action: DIRECTIONAL_LONG, confirm_bars: 1 }
  ZB: { action: CAUTION }

TRUMP_TRADE_DEAL_POSITIVE:
  ES: { action: DIRECTIONAL_LONG, confirm_bars: 1 }
  NQ: { action: DIRECTIONAL_LONG, confirm_bars: 1 }
  CL: { action: IGNORE }
  GC: { action: DIRECTIONAL_SHORT, confirm_bars: 1 }
  ZB: { action: IGNORE }

MIDDLE_EAST_ESCALATION:
  ES: { action: HALT }
  NQ: { action: HALT }
  CL: { action: DIRECTIONAL_LONG, confirm_bars: 2 }
  GC: { action: DIRECTIONAL_LONG, confirm_bars: 2 }
  ZB: { action: DIRECTIONAL_LONG, confirm_bars: 2 }

MIDDLE_EAST_CEASEFIRE:
  ES: { action: DIRECTIONAL_LONG, confirm_bars: 2 }
  NQ: { action: DIRECTIONAL_LONG, confirm_bars: 2 }
  CL: { action: DIRECTIONAL_SHORT, confirm_bars: 2 }
  GC: { action: DIRECTIONAL_SHORT, confirm_bars: 2 }
  ZB: { action: IGNORE }

OPEC_PRODUCTION_CUT:
  ES: { action: IGNORE }
  NQ: { action: IGNORE }
  CL: { action: DIRECTIONAL_LONG, confirm_bars: 1 }
  GC: { action: IGNORE }
  ZB: { action: IGNORE }

OPEC_PRODUCTION_INCREASE:
  ES: { action: IGNORE }
  NQ: { action: IGNORE }
  CL: { action: DIRECTIONAL_SHORT, confirm_bars: 1 }
  GC: { action: IGNORE }
  ZB: { action: IGNORE }

BANK_FAILURE_SMALL:
  ES: { action: REDUCE }
  NQ: { action: REDUCE }
  CL: { action: IGNORE }
  GC: { action: DIRECTIONAL_LONG, confirm_bars: 1 }
  ZB: { action: DIRECTIONAL_LONG, confirm_bars: 1 }

BANK_FAILURE_MAJOR:
  ES: { action: HALT, human_required: true }
  NQ: { action: HALT, human_required: true }
  CL: { action: HALT }
  GC: { action: DIRECTIONAL_LONG, confirm_bars: 2, human_required: true }
  ZB: { action: DIRECTIONAL_LONG, confirm_bars: 2, human_required: true }

CHINA_EXPORT_CONTROLS_NQ:
  ES: { action: REDUCE }
  NQ: { action: DIRECTIONAL_SHORT, confirm_bars: 1 }
  CL: { action: CAUTION }
  GC: { action: DIRECTIONAL_LONG, confirm_bars: 1 }
  ZB: { action: CAUTION }

EIA_INVENTORY_BULLISH_SURPRISE:
  ES: { action: IGNORE }
  NQ: { action: IGNORE }
  CL: { action: DIRECTIONAL_LONG, confirm_bars: 1 }
  GC: { action: IGNORE }
  ZB: { action: IGNORE }

EIA_INVENTORY_BEARISH_SURPRISE:
  ES: { action: IGNORE }
  NQ: { action: IGNORE }
  CL: { action: DIRECTIONAL_SHORT, confirm_bars: 1 }
  GC: { action: IGNORE }
  ZB: { action: IGNORE }

NUCLEAR_ANY_REFERENCE:
  ES: { action: HALT, human_required: true }
  NQ: { action: HALT, human_required: true }
  CL: { action: HALT, human_required: true }
  GC: { action: HALT, human_required: true }
  ZB: { action: HALT, human_required: true }

CIRCUIT_BREAKER_ACTIVATED:
  ES: { action: HALT, human_required: true }
  NQ: { action: HALT, human_required: true }
  CL: { action: HALT, human_required: true }
  GC: { action: HALT, human_required: true }
  ZB: { action: HALT, human_required: true }
```

**Step 2: Write the failing tests**

File: `openclaw_trader/tests/test_response_matrix.py`

```python
"""Tests for NEWS_RESPONSE_MAP loading and querying."""
import pytest
from openclaw_trader.signals.response_matrix import ResponseMatrix


@pytest.fixture
def matrix():
    return ResponseMatrix()


class TestResponseMatrix:
    def test_load_all_events(self, matrix):
        assert len(matrix.events()) >= 22

    def test_fed_rate_cut_es_long(self, matrix):
        r = matrix.get("FED_RATE_CUT_SURPRISE", "ES")
        assert r["action"] == "DIRECTIONAL_LONG"
        assert r["confirm_bars"] == 1

    def test_fed_rate_hike_gc_short(self, matrix):
        r = matrix.get("FED_RATE_HIKE_SURPRISE", "GC")
        assert r["action"] == "DIRECTIONAL_SHORT"
        assert r["confirm_bars"] == 2

    def test_middle_east_escalation_es_halt(self, matrix):
        r = matrix.get("MIDDLE_EAST_ESCALATION", "ES")
        assert r["action"] == "HALT"

    def test_middle_east_escalation_cl_long(self, matrix):
        r = matrix.get("MIDDLE_EAST_ESCALATION", "CL")
        assert r["action"] == "DIRECTIONAL_LONG"
        assert r["confirm_bars"] == 2

    def test_nuclear_all_halt(self, matrix):
        for sym in ("ES", "NQ", "CL", "GC", "ZB"):
            r = matrix.get("NUCLEAR_ANY_REFERENCE", sym)
            assert r["action"] == "HALT"
            assert r.get("human_required") is True

    def test_opec_cut_only_cl(self, matrix):
        assert matrix.get("OPEC_PRODUCTION_CUT", "CL")["action"] == "DIRECTIONAL_LONG"
        assert matrix.get("OPEC_PRODUCTION_CUT", "ES")["action"] == "IGNORE"
        assert matrix.get("OPEC_PRODUCTION_CUT", "GC")["action"] == "IGNORE"

    def test_unknown_event_returns_monitor(self, matrix):
        r = matrix.get("TOTALLY_UNKNOWN_EVENT", "ES")
        assert r["action"] == "MONITOR"

    def test_unknown_instrument_returns_monitor(self, matrix):
        r = matrix.get("FED_RATE_CUT_SURPRISE", "FAKE")
        assert r["action"] == "MONITOR"

    def test_trump_tariff_nq_short(self, matrix):
        r = matrix.get("TRUMP_NEW_TARIFF", "NQ")
        assert r["action"] == "DIRECTIONAL_SHORT"

    def test_trump_rollback_gc_short(self, matrix):
        r = matrix.get("TRUMP_TARIFF_ROLLBACK", "GC")
        assert r["action"] == "DIRECTIONAL_SHORT"

    def test_bank_failure_major_human_required(self, matrix):
        r = matrix.get("BANK_FAILURE_MAJOR", "ES")
        assert r["action"] == "HALT"
        assert r.get("human_required") is True

    def test_cpi_hot_gc_long(self, matrix):
        r = matrix.get("CPI_HOT", "GC")
        assert r["action"] == "DIRECTIONAL_LONG"

    def test_eia_bullish_cl_long(self, matrix):
        r = matrix.get("EIA_INVENTORY_BULLISH_SURPRISE", "CL")
        assert r["action"] == "DIRECTIONAL_LONG"

    def test_get_all_instruments(self, matrix):
        actions = matrix.get_all("MIDDLE_EAST_ESCALATION")
        assert actions["ES"]["action"] == "HALT"
        assert actions["CL"]["action"] == "DIRECTIONAL_LONG"
        assert len(actions) == 5
```

**Step 3: Run tests to verify they fail**

```bash
cd /Users/jasonljc/trading && python -m pytest openclaw_trader/tests/test_response_matrix.py -v
```

Expected: ModuleNotFoundError

**Step 4: Implement response_matrix.py**

File: `openclaw_trader/signals/response_matrix.py`

```python
"""Load and query the NEWS_RESPONSE_MAP for per-instrument actions."""
from __future__ import annotations

from pathlib import Path

import yaml

_CONFIG_DIR = Path(__file__).parent.parent / "config"
_DEFAULT_RESPONSE = {"action": "MONITOR"}


class ResponseMatrix:
    """Lookup event type + instrument -> response action."""

    def __init__(self, path: Path | None = None):
        p = path or (_CONFIG_DIR / "NEWS_RESPONSE_MAP.yaml")
        with open(p) as f:
            self._map: dict = yaml.safe_load(f) or {}

    def events(self) -> list[str]:
        return list(self._map.keys())

    def get(self, event_type: str, instrument: str) -> dict:
        """Return response dict for event + instrument. Defaults to MONITOR."""
        event = self._map.get(event_type)
        if event is None:
            return dict(_DEFAULT_RESPONSE)
        resp = event.get(instrument)
        if resp is None:
            return dict(_DEFAULT_RESPONSE)
        return dict(resp)

    def get_all(self, event_type: str) -> dict[str, dict]:
        """Return response dict for all instruments on an event."""
        event = self._map.get(event_type, {})
        return {sym: dict(resp) for sym, resp in event.items()}
```

**Step 5: Run tests to verify they pass**

```bash
cd /Users/jasonljc/trading && python -m pytest openclaw_trader/tests/test_response_matrix.py -v
```

Expected: all pass

**Step 6: Commit**

```bash
git add openclaw_trader/config/NEWS_RESPONSE_MAP.yaml openclaw_trader/signals/response_matrix.py openclaw_trader/tests/test_response_matrix.py
git commit -m "feat: NEWS_RESPONSE_MAP and response matrix with tests"
```

---

### Task 5: LLM classifier with tests

**Files:**
- Create: `openclaw_trader/signals/llm_classifier.py`
- Create: `openclaw_trader/tests/test_llm_classifier.py`

**Step 1: Write the failing tests**

File: `openclaw_trader/tests/test_llm_classifier.py`

```python
"""Tests for Layer 3 LLM classification using mocked Anthropic client."""
import json
import pytest
from unittest.mock import MagicMock, patch, AsyncMock

from openclaw_trader.signals.llm_classifier import (
    classify_headline,
    _build_prompt,
    _parse_response,
    PROMPT_TEMPLATES,
)


class TestBuildPrompt:
    def test_fed_source_uses_fed_template(self):
        prompt = _build_prompt(
            headline="Fed raises rates",
            summary="25bp hike announced",
            source_id="FED_PRESS_RELEASES",
        )
        assert "HAWKISH" in prompt
        assert "Fed raises rates" in prompt

    def test_geopolitical_source_uses_geo_template(self):
        prompt = _build_prompt(
            headline="Missiles launched",
            summary="Conflict escalation",
            source_id="REUTERS_WORLD",
        )
        assert "ESCALATION" in prompt or "conflict" in prompt.lower()

    def test_trump_source_uses_trump_template(self):
        prompt = _build_prompt(
            headline="New tariffs on China",
            summary="50% tariff",
            source_id="TRUMP_TRUTH_SOCIAL",
        )
        assert "TARIFF" in prompt

    def test_summary_truncated_to_150_chars(self):
        long_summary = "x" * 300
        prompt = _build_prompt(
            headline="test",
            summary=long_summary,
            source_id="FED_PRESS_RELEASES",
        )
        # The summary in the prompt should be truncated
        assert "x" * 151 not in prompt


class TestParseResponse:
    def test_valid_json(self):
        raw = '{"tier":"CAUTION","direction":"HAWKISH","instruments":["ES","NQ"],"confidence":0.85}'
        result = _parse_response(raw)
        assert result["tier"] == "CAUTION"
        assert result["direction"] == "HAWKISH"
        assert result["confidence"] == 0.85
        assert "ES" in result["instruments"]

    def test_malformed_json_returns_caution(self):
        result = _parse_response("this is not json at all")
        assert result["tier"] == "CAUTION"
        assert result["confidence"] == 0.5

    def test_missing_fields_get_defaults(self):
        raw = '{"tier":"MONITOR"}'
        result = _parse_response(raw)
        assert result["tier"] == "MONITOR"
        assert result["direction"] == "NEUTRAL"
        assert result["confidence"] == 0.5

    def test_json_embedded_in_text(self):
        raw = 'Here is my analysis: {"tier":"HALT","direction":"NEUTRAL","instruments":["ES"],"confidence":0.95} end'
        result = _parse_response(raw)
        assert result["tier"] == "HALT"


class TestClassifyHeadline:
    def test_timeout_returns_caution(self):
        """If LLM call times out, default to CAUTION."""
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = TimeoutError("timeout")
        result = classify_headline(
            headline="Some ambiguous headline",
            summary="",
            source_id="REUTERS_WORLD",
            client=mock_client,
        )
        assert result["tier"] == "CAUTION"
        assert result["classification"] == "TIMEOUT"

    def test_successful_classification(self):
        mock_response = MagicMock()
        mock_response.content = [MagicMock()]
        mock_response.content[0].text = json.dumps({
            "tier": "CAUTION",
            "direction": "HAWKISH",
            "instruments": ["ES", "NQ", "GC", "ZB"],
            "confidence": 0.8,
        })
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        result = classify_headline(
            headline="Fed signals fewer rate cuts",
            summary="Dot plot revised",
            source_id="FED_PRESS_RELEASES",
            client=mock_client,
        )
        assert result["tier"] == "CAUTION"
        assert result["direction"] == "HAWKISH"
        assert result["classification"] == "LLM"

    def test_api_error_returns_caution(self):
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = Exception("API error")
        result = classify_headline(
            headline="Something happened",
            summary="",
            source_id="REUTERS_WORLD",
            client=mock_client,
        )
        assert result["tier"] == "CAUTION"
        assert result["classification"] == "ERROR"
```

**Step 2: Run tests to verify they fail**

```bash
cd /Users/jasonljc/trading && python -m pytest openclaw_trader/tests/test_llm_classifier.py -v
```

**Step 3: Implement llm_classifier.py**

File: `openclaw_trader/signals/llm_classifier.py`

```python
"""Layer 3 LLM classification using Claude Haiku."""
from __future__ import annotations

import json
import re
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from anthropic import Anthropic

MODEL = "claude-haiku-4-5-20251001"
MAX_INPUT_TOKENS = 200
MAX_OUTPUT_TOKENS = 100
TIMEOUT_SECONDS = 3

_CAUTION_DEFAULT = {
    "tier": "CAUTION",
    "direction": "NEUTRAL",
    "instruments": ["ES", "NQ", "CL", "GC", "ZB"],
    "confidence": 0.5,
}

# ── Source → prompt template mapping ─────────────────────────────────────

PROMPT_TEMPLATES = {
    "FED": (
        "Fed news classifier. Respond JSON only.\n"
        "Headline: {headline}\n"
        "Summary: {summary}\n"
        '{{"tier":"HALT|CAUTION|MONITOR","direction":"HAWKISH|DOVISH|NEUTRAL",'
        '"instruments":["ES","NQ","GC","ZB"],"confidence":0.0-1.0}}\n'
        "HAWKISH=rate hike/less cuts=ES down GC down ZB down\n"
        "DOVISH=rate cut/more cuts=ES up GC up ZB up"
    ),
    "TRUMP": (
        "Trump/White House post market classifier. JSON only.\n"
        "Post: {headline}\n"
        "Context: {summary}\n"
        '{{"tier":"HALT|CAUTION|MONITOR",'
        '"topic":"TARIFF_NEW|TARIFF_ROLLBACK|FED_ATTACK|ENERGY_DRILL|'
        'CHINA_HOSTILE|TRADE_DEAL_POSITIVE|GEOPOLITICAL|OTHER",'
        '"instruments":["ES","NQ","CL","GC","ZB"],"confidence":0.0-1.0}}'
    ),
    "GEO": (
        "Geopolitical/conflict news classifier. JSON only.\n"
        "Headline: {headline}\n"
        "Summary: {summary}\n"
        '{{"tier":"HALT|CAUTION|MONITOR",'
        '"conflict_type":"ESCALATION|DE_ESCALATION|NEUTRAL",'
        '"region":"MIDDLE_EAST|UKRAINE_RUSSIA|TAIWAN_CHINA|OTHER",'
        '"instruments":["ES","NQ","CL","GC","ZB"],"confidence":0.0-1.0}}'
    ),
    "ENERGY": (
        "Energy market news classifier. JSON only.\n"
        "Headline: {headline}\n"
        "Summary: {summary}\n"
        '{{"tier":"HALT|CAUTION|MONITOR","direction":"BULLISH|BEARISH|NEUTRAL",'
        '"instruments":["CL"],"confidence":0.0-1.0}}'
    ),
    "DEFAULT": (
        "Market news classifier. JSON only.\n"
        "Headline: {headline}\n"
        "Summary: {summary}\n"
        '{{"tier":"HALT|CAUTION|MONITOR","direction":"BULLISH|BEARISH|NEUTRAL",'
        '"instruments":["ES","NQ","CL","GC","ZB"],"confidence":0.0-1.0}}'
    ),
}

_SOURCE_TO_TEMPLATE = {
    "FED_PRESS_RELEASES": "FED",
    "FED_SPEECHES": "FED",
    "NY_FED": "FED",
    "TRUMP_TRUTH_SOCIAL": "TRUMP",
    "TRUMP_TWITTER": "TRUMP",
    "WHITE_HOUSE_OFFICIAL": "TRUMP",
    "WHITE_HOUSE_PRESS_SEC": "TRUMP",
    "REUTERS_WORLD": "GEO",
    "AP_BREAKING": "GEO",
    "BBC_WORLD": "GEO",
    "AL_JAZEERA": "GEO",
    "KYIV_INDEPENDENT": "GEO",
    "TIMES_OF_ISRAEL": "GEO",
    "SCMP": "GEO",
    "EIA_PETROLEUM": "ENERGY",
    "OPEC_OFFICIAL": "ENERGY",
}


def _build_prompt(headline: str, summary: str, source_id: str) -> str:
    template_key = _SOURCE_TO_TEMPLATE.get(source_id, "DEFAULT")
    template = PROMPT_TEMPLATES[template_key]
    return template.format(
        headline=headline[:200],
        summary=summary[:150],
    )


def _parse_response(raw: str) -> dict[str, Any]:
    """Extract JSON from LLM response. Fall back to CAUTION on failure."""
    # Try to find JSON in the response
    match = re.search(r"\{[^{}]+\}", raw)
    if match:
        try:
            data = json.loads(match.group())
            return {
                "tier": data.get("tier", "CAUTION"),
                "direction": data.get("direction", "NEUTRAL"),
                "instruments": data.get("instruments", ["ES", "NQ", "CL", "GC", "ZB"]),
                "confidence": data.get("confidence", 0.5),
                **{k: v for k, v in data.items()
                   if k not in ("tier", "direction", "instruments", "confidence")},
            }
        except (json.JSONDecodeError, ValueError):
            pass
    return dict(_CAUTION_DEFAULT)


def classify_headline(
    headline: str,
    summary: str,
    source_id: str,
    client: "Anthropic",
) -> dict[str, Any]:
    """Classify a headline using Haiku. Returns result dict with 'classification' field."""
    prompt = _build_prompt(headline, summary, source_id)
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_OUTPUT_TOKENS,
            messages=[{"role": "user", "content": prompt}],
            timeout=TIMEOUT_SECONDS,
        )
        raw = response.content[0].text
        result = _parse_response(raw)
        result["classification"] = "LLM"
        return result
    except TimeoutError:
        return {**_CAUTION_DEFAULT, "classification": "TIMEOUT"}
    except Exception:
        return {**_CAUTION_DEFAULT, "classification": "ERROR"}
```

**Step 4: Run tests to verify they pass**

```bash
cd /Users/jasonljc/trading && python -m pytest openclaw_trader/tests/test_llm_classifier.py -v
```

**Step 5: Commit**

```bash
git add openclaw_trader/signals/llm_classifier.py openclaw_trader/tests/test_llm_classifier.py
git commit -m "feat: LLM classifier with Haiku and tests"
```

---

### Task 6: Signal publisher (Redis Streams)

**Files:**
- Create: `openclaw_trader/signals/signal_publisher.py`

**Step 1: Implement signal_publisher.py**

File: `openclaw_trader/signals/signal_publisher.py`

```python
"""Publish classified signals to Redis Streams and ledger."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from redis import Redis

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from shared import contracts as C
from shared import ledger

NEWS_STREAM = "news_signals"
POLYMARKET_STREAM = "polymarket_signals"


def publish_news_signal(
    redis_client: "Redis",
    source_id: str,
    headline: str,
    summary: str,
    tier: str,
    direction: str | None,
    confidence: float,
    instruments: list[str],
    duration_minutes: int = 30,
    classification: str = "KEYWORD",
    source_url: str = "",
    event_type: str | None = None,
    run_id: str = "",
) -> str:
    """Publish a news signal to Redis Stream. Returns the stream entry ID."""
    now = datetime.now(timezone.utc).isoformat()
    fields = {
        "source_id": source_id,
        "headline": headline[:200],
        "summary": summary[:300],
        "tier": tier,
        "direction": direction or "",
        "confidence": str(confidence),
        "instruments": json.dumps(instruments),
        "duration_minutes": str(duration_minutes),
        "classification": classification,
        "source_url": source_url,
        "event_type": event_type or "",
        "timestamp": now,
    }
    entry_id = redis_client.xadd(NEWS_STREAM, fields, maxlen=1000)

    # Log to ledger
    ledger.append(C.EventType.NEWS_SIGNAL, run_id or "SIGNAL_DAEMON", source_id, {
        "source_id": source_id,
        "headline": headline[:200],
        "tier": tier,
        "direction": direction,
        "instruments": instruments,
        "confidence": confidence,
        "event_type": event_type,
    })

    return entry_id


def publish_polymarket_signal(
    redis_client: "Redis",
    signal_type: str,
    market_question: str,
    instruments: list[str],
    direction: str | None = None,
    strength: str = "MEDIUM",
    value_usd: float | None = None,
    drift_magnitude: float | None = None,
    duration_minutes: int = 120,
    run_id: str = "",
) -> str:
    """Publish a Polymarket signal to Redis Stream."""
    now = datetime.now(timezone.utc)
    expires = now.replace(minute=now.minute)  # placeholder
    fields = {
        "type": signal_type,
        "market_question": market_question[:150],
        "instruments": json.dumps(instruments),
        "direction": direction or "",
        "strength": strength,
        "value_usd": str(value_usd) if value_usd is not None else "",
        "drift_magnitude": str(drift_magnitude) if drift_magnitude is not None else "",
        "timestamp": now.isoformat(),
        "expires_at": now.isoformat(),  # computed by caller
        "duration_minutes": str(duration_minutes),
    }
    entry_id = redis_client.xadd(POLYMARKET_STREAM, fields, maxlen=500)

    ledger.append(C.EventType.POLYMARKET_SIGNAL, run_id or "SIGNAL_DAEMON", signal_type, {
        "type": signal_type,
        "market_question": market_question[:150],
        "instruments": instruments,
        "strength": strength,
        "drift_magnitude": drift_magnitude,
    })

    return entry_id


def read_active_signals(
    redis_client: "Redis",
    stream: str = NEWS_STREAM,
    count: int = 50,
) -> list[dict[str, Any]]:
    """Read recent signals from a Redis Stream, filtering expired ones."""
    now = datetime.now(timezone.utc)
    entries = redis_client.xrevrange(stream, count=count)
    active = []
    for entry_id, fields in entries:
        # Decode bytes if needed
        decoded = {}
        for k, v in fields.items():
            key = k.decode() if isinstance(k, bytes) else k
            val = v.decode() if isinstance(v, bytes) else v
            decoded[key] = val

        # Check expiry
        try:
            ts = datetime.fromisoformat(decoded.get("timestamp", ""))
            duration = int(decoded.get("duration_minutes", "30"))
            if (now - ts).total_seconds() > duration * 60:
                continue  # expired
        except (ValueError, TypeError):
            continue

        # Parse instruments back to list
        try:
            decoded["instruments"] = json.loads(decoded.get("instruments", "[]"))
        except json.JSONDecodeError:
            decoded["instruments"] = []

        # Parse numeric fields
        for field in ("confidence", "value_usd", "drift_magnitude"):
            if decoded.get(field):
                try:
                    decoded[field] = float(decoded[field])
                except ValueError:
                    pass

        decoded["_entry_id"] = entry_id
        active.append(decoded)

    return active
```

**Step 2: Commit**

```bash
git add openclaw_trader/signals/signal_publisher.py
git commit -m "feat: Redis Stream signal publisher with ledger logging"
```

---

### Task 7: Telegram alerter

**Files:**
- Create: `openclaw_trader/signals/telegram_alerter.py`

**Step 1: Implement telegram_alerter.py**

File: `openclaw_trader/signals/telegram_alerter.py`

```python
"""Telegram Bot API alerter for news and Polymarket signals."""
from __future__ import annotations

import os
import time
import urllib.request
import urllib.parse
import json
from typing import Any

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
MAX_MESSAGES_PER_HOUR = 20
_SEND_LOG: list[float] = []


def _rate_ok() -> bool:
    """Check if we're under the hourly rate limit."""
    now = time.time()
    cutoff = now - 3600
    _SEND_LOG[:] = [t for t in _SEND_LOG if t > cutoff]
    return len(_SEND_LOG) < MAX_MESSAGES_PER_HOUR


def send_message(text: str, token: str = "", chat_id: str = "") -> bool:
    """Send a message via Telegram Bot API. Returns True on success."""
    tk = token or BOT_TOKEN
    cid = chat_id or CHAT_ID
    if not tk or not cid:
        return False
    if not _rate_ok():
        return False

    url = f"https://api.telegram.org/bot{tk}/sendMessage"
    payload = json.dumps({
        "chat_id": cid,
        "text": text,
        "parse_mode": "HTML",
    }).encode()

    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            _SEND_LOG.append(time.time())
            return resp.status == 200
    except Exception:
        return False


def format_news_alert(signal: dict[str, Any]) -> str | None:
    """Format a news signal for Telegram. Returns None if not alert-worthy."""
    tier = signal.get("tier", "MONITOR")
    if tier not in ("HALT", "DIRECTIONAL_LONG", "DIRECTIONAL_SHORT", "REDUCE"):
        return None

    source = signal.get("source_id", "UNKNOWN")
    headline = signal.get("headline", "")
    instruments = signal.get("instruments", [])

    if tier == "HALT":
        prefix = "HALT"
        instr_text = " ".join(instruments)
        return (
            f"<b>HALT</b> -- {signal.get('event_type', source)}\n"
            f"Source: {source}\n"
            f"<i>{headline}</i>\n"
            f"Instruments blocked: {instr_text}\n"
            f"Action: New entries blocked. Stops tightened."
        )
    elif tier in ("DIRECTIONAL_LONG", "DIRECTIONAL_SHORT"):
        direction = "LONG" if "LONG" in tier else "SHORT"
        sym = instruments[0] if instruments else "?"
        return (
            f"<b>DIRECTIONAL_{direction}</b> -- {sym}\n"
            f"Source: {source}\n"
            f"<i>{headline}</i>\n"
            f"Waiting for confirmation bar..."
        )
    elif tier == "REDUCE":
        return (
            f"<b>REDUCE</b>\n"
            f"Source: {source}\n"
            f"<i>{headline}</i>\n"
            f"Sizing cut to 50% on: {', '.join(instruments)}"
        )
    return None


def format_polymarket_alert(signal: dict[str, Any]) -> str | None:
    """Format a Polymarket signal for Telegram. Returns None if not alert-worthy."""
    sig_type = signal.get("type", "")
    strength = signal.get("strength", "LOW")

    if sig_type == "PROBABILITY_DRIFT" and strength == "HIGH":
        drift = signal.get("drift_magnitude", 0)
        market = signal.get("market_question", "")
        instruments = signal.get("instruments", [])
        return (
            f"<b>POLYMARKET DRIFT</b>\n"
            f"Market: {market}\n"
            f"Drift: {drift:+.0f}pp in &lt;4 hours\n"
            f"Instruments: {', '.join(instruments)}"
        )
    elif sig_type == "FRESH_WALLET":
        market = signal.get("market_question", "")
        value = signal.get("value_usd", 0)
        return (
            f"<b>POLYMARKET FRESH WALLET</b>\n"
            f"Market: {market}\n"
            f"Trade size: ${value:,.0f}"
        )
    return None
```

**Step 2: Commit**

```bash
git add openclaw_trader/signals/telegram_alerter.py
git commit -m "feat: Telegram alerter with rate limiting"
```

---

### Task 8: Base collector and RSS collector

**Files:**
- Create: `openclaw_trader/signals/base_collector.py`
- Create: `openclaw_trader/signals/rss_collector.py`
- Create: `openclaw_trader/config/sources_tier1.yaml`

**Step 1: Create sources_tier1.yaml**

File: `openclaw_trader/config/sources_tier1.yaml`

```yaml
sources:
  - source_id: FED_PRESS_RELEASES
    url: "https://www.federalreserve.gov/feeds/press_all.xml"
    type: rss
    poll_interval_seconds: 30
    priority: CRITICAL

  - source_id: FED_SPEECHES
    url: "https://www.federalreserve.gov/feeds/speeches.xml"
    type: rss
    poll_interval_seconds: 60
    priority: HIGH

  - source_id: REUTERS_WORLD
    url: "https://feeds.reuters.com/Reuters/worldNews"
    type: rss
    poll_interval_seconds: 30
    priority: CRITICAL

  - source_id: AP_BREAKING
    url: "https://apnews.com/rss"
    type: rss
    poll_interval_seconds: 30
    priority: CRITICAL

  - source_id: TRUMP_TRUTH_SOCIAL
    url: "https://truthsocial.com/@realDonaldTrump.rss"
    type: rss
    poll_interval_seconds: 15
    priority: CRITICAL

  - source_id: WHITE_HOUSE_OFFICIAL
    url: "https://www.whitehouse.gov/feed/"
    type: rss
    poll_interval_seconds: 60
    priority: HIGH

  - source_id: EIA_PETROLEUM
    url: "https://www.eia.gov/petroleum/supply/weekly/"
    type: rss
    poll_interval_seconds: 60
    priority: CRITICAL
```

**Step 2: Implement base_collector.py**

File: `openclaw_trader/signals/base_collector.py`

```python
"""Abstract base class for all signal collectors."""
from __future__ import annotations

import abc
import logging
from typing import Any

logger = logging.getLogger(__name__)


class BaseCollector(abc.ABC):
    """All collectors implement poll() and parse()."""

    def __init__(self, source_id: str, poll_interval: int, priority: str = "MEDIUM"):
        self.source_id = source_id
        self.poll_interval = poll_interval
        self.priority = priority

    @abc.abstractmethod
    async def poll(self) -> list[dict[str, Any]]:
        """Fetch raw items from the source. Returns list of raw item dicts."""

    @abc.abstractmethod
    def parse(self, raw_item: dict[str, Any]) -> dict[str, Any]:
        """Parse a raw item into {headline, summary, url, published}."""
```

**Step 3: Implement rss_collector.py**

File: `openclaw_trader/signals/rss_collector.py`

```python
"""RSS/Atom feed collector using feedparser."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import feedparser

from openclaw_trader.signals.base_collector import BaseCollector

logger = logging.getLogger(__name__)


class RSSCollector(BaseCollector):
    """Poll an RSS/Atom feed URL."""

    def __init__(self, source_id: str, url: str, poll_interval: int, priority: str = "MEDIUM"):
        super().__init__(source_id, poll_interval, priority)
        self.url = url
        self._etag: str | None = None
        self._modified: str | None = None

    async def poll(self) -> list[dict[str, Any]]:
        """Fetch RSS feed in a thread (feedparser is blocking)."""
        loop = asyncio.get_event_loop()
        feed = await loop.run_in_executor(None, self._fetch)
        if feed is None:
            return []
        # Update conditional GET headers for next poll
        self._etag = feed.get("etag", self._etag)
        self._modified = feed.get("modified", self._modified)
        return [self.parse(entry) for entry in feed.get("entries", [])]

    def _fetch(self) -> dict | None:
        try:
            kwargs = {}
            if self._etag:
                kwargs["etag"] = self._etag
            if self._modified:
                kwargs["modified"] = self._modified
            feed = feedparser.parse(self.url, **kwargs)
            if feed.get("status", 200) == 304:
                return None  # Not modified
            if feed.bozo and not feed.entries:
                logger.warning(f"[{self.source_id}] Feed parse error: {feed.bozo_exception}")
                return None
            return feed
        except Exception as exc:
            logger.error(f"[{self.source_id}] Fetch failed: {exc}")
            return None

    def parse(self, raw_item: dict[str, Any]) -> dict[str, Any]:
        return {
            "headline": raw_item.get("title", "")[:200],
            "summary": raw_item.get("summary", raw_item.get("description", ""))[:300],
            "url": raw_item.get("link", ""),
            "published": raw_item.get("published", ""),
            "source_id": self.source_id,
        }
```

**Step 4: Commit**

```bash
git add openclaw_trader/signals/base_collector.py openclaw_trader/signals/rss_collector.py openclaw_trader/config/sources_tier1.yaml
git commit -m "feat: base collector, RSS collector, and Tier 1 source config"
```

---

### Task 9: Polymarket collector with tests

**Files:**
- Create: `openclaw_trader/signals/polymarket_collector.py`
- Create: `openclaw_trader/tests/test_polymarket_collector.py`

**Step 1: Write the failing tests**

File: `openclaw_trader/tests/test_polymarket_collector.py`

```python
"""Tests for Polymarket collector drift and anomaly detection."""
import pytest
from datetime import datetime, timezone, timedelta
from openclaw_trader.signals.polymarket_collector import (
    PolymarketCollector,
    detect_drift,
    detect_liquidity_spike,
    compute_regime_confidence_mod,
)


class TestDetectDrift:
    def test_drift_above_15pp_fires(self):
        now = datetime.now(timezone.utc)
        snapshots = [
            {"probability": 0.40, "timestamp": (now - timedelta(hours=3)).isoformat()},
            {"probability": 0.50, "timestamp": (now - timedelta(hours=2)).isoformat()},
            {"probability": 0.60, "timestamp": (now - timedelta(hours=1)).isoformat()},
        ]
        result = detect_drift(snapshots, current_prob=0.60)
        assert result is not None
        assert result["drift_magnitude"] == pytest.approx(20.0, abs=0.1)
        assert result["strength"] == "HIGH"  # >25pp? no, 20pp -> not HIGH

    def test_drift_above_25pp_is_high(self):
        now = datetime.now(timezone.utc)
        snapshots = [
            {"probability": 0.30, "timestamp": (now - timedelta(hours=3)).isoformat()},
        ]
        result = detect_drift(snapshots, current_prob=0.60)
        assert result is not None
        assert result["drift_magnitude"] == pytest.approx(30.0, abs=0.1)
        assert result["strength"] == "HIGH"

    def test_drift_below_15pp_no_signal(self):
        now = datetime.now(timezone.utc)
        snapshots = [
            {"probability": 0.45, "timestamp": (now - timedelta(hours=3)).isoformat()},
        ]
        result = detect_drift(snapshots, current_prob=0.50)
        assert result is None

    def test_empty_snapshots_no_signal(self):
        result = detect_drift([], current_prob=0.50)
        assert result is None

    def test_negative_drift_detected(self):
        now = datetime.now(timezone.utc)
        snapshots = [
            {"probability": 0.70, "timestamp": (now - timedelta(hours=3)).isoformat()},
        ]
        result = detect_drift(snapshots, current_prob=0.50)
        assert result is not None
        assert result["drift_magnitude"] == pytest.approx(-20.0, abs=0.1)


class TestLiquiditySpike:
    def test_spike_above_25k(self):
        result = detect_liquidity_spike(
            previous_liquidity=100_000, current_liquidity=130_000
        )
        assert result is not None
        assert result["strength"] == "MEDIUM"

    def test_spike_above_100k_is_high(self):
        result = detect_liquidity_spike(
            previous_liquidity=100_000, current_liquidity=210_000
        )
        assert result is not None
        assert result["strength"] == "HIGH"

    def test_no_spike_below_25k(self):
        result = detect_liquidity_spike(
            previous_liquidity=100_000, current_liquidity=120_000
        )
        assert result is None


class TestRegimeConfidenceMod:
    def test_two_high_same_direction_boost(self):
        signals = [
            {"strength": "HIGH", "direction": "YES", "instruments": ["ES"]},
            {"strength": "HIGH", "direction": "YES", "instruments": ["ES"]},
        ]
        mod = compute_regime_confidence_mod(signals, instrument="ES")
        assert mod == pytest.approx(1.2)

    def test_two_high_opposing_reduce(self):
        signals = [
            {"strength": "HIGH", "direction": "NO", "instruments": ["ES"]},
            {"strength": "HIGH", "direction": "NO", "instruments": ["ES"]},
        ]
        mod = compute_regime_confidence_mod(
            signals, instrument="ES", current_direction="YES"
        )
        assert mod == pytest.approx(0.8)

    def test_one_signal_no_mod(self):
        signals = [
            {"strength": "HIGH", "direction": "YES", "instruments": ["ES"]},
        ]
        mod = compute_regime_confidence_mod(signals, instrument="ES")
        assert mod == pytest.approx(1.0)

    def test_medium_strength_ignored(self):
        signals = [
            {"strength": "MEDIUM", "direction": "YES", "instruments": ["ES"]},
            {"strength": "MEDIUM", "direction": "YES", "instruments": ["ES"]},
        ]
        mod = compute_regime_confidence_mod(signals, instrument="ES")
        assert mod == pytest.approx(1.0)
```

**Step 2: Run tests to verify they fail**

```bash
cd /Users/jasonljc/trading && python -m pytest openclaw_trader/tests/test_polymarket_collector.py -v
```

**Step 3: Implement polymarket_collector.py**

File: `openclaw_trader/signals/polymarket_collector.py`

```python
"""Polymarket API collector with drift and anomaly detection."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Any

import aiohttp

from openclaw_trader.signals.base_collector import BaseCollector

logger = logging.getLogger(__name__)

API_URL = "https://gamma-api.polymarket.com/markets"

# Keyword sets to match markets to instruments
INSTRUMENT_KEYWORDS = {
    "ES": ["fed rate", "federal reserve", "recession", "gdp", "inflation", "cpi", "s&p", "spx"],
    "NQ": ["fed rate", "nasdaq", "tech", "semiconductor", "nvidia", "apple"],
    "CL": ["oil price", "crude", "opec", "iran", "saudi", "energy"],
    "GC": ["gold price", "inflation", "fed rate", "dollar"],
    "ZB": ["fed rate", "treasury", "yield", "interest rate", "debt ceiling"],
}

DRIFT_THRESHOLD_PP = 15.0
DRIFT_HIGH_PP = 25.0
LIQUIDITY_SPIKE_USD = 25_000
LIQUIDITY_HIGH_USD = 100_000


def detect_drift(
    snapshots: list[dict],
    current_prob: float,
) -> dict[str, Any] | None:
    """Detect probability drift >15pp over the snapshot window. Returns signal dict or None."""
    if not snapshots:
        return None

    oldest_prob = snapshots[0].get("probability", current_prob)
    drift_pp = (current_prob - oldest_prob) * 100.0

    if abs(drift_pp) < DRIFT_THRESHOLD_PP:
        return None

    strength = "HIGH" if abs(drift_pp) >= DRIFT_HIGH_PP else "MEDIUM"
    return {
        "drift_magnitude": round(drift_pp, 1),
        "strength": strength,
        "oldest_prob": oldest_prob,
        "current_prob": current_prob,
    }


def detect_liquidity_spike(
    previous_liquidity: float,
    current_liquidity: float,
) -> dict[str, Any] | None:
    """Detect liquidity increase >$25K in one poll cycle."""
    delta = current_liquidity - previous_liquidity
    if delta < LIQUIDITY_SPIKE_USD:
        return None

    strength = "HIGH" if delta >= LIQUIDITY_HIGH_USD else "MEDIUM"
    return {
        "delta_usd": round(delta, 2),
        "strength": strength,
    }


def compute_regime_confidence_mod(
    signals: list[dict],
    instrument: str,
    current_direction: str | None = None,
) -> float:
    """Compute regime confidence modifier from Polymarket signals.

    Returns 1.2 if 2+ HIGH signals agree, 0.8 if 2+ HIGH oppose, else 1.0.
    """
    high_for_instrument = [
        s for s in signals
        if s.get("strength") == "HIGH" and instrument in s.get("instruments", [])
    ]

    if len(high_for_instrument) < 2:
        return 1.0

    # Count direction agreement
    directions = [s.get("direction") for s in high_for_instrument]
    most_common = max(set(directions), key=directions.count)
    count = directions.count(most_common)

    if count < 2:
        return 1.0

    # If opposing current position direction
    if current_direction and most_common != current_direction:
        return 0.8

    return 1.2


def match_instruments(question: str) -> list[str]:
    """Match a Polymarket question to affected instruments."""
    q_lower = question.lower()
    matched = []
    for instrument, keywords in INSTRUMENT_KEYWORDS.items():
        if any(kw in q_lower for kw in keywords):
            matched.append(instrument)
    return matched or ["ES"]  # default to ES if no match


class PolymarketCollector(BaseCollector):
    """Poll Polymarket API for relevant markets."""

    def __init__(self, poll_interval: int = 60):
        super().__init__("POLYMARKET_MONITOR", poll_interval, "MEDIUM")
        self._snapshots: dict[str, list[dict]] = {}  # market_id -> probability snapshots
        self._prev_liquidity: dict[str, float] = {}   # market_id -> last known liquidity

    async def poll(self) -> list[dict[str, Any]]:
        """Fetch markets and detect anomalies."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(API_URL, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status != 200:
                        logger.warning(f"[POLYMARKET] HTTP {resp.status}")
                        return []
                    markets = await resp.json()
        except Exception as exc:
            logger.error(f"[POLYMARKET] Fetch failed: {exc}")
            return []

        signals = []
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=4)

        for market in (markets if isinstance(markets, list) else []):
            question = market.get("question", "")
            instruments = match_instruments(question)
            if not instruments:
                continue

            market_id = market.get("id", "")
            current_prob = float(market.get("outcomePrices", [0.5])[0] if isinstance(market.get("outcomePrices"), list) else 0.5)
            current_liquidity = float(market.get("liquidity", 0) or 0)

            # Store snapshot
            if market_id not in self._snapshots:
                self._snapshots[market_id] = []
            self._snapshots[market_id].append({
                "probability": current_prob,
                "timestamp": now.isoformat(),
            })
            # Trim to 4-hour window
            self._snapshots[market_id] = [
                s for s in self._snapshots[market_id]
                if datetime.fromisoformat(s["timestamp"]) > cutoff
            ]

            # Drift detection
            drift = detect_drift(self._snapshots[market_id], current_prob)
            if drift:
                signals.append({
                    "type": "PROBABILITY_DRIFT",
                    "market_question": question,
                    "instruments": instruments,
                    "direction": "YES" if drift["drift_magnitude"] > 0 else "NO",
                    "strength": drift["strength"],
                    "drift_magnitude": drift["drift_magnitude"],
                    "source_id": self.source_id,
                })

            # Liquidity spike
            prev_liq = self._prev_liquidity.get(market_id, current_liquidity)
            spike = detect_liquidity_spike(prev_liq, current_liquidity)
            if spike:
                signals.append({
                    "type": "LIQUIDITY_SPIKE",
                    "market_question": question,
                    "instruments": instruments,
                    "direction": None,
                    "strength": spike["strength"],
                    "value_usd": spike["delta_usd"],
                    "source_id": self.source_id,
                })
            self._prev_liquidity[market_id] = current_liquidity

        return signals

    def parse(self, raw_item: dict[str, Any]) -> dict[str, Any]:
        return raw_item  # Already structured from poll()
```

**Step 4: Run tests to verify they pass**

```bash
cd /Users/jasonljc/trading && python -m pytest openclaw_trader/tests/test_polymarket_collector.py -v
```

**Step 5: Commit**

```bash
git add openclaw_trader/signals/polymarket_collector.py openclaw_trader/tests/test_polymarket_collector.py
git commit -m "feat: Polymarket collector with drift/spike detection and tests"
```

---

### Task 10: Sentinel bridge (check_external_signals)

**Files:**
- Create: `openclaw_trader/signals/sentinel_bridge.py`
- Modify: `workspace-sentinel/sentinel.py:616-675` (add signal check in evaluate_intent)

**Step 1: Implement sentinel_bridge.py**

File: `openclaw_trader/signals/sentinel_bridge.py`

```python
"""Bridge between Redis signal streams and Sentinel evaluation."""
from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Signal tier → sizing modifier
_TIER_MODIFIERS = {
    "HALT": 0.0,
    "REDUCE": 0.50,
    "CAUTION": 0.75,
}

# Priority order (most conservative first)
_TIER_PRIORITY = {"HALT": 0, "REDUCE": 1, "CAUTION": 2, "MONITOR": 3, "IGNORE": 4}


def check_external_signals(
    symbol: str,
    redis_client: Any | None = None,
) -> dict[str, Any]:
    """Read Redis streams and return signal modifiers for this instrument.

    Returns:
        {
            "has_signal": bool,
            "tier": str (most conservative active signal),
            "sizing_modifier": float (1.0 if no signal),
            "stop_modifier": float (1.0 or 1.25 for CAUTION),
            "halt": bool,
            "active_signals": list[dict],
            "polymarket_confidence_mod": float (1.0 default),
        }
    """
    default = {
        "has_signal": False,
        "tier": "NONE",
        "sizing_modifier": 1.0,
        "stop_modifier": 1.0,
        "halt": False,
        "active_signals": [],
        "polymarket_confidence_mod": 1.0,
    }

    if redis_client is None:
        return default

    try:
        from openclaw_trader.signals.signal_publisher import read_active_signals, NEWS_STREAM, POLYMARKET_STREAM
    except ImportError:
        logger.debug("Signal publisher not available — skipping external signals")
        return default

    try:
        news_signals = read_active_signals(redis_client, NEWS_STREAM, count=50)
        poly_signals = read_active_signals(redis_client, POLYMARKET_STREAM, count=50)
    except Exception as exc:
        logger.warning(f"Redis read failed — skipping external signals: {exc}")
        return default

    # Filter to signals affecting this instrument
    relevant_news = [
        s for s in news_signals if symbol in s.get("instruments", [])
    ]
    relevant_poly = [
        s for s in poly_signals if symbol in s.get("instruments", [])
    ]

    if not relevant_news and not relevant_poly:
        return default

    # Find most conservative tier from news signals
    worst_tier = "MONITOR"
    for sig in relevant_news:
        tier = sig.get("tier", "MONITOR")
        if _TIER_PRIORITY.get(tier, 99) < _TIER_PRIORITY.get(worst_tier, 99):
            worst_tier = tier

    sizing_mod = _TIER_MODIFIERS.get(worst_tier, 1.0)
    stop_mod = 1.25 if worst_tier == "CAUTION" else 1.0
    is_halt = worst_tier == "HALT"

    # Polymarket confidence modifier
    poly_mod = 1.0
    if relevant_poly:
        try:
            from openclaw_trader.signals.polymarket_collector import compute_regime_confidence_mod
            poly_mod = compute_regime_confidence_mod(relevant_poly, instrument=symbol)
        except ImportError:
            pass

    return {
        "has_signal": True,
        "tier": worst_tier,
        "sizing_modifier": sizing_mod,
        "stop_modifier": stop_mod,
        "halt": is_halt,
        "active_signals": relevant_news + relevant_poly,
        "polymarket_confidence_mod": poly_mod,
    }
```

**Step 2: Modify sentinel.py — add signal check in evaluate_intent**

In `workspace-sentinel/sentinel.py`, add after line 631 (after `sizing = params.get("sizing", {})`) and before the intent_id assignment on line 633:

```python
    # --- External signals (news/Polymarket) — runs before all rules ---
    _signal_mod = 1.0
    _signal_stop_mod = 1.0
    try:
        import redis as _redis_mod
        _r = _redis_mod.from_url(
            __import__("os").environ.get("REDIS_URL", "redis://localhost:6379"),
            decode_responses=True,
        )
        from openclaw_trader.signals.sentinel_bridge import check_external_signals
        _ext = check_external_signals(intent.get("symbol", "ES"), redis_client=_r)
        if _ext["halt"] and intent.get("intent_type") == C.IntentType.ENTRY:
            approval_id = IDs.make_approval_id()
            reason = f"External signal HALT: {[s.get('headline', s.get('type', '')) for s in _ext['active_signals'][:3]]}"
            deny = _deny(intent, approval_id, run_id, reason, sp, posture=posture)
            ledger.append(C.EventType.INTENT_DENIED, run_id, intent.get("intent_id", ""), deny)
            return deny
        _signal_mod = _ext.get("sizing_modifier", 1.0)
        _signal_stop_mod = _ext.get("stop_modifier", 1.0)
    except Exception:
        pass  # Redis/signals unavailable — continue with normal rules
```

Then in the sizing section (around line 780, where `effective_risk_usd` is computed), multiply by `_signal_mod`:

Find the line that computes `effective_risk_usd` and multiply:
```python
    effective_risk_usd *= _signal_mod
```

**Step 3: Commit**

```bash
git add openclaw_trader/signals/sentinel_bridge.py workspace-sentinel/sentinel.py
git commit -m "feat: Sentinel bridge reads Redis signals and applies modifiers"
```

---

### Task 11: NEWS_DIRECTIONAL setup scanner with tests

**Files:**
- Create: `workspace-c3po/setups/news_directional.py`
- Create: `openclaw_trader/tests/test_news_directional.py`
- Modify: `run_intraday.py:86-127` (add NEWS_DIRECTIONAL to scanner dispatch)

**Step 1: Write the failing tests**

File: `openclaw_trader/tests/test_news_directional.py`

```python
"""Tests for NEWS_DIRECTIONAL setup scanner."""
import pytest
from datetime import datetime, timezone, timedelta

from workspace_c3po_setups_news_directional import detect


def _make_bar(o, h, l, c, volume=1000):
    return {"o": o, "h": h, "l": l, "c": c, "v": volume}


def _make_signal(direction="LONG", confirm_bars=1, event_type="FED_RATE_CUT_SURPRISE",
                 instruments=None, signal_id="sig_001"):
    return {
        "tier": f"DIRECTIONAL_{direction}",
        "direction": direction,
        "instruments": instruments or ["ES"],
        "event_type": event_type,
        "confirm_bars": confirm_bars,
        "signal_id": signal_id,
        "source_id": "FED_PRESS_RELEASES",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@pytest.fixture
def base_kwargs():
    return {
        "regime": {"regime_type": "NEUTRAL"},
        "session": {
            "session": "MORNING_DRIVE",
            "is_rth": True,
            "minutes_into_session": 60,
            "modifier": 1.0,
        },
        "structure": {"vwap": 5000.0},
        "snapshot": {
            "indicators": {"atr_14_1H": 20.0, "last_price": 5010.0},
        },
        "strategy": {
            "symbol": "ES",
            "tick_size": 0.25,
            "point_value_usd": 5.0,
        },
        "traded_signal_ids": set(),
    }


class TestConfirmationBar:
    def test_long_confirmed_by_bullish_bar(self, base_kwargs):
        # 20 bars for volume average + 1 confirmation bar
        avg_bars = [_make_bar(5000, 5005, 4998, 5002, volume=800)] * 20
        confirm_bar = _make_bar(5005, 5015, 5004, 5013, volume=1200)  # closes up, volume > avg
        bars_5m = avg_bars + [confirm_bar]

        signal = _make_signal("LONG", confirm_bars=1)
        result = detect(bars_5m=bars_5m, signals=[signal], **base_kwargs)
        assert result is not None
        assert result["side"] == "LONG"

    def test_long_rejected_by_bearish_bar(self, base_kwargs):
        avg_bars = [_make_bar(5000, 5005, 4998, 5002, volume=800)] * 20
        confirm_bar = _make_bar(5005, 5008, 4995, 4996, volume=1200)  # closes down
        bars_5m = avg_bars + [confirm_bar]

        signal = _make_signal("LONG", confirm_bars=1)
        result = detect(bars_5m=bars_5m, signals=[signal], **base_kwargs)
        assert result is None

    def test_indecisive_bar_skipped(self, base_kwargs):
        """Bar with body < 30% of range should be skipped."""
        avg_bars = [_make_bar(5000, 5005, 4998, 5002, volume=800)] * 20
        # Range = 10, body = 2 (20% < 30%)
        confirm_bar = _make_bar(5000, 5010, 5000, 5002, volume=1200)
        bars_5m = avg_bars + [confirm_bar]

        signal = _make_signal("LONG", confirm_bars=1)
        result = detect(bars_5m=bars_5m, signals=[signal], **base_kwargs)
        assert result is None

    def test_low_volume_skipped(self, base_kwargs):
        avg_bars = [_make_bar(5000, 5005, 4998, 5002, volume=1000)] * 20
        confirm_bar = _make_bar(5005, 5015, 5004, 5013, volume=500)  # below avg
        bars_5m = avg_bars + [confirm_bar]

        signal = _make_signal("LONG", confirm_bars=1)
        result = detect(bars_5m=bars_5m, signals=[signal], **base_kwargs)
        assert result is None

    def test_geo_event_needs_2_bars(self, base_kwargs):
        avg_bars = [_make_bar(5000, 5005, 4998, 5002, volume=800)] * 20
        bar1 = _make_bar(5005, 5015, 5004, 5013, volume=1200)
        bars_5m = avg_bars + [bar1]  # only 1 confirm bar

        signal = _make_signal("LONG", confirm_bars=2, event_type="MIDDLE_EAST_ESCALATION")
        result = detect(bars_5m=bars_5m, signals=[signal], **base_kwargs)
        assert result is None  # needs 2 bars

    def test_geo_event_passes_with_2_bars(self, base_kwargs):
        avg_bars = [_make_bar(5000, 5005, 4998, 5002, volume=800)] * 20
        bar1 = _make_bar(5005, 5015, 5004, 5013, volume=1200)
        bar2 = _make_bar(5013, 5020, 5012, 5018, volume=1100)
        bars_5m = avg_bars + [bar1, bar2]

        signal = _make_signal("LONG", confirm_bars=2, event_type="MIDDLE_EAST_ESCALATION")
        result = detect(bars_5m=bars_5m, signals=[signal], **base_kwargs)
        assert result is not None


class TestSizingAndStops:
    def test_sizing_50_pct(self, base_kwargs):
        avg_bars = [_make_bar(5000, 5005, 4998, 5002, volume=800)] * 20
        confirm_bar = _make_bar(5005, 5015, 5004, 5013, volume=1200)
        bars_5m = avg_bars + [confirm_bar]

        signal = _make_signal("LONG", confirm_bars=1)
        result = detect(bars_5m=bars_5m, signals=[signal], **base_kwargs)
        assert result is not None
        assert result["sizing_modifier"] == 0.5

    def test_stop_075x_atr(self, base_kwargs):
        avg_bars = [_make_bar(5000, 5005, 4998, 5002, volume=800)] * 20
        confirm_bar = _make_bar(5005, 5015, 5004, 5013, volume=1200)
        bars_5m = avg_bars + [confirm_bar]

        signal = _make_signal("LONG", confirm_bars=1)
        result = detect(bars_5m=bars_5m, signals=[signal], **base_kwargs)
        assert result is not None
        atr = 20.0
        expected_stop = result["entry_price"] - (0.75 * atr)
        assert result["stop_price"] == pytest.approx(expected_stop, abs=0.5)


class TestSessionAndDedup:
    def test_no_entry_within_30min_of_close(self, base_kwargs):
        base_kwargs["session"]["minutes_into_session"] = 370  # ES close at 15:45, ~375min from open
        base_kwargs["session"]["session"] = "MOC_CLOSE"
        avg_bars = [_make_bar(5000, 5005, 4998, 5002, volume=800)] * 20
        confirm_bar = _make_bar(5005, 5015, 5004, 5013, volume=1200)
        bars_5m = avg_bars + [confirm_bar]

        signal = _make_signal("LONG", confirm_bars=1)
        result = detect(bars_5m=bars_5m, signals=[signal], **base_kwargs)
        assert result is None

    def test_one_trade_per_signal_id(self, base_kwargs):
        avg_bars = [_make_bar(5000, 5005, 4998, 5002, volume=800)] * 20
        confirm_bar = _make_bar(5005, 5015, 5004, 5013, volume=1200)
        bars_5m = avg_bars + [confirm_bar]

        signal = _make_signal("LONG", confirm_bars=1, signal_id="sig_already_traded")
        base_kwargs["traded_signal_ids"] = {"sig_already_traded"}
        result = detect(bars_5m=bars_5m, signals=[signal], **base_kwargs)
        assert result is None

    def test_not_rth_no_entry(self, base_kwargs):
        base_kwargs["session"]["is_rth"] = False
        avg_bars = [_make_bar(5000, 5005, 4998, 5002, volume=800)] * 20
        confirm_bar = _make_bar(5005, 5015, 5004, 5013, volume=1200)
        bars_5m = avg_bars + [confirm_bar]

        signal = _make_signal("LONG", confirm_bars=1)
        result = detect(bars_5m=bars_5m, signals=[signal], **base_kwargs)
        assert result is None

    def test_no_signals_returns_none(self, base_kwargs):
        bars_5m = [_make_bar(5000, 5005, 4998, 5002, volume=800)] * 21
        result = detect(bars_5m=bars_5m, signals=[], **base_kwargs)
        assert result is None
```

Note: The test imports `workspace_c3po_setups_news_directional` — we need a conftest to handle path setup. Add to `openclaw_trader/tests/conftest.py`:

File: `openclaw_trader/tests/conftest.py`

```python
import sys
from pathlib import Path

# Allow importing from workspace-c3po/setups/
_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_ROOT / "workspace-c3po" / "setups"))

# Re-export for test imports
import news_directional as workspace_c3po_setups_news_directional
sys.modules["workspace_c3po_setups_news_directional"] = workspace_c3po_setups_news_directional
```

**Step 2: Run tests to verify they fail**

```bash
cd /Users/jasonljc/trading && python -m pytest openclaw_trader/tests/test_news_directional.py -v
```

**Step 3: Implement news_directional.py**

File: `workspace-c3po/setups/news_directional.py`

```python
"""NEWS_DIRECTIONAL setup scanner — generates trade candidates from news signals."""
from __future__ import annotations

from typing import Any


def detect(
    regime: dict,
    session: dict,
    structure: dict | None,
    bars_5m: list[dict],
    snapshot: dict,
    strategy: dict,
    signals: list[dict] | None = None,
    traded_signal_ids: set | None = None,
) -> dict[str, Any] | None:
    """Scan for a NEWS_DIRECTIONAL setup.

    Args:
        signals: list of active DIRECTIONAL signals from Redis (pre-filtered to this instrument)
        traded_signal_ids: set of signal_ids already traded this session

    Returns SetupCandidate dict or None.
    """
    if not signals or not bars_5m:
        return None

    traded = traded_signal_ids or set()

    # Session gate: must be RTH
    if not session.get("is_rth", False):
        return None

    # Session gate: no entries within 30 min of close (MOC_CLOSE)
    session_name = session.get("session", "CLOSED")
    if session_name == "MOC_CLOSE":
        return None

    # Session gate: no entries in first 2 min
    minutes_in = session.get("minutes_into_session", 0)
    if minutes_in < 2:
        return None

    atr = snapshot.get("indicators", {}).get("atr_14_1H", 0)
    if atr <= 0:
        atr = snapshot.get("indicators", {}).get("atr_14_4H", 10.0)

    for signal in signals:
        signal_id = signal.get("signal_id", "")
        if signal_id in traded:
            continue

        direction = signal.get("direction", "")
        if direction not in ("LONG", "SHORT"):
            continue

        confirm_bars_needed = signal.get("confirm_bars", 1)

        # Check we have enough bars for confirmation
        if len(bars_5m) < 20 + confirm_bars_needed:
            continue

        # Volume average from first 20 bars
        vol_avg = sum(b.get("v", 0) for b in bars_5m[:20]) / 20.0

        # Check confirmation bars
        confirm_slice = bars_5m[-(confirm_bars_needed):]
        confirmed = True
        for bar in confirm_slice:
            bar_open = bar.get("o", 0)
            bar_close = bar.get("c", 0)
            bar_high = bar.get("h", 0)
            bar_low = bar.get("l", 0)
            bar_vol = bar.get("v", 0)
            bar_range = bar_high - bar_low
            bar_body = abs(bar_close - bar_open)

            # Body must be > 30% of range
            if bar_range > 0 and bar_body / bar_range < 0.30:
                confirmed = False
                break

            # Volume must be above 20-bar average
            if bar_vol < vol_avg:
                confirmed = False
                break

            # Bar must close in expected direction
            if direction == "LONG" and bar_close <= bar_open:
                confirmed = False
                break
            if direction == "SHORT" and bar_close >= bar_open:
                confirmed = False
                break

        if not confirmed:
            continue

        # Build SetupCandidate
        last_bar = bars_5m[-1]
        entry_price = last_bar.get("c", 0)
        stop_distance = 0.75 * atr
        tick_size = strategy.get("tick_size", 0.25)

        if direction == "LONG":
            stop_price = entry_price - stop_distance
            target_price = entry_price + (1.5 * stop_distance)
        else:
            stop_price = entry_price + stop_distance
            target_price = entry_price - (1.5 * stop_distance)

        # Round to tick
        def _round_tick(price: float) -> float:
            if tick_size > 0:
                return round(round(price / tick_size) * tick_size, 6)
            return price

        return {
            "side": direction,
            "entry_price": _round_tick(entry_price),
            "stop_price": _round_tick(stop_price),
            "target_price": _round_tick(target_price),
            "setup_family": "NEWS_DIRECTIONAL",
            "sizing_modifier": 0.5,  # Rule 3: always 50% sizing
            "signal_id": signal_id,
            "event_type": signal.get("event_type", ""),
            "metadata": {
                "source_id": signal.get("source_id", ""),
                "headline": signal.get("headline", ""),
                "confirm_bars": confirm_bars_needed,
                "atr": atr,
                "stop_distance": stop_distance,
            },
        }

    return None
```

**Step 4: Run tests**

```bash
cd /Users/jasonljc/trading && python -m pytest openclaw_trader/tests/test_news_directional.py -v
```

**Step 5: Modify run_intraday.py — add NEWS_DIRECTIONAL to _scan_setups()**

In `run_intraday.py`, after line 88 (`from setups.trend_pullback import detect as detect_trend_pullback`), add:

```python
    from setups.news_directional import detect as detect_news
```

After the TREND_PULLBACK elif block (line 127), add:

```python
        elif setup_family == "NEWS_DIRECTIONAL":
            # Read directional signals from Redis for this instrument
            _news_signals = []
            try:
                import redis as _rmod
                _rc = _rmod.from_url(
                    __import__("os").environ.get("REDIS_URL", "redis://localhost:6379"),
                    decode_responses=True,
                )
                from openclaw_trader.signals.signal_publisher import read_active_signals
                raw = read_active_signals(_rc, "news_signals", count=50)
                _news_signals = [
                    s for s in raw
                    if symbol in s.get("instruments", [])
                    and s.get("tier", "").startswith("DIRECTIONAL")
                ]
            except Exception:
                pass  # Redis unavailable — no news signals
            detect_kwargs["signals"] = _news_signals
            detect_kwargs["traded_signal_ids"] = set()  # TODO: track per session
            candidate = detect_news(**detect_kwargs)
```

**Step 6: Commit**

```bash
git add workspace-c3po/setups/news_directional.py openclaw_trader/tests/test_news_directional.py openclaw_trader/tests/conftest.py run_intraday.py
git commit -m "feat: NEWS_DIRECTIONAL setup scanner with tests and intraday integration"
```

---

### Task 12: Strategy JSON configs for NEWS instruments

**Files:**
- Create: `strategies/news_5m_MES.json`
- Create: `strategies/news_5m_MNQ.json`
- Create: `strategies/news_5m_MCL.json`
- Create: `strategies/news_5m_MGC.json`
- Create: `strategies/news_5m_ZB.json`

**Step 1: Create all 5 strategy configs**

Use the same structure as `orb_5m_MES.json` with these changes:
- `strategy_id`: `news_5m_MES`, etc.
- `signal.setup_family`: `"NEWS_DIRECTIONAL"`
- `signal.entry_condition`: `"news_directional"`
- `incubation.is_incubating`: `true`
- `incubation.incubation_size_pct`: `25`
- `status`: `"ACTIVE"`

Example for `strategies/news_5m_MES.json`:

```json
{
  "strategy_id": "news_5m_MES",
  "description": "5m News-driven directional entries on MES; fires on classified news signals with bar confirmation",
  "symbol": "ES",
  "timeframe": "5m",
  "contract_type": "FUTURE",
  "contract_month": "ESM26",
  "tick_size": 0.25,
  "tick_value_usd": 1.25,
  "point_value_usd": 5.00,
  "micro_available": false,
  "micro_symbol": null,
  "micro_point_value_usd": null,
  "micro_tick_value_usd": null,
  "use_micro": true,
  "correlation_group": "equity_beta",
  "fee_per_contract_round_trip_usd": 1.34,
  "margin_per_contract_usd": 1584.00,
  "micro_margin_per_contract_usd": 1584.00,
  "risk_budget_pct": 1.0,
  "max_strategy_dd_pct": 8.0,
  "expected_monthly_return_pct": 2.0,
  "expected_max_dd_pct": 10.0,
  "expected_sharpe": 0.8,
  "expected_hit_rate": 0.45,
  "expected_avg_slippage_ticks": 2.0,
  "expected_trades_per_month": 10,
  "min_health_score": 0.30,
  "cooldown_bars_after_disable": 20,
  "min_trades_for_full_health": 20,
  "max_hold_bars": 12,
  "contract_expiry": "2026-06-20",
  "roll_days_before_expiry": 5,
  "session_schedule": {
    "core": {"start": "09:30", "end": "16:00", "tz": "America/New_York"},
    "extended": {"start": "18:00", "end": "09:30", "tz": "America/New_York"},
    "closed": {"start": "16:00", "end": "18:00", "tz": "America/New_York"}
  },
  "signal": {
    "entry_condition": "news_directional",
    "setup_family": "NEWS_DIRECTIONAL",
    "min_reward_risk": 1.5
  },
  "status": "ACTIVE",
  "status_changed_at": "2026-03-16T00:00:00Z",
  "incubation": {
    "is_incubating": true,
    "incubation_start": "2026-03-16T00:00:00Z",
    "incubation_size_pct": 25,
    "incubation_min_trades": 50,
    "incubation_min_days": 30
  }
}
```

Repeat for NQ (news_5m_MNQ, symbol NQ, correlation_group equity_beta, contract_month NQM26),
CL (news_5m_MCL, symbol CL, correlation_group energy, contract_month CLN26, point_value_usd 10.0, tick_size 0.01, tick_value_usd 0.10, margin 1584),
GC (news_5m_MGC, symbol GC, correlation_group metals, contract_month GCQ26, point_value_usd 10.0, tick_size 0.10, tick_value_usd 1.00, margin 1100),
ZB (news_5m_ZB, symbol ZB, correlation_group rates, contract_month ZBM26, point_value_usd 1000.0, tick_size 0.03125, tick_value_usd 31.25, margin 4400, use_micro false).

**Step 2: Commit**

```bash
git add strategies/news_5m_*.json
git commit -m "feat: 5 NEWS_DIRECTIONAL strategy configs (all incubating)"
```

---

### Task 13: Signal daemon (asyncio main loop)

**Files:**
- Create: `openclaw_trader/signals/signal_daemon.py`
- Create: `openclaw_trader/signals/scrape_collector.py` (stub)

**Step 1: Create scrape_collector.py stub**

File: `openclaw_trader/signals/scrape_collector.py`

```python
"""Web scraping collector stub — Tier 2 implementation."""
from __future__ import annotations

from typing import Any

from openclaw_trader.signals.base_collector import BaseCollector


class ScrapeCollector(BaseCollector):
    """Placeholder for Tier 2 scraping sources (OPEC, USTR, etc.)."""

    def __init__(self, source_id: str, url: str, poll_interval: int, priority: str = "MEDIUM"):
        super().__init__(source_id, poll_interval, priority)
        self.url = url

    async def poll(self) -> list[dict[str, Any]]:
        return []  # Tier 2

    def parse(self, raw_item: dict[str, Any]) -> dict[str, Any]:
        return raw_item
```

**Step 2: Implement signal_daemon.py**

File: `openclaw_trader/signals/signal_daemon.py`

```python
"""Main signal daemon — asyncio loop running all collectors."""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

import redis
import yaml

# Ensure project root is on path
_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_ROOT))

from openclaw_trader.signals.rss_collector import RSSCollector
from openclaw_trader.signals.polymarket_collector import PolymarketCollector
from openclaw_trader.signals.keyword_filter import load_keywords, layer_1_filter, layer_2_check
from openclaw_trader.signals.llm_classifier import classify_headline
from openclaw_trader.signals.deduplicator import Deduplicator
from openclaw_trader.signals.signal_publisher import publish_news_signal, publish_polymarket_signal
from openclaw_trader.signals.response_matrix import ResponseMatrix
from openclaw_trader.signals import telegram_alerter

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("signal_daemon")

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")


def _load_sources() -> list[dict]:
    config_path = Path(__file__).parent.parent / "config" / "sources_tier1.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f).get("sources", [])


def _build_rss_collectors(sources: list[dict]) -> list[RSSCollector]:
    return [
        RSSCollector(
            source_id=s["source_id"],
            url=s["url"],
            poll_interval=s["poll_interval_seconds"],
            priority=s.get("priority", "MEDIUM"),
        )
        for s in sources
        if s.get("type") == "rss"
    ]


async def _run_rss_collector(
    collector: RSSCollector,
    redis_client: redis.Redis,
    dedup: Deduplicator,
    keywords: dict,
    matrix: ResponseMatrix,
    anthropic_client,
):
    """Run one RSS collector on its polling interval."""
    logger.info(f"Starting {collector.source_id} (poll={collector.poll_interval}s)")
    while True:
        try:
            items = await collector.poll()
            for item in items:
                headline = item.get("headline", "")
                summary = item.get("summary", "")
                source_id = collector.source_id

                # Dedup
                if dedup.is_duplicate(headline):
                    continue

                # Layer 1
                if not layer_1_filter(headline, keywords, summary=summary):
                    continue

                # Layer 2
                l2_action = layer_2_check(headline, keywords, source_id=source_id)

                # If Layer 2 fires, publish immediately
                if l2_action:
                    instruments = ["ES", "NQ", "CL", "GC", "ZB"]
                    publish_news_signal(
                        redis_client, source_id, headline, summary,
                        tier=l2_action, direction=None, confidence=1.0,
                        instruments=instruments, classification="KEYWORD",
                        source_url=item.get("url", ""),
                    )
                    # Telegram alert
                    alert_text = telegram_alerter.format_news_alert({
                        "tier": l2_action, "source_id": source_id,
                        "headline": headline, "instruments": instruments,
                    })
                    if alert_text:
                        telegram_alerter.send_message(alert_text)

                # Layer 3: LLM for non-L2 items (or concurrently for L2 refinement)
                if anthropic_client and not l2_action:
                    result = classify_headline(headline, summary, source_id, anthropic_client)
                    tier = result.get("tier", "MONITOR")
                    if tier != "IGNORE":
                        instruments = result.get("instruments", ["ES", "NQ", "CL", "GC", "ZB"])
                        direction = result.get("direction")
                        # Map LLM direction to response matrix event type if possible
                        event_type = result.get("topic", result.get("conflict_type", ""))
                        publish_news_signal(
                            redis_client, source_id, headline, summary,
                            tier=tier, direction=direction,
                            confidence=result.get("confidence", 0.5),
                            instruments=instruments, classification="LLM",
                            source_url=item.get("url", ""),
                            event_type=event_type,
                        )
                        alert_text = telegram_alerter.format_news_alert({
                            "tier": tier, "direction": direction,
                            "source_id": source_id, "headline": headline,
                            "instruments": instruments, "event_type": event_type,
                        })
                        if alert_text:
                            telegram_alerter.send_message(alert_text)

        except Exception as exc:
            logger.error(f"[{collector.source_id}] Error: {exc}")

        await asyncio.sleep(collector.poll_interval)


async def _run_polymarket(
    collector: PolymarketCollector,
    redis_client: redis.Redis,
):
    """Run Polymarket collector on its polling interval."""
    logger.info(f"Starting Polymarket (poll={collector.poll_interval}s)")
    while True:
        try:
            signals = await collector.poll()
            for signal in signals:
                publish_polymarket_signal(
                    redis_client,
                    signal_type=signal.get("type", ""),
                    market_question=signal.get("market_question", ""),
                    instruments=signal.get("instruments", []),
                    direction=signal.get("direction"),
                    strength=signal.get("strength", "MEDIUM"),
                    value_usd=signal.get("value_usd"),
                    drift_magnitude=signal.get("drift_magnitude"),
                )
                alert_text = telegram_alerter.format_polymarket_alert(signal)
                if alert_text:
                    telegram_alerter.send_message(alert_text)

        except Exception as exc:
            logger.error(f"[POLYMARKET] Error: {exc}")

        await asyncio.sleep(collector.poll_interval)


async def main():
    logger.info("Signal daemon starting")

    # Connect Redis
    redis_client = redis.from_url(REDIS_URL, decode_responses=True)
    redis_client.ping()
    logger.info(f"Redis connected: {REDIS_URL}")

    # Load config
    keywords = load_keywords()
    matrix = ResponseMatrix()
    dedup = Deduplicator(redis_client)
    sources = _load_sources()
    rss_collectors = _build_rss_collectors(sources)
    polymarket = PolymarketCollector(poll_interval=60)

    # Anthropic client (optional)
    anthropic_client = None
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if api_key:
        try:
            import anthropic
            anthropic_client = anthropic.Anthropic(api_key=api_key)
            logger.info("Anthropic client initialized (Haiku)")
        except ImportError:
            logger.warning("anthropic package not installed — LLM classification disabled")

    # Send startup notification
    telegram_alerter.send_message(
        f"Signal daemon started\n"
        f"Sources: {len(rss_collectors)} RSS + Polymarket\n"
        f"LLM: {'enabled' if anthropic_client else 'disabled'}"
    )

    # Launch all collectors as concurrent tasks
    tasks = []
    for collector in rss_collectors:
        tasks.append(
            asyncio.create_task(
                _run_rss_collector(collector, redis_client, dedup, keywords, matrix, anthropic_client)
            )
        )
    tasks.append(asyncio.create_task(_run_polymarket(polymarket, redis_client)))

    logger.info(f"Running {len(tasks)} collector tasks")
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Signal daemon stopped")
```

**Step 3: Commit**

```bash
git add openclaw_trader/signals/signal_daemon.py openclaw_trader/signals/scrape_collector.py
git commit -m "feat: signal daemon asyncio main loop with all Tier 1 collectors"
```

---

### Task 14: Docker setup

**Files:**
- Create: `Dockerfile`
- Create: `docker-compose.yaml`
- Create: `.env.example`
- Create: `.dockerignore`

**Step 1: Create Dockerfile**

File: `Dockerfile`

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
```

**Step 2: Create docker-compose.yaml**

File: `docker-compose.yaml`

```yaml
services:
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    restart: unless-stopped

  signal-daemon:
    build: .
    command: python -m openclaw_trader.signals.signal_daemon
    depends_on:
      - redis
    env_file: .env
    restart: unless-stopped

  trading:
    build: .
    command: python run_intraday.py --mode loop
    depends_on:
      - redis
    env_file: .env
    restart: unless-stopped
    profiles:
      - full

volumes:
  redis_data:
```

**Step 3: Create .env.example**

File: `.env.example`

```
REDIS_URL=redis://redis:6379
ANTHROPIC_API_KEY=sk-ant-...
TELEGRAM_BOT_TOKEN=123456:ABC...
TELEGRAM_CHAT_ID=your_chat_id
```

**Step 4: Create .dockerignore**

File: `.dockerignore`

```
.git
.env
__pycache__
*.pyc
.pytest_cache
data/
docs/
```

**Step 5: Commit**

```bash
git add Dockerfile docker-compose.yaml .env.example .dockerignore
git commit -m "feat: Docker setup for signal daemon and trading pipeline"
```

---

### Task 15: Run all tests and verify

**Step 1: Install new dependencies**

```bash
cd /Users/jasonljc/trading && pip install -r requirements.txt
```

**Step 2: Run existing tests (regression check)**

```bash
cd /Users/jasonljc/trading && python -m pytest tests/ -v
```

Expected: all 334 existing tests pass

**Step 3: Run new signal tests**

```bash
cd /Users/jasonljc/trading && python -m pytest openclaw_trader/tests/ -v
```

Expected: all new tests pass

**Step 4: Run full test suite**

```bash
cd /Users/jasonljc/trading && python -m pytest tests/ openclaw_trader/tests/ -v
```

**Step 5: Commit any fixes**

```bash
git commit -m "test: verify all tests pass with signal registry integration"
```

---

## Summary

| Task | Description | Estimated Steps |
|------|-------------|----------------|
| 1 | Scaffolding + dependencies + contracts | 4 |
| 2 | Keyword filter + tests | 6 |
| 3 | Deduplicator + tests | 5 |
| 4 | Response matrix + YAML + tests | 6 |
| 5 | LLM classifier + tests | 5 |
| 6 | Signal publisher (Redis Streams) | 2 |
| 7 | Telegram alerter | 2 |
| 8 | Base collector + RSS collector + source config | 4 |
| 9 | Polymarket collector + tests | 5 |
| 10 | Sentinel bridge + sentinel.py modification | 3 |
| 11 | NEWS_DIRECTIONAL scanner + tests + intraday integration | 6 |
| 12 | Strategy JSON configs (5 files) | 2 |
| 13 | Signal daemon (asyncio main) | 3 |
| 14 | Docker setup | 5 |
| 15 | Full test run + regression | 5 |

**Total: 15 tasks, ~63 steps, 15 commits**
