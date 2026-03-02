#!/usr/bin/env python3
"""Sentinel — Risk & Governance Officer — spec Section 7.

Phase 1 scope: hard risk limits + idempotency + sizing.
Posture state machine (Phase 2 item) reads posture from state but does NOT
auto-escalate/recover in Phase 1 (all transitions require manual trigger or Phase 2 code).

Public API:
    run_sentinel(intents, snapshots, run_id, param_version) -> list[approval]
"""

from __future__ import annotations
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))
from shared import contracts as C
from shared import identifiers as IDs
from shared import ledger
from shared import state_store as store

# Add forge path for slippage model
sys.path.insert(0, str(Path(__file__).parent.parent / "workspace-forge"))
from slippage_model import estimate_slippage_ticks, compute_ev_ratio


# ---------------------------------------------------------------------------
# Sizing pipeline — spec Section 10
# ---------------------------------------------------------------------------

def calculate_contracts(
    final_risk_usd: float,
    stop_distance_points: float,
    point_value_usd: float,
    micro_available: bool = False,
    micro_point_value_usd: float = 5.0,
) -> tuple[int, bool]:
    """
    Calculate the number of contracts given a risk budget and stop distance.
    Returns (contracts, use_micro).
    Raises ValueError if budget is insufficient even for one micro contract.
    """
    if stop_distance_points <= 0 or final_risk_usd <= 0:
        raise ValueError("stop_distance_points and final_risk_usd must be positive")

    risk_per_contract = stop_distance_points * point_value_usd
    contracts = math.floor(final_risk_usd / risk_per_contract)

    if contracts >= 1:
        return contracts, False

    if micro_available:
        micro_risk = stop_distance_points * micro_point_value_usd
        micro_contracts = math.floor(final_risk_usd / micro_risk)
        if micro_contracts >= 1:
            return micro_contracts, True
        raise ValueError(
            f"Risk budget ${final_risk_usd:.0f} insufficient for 1 micro contract "
            f"(need ${micro_risk:.0f})"
        )

    raise ValueError(
        f"Risk budget ${final_risk_usd:.0f} insufficient for 1 contract "
        f"(need ${risk_per_contract:.0f}); no micro available"
    )


def validate_margin(
    contracts: int,
    use_micro: bool,
    margin_per_contract: float,
    micro_margin_per_contract: float,
    current_margin_used: float,
    equity: float,
    posture: str,
    sp: dict,
) -> int:
    """
    Iteratively reduce contracts until margin fits within posture-based limit.
    Returns final contract count (0 = deny).
    """
    max_margin_pct = sp.get("max_margin_utilization_pct", 40.0)

    # Posture-based limit reduction
    posture_limit = {
        C.Posture.NORMAL:    max_margin_pct,
        C.Posture.CAUTION:   30.0,
        C.Posture.DEFENSIVE: 20.0,
        C.Posture.HALT:      0.0,
    }.get(posture, max_margin_pct)

    per_contract = micro_margin_per_contract if use_micro else margin_per_contract
    if per_contract <= 0:
        return 0  # No margin data — cannot validate, deny

    while contracts > 0:
        new_margin   = current_margin_used + contracts * per_contract
        utilization  = (new_margin / equity * 100.0) if equity > 0 else 100.0
        if utilization <= posture_limit:
            break
        contracts -= 1

    return contracts


# ---------------------------------------------------------------------------
# Idempotency checks — spec 7.7
# ---------------------------------------------------------------------------

