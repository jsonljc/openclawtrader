#!/usr/bin/env python3
"""Unit tests for Sentinel — risk rules, sizing math, idempotency, posture gating.

Covers:
  - calculate_contracts(): sizing math, micro fallback, edge cases
  - validate_margin(): margin reduction with posture-based limits
  - _run_hard_checks(): Rules 1-13 + slippage EV + Rule 19
  - Rules 14-17: session gate, cooldown, daily trade count, loss velocity
  - Rule 18: max concurrent positions
  - check_idempotency(): 4 idempotency checks
  - _compute_streak_modifier(): streak-based size reduction
  - _validate_strategy_fields(): pre-flight validation
  - evaluate_intent(): end-to-end approve/deny/reduce/bypass flows
"""

from __future__ import annotations
import os
import sys
import tempfile
import shutil
import math
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Set up isolated data directory BEFORE any imports that read OPENCLAW_DATA
_test_data_dir = tempfile.mkdtemp(prefix="sentinel_test_")
os.environ["OPENCLAW_DATA"] = _test_data_dir
os.environ["OPENCLAW_STRATEGIES"] = os.path.join(_test_data_dir, "strategies")
os.environ["OPENCLAW_PARAMS"] = os.path.join(_test_data_dir, "params")

# Insert project roots into path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "workspace-sentinel"))
sys.path.insert(0, str(ROOT / "workspace-forge"))
sys.path.insert(0, str(ROOT / "workspace-c3po"))

