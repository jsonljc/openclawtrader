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