def check_idempotency(intent: dict, portfolio: dict) -> tuple[bool, str]:
    """
    Four idempotency checks.  Returns (passed, reason).
    Pass = no duplicate found.
    """
    intent_id   = intent.get("intent_id", "")
    strategy_id = intent.get("strategy_id", "")
    symbol      = intent.get("symbol", "")
    side        = intent.get("side", "BUY")
    position_side = "LONG" if side == "BUY" else "SHORT"

    # Check 1: intent_id already in ledger as approved/sent/filled
    terminal_types = {
        C.EventType.APPROVAL_ISSUED,
        C.EventType.ORDER_SENT,
        C.EventType.ORDER_FILLED,
        C.EventType.BRACKET_CONFIRMED,
    }
    for entry in ledger.query(event_types=list(terminal_types), limit=5_000):
        p = entry.get("payload", {})
        if p.get("intent_id") == intent_id:
            return False, f"Duplicate: intent_id {intent_id} already processed (seq={entry['ledger_seq']})"

    # Check 2: active position for same strategy + symbol + side (skip if ROLL targeting that position)
    for pos in portfolio.get("positions", []):
        if (pos.get("strategy_id") == strategy_id
                and pos.get("symbol") == symbol
                and pos.get("side") == position_side):
            if intent.get("intent_type") == C.IntentType.ROLL and pos.get("position_id") == intent.get("position_id"):
                break  # This is the position we're rolling — allow
            return False, f"Active position already exists for {strategy_id}/{symbol}/{position_side}"

    # Check 3: conflicting pending intent (same strategy+symbol, non-terminal, NOT this intent)
    for entry in ledger.query(event_types=[C.EventType.INTENT_CREATED], limit=2_000):
        p = entry.get("payload", {})
        if (p.get("intent_id") != intent_id
                and p.get("strategy_id") == strategy_id
                and p.get("symbol") == symbol
                and p.get("state") not in C.IntentState.TERMINAL):
            return False, f"Conflicting pending intent {p.get('intent_id')} for {strategy_id}/{symbol}"

    # Check 4: rapid-fire guard — same strategy approved within 60 sec
    now = datetime.now(timezone.utc)
    for entry in ledger.query(event_types=[C.EventType.APPROVAL_ISSUED], limit=200):
        p = entry.get("payload", {})
        if p.get("strategy_id") != strategy_id:
            continue
        ts_str = entry.get("timestamp", "")
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        except ValueError:
            continue
        age = (now - ts).total_seconds()
        if age < 60:
            return False, f"Rapid-fire guard: approval for {strategy_id} issued {age:.0f}s ago (< 60s)"

    return True, ""


# ---------------------------------------------------------------------------
# Hard risk limit checks — spec 7.5 (Rules 1-13)
# ---------------------------------------------------------------------------

