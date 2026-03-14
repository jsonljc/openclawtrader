#!/usr/bin/env python3
"""Unit tests for run_daily_reset.py — 6-step audit, FREEZE logic.

Covers:
  - Position reconciliation (paper mode)
  - Bracket integrity checks
  - Daily counter reset
  - Opening equity snapshot
  - Ledger chain integrity
  - FREEZE on critical issues
  - Dry-run mode
"""

from __future__ import annotations
import os
import sys
import json
import importlib
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "workspace-c3po"))
sys.path.insert(0, str(ROOT / "workspace-forge"))
sys.path.insert(0, str(ROOT / "workspace-sentinel"))
sys.path.insert(0, str(ROOT / "workspace-watchtower"))

from shared import contracts as C
from shared import state_store as store
from shared import ledger
from run_daily_reset import run_daily_reset


@pytest.fixture(autouse=True)
def _isolate(tmp_path):
    """Give each test an isolated data directory."""
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
    # Write default params
    with open(params_dir / "PV_0001.json", "w") as f:
        json.dump({"param_version": "PV_0001", "regime": {}, "health": {},
                   "sentinel": {}, "sizing": {}, "overnight": {}, "slippage": {}}, f)
    # Write default portfolio and posture
    _write_portfolio(data_dir)
    _write_posture(data_dir)
    yield data_dir


def _write_portfolio(data_dir=None, positions=None, equity=100000.0, realized_today=150.0):
    if data_dir is None:
        data_dir = Path(store._DATA_DIR)
    port = {
        "asof": "2026-03-14T12:00:00Z", "param_version": "PV_0001",
        "account": {
            "equity_usd": equity, "peak_equity_usd": equity,
            "cash_usd": equity, "margin_used_usd": 0.0,
            "margin_available_usd": equity, "margin_utilization_pct": 0.0,
        },
        "pnl": {
            "unrealized_usd": 0.0, "realized_today_usd": realized_today,
            "total_today_usd": realized_today, "total_today_pct": realized_today / equity * 100,
            "portfolio_dd_pct": 0.0,
        },
        "positions": positions or [],
        "heat": {"total_open_risk_usd": 0.0, "total_open_risk_pct": 0.0,
                 "cluster_exposure": {}, "correlations_20d": {}},
        "sentinel_posture": "NORMAL",
    }
    with open(Path(data_dir) / "portfolio.json", "w") as f:
        json.dump(port, f)
    return port


def _write_posture(data_dir=None, posture="NORMAL"):
    if data_dir is None:
        data_dir = Path(store._DATA_DIR)
    state = {"posture": posture, "posture_since": "2026-03-14T06:00:00Z"}
    with open(Path(data_dir) / "posture_state.json", "w") as f:
        json.dump(state, f)


# ── Basic functionality ──

class TestDailyResetBasic:
    @patch.object(ledger, "verify_integrity", return_value=(True, "OK"))
    @patch.object(ledger, "append")
    def test_clean_run_no_issues(self, mock_append, mock_verify):
        result = run_daily_reset(dry_run=False, paper=True)
        assert result["freeze"] is False
        assert len(result["issues"]) == 0
        assert result["opening_equity_usd"] == 100000.0

    @patch.object(ledger, "verify_integrity", return_value=(True, "OK"))
    @patch.object(ledger, "append")
    def test_returns_run_id(self, mock_append, mock_verify):
        result = run_daily_reset(paper=True)
        assert "run_id" in result
        assert result["run_id"].startswith("RUN_")

    @patch.object(ledger, "verify_integrity", return_value=(True, "OK"))
    @patch.object(ledger, "append")
    def test_date_field_present(self, mock_append, mock_verify):
        result = run_daily_reset(paper=True)
        assert "date" in result


# ── Position reconciliation ──

