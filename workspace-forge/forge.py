#!/usr/bin/env python3
"""Forge — Execution Engine — spec Section 8.

Executes approved orders exactly as instructed. No decisions. No creativity.
Fully idempotent and logged.

Public API:
    run_forge(approvals, snapshots, run_id, paper=True) -> list[receipt]
    process_bracket_triggers(snapshots, run_id, paper=True) -> list[closed]
    close_position(position, exit_result, run_id) -> None
"""

from __future__ import annotations
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Add workspace root to path
sys.path.insert(0, str(Path(__file__).parent.parent))
from shared import contracts as C
from shared import identifiers as IDs
from shared import ledger
from shared import state_store as store
from paper_broker import simulate_market_fill, check_bracket_triggers
from fees_model import exit_fee_usd
from slippage_model import estimate_slippage_ticks, slippage_usd


# ---------------------------------------------------------------------------
# Idempotency — spec 8.4 STEP 2
# ---------------------------------------------------------------------------

def _check_idempotency(idem_key: str) -> dict | None:
    """
    Return an existing receipt if this idempotency key was already used,
    else None.
    """
    entries = ledger.query(
        event_types=[C.EventType.ORDER_SENT, C.EventType.ORDER_FILLED,
                     C.EventType.BRACKET_CONFIRMED],
        limit=10_000,
    )
    for e in entries:
        if e.get("payload", {}).get("idempotency_key") == idem_key:
            return e.get("payload")
    return None


# ---------------------------------------------------------------------------
# Pre-flight checks — spec 8.4 STEP 3
# ---------------------------------------------------------------------------

def _preflight(approval: dict, snapshot: dict) -> tuple[bool, str]:
    """
    Run pre-execution checks. Returns (ok, reason).
    Checks: spread, approval age, HALT posture, exchange connectivity (paper: always OK).
    """
    # Check approval freshness
    approved_at = approval.get("approved_at", "")
    if approved_at:
        try:
            t = datetime.fromisoformat(approved_at.replace("Z", "+00:00"))
            age_sec = (datetime.now(timezone.utc) - t).total_seconds()
            if age_sec > approval.get("constraints", {}).get("max_intent_age_sec", 900):
                return False, f"Approval expired (age={age_sec:.0f}s)"
        except ValueError:
            pass

    # HALT posture blocks all entries
    posture = store.load_posture_state().get("posture", "NORMAL")
    if posture == C.Posture.HALT:
        intent_type = approval.get("intent_type", "ENTRY")
        if intent_type not in (C.IntentType.FLATTEN, C.IntentType.EXIT):
            return False, "System posture is HALT; only FLATTEN/EXIT allowed"

    # Spread check
    constraints = approval.get("constraints", {})
    max_spread = constraints.get("reduce_if_spread_ticks_gt", 2)
    spread = snapshot.get("microstructure", {}).get("spread_ticks", 0)
    if spread > max_spread:
        return False, f"Spread {spread} ticks exceeds constraint {max_spread}"

    return True, ""


# ---------------------------------------------------------------------------
# Bracket placement — spec 8.4 STEP 7 / 8.7
# ---------------------------------------------------------------------------

def _place_bracket(
    position: dict,
    approval: dict,
    run_id: str,
    paper: bool = True,
) -> tuple[dict | None, str]:
    """
    Place stop and take-profit bracket orders.
    Retries up to 3 times with 0.5s backoff.
    Returns (bracket_dict, error_msg). On failure: bracket_dict is None.
    """
    for attempt in range(1, 4):
        try:
            stop_order_id = IDs.make_order_id("ORD_STOP")
            tp_order_id   = IDs.make_order_id("ORD_TP")
            placed_at     = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

            bracket = {
                "stop": {
                    "order_id":          stop_order_id,
                    "type":              "STOP_MARKET",
                    "price":             position["stop_price"],
                    "status":            "ACTIVE",
                    "placed_at":         placed_at,
                    "placement_latency_ms": 100 * attempt,
                },
                "take_profit": {
                    "order_id":          tp_order_id,
                    "type":              "LIMIT",
                    "price":             position["take_profit_price"],
                    "status":            "ACTIVE",
                    "placed_at":         placed_at,
                    "placement_latency_ms": 120 * attempt,
                },
            }
            return bracket, ""
        except Exception as exc:
            if attempt < 3:
                time.sleep(0.5 * attempt)
            else:
                return None, str(exc)

    return None, "Bracket placement failed after 3 retries"