def _run_hard_checks(
    intent: dict,
    contracts: int,
    use_micro: bool,
    strategy: dict,
    portfolio: dict,
    snapshot: dict,
    posture: str,
    sp: dict,
) -> tuple[list[dict], list[dict], list[str]]:
    """
    Run all 13 hard rules.
    Returns (passed_checks, failed_checks, warnings).
    """
    passed:   list[dict] = []
    failed:   list[dict] = []
    warnings: list[str]  = []

    equity = portfolio["account"]["equity_usd"]

    def check(rule: str, value: float, limit: float, unit: str, ok: bool, *, deny_on_fail: bool = True):
        rec = {"rule": rule, "value": value, "limit": limit, "unit": unit}
        if ok:
            passed.append(rec)
        else:
            if deny_on_fail:
                failed.append(rec)
            else:
                warnings.append(f"{rule}: {value}{unit} approaching {limit}{unit}")
                passed.append(rec)

    point_value = (strategy.get("micro_point_value_usd", 5.0) if use_micro
                   else strategy.get("point_value_usd", 50.0))
    tick_size   = strategy.get("tick_size", 0.25)
    tick_value  = (strategy.get("micro_tick_value_usd", 1.25) if use_micro
                   else strategy.get("tick_value_usd", 12.50))
    # Use intent entry price as primary source; fall back to last 1H bar close
    intent_entry = intent.get("entry_plan", {}).get("price", 0.0)
    bar_fallback = snapshot["bars"]["1H"][-1]["c"] if snapshot.get("bars", {}).get("1H") else 0.0
    entry_ref = intent_entry if intent_entry else bar_fallback
    stop_dist   = abs(entry_ref - intent["stop_plan"]["price"])
    tp_dist     = abs(intent["take_profit_plan"]["price"] - entry_ref)

    stop_dist_ticks = stop_dist / tick_size if tick_size > 0 else 0
    tp_dist_ticks   = tp_dist   / tick_size if tick_size > 0 else 0

    risk_at_stop_usd  = stop_dist * point_value * contracts
    risk_at_stop_pct  = risk_at_stop_usd / equity * 100.0 if equity > 0 else 100.0

    posture_mods = {
        C.Posture.NORMAL:    1.0,
        C.Posture.CAUTION:   0.6,
        C.Posture.DEFENSIVE: 0.25,
        C.Posture.HALT:      0.0,
    }
    pm = posture_mods.get(posture, 1.0)

    # Rule 1: Max risk per trade
    max_risk_per_trade = sp.get("max_risk_per_trade_pct", 1.0) * pm
    check("max_risk_per_trade", round(risk_at_stop_pct, 4), max_risk_per_trade, "%",
          risk_at_stop_pct <= max_risk_per_trade)

    # Rule 2: Max open portfolio risk
    heat      = portfolio.get("heat", {})
    open_risk = heat.get("total_open_risk_usd", 0.0) + risk_at_stop_usd
    open_pct  = open_risk / equity * 100.0 if equity > 0 else 100.0
    max_open  = sp.get("max_open_risk_pct", 5.0) * pm
    check("max_open_risk", round(open_pct, 4), max_open, "%", open_pct <= max_open)

    # Rule 3: Daily loss cap (max_daily_loss_pct is positive; daily_pnl is negative when losing)
    daily_pnl = portfolio.get("pnl", {}).get("total_today_pct", 0.0)
    max_daily = sp.get("max_daily_loss_pct", 3.0)
    check("daily_loss_cap", round(daily_pnl, 4), -abs(max_daily), "%", daily_pnl >= -abs(max_daily))

    # Rule 4: Portfolio drawdown cap (max_portfolio_dd_pct is positive; dd_pct is positive)
    dd_pct  = portfolio.get("pnl", {}).get("portfolio_dd_pct", 0.0)
    max_dd  = sp.get("max_portfolio_dd_pct", 15.0)
    check("portfolio_dd_cap", round(dd_pct, 4), abs(max_dd), "%", dd_pct <= abs(max_dd))

    # Rule 5: Projected margin utilization
    margin_used  = portfolio["account"].get("margin_used_usd", 0.0)
    margin_per_c = (strategy.get("micro_margin_per_contract_usd", 1584.0) if use_micro
                    else strategy.get("margin_per_contract_usd", 15840.0))
    new_margin   = margin_used + contracts * margin_per_c
    new_util_pct = (new_margin / equity * 100.0) if equity > 0 else 100.0
    max_margin   = sp.get("max_margin_utilization_pct", 40.0) * pm
    check("margin_utilization", round(new_util_pct, 2), max_margin, "%", new_util_pct <= max_margin)

    # Rule 6: Cluster exposure
    cg = strategy.get("correlation_group", "uncategorized")
    cluster      = heat.get("cluster_exposure", {}).get(cg, {})
    cluster_risk = cluster.get("risk_usd", 0.0) + risk_at_stop_usd
    cluster_pct  = cluster_risk / equity * 100.0 if equity > 0 else 100.0
    max_cluster  = sp.get("max_cluster_exposure_pct", 3.0)
    check("cluster_exposure", round(cluster_pct, 4), max_cluster, "%", cluster_pct <= max_cluster)

    # Rule 7: Single-instrument exposure
    instr_risk = sum(
        p.get("risk_at_stop_usd", 0)
        for p in portfolio.get("positions", [])
        if p.get("symbol") == intent.get("symbol")
    ) + risk_at_stop_usd
    instr_pct  = instr_risk / equity * 100.0 if equity > 0 else 100.0
    max_instr  = sp.get("max_instrument_exposure_pct", 2.0)
    check("instrument_exposure", round(instr_pct, 4), max_instr, "%", instr_pct <= max_instr)

    # Rule 8: Intra-cluster correlation (Phase 2: enforce)
    corr_20d = heat.get("correlations_20d", {})
    max_corr  = sp.get("max_intra_cluster_corr", 0.85)
    for pair, corr in corr_20d.items():
        if corr > max_corr:
            failed.append({"rule": "max_intra_cluster_corr", "value": corr,
                           "limit": max_corr, "unit": "", "pair": pair})

    # Rule 9: Max concurrent open strategies
    open_strategies = len({p.get("strategy_id") for p in portfolio.get("positions", [])})
    # count current strategy as +1 if not already open
    if intent.get("strategy_id") not in {p.get("strategy_id") for p in portfolio.get("positions", [])}:
        open_strategies += 1
    max_strat = sp.get("max_concurrent_strategies", 4)
    check("max_concurrent_strategies", open_strategies, max_strat, "",
          open_strategies <= max_strat)

    # Rule 10: Slippage
    vol_pct = snapshot.get("external", {}).get("vix_percentile_252d", 0.5)
    session = snapshot.get("session_state", C.SessionState.CORE)
    depth   = snapshot.get("microstructure", {}).get("avg_book_depth_contracts", 850)
    slip_ticks = estimate_slippage_ticks(contracts, vol_pct, session, depth)
    max_slip   = sp.get("max_slippage_ticks", 4)
    check("max_slippage", slip_ticks, max_slip, " ticks", slip_ticks <= max_slip)

    # Rule 11: Min reward:risk ratio
    rr_ratio  = tp_dist / stop_dist if stop_dist > 0 else 0.0
    min_rr    = sp.get("min_reward_risk_ratio", 0.8)
    check("min_reward_risk", round(rr_ratio, 4), min_rr, "", rr_ratio >= min_rr)

    # Rule 12: Max intent age
    created_at = intent.get("created_at", "")
    max_age    = sp.get("max_intent_age_sec", 900)
    age_sec    = 0.0
    if created_at:
        try:
            t    = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            age_sec = (datetime.now(timezone.utc) - t).total_seconds()
        except ValueError:
            pass
    check("max_intent_age", round(age_sec, 0), max_age, "s", age_sec <= max_age)

    # Rule 13: Max hold time — enforce at reconciliation, not entry; warn if strategy max_hold_bars exceeded
    # (No deny at entry; position hold time is checked in reconcile)
    max_hold_bars = strategy.get("max_hold_bars", 20)

    # Slippage EV check
    ev = compute_ev_ratio(tp_dist_ticks, stop_dist_ticks, slip_ticks)
    ev_min = 0.5
    check("slippage_ev", round(ev, 4), ev_min, "", ev >= ev_min)

    return passed, failed, warnings


