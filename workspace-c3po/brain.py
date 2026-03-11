#!/usr/bin/env python3
"""C3PO — Portfolio Strategist — spec Section 6.

Phase 1 scope:
- Single strategy: trend_reclaim_4H_ES
- Fixed risk (no regime scaling, no health scaling from ledger)
- Full proposal gating (all 9 gates)
- Full intent construction with stop/TP/sizing
- Micro-contract fallback
- All intent types emitted to ledger

Public API:
    run_brain(snapshots, run_id, param_version, watchtower_status) -> list[intent]
"""

from __future__ import annotations
import math
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))
from shared import contracts as C
from shared import identifiers as IDs
from shared import ledger
from shared import state_store as store
from shared.contract_calendar import next_contract_month

from regime import compute_regime as _compute_regime
from health import evaluate_strategy_health


# ---------------------------------------------------------------------------
# Regime scoring — delegated to regime.py (Phase 2)
# ---------------------------------------------------------------------------

def _compute_regime_for_snapshot(snapshot: dict, portfolio: dict, param_version: str, run_id: str) -> dict:
    """Delegate to regime.py for full sigmoid-weighted scoring."""
    return _compute_regime(snapshot, portfolio, param_version, run_id, snapshot.get("asof"))


# ---------------------------------------------------------------------------
# Strategy health — delegated to health.py
# ---------------------------------------------------------------------------

def _evaluate_strategy_health(strategy: dict, param_version: str = "PV_0001") -> dict:
    """Delegate to health.py."""
    return evaluate_strategy_health(strategy, param_version)


# ---------------------------------------------------------------------------
# Proposal gates — spec 6.7
# ---------------------------------------------------------------------------

def _check_gates(
    strategy: dict,
    health: dict,
    snapshot: dict,
    portfolio: dict,
    posture: str,
    wt_status: str,
    run_id: str,
    regime: dict | None = None,
) -> tuple[bool, list[str]]:
    """
    Check all 9 proposal gates.
    Returns (all_passed, list_of_failures).
    """
    failures: list[str] = []

    # Gate 1: Strategy status ACTIVE
    status = strategy.get("status", C.StrategyStatus.ACTIVE)
    if status != C.StrategyStatus.ACTIVE:
        failures.append(f"Gate 1: strategy status={status} (need ACTIVE)")

    # Gate 2: Health score >= min_health_score
    min_hs = strategy.get("min_health_score", 0.30)
    hs     = health.get("health_score", 0.60)
    if hs < min_hs:
        failures.append(f"Gate 2: health_score={hs:.2f} < min {min_hs}")

    # Gate 3: Health action != DISABLE (effective_regime_score check is Phase 2)
    if health.get("action") == C.HealthAction.DISABLE:
        failures.append("Gate 3: strategy health action=DISABLE")

    # Gate 3b: Regime score too low
    if regime and regime.get("effective_regime_score", 1.0) < 0.30:
        failures.append(
            f"Gate 3b: effective_regime_score={regime['effective_regime_score']:.2f} < 0.30"
        )

    # Gate 4: Sentinel posture allows entries
    if posture in (C.Posture.DEFENSIVE, C.Posture.HALT):
        failures.append(f"Gate 4: posture={posture} blocks entries")

    # Gate 5: Session state allows entries
    session = snapshot.get("session_state", C.SessionState.CORE)
    if session in (C.SessionState.CLOSED, C.SessionState.POST_CLOSE, C.SessionState.PRE_OPEN):
        failures.append(f"Gate 5: session={session} — no new entries")

    # Gate 6: (Removed — rollover is handled before gate check)

    # Gate 7: Watchtower not HALT
    if wt_status == C.WatchtowerStatus.HALT:
        failures.append("Gate 7: Watchtower status=HALT")

    # Gate 8: No duplicate intent (no open position for same strategy+symbol+side already enforced
    # by Sentinel idempotency check; C3PO pre-screens here to avoid emitting unnecessary intents)
    strategy_id = strategy.get("strategy_id", "")
    symbol      = strategy.get("symbol", "")
    for pos in portfolio.get("positions", []):
        if pos.get("strategy_id") == strategy_id and pos.get("symbol") == symbol:
            failures.append(f"Gate 8: active position already exists for {strategy_id}/{symbol}")
            break

    # Gate 9: Data not stale
    if snapshot.get("data_quality", {}).get("is_stale", False):
        failures.append("Gate 9: snapshot is_stale=True")

    return len(failures) == 0, failures


# ---------------------------------------------------------------------------
# Signal: Trend Reclaim 4H — spec strategy signal_engine
# ---------------------------------------------------------------------------