# ---------------------------------------------------------------------------
# Position registration — spec 8.4 STEP 8 / 5.5
# ---------------------------------------------------------------------------

def _register_position(
    approval: dict,
    fill: dict,
    bracket: dict,
    run_id: str,
) -> dict:
    """
    Add position to portfolio state.  Returns the position dict.
    """
    portfolio = store.load_portfolio()
    equity = portfolio["account"]["equity_usd"]

    strategy_id      = approval.get("strategy_id", "")
    symbol           = approval.get("symbol", "")
    contract_month   = approval.get("contract_month", "")
    side             = approval.get("side", "BUY")
    position_side    = "LONG" if side == "BUY" else "SHORT"
    contracts_filled = fill["contracts_filled"]
    entry_price      = fill["fill_price"]
    stop_price       = approval["stop_plan"]["price"]
    tp_price         = approval["take_profit_plan"]["price"]
    margin_req       = approval.get("margin_per_contract_usd", 0.0)
    point_value      = approval.get("point_value_usd", 50.0)
    correlation_group = approval.get("correlation_group", "")

    # Risk at stop: stop distance × point_value × contracts
    stop_distance = abs(entry_price - stop_price)
    risk_at_stop_usd = round(stop_distance * point_value * contracts_filled, 2)
    risk_at_stop_pct = round(risk_at_stop_usd / equity * 100.0, 4) if equity > 0 else 0.0

    total_margin = margin_req * contracts_filled
    pos_id = IDs.make_position_id()

    position: dict[str, Any] = {
        "position_id":       pos_id,
        "symbol":            symbol,
        "contract_month":    contract_month,
        "strategy_id":       strategy_id,
        "side":              position_side,
        "contracts":         contracts_filled,
        "entry_price":       entry_price,
        "current_price":     entry_price,
        "stop_price":        stop_price,
        "take_profit_price": tp_price,
        "unrealized_pnl_usd": 0.0,
        "risk_at_stop_usd":  risk_at_stop_usd,
        "risk_at_stop_pct":  risk_at_stop_pct,
        "margin_used_usd":   total_margin,
        "opened_at":         datetime.now(timezone.utc).isoformat(),
        "bars_held":         0,
        "correlation_group": correlation_group,
        "point_value_usd":   point_value,
        "bracket_status": {
            "stop_order_id":  bracket["stop"]["order_id"],
            "stop_status":    "ACTIVE",
            "tp_order_id":    bracket["take_profit"]["order_id"],
            "tp_status":      "ACTIVE",
        },
    }

    # Update portfolio
    portfolio["positions"].append(position)

    acct = portfolio["account"]
    acct["margin_used_usd"]        = round(acct.get("margin_used_usd", 0.0) + total_margin, 2)
    acct["cash_usd"]               = round(acct.get("cash_usd", equity) - total_margin, 2)
    acct["margin_available_usd"]   = acct["cash_usd"]
    acct["margin_utilization_pct"] = round(
        acct["margin_used_usd"] / equity * 100.0, 2
    ) if equity > 0 else 0.0

    # Heat
    heat = portfolio.setdefault("heat", {})
    heat["total_open_risk_usd"] = round(
        sum(p.get("risk_at_stop_usd", 0) for p in portfolio["positions"]), 2
    )
    heat["total_open_risk_pct"] = round(
        heat["total_open_risk_usd"] / equity * 100.0, 4
    ) if equity > 0 else 0.0

    cluster = heat.setdefault("cluster_exposure", {})
    cg = correlation_group or "uncategorized"
    if cg not in cluster:
        cluster[cg] = {"risk_usd": 0.0, "risk_pct": 0.0, "positions": 0, "instruments": []}
    cluster[cg]["risk_usd"]   = round(cluster[cg]["risk_usd"] + risk_at_stop_usd, 2)
    cluster[cg]["risk_pct"]   = round(cluster[cg]["risk_usd"] / equity * 100.0, 4) if equity > 0 else 0.0
    cluster[cg]["positions"] += 1
    if symbol not in cluster[cg]["instruments"]:
        cluster[cg]["instruments"].append(symbol)

    store.save_portfolio(portfolio)
    return position