# ---------------------------------------------------------------------------
# Exit / flatten fast-path (always allowed)
# ---------------------------------------------------------------------------

def _approve_exit(intent: dict, approval_id: str, run_id: str, sp: dict,
                   posture: str = "NORMAL") -> dict:
    return {
        "approval_id":     approval_id,
        "intent_id":       intent["intent_id"],
        "strategy_id":     intent.get("strategy_id", ""),
        "symbol":          intent.get("symbol", ""),
        "run_id":          run_id,
        "param_version":   intent.get("param_version", "PV_0001"),
        "decision":        C.RiskDecision.APPROVE,
        "sentinel_posture": posture,
        "intent_type":     intent.get("intent_type"),
        "side":            intent.get("side"),
        "sizing_final": {
            "contracts_allowed": intent.get("sizing", {}).get("contracts_suggested", 1),
            "final_risk_pct":    0.0,
            "reduction_reason":  None,
        },
        "constraints": {
            "max_slippage_ticks":         sp.get("max_slippage_ticks", 4),
            "max_time_to_fill_sec":       15,
            "reduce_if_spread_ticks_gt":  2,
        },
        "stop_plan":          intent.get("stop_plan", {}),
        "take_profit_plan":   intent.get("take_profit_plan", {}),
        "checks":    {"passed": [], "failed": [], "warnings": []},
        "reasons":   [],
        "approved_at": datetime.now(timezone.utc).isoformat(),
        "state":       C.IntentState.APPROVED,
    }


def _approve_roll(intent: dict, approval_id: str, run_id: str, sp: dict,
                   posture: str = "NORMAL") -> dict:
    """Phase 3: Approve roll intent — same contracts, new contract month."""
    contracts = intent.get("current_contracts", 1)
    return {
        "approval_id":     approval_id,
        "intent_id":       intent["intent_id"],
        "strategy_id":     intent.get("strategy_id", ""),
        "symbol":          intent.get("symbol", ""),
        "run_id":          run_id,
        "param_version":   intent.get("param_version", "PV_0001"),
        "decision":        C.RiskDecision.APPROVE,
        "sentinel_posture": posture,
        "intent_type":     C.IntentType.ROLL,
        "side":            intent.get("side"),
        "position_id":     intent.get("position_id"),
        "roll_from":       intent.get("roll_from"),
        "roll_to":         intent.get("roll_to"),
        "sizing_final": {
            "contracts_allowed": contracts,
            "use_micro":         False,
            "final_risk_pct":    0.0,
            "reduction_reason":  None,
        },
        "constraints": {
            "max_slippage_ticks":         sp.get("max_slippage_ticks", 4),
            "max_time_to_fill_sec":       15,
            "reduce_if_spread_ticks_gt":  2,
        },
        "stop_plan":          {"price": intent.get("stop_price")},
        "take_profit_plan":   {"price": intent.get("take_profit_price")},
        "checks":    {"passed": [], "failed": [], "warnings": []},
        "reasons":   [],
        "approved_at": datetime.now(timezone.utc).isoformat(),
        "state":       C.IntentState.APPROVED,
    }