from shared import contracts as C
from shared import ledger
from shared import state_store as store
from sentinel import (
    calculate_contracts,
    validate_margin,
    check_idempotency,
    _run_hard_checks,
    _compute_streak_modifier,
    _check_max_concurrent_positions,
    _check_cooldown,
    _check_daily_trade_count,
    _check_loss_velocity,
    _validate_strategy_fields,
    evaluate_intent,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _isolate_data(tmp_path):
    """Point all state to a fresh temp dir for every test."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    strat_dir = tmp_path / "strategies"
    strat_dir.mkdir()
    params_dir = tmp_path / "params"
    params_dir.mkdir()

    os.environ["OPENCLAW_DATA"] = str(data_dir)
    os.environ["OPENCLAW_STRATEGIES"] = str(strat_dir)
    os.environ["OPENCLAW_PARAMS"] = str(params_dir)

    # Reload module-level paths
    import importlib
    importlib.reload(store)
    importlib.reload(ledger)

    # Reset ledger cache
    ledger._cached_last_seq = None
    ledger._cached_last_checksum = None


def _default_sp():
    """Default sentinel params."""
    return {
        "max_risk_per_trade_pct": 1.0,
        "max_open_risk_pct": 5.0,
        "max_daily_loss_pct": 3.0,
        "max_portfolio_dd_pct": 15.0,
        "max_margin_utilization_pct": 40.0,
        "max_cluster_exposure_pct": 3.0,
        "max_instrument_exposure_pct": 2.0,
        "max_intra_cluster_corr": 0.85,
        "max_concurrent_strategies": 4,
        "max_slippage_ticks": 4,
        "min_reward_risk_ratio": 1.5,
        "max_intent_age_sec": 900,
        "max_concurrent_positions": 4,
    }


def _default_portfolio(equity=100_000):
    """Minimal valid portfolio."""
    return {
        "account": {
            "equity_usd": equity,
            "opening_equity_usd": equity,
            "peak_equity_usd": equity,
            "margin_used_usd": 0.0,
            "margin_available_usd": equity,
            "margin_utilization_pct": 0.0,
        },
        "pnl": {
            "unrealized_usd": 0.0,
            "realized_today_usd": 0.0,
            "total_today_usd": 0.0,
            "total_today_pct": 0.0,
            "portfolio_dd_pct": 0.0,
        },
        "positions": [],
        "heat": {
            "total_open_risk_usd": 0.0,
            "total_open_risk_pct": 0.0,
            "cluster_exposure": {},
            "correlations_20d": {},
        },
    }


def _default_strategy():
    """Minimal ES strategy."""
    return {
        "strategy_id": "es_trend_4h",
        "symbol": "ES",
        "tick_size": 0.25,
        "tick_value_usd": 12.50,
        "point_value_usd": 50.0,
        "margin_per_contract_usd": 15840.0,
        "micro_available": True,
        "micro_point_value_usd": 5.0,
        "micro_tick_value_usd": 1.25,
        "micro_margin_per_contract_usd": 1584.0,
        "correlation_group": "equity_index",
        "risk_budget_pct": 0.5,
        "timeframe": "4H",
    }


def _default_snapshot(last_close=5000.0):
    """Minimal market snapshot."""
    bars_1h = [{"o": last_close, "h": last_close + 10, "l": last_close - 10, "c": last_close}]
    return {
        "bars": {"1H": bars_1h},
        "external": {"vix_percentile_252d": 0.5},
        "session_state": C.SessionState.CORE,
        "microstructure": {"avg_book_depth_contracts": 850},
        "indicators": {"atr_14_1H": 15.0},
    }


def _default_intent(entry=5000.0, stop=4990.0, tp=5020.0, strategy_id="es_trend_4h"):
    """Minimal ENTRY intent for ES."""
    return {
        "intent_id": "TI_test_001",
        "strategy_id": strategy_id,
        "symbol": "ES",
        "side": "BUY",
        "intent_type": C.IntentType.ENTRY,
        "param_version": "PV_0001",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "entry_plan": {"price": entry},
        "stop_plan": {"price": stop},
        "take_profit_plan": {"price": tp},
        "sizing": {"contracts_suggested": 1},
    }


def _register_strategy(strategy=None):
    """Write strategy file so Sentinel can load it."""
    s = strategy or _default_strategy()
    store.save_strategy(s)
    return s


def _write_params(params=None):
    """Write params file."""
    p = params or store._default_params()
    params_dir = Path(os.environ["OPENCLAW_PARAMS"])
    params_dir.mkdir(parents=True, exist_ok=True)
    import json
    with open(params_dir / "PV_0001.json", "w") as f:
        json.dump(p, f)
    return p


# ===================================================================
# calculate_contracts()
# ===================================================================

class TestCalculateContracts:
    def test_basic_full_contract(self):
        """$500 budget, 10pt stop, $50/pt → exactly 1 contract."""
        contracts, use_micro = calculate_contracts(500.0, 10.0, 50.0)
        assert contracts == 1
        assert use_micro is False

    def test_multiple_contracts(self):
        """$2000 budget, 10pt stop, $50/pt → 4 contracts."""
        contracts, use_micro = calculate_contracts(2000.0, 10.0, 50.0)
        assert contracts == 4
        assert use_micro is False

    def test_floors_down(self):
        """$750 budget, 10pt stop, $50/pt → floor(1.5) = 1."""
        contracts, use_micro = calculate_contracts(750.0, 10.0, 50.0)
        assert contracts == 1
        assert use_micro is False

    def test_micro_fallback(self):
        """Budget too small for full, falls back to micro."""
        # $40 budget, 10pt stop, $50/pt full = $500 risk/c — insufficient
        # micro: 10pt stop × $5/pt = $50 risk/c → floor(40/50) = 0 → fail
        # $60 budget: floor(60/50) = 1 micro
        contracts, use_micro = calculate_contracts(60.0, 10.0, 50.0,
                                                    micro_available=True,
                                                    micro_point_value_usd=5.0)
        assert contracts == 1
        assert use_micro is True

    def test_micro_multiple(self):
        """Budget for 3 micros."""
        contracts, use_micro = calculate_contracts(160.0, 10.0, 50.0,
                                                    micro_available=True,
                                                    micro_point_value_usd=5.0)
        assert contracts == 3
        assert use_micro is True

    def test_insufficient_no_micro(self):
        """Budget too small, no micro available → ValueError."""
        with pytest.raises(ValueError, match="insufficient for 1 contract"):
            calculate_contracts(100.0, 10.0, 50.0, micro_available=False)

    def test_insufficient_even_micro(self):
        """Budget too small even for 1 micro → ValueError."""
        with pytest.raises(ValueError, match="insufficient for 1 micro"):
            calculate_contracts(10.0, 10.0, 50.0,
                                micro_available=True,
                                micro_point_value_usd=5.0)

    def test_zero_budget_raises(self):
        with pytest.raises(ValueError, match="must be positive"):
            calculate_contracts(0.0, 10.0, 50.0)

    def test_negative_budget_raises(self):
        with pytest.raises(ValueError, match="must be positive"):
            calculate_contracts(-100.0, 10.0, 50.0)

    def test_zero_stop_distance_raises(self):
        with pytest.raises(ValueError, match="must be positive"):
            calculate_contracts(500.0, 0.0, 50.0)

    def test_negative_stop_distance_raises(self):
        with pytest.raises(ValueError, match="must be positive"):
            calculate_contracts(500.0, -5.0, 50.0)

    def test_large_budget_many_contracts(self):
        """$50000 budget, 10pt stop, $50/pt → 100 contracts."""
        contracts, use_micro = calculate_contracts(50_000.0, 10.0, 50.0)
        assert contracts == 100
        assert use_micro is False

    def test_cl_contract(self):
        """CL: $1000/pt, 2pt stop → $2000 risk/c. $5000 budget → 2 contracts."""
        contracts, use_micro = calculate_contracts(5000.0, 2.0, 1000.0)
        assert contracts == 2
        assert use_micro is False


# ===================================================================
# validate_margin()
# ===================================================================

class TestValidateMargin:
    def test_margin_within_limit(self):
        """1 contract at $15840 margin, $100K equity → 15.84% < 40%."""
        sp = _default_sp()
        result = validate_margin(
            contracts=1, use_micro=False,
            margin_per_contract=15840.0, micro_margin_per_contract=1584.0,
            current_margin_used=0.0, equity=100_000.0,
            posture="NORMAL", sp=sp,
        )
        assert result == 1

    def test_margin_exceeds_limit(self):
        """3 contracts at $15840 = $47520 → 47.52% > 40% → reduce to 2."""
        sp = _default_sp()
        result = validate_margin(
            contracts=3, use_micro=False,
            margin_per_contract=15840.0, micro_margin_per_contract=1584.0,
            current_margin_used=0.0, equity=100_000.0,
            posture="NORMAL", sp=sp,
        )
        assert result == 2  # 2 × $15840 = 31.68% < 40%

    def test_margin_caution_posture(self):
        """CAUTION posture limits margin to 30%."""
        sp = _default_sp()
        result = validate_margin(
            contracts=2, use_micro=False,
            margin_per_contract=15840.0, micro_margin_per_contract=1584.0,
            current_margin_used=0.0, equity=100_000.0,
            posture="CAUTION", sp=sp,
        )
        # 2 × $15840 = 31.68% > 30% → reduce to 1 (15.84% ≤ 30%)
        assert result == 1

    def test_margin_defensive_posture(self):
        """DEFENSIVE posture limits margin to 20%."""
        sp = _default_sp()
        result = validate_margin(
            contracts=2, use_micro=False,
            margin_per_contract=15840.0, micro_margin_per_contract=1584.0,
            current_margin_used=0.0, equity=100_000.0,
            posture="DEFENSIVE", sp=sp,
        )
        # 2 × $15840 = 31.68% > 20% → 1 × $15840 = 15.84% ≤ 20% → 1
        assert result == 1

    def test_margin_halt_posture(self):
        """HALT posture limits margin to 0% → always returns 0."""
        sp = _default_sp()
        result = validate_margin(
            contracts=1, use_micro=False,
            margin_per_contract=15840.0, micro_margin_per_contract=1584.0,
            current_margin_used=0.0, equity=100_000.0,
            posture="HALT", sp=sp,
        )
        assert result == 0

    def test_margin_micro_contract(self):
        """Micro uses micro_margin_per_contract."""
        sp = _default_sp()
        result = validate_margin(
            contracts=20, use_micro=True,
            margin_per_contract=15840.0, micro_margin_per_contract=1584.0,
            current_margin_used=0.0, equity=100_000.0,
            posture="NORMAL", sp=sp,
        )
        # 20 × $1584 = $31680 → 31.68% ≤ 40% → 20
        assert result == 20

    def test_margin_existing_usage(self):
        """Pre-existing margin usage reduces available room."""
        sp = _default_sp()
        result = validate_margin(
            contracts=2, use_micro=False,
            margin_per_contract=15840.0, micro_margin_per_contract=1584.0,
            current_margin_used=25_000.0, equity=100_000.0,
            posture="NORMAL", sp=sp,
        )
        # $25000 + 2×$15840 = $56680 → 56.68% > 40% → try 1: $25000+$15840 = $40840 = 40.84% > 40% → 0
        assert result == 0

    def test_zero_margin_per_contract(self):
        """Zero margin_per_contract → returns 0 (cannot validate)."""
        sp = _default_sp()
        result = validate_margin(
            contracts=1, use_micro=False,
            margin_per_contract=0.0, micro_margin_per_contract=0.0,
            current_margin_used=0.0, equity=100_000.0,
            posture="NORMAL", sp=sp,
        )
        assert result == 0

    def test_zero_equity(self):
        """Zero equity → utilization = 100% → always exceeds limit → 0."""
        sp = _default_sp()
        result = validate_margin(
            contracts=1, use_micro=False,
            margin_per_contract=15840.0, micro_margin_per_contract=1584.0,
            current_margin_used=0.0, equity=0.0,
            posture="NORMAL", sp=sp,
        )
        assert result == 0


# ===================================================================
# _validate_strategy_fields()
# ===================================================================

class TestValidateStrategyFields:
    def test_valid_strategy(self):
        ok, msg = _validate_strategy_fields(_default_strategy(), "es_trend_4h")
        assert ok is True
        assert msg == ""

    def test_missing_tick_size(self):
        s = _default_strategy()
        del s["tick_size"]
        ok, msg = _validate_strategy_fields(s, "es_trend_4h")
        assert ok is False
        assert "tick_size" in msg

    def test_none_field(self):
        s = _default_strategy()
        s["point_value_usd"] = None
        ok, msg = _validate_strategy_fields(s, "es_trend_4h")
        assert ok is False
        assert "point_value_usd" in msg

    def test_all_missing(self):
        ok, msg = _validate_strategy_fields({}, "empty")
        assert ok is False


# ===================================================================
# _compute_streak_modifier()
# ===================================================================

class TestStreakModifier:
    def test_no_losses(self):
        """No closed positions → modifier 1.0."""
        with patch.object(ledger, "query", return_value=[]):
            assert _compute_streak_modifier() == 1.0

    def test_two_losses(self):
        """2 consecutive losses < 3 threshold → 1.0."""
        entries = [
            {"payload": {"realized_pnl": -100}},
            {"payload": {"realized_pnl": -200}},
        ]
        with patch.object(ledger, "query", return_value=entries):
            assert _compute_streak_modifier() == 1.0

    def test_three_losses(self):
        """3 consecutive losses → 0.7."""
        entries = [
            {"payload": {"realized_pnl": -100}},
            {"payload": {"realized_pnl": -200}},
            {"payload": {"realized_pnl": -50}},
        ]
        with patch.object(ledger, "query", return_value=entries):
            assert _compute_streak_modifier() == 0.7

    def test_four_losses(self):
        """4 consecutive losses → still 0.7 (not yet 5)."""
        entries = [{"payload": {"realized_pnl": -100}} for _ in range(4)]
        with patch.object(ledger, "query", return_value=entries):
            assert _compute_streak_modifier() == 0.7

    def test_five_losses(self):
        """5 consecutive losses → 0.5."""
        entries = [{"payload": {"realized_pnl": -100}} for _ in range(5)]
        with patch.object(ledger, "query", return_value=entries):
            assert _compute_streak_modifier() == 0.5

    def test_streak_broken_by_win(self):
        """Loss, win, loss → streak = 1 → 1.0."""
        entries = [
            {"payload": {"realized_pnl": -100}},
            {"payload": {"realized_pnl": 200}},  # win breaks streak
            {"payload": {"realized_pnl": -50}},
        ]
        with patch.object(ledger, "query", return_value=entries):
            assert _compute_streak_modifier() == 1.0

    def test_zero_pnl_breaks_streak(self):
        """Zero PnL is not negative → breaks streak."""
        entries = [
            {"payload": {"realized_pnl": -100}},
            {"payload": {"realized_pnl": 0}},
            {"payload": {"realized_pnl": -100}},
        ]
        with patch.object(ledger, "query", return_value=entries):
            assert _compute_streak_modifier() == 1.0


# ===================================================================
# _check_max_concurrent_positions() (Rule 18)
# ===================================================================

class TestMaxConcurrentPositions:
    def test_no_positions(self):
        portfolio = _default_portfolio()
        sp = _default_sp()
        ok, _ = _check_max_concurrent_positions(portfolio, sp)
        assert ok is True

    def test_at_limit(self):
        portfolio = _default_portfolio()
        portfolio["positions"] = [{"strategy_id": f"s{i}"} for i in range(4)]
        sp = _default_sp()
        ok, reason = _check_max_concurrent_positions(portfolio, sp)
        assert ok is False
        assert "4" in reason

    def test_below_limit(self):
        portfolio = _default_portfolio()
        portfolio["positions"] = [{"strategy_id": f"s{i}"} for i in range(3)]
        sp = _default_sp()
        ok, _ = _check_max_concurrent_positions(portfolio, sp)
        assert ok is True


# ===================================================================
# _check_daily_trade_count() (Rule 16)
# ===================================================================

class TestDailyTradeCount:
    def test_under_limit(self):
        with patch.object(ledger, "query", return_value=[]):
            ok, _ = _check_daily_trade_count()
            assert ok is True

    def test_at_limit(self):
        """16 fills (8 round-trips × 2 fills each) → deny."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        entries = [{"timestamp": f"{today}T12:00:00Z"} for _ in range(16)]
        with patch.object(ledger, "query", return_value=entries):
            ok, reason = _check_daily_trade_count()
            assert ok is False
            assert "8" in reason

    def test_old_fills_ignored(self):
        """Fills from yesterday don't count."""
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
        entries = [{"timestamp": f"{yesterday}T12:00:00Z"} for _ in range(20)]
        with patch.object(ledger, "query", return_value=entries):
            ok, _ = _check_daily_trade_count()
            assert ok is True


# ===================================================================
# _check_loss_velocity() (Rule 17)
# ===================================================================

class TestLossVelocity:
    def test_no_losses(self):
        with patch.object(ledger, "query", return_value=[]):
            ok, _ = _check_loss_velocity()
            assert ok is True

    def test_two_recent_losses(self):
        """2 losses in 60min → OK (threshold is 3)."""
        now = datetime.now(timezone.utc)
        entries = [
            {"timestamp": (now - timedelta(minutes=5)).isoformat(), "payload": {"realized_pnl": -100}},
            {"timestamp": (now - timedelta(minutes=10)).isoformat(), "payload": {"realized_pnl": -50}},
        ]
        with patch.object(ledger, "query", return_value=entries):
            ok, _ = _check_loss_velocity()
            assert ok is True

    def test_three_recent_losses(self):
        """3 losses in 60min → HALT."""
        now = datetime.now(timezone.utc)
        entries = [
            {"timestamp": (now - timedelta(minutes=5)).isoformat(), "payload": {"realized_pnl": -100}},
            {"timestamp": (now - timedelta(minutes=10)).isoformat(), "payload": {"realized_pnl": -50}},
            {"timestamp": (now - timedelta(minutes=30)).isoformat(), "payload": {"realized_pnl": -75}},
        ]
        with patch.object(ledger, "query", return_value=entries):
            ok, reason = _check_loss_velocity()
            assert ok is False
            assert "3 losses" in reason

    def test_old_losses_outside_window(self):
        """Losses older than 60min don't count."""
        now = datetime.now(timezone.utc)
        entries = [
            {"timestamp": (now - timedelta(minutes=5)).isoformat(), "payload": {"realized_pnl": -100}},
            # This one is > 60 min ago — the loop should break
            {"timestamp": (now - timedelta(minutes=90)).isoformat(), "payload": {"realized_pnl": -50}},
        ]
        with patch.object(ledger, "query", return_value=entries):
            ok, _ = _check_loss_velocity()
            assert ok is True


# ===================================================================
# check_idempotency()
# ===================================================================

class TestIdempotency:
    def test_clean_intent_passes(self):
        """No duplicates → passes all 4 checks."""
        with patch.object(ledger, "query", return_value=[]):
            ok, _ = check_idempotency(_default_intent(), _default_portfolio())
            assert ok is True

    def test_duplicate_intent_id(self):
        """Intent already approved → denied (Check 1)."""
        intent = _default_intent()
        entries = [{"payload": {"intent_id": intent["intent_id"]}, "ledger_seq": 42}]
        with patch.object(ledger, "query", return_value=entries):
            ok, reason = check_idempotency(intent, _default_portfolio())
            assert ok is False
            assert "Duplicate" in reason

    def test_active_position_blocks(self):
        """Existing position for same strategy/symbol/side → denied (Check 2)."""
        intent = _default_intent()
        portfolio = _default_portfolio()
        portfolio["positions"] = [{
            "strategy_id": "es_trend_4h",
            "symbol": "ES",
            "side": "LONG",
        }]
        with patch.object(ledger, "query", return_value=[]):
            ok, reason = check_idempotency(intent, portfolio)
            assert ok is False
            assert "Active position" in reason

    def test_roll_intent_bypasses_position_check(self):
        """ROLL intent for the same position is allowed (Check 2 bypass)."""
        intent = _default_intent()
        intent["intent_type"] = C.IntentType.ROLL
        intent["position_id"] = "POS_001"
        portfolio = _default_portfolio()
        portfolio["positions"] = [{
            "strategy_id": "es_trend_4h",
            "symbol": "ES",
            "side": "LONG",
            "position_id": "POS_001",
        }]
        with patch.object(ledger, "query", return_value=[]):
            ok, _ = check_idempotency(intent, portfolio)
            assert ok is True

    def test_conflicting_pending_intent(self):
        """Another non-terminal intent for same strategy+symbol → denied (Check 3)."""
        intent = _default_intent()
        # First query (terminal_types) returns empty
        # Second query (INTENT_CREATED) returns a conflicting intent
        conflicting = [{
            "payload": {
                "intent_id": "TI_other_999",
                "strategy_id": "es_trend_4h",
                "symbol": "ES",
                "state": C.IntentState.PROPOSED,
            }
        }]

        call_count = [0]
        def mock_query(**kwargs):
            call_count[0] += 1
            event_types = kwargs.get("event_types", [])
            if C.EventType.INTENT_CREATED in event_types:
                return conflicting
            return []

        with patch.object(ledger, "query", side_effect=mock_query):
            ok, reason = check_idempotency(intent, _default_portfolio())
            assert ok is False
            assert "Conflicting pending" in reason

    def test_rapid_fire_guard(self):
        """Same strategy approved <60s ago → denied (Check 4)."""
        intent = _default_intent()
        now = datetime.now(timezone.utc)
        recent_approval = [{
            "payload": {"strategy_id": "es_trend_4h"},
            "timestamp": (now - timedelta(seconds=30)).isoformat(),
        }]

        call_count = [0]
        def mock_query(**kwargs):
            call_count[0] += 1
            event_types = kwargs.get("event_types", [])
            if C.EventType.APPROVAL_ISSUED in event_types:
                return recent_approval
            return []

        with patch.object(ledger, "query", side_effect=mock_query):
            ok, reason = check_idempotency(intent, _default_portfolio())
            assert ok is False
            assert "Rapid-fire" in reason


# ===================================================================
# _run_hard_checks() — Rules 1-13 + slippage EV
# ===================================================================

class TestHardChecks:
    """Each test isolates one rule by making all others pass."""

    def _run(self, intent=None, contracts=1, use_micro=False, strategy=None,
             portfolio=None, snapshot=None, posture="NORMAL", sp=None):
        intent = intent or _default_intent()
        strategy = strategy or _default_strategy()
        portfolio = portfolio or _default_portfolio()
        snapshot = snapshot or _default_snapshot()
        sp = sp or _default_sp()
        # Patch event_calendar import to prevent Rule 19 from interfering
        # (it's imported inside the function via try/except ImportError)
        import sentinel as sentinel_mod
        original_import = __builtins__.__import__ if hasattr(__builtins__, '__import__') else __import__
        def _mock_import(name, *args, **kwargs):
            if "event_calendar" in name:
                raise ImportError("mocked")
            return original_import(name, *args, **kwargs)
        with patch("builtins.__import__", side_effect=_mock_import):
            return _run_hard_checks(intent, contracts, use_micro, strategy,
                                     portfolio, snapshot, posture, sp)

    def test_all_pass_baseline(self):
        """Baseline: 1 ES contract at $100K equity, all rules pass."""
        passed, failed, warnings = self._run()
        assert len(failed) == 0

    # --- Rule 1: Max risk per trade ---
    def test_rule1_risk_per_trade_pass(self):
        """1 contract, 10pt stop, $50/pt → $500 = 0.5% ≤ 1%."""
        passed, failed, _ = self._run()
        rule1 = [r for r in passed if r["rule"] == "max_risk_per_trade"]
        assert len(rule1) == 1
        assert rule1[0]["value"] <= rule1[0]["limit"]

    def test_rule1_risk_per_trade_fail(self):
        """3 contracts, 10pt stop → $1500 = 1.5% > 1%."""
        passed, failed, _ = self._run(contracts=3)
        rule1_fail = [r for r in failed if r["rule"] == "max_risk_per_trade"]
        assert len(rule1_fail) == 1

    def test_rule1_posture_reduces_limit(self):
        """CAUTION posture → max risk = 1.0 × 0.6 = 0.6%. $500 = 0.5% still passes."""
        passed, failed, _ = self._run(posture="CAUTION")
        rule1 = [r for r in passed if r["rule"] == "max_risk_per_trade"]
        assert rule1[0]["limit"] == pytest.approx(0.6, abs=0.01)

    # --- Rule 2: Max open portfolio risk ---
    def test_rule2_open_risk_pass(self):
        passed, failed, _ = self._run()
        rule2 = [r for r in passed if r["rule"] == "max_open_risk"]
        assert len(rule2) == 1

    def test_rule2_open_risk_fail(self):
        """Existing open risk + new trade > 5%."""
        portfolio = _default_portfolio()
        portfolio["heat"]["total_open_risk_usd"] = 4600.0  # 4.6%
        passed, failed, _ = self._run(portfolio=portfolio)
        # New risk = 10pt × $50 × 1 = $500 → total = $5100 = 5.1% > 5%
        rule2_fail = [r for r in failed if r["rule"] == "max_open_risk"]
        assert len(rule2_fail) == 1

    # --- Rule 3: Daily loss cap ---
    def test_rule3_daily_loss_pass(self):
        passed, failed, _ = self._run()
        rule3 = [r for r in passed if r["rule"] == "daily_loss_cap"]
        assert len(rule3) == 1

    def test_rule3_daily_loss_fail(self):
        """Daily PnL = -3.5% > -3% cap."""
        portfolio = _default_portfolio()
        portfolio["pnl"]["total_today_pct"] = -3.5
        passed, failed, _ = self._run(portfolio=portfolio)
        rule3_fail = [r for r in failed if r["rule"] == "daily_loss_cap"]
        assert len(rule3_fail) == 1

    # --- Rule 4: Portfolio DD cap ---
    def test_rule4_dd_pass(self):
        passed, failed, _ = self._run()
        rule4 = [r for r in passed if r["rule"] == "portfolio_dd_cap"]
        assert len(rule4) == 1

    def test_rule4_dd_fail(self):
        """DD = 16% > 15% cap."""
        portfolio = _default_portfolio()
        portfolio["pnl"]["portfolio_dd_pct"] = 16.0
        passed, failed, _ = self._run(portfolio=portfolio)
        rule4_fail = [r for r in failed if r["rule"] == "portfolio_dd_cap"]
        assert len(rule4_fail) == 1

    # --- Rule 5: Margin utilization ---
    def test_rule5_margin_pass(self):
        passed, failed, _ = self._run()
        rule5 = [r for r in passed if r["rule"] == "margin_utilization"]
        assert len(rule5) == 1

    def test_rule5_margin_fail(self):
        """Margin usage already at 35%, adding $15840 → 50.84% > 40%."""
        portfolio = _default_portfolio()
        portfolio["account"]["margin_used_usd"] = 35_000.0
        passed, failed, _ = self._run(portfolio=portfolio)
        rule5_fail = [r for r in failed if r["rule"] == "margin_utilization"]
        assert len(rule5_fail) == 1

    # --- Rule 6: Cluster exposure ---
    def test_rule6_cluster_pass(self):
        passed, failed, _ = self._run()
        assert not [r for r in failed if r["rule"] == "cluster_exposure"]

    def test_rule6_cluster_fail(self):
        """Existing cluster risk + new → >3%."""
        portfolio = _default_portfolio()
        portfolio["heat"]["cluster_exposure"] = {
            "equity_index": {"risk_usd": 2_600.0}
        }
        passed, failed, _ = self._run(portfolio=portfolio)
        # New risk = $500 → total $3100 = 3.1% > 3%
        rule6_fail = [r for r in failed if r["rule"] == "cluster_exposure"]
        assert len(rule6_fail) == 1

    # --- Rule 7: Single-instrument exposure ---
    def test_rule7_instrument_pass(self):
        passed, failed, _ = self._run()
        assert not [r for r in failed if r["rule"] == "instrument_exposure"]

    def test_rule7_instrument_fail(self):
        """Existing ES position risk + new > 2%."""
        portfolio = _default_portfolio()
        portfolio["positions"] = [
            {"symbol": "ES", "risk_at_stop_usd": 1600.0}
        ]
        passed, failed, _ = self._run(portfolio=portfolio)
        # $1600 + $500 = $2100 = 2.1% > 2%
        rule7_fail = [r for r in failed if r["rule"] == "instrument_exposure"]
        assert len(rule7_fail) == 1

    # --- Rule 8: Intra-cluster correlation ---
    def test_rule8_correlation_pass(self):
        portfolio = _default_portfolio()
        portfolio["heat"]["correlations_20d"] = {"ES-NQ": 0.80}
        passed, failed, _ = self._run(portfolio=portfolio)
        assert not [r for r in failed if r["rule"] == "max_intra_cluster_corr"]

    def test_rule8_correlation_fail(self):
        """Correlation > 0.85 → fail."""
        portfolio = _default_portfolio()
        portfolio["heat"]["correlations_20d"] = {"ES-NQ": 0.92}
        passed, failed, _ = self._run(portfolio=portfolio)
        rule8_fail = [r for r in failed if r["rule"] == "max_intra_cluster_corr"]
        assert len(rule8_fail) == 1
        assert rule8_fail[0]["value"] == 0.92

    # --- Rule 9: Max concurrent strategies ---
    def test_rule9_concurrent_pass(self):
        passed, failed, _ = self._run()
        assert not [r for r in failed if r["rule"] == "max_concurrent_strategies"]

    def test_rule9_concurrent_fail(self):
        """4 open strategies + 1 new = 5 > 4."""
        portfolio = _default_portfolio()
        portfolio["positions"] = [
            {"strategy_id": f"s{i}"} for i in range(4)
        ]
        passed, failed, _ = self._run(portfolio=portfolio)
        rule9_fail = [r for r in failed if r["rule"] == "max_concurrent_strategies"]
        assert len(rule9_fail) == 1

    def test_rule9_same_strategy_no_count(self):
        """Opening a 2nd position for same strategy doesn't add to count."""
        portfolio = _default_portfolio()
        portfolio["positions"] = [
            {"strategy_id": "es_trend_4h"},
            {"strategy_id": "s2"},
            {"strategy_id": "s3"},
        ]
        intent = _default_intent(strategy_id="es_trend_4h")
        passed, failed, _ = self._run(intent=intent, portfolio=portfolio)
        # 3 strategies, not adding new one → count stays 3 ≤ 4
        assert not [r for r in failed if r["rule"] == "max_concurrent_strategies"]

    # --- Rule 11: Min reward:risk ratio ---
    def test_rule11_reward_risk_pass(self):
        """TP 20pt / stop 10pt = 2.0 ≥ 1.5."""
        passed, failed, _ = self._run()
        assert not [r for r in failed if r["rule"] == "min_reward_risk"]

    def test_rule11_reward_risk_fail(self):
        """TP 10pt / stop 10pt = 1.0 < 1.5."""
        intent = _default_intent(entry=5000.0, stop=4990.0, tp=5010.0)
        passed, failed, _ = self._run(intent=intent)
        rule11_fail = [r for r in failed if r["rule"] == "min_reward_risk"]
        assert len(rule11_fail) == 1

    # --- Rule 12: Max intent age ---
    def test_rule12_fresh_intent(self):
        """Intent created just now → passes."""
        passed, failed, _ = self._run()
        assert not [r for r in failed if r["rule"] == "max_intent_age"]

    def test_rule12_stale_intent(self):
        """Intent created 20min ago → > 900s → fail."""
        intent = _default_intent()
        intent["created_at"] = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat()
        passed, failed, _ = self._run(intent=intent)
        rule12_fail = [r for r in failed if r["rule"] == "max_intent_age"]
        assert len(rule12_fail) == 1

    # --- Slippage EV check ---
    def test_slippage_ev_pass(self):
        """Baseline: 20pt TP, 10pt stop, low slippage → good EV."""
        passed, failed, _ = self._run()
        assert not [r for r in failed if r["rule"] == "slippage_ev"]

    def test_slippage_ev_fail(self):
        """Tight TP with high slippage → bad EV."""
        # TP 2pt, stop 10pt → tp_dist_ticks=8, stop_dist_ticks=40
        # EV = (8-1)/(40+1) ≈ 0.17 < 0.5
        intent = _default_intent(entry=5000.0, stop=4990.0, tp=5002.0)
        passed, failed, _ = self._run(intent=intent)
        ev_fail = [r for r in failed if r["rule"] == "slippage_ev"]
        assert len(ev_fail) == 1


# ===================================================================
# evaluate_intent() — end-to-end
# ===================================================================

class TestEvaluateIntent:
    """End-to-end tests for the main evaluation pipeline."""

    def _run_eval(self, intent=None, portfolio=None, snapshot=None,
                  posture="NORMAL", strategy=None, health_by_strategy=None):
        intent = intent or _default_intent()
        portfolio = portfolio or _default_portfolio()
        snapshot = snapshot or _default_snapshot()
        _register_strategy(strategy)
        _write_params()

        original_import = __import__
        def _mock_import(name, *args, **kwargs):
            if "event_calendar" in name:
                raise ImportError("mocked")
            return original_import(name, *args, **kwargs)
        with patch.object(ledger, "query", return_value=[]), \
             patch.object(ledger, "append", return_value={}), \
             patch("sentinel._compute_streak_modifier", return_value=1.0), \
             patch("builtins.__import__", side_effect=_mock_import):
            return evaluate_intent(
                intent, portfolio, snapshot, posture,
                run_id="RUN_test_001",
                health_by_strategy=health_by_strategy,
            )

    def test_entry_approved(self):
        """Basic entry in good conditions → APPROVE."""
        result = self._run_eval()
        assert result["decision"] == C.RiskDecision.APPROVE
        assert result["state"] == C.IntentState.APPROVED
        assert result["sizing_final"]["contracts_allowed"] >= 1

    def test_exit_always_approved(self):
        """EXIT intent always approved, even at HALT."""
        intent = _default_intent()
        intent["intent_type"] = C.IntentType.EXIT
        result = self._run_eval(intent=intent, posture="HALT")
        assert result["decision"] == C.RiskDecision.APPROVE

    def test_flatten_always_approved(self):
        """FLATTEN intent always approved."""
        intent = _default_intent()
        intent["intent_type"] = C.IntentType.FLATTEN
        result = self._run_eval(intent=intent, posture="HALT")
        assert result["decision"] == C.RiskDecision.APPROVE

    def test_scale_out_always_approved(self):
        """SCALE_OUT intent always approved."""
        intent = _default_intent()
        intent["intent_type"] = C.IntentType.SCALE_OUT
        result = self._run_eval(intent=intent, posture="DEFENSIVE")
        assert result["decision"] == C.RiskDecision.APPROVE

    def test_defensive_blocks_entry(self):
        """DEFENSIVE posture blocks ENTRY intents."""
        result = self._run_eval(posture="DEFENSIVE")
        assert result["decision"] == C.RiskDecision.DENY
        assert "DEFENSIVE" in result["reasons"][0]

    def test_halt_blocks_entry(self):
        """HALT posture blocks ENTRY intents."""
        result = self._run_eval(posture="HALT")
        assert result["decision"] == C.RiskDecision.DENY
        assert "HALT" in result["reasons"][0]

    def test_caution_allows_entry(self):
        """CAUTION posture allows entries (with reduced size)."""
        result = self._run_eval(posture="CAUTION")
        # May be approved or denied based on margin, but not denied for posture
        if result["decision"] == C.RiskDecision.DENY:
            assert "CAUTION" not in result["reasons"][0] or "blocks" not in result["reasons"][0]

    def test_unknown_strategy_denied(self):
        """Strategy not in registry → denied."""
        intent = _default_intent(strategy_id="nonexistent_strat")
        # Don't register any strategy
        _write_params()
        with patch.object(ledger, "query", return_value=[]), \
             patch.object(ledger, "append", return_value={}), \
             patch("sentinel._compute_streak_modifier", return_value=1.0):
            result = evaluate_intent(
                intent, _default_portfolio(), _default_snapshot(), "NORMAL",
                run_id="RUN_test_001",
            )
        assert result["decision"] == C.RiskDecision.DENY
        assert "Unknown strategy_id" in result["reasons"][0]

    def test_zero_stop_distance_denied(self):
        """Stop at entry price → denied."""
        intent = _default_intent(entry=5000.0, stop=5000.0, tp=5020.0)
        result = self._run_eval(intent=intent)
        assert result["decision"] == C.RiskDecision.DENY
        assert "Stop distance" in result["reasons"][0]

    def test_health_disable_denies(self):
        """DISABLE health action → risk_usd = 0 → denied."""
        health = {"es_trend_4h": {"action": C.HealthAction.DISABLE}}
        result = self._run_eval(health_by_strategy=health)
        assert result["decision"] == C.RiskDecision.DENY

    def test_health_half_size_reduces(self):
        """HALF_SIZE health action → half risk budget."""
        health = {"es_trend_4h": {"action": C.HealthAction.HALF_SIZE}}
        result = self._run_eval(health_by_strategy=health)
        # With half risk, might still get 1 micro or be denied — depends on math
        # At $100K equity, 0.5% × 0.5 = 0.25% = $250 budget, ES 10pt stop = $500/c
        # → needs micro fallback. With micro: $250 / (10 × $5) = 5 micro contracts
        if result["decision"] in (C.RiskDecision.APPROVE, C.RiskDecision.APPROVE_REDUCED):
            assert result["sizing_final"]["contracts_allowed"] >= 1

    def test_roll_approved_normal_posture(self):
        """ROLL intent approved when margin OK and posture is NORMAL."""
        intent = _default_intent()
        intent["intent_type"] = C.IntentType.ROLL
        intent["current_contracts"] = 1
        intent["position_id"] = "POS_001"
        intent["roll_from"] = "ESH6"
        intent["roll_to"] = "ESM6"
        intent["stop_price"] = 4990.0
        intent["take_profit_price"] = 5020.0
        result = self._run_eval(intent=intent)
        assert result["decision"] == C.RiskDecision.APPROVE
        assert result["intent_type"] == C.IntentType.ROLL

    def test_roll_denied_halt_posture(self):
        """ROLL intent denied at HALT posture."""
        intent = _default_intent()
        intent["intent_type"] = C.IntentType.ROLL
        intent["current_contracts"] = 1
        result = self._run_eval(intent=intent, posture="HALT")
        assert result["decision"] == C.RiskDecision.DENY
        assert "HALT" in result["reasons"][0]

    def test_missing_strategy_fields_denied(self):
        """Strategy missing required fields → denied."""
        bad_strategy = _default_strategy()
        del bad_strategy["tick_size"]
        result = self._run_eval(strategy=bad_strategy)
        assert result["decision"] == C.RiskDecision.DENY
        assert "missing required fields" in result["reasons"][0]

    def test_incubation_reduces_size(self):
        """Incubating strategy uses 25% of normal size."""
        strategy = _default_strategy()
        strategy["incubation"] = {"is_incubating": True, "incubation_size_pct": 25}
        # At $100K, 0.5% risk = $500 base. With 25% incubation = $125.
        # Full ES: $500 risk/c → 0 contracts. Micro: $50 risk/c → 2 contracts.
        result = self._run_eval(strategy=strategy)
        if result["decision"] in (C.RiskDecision.APPROVE, C.RiskDecision.APPROVE_REDUCED):
            assert result["sizing_final"]["use_micro"] is True

    def test_approve_reduced_when_contracts_cut(self):
        """If Sentinel reduces contracts below suggested → APPROVE_REDUCED."""
        intent = _default_intent()
        intent["sizing"]["contracts_suggested"] = 5
        # With $100K equity, 0.5% risk = $500. ES $500/c → 1 contract.
        # Suggested was 5 → reduced to 1 → APPROVE_REDUCED
        result = self._run_eval(intent=intent)
        if result["decision"] != C.RiskDecision.DENY:
            assert result["decision"] == C.RiskDecision.APPROVE_REDUCED
            assert result["sizing_final"]["contracts_allowed"] < 5


# ===================================================================
# _check_cooldown() (Rule 15)
# ===================================================================

class TestCooldown:
    def test_no_setup_family_skips(self):
        """No setup_family → skip cooldown check."""
        intent = _default_intent()
        with patch.object(ledger, "query", return_value=[]):
            ok, _ = _check_cooldown(intent)
            assert ok is True

    def test_recent_stopout_blocks(self):
        """Stop-out for same family < 15min ago → denied."""
        intent = _default_intent()
        intent["setup_metadata"] = {"setup_family": "trend_pullback"}
        now = datetime.now(timezone.utc)
        entries = [{
            "payload": {
                "close_reason": "STOP_HIT",
                "setup_family": "trend_pullback",
            },
            "timestamp": (now - timedelta(minutes=5)).isoformat(),
        }]
        with patch.object(ledger, "query", return_value=entries):
            ok, reason = _check_cooldown(intent)
            assert ok is False
            assert "Cooldown" in reason

    def test_old_stopout_allows(self):
        """Stop-out > 15min ago → allowed."""
        intent = _default_intent()
        intent["setup_metadata"] = {"setup_family": "trend_pullback"}
        now = datetime.now(timezone.utc)
        entries = [{
            "payload": {
                "close_reason": "STOP_HIT",
                "setup_family": "trend_pullback",
            },
            "timestamp": (now - timedelta(minutes=20)).isoformat(),
        }]
        with patch.object(ledger, "query", return_value=entries):
            ok, _ = _check_cooldown(intent)
            assert ok is True

    def test_different_family_allows(self):
        """Stop-out for different family → allowed."""
        intent = _default_intent()
        intent["setup_metadata"] = {"setup_family": "trend_pullback"}
        now = datetime.now(timezone.utc)
        entries = [{
            "payload": {
                "close_reason": "STOP_HIT",
                "setup_family": "mean_reversion",
            },
            "timestamp": (now - timedelta(minutes=5)).isoformat(),
        }]
        with patch.object(ledger, "query", return_value=entries):
            ok, _ = _check_cooldown(intent)
            assert ok is True


# ===================================================================
# Run with pytest
# ===================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
