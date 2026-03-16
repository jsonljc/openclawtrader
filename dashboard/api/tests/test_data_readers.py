# dashboard/api/tests/test_data_readers.py
"""Tests for data_readers -- shared read logic for dashboard."""
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