# ---------------------------------------------------------------------------
# Intent evaluation
# ---------------------------------------------------------------------------

def evaluate_intent(
    intent: dict,
    portfolio: dict,
    snapshot: dict,
    posture: str,
    run_id: str,
    param_version: str = "PV_0001",
    regime_report: dict | None = None,
    health_by_strategy: dict[str, dict] | None = None,
) -> dict:
    """
    Evaluate one trade intent.  Returns a risk decision dict.
    """
    params  = store.load_params(param_version)
    sp      = params.get("sentinel", {})
    sizing  = params.get("sizing", {})

    intent_id   = intent.get("intent_id", IDs.make_intent_id())
    intent_type = intent.get("intent_type", C.IntentType.ENTRY)
    strategy_id = intent.get("strategy_id", "")
    approval_id = IDs.make_approval_id()

    # --- EXIT / FLATTEN / SCALE_OUT: always allowed ---
    if intent_type in C.IntentType.RELAXED:
        decision = _approve_exit(intent, approval_id, run_id, sp, posture=posture)
        ledger.append(C.EventType.APPROVAL_ISSUED, run_id, approval_id, decision)
        return decision

    # --- ROLL: approve with posture/margin checks (Phase 3) ---
    if intent_type == C.IntentType.ROLL:
        # HALT posture → deny roll (force close instead)
        if posture == C.Posture.HALT:
            reason = "Posture HALT blocks roll — position should be closed instead"
            deny = _deny(intent, approval_id, run_id, reason, sp, posture=posture)
            ledger.append(C.EventType.INTENT_DENIED, run_id, intent_id, deny)
            return deny
        # Margin validation for roll
        roll_strategy = store.load_strategy_registry().get(strategy_id, {})
        contracts = intent.get("current_contracts", 1)
        use_micro = False
        margin_ok = validate_margin(
            contracts=contracts,
            use_micro=use_micro,
            margin_per_contract=roll_strategy.get("margin_per_contract_usd", 15840.0),
            micro_margin_per_contract=roll_strategy.get("micro_margin_per_contract_usd", 1584.0),
            current_margin_used=portfolio["account"].get("margin_used_usd", 0.0),
            equity=portfolio["account"]["equity_usd"],
            posture=posture,
            sp=sp,
        )
        if margin_ok == 0:
            reason = "Margin insufficient for roll — deny"
            deny = _deny(intent, approval_id, run_id, reason, sp, posture=posture)
            ledger.append(C.EventType.INTENT_DENIED, run_id, intent_id, deny)
            return deny
        decision = _approve_roll(intent, approval_id, run_id, sp, posture=posture)
        ledger.append(C.EventType.APPROVAL_ISSUED, run_id, approval_id, decision)
        return decision

    # --- DEFENSIVE/HALT blocks new entries ---
    if posture in (C.Posture.DEFENSIVE, C.Posture.HALT):
        if intent_type == C.IntentType.ENTRY:
            reason = f"Posture {posture} blocks new entries"
            deny   = _deny(intent, approval_id, run_id, reason, sp, posture=posture)
            ledger.append(C.EventType.INTENT_DENIED, run_id, intent_id, deny)
            return deny

    # --- Idempotency checks ---
    idem_ok, idem_reason = check_idempotency(intent, portfolio)
    if not idem_ok:
        deny = _deny(intent, approval_id, run_id, idem_reason, sp, posture=posture)
        ledger.append(C.EventType.INTENT_DENIED, run_id, intent_id, deny)
        return deny

    # --- Load strategy ---
    registry = store.load_strategy_registry()
    strategy = registry.get(strategy_id, {})
    if not strategy:
        deny = _deny(intent, approval_id, run_id, f"Unknown strategy_id: {strategy_id}", sp, posture=posture)
        ledger.append(C.EventType.INTENT_DENIED, run_id, intent_id, deny)
        return deny

    equity    = portfolio["account"]["equity_usd"]

    # --- Compute risk budget ---
    base_risk_pct = strategy.get("risk_budget_pct", 0.5)
    base_risk_usd = equity * base_risk_pct / 100.0

    # Regime modifier (Phase 2) — from brain's regime report
    regime_mod = 1.0
    if regime_report:
        regime_mod = regime_report.get("risk_multiplier", 1.0)

    # Health modifier — from brain's health report for this strategy
    health_mod = 1.0
    if health_by_strategy and strategy_id in health_by_strategy:
        h = health_by_strategy[strategy_id]
        health_mod = {
            C.HealthAction.NORMAL:    1.0,
            C.HealthAction.HALF_SIZE: 0.5,
            C.HealthAction.DISABLE:   0.0,
        }.get(h.get("action", C.HealthAction.NORMAL), 1.0)

    posture_mod = {
        C.Posture.NORMAL:    sizing.get("posture_modifier_normal",    1.0),
        C.Posture.CAUTION:   sizing.get("posture_modifier_caution",   0.6),
        C.Posture.DEFENSIVE: sizing.get("posture_modifier_defensive", 0.25),
        C.Posture.HALT:      0.0,
    }.get(posture, 1.0)

    # Session modifier
    session = snapshot.get("session_state", C.SessionState.CORE)
    session_mod = sizing.get("session_modifier_extended", 0.5) \
                  if session == C.SessionState.EXTENDED else 1.0

    # Incubation modifier
    incub = strategy.get("incubation", {})
    incub_mod = (incub.get("incubation_size_pct", 5) / 100.0) if incub.get("is_incubating") else 1.0

    final_risk_usd = base_risk_usd * regime_mod * health_mod * posture_mod * session_mod * incub_mod

    # --- Size contracts ---
    stop_price  = intent.get("stop_plan", {}).get("price", 0.0)
    # Use intent entry price as primary source; fall back to last 1H bar close
    intent_entry_price = intent.get("entry_plan", {}).get("price", 0.0)
    bar_close_fallback = snapshot["bars"]["1H"][-1]["c"] if snapshot.get("bars", {}).get("1H") else 0.0
    entry_price = intent_entry_price if intent_entry_price else bar_close_fallback
    stop_dist   = abs(entry_price - stop_price)

    if stop_dist <= 0:
        deny = _deny(intent, approval_id, run_id, "Stop distance is zero", sp, posture=posture)
        ledger.append(C.EventType.INTENT_DENIED, run_id, intent_id, deny)
        return deny

    try:
        contracts, use_micro = calculate_contracts(
            final_risk_usd,
            stop_dist,                                       # price distance in points
            strategy.get("point_value_usd", 50.0),          # $/point for standard contract
            micro_available=strategy.get("micro_available", False),
            micro_point_value_usd=strategy.get("micro_point_value_usd", 5.0),
        )
    except ValueError as exc:
        deny = _deny(intent, approval_id, run_id, str(exc), sp, posture=posture)
        ledger.append(C.EventType.INTENT_DENIED, run_id, intent_id, deny)
        return deny

    # --- Margin validation ---
    contracts = validate_margin(
        contracts=contracts,
        use_micro=use_micro,
        margin_per_contract=strategy.get("margin_per_contract_usd", 15840.0),
        micro_margin_per_contract=strategy.get("micro_margin_per_contract_usd", 1584.0),
        current_margin_used=portfolio["account"].get("margin_used_usd", 0.0),
        equity=equity,
        posture=posture,
        sp=sp,
    )
    if contracts == 0:
        deny = _deny(intent, approval_id, run_id, "Margin limit exceeded after reduction", sp, posture=posture)
        ledger.append(C.EventType.INTENT_DENIED, run_id, intent_id, deny)
        return deny

    # --- Hard risk checks ---
    passed, failed, warnings = _run_hard_checks(
        intent, contracts, use_micro, strategy, portfolio, snapshot, posture, sp
    )
    if failed:
        fail_reasons = [f"{r['rule']}: {r['value']} > limit {r['limit']}" for r in failed]

        # Log missed opportunity before denying (Phase 2: simulate outcome)
        _track_missed_opportunity(intent, "; ".join(fail_reasons), posture, run_id,
                                  snapshot=snapshot, portfolio=portfolio)

        deny = _deny(intent, approval_id, run_id, "; ".join(fail_reasons), sp, posture=posture)
        deny["checks"] = {"passed": passed, "failed": failed, "warnings": warnings}
        ledger.append(C.EventType.INTENT_DENIED, run_id, intent_id, deny)
        return deny

    # --- Build approval ---
    point_value   = strategy.get("micro_point_value_usd" if use_micro else "point_value_usd", 50.0)
    risk_at_stop  = stop_dist * point_value * contracts
    final_risk_pct = risk_at_stop / equity * 100.0 if equity > 0 else 0.0

    orig_contracts = intent.get("sizing", {}).get("contracts_suggested", contracts)
    decision_type = (C.RiskDecision.APPROVE_REDUCED if contracts < orig_contracts
                     else C.RiskDecision.APPROVE)

    approval: dict[str, Any] = {
        "approval_id":     approval_id,
        "intent_id":       intent_id,
        "strategy_id":     strategy_id,
        "symbol":          intent.get("symbol", ""),
        "run_id":          run_id,
        "param_version":   param_version,
        "decision":        decision_type,
        "sentinel_posture": posture,
        "intent_type":     intent_type,
        "side":            intent.get("side"),
        "contract_month":  intent.get("contract_month", ""),
        "stop_plan":       intent.get("stop_plan", {}),
        "take_profit_plan": intent.get("take_profit_plan", {}),
        "sizing_final": {
            "contracts_allowed": contracts,
            "use_micro":         use_micro,
            "final_risk_pct":    round(final_risk_pct, 4),
            "reduction_reason":  (f"Reduced from {orig_contracts} to {contracts} contracts"
                                  if contracts < orig_contracts else None),
        },
        "constraints": {
            "max_slippage_ticks":        sp.get("max_slippage_ticks", 4),
            "max_time_to_fill_sec":      15,
            "reduce_if_spread_ticks_gt": 2,
            "execution_profile":         posture,
        },
        "checks": {"passed": passed, "failed": failed, "warnings": warnings},
        "reasons": warnings,
        "approved_at": datetime.now(timezone.utc).isoformat(),
        "state":       C.IntentState.APPROVED,
    }

    ledger.append(C.EventType.APPROVAL_ISSUED, run_id, approval_id, approval)
    return approval