def _evaluate_trend_reclaim_4H(
    snapshot: dict,
    strategy: dict,
) -> dict | None:
    """
    Entry signal: 4H close above MA20 with ADX > 25 and positive MA slope.
    Returns signal dict or None if no signal.
    """
    ind  = snapshot.get("indicators", {})
    bars = snapshot.get("bars", {})

    price     = ind.get("last_price")
    ma20      = ind.get("ma_20_value")
    ma50      = ind.get("ma_50_value")
    adx       = ind.get("adx_14", 0.0)
    ma_slope  = ind.get("ma_20_slope", 0.0)
    atr_4h    = ind.get("atr_14_4H", 40.0)
    atr_1h    = ind.get("atr_14_1H", 15.0)

    if price is None or ma20 is None:
        return None

    adx_min    = strategy.get("signal", {}).get("adx_min", 25)
    stop_mult  = strategy.get("signal", {}).get("stop_atr_multiple", 1.5)
    tp_mult    = strategy.get("signal", {}).get("tp_atr_multiple", 1.5)

    # LONG: price above MA20, ADX confirming trend, positive slope
    if price > ma20 and adx >= adx_min and ma_slope > 0:
        stop_dist = atr_4h * stop_mult
        tp_dist   = atr_4h * tp_mult
        return {
            "side":       "BUY",
            "stop_price": round(price - stop_dist, 2),
            "tp_price":   round(price + tp_dist, 2),
            "stop_dist":  round(stop_dist, 4),
            "tp_dist":    round(tp_dist, 4),
            "atr_used":   atr_4h,
            "direction":  "LONG",
        }

    # SHORT: price below MA20, ADX confirming trend, negative slope
    if price < ma20 and adx >= adx_min and ma_slope < 0:
        stop_dist = atr_4h * stop_mult
        tp_dist   = atr_4h * tp_mult
        return {
            "side":       "SELL",
            "stop_price": round(price + stop_dist, 2),
            "tp_price":   round(price - tp_dist, 2),
            "stop_dist":  round(stop_dist, 4),
            "tp_dist":    round(tp_dist, 4),
            "atr_used":   atr_4h,
            "direction":  "SHORT",
        }

    return None


# ---------------------------------------------------------------------------
# Sizing (Steps 1–4 + incubation) — spec Section 10
# Phase 1: no regime/health multipliers; posture mod applied by Sentinel
# ---------------------------------------------------------------------------

def _suggest_sizing(
    strategy: dict,
    health: dict,
    regime: dict,
    snapshot: dict,
    signal: dict,
    equity: float,
) -> dict:
    """Compute C3PO's sizing suggestion (before Sentinel applies posture mod)."""
    base_risk_pct = strategy.get("risk_budget_pct", 0.50)
    base_risk_usd = equity * base_risk_pct / 100.0

    # Regime modifier (Phase 2)
    regime_mod = regime.get("risk_multiplier", 1.0)

    # Health modifier
    health_mod = {
        C.HealthAction.NORMAL:    1.0,
        C.HealthAction.HALF_SIZE: 0.5,
        C.HealthAction.DISABLE:   0.0,
    }.get(health.get("action", C.HealthAction.NORMAL), 1.0)

    # Session modifier
    session = snapshot.get("session_state", C.SessionState.CORE)
    session_mod = 0.5 if session == C.SessionState.EXTENDED else 1.0

    # Incubation modifier
    incub = strategy.get("incubation", {})
    incub_mod = (incub.get("incubation_size_pct", 5) / 100.0) if incub.get("is_incubating") else 1.0

    final_risk_usd = base_risk_usd * regime_mod * health_mod * session_mod * incub_mod

    # Contract sizing
    stop_dist_pts  = signal["stop_dist"]
    point_val      = strategy.get("point_value_usd", 50.0)
    micro_pv       = strategy.get("micro_point_value_usd", 5.0)
    micro_avail    = strategy.get("micro_available", False)

    risk_per_c     = stop_dist_pts * point_val
    contracts      = math.floor(final_risk_usd / risk_per_c) if risk_per_c > 0 else 0
    use_micro      = False

    if contracts == 0 and micro_avail:
        micro_risk = stop_dist_pts * micro_pv
        contracts  = math.floor(final_risk_usd / micro_risk) if micro_risk > 0 else 0
        use_micro  = contracts > 0

    actual_pv     = micro_pv if use_micro else point_val
    risk_at_stop  = stop_dist_pts * actual_pv * contracts if contracts > 0 else 0.0
    risk_pct      = risk_at_stop / equity * 100.0 if equity > 0 else 0.0

    return {
        "risk_per_contract_usd":   round(stop_dist_pts * actual_pv, 2),
        "contracts_suggested":     contracts,
        "use_micro":               use_micro,
        "risk_pct_suggested":      round(base_risk_pct, 4),
        "risk_pct_after_health":   round(base_risk_pct * regime_mod * health_mod * session_mod * incub_mod, 4),
        "risk_multiplier_regime":  regime_mod,
        "risk_multiplier_health":  health_mod,
        "risk_multiplier_session": session_mod,
        "final_risk_usd":          round(final_risk_usd, 2),
    }