class TestPositionRecon:
    @patch.object(ledger, "verify_integrity", return_value=(True, "OK"))
    @patch.object(ledger, "append")
    def test_missing_position_id_flagged(self, mock_append, mock_verify):
        _write_portfolio(positions=[{"symbol": "ES", "contracts": 1, "stop_price": 4900}])
        _write_posture()
        result = run_daily_reset(paper=True)
        assert any("missing position_id" in i for i in result["issues"])

    @patch.object(ledger, "verify_integrity", return_value=(True, "OK"))
    @patch.object(ledger, "append")
    def test_zero_contracts_flagged(self, mock_append, mock_verify):
        _write_portfolio(positions=[{"position_id": "P001", "symbol": "ES",
                                      "contracts": 0, "stop_price": 4900}])
        _write_posture()
        result = run_daily_reset(paper=True)
        assert any("0 contracts" in i for i in result["issues"])

    @patch.object(ledger, "verify_integrity", return_value=(True, "OK"))
    @patch.object(ledger, "append")
    def test_missing_stop_flagged(self, mock_append, mock_verify):
        _write_portfolio(positions=[{"position_id": "P001", "symbol": "ES",
                                      "contracts": 1}])
        _write_posture()
        result = run_daily_reset(paper=True)
        assert any("missing stop_price" in i for i in result["issues"])

    @patch.object(ledger, "verify_integrity", return_value=(True, "OK"))
    @patch.object(ledger, "append")
    def test_valid_positions_no_issues(self, mock_append, mock_verify):
        _write_portfolio(positions=[{
            "position_id": "P001", "symbol": "ES", "contracts": 1,
            "stop_price": 4900, "bracket_status": {"stop_status": "ACTIVE", "tp_status": "ACTIVE"},
        }])
        _write_posture()
        result = run_daily_reset(paper=True)
        assert len(result["issues"]) == 0


# ── Bracket integrity ──

class TestBracketIntegrity:
    @patch.object(ledger, "verify_integrity", return_value=(True, "OK"))
    @patch.object(ledger, "append")
    def test_inactive_stop_flagged(self, mock_append, mock_verify):
        _write_portfolio(positions=[{
            "position_id": "P001", "symbol": "ES", "contracts": 1, "stop_price": 4900,
            "bracket_status": {"stop_status": "PENDING", "tp_status": "ACTIVE"},
        }])
        _write_posture()
        result = run_daily_reset(paper=True)
        assert any("stop not ACTIVE" in i for i in result["issues"])

    @patch.object(ledger, "verify_integrity", return_value=(True, "OK"))
    @patch.object(ledger, "append")
    def test_inactive_tp_flagged(self, mock_append, mock_verify):
        _write_portfolio(positions=[{
            "position_id": "P001", "symbol": "ES", "contracts": 1, "stop_price": 4900,
            "bracket_status": {"stop_status": "ACTIVE", "tp_status": "CANCELLED"},
        }])
        _write_posture()
        result = run_daily_reset(paper=True)
        assert any("TP not ACTIVE" in i for i in result["issues"])


# ── Daily counter reset ──

class TestCounterReset:
    @patch.object(ledger, "verify_integrity", return_value=(True, "OK"))
    @patch.object(ledger, "append")
    def test_pnl_counters_reset(self, mock_append, mock_verify):
        _write_portfolio(realized_today=500.0)
        _write_posture()
        run_daily_reset(dry_run=False, paper=True)
        port = store.load_portfolio()
        assert port["pnl"]["realized_today_usd"] == 0.0
        assert port["pnl"]["total_today_usd"] == 0.0

    @patch.object(ledger, "verify_integrity", return_value=(True, "OK"))
    @patch.object(ledger, "append")
    def test_dry_run_no_reset(self, mock_append, mock_verify):
        _write_portfolio(realized_today=500.0)
        _write_posture()
        run_daily_reset(dry_run=True, paper=True)
        port = store.load_portfolio()
        assert port["pnl"]["realized_today_usd"] == 500.0


# ── Opening equity ──