# ---------------------------------------------------------------------------
# Missed opportunity tracking — spec 7.10
# ---------------------------------------------------------------------------

def _simulate_missed_outcome(intent: dict, snapshot: dict, portfolio: dict) -> tuple[str | None, float | None, float | None]:
    """
    Phase 2: Simulate what would have happened if we had taken the trade.
    Uses current bar high/low to check stop/TP. Returns (outcome, pnl_usd, pnl_pct).
    """
    stop_price = intent.get("stop_plan", {}).get("price")
    tp_price = intent.get("take_profit_plan", {}).get("price")
    side = intent.get("side", "BUY")
    contracts = intent.get("sizing", {}).get("contracts_suggested", 1)
    entry_price = snapshot.get("indicators", {}).get("last_price", 0.0)
    bars_1h = snapshot.get("bars", {}).get("1H", [])
    if not bars_1h or not stop_price or not tp_price:
        return None, None, None
    bar = bars_1h[-1]
    bar_high = bar.get("h", bar.get("high", entry_price))
    bar_low = bar.get("l", bar.get("low", entry_price))
    registry = store.load_strategy_registry()
    strategy = registry.get(intent.get("strategy_id", ""), {})
    pv = strategy.get("point_value_usd", 50.0)
    if intent.get("sizing", {}).get("use_micro"):
        pv = strategy.get("micro_point_value_usd", 5.0)
    exit_price = entry_price
    outcome = "OPEN"
    if side == "BUY":
        if bar_low <= stop_price:
            exit_price = stop_price
            outcome = "STOP_HIT"
        elif bar_high >= tp_price:
            exit_price = tp_price
            outcome = "TP_HIT"
    else:
        if bar_high >= stop_price:
            exit_price = stop_price
            outcome = "STOP_HIT"
        elif bar_low <= tp_price:
            exit_price = tp_price
            outcome = "TP_HIT"
    if side == "BUY":
        pnl = (exit_price - entry_price) * pv * contracts
    else:
        pnl = (entry_price - exit_price) * pv * contracts
    equity = portfolio.get("account", {}).get("equity_usd", 100_000)
    pnl_pct = (pnl / equity * 100.0) if equity > 0 else 0.0
    return outcome, round(pnl, 2), round(pnl_pct, 4)