# ---------------------------------------------------------------------------
# Build intent — spec 5.6
# ---------------------------------------------------------------------------

def _build_intent(
    strategy: dict,
    signal: dict,
    sizing: dict,
    snapshot: dict,
    regime: dict,
    health: dict,
    run_id: str,
    param_version: str,
) -> dict:
    now       = datetime.now(timezone.utc)
    intent_id = IDs.make_intent_id()
    session   = snapshot.get("session_state", C.SessionState.CORE)
    price     = snapshot.get("indicators", {}).get("last_price", 0.0)
    adx       = snapshot.get("indicators", {}).get("adx_14", 0.0)
    ma20      = snapshot.get("indicators", {}).get("ma_20_value", 0.0)

    tick_size = strategy.get("tick_size", 0.25)

    stop_price = signal["stop_price"]
    tp_price   = signal["tp_price"]
    stop_dist  = signal["stop_dist"]
    tp_dist    = signal["tp_dist"]

    # Expiry: next 15-min boundary
    slot_start = now.replace(minute=(now.minute // 15) * 15, second=0, microsecond=0)
    expires_at = slot_start + timedelta(minutes=15)

    thesis = (
        f"4H close {'above' if signal['side'] == 'BUY' else 'below'} MA20 ({ma20:.2f})"
        f" with ADX {adx:.1f} > {strategy['signal']['adx_min']};"
        f" price {price:.2f} {'reclaiming trend structure' if signal['side'] == 'BUY' else 'breaking below'};"
        f" session={session}; health={health['health_score']:.2f} {health['action']}"
    )

    sym  = strategy.get("micro_symbol") if sizing.get("use_micro") else strategy.get("symbol", "ES")
    pv   = strategy.get("micro_point_value_usd") if sizing.get("use_micro") else strategy.get("point_value_usd", 50.0)
    tv   = strategy.get("micro_tick_value_usd") if sizing.get("use_micro") else strategy.get("tick_value_usd", 12.50)

    return {
        "intent_id":    intent_id,
        "run_id":       run_id,
        "param_version": param_version,
        "strategy_id":  strategy["strategy_id"],
        "intent_type":  C.IntentType.ENTRY,
        "symbol":       sym,
        "contract_month": strategy.get("contract_month", ""),
        "side":         signal["side"],
        "thesis":       thesis,
        "entry_plan":   {"type": "MARKET", "price": price},
        "stop_plan": {
            "type":                  "STOP_MARKET",
            "price":                 stop_price,
            "distance_points":       round(stop_dist, 4),
            "distance_ticks":        int(stop_dist / tick_size),
            "distance_atr_multiple": round(stop_dist / signal["atr_used"], 4),
        },
        "take_profit_plan": {
            "type":                "LIMIT",
            "price":               tp_price,
            "distance_points":     round(tp_dist, 4),
            "distance_ticks":      int(tp_dist / tick_size),
            "reward_risk_ratio":   round(tp_dist / stop_dist, 4) if stop_dist > 0 else 0.0,
        },
        "sizing": sizing,
        "time_in_force":            "GTC",
        "session_state_at_creation": session,
        "created_at":               now.isoformat(),
        "expires_at":               expires_at.isoformat(),
        "state":                    C.IntentState.PROPOSED,
    }


# ---------------------------------------------------------------------------
# Roll intent — spec 6.10
# ---------------------------------------------------------------------------

def _build_roll_intent(
    strategy: dict,
    position: dict,
    snapshot: dict,
    run_id: str,
    param_version: str,
) -> dict:
    intent_id = IDs.make_intent_id()
    sym = strategy.get("symbol", "ES")
    cur_month  = position.get("contract_month", strategy.get("contract_month", ""))
    next_month = next_contract_month(sym, cur_month)

    return {
        "intent_id":     intent_id,
        "run_id":        run_id,
        "param_version": param_version,
        "strategy_id":   strategy["strategy_id"],
        "intent_type":   C.IntentType.ROLL,
        "symbol":        sym,
        "position_id":   position.get("position_id"),
        "roll_from":     position.get("contract_month", cur_month),
        "roll_to":       next_month,
        "current_contracts": position.get("contracts", 1),
        "side":          "BUY" if position.get("side") == "LONG" else "SELL",
        "entry_price":   position.get("entry_price"),
        "stop_price":    position.get("stop_price"),
        "take_profit_price": position.get("take_profit_price"),
        "estimated_calendar_spread_usd": None,
        "estimated_roll_cost_total_usd": None,
        "reason":        f"{strategy.get('roll_days_before_expiry', 5)} days to expiry; standard roll window",
        "created_at":    datetime.now(timezone.utc).isoformat(),
        "state":         C.IntentState.PROPOSED,
    }


# ---------------------------------------------------------------------------
# Signal dispatch table
# ---------------------------------------------------------------------------

_SIGNAL_HANDLERS = {
    "trend_reclaim_4H_ES":  _evaluate_trend_reclaim_4H,
    "trend_reclaim_4H_NQ":  _evaluate_trend_reclaim_4H,
    "trend_reclaim_4H_BTC": _evaluate_trend_reclaim_4H,
    "trend_reclaim_4H_CL":  _evaluate_trend_reclaim_4H,
    "trend_reclaim_4H_GC":  _evaluate_trend_reclaim_4H,
    "trend_reclaim_4H_ZB":  _evaluate_trend_reclaim_4H,
}


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_brain(
    snapshots: dict[str, dict],
    run_id: str,
    param_version: str = "PV_0001",
    watchtower_status: str = C.WatchtowerStatus.HEALTHY,
) -> tuple[list[dict], dict | None, dict[str, dict]]:
    """
    Run the C3PO evaluation cycle.
    Returns (intents, regime_report, health_by_strategy) for Sentinel sizing.
    """
    registry  = store.load_strategy_registry()
    portfolio = store.load_portfolio()
    posture_state = store.load_posture_state()
    posture   = posture_state.get("posture", C.Posture.NORMAL)
    equity    = portfolio["account"]["equity_usd"]

    intents: list[dict] = []
    regime_report: dict | None = None
    health_by_strategy: dict[str, dict] = {}

    for strategy_id, strategy in registry.items():
        if strategy.get("status") not in (C.StrategyStatus.ACTIVE, C.StrategyStatus.INCUBATING):
            continue

        symbol = strategy.get("symbol", "ES")
        micro  = strategy.get("micro_symbol")
        snap   = snapshots.get(symbol) or snapshots.get(micro) or next(iter(snapshots.values()), None)
        if snap is None:
            continue

        # Compute regime and health reports
        regime = _compute_regime_for_snapshot(snap, portfolio, param_version, run_id)
        health = _evaluate_strategy_health(strategy, param_version)
        if regime_report is None:
            regime_report = regime
        health_by_strategy[strategy_id] = health

        # Log reports
        ledger.append(C.EventType.REGIME_COMPUTED, run_id, regime["report_id"], regime)
        ledger.append(C.EventType.HEALTH_COMPUTED, run_id,
                      f"HLT_{strategy_id}", health)

        # Check for rollover BEFORE gate check (rollover is independent of gates)
        days_exp = snap.get("contract", {}).get("days_to_expiry", 999)
        roll_win = strategy.get("roll_days_before_expiry", 5)
        if days_exp <= roll_win:
            for pos in portfolio.get("positions", []):
                if pos.get("strategy_id") == strategy_id:
                    roll = _build_roll_intent(strategy, pos, snap, run_id, param_version)
                    ledger.append(C.EventType.INTENT_CREATED, run_id, roll["intent_id"], roll)
                    intents.append(roll)
            continue  # No new entries when rolling

        # Gate check
        gates_ok, gate_failures = _check_gates(
            strategy, health, snap, portfolio, posture, watchtower_status, run_id,
            regime=regime,
        )
        if not gates_ok:
            continue  # Log failure reason without intent

        # Evaluate signal
        handler = _SIGNAL_HANDLERS.get(strategy_id)
        if handler is None:
            continue
        signal = handler(snap, strategy)
        if signal is None:
            continue  # No signal this cycle

        # Size the trade
        sizing = _suggest_sizing(strategy, health, regime, snap, signal, equity)
        if sizing.get("contracts_suggested", 0) == 0:
            continue

        # Build and log intent
        intent = _build_intent(strategy, signal, sizing, snap, regime, health,
                               run_id, param_version)
        ledger.append(C.EventType.INTENT_CREATED, run_id, intent["intent_id"], intent)
        intents.append(intent)

    return intents, regime_report, health_by_strategy
