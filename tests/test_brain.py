#!/usr/bin/env python3
"""Unit tests for C3PO brain.py — signal generation, gate checks, sizing, roll logic.

Covers:
  - _check_gates(): All 9 gates + Gate 6.5 (event suppression)
  - _evaluate_trend_reclaim_4H(): LONG/SHORT/no-signal conditions
  - _suggest_sizing(): risk budget, regime/health/session/incubation modifiers, micro fallback
  - _build_intent(): intent structure, field population
  - _roll_decision_tree(): profitable→ROLL, big loss→CLOSE, regime-gated
  - _build_roll_intent(): roll intent structure
  - run_brain(): end-to-end orchestration
"""

from __future__ import annotations
import os
import sys
import json
import importlib
import math
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Isolated data dirs
import tempfile
_test_data_dir = tempfile.mkdtemp(prefix="brain_test_")
os.environ["OPENCLAW_DATA"] = _test_data_dir
os.environ["OPENCLAW_STRATEGIES"] = os.path.join(_test_data_dir, "strategies")
os.environ["OPENCLAW_PARAMS"] = os.path.join(_test_data_dir, "params")

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "workspace-c3po"))
sys.path.insert(0, str(ROOT / "workspace-sentinel"))
sys.path.insert(0, str(ROOT / "workspace-forge"))

from shared import contracts as C
from shared import ledger
from shared import state_store as store