def _track_missed_opportunity(
    intent: dict,
    deny_reason: str,
    posture: str,
    run_id: str,
    snapshot: dict | None = None,
    portfolio: dict | None = None,
) -> None:
    """Log a MISSED_OPPORTUNITY event. Phase 2: simulate outcome when snapshot available."""
    sim_outcome, sim_pnl, sim_pct = None, None, None
    if snapshot and portfolio:
        sim_outcome, sim_pnl, sim_pct = _simulate_missed_outcome(intent, snapshot, portfolio)
    ledger.append(C.EventType.MISSED_OPPORTUNITY, run_id, intent.get("intent_id", ""), {
        "intent_id":               intent.get("intent_id"),
        "strategy_id":             intent.get("strategy_id"),
        "symbol":                  intent.get("symbol"),
        "side":                    intent.get("side"),
        "stop_price":              intent.get("stop_plan", {}).get("price"),
        "tp_price":                intent.get("take_profit_plan", {}).get("price"),
        "deny_reason":             deny_reason,
        "sentinel_posture_at_deny": posture,
        "simulated_outcome":       sim_outcome,
        "simulated_pnl_usd":       sim_pnl,
        "simulated_pnl_pct":       sim_pct,
    })


# ---------------------------------------------------------------------------
# Deny helper
# ---------------------------------------------------------------------------