# ---------------------------------------------------------------------------
# Close position (bracket trigger) — used by process_bracket_triggers
# ---------------------------------------------------------------------------

def close_position(
    position: dict,
    exit_price: float,
    trigger: str,
    run_id: str,
) -> dict:
    """
    Remove a position from portfolio; update cash/margin/PnL; emit POSITION_CLOSED.
    Returns the close record.
    """
    portfolio = store.load_portfolio()
    equity    = portfolio["account"]["equity_usd"]
    pos_id    = position["position_id"]
    strategy_id = position.get("strategy_id", "")
    symbol      = position.get("symbol", "")
    side        = position.get("side", "LONG")
    contracts   = position.get("contracts", 0)
    entry_price = position.get("entry_price", exit_price)
    point_value = position.get("point_value_usd", 50.0)
    margin_used = position.get("margin_used_usd", 0.0)
    cg          = position.get("correlation_group", "uncategorized")
    risk_usd    = position.get("risk_at_stop_usd", 0.0)

    fee_rt = position.get("fee_per_contract_round_trip_usd")
    if fee_rt is None:
        strategy_rec = store.load_strategy_registry().get(strategy_id, {})
        fee_rt = strategy_rec.get("fee_per_contract_round_trip_usd", 4.62)
    fee = exit_fee_usd(contracts, fee_rt)

    # PnL calculation
    if side == "LONG":
        raw_pnl = (exit_price - entry_price) * point_value * contracts
    else:
        raw_pnl = (entry_price - exit_price) * point_value * contracts
    realized_pnl = round(raw_pnl - fee, 2)

    # Remove position
    portfolio["positions"] = [p for p in portfolio["positions"] if p.get("position_id") != pos_id]

    # Restore margin → cash
    acct = portfolio["account"]
    acct["margin_used_usd"]  = round(max(0.0, acct.get("margin_used_usd", 0) - margin_used), 2)
    acct["cash_usd"]         = round(acct.get("cash_usd", 0) + margin_used + realized_pnl, 2)
    acct["equity_usd"]       = round(acct["cash_usd"] + acct["margin_used_usd"] +
                                     sum(p.get("unrealized_pnl_usd", 0) for p in portfolio["positions"]), 2)
    acct["peak_equity_usd"]  = max(acct["peak_equity_usd"], acct["equity_usd"])
    acct["margin_available_usd"]   = acct["cash_usd"]
    acct["margin_utilization_pct"] = round(
        acct["margin_used_usd"] / acct["equity_usd"] * 100.0, 2
    ) if acct["equity_usd"] > 0 else 0.0

    # PnL tracking
    pnl = portfolio.setdefault("pnl", {})
    pnl["realized_today_usd"] = round(pnl.get("realized_today_usd", 0) + realized_pnl, 2)
    pnl["total_today_usd"]    = round(pnl.get("total_today_usd", 0) + realized_pnl, 2)
    equity_base = acct["equity_usd"] or 1.0
    pnl["total_today_pct"]    = round(pnl["total_today_usd"] / equity_base * 100.0, 4)
    dd = round((acct["peak_equity_usd"] - acct["equity_usd"]) / acct["peak_equity_usd"] * 100.0, 4) \
         if acct["peak_equity_usd"] > 0 else 0.0
    pnl["portfolio_dd_pct"]   = dd

    # Heat
    heat = portfolio.setdefault("heat", {})
    heat["total_open_risk_usd"] = round(
        sum(p.get("risk_at_stop_usd", 0) for p in portfolio["positions"]), 2
    )
    heat["total_open_risk_pct"] = round(
        heat["total_open_risk_usd"] / equity * 100.0, 4
    ) if equity > 0 else 0.0

    cluster = heat.get("cluster_exposure", {})
    if cg in cluster:
        cluster[cg]["risk_usd"]    = round(max(0.0, cluster[cg]["risk_usd"] - risk_usd), 2)
        cluster[cg]["risk_pct"]    = round(cluster[cg]["risk_usd"] / equity * 100.0, 4) if equity > 0 else 0.0
        cluster[cg]["positions"]   = max(0, cluster[cg]["positions"] - 1)
        if symbol in cluster[cg].get("instruments", []) and cluster[cg]["positions"] == 0:
            cluster[cg]["instruments"].remove(symbol)

    store.save_portfolio(portfolio)

    close_record = {
        "position_id":    pos_id,
        "strategy_id":    strategy_id,
        "symbol":         symbol,
        "side":           side,
        "contracts":      contracts,
        "entry_price":    entry_price,
        "exit_price":     exit_price,
        "trigger":        trigger,
        "realized_pnl":   realized_pnl,
        "fee_usd":        fee,
        "closed_at":      datetime.now(timezone.utc).isoformat(),
    }

    ledger.append(
        C.EventType.POSITION_CLOSED,
        run_id,
        pos_id,
        close_record,
    )

    return close_record