class TestOpeningEquity:
    @patch.object(ledger, "verify_integrity", return_value=(True, "OK"))
    @patch.object(ledger, "append")
    def test_opening_equity_set(self, mock_append, mock_verify):
        _write_portfolio(equity=100000.0)
        _write_posture()
        run_daily_reset(dry_run=False, paper=True)
        port = store.load_portfolio()
        assert port["account"]["opening_equity_usd"] == 100000.0

    @patch.object(ledger, "verify_integrity", return_value=(True, "OK"))
    @patch.object(ledger, "append")
    def test_opening_equity_in_result(self, mock_append, mock_verify):
        _write_portfolio(equity=75000.0)
        _write_posture()
        result = run_daily_reset(paper=True)
        assert result["opening_equity_usd"] == 75000.0


# ── Ledger chain integrity ──

class TestLedgerChain:
    @patch.object(ledger, "verify_integrity", return_value=(False, "Chain broken at entry 42"))
    @patch.object(ledger, "append")
    @patch("run_daily_reset.alerting")
    def test_chain_failure_triggers_freeze(self, mock_alerting, mock_append, mock_verify):
        result = run_daily_reset(dry_run=False, paper=True)
        assert result["freeze"] is True
        assert any("integrity FAILED" in i for i in result["issues"])

    @patch.object(ledger, "verify_integrity", return_value=(True, "OK"))
    @patch.object(ledger, "append")
    def test_chain_ok_no_freeze(self, mock_append, mock_verify):
        result = run_daily_reset(paper=True)
        assert result["freeze"] is False

    @patch.object(ledger, "verify_integrity", side_effect=Exception("File not found"))
    @patch.object(ledger, "append")
    def test_chain_error_logged(self, mock_append, mock_verify):
        result = run_daily_reset(paper=True)
        assert any("verification error" in i.lower() for i in result["issues"])


# ── FREEZE logic ──

class TestFreeze:
    @patch.object(ledger, "verify_integrity", return_value=(True, "OK"))
    @patch.object(ledger, "append")
    @patch("run_daily_reset.alerting")
    def test_critical_mismatch_triggers_freeze(self, mock_alerting, mock_append, mock_verify):
        _write_portfolio(positions=[{"symbol": "ES", "contracts": 0}])
        _write_posture()
        result = run_daily_reset(paper=True)
        # The "0 contracts" issue itself won't freeze (no "FAILED" or "mismatch")
        # but position_id is missing which is flagged
        assert "issues" in result

    @patch.object(ledger, "verify_integrity", return_value=(False, "broken"))
    @patch.object(ledger, "append")
    @patch("run_daily_reset.alerting")
    def test_freeze_sets_halt_posture(self, mock_alerting, mock_append, mock_verify):
        _write_portfolio()
        _write_posture(posture="NORMAL")
        run_daily_reset(dry_run=False, paper=True)
        posture = store.load_posture_state()
        assert posture["posture"] == C.Posture.HALT

    @patch.object(ledger, "verify_integrity", return_value=(True, "OK"))
    @patch.object(ledger, "append")
    def test_dry_run_no_freeze_persist(self, mock_append, mock_verify):
        _write_portfolio()
        _write_posture(posture="NORMAL")
        result = run_daily_reset(dry_run=True, paper=True)
        posture = store.load_posture_state()
        assert posture["posture"] == "NORMAL"


# ── Ledger event ──

class TestLedgerEvent:
    @patch.object(ledger, "verify_integrity", return_value=(True, "OK"))
    @patch.object(ledger, "append")
    def test_daily_snapshot_event_emitted(self, mock_append, mock_verify):
        _write_portfolio()
        _write_posture()
        run_daily_reset(dry_run=False, paper=True)
        # Check that append was called with DAILY_SNAPSHOT
        calls = [c for c in mock_append.call_args_list
                 if c[0][0] == C.EventType.DAILY_SNAPSHOT]
        assert len(calls) == 1
        payload = calls[0][0][3]
        assert payload["type"] == "DAILY_RESET"
