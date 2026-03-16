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