# ---------------------------------------------------------------------------
# Core execution — spec 8.4
# ---------------------------------------------------------------------------

def execute_approval(
    approval: dict,
    intent: dict,
    snapshot: dict,
    run_id: str,
    paper: bool = True,
) -> dict:
    """
    Execute one approved intent through the full 8-step protocol.
    Returns an execution receipt dict.
    """
    if not paper:
        raise NotImplementedError("Live execution not implemented (Phase 4)")

    approval_id = approval["approval_id"]
    intent_id   = approval["intent_id"]
    exec_id     = IDs.make_execution_id()
    idem_key    = IDs.make_idempotency_key(approval_id)

    # STEP 2: Idempotency check
    existing = _check_idempotency(idem_key)
    if existing:
        return {
            "execution_id":    exec_id,
            "approval_id":     approval_id,
            "idempotency_key": idem_key,
            "status":          "DUPLICATE_CATCH",
            "message":         "Duplicate prevented — returning existing receipt",
            "existing":        existing,
        }

    # STEP 3: Pre-flight
    ok, reason = _preflight(approval, snapshot)
    if not ok:
        ledger.append(C.EventType.ORDER_REJECTED, run_id, exec_id, {
            "execution_id":  exec_id,
            "approval_id":   approval_id,
            "reason":        reason,
        })
        return {
            "execution_id": exec_id,
            "approval_id":  approval_id,
            "status":       C.ExecStatus.FAILED,
            "reason":       reason,
        }

    # Extract order parameters
    sizing        = approval.get("sizing_final", approval.get("sizing", {}))
    contracts     = sizing.get("contracts_allowed", intent.get("sizing", {}).get("contracts_suggested", 1))
    side          = intent.get("side", "BUY")
    symbol        = intent.get("symbol", "ES")
    price         = snapshot.get("indicators", {}).get("last_price",
                    snapshot["bars"]["1H"][-1]["c"] if snapshot.get("bars", {}).get("1H") else 0.0)
    strategy      = store.load_strategy_registry().get(intent.get("strategy_id", ""), {})
    use_micro     = approval.get("sizing_final", {}).get("use_micro", False)
    tick_size     = strategy.get("tick_size", 0.25)
    tick_value    = (strategy.get("micro_tick_value_usd", 1.25) if use_micro
                     else strategy.get("tick_value_usd", 12.50))
    point_value   = (strategy.get("micro_point_value_usd", 5.0) if use_micro
                     else strategy.get("point_value_usd", 50.0))
    fee_rt        = strategy.get("fee_per_contract_round_trip_usd", 4.62)
    margin_per_c  = (strategy.get("micro_margin_per_contract_usd", 1584.0) if use_micro
                     else strategy.get("margin_per_contract_usd", 15840.0))

    vol_pct  = snapshot.get("external", {}).get("vix_percentile_252d", 0.5)
    session  = snapshot.get("session_state", C.SessionState.CORE)
    depth    = snapshot.get("microstructure", {}).get("avg_book_depth_contracts", 850)

    # STEP 4: Persist ORDER_SENT
    ledger.append(C.EventType.ORDER_SENT, run_id, exec_id, {
        "execution_id":    exec_id,
        "approval_id":     approval_id,
        "idempotency_key": idem_key,
        "symbol":          symbol,
        "side":            side,
        "contracts":       contracts,
        "param_version":   approval.get("param_version", "PV_0001"),
    })

    # STEP 5–6: Simulate fill
    prng_seed = abs(hash(exec_id)) % (2**31)
    fill = simulate_market_fill(
        side=side,
        price=price,
        tick_size=tick_size,
        tick_value_usd=tick_value,
        point_value_usd=point_value,
        contracts=contracts,
        fee_per_contract_round_trip_usd=fee_rt,
        vol_pct=vol_pct,
        session=session,
        avg_book_depth=depth,
        prng_seed=prng_seed,
    )

    if fill["status"] == "REJECTED":
        ledger.append(C.EventType.ORDER_REJECTED, run_id, exec_id, {
            "execution_id": exec_id,
            "approval_id":  approval_id,
            "reason":       fill["reason"],
            "prng_seed":    fill["prng_seed"],
        })
        return {
            "execution_id": exec_id,
            "approval_id":  approval_id,
            "status":       C.ExecStatus.REJECTED,
            "reason":       fill["reason"],
            "prng_seed":    fill["prng_seed"],
        }

    contracts_filled = fill["contracts_filled"]
    fill_price       = fill["fill_price"]

    # Log fill
    fill_event_type = (C.EventType.ORDER_PARTIALLY_FILLED
                       if fill["status"] == "PARTIALLY_FILLED"
                       else C.EventType.ORDER_FILLED)
    ledger.append(fill_event_type, run_id, exec_id, {
        "execution_id":     exec_id,
        "approval_id":      approval_id,
        "fill_price":       fill_price,
        "contracts_filled": contracts_filled,
        "slippage_ticks":   fill["slippage_ticks"],
        "slippage_usd":     fill["slippage_usd"],
        "fees_usd":         fill["fees_usd"],
        "fill_latency_ms":  fill["fill_latency_ms"],
        "prng_seed":        fill["prng_seed"],
    })

    # Build position dict for bracket placement
    position_template = {
        "position_id":        None,  # filled in _register_position
        "symbol":             symbol,
        "strategy_id":        intent.get("strategy_id", ""),
        "side":               "LONG" if side == "BUY" else "SHORT",
        "contracts":          contracts_filled,
        "entry_price":        fill_price,
        "stop_price":         intent.get("stop_plan", {}).get("price", fill_price - 50),
        "take_profit_price":  intent.get("take_profit_plan", {}).get("price", fill_price + 50),
        "margin_used_usd":    margin_per_c * contracts_filled,
        "fee_per_contract_round_trip_usd": fee_rt,
        "point_value_usd":    point_value,
        "correlation_group":  strategy.get("correlation_group", ""),
    }

    # STEP 7: Place bracket orders — CRITICAL
    bracket, bracket_err = _place_bracket(position_template, approval, run_id, paper)

    if bracket is None:
        # Emergency flatten — spec 8.4 STEP 7c / 8.7 Invariant 3
        ledger.append(C.EventType.ALERT, run_id, exec_id, {
            "alert_type":    "EMERGENCY_FLATTEN",
            "execution_id":  exec_id,
            "reason":        f"Stop placement failed: {bracket_err}",
        })
        return {
            "execution_id": exec_id,
            "approval_id":  approval_id,
            "status":       C.ExecStatus.EMERGENCY_FLATTENED,
            "reason":       f"Emergency flatten: stop could not be placed — {bracket_err}",
        }

    # STEP 8: Register position + confirm
    approval_with_meta = dict(approval)
    approval_with_meta.update({
        "strategy_id":             intent.get("strategy_id"),
        "symbol":                  symbol,
        "contract_month":          intent.get("contract_month", ""),
        "side":                    side,
        "stop_plan":               intent.get("stop_plan", {}),
        "take_profit_plan":        intent.get("take_profit_plan", {}),
        "margin_per_contract_usd": margin_per_c,
        "point_value_usd":         point_value,
        "correlation_group":       strategy.get("correlation_group", ""),
    })

    position = _register_position(approval_with_meta, fill, bracket, run_id)

    receipt: dict[str, Any] = {
        "execution_id":    exec_id,
        "approval_id":     approval_id,
        "idempotency_key": idem_key,
        "param_version":   approval.get("param_version", "PV_0001"),
        "order": {
            "symbol":             symbol,
            "contract_month":     intent.get("contract_month", ""),
            "side":               side,
            "type":               "MARKET",
            "contracts_requested": contracts,
            "contracts_filled":   contracts_filled,
        },
        "fill": {
            "avg_fill_price":  fill_price,
            "slippage_ticks":  fill["slippage_ticks"],
            "slippage_usd":    fill["slippage_usd"],
            "fees_usd":        fill["fees_usd"],
            "fill_time_ms":    fill["fill_latency_ms"],
        },
        "bracket": bracket,
        "position_id": position["position_id"],
        "status":      C.ExecStatus.COMPLETE,
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "state":       C.IntentState.COMPLETE,
        "prng_seed":   prng_seed,
    }

    ledger.append(C.EventType.BRACKET_CONFIRMED, run_id, exec_id, {
        "execution_id": exec_id,
        "position_id":  position["position_id"],
        "approval_id":  approval_id,
        "stop":         bracket["stop"],
        "take_profit":  bracket["take_profit"],
    })

    return receipt


