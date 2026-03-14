#!/usr/bin/env python3
"""Unit tests for health.py — strategy health scoring and action thresholds.

Covers:
  - evaluate_strategy_health(): with < 3 trades (capped)
  - evaluate_strategy_health(): with sufficient trades
  - Health action thresholds: NORMAL, HALF_SIZE, DISABLE
  - Component weights: DD, Sharpe, hit rate, execution quality
"""

from __future__ import annotations
import os
import sys
import json
import importlib
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "workspace-c3po"))

from shared import contracts as C
from shared import ledger
from shared import state_store as store


@pytest.fixture(autouse=True)
def _isolate(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    params_dir = tmp_path / "params"
    params_dir.mkdir()
    os.environ["OPENCLAW_DATA"] = str(data_dir)
    os.environ["OPENCLAW_STRATEGIES"] = str(tmp_path / "strategies")
    os.environ["OPENCLAW_PARAMS"] = str(params_dir)
    importlib.reload(store)
    importlib.reload(ledger)
    ledger._cached_last_seq = None
    ledger._cached_last_checksum = None
    # Write params
    with open(params_dir / "PV_0001.json", "w") as f:
        json.dump({
            "param_version": "PV_0001",
            "health": {
                "weight_dd": 0.35, "weight_sharpe": 0.25,
                "weight_hit_rate": 0.20, "weight_execution": 0.20,
                "min_trades_for_full_health": 10,
                "disable_threshold": 0.30, "half_size_threshold": 0.50,
            },
            "regime": {}, "sentinel": {}, "sizing": {}, "overnight": {}, "slippage": {},
        }, f)
    # Write portfolio
    with open(data_dir / "portfolio.json", "w") as f:
        json.dump({
            "asof": "2026-03-14T12:00:00Z", "param_version": "PV_0001",
            "account": {"equity_usd": 100000.0, "peak_equity_usd": 100000.0,
                         "cash_usd": 100000.0, "margin_used_usd": 0.0,
                         "margin_available_usd": 100000.0, "margin_utilization_pct": 0.0},
            "pnl": {}, "positions": [],
            "heat": {"total_open_risk_usd": 0.0, "total_open_risk_pct": 0.0,
                     "cluster_exposure": {}, "correlations_20d": {}},
            "sentinel_posture": "NORMAL",
        }, f)


from health import evaluate_strategy_health


def _strategy(**kw):
    base = {
        "strategy_id": "trend_reclaim_4H_ES",
        "expected_max_dd_pct": 10.0,
        "expected_sharpe": 0.7,
        "expected_hit_rate": 0.45,
        "expected_avg_slippage_ticks": 1.0,
    }
    base.update(kw)
    return base


def _make_closes(pnls, strategy_id="trend_reclaim_4H_ES"):
    now = datetime.now(timezone.utc)
    events = []
    for i, pnl in enumerate(pnls):
        events.append({
            "event_type": C.EventType.POSITION_CLOSED,
            "timestamp": (now - timedelta(days=len(pnls) - i)).isoformat(),
            "payload": {"strategy_id": strategy_id, "realized_pnl": pnl},
        })
    return events


# ── Insufficient trades ──

class TestInsufficientTrades:
    @patch.object(ledger, "query", return_value=[])
    def test_zero_trades_returns_capped_score(self, mock_query):
        result = evaluate_strategy_health(_strategy())
        assert result["health_score"] == pytest.approx(0.60, abs=0.01)
        assert result["action"] == C.HealthAction.NORMAL

    @patch.object(ledger, "query")
    def test_two_trades_capped(self, mock_query):
        mock_query.return_value = _make_closes([100, -50])
        result = evaluate_strategy_health(_strategy())
        assert result["health_score"] == pytest.approx(0.60, abs=0.01)

    @patch.object(ledger, "query", return_value=[])
    def test_stats_populated_with_defaults(self, mock_query):
        result = evaluate_strategy_health(_strategy())
        assert result["stats"]["trade_count_30d"] == 0
        assert result["stats"]["realized_dd_pct"] == 0.0


# ── Sufficient trades ──

class TestSufficientTrades:
    @patch("health.store.load_exec_quality", return_value={})
    @patch.object(ledger, "query")
    def test_winning_strategy_high_score(self, mock_query, mock_eq):
        pnls = [200, 150, -50, 180, 200, -30, 250, 100, 150, -40, 200, 180, 120, 150, -20]
        mock_query.return_value = _make_closes(pnls)
        result = evaluate_strategy_health(_strategy())
        assert result["health_score"] > 0.60
        assert result["action"] == C.HealthAction.NORMAL

    @patch("health.store.load_exec_quality", return_value={})
    @patch.object(ledger, "query")
    def test_losing_strategy_low_score(self, mock_query, mock_eq):
        # Mostly losing trades
        pnls = [-200, -150, 50, -180, -200, 30, -250, -100, -150, 40, -200, -180]
        mock_query.return_value = _make_closes(pnls)
        result = evaluate_strategy_health(_strategy())
        assert result["health_score"] < 0.65

    @patch("health.store.load_exec_quality", return_value={})
    @patch.object(ledger, "query")
    def test_stats_populated(self, mock_query, mock_eq):
        pnls = [100, -50, 100, -50, 100, -50, 100, -50, 100, -50, 100, -50]
        mock_query.return_value = _make_closes(pnls)
        result = evaluate_strategy_health(_strategy())
        assert result["stats"]["trade_count_30d"] == 12
        assert result["stats"]["realized_hit_rate_30d"] > 0
        assert result["stats"]["profit_factor_30d"] > 0


# ── Action thresholds ──

class TestActionThresholds:
    @patch("health.store.load_exec_quality", return_value={})
    @patch.object(ledger, "query")
    def test_disable_on_terrible_performance(self, mock_query, mock_eq):
        pnls = [-500] * 15
        mock_query.return_value = _make_closes(pnls)
        result = evaluate_strategy_health(_strategy())
        assert result["action"] in (C.HealthAction.HALF_SIZE, C.HealthAction.DISABLE)

    @patch("health.store.load_exec_quality", return_value={})
    @patch.object(ledger, "query")
    def test_normal_on_good_performance(self, mock_query, mock_eq):
        pnls = [200, 150, 100, 180, 200, -30, 250, 100, 150, -40, 200, 180, 120, 150, -20]
        mock_query.return_value = _make_closes(pnls)
        result = evaluate_strategy_health(_strategy())
        assert result["action"] == C.HealthAction.NORMAL


# ── Capped score below min_trades ──

class TestCappedScore:
    @patch("health.store.load_exec_quality", return_value={})
    @patch.object(ledger, "query")
    def test_few_trades_capped_at_060(self, mock_query, mock_eq):
        pnls = [200, 300, 150, 200, 100]
        mock_query.return_value = _make_closes(pnls)
        result = evaluate_strategy_health(_strategy())
        assert result["health_score"] <= 0.60
        assert result["health_score_capped"] is True


# ── Strategy ID filtering ──

class TestStrategyFiltering:
    @patch("health.store.load_exec_quality", return_value={})
    @patch.object(ledger, "query")
    def test_only_matching_strategy_used(self, mock_query, mock_eq):
        events = _make_closes([100, 200, 300], "trend_reclaim_4H_ES")
        events += _make_closes([-500, -500, -500], "other_strategy")
        mock_query.return_value = events
        result = evaluate_strategy_health(_strategy(strategy_id="trend_reclaim_4H_ES"))
        assert result["stats"]["trade_count_30d"] == 3
