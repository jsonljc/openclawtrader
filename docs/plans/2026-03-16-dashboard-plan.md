# Trading Dashboard Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a mobile-friendly React web dashboard and Telegram bot to monitor the OpenClaw trading system in real-time and review historical performance.

**Architecture:** FastAPI backend reads existing data files (portfolio.json, ledger.jsonl, posture_state.json, alerts.log, strategies/*.json) and Redis streams — pure read-only, no new database. React SPA frontend with TradingView Lightweight Charts + Recharts. Telegram bot runs as background task in the FastAPI process. Two Docker containers (api + ui) added via separate docker-compose file.

**Tech Stack:** Python (FastAPI, uvicorn, python-telegram-bot, redis), TypeScript/React 18, Vite, TailwindCSS, TradingView Lightweight Charts, Recharts, axios, nginx, Docker

---

## Context

**Existing data sources the dashboard reads (never writes):**
- `data/portfolio.json` — equity, PnL, positions, heat, posture (loaded via `shared/state_store.py:load_portfolio()`)
- `data/posture_state.json` — posture, streak, recovery state (loaded via `shared/state_store.py:load_state("posture_state")`)
- `data/ledger.jsonl` — append-only JSONL with SHA-256 chain, 30+ event types (queried via `shared/ledger.py:query()`)
- `data/alerts.log` — JSONL with `ts`, `level`, `message` fields
- `data/slippage_tracker.json` — micro/full fill stats
- `data/intraday_regime.json` — per-instrument regime state
- `strategies/*.json` — 25 strategy configs
- Redis streams: `news_signals` (maxlen=1000), `polymarket_signals` (maxlen=500)

**Key APIs to reuse:**
- `shared/state_store.load_portfolio()` → dict with account, pnl, positions, heat, sentinel_posture
- `shared/state_store.load_state(name)` → arbitrary state dict
- `shared/state_store.load_strategy_registry()` → {strategy_id: config}
- `shared/ledger.query(event_types=, limit=)` → list of ledger entries
- `openclaw_trader/signals/signal_publisher.read_active_signals(redis_client, stream, count)` → list of signal dicts

---

### Task 1: Backend scaffolding and data readers

**Files:**
- Create: `dashboard/api/main.py`
- Create: `dashboard/api/data_readers.py`
- Create: `dashboard/api/requirements.txt`
- Create: `dashboard/api/__init__.py`
- Create: `dashboard/api/routers/__init__.py`
- Test: `dashboard/api/tests/test_data_readers.py`

**Step 1: Create directory structure**

```bash
mkdir -p dashboard/api/routers dashboard/api/tests
touch dashboard/api/__init__.py dashboard/api/routers/__init__.py dashboard/api/tests/__init__.py
```

**Step 2: Write `dashboard/api/requirements.txt`**

```
fastapi>=0.110
uvicorn>=0.29
python-telegram-bot>=21.0
redis>=5.0
```

**Step 3: Write tests for data_readers**

```python
# dashboard/api/tests/test_data_readers.py
"""Tests for data_readers — shared read logic for dashboard."""
import json
import os
import pytest
from pathlib import Path
from unittest.mock import patch


@pytest.fixture
def data_dir(tmp_path):
    """Set up a temporary data directory with fixture files."""
    os.environ["OPENCLAW_DATA"] = str(tmp_path)
    os.environ["OPENCLAW_STRATEGIES"] = str(tmp_path / "strategies")
    (tmp_path / "strategies").mkdir()

    # Portfolio
    portfolio = {
        "asof": "2026-03-16T12:00:00Z",
        "param_version": "PV_0001",
        "account": {
            "equity_usd": 101250.0,
            "opening_equity_usd": 100000.0,
            "peak_equity_usd": 102000.0,
            "cash_usd": 95000.0,
            "margin_used_usd": 6250.0,
            "margin_available_usd": 95000.0,
            "margin_utilization_pct": 6.17,
        },
        "pnl": {
            "unrealized_usd": 430.0,
            "realized_today_usd": 820.0,
            "total_today_usd": 1250.0,
            "total_today_pct": 1.25,
            "portfolio_dd_pct": 0.73,
            "portfolio_dd_peak_date": "2026-03-14",
        },
        "positions": [
            {
                "position_id": "POS_001",
                "symbol": "ES",
                "side": "LONG",
                "contracts": 1,
                "entry_price": 5420.0,
                "current_price": 5445.0,
                "stop_price": 5400.0,
                "target_price": 5480.0,
                "unrealized_pnl_usd": 125.0,
                "strategy_id": "orb_5m_MES",
                "opened_at": "2026-03-16T10:15:00Z",
            }
        ],
        "heat": {
            "total_open_risk_usd": 500.0,
            "total_open_risk_pct": 0.49,
            "cluster_exposure": {"equity_beta": 1},
            "correlations_20d": {},
        },
        "sentinel_posture": "NORMAL",
        "sentinel_posture_since": "2026-03-15T06:00:00Z",
    }
    (tmp_path / "portfolio.json").write_text(json.dumps(portfolio))

    # Posture state
    posture = {
        "posture": "NORMAL",
        "posture_since": "2026-03-15T06:00:00Z",
        "consecutive_positive_days": 3,
    }
    (tmp_path / "posture_state.json").write_text(json.dumps(posture))

    # Alerts log
    alerts = [
        json.dumps({"ts": "2026-03-16T10:00:00Z", "level": "INFO", "message": "Daily reset complete"}),
        json.dumps({"ts": "2026-03-16T10:05:00Z", "level": "WARNING", "message": "Slippage elevated on MES"}),
        json.dumps({"ts": "2026-03-16T10:10:00Z", "level": "CAUTION", "message": "Streak -3 detected"}),
    ]
    (tmp_path / "alerts.log").write_text("\n".join(alerts) + "\n")

    # Ledger
    entries = [
        json.dumps({
            "ledger_seq": 1, "timestamp": "2026-03-15T16:00:00Z",
            "event_type": "DAILY_SNAPSHOT", "run_id": "R1", "ref_id": "DAILY",
            "payload": {"equity_usd": 100000.0, "date": "2026-03-15"},
            "checksum": "sha256:abc",
        }),
        json.dumps({
            "ledger_seq": 2, "timestamp": "2026-03-16T16:00:00Z",
            "event_type": "DAILY_SNAPSHOT", "run_id": "R2", "ref_id": "DAILY",
            "payload": {"equity_usd": 101250.0, "date": "2026-03-16"},
            "checksum": "sha256:def",
        }),
        json.dumps({
            "ledger_seq": 3, "timestamp": "2026-03-16T14:00:00Z",
            "event_type": "POSITION_CLOSED", "run_id": "R2", "ref_id": "POS_099",
            "payload": {
                "symbol": "NQ", "side": "SHORT", "strategy_id": "trend_5m_MNQ",
                "realized_pnl_usd": 320.0, "entry_price": 19500.0,
                "exit_price": 19340.0, "contracts": 1,
            },
            "checksum": "sha256:ghi",
        }),
    ]
    (tmp_path / "ledger.jsonl").write_text("\n".join(entries) + "\n")

    # Strategy
    strategy = {
        "strategy_id": "orb_5m_MES",
        "symbol": "ES", "timeframe": "5m", "status": "ACTIVE",
        "incubation": {"is_incubating": True, "incubation_start": "2026-03-01T00:00:00Z",
                       "incubation_size_pct": 25, "incubation_min_trades": 50, "incubation_min_days": 30},
    }
    (tmp_path / "strategies" / "orb_5m_MES.json").write_text(json.dumps(strategy))

    # Regime
    regime = {
        "ES": {"regime_type": "TRENDING", "vol_driver": "VIX", "vol_value": 18.0, "score": 72},
        "CL": {"regime_type": "VOLATILE", "vol_driver": "ATR", "vol_value": 1.8, "score": 45},
    }
    (tmp_path / "intraday_regime.json").write_text(json.dumps(regime))

    yield tmp_path

    # Cleanup env
    os.environ.pop("OPENCLAW_DATA", None)
    os.environ.pop("OPENCLAW_STRATEGIES", None)


class TestReadPortfolio:
    def test_returns_portfolio_dict(self, data_dir):
        import importlib
        import shared.state_store as store
        importlib.reload(store)
        from dashboard.api.data_readers import read_portfolio
        result = read_portfolio()
        assert result["account"]["equity_usd"] == 101250.0
        assert result["pnl"]["total_today_pct"] == 1.25
        assert len(result["positions"]) == 1
        assert result["sentinel_posture"] == "NORMAL"

    def test_includes_posture_details(self, data_dir):
        import importlib
        import shared.state_store as store
        importlib.reload(store)
        from dashboard.api.data_readers import read_portfolio
        result = read_portfolio()
        assert result["posture_details"]["posture"] == "NORMAL"
        assert result["posture_details"]["consecutive_positive_days"] == 3


class TestReadAlerts:
    def test_returns_alerts_newest_first(self, data_dir):
        from dashboard.api.data_readers import read_alerts
        result = read_alerts(data_dir, limit=20)
        assert len(result) == 3
        assert result[0]["level"] == "CAUTION"  # newest first
        assert result[2]["level"] == "INFO"     # oldest last

    def test_limit_works(self, data_dir):
        from dashboard.api.data_readers import read_alerts
        result = read_alerts(data_dir, limit=2)
        assert len(result) == 2


class TestReadTrades:
    def test_returns_closed_positions(self, data_dir):
        from dashboard.api.data_readers import read_trades
        result = read_trades(data_dir, limit=50)
        assert len(result) == 1
        assert result[0]["payload"]["symbol"] == "NQ"
        assert result[0]["payload"]["realized_pnl_usd"] == 320.0


class TestReadEquityCurve:
    def test_returns_daily_snapshots(self, data_dir):
        from dashboard.api.data_readers import read_equity_curve
        result = read_equity_curve(data_dir, days=30)
        assert len(result) == 2
        assert result[0]["payload"]["equity_usd"] == 100000.0
        assert result[1]["payload"]["equity_usd"] == 101250.0


class TestReadHealth:
    def test_returns_strategy_configs(self, data_dir):
        import importlib
        import shared.state_store as store
        importlib.reload(store)
        from dashboard.api.data_readers import read_health
        result = read_health()
        assert "orb_5m_MES" in result
        assert result["orb_5m_MES"]["status"] == "ACTIVE"


class TestReadRegime:
    def test_returns_regime_state(self, data_dir):
        from dashboard.api.data_readers import read_regime
        result = read_regime(data_dir)
        assert result["ES"]["regime_type"] == "TRENDING"
        assert result["CL"]["regime_type"] == "VOLATILE"
```

**Step 4: Run tests to verify they fail**

```bash
cd /Users/jasonljc/trading && python3 -m pytest dashboard/api/tests/test_data_readers.py -v --tb=short
```

Expected: FAIL (module not found)

**Step 5: Implement `dashboard/api/data_readers.py`**

```python
# dashboard/api/data_readers.py
"""Shared data reading functions for dashboard API and Telegram bot."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

# Add trading root to path for shared module access
_TRADING_ROOT = Path(__file__).parent.parent.parent
if str(_TRADING_ROOT) not in sys.path:
    sys.path.insert(0, str(_TRADING_ROOT))

from shared import state_store as store


def _data_dir() -> Path:
    return Path(os.environ.get("OPENCLAW_DATA", _TRADING_ROOT / "data"))


def read_portfolio() -> dict[str, Any]:
    """Read portfolio + posture state."""
    portfolio = store.load_portfolio()
    posture_state = store.load_state("posture_state") or {}
    portfolio["posture_details"] = posture_state
    return portfolio


def read_alerts(data_dir: Path | None = None, limit: int = 20) -> list[dict]:
    """Read alerts.log, return newest first."""
    d = data_dir or _data_dir()
    alerts_path = d / "alerts.log"
    if not alerts_path.exists():
        return []
    alerts = []
    with open(alerts_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                alerts.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    # Newest first
    alerts.reverse()
    return alerts[:limit]


def read_trades(data_dir: Path | None = None, limit: int = 50) -> list[dict]:
    """Read POSITION_CLOSED events from ledger, newest first."""
    d = data_dir or _data_dir()
    ledger_path = d / "ledger.jsonl"
    if not ledger_path.exists():
        return []
    trades = []
    with open(ledger_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("event_type") == "POSITION_CLOSED":
                trades.append(entry)
    trades.reverse()
    return trades[:limit]


def read_equity_curve(data_dir: Path | None = None, days: int = 30) -> list[dict]:
    """Read DAILY_SNAPSHOT events from ledger, oldest first."""
    d = data_dir or _data_dir()
    ledger_path = d / "ledger.jsonl"
    if not ledger_path.exists():
        return []
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    snapshots = []
    with open(ledger_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("event_type") == "DAILY_SNAPSHOT":
                if entry.get("timestamp", "") >= cutoff:
                    snapshots.append(entry)
    return snapshots


def read_health() -> dict[str, dict]:
    """Read strategy registry for health/incubation data."""
    return store.load_strategy_registry()


def read_regime(data_dir: Path | None = None) -> dict[str, dict]:
    """Read intraday regime state."""
    d = data_dir or _data_dir()
    regime_path = d / "intraday_regime.json"
    if not regime_path.exists():
        return {}
    try:
        with open(regime_path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def read_signals(redis_url: str = "") -> dict[str, list]:
    """Read active signals from Redis streams."""
    url = redis_url or os.environ.get("REDIS_URL", "redis://localhost:6379")
    try:
        import redis
        rc = redis.from_url(url, decode_responses=True)
        from openclaw_trader.signals.signal_publisher import read_active_signals
        news = read_active_signals(rc, "news_signals", count=50)
        poly = read_active_signals(rc, "polymarket_signals", count=50)
        return {"news": news, "polymarket": poly}
    except Exception:
        return {"news": [], "polymarket": []}
```

**Step 6: Write minimal `dashboard/api/main.py`**

```python
# dashboard/api/main.py
"""FastAPI dashboard backend."""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure trading root is importable
_TRADING_ROOT = Path(__file__).parent.parent.parent
if str(_TRADING_ROOT) not in sys.path:
    sys.path.insert(0, str(_TRADING_ROOT))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="OpenClaw Dashboard", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/api/health-check")
def health_check():
    return {"status": "ok"}
```

**Step 7: Run tests to verify they pass**

```bash
cd /Users/jasonljc/trading && python3 -m pytest dashboard/api/tests/test_data_readers.py -v --tb=short
```

Expected: all 8 tests PASS

**Step 8: Commit**

```bash
git add dashboard/ && git commit -m "feat: dashboard backend scaffolding and data readers with tests"
```

---

### Task 2: API route — portfolio

**Files:**
- Create: `dashboard/api/routers/portfolio.py`
- Test: `dashboard/api/tests/test_routes.py`

**Step 1: Write test**

```python
# dashboard/api/tests/test_routes.py
"""Tests for dashboard API routes."""
import json
import os
import pytest
import importlib
from pathlib import Path
from fastapi.testclient import TestClient


@pytest.fixture
def data_dir(tmp_path):
    os.environ["OPENCLAW_DATA"] = str(tmp_path)
    os.environ["OPENCLAW_STRATEGIES"] = str(tmp_path / "strategies")
    (tmp_path / "strategies").mkdir()

    portfolio = {
        "asof": "2026-03-16T12:00:00Z",
        "param_version": "PV_0001",
        "account": {"equity_usd": 101250.0, "opening_equity_usd": 100000.0,
                     "peak_equity_usd": 102000.0, "cash_usd": 95000.0,
                     "margin_used_usd": 6250.0, "margin_available_usd": 95000.0,
                     "margin_utilization_pct": 6.17},
        "pnl": {"unrealized_usd": 430.0, "realized_today_usd": 820.0,
                "total_today_usd": 1250.0, "total_today_pct": 1.25,
                "portfolio_dd_pct": 0.73, "portfolio_dd_peak_date": "2026-03-14"},
        "positions": [{"position_id": "POS_001", "symbol": "ES", "side": "LONG",
                       "contracts": 1, "entry_price": 5420.0, "current_price": 5445.0,
                       "stop_price": 5400.0, "target_price": 5480.0,
                       "unrealized_pnl_usd": 125.0, "strategy_id": "orb_5m_MES",
                       "opened_at": "2026-03-16T10:15:00Z"}],
        "heat": {"total_open_risk_usd": 500.0, "total_open_risk_pct": 0.49,
                 "cluster_exposure": {}, "correlations_20d": {}},
        "sentinel_posture": "NORMAL",
        "sentinel_posture_since": "2026-03-15T06:00:00Z",
    }
    (tmp_path / "portfolio.json").write_text(json.dumps(portfolio))

    posture = {"posture": "NORMAL", "posture_since": "2026-03-15T06:00:00Z",
               "consecutive_positive_days": 3}
    (tmp_path / "posture_state.json").write_text(json.dumps(posture))

    alerts = [json.dumps({"ts": "2026-03-16T10:00:00Z", "level": "INFO", "message": "Test alert"})]
    (tmp_path / "alerts.log").write_text("\n".join(alerts) + "\n")

    entries = [
        json.dumps({"ledger_seq": 1, "timestamp": "2026-03-16T16:00:00Z",
                     "event_type": "DAILY_SNAPSHOT", "run_id": "R1", "ref_id": "DAILY",
                     "payload": {"equity_usd": 101250.0, "date": "2026-03-16"},
                     "checksum": "sha256:abc"}),
        json.dumps({"ledger_seq": 2, "timestamp": "2026-03-16T14:00:00Z",
                     "event_type": "POSITION_CLOSED", "run_id": "R1", "ref_id": "POS_099",
                     "payload": {"symbol": "NQ", "side": "SHORT", "strategy_id": "trend_5m_MNQ",
                                 "realized_pnl_usd": 320.0, "entry_price": 19500.0,
                                 "exit_price": 19340.0, "contracts": 1},
                     "checksum": "sha256:def"}),
    ]
    (tmp_path / "ledger.jsonl").write_text("\n".join(entries) + "\n")

    strategy = {"strategy_id": "orb_5m_MES", "symbol": "ES", "timeframe": "5m",
                "status": "ACTIVE", "incubation": {"is_incubating": True,
                "incubation_start": "2026-03-01T00:00:00Z", "incubation_size_pct": 25,
                "incubation_min_trades": 50, "incubation_min_days": 30}}
    (tmp_path / "strategies" / "orb_5m_MES.json").write_text(json.dumps(strategy))

    regime = {"ES": {"regime_type": "TRENDING", "vol_driver": "VIX", "vol_value": 18.0, "score": 72}}
    (tmp_path / "intraday_regime.json").write_text(json.dumps(regime))

    import shared.state_store as store
    importlib.reload(store)
    yield tmp_path
    os.environ.pop("OPENCLAW_DATA", None)
    os.environ.pop("OPENCLAW_STRATEGIES", None)


@pytest.fixture
def client(data_dir):
    from dashboard.api.main import app
    return TestClient(app)


class TestPortfolioRoute:
    def test_returns_200(self, client):
        resp = client.get("/api/portfolio")
        assert resp.status_code == 200

    def test_has_account_fields(self, client):
        data = client.get("/api/portfolio").json()
        assert data["account"]["equity_usd"] == 101250.0
        assert data["pnl"]["total_today_pct"] == 1.25

    def test_has_positions(self, client):
        data = client.get("/api/portfolio").json()
        assert len(data["positions"]) == 1
        assert data["positions"][0]["symbol"] == "ES"

    def test_has_posture_details(self, client):
        data = client.get("/api/portfolio").json()
        assert data["posture_details"]["posture"] == "NORMAL"


class TestAlertsRoute:
    def test_returns_alerts(self, client):
        resp = client.get("/api/alerts")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        assert data[0]["level"] == "INFO"

    def test_limit_param(self, client):
        resp = client.get("/api/alerts?limit=1")
        assert len(resp.json()) == 1


class TestTradesRoute:
    def test_returns_trades(self, client):
        resp = client.get("/api/trades")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["payload"]["symbol"] == "NQ"


class TestEquityCurveRoute:
    def test_returns_snapshots(self, client):
        resp = client.get("/api/equity-curve")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1


class TestHealthRoute:
    def test_returns_strategies(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "orb_5m_MES" in data


class TestRegimeRoute:
    def test_returns_regime(self, client):
        resp = client.get("/api/regime")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ES"]["regime_type"] == "TRENDING"


class TestSignalsRoute:
    def test_returns_empty_when_no_redis(self, client):
        resp = client.get("/api/signals")
        assert resp.status_code == 200
        data = resp.json()
        assert data["news"] == []
        assert data["polymarket"] == []
```

**Step 2: Implement all 7 routers**

```python
# dashboard/api/routers/portfolio.py
from fastapi import APIRouter
from dashboard.api.data_readers import read_portfolio

router = APIRouter()

@router.get("/api/portfolio")
def get_portfolio():
    return read_portfolio()
```

```python
# dashboard/api/routers/signals.py
from fastapi import APIRouter
from dashboard.api.data_readers import read_signals

router = APIRouter()

@router.get("/api/signals")
def get_signals():
    return read_signals()
```

```python
# dashboard/api/routers/alerts.py
from fastapi import APIRouter, Query
from dashboard.api.data_readers import read_alerts

router = APIRouter()

@router.get("/api/alerts")
def get_alerts(limit: int = Query(default=20, ge=1, le=100)):
    return read_alerts(limit=limit)
```

```python
# dashboard/api/routers/trades.py
from fastapi import APIRouter, Query
from dashboard.api.data_readers import read_trades

router = APIRouter()

@router.get("/api/trades")
def get_trades(limit: int = Query(default=50, ge=1, le=200)):
    return read_trades(limit=limit)
```

```python
# dashboard/api/routers/equity_curve.py
from fastapi import APIRouter, Query
from dashboard.api.data_readers import read_equity_curve

router = APIRouter()

@router.get("/api/equity-curve")
def get_equity_curve(days: int = Query(default=30, ge=1, le=365)):
    return read_equity_curve(days=days)
```

```python
# dashboard/api/routers/health.py
from fastapi import APIRouter
from dashboard.api.data_readers import read_health

router = APIRouter()

@router.get("/api/health")
def get_health():
    return read_health()
```

```python
# dashboard/api/routers/regime.py
from fastapi import APIRouter
from dashboard.api.data_readers import read_regime

router = APIRouter()

@router.get("/api/regime")
def get_regime():
    return read_regime()
```

**Step 3: Register all routers in main.py**

Update `dashboard/api/main.py` to include:

```python
from dashboard.api.routers import portfolio, signals, alerts, trades, equity_curve, health, regime

app.include_router(portfolio.router)
app.include_router(signals.router)
app.include_router(alerts.router)
app.include_router(trades.router)
app.include_router(equity_curve.router)
app.include_router(health.router)
app.include_router(regime.router)
```

**Step 4: Run tests**

```bash
cd /Users/jasonljc/trading && python3 -m pytest dashboard/api/tests/test_routes.py -v --tb=short
```

Expected: all 12 tests PASS

**Step 5: Commit**

```bash
git add dashboard/ && git commit -m "feat: 7 dashboard API routes with tests"
```

---

### Task 3: Telegram bot

**Files:**
- Create: `dashboard/api/telegram_bot.py`
- Test: `dashboard/api/tests/test_telegram_bot.py`

**Step 1: Write tests**

```python
# dashboard/api/tests/test_telegram_bot.py
"""Tests for Telegram bot command formatters."""
import json
import os
import pytest
import importlib


@pytest.fixture
def data_dir(tmp_path):
    os.environ["OPENCLAW_DATA"] = str(tmp_path)
    os.environ["OPENCLAW_STRATEGIES"] = str(tmp_path / "strategies")
    (tmp_path / "strategies").mkdir()

    portfolio = {
        "asof": "2026-03-16T12:00:00Z", "param_version": "PV_0001",
        "account": {"equity_usd": 101250.0, "opening_equity_usd": 100000.0,
                     "peak_equity_usd": 102000.0, "cash_usd": 95000.0,
                     "margin_used_usd": 6250.0, "margin_available_usd": 95000.0,
                     "margin_utilization_pct": 6.17},
        "pnl": {"unrealized_usd": 430.0, "realized_today_usd": 820.0,
                "total_today_usd": 1250.0, "total_today_pct": 1.25,
                "portfolio_dd_pct": 0.73, "portfolio_dd_peak_date": "2026-03-14"},
        "positions": [{"position_id": "POS_001", "symbol": "ES", "side": "LONG",
                       "contracts": 1, "entry_price": 5420.0, "current_price": 5445.0,
                       "stop_price": 5400.0, "target_price": 5480.0,
                       "unrealized_pnl_usd": 125.0, "strategy_id": "orb_5m_MES",
                       "opened_at": "2026-03-16T10:15:00Z"}],
        "heat": {"total_open_risk_usd": 500.0, "total_open_risk_pct": 0.49,
                 "cluster_exposure": {}, "correlations_20d": {}},
        "sentinel_posture": "NORMAL",
        "sentinel_posture_since": "2026-03-15T06:00:00Z",
    }
    (tmp_path / "portfolio.json").write_text(json.dumps(portfolio))
    posture = {"posture": "NORMAL", "posture_since": "2026-03-15T06:00:00Z",
               "consecutive_positive_days": 3}
    (tmp_path / "posture_state.json").write_text(json.dumps(posture))

    alerts = [json.dumps({"ts": "2026-03-16T10:00:00Z", "level": "INFO", "message": "Test"})]
    (tmp_path / "alerts.log").write_text("\n".join(alerts) + "\n")

    entries = [json.dumps({"ledger_seq": 1, "timestamp": "2026-03-16T14:00:00Z",
               "event_type": "POSITION_CLOSED", "run_id": "R1", "ref_id": "POS_099",
               "payload": {"symbol": "NQ", "side": "SHORT", "strategy_id": "trend_5m_MNQ",
                           "realized_pnl_usd": 320.0, "entry_price": 19500.0,
                           "exit_price": 19340.0, "contracts": 1},
               "checksum": "sha256:abc"})]
    (tmp_path / "ledger.jsonl").write_text("\n".join(entries) + "\n")

    strategy = {"strategy_id": "orb_5m_MES", "symbol": "ES", "timeframe": "5m",
                "status": "ACTIVE", "incubation": {"is_incubating": True,
                "incubation_start": "2026-03-01T00:00:00Z", "incubation_size_pct": 25,
                "incubation_min_trades": 50, "incubation_min_days": 30}}
    (tmp_path / "strategies" / "orb_5m_MES.json").write_text(json.dumps(strategy))

    regime = {"ES": {"regime_type": "TRENDING", "vol_driver": "VIX", "vol_value": 18.0, "score": 72}}
    (tmp_path / "intraday_regime.json").write_text(json.dumps(regime))

    import shared.state_store as store
    importlib.reload(store)
    yield tmp_path
    os.environ.pop("OPENCLAW_DATA", None)
    os.environ.pop("OPENCLAW_STRATEGIES", None)


class TestStatusFormat:
    def test_returns_string_with_equity(self, data_dir):
        from dashboard.api.telegram_bot import format_status
        text = format_status()
        assert "$101,250" in text
        assert "NORMAL" in text

    def test_includes_pnl(self, data_dir):
        from dashboard.api.telegram_bot import format_status
        text = format_status()
        assert "+$1,250" in text or "1,250" in text


class TestPositionsFormat:
    def test_returns_position_lines(self, data_dir):
        from dashboard.api.telegram_bot import format_positions
        text = format_positions()
        assert "ES" in text
        assert "LONG" in text

    def test_no_positions(self, data_dir):
        portfolio = json.loads((data_dir / "portfolio.json").read_text())
        portfolio["positions"] = []
        (data_dir / "portfolio.json").write_text(json.dumps(portfolio))
        import shared.state_store as store
        importlib.reload(store)
        from dashboard.api.telegram_bot import format_positions
        text = format_positions()
        assert "No open positions" in text


class TestPnlFormat:
    def test_returns_pnl_breakdown(self, data_dir):
        from dashboard.api.telegram_bot import format_pnl
        text = format_pnl()
        assert "Realized" in text or "realized" in text
        assert "Unrealized" in text or "unrealized" in text


class TestAlertsFormat:
    def test_returns_alerts(self, data_dir):
        from dashboard.api.telegram_bot import format_alerts
        text = format_alerts()
        assert "INFO" in text


class TestHealthFormat:
    def test_returns_strategy_health(self, data_dir):
        from dashboard.api.telegram_bot import format_health
        text = format_health()
        assert "orb_5m_MES" in text


class TestRegimeFormat:
    def test_returns_regime_state(self, data_dir):
        from dashboard.api.telegram_bot import format_regime
        text = format_regime()
        assert "ES" in text
        assert "TRENDING" in text
```

**Step 2: Implement `dashboard/api/telegram_bot.py`**

```python
# dashboard/api/telegram_bot.py
"""Telegram bot command handlers for OpenClaw dashboard."""
from __future__ import annotations

import os
import logging
from dashboard.api.data_readers import (
    read_portfolio, read_alerts, read_trades, read_signals, read_health, read_regime,
)

logger = logging.getLogger(__name__)


def format_status() -> str:
    try:
        p = read_portfolio()
        acct = p.get("account", {})
        pnl = p.get("pnl", {})
        equity = acct.get("equity_usd", 0)
        today = pnl.get("total_today_usd", 0)
        today_pct = pnl.get("total_today_pct", 0)
        dd = pnl.get("portfolio_dd_pct", 0)
        posture = p.get("sentinel_posture", "?")
        positions = len(p.get("positions", []))
        sign = "+" if today >= 0 else ""
        return (
            f"Equity: ${equity:,.0f} | "
            f"Today: {sign}${today:,.0f} ({sign}{today_pct:.2f}%) | "
            f"DD: {dd:.1f}% | "
            f"Posture: {posture} | "
            f"Positions: {positions}"
        )
    except Exception as e:
        return f"Error reading status: {e}"


def format_positions() -> str:
    try:
        p = read_portfolio()
        positions = p.get("positions", [])
        if not positions:
            return "No open positions"
        lines = []
        for pos in positions:
            sym = pos.get("symbol", "?")
            side = pos.get("side", "?")
            contracts = pos.get("contracts", 0)
            entry = pos.get("entry_price", 0)
            current = pos.get("current_price", 0)
            pnl = pos.get("unrealized_pnl_usd", 0)
            stop = pos.get("stop_price", 0)
            sign = "+" if pnl >= 0 else ""
            lines.append(
                f"{sym} {side} {contracts}x @ {entry:,.2f} → {current:,.2f} "
                f"({sign}${pnl:,.0f}) stop:{stop:,.2f}"
            )
        return "\n".join(lines)
    except Exception as e:
        return f"Error reading positions: {e}"


def format_signals() -> str:
    try:
        signals = read_signals()
        lines = []
        for s in signals.get("news", [])[:5]:
            tier = s.get("tier", "?")
            headline = s.get("headline", "")[:80]
            instruments = s.get("instruments", [])
            lines.append(f"{tier}: \"{headline}\" [{' '.join(instruments)}]")
        for s in signals.get("polymarket", [])[:3]:
            sig_type = s.get("type", "?")
            strength = s.get("strength", "?")
            market = s.get("market_question", "")[:60]
            lines.append(f"Polymarket {sig_type} ({strength}): {market}")
        if not lines:
            return "No active signals"
        return "\n".join(lines)
    except Exception as e:
        return f"Error reading signals: {e}"


def format_alerts() -> str:
    try:
        alerts = read_alerts(limit=5)
        if not alerts:
            return "No recent alerts"
        lines = []
        for a in alerts:
            ts = a.get("ts", "?")[:19]
            level = a.get("level", "?")
            msg = a.get("message", "")
            lines.append(f"[{ts}] {level}: {msg}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error reading alerts: {e}"


def format_pnl() -> str:
    try:
        p = read_portfolio()
        acct = p.get("account", {})
        pnl = p.get("pnl", {})
        opening = acct.get("opening_equity_usd", 0)
        equity = acct.get("equity_usd", 0)
        realized = pnl.get("realized_today_usd", 0)
        unrealized = pnl.get("unrealized_usd", 0)
        total = pnl.get("total_today_usd", 0)
        pct = pnl.get("total_today_pct", 0)
        positions = p.get("positions", [])
        lines = [
            f"Opening: ${opening:,.0f}",
            f"Current: ${equity:,.0f}",
            f"Realized: ${realized:+,.0f}",
            f"Unrealized: ${unrealized:+,.0f}",
            f"Total: ${total:+,.0f} ({pct:+.2f}%)",
        ]
        if positions:
            lines.append("\nBy position:")
            for pos in positions:
                sym = pos.get("symbol", "?")
                upnl = pos.get("unrealized_pnl_usd", 0)
                lines.append(f"  {sym}: ${upnl:+,.0f}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error reading PnL: {e}"


def format_health() -> str:
    try:
        registry = read_health()
        if not registry:
            return "No strategies loaded"
        lines = []
        for sid, cfg in sorted(registry.items()):
            status = cfg.get("status", "?")
            incub = cfg.get("incubation", {})
            is_incub = incub.get("is_incubating", False)
            badge = " [INCUB]" if is_incub else ""
            lines.append(f"{sid}: {status}{badge}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error reading health: {e}"


def format_regime() -> str:
    try:
        regime = read_regime()
        if not regime:
            return "No regime data"
        lines = []
        for sym, r in sorted(regime.items()):
            rtype = r.get("regime_type", "?")
            driver = r.get("vol_driver", "?")
            val = r.get("vol_value", 0)
            score = r.get("score", 0)
            lines.append(f"{sym}: {rtype} ({driver}: {val}) score={score}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error reading regime: {e}"


async def setup_telegram_bot(app) -> None:
    """Start the Telegram bot as a background task in the FastAPI app."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        logger.info("Telegram bot not configured (missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID)")
        return

    try:
        from telegram import Update
        from telegram.ext import Application, CommandHandler, ContextTypes, filters

        tg_app = Application.builder().token(token).build()

        # Only respond to the configured chat
        chat_filter = filters.Chat(chat_id=int(chat_id))

        async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
            await update.message.reply_text(format_status())

        async def cmd_positions(update: Update, context: ContextTypes.DEFAULT_TYPE):
            await update.message.reply_text(format_positions())

        async def cmd_signals(update: Update, context: ContextTypes.DEFAULT_TYPE):
            await update.message.reply_text(format_signals())

        async def cmd_alerts(update: Update, context: ContextTypes.DEFAULT_TYPE):
            await update.message.reply_text(format_alerts())

        async def cmd_pnl(update: Update, context: ContextTypes.DEFAULT_TYPE):
            await update.message.reply_text(format_pnl())

        async def cmd_health(update: Update, context: ContextTypes.DEFAULT_TYPE):
            await update.message.reply_text(format_health())

        async def cmd_regime(update: Update, context: ContextTypes.DEFAULT_TYPE):
            await update.message.reply_text(format_regime())

        tg_app.add_handler(CommandHandler("status", cmd_status, filters=chat_filter))
        tg_app.add_handler(CommandHandler("positions", cmd_positions, filters=chat_filter))
        tg_app.add_handler(CommandHandler("signals", cmd_signals, filters=chat_filter))
        tg_app.add_handler(CommandHandler("alerts", cmd_alerts, filters=chat_filter))
        tg_app.add_handler(CommandHandler("pnl", cmd_pnl, filters=chat_filter))
        tg_app.add_handler(CommandHandler("health", cmd_health, filters=chat_filter))
        tg_app.add_handler(CommandHandler("regime", cmd_regime, filters=chat_filter))

        await tg_app.initialize()
        await tg_app.start()
        await tg_app.updater.start_polling()
        logger.info("Telegram bot started")

    except ImportError:
        logger.warning("python-telegram-bot not installed — Telegram bot disabled")
    except Exception as e:
        logger.error(f"Failed to start Telegram bot: {e}")
```

**Step 3: Wire bot startup into main.py**

Add to `dashboard/api/main.py`:

```python
from contextlib import asynccontextmanager
from dashboard.api.telegram_bot import setup_telegram_bot

@asynccontextmanager
async def lifespan(app: FastAPI):
    await setup_telegram_bot(app)
    yield

# Update app creation:
app = FastAPI(title="OpenClaw Dashboard", version="1.0.0", lifespan=lifespan)
```

**Step 4: Run tests**

```bash
cd /Users/jasonljc/trading && python3 -m pytest dashboard/api/tests/test_telegram_bot.py -v --tb=short
```

Expected: all 9 tests PASS

**Step 5: Commit**

```bash
git add dashboard/ && git commit -m "feat: Telegram bot with 7 commands and formatters"
```

---

### Task 4: React frontend scaffolding

**Files:**
- Create: `dashboard/ui/package.json`
- Create: `dashboard/ui/vite.config.ts`
- Create: `dashboard/ui/tsconfig.json`
- Create: `dashboard/ui/tailwind.config.js`
- Create: `dashboard/ui/postcss.config.js`
- Create: `dashboard/ui/index.html`
- Create: `dashboard/ui/src/main.tsx`
- Create: `dashboard/ui/src/App.tsx`
- Create: `dashboard/ui/src/api.ts`
- Create: `dashboard/ui/src/index.css`
- Create: `dashboard/ui/src/hooks/useApi.ts`

**Step 1: Initialize React project**

```bash
cd /Users/jasonljc/trading/dashboard/ui
npm create vite@latest . -- --template react-ts
npm install react-router-dom axios recharts lightweight-charts
npm install -D tailwindcss @tailwindcss/vite
```

**Step 2: Write `dashboard/ui/src/api.ts`**

```typescript
// dashboard/ui/src/api.ts
import axios from "axios";

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || "/api",
});

export const fetchPortfolio = () => api.get("/portfolio").then((r) => r.data);
export const fetchSignals = () => api.get("/signals").then((r) => r.data);
export const fetchAlerts = (limit = 20) => api.get(`/alerts?limit=${limit}`).then((r) => r.data);
export const fetchTrades = (limit = 50) => api.get(`/trades?limit=${limit}`).then((r) => r.data);
export const fetchEquityCurve = (days = 30) => api.get(`/equity-curve?days=${days}`).then((r) => r.data);
export const fetchHealth = () => api.get("/health").then((r) => r.data);
export const fetchRegime = () => api.get("/regime").then((r) => r.data);
```

**Step 3: Write `dashboard/ui/src/hooks/useApi.ts`**

```typescript
// dashboard/ui/src/hooks/useApi.ts
import { useState, useCallback } from "react";

export function useApi<T>(fetcher: () => Promise<T>) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await fetcher();
      setData(result);
      setLastUpdated(new Date());
    } catch (e: any) {
      setError(e.message || "Failed to fetch");
    } finally {
      setLoading(false);
    }
  }, [fetcher]);

  return { data, loading, error, lastUpdated, refresh };
}
```

**Step 4: Write `dashboard/ui/src/App.tsx`**

```tsx
// dashboard/ui/src/App.tsx
import { BrowserRouter, Routes, Route, NavLink } from "react-router-dom";
import LiveOverview from "./pages/LiveOverview";
import Analytics from "./pages/Analytics";

export default function App() {
  return (
    <BrowserRouter>
      <div className="min-h-screen bg-gray-950 text-gray-100">
        <nav className="bg-gray-900 border-b border-gray-800 px-4 py-3 flex items-center gap-6">
          <span className="text-lg font-bold text-emerald-400">OpenClaw</span>
          <NavLink
            to="/"
            className={({ isActive }) =>
              isActive ? "text-emerald-400 font-medium" : "text-gray-400 hover:text-gray-200"
            }
          >
            Live
          </NavLink>
          <NavLink
            to="/analytics"
            className={({ isActive }) =>
              isActive ? "text-emerald-400 font-medium" : "text-gray-400 hover:text-gray-200"
            }
          >
            Analytics
          </NavLink>
        </nav>
        <main className="p-4 max-w-7xl mx-auto">
          <Routes>
            <Route path="/" element={<LiveOverview />} />
            <Route path="/analytics" element={<Analytics />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}
```

**Step 5: Write placeholder pages**

```tsx
// dashboard/ui/src/pages/LiveOverview.tsx
export default function LiveOverview() {
  return <div className="text-gray-400">Live Overview — components coming soon</div>;
}
```

```tsx
// dashboard/ui/src/pages/Analytics.tsx
export default function Analytics() {
  return <div className="text-gray-400">Analytics — components coming soon</div>;
}
```

**Step 6: Update `dashboard/ui/src/index.css`**

```css
@import "tailwindcss";
```

**Step 7: Verify build**

```bash
cd /Users/jasonljc/trading/dashboard/ui && npm run build
```

Expected: Build succeeds, `dist/` created

**Step 8: Commit**

```bash
cd /Users/jasonljc/trading && git add dashboard/ui/ && git commit -m "feat: React frontend scaffolding with Vite, Tailwind, routing"
```

---

### Task 5: Live Overview components (Page 1)

**Files:**
- Create: `dashboard/ui/src/components/PortfolioSummary.tsx`
- Create: `dashboard/ui/src/components/PostureCard.tsx`
- Create: `dashboard/ui/src/components/PositionsTable.tsx`
- Create: `dashboard/ui/src/components/SignalsPanel.tsx`
- Create: `dashboard/ui/src/components/AlertsPanel.tsx`
- Modify: `dashboard/ui/src/pages/LiveOverview.tsx`

**Step 1: Write `PortfolioSummary.tsx`**

```tsx
// dashboard/ui/src/components/PortfolioSummary.tsx
interface Props {
  data: any;
}

export default function PortfolioSummary({ data }: Props) {
  if (!data) return null;
  const { account, pnl, heat } = data;
  const equity = account?.equity_usd ?? 0;
  const opening = account?.opening_equity_usd ?? 0;
  const peak = account?.peak_equity_usd ?? 0;
  const todayPnl = pnl?.total_today_usd ?? 0;
  const todayPct = pnl?.total_today_pct ?? 0;
  const dd = pnl?.portfolio_dd_pct ?? 0;
  const heatPct = heat?.total_open_risk_pct ?? 0;
  const positive = todayPnl >= 0;

  return (
    <div className="bg-gray-900 rounded-lg p-4 border border-gray-800">
      <h2 className="text-sm font-medium text-gray-400 mb-3">Portfolio</h2>
      <div className="text-3xl font-bold mb-2">${equity.toLocaleString()}</div>
      <div className="grid grid-cols-2 gap-2 text-sm">
        <div>
          <span className="text-gray-500">Today </span>
          <span className={positive ? "text-emerald-400" : "text-red-400"}>
            {positive ? "+" : ""}${todayPnl.toLocaleString()} ({positive ? "+" : ""}{todayPct.toFixed(2)}%)
          </span>
        </div>
        <div>
          <span className="text-gray-500">Opening </span>
          <span>${opening.toLocaleString()}</span>
        </div>
        <div>
          <span className="text-gray-500">Peak </span>
          <span>${peak.toLocaleString()}</span>
        </div>
        <div>
          <span className="text-gray-500">DD </span>
          <span className={dd > 4 ? "text-red-400" : "text-gray-300"}>{dd.toFixed(2)}%</span>
        </div>
        <div>
          <span className="text-gray-500">Heat </span>
          <span>{heatPct.toFixed(2)}%</span>
        </div>
      </div>
    </div>
  );
}
```

**Step 2: Write `PostureCard.tsx`**

```tsx
// dashboard/ui/src/components/PostureCard.tsx
interface Props {
  data: any;
}

const POSTURE_COLORS: Record<string, string> = {
  NORMAL: "text-emerald-400",
  CAUTION: "text-yellow-400",
  DEFENSIVE: "text-orange-400",
  HALT: "text-red-500",
};

export default function PostureCard({ data }: Props) {
  if (!data) return null;
  const posture = data.sentinel_posture ?? "?";
  const since = data.sentinel_posture_since ?? "";
  const details = data.posture_details ?? {};
  const streak = details.consecutive_positive_days ?? 0;
  const dd = data.pnl?.portfolio_dd_pct ?? 0;

  const thresholds = [
    { label: "CAUTION", pct: 4 },
    { label: "DEFENSIVE", pct: 10 },
    { label: "HALT", pct: 15 },
  ];

  return (
    <div className="bg-gray-900 rounded-lg p-4 border border-gray-800">
      <h2 className="text-sm font-medium text-gray-400 mb-3">Sentinel Posture</h2>
      <div className={`text-2xl font-bold mb-2 ${POSTURE_COLORS[posture] ?? "text-gray-300"}`}>
        {posture}
      </div>
      <div className="text-sm space-y-1">
        <div><span className="text-gray-500">Since </span>{since.slice(0, 10)}</div>
        <div><span className="text-gray-500">Streak </span>{streak} positive days</div>
        <div className="mt-2">
          <div className="text-gray-500 text-xs mb-1">DD vs thresholds</div>
          <div className="w-full bg-gray-800 rounded-full h-2">
            <div
              className={`h-2 rounded-full ${dd > 10 ? "bg-red-500" : dd > 4 ? "bg-yellow-400" : "bg-emerald-400"}`}
              style={{ width: `${Math.min(dd / 15 * 100, 100)}%` }}
            />
          </div>
          <div className="flex justify-between text-xs text-gray-600 mt-1">
            {thresholds.map((t) => (
              <span key={t.label}>{t.label} {t.pct}%</span>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
```

**Step 3: Write `PositionsTable.tsx`**

```tsx
// dashboard/ui/src/components/PositionsTable.tsx
interface Props {
  positions: any[];
}

export default function PositionsTable({ positions }: Props) {
  if (!positions || positions.length === 0) {
    return (
      <div className="bg-gray-900 rounded-lg p-4 border border-gray-800">
        <h2 className="text-sm font-medium text-gray-400 mb-3">Open Positions</h2>
        <div className="text-gray-500 text-sm">No open positions</div>
      </div>
    );
  }

  return (
    <div className="bg-gray-900 rounded-lg p-4 border border-gray-800">
      <h2 className="text-sm font-medium text-gray-400 mb-3">
        Open Positions ({positions.length})
      </h2>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-gray-500 text-left border-b border-gray-800">
              <th className="pb-2">Symbol</th>
              <th className="pb-2">Side</th>
              <th className="pb-2">Qty</th>
              <th className="pb-2">Entry</th>
              <th className="pb-2">Current</th>
              <th className="pb-2">P&L</th>
              <th className="pb-2">Stop</th>
              <th className="pb-2">Target</th>
              <th className="pb-2">Strategy</th>
            </tr>
          </thead>
          <tbody>
            {positions.map((pos: any) => {
              const pnl = pos.unrealized_pnl_usd ?? 0;
              const positive = pnl >= 0;
              return (
                <tr key={pos.position_id} className="border-b border-gray-800/50">
                  <td className="py-2 font-medium">{pos.symbol}</td>
                  <td className={pos.side === "LONG" ? "text-emerald-400" : "text-red-400"}>
                    {pos.side}
                  </td>
                  <td>{pos.contracts}</td>
                  <td>{pos.entry_price?.toLocaleString()}</td>
                  <td>{pos.current_price?.toLocaleString()}</td>
                  <td className={positive ? "text-emerald-400" : "text-red-400"}>
                    {positive ? "+" : ""}${pnl.toLocaleString()}
                  </td>
                  <td className="text-gray-500">{pos.stop_price?.toLocaleString()}</td>
                  <td className="text-gray-500">{pos.target_price?.toLocaleString()}</td>
                  <td className="text-gray-500 text-xs">{pos.strategy_id}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
```

**Step 4: Write `SignalsPanel.tsx`**

```tsx
// dashboard/ui/src/components/SignalsPanel.tsx
interface Props {
  data: any;
}

const TIER_COLORS: Record<string, string> = {
  HALT: "bg-red-500/20 text-red-400 border-red-500/30",
  REDUCE: "bg-orange-500/20 text-orange-400 border-orange-500/30",
  CAUTION: "bg-yellow-500/20 text-yellow-400 border-yellow-500/30",
};

export default function SignalsPanel({ data }: Props) {
  const news = data?.news ?? [];
  const poly = data?.polymarket ?? [];
  const empty = news.length === 0 && poly.length === 0;

  return (
    <div className="bg-gray-900 rounded-lg p-4 border border-gray-800">
      <h2 className="text-sm font-medium text-gray-400 mb-3">Active Signals</h2>
      {empty && <div className="text-gray-500 text-sm">No active signals</div>}
      <div className="space-y-2 max-h-64 overflow-y-auto">
        {news.map((s: any, i: number) => (
          <div key={i} className={`text-sm p-2 rounded border ${TIER_COLORS[s.tier] ?? "border-gray-700"}`}>
            <div className="font-medium">{s.tier} — {s.source_id}</div>
            <div className="text-gray-300 text-xs mt-1">{s.headline}</div>
            <div className="text-gray-500 text-xs mt-1">{(s.instruments ?? []).join(", ")}</div>
          </div>
        ))}
        {poly.map((s: any, i: number) => (
          <div key={`p${i}`} className="text-sm p-2 rounded border border-blue-500/30 bg-blue-500/10">
            <div className="font-medium text-blue-400">
              {s.type} ({s.strength})
            </div>
            <div className="text-gray-300 text-xs mt-1">{s.market_question}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
```

**Step 5: Write `AlertsPanel.tsx`**

```tsx
// dashboard/ui/src/components/AlertsPanel.tsx
interface Props {
  alerts: any[];
}

const LEVEL_COLORS: Record<string, string> = {
  HALT: "text-red-500",
  DEGRADED: "text-red-400",
  DEFENSIVE: "text-orange-400",
  CAUTION: "text-yellow-400",
  WARNING: "text-yellow-300",
  INFO: "text-blue-400",
  RECOVERY: "text-emerald-400",
};

export default function AlertsPanel({ alerts }: Props) {
  return (
    <div className="bg-gray-900 rounded-lg p-4 border border-gray-800">
      <h2 className="text-sm font-medium text-gray-400 mb-3">Alerts</h2>
      {(!alerts || alerts.length === 0) && (
        <div className="text-gray-500 text-sm">No recent alerts</div>
      )}
      <div className="space-y-1 max-h-64 overflow-y-auto">
        {(alerts ?? []).map((a: any, i: number) => (
          <div key={i} className="text-sm flex gap-2">
            <span className="text-gray-600 text-xs whitespace-nowrap">
              {a.ts?.slice(11, 19)}
            </span>
            <span className={`font-medium text-xs ${LEVEL_COLORS[a.level] ?? "text-gray-400"}`}>
              {a.level}
            </span>
            <span className="text-gray-300 text-xs">{a.message}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
```

**Step 6: Wire up `LiveOverview.tsx`**

```tsx
// dashboard/ui/src/pages/LiveOverview.tsx
import { useCallback } from "react";
import { useApi } from "../hooks/useApi";
import { fetchPortfolio, fetchSignals, fetchAlerts } from "../api";
import PortfolioSummary from "../components/PortfolioSummary";
import PostureCard from "../components/PostureCard";
import PositionsTable from "../components/PositionsTable";
import SignalsPanel from "../components/SignalsPanel";
import AlertsPanel from "../components/AlertsPanel";

export default function LiveOverview() {
  const portfolio = useApi(useCallback(() => fetchPortfolio(), []));
  const signals = useApi(useCallback(() => fetchSignals(), []));
  const alerts = useApi(useCallback(() => fetchAlerts(20), []));

  const refreshAll = () => {
    portfolio.refresh();
    signals.refresh();
    alerts.refresh();
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold">Live Overview</h1>
        <div className="flex items-center gap-3">
          {portfolio.lastUpdated && (
            <span className="text-xs text-gray-500">
              Updated: {portfolio.lastUpdated.toLocaleTimeString()}
            </span>
          )}
          <button
            onClick={refreshAll}
            disabled={portfolio.loading}
            className="px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 disabled:bg-gray-700
                       text-sm rounded font-medium transition-colors"
          >
            {portfolio.loading ? "Loading..." : "Refresh"}
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="md:col-span-2">
          <PortfolioSummary data={portfolio.data} />
        </div>
        <PostureCard data={portfolio.data} />
      </div>

      <PositionsTable positions={portfolio.data?.positions ?? []} />

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <SignalsPanel data={signals.data} />
        <AlertsPanel alerts={alerts.data ?? []} />
      </div>

      {portfolio.error && (
        <div className="text-red-400 text-sm">Error: {portfolio.error}</div>
      )}
    </div>
  );
}
```

**Step 7: Verify build**

```bash
cd /Users/jasonljc/trading/dashboard/ui && npm run build
```

Expected: Build succeeds

**Step 8: Commit**

```bash
cd /Users/jasonljc/trading && git add dashboard/ui/ && git commit -m "feat: Live Overview page with 5 components"
```

---

### Task 6: Analytics page components (Page 2)

**Files:**
- Create: `dashboard/ui/src/components/EquityCurve.tsx`
- Create: `dashboard/ui/src/components/TradesTable.tsx`
- Create: `dashboard/ui/src/components/HealthPanel.tsx`
- Create: `dashboard/ui/src/components/RegimePanel.tsx`
- Modify: `dashboard/ui/src/pages/Analytics.tsx`

**Step 1: Write `EquityCurve.tsx`**

```tsx
// dashboard/ui/src/components/EquityCurve.tsx
import { useEffect, useRef } from "react";
import { createChart, IChartApi, LineSeries } from "lightweight-charts";

interface Props {
  data: any[];
}

export default function EquityCurve({ data }: Props) {
  const chartRef = useRef<HTMLDivElement>(null);
  const chartInstance = useRef<IChartApi | null>(null);

  useEffect(() => {
    if (!chartRef.current || !data || data.length === 0) return;

    if (chartInstance.current) {
      chartInstance.current.remove();
    }

    const chart = createChart(chartRef.current, {
      width: chartRef.current.clientWidth,
      height: 300,
      layout: { background: { color: "#111827" }, textColor: "#9ca3af" },
      grid: { vertLines: { color: "#1f2937" }, horzLines: { color: "#1f2937" } },
      timeScale: { borderColor: "#374151" },
      rightPriceScale: { borderColor: "#374151" },
    });

    const series = chart.addSeries(LineSeries, {
      color: "#10b981",
      lineWidth: 2,
    });

    const points = data.map((entry: any) => ({
      time: entry.payload?.date || entry.timestamp?.slice(0, 10),
      value: entry.payload?.equity_usd ?? 0,
    }));

    series.setData(points);
    chart.timeScale().fitContent();
    chartInstance.current = chart;

    const handleResize = () => {
      if (chartRef.current) {
        chart.applyOptions({ width: chartRef.current.clientWidth });
      }
    };
    window.addEventListener("resize", handleResize);
    return () => {
      window.removeEventListener("resize", handleResize);
      chart.remove();
    };
  }, [data]);

  return (
    <div className="bg-gray-900 rounded-lg p-4 border border-gray-800">
      <h2 className="text-sm font-medium text-gray-400 mb-3">Equity Curve</h2>
      {(!data || data.length === 0) ? (
        <div className="text-gray-500 text-sm">No equity data yet</div>
      ) : (
        <div ref={chartRef} />
      )}
    </div>
  );
}
```

**Step 2: Write `TradesTable.tsx`**

```tsx
// dashboard/ui/src/components/TradesTable.tsx
interface Props {
  trades: any[];
}

export default function TradesTable({ trades }: Props) {
  return (
    <div className="bg-gray-900 rounded-lg p-4 border border-gray-800">
      <h2 className="text-sm font-medium text-gray-400 mb-3">
        Recent Trades ({trades?.length ?? 0})
      </h2>
      {(!trades || trades.length === 0) ? (
        <div className="text-gray-500 text-sm">No closed trades yet</div>
      ) : (
        <div className="overflow-x-auto max-h-80 overflow-y-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-gray-500 text-left border-b border-gray-800 sticky top-0 bg-gray-900">
                <th className="pb-2">Date</th>
                <th className="pb-2">Symbol</th>
                <th className="pb-2">Side</th>
                <th className="pb-2">Entry</th>
                <th className="pb-2">Exit</th>
                <th className="pb-2">P&L</th>
                <th className="pb-2">Strategy</th>
              </tr>
            </thead>
            <tbody>
              {trades.map((t: any, i: number) => {
                const p = t.payload ?? {};
                const pnl = p.realized_pnl_usd ?? 0;
                const positive = pnl >= 0;
                return (
                  <tr key={i} className="border-b border-gray-800/50">
                    <td className="py-2 text-gray-500 text-xs">{t.timestamp?.slice(0, 10)}</td>
                    <td className="font-medium">{p.symbol}</td>
                    <td className={p.side === "LONG" ? "text-emerald-400" : "text-red-400"}>
                      {p.side}
                    </td>
                    <td>{p.entry_price?.toLocaleString()}</td>
                    <td>{p.exit_price?.toLocaleString()}</td>
                    <td className={positive ? "text-emerald-400" : "text-red-400"}>
                      {positive ? "+" : ""}${pnl.toLocaleString()}
                    </td>
                    <td className="text-gray-500 text-xs">{p.strategy_id}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
```

**Step 3: Write `HealthPanel.tsx`**

```tsx
// dashboard/ui/src/components/HealthPanel.tsx
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from "recharts";

interface Props {
  data: Record<string, any>;
}

export default function HealthPanel({ data }: Props) {
  if (!data || Object.keys(data).length === 0) {
    return (
      <div className="bg-gray-900 rounded-lg p-4 border border-gray-800">
        <h2 className="text-sm font-medium text-gray-400 mb-3">Strategy Health</h2>
        <div className="text-gray-500 text-sm">No strategy data</div>
      </div>
    );
  }

  const strategies = Object.entries(data).map(([sid, cfg]: [string, any]) => ({
    name: sid.replace(/_/g, " ").replace(/^\w/, (c: string) => c.toUpperCase()),
    sid,
    status: cfg.status ?? "?",
    incubating: cfg.incubation?.is_incubating ?? false,
    incubPct: cfg.incubation?.incubation_size_pct ?? 0,
  }));

  return (
    <div className="bg-gray-900 rounded-lg p-4 border border-gray-800">
      <h2 className="text-sm font-medium text-gray-400 mb-3">Strategy Health</h2>
      <div className="space-y-2 max-h-80 overflow-y-auto">
        {strategies.map((s) => (
          <div key={s.sid} className="flex items-center justify-between text-sm">
            <div className="flex items-center gap-2">
              <span className={`w-2 h-2 rounded-full ${
                s.status === "ACTIVE" ? "bg-emerald-400" :
                s.status === "DISABLED" ? "bg-red-400" : "bg-gray-500"
              }`} />
              <span className="text-gray-300 text-xs">{s.sid}</span>
            </div>
            <div className="flex items-center gap-2">
              {s.incubating && (
                <span className="text-xs px-1.5 py-0.5 bg-yellow-500/20 text-yellow-400 rounded">
                  INCUB {s.incubPct}%
                </span>
              )}
              <span className={`text-xs ${
                s.status === "ACTIVE" ? "text-emerald-400" : "text-gray-500"
              }`}>
                {s.status}
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
```

**Step 4: Write `RegimePanel.tsx`**

```tsx
// dashboard/ui/src/components/RegimePanel.tsx
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from "recharts";

interface Props {
  data: Record<string, any>;
}

const REGIME_COLORS: Record<string, string> = {
  TRENDING: "#10b981",
  VOLATILE: "#ef4444",
  NEUTRAL: "#6b7280",
  MEAN_REVERTING: "#3b82f6",
  RANGE_BOUND: "#8b5cf6",
};

export default function RegimePanel({ data }: Props) {
  if (!data || Object.keys(data).length === 0) {
    return (
      <div className="bg-gray-900 rounded-lg p-4 border border-gray-800">
        <h2 className="text-sm font-medium text-gray-400 mb-3">Regime State</h2>
        <div className="text-gray-500 text-sm">No regime data</div>
      </div>
    );
  }

  const chartData = Object.entries(data).map(([sym, r]: [string, any]) => ({
    symbol: sym,
    score: r.score ?? 0,
    regime: r.regime_type ?? "?",
    driver: r.vol_driver ?? "?",
    value: r.vol_value ?? 0,
  }));

  return (
    <div className="bg-gray-900 rounded-lg p-4 border border-gray-800">
      <h2 className="text-sm font-medium text-gray-400 mb-3">Regime State</h2>
      <ResponsiveContainer width="100%" height={200}>
        <BarChart data={chartData}>
          <XAxis dataKey="symbol" tick={{ fill: "#9ca3af", fontSize: 12 }} />
          <YAxis tick={{ fill: "#9ca3af", fontSize: 12 }} domain={[0, 100]} />
          <Tooltip
            contentStyle={{ backgroundColor: "#1f2937", border: "1px solid #374151", borderRadius: 8 }}
            labelStyle={{ color: "#e5e7eb" }}
            formatter={(value: number, _: any, entry: any) => [
              `${value} (${entry.payload.regime})`,
              "Score",
            ]}
          />
          <Bar dataKey="score" radius={[4, 4, 0, 0]}>
            {chartData.map((entry, i) => (
              <Cell key={i} fill={REGIME_COLORS[entry.regime] ?? "#6b7280"} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
      <div className="grid grid-cols-2 md:grid-cols-5 gap-2 mt-3">
        {chartData.map((d) => (
          <div key={d.symbol} className="text-center text-xs">
            <div className="font-medium">{d.symbol}</div>
            <div style={{ color: REGIME_COLORS[d.regime] ?? "#6b7280" }}>{d.regime}</div>
            <div className="text-gray-500">{d.driver}: {d.value}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
```

**Step 5: Wire up `Analytics.tsx`**

```tsx
// dashboard/ui/src/pages/Analytics.tsx
import { useCallback } from "react";
import { useApi } from "../hooks/useApi";
import { fetchEquityCurve, fetchTrades, fetchHealth, fetchRegime } from "../api";
import EquityCurve from "../components/EquityCurve";
import TradesTable from "../components/TradesTable";
import HealthPanel from "../components/HealthPanel";
import RegimePanel from "../components/RegimePanel";

export default function Analytics() {
  const equity = useApi(useCallback(() => fetchEquityCurve(30), []));
  const trades = useApi(useCallback(() => fetchTrades(50), []));
  const health = useApi(useCallback(() => fetchHealth(), []));
  const regime = useApi(useCallback(() => fetchRegime(), []));

  const refreshAll = () => {
    equity.refresh();
    trades.refresh();
    health.refresh();
    regime.refresh();
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold">Analytics</h1>
        <div className="flex items-center gap-3">
          {equity.lastUpdated && (
            <span className="text-xs text-gray-500">
              Updated: {equity.lastUpdated.toLocaleTimeString()}
            </span>
          )}
          <button
            onClick={refreshAll}
            disabled={equity.loading}
            className="px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 disabled:bg-gray-700
                       text-sm rounded font-medium transition-colors"
          >
            {equity.loading ? "Loading..." : "Refresh"}
          </button>
        </div>
      </div>

      <EquityCurve data={equity.data ?? []} />

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <TradesTable trades={trades.data ?? []} />
        <HealthPanel data={health.data ?? {}} />
      </div>

      <RegimePanel data={regime.data ?? {}} />
    </div>
  );
}
```

**Step 6: Verify build**

```bash
cd /Users/jasonljc/trading/dashboard/ui && npm run build
```

Expected: Build succeeds

**Step 7: Commit**

```bash
cd /Users/jasonljc/trading && git add dashboard/ui/ && git commit -m "feat: Analytics page with equity curve, trades, health, regime"
```

---

### Task 7: Docker setup

**Files:**
- Create: `dashboard/api/Dockerfile`
- Create: `dashboard/ui/Dockerfile`
- Create: `dashboard/ui/nginx.conf`
- Create: `dashboard/docker-compose.dashboard.yaml`

**Step 1: Write `dashboard/api/Dockerfile`**

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY ../shared/ /app/shared/
COPY ../strategies/ /app/strategies/
COPY ../params/ /app/params/
COPY ../openclaw_trader/ /app/openclaw_trader/
COPY api/ /app/dashboard/api/
ENV PYTHONPATH=/app
CMD ["uvicorn", "dashboard.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Step 2: Write `dashboard/ui/nginx.conf`**

```nginx
server {
    listen 80;
    root /usr/share/nginx/html;
    index index.html;

    location /api {
        proxy_pass http://dashboard-api:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

**Step 3: Write `dashboard/ui/Dockerfile`**

```dockerfile
FROM node:20-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
```

**Step 4: Write `dashboard/docker-compose.dashboard.yaml`**

```yaml
# Usage: docker-compose -f docker-compose.yaml -f dashboard/docker-compose.dashboard.yaml up
services:
  dashboard-api:
    build:
      context: .
      dockerfile: dashboard/api/Dockerfile
    ports:
      - "8000:8000"
    volumes:
      - ../data:/app/data:ro
    environment:
      - OPENCLAW_DATA=/app/data
      - OPENCLAW_STRATEGIES=/app/strategies
      - OPENCLAW_PARAMS=/app/params
      - REDIS_URL=redis://redis:6379
      - TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN:-}
      - TELEGRAM_CHAT_ID=${TELEGRAM_CHAT_ID:-}
    depends_on:
      - redis

  dashboard-ui:
    build:
      context: dashboard/ui
      dockerfile: Dockerfile
    ports:
      - "3000:80"
    depends_on:
      - dashboard-api
```

**Step 5: Commit**

```bash
cd /Users/jasonljc/trading && git add dashboard/ && git commit -m "feat: Docker setup for dashboard API and UI"
```

---

### Task 8: Run all tests and verify

**Step 1: Install backend dependencies**

```bash
pip install fastapi uvicorn python-telegram-bot httpx
```

Note: `httpx` is required by FastAPI's `TestClient`.

**Step 2: Run all existing tests (regression check)**

```bash
cd /Users/jasonljc/trading && python3 -m pytest tests/ openclaw_trader/tests/ -v --tb=short
```

Expected: 419 tests PASS

**Step 3: Run dashboard backend tests**

```bash
cd /Users/jasonljc/trading && python3 -m pytest dashboard/api/tests/ -v --tb=short
```

Expected: ~29 tests PASS

**Step 4: Run full combined suite**

```bash
cd /Users/jasonljc/trading && python3 -m pytest tests/ openclaw_trader/tests/ dashboard/api/tests/ -v --tb=short
```

Expected: ~448 tests PASS

**Step 5: Verify frontend builds**

```bash
cd /Users/jasonljc/trading/dashboard/ui && npm run build
```

Expected: Build succeeds

**Step 6: Fix any issues found**

**Step 7: Commit if any fixes were needed**

```bash
git add -A && git commit -m "fix: resolve test/build issues"
```