# ---------------------------------------------------------------------------
# Bracket trigger processing — called every reconcile cycle
# ---------------------------------------------------------------------------

def process_bracket_triggers(
    snapshots: dict[str, dict],
    run_id: str,
    paper: bool = True,
) -> list[dict]:
    """
    Check all open positions for stop/TP triggers using the latest 15m bars.
    Closes triggered positions and returns the list of close records.
    """
    if not paper:
        return []  # Live bracket monitoring is exchange-driven

    portfolio = store.load_portfolio()
    positions = portfolio.get("positions", [])
    if not positions:
        return []

    # Build 15m bar lookup by symbol (fall back to 1H if no 15m).
    # Also map micro symbols (MES→ES, MNQ→NQ) so micro positions find their bars.
    _micro_to_standard = {"MES": "ES", "MNQ": "NQ", "MCL": "CL", "MBT": "BTC"}
    bars_by_symbol: dict[str, list[dict]] = {}
    for sym, snap in snapshots.items():
        bars_15m = snap.get("bars", {}).get("15m") or snap.get("bars", {}).get("1H", [])
        if bars_15m:
            bars_by_symbol[sym] = bars_15m
    # Add micro-symbol aliases
    for micro, standard in _micro_to_standard.items():
        if standard in bars_by_symbol and micro not in bars_by_symbol:
            bars_by_symbol[micro] = bars_by_symbol[standard]

    triggered = check_bracket_triggers(positions, bars_by_symbol)
    closed: list[dict] = []

    for event in triggered:
        pos       = event["position"]
        trigger   = event["trigger"]
        exit_px   = event["exit_price"]
        record    = close_position(pos, exit_px, trigger, run_id)
        closed.append(record)

    return closed


# ---------------------------------------------------------------------------
# Main entry point — called by run_cycle.py
# ---------------------------------------------------------------------------

def run_forge(
    approvals: list[dict],
    intents_by_id: dict[str, dict],
    snapshots: dict[str, dict],
    run_id: str,
    paper: bool = True,
) -> list[dict]:
    """
    Execute all approved intents.  Returns list of execution receipts.
    Only APPROVE and APPROVE_REDUCED decisions are executed.
    """
    receipts: list[dict] = []
    executable = {C.RiskDecision.APPROVE, C.RiskDecision.APPROVE_REDUCED}

    for approval in approvals:
        decision = approval.get("decision")
        if decision not in executable:
            continue

        intent_id = approval.get("intent_id", "")
        intent    = intents_by_id.get(intent_id)
        if not intent:
            continue

        symbol   = intent.get("symbol", "ES")
        snapshot = snapshots.get(symbol, next(iter(snapshots.values()), {}))

        receipt = execute_approval(approval, intent, snapshot, run_id, paper=paper)
        receipts.append(receipt)

    return receipts