def _deny(intent: dict, approval_id: str, run_id: str, reason: str, sp: dict,
          posture: str = "NORMAL") -> dict:
    return {
        "approval_id":     approval_id,
        "intent_id":       intent.get("intent_id"),
        "strategy_id":     intent.get("strategy_id", ""),
        "symbol":          intent.get("symbol", ""),
        "run_id":          run_id,
        "param_version":   intent.get("param_version", "PV_0001"),
        "decision":        C.RiskDecision.DENY,
        "sentinel_posture": posture,
        "intent_type":     intent.get("intent_type"),
        "side":            intent.get("side"),
        "stop_plan":       intent.get("stop_plan", {}),
        "take_profit_plan": intent.get("take_profit_plan", {}),
        "sizing_final":    {"contracts_allowed": 0},
        "constraints":     {},
        "checks":          {"passed": [], "failed": [], "warnings": []},
        "reasons":         [reason],
        "denied_at":       datetime.now(timezone.utc).isoformat(),
        "state":           C.IntentState.DENIED,
    }


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_sentinel(
    intents: list[dict],
    snapshots: dict[str, dict],
    run_id: str,
    param_version: str = "PV_0001",
    regime_report: dict | None = None,
    health_by_strategy: dict[str, dict] | None = None,
) -> list[dict]:
    """
    Evaluate all intents.  Returns list of risk decisions.
    """
    portfolio = store.load_portfolio()
    posture_state = store.load_posture_state()
    posture = posture_state.get("posture", C.Posture.NORMAL)

    decisions: list[dict] = []
    health_by_strategy = health_by_strategy or {}

    for intent in intents:
        symbol   = intent.get("symbol", "ES")
        snapshot = snapshots.get(symbol, next(iter(snapshots.values()), {}))

        decision = evaluate_intent(
            intent,
            portfolio,
            snapshot,
            posture,
            run_id,
            param_version,
            regime_report=regime_report,
            health_by_strategy=health_by_strategy,
        )
        decisions.append(decision)

        # Refresh portfolio after each approval (in case of position changes)
        if decision.get("decision") in (C.RiskDecision.APPROVE, C.RiskDecision.APPROVE_REDUCED):
            portfolio = store.load_portfolio()

    return decisions