from brain import (
    _check_gates,
    _evaluate_trend_reclaim_4H,
    _suggest_sizing,
    _build_intent,
    _build_roll_intent,
    _roll_decision_tree,
    run_brain,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _isolate(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    strat_dir = tmp_path / "strategies"
    strat_dir.mkdir()
    params_dir = tmp_path / "params"
    params_dir.mkdir()
    os.environ["OPENCLAW_DATA"] = str(data_dir)
    os.environ["OPENCLAW_STRATEGIES"] = str(strat_dir)
    os.environ["OPENCLAW_PARAMS"] = str(params_dir)
    importlib.reload(store)
    importlib.reload(ledger)
    ledger._cached_last_seq = None
    ledger._cached_last_checksum = None


def _strategy(overrides=None):
    s = {
        "strategy_id": "trend_reclaim_4H_ES",
        "symbol": "ES",
        "micro_symbol": "MES",
        "tick_size": 0.25,
        "tick_value_usd": 12.50,
        "point_value_usd": 50.0,
        "micro_point_value_usd": 5.0,
        "micro_tick_value_usd": 1.25,
        "margin_per_contract_usd": 15840.0,
        "micro_margin_per_contract_usd": 1584.0,
        "micro_available": True,
        "correlation_group": "equity_index",
        "risk_budget_pct": 0.5,
        "timeframe": "4H",
        "status": C.StrategyStatus.ACTIVE,
        "min_health_score": 0.30,
        "contract_month": "ESH6",
        "roll_days_before_expiry": 5,
        "signal": {
            "adx_min": 25,
            "stop_atr_multiple": 1.5,
            "tp_atr_multiple": 1.5,
        },
    }
    if overrides:
        s.update(overrides)
    return s


def _snapshot(price=5000.0, ma20=4990.0, adx=30.0, ma_slope=0.5, atr_4h=40.0,
              session=C.SessionState.CORE, stale=False):
    return {
        "indicators": {
            "last_price": price,
            "ma_20_value": ma20,
            "ma_50_value": 4950.0,
            "adx_14": adx,
            "ma_20_slope": ma_slope,
            "atr_14_4H": atr_4h,
            "atr_14_1H": 15.0,
        },
        "bars": {"1H": [{"o": price, "h": price + 10, "l": price - 10, "c": price}]},
        "session_state": session,
        "external": {"vix_percentile_252d": 0.5},
        "microstructure": {"avg_book_depth_contracts": 850},
        "data_quality": {"is_stale": stale},
        "contract": {"days_to_expiry": 30},
    }


def _portfolio(equity=100_000):
    return {
        "account": {
            "equity_usd": equity,
            "margin_used_usd": 0.0,
            "margin_available_usd": equity,
        },
        "pnl": {"total_today_pct": 0.0, "portfolio_dd_pct": 0.0},
        "positions": [],
        "heat": {"total_open_risk_usd": 0.0, "cluster_exposure": {}, "correlations_20d": {}},
    }


def _health(score=0.70, action=C.HealthAction.NORMAL):
    return {"health_score": score, "action": action}


def _regime(score=0.65, multiplier=0.85):
    return {
        "report_id": "REG_test",
        "regime_score": score,
        "effective_regime_score": score,
        "risk_multiplier": multiplier,
    }


def _no_suppression(*args, **kwargs):
    return {"suppressed": False, "event_name": None, "tier": None, "minutes_to_event": None}


def _suppressed(*args, **kwargs):
    return {"suppressed": True, "event_name": "FOMC", "tier": 1, "minutes_to_event": 10.0}


# ===================================================================
# _check_gates()
# ===================================================================

class TestCheckGates:
    def _run(self, strategy=None, health=None, snapshot=None, portfolio=None,
             posture="NORMAL", wt_status="HEALTHY", regime=None, suppression_fn=None):
        strategy = strategy or _strategy()
        health = health or _health()
        snapshot = snapshot or _snapshot()
        portfolio = portfolio or _portfolio()
        regime = regime or _regime()
        with patch("brain.check_event_suppression", suppression_fn or _no_suppression):
            return _check_gates(strategy, health, snapshot, portfolio,
                                posture, wt_status, "RUN_test", regime=regime)

    def test_all_gates_pass(self):
        ok, failures = self._run()
        assert ok is True
        assert failures == []

    # --- Gate 1: Strategy status ---
    def test_gate1_cooldown_fails(self):
        ok, failures = self._run(strategy=_strategy({"status": C.StrategyStatus.COOLDOWN}))
        assert ok is False
        assert any("Gate 1" in f for f in failures)

    def test_gate1_disabled_fails(self):
        ok, failures = self._run(strategy=_strategy({"status": C.StrategyStatus.DISABLED}))
        assert ok is False
        assert any("Gate 1" in f for f in failures)

    def test_gate1_active_passes(self):
        ok, failures = self._run(strategy=_strategy({"status": C.StrategyStatus.ACTIVE}))
        assert not any("Gate 1" in f for f in failures)

    # --- Gate 2: Health score ---
    def test_gate2_low_health_fails(self):
        ok, failures = self._run(health=_health(score=0.20))
        assert ok is False
        assert any("Gate 2" in f for f in failures)

    def test_gate2_at_threshold_passes(self):
        ok, failures = self._run(health=_health(score=0.30))
        assert not any("Gate 2" in f for f in failures)

    # --- Gate 3: Health action DISABLE ---
    def test_gate3_disable_fails(self):
        ok, failures = self._run(health=_health(action=C.HealthAction.DISABLE))
        assert ok is False
        assert any("Gate 3:" in f for f in failures)

    def test_gate3_half_size_passes(self):
        ok, failures = self._run(health=_health(action=C.HealthAction.HALF_SIZE))
        assert not any("Gate 3:" in f for f in failures)

    # --- Gate 3b: Regime score too low ---
    def test_gate3b_low_regime_fails(self):
        ok, failures = self._run(regime=_regime(score=0.25))
        assert ok is False
        assert any("Gate 3b" in f for f in failures)

    def test_gate3b_regime_at_threshold_passes(self):
        ok, failures = self._run(regime=_regime(score=0.30))
        assert not any("Gate 3b" in f for f in failures)

    # --- Gate 4: Posture ---
    def test_gate4_defensive_fails(self):
        ok, failures = self._run(posture=C.Posture.DEFENSIVE)
        assert ok is False
        assert any("Gate 4" in f for f in failures)

    def test_gate4_halt_fails(self):
        ok, failures = self._run(posture=C.Posture.HALT)
        assert ok is False
        assert any("Gate 4" in f for f in failures)

    def test_gate4_caution_passes(self):
        ok, failures = self._run(posture=C.Posture.CAUTION)
        assert not any("Gate 4" in f for f in failures)

    def test_gate4_normal_passes(self):
        ok, failures = self._run(posture=C.Posture.NORMAL)
        assert not any("Gate 4" in f for f in failures)

    # --- Gate 5: Session state ---
    def test_gate5_closed_fails(self):
        ok, failures = self._run(snapshot=_snapshot(session=C.SessionState.CLOSED))
        assert ok is False
        assert any("Gate 5" in f for f in failures)

    def test_gate5_post_close_fails(self):
        ok, failures = self._run(snapshot=_snapshot(session=C.SessionState.POST_CLOSE))
        assert ok is False
        assert any("Gate 5" in f for f in failures)

    def test_gate5_pre_open_fails(self):
        ok, failures = self._run(snapshot=_snapshot(session=C.SessionState.PRE_OPEN))
        assert ok is False
        assert any("Gate 5" in f for f in failures)

    def test_gate5_core_passes(self):
        ok, failures = self._run(snapshot=_snapshot(session=C.SessionState.CORE))
        assert not any("Gate 5" in f for f in failures)

    def test_gate5_extended_passes(self):
        ok, failures = self._run(snapshot=_snapshot(session=C.SessionState.EXTENDED))
        assert not any("Gate 5" in f for f in failures)

    # --- Gate 6.5: Event suppression ---
    def test_gate65_suppressed_fails(self):
        ok, failures = self._run(suppression_fn=_suppressed)
        assert ok is False
        assert any("Gate 6.5" in f for f in failures)
        assert any("FOMC" in f for f in failures)

    def test_gate65_no_event_passes(self):
        ok, failures = self._run(suppression_fn=_no_suppression)
        assert not any("Gate 6.5" in f for f in failures)

    # --- Gate 7: Watchtower ---
    def test_gate7_halt_fails(self):
        ok, failures = self._run(wt_status=C.WatchtowerStatus.HALT)
        assert ok is False
        assert any("Gate 7" in f for f in failures)

    def test_gate7_degraded_passes(self):
        ok, failures = self._run(wt_status=C.WatchtowerStatus.DEGRADED)
        assert not any("Gate 7" in f for f in failures)

    def test_gate7_healthy_passes(self):
        ok, failures = self._run(wt_status=C.WatchtowerStatus.HEALTHY)
        assert not any("Gate 7" in f for f in failures)

    # --- Gate 8: Active position ---
    def test_gate8_existing_position_fails(self):
        portfolio = _portfolio()
        portfolio["positions"] = [{"strategy_id": "trend_reclaim_4H_ES", "symbol": "ES"}]
        ok, failures = self._run(portfolio=portfolio)
        assert ok is False
        assert any("Gate 8" in f for f in failures)

    def test_gate8_different_strategy_passes(self):
        portfolio = _portfolio()
        portfolio["positions"] = [{"strategy_id": "other_strat", "symbol": "NQ"}]
        ok, failures = self._run(portfolio=portfolio)
        assert not any("Gate 8" in f for f in failures)

    # --- Gate 9: Data freshness ---
    def test_gate9_stale_fails(self):
        ok, failures = self._run(snapshot=_snapshot(stale=True))
        assert ok is False
        assert any("Gate 9" in f for f in failures)

    def test_gate9_fresh_passes(self):
        ok, failures = self._run(snapshot=_snapshot(stale=False))
        assert not any("Gate 9" in f for f in failures)

    # --- Multiple failures ---
    def test_multiple_gates_fail(self):
        """Multiple gates can fail simultaneously."""
        ok, failures = self._run(
            posture=C.Posture.HALT,
            wt_status=C.WatchtowerStatus.HALT,
            health=_health(action=C.HealthAction.DISABLE),
        )
        assert ok is False
        assert len(failures) >= 3


# ===================================================================
# _evaluate_trend_reclaim_4H()
# ===================================================================

class TestTrendReclaim4H:
    def test_long_signal(self):
        """Price > MA20, ADX > 25, positive slope → BUY signal."""
        snap = _snapshot(price=5000.0, ma20=4990.0, adx=30.0, ma_slope=0.5, atr_4h=40.0)
        sig = _evaluate_trend_reclaim_4H(snap, _strategy())
        assert sig is not None
        assert sig["side"] == "BUY"
        assert sig["direction"] == "LONG"
        assert sig["stop_price"] < 5000.0
        assert sig["tp_price"] > 5000.0

    def test_short_signal(self):
        """Price < MA20, ADX > 25, negative slope → SELL signal."""
        snap = _snapshot(price=4980.0, ma20=4990.0, adx=30.0, ma_slope=-0.5, atr_4h=40.0)
        sig = _evaluate_trend_reclaim_4H(snap, _strategy())
        assert sig is not None
        assert sig["side"] == "SELL"
        assert sig["direction"] == "SHORT"
        assert sig["stop_price"] > 4980.0
        assert sig["tp_price"] < 4980.0

    def test_no_signal_adx_too_low(self):
        """Price > MA20 but ADX < 25 → no signal."""
        snap = _snapshot(price=5000.0, ma20=4990.0, adx=20.0, ma_slope=0.5)
        sig = _evaluate_trend_reclaim_4H(snap, _strategy())
        assert sig is None

    def test_no_signal_wrong_slope(self):
        """Price > MA20 but negative slope → no signal."""
        snap = _snapshot(price=5000.0, ma20=4990.0, adx=30.0, ma_slope=-0.5)
        sig = _evaluate_trend_reclaim_4H(snap, _strategy())
        assert sig is None

    def test_no_signal_zero_slope(self):
        """Zero slope → no signal (slope must be > 0 for LONG)."""
        snap = _snapshot(price=5000.0, ma20=4990.0, adx=30.0, ma_slope=0.0)
        sig = _evaluate_trend_reclaim_4H(snap, _strategy())
        assert sig is None

    def test_no_signal_price_equals_ma20(self):
        """Price == MA20 → neither > nor < → no signal."""
        snap = _snapshot(price=5000.0, ma20=5000.0, adx=30.0, ma_slope=0.5)
        sig = _evaluate_trend_reclaim_4H(snap, _strategy())
        assert sig is None

    def test_no_signal_missing_price(self):
        """No last_price → no signal."""
        snap = _snapshot()
        snap["indicators"]["last_price"] = None
        sig = _evaluate_trend_reclaim_4H(snap, _strategy())
        assert sig is None

    def test_no_signal_missing_ma20(self):
        """No MA20 → no signal."""
        snap = _snapshot()
        snap["indicators"]["ma_20_value"] = None
        sig = _evaluate_trend_reclaim_4H(snap, _strategy())
        assert sig is None

    def test_stop_distance_uses_atr(self):
        """Stop distance = ATR × stop_atr_multiple."""
        snap = _snapshot(price=5000.0, ma20=4990.0, adx=30.0, ma_slope=0.5, atr_4h=40.0)
        strat = _strategy()
        strat["signal"]["stop_atr_multiple"] = 2.0
        sig = _evaluate_trend_reclaim_4H(snap, strat)
        assert sig["stop_dist"] == pytest.approx(80.0, abs=0.01)

    def test_tp_distance_uses_atr(self):
        """TP distance = ATR × tp_atr_multiple."""
        snap = _snapshot(price=5000.0, ma20=4990.0, adx=30.0, ma_slope=0.5, atr_4h=40.0)
        strat = _strategy()
        strat["signal"]["tp_atr_multiple"] = 3.0
        sig = _evaluate_trend_reclaim_4H(snap, strat)
        assert sig["tp_dist"] == pytest.approx(120.0, abs=0.01)

    def test_tick_rounding(self):
        """Stop/TP prices snapped to tick grid."""
        snap = _snapshot(price=5000.0, ma20=4990.0, adx=30.0, ma_slope=0.5, atr_4h=40.0)
        sig = _evaluate_trend_reclaim_4H(snap, _strategy())
        tick = 0.25
        assert sig["stop_price"] % tick == pytest.approx(0.0, abs=1e-9)
        assert sig["tp_price"] % tick == pytest.approx(0.0, abs=1e-9)

    def test_adx_at_threshold(self):
        """ADX exactly at adx_min → signal fires."""
        snap = _snapshot(price=5000.0, ma20=4990.0, adx=25.0, ma_slope=0.5)
        sig = _evaluate_trend_reclaim_4H(snap, _strategy())
        assert sig is not None
        assert sig["side"] == "BUY"

    def test_custom_adx_min(self):
        """Custom adx_min in strategy config."""
        snap = _snapshot(price=5000.0, ma20=4990.0, adx=15.0, ma_slope=0.5)
        strat = _strategy()
        strat["signal"]["adx_min"] = 10
        sig = _evaluate_trend_reclaim_4H(snap, strat)
        assert sig is not None


# ===================================================================
# _suggest_sizing()
# ===================================================================

class TestSuggestSizing:
    def _signal(self, stop_dist=60.0, tp_dist=60.0):
        return {"stop_dist": stop_dist, "tp_dist": tp_dist, "atr_used": 40.0}

    def test_basic_sizing(self):
        """$100K equity, 0.5% risk = $500, 60pt stop × $50/pt = $3000/c → 0 full, micro fallback."""
        result = _suggest_sizing(
            _strategy(), _health(), _regime(multiplier=1.0),
            _snapshot(), self._signal(), 100_000,
        )
        # $500 / $3000 = 0 full contracts → try micro: $500 / (60 × $5) = 1.67 → 1
        assert result["contracts_suggested"] >= 1
        assert result["use_micro"] is True

    def test_large_equity_full_contracts(self):
        """$500K equity, 0.5% = $2500, 60pt × $50 = $3000 → 0 full. But 10pt stop → $500/c → 5."""
        result = _suggest_sizing(
            _strategy(), _health(), _regime(multiplier=1.0),
            _snapshot(), self._signal(stop_dist=10.0), 500_000,
        )
        # $2500 / (10 × $50) = 5
        assert result["contracts_suggested"] == 5
        assert result["use_micro"] is False

    def test_regime_modifier_reduces(self):
        """Regime multiplier 0.5 halves the risk budget."""
        full = _suggest_sizing(
            _strategy(), _health(), _regime(multiplier=1.0),
            _snapshot(), self._signal(stop_dist=10.0), 500_000,
        )
        reduced = _suggest_sizing(
            _strategy(), _health(), _regime(multiplier=0.5),
            _snapshot(), self._signal(stop_dist=10.0), 500_000,
        )
        assert reduced["contracts_suggested"] < full["contracts_suggested"]
        assert reduced["risk_multiplier_regime"] == 0.5

    def test_health_half_size(self):
        """HALF_SIZE health action halves risk."""
        full = _suggest_sizing(
            _strategy(), _health(action=C.HealthAction.NORMAL), _regime(multiplier=1.0),
            _snapshot(), self._signal(stop_dist=10.0), 500_000,
        )
        half = _suggest_sizing(
            _strategy(), _health(action=C.HealthAction.HALF_SIZE), _regime(multiplier=1.0),
            _snapshot(), self._signal(stop_dist=10.0), 500_000,
        )
        assert half["contracts_suggested"] < full["contracts_suggested"]
        assert half["risk_multiplier_health"] == 0.5

    def test_health_disable_zero_contracts(self):
        """DISABLE health → zero risk → zero contracts."""
        result = _suggest_sizing(
            _strategy(), _health(action=C.HealthAction.DISABLE), _regime(multiplier=1.0),
            _snapshot(), self._signal(stop_dist=10.0), 500_000,
        )
        assert result["contracts_suggested"] == 0

    def test_extended_session_modifier(self):
        """EXTENDED session halves the risk budget."""
        core = _suggest_sizing(
            _strategy(), _health(), _regime(multiplier=1.0),
            _snapshot(session=C.SessionState.CORE), self._signal(stop_dist=10.0), 500_000,
        )
        ext = _suggest_sizing(
            _strategy(), _health(), _regime(multiplier=1.0),
            _snapshot(session=C.SessionState.EXTENDED), self._signal(stop_dist=10.0), 500_000,
        )
        assert ext["contracts_suggested"] < core["contracts_suggested"]
        assert ext["risk_multiplier_session"] == 0.5

    def test_incubation_modifier(self):
        """Incubating strategy uses 25% of size."""
        strat = _strategy({"incubation": {"is_incubating": True, "incubation_size_pct": 25}})
        result = _suggest_sizing(
            strat, _health(), _regime(multiplier=1.0),
            _snapshot(), self._signal(stop_dist=10.0), 500_000,
        )
        # $2500 × 0.25 = $625. $625 / $500 = 1 full contract
        assert result["contracts_suggested"] == 1
        assert result["use_micro"] is False

    def test_zero_stop_dist_zero_contracts(self):
        """Zero stop distance → division by zero handled → 0 contracts."""
        result = _suggest_sizing(
            _strategy(), _health(), _regime(multiplier=1.0),
            _snapshot(), self._signal(stop_dist=0.0), 100_000,
        )
        assert result["contracts_suggested"] == 0

    def test_output_fields(self):
        """Sizing dict has all required fields."""
        result = _suggest_sizing(
            _strategy(), _health(), _regime(multiplier=1.0),
            _snapshot(), self._signal(stop_dist=10.0), 100_000,
        )
        assert "contracts_suggested" in result
        assert "use_micro" in result
        assert "final_risk_usd" in result
        assert "risk_multiplier_regime" in result
        assert "risk_multiplier_health" in result
        assert "risk_multiplier_session" in result


# ===================================================================
# _build_intent()
# ===================================================================

class TestBuildIntent:
    def test_intent_structure(self):
        """Built intent has all required fields."""
        strat = _strategy()
        snap = _snapshot()
        sig = {"side": "BUY", "stop_price": 4940.0, "tp_price": 5060.0,
               "stop_dist": 60.0, "tp_dist": 60.0, "atr_used": 40.0}
        sizing = {"contracts_suggested": 1, "use_micro": False,
                  "risk_per_contract_usd": 3000.0, "final_risk_usd": 500.0,
                  "risk_pct_suggested": 0.5, "risk_pct_after_health": 0.5,
                  "risk_multiplier_regime": 1.0, "risk_multiplier_health": 1.0,
                  "risk_multiplier_session": 1.0}
        intent = _build_intent(strat, sig, sizing, snap, _regime(), _health(),
                               "RUN_test", "PV_0001")

        assert intent["intent_type"] == C.IntentType.ENTRY
        assert intent["strategy_id"] == "trend_reclaim_4H_ES"
        assert intent["side"] == "BUY"
        assert intent["state"] == C.IntentState.PROPOSED
        assert "intent_id" in intent
        assert "created_at" in intent
        assert "expires_at" in intent
        assert "thesis" in intent
        assert intent["stop_plan"]["price"] == 4940.0
        assert intent["take_profit_plan"]["price"] == 5060.0
        assert intent["sizing"] == sizing

    def test_micro_uses_micro_symbol(self):
        """When use_micro=True, intent uses micro_symbol."""
        strat = _strategy()
        snap = _snapshot()
        sig = {"side": "BUY", "stop_price": 4940.0, "tp_price": 5060.0,
               "stop_dist": 60.0, "tp_dist": 60.0, "atr_used": 40.0}
        sizing = {"contracts_suggested": 1, "use_micro": True,
                  "risk_per_contract_usd": 300.0, "final_risk_usd": 300.0,
                  "risk_pct_suggested": 0.5, "risk_pct_after_health": 0.5,
                  "risk_multiplier_regime": 1.0, "risk_multiplier_health": 1.0,
                  "risk_multiplier_session": 1.0}
        intent = _build_intent(strat, sig, sizing, snap, _regime(), _health(),
                               "RUN_test", "PV_0001")
        assert intent["symbol"] == "MES"

    def test_reward_risk_ratio(self):
        """Take profit plan includes reward:risk ratio."""
        sig = {"side": "BUY", "stop_price": 4940.0, "tp_price": 5060.0,
               "stop_dist": 60.0, "tp_dist": 60.0, "atr_used": 40.0}
        sizing = {"contracts_suggested": 1, "use_micro": False,
                  "risk_per_contract_usd": 3000.0, "final_risk_usd": 500.0,
                  "risk_pct_suggested": 0.5, "risk_pct_after_health": 0.5,
                  "risk_multiplier_regime": 1.0, "risk_multiplier_health": 1.0,
                  "risk_multiplier_session": 1.0}
        intent = _build_intent(_strategy(), sig, sizing, _snapshot(), _regime(),
                               _health(), "RUN_test", "PV_0001")
        assert intent["take_profit_plan"]["reward_risk_ratio"] == pytest.approx(1.0, abs=0.01)


# ===================================================================
# _roll_decision_tree()
# ===================================================================

class TestRollDecisionTree:
    def test_profitable_long_rolls(self):
        """Profitable LONG position → ROLL."""
        pos = {"entry_price": 5000.0, "current_price": 5050.0, "side": "LONG",
               "risk_at_stop_usd": 500.0, "point_value_usd": 50.0, "contracts": 1}
        assert _roll_decision_tree(pos, _regime(), _snapshot()) == "ROLL"

    def test_profitable_short_rolls(self):
        """Profitable SHORT position → ROLL."""
        pos = {"entry_price": 5050.0, "current_price": 5000.0, "side": "SHORT",
               "risk_at_stop_usd": 500.0, "point_value_usd": 50.0, "contracts": 1}
        assert _roll_decision_tree(pos, _regime(), _snapshot()) == "ROLL"

    def test_breakeven_rolls(self):
        """Breakeven (unrealized = 0) → ROLL."""
        pos = {"entry_price": 5000.0, "current_price": 5000.0, "side": "LONG",
               "risk_at_stop_usd": 500.0, "point_value_usd": 50.0, "contracts": 1}
        assert _roll_decision_tree(pos, _regime(), _snapshot()) == "ROLL"

    def test_big_loss_closes(self):
        """Loss > 50% of risk at stop → CLOSE."""
        pos = {"entry_price": 5000.0, "current_price": 4990.0, "side": "LONG",
               "risk_at_stop_usd": 500.0, "point_value_usd": 50.0, "contracts": 1}
        # unrealized = (4990-5000)*50*1 = -$500, 50% of $500 risk = $250, |-500| > $250 → CLOSE
        assert _roll_decision_tree(pos, _regime(), _snapshot()) == "CLOSE"

    def test_small_loss_good_regime_rolls(self):
        """Small loss + regime ≥ 0.45 → ROLL."""
        pos = {"entry_price": 5000.0, "current_price": 4998.0, "side": "LONG",
               "risk_at_stop_usd": 500.0, "point_value_usd": 50.0, "contracts": 1}
        # unrealized = -$100, 50% of $500 = $250, |-100| < $250 → check regime
        assert _roll_decision_tree(pos, _regime(score=0.60), _snapshot()) == "ROLL"

    def test_small_loss_bad_regime_closes(self):
        """Small loss + regime < 0.45 → CLOSE."""
        pos = {"entry_price": 5000.0, "current_price": 4998.0, "side": "LONG",
               "risk_at_stop_usd": 500.0, "point_value_usd": 50.0, "contracts": 1}
        assert _roll_decision_tree(pos, _regime(score=0.30), _snapshot()) == "CLOSE"

    def test_regime_at_threshold_rolls(self):
        """Regime exactly 0.45 → ROLL (>= check)."""
        pos = {"entry_price": 5000.0, "current_price": 4998.0, "side": "LONG",
               "risk_at_stop_usd": 500.0, "point_value_usd": 50.0, "contracts": 1}
        assert _roll_decision_tree(pos, _regime(score=0.45), _snapshot()) == "ROLL"

    def test_zero_risk_at_stop_checks_regime(self):
        """If risk_at_stop is 0, loss > 50% check is skipped → falls to regime."""
        pos = {"entry_price": 5000.0, "current_price": 4990.0, "side": "LONG",
               "risk_at_stop_usd": 0.0, "point_value_usd": 50.0, "contracts": 1}
        # unrealized = -$500, risk_at_stop=0 → 50% check is false → check regime
        assert _roll_decision_tree(pos, _regime(score=0.60), _snapshot()) == "ROLL"
        assert _roll_decision_tree(pos, _regime(score=0.30), _snapshot()) == "CLOSE"


# ===================================================================
# _build_roll_intent()
# ===================================================================

class TestBuildRollIntent:
    def test_roll_intent_structure(self):
        strat = _strategy()
        pos = {"position_id": "POS_001", "contract_month": "ESH6",
               "contracts": 2, "side": "LONG", "entry_price": 5000.0,
               "stop_price": 4940.0, "take_profit_price": 5060.0}
        with patch("brain.next_contract_month", return_value="ESM6"):
            intent = _build_roll_intent(strat, pos, _snapshot(), "RUN_test", "PV_0001")

        assert intent["intent_type"] == C.IntentType.ROLL
        assert intent["roll_from"] == "ESH6"
        assert intent["roll_to"] == "ESM6"
        assert intent["current_contracts"] == 2
        assert intent["side"] == "BUY"  # LONG → BUY
        assert intent["state"] == C.IntentState.PROPOSED

    def test_short_position_sell_side(self):
        pos = {"position_id": "POS_002", "contract_month": "ESH6",
               "contracts": 1, "side": "SHORT", "entry_price": 5000.0,
               "stop_price": 5060.0, "take_profit_price": 4940.0}
        with patch("brain.next_contract_month", return_value="ESM6"):
            intent = _build_roll_intent(_strategy(), pos, _snapshot(), "RUN_test", "PV_0001")
        assert intent["side"] == "SELL"


# ===================================================================
# run_brain() — end-to-end
# ===================================================================

class TestRunBrain:
    def _setup(self, strategy=None, portfolio=None, params=None):
        s = strategy or _strategy()
        store.save_strategy(s)
        p = params or store._default_params()
        params_dir = Path(os.environ["OPENCLAW_PARAMS"])
        params_dir.mkdir(parents=True, exist_ok=True)
        with open(params_dir / "PV_0001.json", "w") as f:
            json.dump(p, f)
        if portfolio:
            store.save_portfolio(portfolio)

    def test_signal_produces_intent(self):
        """Active strategy + valid signal → produces intent."""
        self._setup()
        snap = _snapshot(price=5000.0, ma20=4990.0, adx=30.0, ma_slope=0.5, atr_4h=40.0)
        with patch.object(ledger, "append", return_value={}), \
             patch("brain.check_event_suppression", _no_suppression):
            intents, regime, health = run_brain(
                {"ES": snap}, "RUN_test", watchtower_status=C.WatchtowerStatus.HEALTHY,
            )
        assert len(intents) >= 1
        assert intents[0]["intent_type"] == C.IntentType.ENTRY
        assert regime is not None
        assert "trend_reclaim_4H_ES" in health

    def test_no_signal_no_intent(self):
        """No signal condition → no intents emitted."""
        self._setup()
        snap = _snapshot(price=5000.0, ma20=4990.0, adx=10.0, ma_slope=0.5)  # ADX too low
        with patch.object(ledger, "append", return_value={}), \
             patch("brain.check_event_suppression", _no_suppression):
            intents, _, _ = run_brain(
                {"ES": snap}, "RUN_test", watchtower_status=C.WatchtowerStatus.HEALTHY,
            )
        assert len(intents) == 0

    def test_gate_failure_blocks_intent(self):
        """Watchtower HALT → gate 7 fails → no intent."""
        self._setup()
        snap = _snapshot(price=5000.0, ma20=4990.0, adx=30.0, ma_slope=0.5)
        with patch.object(ledger, "append", return_value={}), \
             patch("brain.check_event_suppression", _no_suppression):
            intents, _, _ = run_brain(
                {"ES": snap}, "RUN_test", watchtower_status=C.WatchtowerStatus.HALT,
            )
        assert len(intents) == 0

    def test_disabled_strategy_skipped(self):
        """DISABLED strategy is skipped entirely."""
        self._setup(strategy=_strategy({"status": C.StrategyStatus.DISABLED}))
        snap = _snapshot(price=5000.0, ma20=4990.0, adx=30.0, ma_slope=0.5)
        with patch.object(ledger, "append", return_value={}), \
             patch("brain.check_event_suppression", _no_suppression):
            intents, _, health = run_brain(
                {"ES": snap}, "RUN_test",
            )
        assert len(intents) == 0
        assert len(health) == 0

    def test_incubating_strategy_evaluated(self):
        """INCUBATING strategy is still evaluated (status check allows it)."""
        self._setup(strategy=_strategy({"status": C.StrategyStatus.INCUBATING}))
        snap = _snapshot(price=5000.0, ma20=4990.0, adx=30.0, ma_slope=0.5)
        with patch.object(ledger, "append", return_value={}), \
             patch("brain.check_event_suppression", _no_suppression):
            intents, _, health = run_brain(
                {"ES": snap}, "RUN_test",
            )
        # INCUBATING passes status filter but will fail Gate 1 (not ACTIVE)
        # so no intents, but health IS computed
        assert "trend_reclaim_4H_ES" in health

    def test_roll_window_emits_roll_intent(self):
        """Position within roll window + profitable → ROLL intent."""
        self._setup()
        port = _portfolio()
        port["positions"] = [{
            "strategy_id": "trend_reclaim_4H_ES",
            "symbol": "ES",
            "position_id": "POS_001",
            "contract_month": "ESH6",
            "contracts": 1,
            "side": "LONG",
            "entry_price": 5000.0,
            "current_price": 5050.0,
            "risk_at_stop_usd": 500.0,
            "point_value_usd": 50.0,
            "stop_price": 4940.0,
            "take_profit_price": 5060.0,
        }]
        store.save_portfolio(port)
        snap = _snapshot()
        snap["contract"]["days_to_expiry"] = 3  # Within 5-day roll window
        with patch.object(ledger, "append", return_value={}), \
             patch("brain.check_event_suppression", _no_suppression), \
             patch("brain.next_contract_month", return_value="ESM6"):
            intents, _, _ = run_brain(
                {"ES": snap}, "RUN_test",
            )
        assert len(intents) == 1
        assert intents[0]["intent_type"] == C.IntentType.ROLL

    def test_roll_close_emits_exit_intent(self):
        """Position in roll window + big loss → EXIT intent."""
        self._setup()
        port = _portfolio()
        port["positions"] = [{
            "strategy_id": "trend_reclaim_4H_ES",
            "symbol": "ES",
            "position_id": "POS_001",
            "contract_month": "ESH6",
            "contracts": 1,
            "side": "LONG",
            "entry_price": 5000.0,
            "current_price": 4980.0,  # -$1000 unrealized, > 50% of $500 risk
            "risk_at_stop_usd": 500.0,
            "point_value_usd": 50.0,
            "stop_price": 4940.0,
            "take_profit_price": 5060.0,
        }]
        store.save_portfolio(port)
        snap = _snapshot()
        snap["contract"]["days_to_expiry"] = 3
        with patch.object(ledger, "append", return_value={}), \
             patch("brain.check_event_suppression", _no_suppression):
            intents, _, _ = run_brain(
                {"ES": snap}, "RUN_test",
            )
        assert len(intents) == 1
        assert intents[0]["intent_type"] == C.IntentType.EXIT


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
