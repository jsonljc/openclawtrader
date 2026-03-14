#!/usr/bin/env python3
"""Forge — Execution Engine — spec Section 8.

Executes approved orders exactly as instructed. No decisions. No creativity.
Fully idempotent and logged.

Public API:
    run_forge(approvals, snapshots, run_id, paper=True) -> list[receipt]
    process_bracket_triggers(snapshots, run_id, paper=True) -> list[closed]
    close_position(position, exit_result, run_id) -> None
    run_reconciliation_ib(run_id) -> dict          # IB position reconciliation
    verify_ib_brackets(run_id) -> dict             # IB bracket verification
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
from shared import alerting
from paper_broker import simulate_market_fill, check_bracket_triggers
from fees_model import exit_fee_usd
from slippage_model import estimate_slippage_ticks, slippage_usd
from slippage_tracker import record_fill as _record_slippage_fill


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

    # Scale-out plan from approval/intent
    raw_scale_out = approval.get("scale_out_plan")
    scale_out_plan = None
    if raw_scale_out:
        scale_out_plan = {
            "t1_pct": raw_scale_out.get("t1_pct", 50),
            "t1_price": raw_scale_out.get("t1_price"),
            "t2_price": raw_scale_out.get("t2_price"),
            "t1_filled": False,
            "be_stop_active": False,
            "trailing_stop": None,
            "trailing_atr_multiple": raw_scale_out.get("trailing_atr_multiple", 1.5),
        }

    position: dict[str, Any] = {
        "position_id":       pos_id,
        "symbol":            symbol,
        "contract_month":    contract_month,
        "strategy_id":       strategy_id,
        "side":              position_side,
        "contracts":         contracts_filled,
        "original_contracts": contracts_filled,
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
        "scale_out_plan":    scale_out_plan,
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
# Partial close — scale-out T1/T2/trailing stop
# ---------------------------------------------------------------------------

def partial_close_position(
    position: dict,
    exit_price: float,
    contracts_to_close: int,
    trigger: str,
    run_id: str,
) -> dict:
    """
    Close a portion of a position (scale-out). Updates position in-place
    within the portfolio, adjusts margin/heat, and emits POSITION_PARTIALLY_CLOSED.
    Returns a close record for the partial exit.
    """
    portfolio = store.load_portfolio()
    equity = portfolio["account"]["equity_usd"]
    pos_id = position["position_id"]
    strategy_id = position.get("strategy_id", "")
    symbol = position.get("symbol", "")
    side = position.get("side", "LONG")
    entry_price = position.get("entry_price", exit_price)
    point_value = position.get("point_value_usd", 50.0)
    cg = position.get("correlation_group", "uncategorized")

    total_contracts = position.get("contracts", 0)
    contracts_to_close = min(contracts_to_close, total_contracts)
    contracts_remaining = total_contracts - contracts_to_close

    # Fee for partial close (exit half of round-trip)
    fee_rt = position.get("fee_per_contract_round_trip_usd")
    if fee_rt is None:
        strategy_rec = store.load_strategy_registry().get(strategy_id, {})
        fee_rt = strategy_rec.get("fee_per_contract_round_trip_usd", 4.62)
    fee = exit_fee_usd(contracts_to_close, fee_rt)

    # PnL for closed portion
    if side == "LONG":
        raw_pnl = (exit_price - entry_price) * point_value * contracts_to_close
    else:
        raw_pnl = (entry_price - exit_price) * point_value * contracts_to_close
    realized_pnl = round(raw_pnl - fee, 2)

    # Update position in portfolio
    for p in portfolio.get("positions", []):
        if p.get("position_id") == pos_id:
            p["contracts"] = contracts_remaining
            # Margin release proportional to closed contracts
            margin_per_c = position.get("margin_used_usd", 0.0) / total_contracts if total_contracts > 0 else 0.0
            margin_released = margin_per_c * contracts_to_close
            p["margin_used_usd"] = round(p.get("margin_used_usd", 0.0) - margin_released, 2)
            # Recalculate risk at stop
            stop_dist = abs(entry_price - p.get("stop_price", entry_price))
            p["risk_at_stop_usd"] = round(stop_dist * point_value * contracts_remaining, 2)
            p["risk_at_stop_pct"] = round(p["risk_at_stop_usd"] / equity * 100.0, 4) if equity > 0 else 0.0

            # If T1 trigger: move stop to breakeven, activate trailing
            if trigger == "T1":
                sop = p.get("scale_out_plan", {})
                if sop:
                    sop["t1_filled"] = True
                    sop["be_stop_active"] = True
                    p["stop_price"] = entry_price  # breakeven stop
                    p["risk_at_stop_usd"] = 0.0
                    p["risk_at_stop_pct"] = 0.0

            # Update margin in account
            acct = portfolio["account"]
            acct["margin_used_usd"] = round(max(0.0, acct.get("margin_used_usd", 0) - margin_released), 2)
            acct["cash_usd"] = round(acct.get("cash_usd", 0) + margin_released + realized_pnl, 2)
            acct["equity_usd"] = round(acct["cash_usd"] + acct["margin_used_usd"] +
                                       sum(pos.get("unrealized_pnl_usd", 0) for pos in portfolio["positions"]), 2)
            acct["peak_equity_usd"] = max(acct["peak_equity_usd"], acct["equity_usd"])
            acct["margin_available_usd"] = acct["cash_usd"]
            acct["margin_utilization_pct"] = round(
                acct["margin_used_usd"] / acct["equity_usd"] * 100.0, 2
            ) if acct["equity_usd"] > 0 else 0.0
            break

    # PnL tracking
    pnl = portfolio.setdefault("pnl", {})
    pnl["realized_today_usd"] = round(pnl.get("realized_today_usd", 0) + realized_pnl, 2)
    pnl["total_today_usd"] = round(pnl.get("total_today_usd", 0) + realized_pnl, 2)
    equity_base = portfolio["account"]["equity_usd"] or 1.0
    pnl["total_today_pct"] = round(pnl["total_today_usd"] / equity_base * 100.0, 4)

    # Heat recalculation
    heat = portfolio.setdefault("heat", {})
    heat["total_open_risk_usd"] = round(
        sum(p.get("risk_at_stop_usd", 0) for p in portfolio["positions"]), 2
    )
    heat["total_open_risk_pct"] = round(
        heat["total_open_risk_usd"] / equity * 100.0, 4
    ) if equity > 0 else 0.0

    cluster = heat.get("cluster_exposure", {})
    if cg in cluster:
        old_risk = position.get("risk_at_stop_usd", 0.0)
        new_risk = round(abs(entry_price - position.get("stop_price", entry_price)) * point_value * contracts_remaining, 2)
        cluster[cg]["risk_usd"] = round(max(0.0, cluster[cg]["risk_usd"] - old_risk + new_risk), 2)
        cluster[cg]["risk_pct"] = round(cluster[cg]["risk_usd"] / equity * 100.0, 4) if equity > 0 else 0.0

    store.save_portfolio(portfolio)

    exit_category = _classify_exit(trigger, entry_price, exit_price, side)

    close_record = {
        "position_id": pos_id,
        "strategy_id": strategy_id,
        "symbol": symbol,
        "side": side,
        "contracts_closed": contracts_to_close,
        "contracts_remaining": contracts_remaining,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "trigger": trigger,
        "exit_reason": trigger,
        "exit_category": exit_category,
        "realized_pnl": realized_pnl,
        "fee_usd": fee,
        "closed_at": datetime.now(timezone.utc).isoformat(),
    }

    ledger.append(
        C.EventType.POSITION_PARTIALLY_CLOSED,
        run_id,
        pos_id,
        close_record,
    )

    # Alert on scale-out fills
    alerting.alert("INFO", f"Scale-out {trigger}: {symbol} {side} closed {contracts_to_close} contracts @ {exit_price}",
                   {"position_id": pos_id, "pnl": realized_pnl, "remaining": contracts_remaining})

    return close_record


# ---------------------------------------------------------------------------
# Exit classification — for learning pipeline
# ---------------------------------------------------------------------------

def _classify_exit(trigger: str, entry_price: float, exit_price: float, side: str) -> str:
    """Classify exit into categories for performance tracking."""
    if side == "LONG":
        pnl_direction = exit_price - entry_price
    else:
        pnl_direction = entry_price - exit_price

    if trigger in ("T1",):
        return "WIN_PARTIAL"
    if trigger in ("T2", "TAKE_PROFIT"):
        return "WIN_FULL"
    if abs(pnl_direction) < 0.01:
        return "BREAKEVEN"
    if pnl_direction > 0:
        if trigger == "TRAILING_STOP":
            return "WIN_PARTIAL"
        return "WIN_FULL"
    if trigger in ("STOP",):
        return "LOSS_FULL"
    return "LOSS_PARTIAL"


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
    Returns the close record with exit_reason and exit_category.
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

    exit_category = _classify_exit(trigger, entry_price, exit_price, side)

    close_record = {
        "position_id":    pos_id,
        "strategy_id":    strategy_id,
        "symbol":         symbol,
        "side":           side,
        "contracts":      contracts,
        "entry_price":    entry_price,
        "exit_price":     exit_price,
        "trigger":        trigger,
        "exit_reason":    trigger,
        "exit_category":  exit_category,
        "realized_pnl":   realized_pnl,
        "fee_usd":        fee,
        "bars_held":      position.get("bars_held", 0),
        "closed_at":      datetime.now(timezone.utc).isoformat(),
    }

    ledger.append(
        C.EventType.POSITION_CLOSED,
        run_id,
        pos_id,
        close_record,
    )

    # Alert on position close
    alerting.alert("INFO", f"Position closed: {symbol} {side} {contracts}ct via {trigger} PnL=${realized_pnl:.2f}",
                   {"position_id": pos_id, "exit_category": exit_category})

    return close_record


# ---------------------------------------------------------------------------
# Roll execution — Phase 3: close front month, open next month
# ---------------------------------------------------------------------------

def _execute_roll_ib(
    approval: dict,
    intent: dict,
    snapshots: dict[str, dict],
    run_id: str,
) -> dict:
    """Execute a roll via IB: close front month position, open next month."""
    from ib_gateway import get_connection
    from ib_broker import execute_market_order, place_bracket_orders, cancel_bracket
    from ib_insync import Future

    exec_id = IDs.make_execution_id()
    idem_key = IDs.make_idempotency_key(approval["approval_id"])

    # Idempotency
    existing = _check_idempotency(idem_key)
    if existing:
        return {
            "execution_id": exec_id, "approval_id": approval["approval_id"],
            "idempotency_key": idem_key, "status": "DUPLICATE_CATCH",
            "message": "Duplicate roll prevented", "existing": existing,
        }

    portfolio = store.load_portfolio()
    position_id = approval.get("position_id") or intent.get("position_id")
    pos = next((p for p in portfolio["positions"] if p.get("position_id") == position_id), None)
    if not pos:
        return {
            "execution_id": exec_id, "approval_id": approval["approval_id"],
            "status": C.ExecStatus.FAILED, "reason": f"Position {position_id} not found",
        }

    symbol = intent.get("symbol", "ES")
    side = pos.get("side", "LONG")
    contracts = pos.get("contracts", 1)
    strategy = store.load_strategy_registry().get(intent.get("strategy_id", ""), {})
    use_micro = approval.get("sizing_final", {}).get("use_micro", False)
    tick_size = strategy.get("tick_size", 0.25)
    tick_value = (strategy.get("micro_tick_value_usd", 1.25) if use_micro
                  else strategy.get("tick_value_usd", 12.50))
    point_value = (strategy.get("micro_point_value_usd", 5.0) if use_micro
                   else strategy.get("point_value_usd", 50.0))
    fee_rt = strategy.get("fee_per_contract_round_trip_usd", 4.62)
    margin_per_c = (strategy.get("micro_margin_per_contract_usd", 1584.0) if use_micro
                    else strategy.get("margin_per_contract_usd", 15840.0))

    ib = get_connection()

    # Step 1: Cancel existing brackets on the old position
    bracket_status = pos.get("bracket_status", {})
    old_bracket_ids = [
        bracket_status.get("stop_order_id", ""),
        bracket_status.get("tp_order_id", ""),
    ]
    old_bracket_ids = [oid for oid in old_bracket_ids if oid.startswith("IB_")]
    if old_bracket_ids:
        cancel_bracket(ib, old_bracket_ids)

    # Step 2: Close old position via IB market order
    close_side = "SELL" if side == "LONG" else "BUY"
    _MICRO_MAP = {"ES": "MES", "NQ": "MNQ", "CL": "MCL", "GC": "MGC"}
    _EXCHANGE_MAP = {"ES": "CME", "NQ": "CME", "MES": "CME", "MNQ": "CME",
                     "CL": "NYMEX", "MCL": "NYMEX", "GC": "COMEX", "MGC": "COMEX",
                     "ZB": "CBOT"}
    ib_symbol_old = _MICRO_MAP.get(symbol, symbol) if use_micro else symbol
    ib_exchange_old = _EXCHANGE_MAP.get(ib_symbol_old, "CME")
    old_contract = Future(ib_symbol_old, exchange=ib_exchange_old, currency="USD")
    qualified = ib.qualifyContracts(old_contract)
    if qualified:
        old_contract = qualified[0]

    ledger.append(C.EventType.ORDER_SENT, run_id, exec_id, {
        "execution_id": exec_id, "approval_id": approval["approval_id"],
        "idempotency_key": idem_key, "symbol": symbol, "side": close_side,
        "contracts": contracts, "execution_mode": "IB", "roll_phase": "CLOSE",
    })

    close_fill = execute_market_order(
        ib, old_contract, close_side, contracts,
        tick_size=tick_size, tick_value_usd=tick_value,
        point_value_usd=point_value, fee_per_contract_round_trip_usd=fee_rt,
    )

    if close_fill["status"] in ("REJECTED", "TIMED_OUT"):
        ledger.append(C.EventType.ORDER_REJECTED, run_id, exec_id, {
            "execution_id": exec_id, "reason": close_fill.get("reason", "Roll close failed"),
            "roll_phase": "CLOSE",
        })
        alerting.alert("HALT", f"ROLL CLOSE FAILED for {symbol} — position still open",
                       {"execution_id": exec_id, "reason": close_fill.get("reason")})
        return {
            "execution_id": exec_id, "approval_id": approval["approval_id"],
            "status": C.ExecStatus.FAILED, "reason": f"Roll close failed: {close_fill.get('reason')}",
        }

    # Update portfolio: close old position
    close_price = close_fill["fill_price"]
    close_record = close_position(pos, close_price, "ROLL", run_id)

    # Step 3: Open new position in next contract month
    roll_to = approval.get("roll_to", intent.get("roll_to", ""))
    open_side = "BUY" if side == "LONG" else "SELL"
    contracts_to_open = approval.get("sizing_final", {}).get(
        "contracts_allowed", contracts)

    # Resolve new contract
    ib_symbol_new = ib_symbol_old  # Same instrument, different month
    new_contract = Future(ib_symbol_new, exchange=ib_exchange_old, currency="USD")
    qualified = ib.qualifyContracts(new_contract)
    if qualified:
        new_contract = qualified[0]

    open_fill = execute_market_order(
        ib, new_contract, open_side, contracts_to_open,
        tick_size=tick_size, tick_value_usd=tick_value,
        point_value_usd=point_value, fee_per_contract_round_trip_usd=fee_rt,
    )

    if open_fill["status"] in ("REJECTED", "TIMED_OUT"):
        ledger.append(C.EventType.ORDER_REJECTED, run_id, exec_id, {
            "execution_id": exec_id, "reason": open_fill.get("reason", "Roll open failed"),
            "roll_phase": "OPEN",
        })
        alerting.alert("HALT", f"ROLL OPEN FAILED for {symbol} — old position closed but new not opened",
                       {"execution_id": exec_id, "reason": open_fill.get("reason")})
        return {
            "execution_id": exec_id, "approval_id": approval["approval_id"],
            "status": C.ExecStatus.FAILED,
            "reason": f"Roll open failed (old position already closed): {open_fill.get('reason')}",
            "closed_pnl": close_record.get("realized_pnl"),
        }

    fill_price = open_fill["fill_price"]
    contracts_filled = open_fill["contracts_filled"]

    # Step 4: Place brackets on new position
    stop_price = approval.get("stop_plan", {}).get("price", fill_price - 50)
    tp_price = approval.get("take_profit_plan", {}).get("price", fill_price + 50)

    try:
        bracket = place_bracket_orders(
            ib, new_contract, open_fill.get("prng_seed", 0),
            open_side, contracts_filled, stop_price, tp_price,
        )
    except Exception as exc:
        # Emergency flatten the new position
        reverse_side = "SELL" if open_side == "BUY" else "BUY"
        execute_market_order(ib, new_contract, reverse_side, contracts_filled,
                             tick_size=tick_size, tick_value_usd=tick_value,
                             point_value_usd=point_value, fee_per_contract_round_trip_usd=fee_rt)
        alerting.alert("HALT", f"ROLL BRACKET FAILED for {symbol} — emergency flattened",
                       {"execution_id": exec_id, "reason": str(exc)})
        return {
            "execution_id": exec_id, "approval_id": approval["approval_id"],
            "status": C.ExecStatus.EMERGENCY_FLATTENED,
            "reason": f"Roll bracket failed — emergency flatten: {exc}",
            "closed_pnl": close_record.get("realized_pnl"),
        }

    # Step 5: Register new position
    approval_roll = dict(approval)
    approval_roll.update({
        "strategy_id": intent.get("strategy_id"),
        "symbol": symbol, "contract_month": roll_to,
        "side": open_side, "stop_plan": {"price": stop_price},
        "take_profit_plan": {"price": tp_price},
        "margin_per_contract_usd": margin_per_c,
        "point_value_usd": point_value,
        "correlation_group": strategy.get("correlation_group", ""),
    })

    new_pos = _register_position(approval_roll, open_fill, bracket, run_id)

    ledger.append(C.EventType.BRACKET_CONFIRMED, run_id, new_pos["position_id"], {
        "execution_id": exec_id, "position_id": new_pos["position_id"],
        "approval_id": approval["approval_id"],
        "stop": bracket["stop"], "take_profit": bracket["take_profit"],
    })

    alerting.alert("INFO", f"Roll complete: {symbol} {roll_to} {contracts_filled}ct @ {fill_price}",
                   {"position_id": new_pos["position_id"], "closed_pnl": close_record.get("realized_pnl")})

    return {
        "execution_id": exec_id, "approval_id": approval["approval_id"],
        "status": C.ExecStatus.COMPLETE,
        "position_id": new_pos["position_id"],
        "roll_from": approval.get("roll_from"),
        "roll_to": roll_to,
        "closed_pnl": close_record.get("realized_pnl"),
        "state": C.IntentState.COMPLETE,
        "execution_mode": "IB",
    }


def execute_roll(
    approval: dict,
    intent: dict,
    snapshots: dict[str, dict],
    run_id: str,
    paper: bool = True,
) -> dict:
    """Execute a roll: close position at current price, open same size in roll_to contract."""
    if not paper:
        return _execute_roll_ib(approval, intent, snapshots, run_id)

    # Idempotency check — same pattern as execute_approval
    idem_key = IDs.make_idempotency_key(approval["approval_id"])
    existing = _check_idempotency(idem_key)
    if existing:
        return {
            "execution_id":    IDs.make_execution_id(),
            "approval_id":     approval["approval_id"],
            "idempotency_key": idem_key,
            "status":          "DUPLICATE_CATCH",
            "message":         "Duplicate roll prevented — returning existing receipt",
            "existing":        existing,
        }

    portfolio = store.load_portfolio()
    position_id = approval.get("position_id") or intent.get("position_id")
    pos = next((p for p in portfolio["positions"] if p.get("position_id") == position_id), None)
    if not pos:
        return {
            "execution_id": IDs.make_execution_id(),
            "approval_id":  approval["approval_id"],
            "status":       C.ExecStatus.FAILED,
            "reason":       f"Position {position_id} not found",
        }
    symbol = intent.get("symbol", "ES")
    snapshot = snapshots.get(symbol, next(iter(snapshots.values()), {}))
    current_price = snapshot.get("indicators", {}).get("last_price") or pos.get("entry_price", 0.0)
    close_record = close_position(pos, current_price, "ROLL", run_id)
    # Re-open same size in new contract
    contracts = approval["sizing_final"]["contracts_allowed"]
    strategy = store.load_strategy_registry().get(intent.get("strategy_id", ""), {})
    roll_to = approval.get("roll_to", intent.get("roll_to", ""))
    fill = {"fill_price": current_price, "contracts_filled": contracts, "slippage_ticks": 0,
            "slippage_usd": 0.0, "fees_usd": 0.0, "fill_latency_ms": 50, "prng_seed": 0}
    bracket, _ = _place_bracket(
        {"position_id": None, "symbol": symbol, "stop_price": approval["stop_plan"].get("price"),
         "take_profit_price": approval["take_profit_plan"].get("price"), "contracts": contracts,
         "entry_price": current_price, "side": "LONG" if intent.get("side") == "BUY" else "SHORT"},
        approval, run_id, paper
    )
    if bracket is None:
        ledger.append(C.EventType.ALERT, run_id, approval["approval_id"], {
            "alert_type": "ROLL_BRACKET_FAILED", "reason": "Bracket placement failed after roll close",
        })
        alerting.alert("HALT", f"ROLL BRACKET FAILED for {symbol} — naked position",
                       {"approval_id": approval["approval_id"]})
        return {"execution_id": IDs.make_execution_id(), "approval_id": approval["approval_id"],
                "status": C.ExecStatus.EMERGENCY_FLATTENED, "reason": "Bracket failed after roll"}
    approval_roll = dict(approval)
    approval_roll["contract_month"] = roll_to
    approval_roll["stop_plan"] = approval.get("stop_plan", {})
    approval_roll["take_profit_plan"] = approval.get("take_profit_plan", {})
    approval_roll["margin_per_contract_usd"] = strategy.get("margin_per_contract_usd", 15840.0)
    approval_roll["point_value_usd"] = strategy.get("point_value_usd", 50.0)
    approval_roll["correlation_group"] = strategy.get("correlation_group", "")
    new_pos = _register_position(approval_roll, fill, bracket, run_id)
    ledger.append(C.EventType.BRACKET_CONFIRMED, run_id, new_pos["position_id"], {
        "execution_id": IDs.make_execution_id(), "position_id": new_pos["position_id"],
        "approval_id": approval["approval_id"], "stop": bracket["stop"], "take_profit": bracket["take_profit"],
    })
    return {
        "execution_id":    IDs.make_execution_id(),
        "approval_id":     approval["approval_id"],
        "status":          C.ExecStatus.COMPLETE,
        "position_id":     new_pos["position_id"],
        "roll_from":       approval.get("roll_from"),
        "roll_to":         roll_to,
        "closed_pnl":      close_record.get("realized_pnl"),
        "state":           C.IntentState.COMPLETE,
    }


# ---------------------------------------------------------------------------
# IB live execution — Phase 4
# ---------------------------------------------------------------------------

def _execute_approval_ib(
    approval: dict,
    intent: dict,
    snapshot: dict,
    run_id: str,
) -> dict:
    """
    Execute one approved intent through IB.
    Mirrors the 8-step protocol from execute_approval but uses IB for
    order submission and bracket placement.
    """
    from ib_gateway import get_connection
    from ib_broker import execute_market_order, place_bracket_orders
    from ib_insync import Future

    approval_id = approval["approval_id"]
    intent_id   = approval["intent_id"]
    exec_id     = IDs.make_execution_id()
    idem_key    = IDs.make_idempotency_key(approval_id)

    # STEP 2: Idempotency check
    existing = _check_idempotency(idem_key)
    if existing:
        return {
            "execution_id": exec_id, "approval_id": approval_id,
            "idempotency_key": idem_key, "status": "DUPLICATE_CATCH",
            "message": "Duplicate prevented — returning existing receipt",
            "existing": existing,
        }

    # STEP 3: Pre-flight
    ok, reason = _preflight(approval, snapshot)
    if not ok:
        ledger.append(C.EventType.ORDER_REJECTED, run_id, exec_id, {
            "execution_id": exec_id, "approval_id": approval_id, "reason": reason,
        })
        return {"execution_id": exec_id, "approval_id": approval_id,
                "status": C.ExecStatus.FAILED, "reason": reason}

    # Extract order parameters
    sizing    = approval.get("sizing_final", approval.get("sizing", {}))
    contracts = sizing.get("contracts_allowed", intent.get("sizing", {}).get("contracts_suggested", 1))
    side      = intent.get("side", "BUY")
    symbol    = intent.get("symbol", "ES")
    strategy  = store.load_strategy_registry().get(intent.get("strategy_id", ""), {})
    use_micro = approval.get("sizing_final", {}).get("use_micro", False)
    tick_size = strategy.get("tick_size", 0.25)
    tick_value = (strategy.get("micro_tick_value_usd", 1.25) if use_micro
                  else strategy.get("tick_value_usd", 12.50))
    point_value = (strategy.get("micro_point_value_usd", 5.0) if use_micro
                   else strategy.get("point_value_usd", 50.0))
    fee_rt    = strategy.get("fee_per_contract_round_trip_usd", 4.62)
    margin_per_c = (strategy.get("micro_margin_per_contract_usd", 1584.0) if use_micro
                    else strategy.get("margin_per_contract_usd", 15840.0))

    # STEP 4: Persist ORDER_SENT
    ledger.append(C.EventType.ORDER_SENT, run_id, exec_id, {
        "execution_id": exec_id, "approval_id": approval_id,
        "idempotency_key": idem_key, "symbol": symbol, "side": side,
        "contracts": contracts, "param_version": approval.get("param_version", "PV_0001"),
        "execution_mode": "IB",
    })

    # STEP 5-6: Submit order to IB
    ib = get_connection()
    _MICRO_MAP = {"ES": "MES", "NQ": "MNQ", "CL": "MCL", "GC": "MGC"}
    _EXCHANGE_MAP = {"ES": "CME", "NQ": "CME", "MES": "CME", "MNQ": "CME",
                     "CL": "NYMEX", "MCL": "NYMEX", "GC": "COMEX", "MGC": "COMEX",
                     "ZB": "CBOT"}
    ib_symbol = _MICRO_MAP.get(symbol, symbol) if use_micro else symbol
    ib_exchange = _EXCHANGE_MAP.get(ib_symbol, "CME")
    ib_contract = Future(ib_symbol, exchange=ib_exchange, currency="USD")
    qualified = ib.qualifyContracts(ib_contract)
    if qualified:
        ib_contract = qualified[0]

    fill = execute_market_order(
        ib, ib_contract, side, contracts,
        tick_size=tick_size, tick_value_usd=tick_value,
        point_value_usd=point_value,
        fee_per_contract_round_trip_usd=fee_rt,
    )

    if fill["status"] in ("REJECTED", "TIMED_OUT"):
        ledger.append(C.EventType.ORDER_REJECTED, run_id, exec_id, {
            "execution_id": exec_id, "approval_id": approval_id,
            "reason": fill.get("reason", fill["status"]),
        })
        return {"execution_id": exec_id, "approval_id": approval_id,
                "status": C.ExecStatus.REJECTED, "reason": fill.get("reason", fill["status"])}

    contracts_filled = fill["contracts_filled"]
    fill_price = fill["fill_price"]

    # Log fill
    fill_event_type = (C.EventType.ORDER_PARTIALLY_FILLED
                       if fill["status"] == "PARTIALLY_FILLED"
                       else C.EventType.ORDER_FILLED)
    ledger.append(fill_event_type, run_id, exec_id, {
        "execution_id": exec_id, "approval_id": approval_id,
        "fill_price": fill_price, "contracts_filled": contracts_filled,
        "slippage_ticks": fill["slippage_ticks"], "slippage_usd": fill["slippage_usd"],
        "fees_usd": fill["fees_usd"], "fill_latency_ms": fill["fill_latency_ms"],
        "execution_mode": "IB",
    })
    store.update_exec_quality_slippage(intent.get("strategy_id", ""), fill["slippage_ticks"])

    # Track slippage by contract type (micro vs full) — IB path
    slip_result = _record_slippage_fill(
        symbol=ib_symbol,
        strategy_id=intent.get("strategy_id", ""),
        slippage_ticks=fill["slippage_ticks"],
        slippage_usd=fill["slippage_usd"],
        contracts=contracts_filled,
        fill_price=fill_price,
        side=side,
        run_id=run_id,
    )
    if slip_result.get("alert"):
        alerting.alert("WARNING", slip_result["alert_message"],
                       {"micro_avg": slip_result["micro_avg"], "full_avg": slip_result["full_avg"]})

    # STEP 7: Place bracket orders via IB
    stop_price = intent.get("stop_plan", {}).get("price", fill_price - 50)
    tp_price = intent.get("take_profit_plan", {}).get("price", fill_price + 50)

    try:
        bracket = place_bracket_orders(
            ib, ib_contract, fill.get("prng_seed", 0),
            side, contracts_filled, stop_price, tp_price,
        )
    except Exception as exc:
        # Emergency flatten
        from ib_broker import execute_market_order as ib_market
        reverse_side = "SELL" if side == "BUY" else "BUY"
        ledger.append(C.EventType.ALERT, run_id, exec_id, {
            "alert_type": "EMERGENCY_FLATTEN", "execution_id": exec_id,
            "reason": f"IB bracket placement failed: {exc}",
        })
        ib_market(ib, ib_contract, reverse_side, contracts_filled,
                  tick_size=tick_size, tick_value_usd=tick_value,
                  point_value_usd=point_value, fee_per_contract_round_trip_usd=fee_rt)
        alerting.alert("HALT", f"EMERGENCY FLATTEN: IB bracket failed for {symbol}",
                       {"execution_id": exec_id, "reason": str(exc)})
        return {"execution_id": exec_id, "approval_id": approval_id,
                "status": C.ExecStatus.EMERGENCY_FLATTENED,
                "reason": f"Emergency flatten: IB bracket failed — {exc}"}

    # STEP 8: Register position
    approval_with_meta = dict(approval)
    approval_with_meta.update({
        "strategy_id": intent.get("strategy_id"),
        "symbol": symbol, "contract_month": intent.get("contract_month", ""),
        "side": side, "stop_plan": intent.get("stop_plan", {}),
        "take_profit_plan": intent.get("take_profit_plan", {}),
        "margin_per_contract_usd": margin_per_c,
        "point_value_usd": point_value,
        "correlation_group": strategy.get("correlation_group", ""),
    })

    position = _register_position(approval_with_meta, fill, bracket, run_id)

    receipt: dict[str, Any] = {
        "execution_id": exec_id, "approval_id": approval_id,
        "idempotency_key": idem_key,
        "param_version": approval.get("param_version", "PV_0001"),
        "order": {
            "symbol": symbol, "contract_month": intent.get("contract_month", ""),
            "side": side, "type": "MARKET",
            "contracts_requested": contracts, "contracts_filled": contracts_filled,
        },
        "fill": {
            "avg_fill_price": fill_price, "slippage_ticks": fill["slippage_ticks"],
            "slippage_usd": fill["slippage_usd"], "fees_usd": fill["fees_usd"],
            "fill_time_ms": fill["fill_latency_ms"],
        },
        "bracket": bracket,
        "position_id": position["position_id"],
        "status": C.ExecStatus.COMPLETE,
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "state": C.IntentState.COMPLETE,
        "execution_mode": "IB",
        "prng_seed": 0,
    }

    ledger.append(C.EventType.BRACKET_CONFIRMED, run_id, exec_id, {
        "execution_id": exec_id, "position_id": position["position_id"],
        "approval_id": approval_id,
        "stop": bracket["stop"], "take_profit": bracket["take_profit"],
    })

    return receipt


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
        return _execute_approval_ib(approval, intent, snapshot, run_id)

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
    # Phase 4: slippage calibration
    store.update_exec_quality_slippage(intent.get("strategy_id", ""), fill["slippage_ticks"])

    # Track slippage by contract type (micro vs full)
    slip_result = _record_slippage_fill(
        symbol=symbol,
        strategy_id=intent.get("strategy_id", ""),
        slippage_ticks=fill["slippage_ticks"],
        slippage_usd=fill["slippage_usd"],
        contracts=contracts_filled,
        fill_price=fill_price,
        side=side,
        run_id=run_id,
    )
    if slip_result.get("alert"):
        alerting.alert("WARNING", slip_result["alert_message"],
                       {"micro_avg": slip_result["micro_avg"], "full_avg": slip_result["full_avg"]})

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
        # Actually close the position by simulating a reverse fill
        ledger.append(C.EventType.ALERT, run_id, exec_id, {
            "alert_type":    "EMERGENCY_FLATTEN",
            "execution_id":  exec_id,
            "reason":        f"Stop placement failed: {bracket_err}",
        })
        # Close the filled position immediately
        reverse_side = "SELL" if side == "BUY" else "BUY"
        reverse_fill = simulate_market_fill(
            side=reverse_side,
            price=fill_price,
            tick_size=tick_size,
            tick_value_usd=tick_value,
            point_value_usd=point_value,
            contracts=contracts_filled,
            fee_per_contract_round_trip_usd=fee_rt,
            vol_pct=vol_pct,
            session=session,
            avg_book_depth=depth,
            prng_seed=prng_seed + 1,
        )
        # Log the emergency close
        ledger.append(C.EventType.POSITION_CLOSED, run_id, exec_id, {
            "execution_id":  exec_id,
            "reason":        "EMERGENCY_FLATTEN",
            "reverse_fill":  reverse_fill["fill_price"] if reverse_fill.get("status") != "REJECTED" else None,
        })
        alerting.alert("HALT", f"EMERGENCY FLATTEN: bracket failed for {symbol} — position closed",
                       {"execution_id": exec_id, "reason": bracket_err})
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
    # Pass through scale_out_plan and max_hold_bars
    if intent.get("scale_out_plan"):
        approval_with_meta["scale_out_plan"] = intent["scale_out_plan"]

    position = _register_position(approval_with_meta, fill, bracket, run_id)

    # Store max_hold_bars on the position for time exit checks
    if approval.get("max_hold_bars"):
        position["max_hold_bars"] = approval["max_hold_bars"]
        # Re-save portfolio with max_hold_bars on the position
        portfolio = store.load_portfolio()
        for p in portfolio["positions"]:
            if p["position_id"] == position["position_id"]:
                p["max_hold_bars"] = approval["max_hold_bars"]
                break
        store.save_portfolio(portfolio)

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

    # Alert on order fill
    alerting.alert("INFO", f"Order filled: {symbol} {side} {contracts_filled} contracts @ {fill_price}",
                   {"position_id": position["position_id"], "strategy_id": intent.get("strategy_id")})

    return receipt


# ---------------------------------------------------------------------------
# IB position reconciliation — verify portfolio state matches IB reality
# ---------------------------------------------------------------------------

def run_reconciliation_ib(run_id: str) -> dict:
    """
    Query IB's actual positions and compare with portfolio.json.
    Detects: phantom positions (in portfolio but not at IB), orphan positions
    (at IB but not in portfolio), and quantity mismatches.

    Returns reconciliation report dict.
    On mismatch: logs ALERT, sends Telegram, sets posture to HALT.
    """
    from ib_gateway import get_connection

    portfolio = store.load_portfolio()
    our_positions = portfolio.get("positions", [])

    ib = get_connection()
    ib.sleep(1)  # Allow position data to settle

    # Query IB positions
    ib_positions = ib.positions()

    # Build IB position map: (symbol, side) -> total contracts
    # IB reports position as signed quantity: positive = long, negative = short
    ib_pos_map: dict[tuple[str, str], float] = {}
    _micro_to_standard = {"MES": "ES", "MNQ": "NQ", "MCL": "CL", "MGC": "GC", "MBT": "BTC"}
    for ib_pos in ib_positions:
        contract = ib_pos.contract
        sym = contract.localSymbol or contract.symbol or ""
        # Normalize micro to standard symbol for comparison
        base_sym = _micro_to_standard.get(sym, sym)
        qty = ib_pos.position  # positive=long, negative=short
        if qty == 0:
            continue
        side = "LONG" if qty > 0 else "SHORT"
        key = (base_sym, side)
        ib_pos_map[key] = ib_pos_map.get(key, 0) + abs(qty)

    # Build our position map: (symbol, side) -> total contracts
    our_pos_map: dict[tuple[str, str], float] = {}
    for pos in our_positions:
        sym = pos.get("symbol", "")
        base_sym = _micro_to_standard.get(sym, sym)
        side = pos.get("side", "LONG")
        contracts = pos.get("contracts", 0)
        key = (base_sym, side)
        our_pos_map[key] = our_pos_map.get(key, 0) + contracts

    # Compare
    mismatches: list[dict] = []

    # Check for phantom positions (in portfolio but not at IB)
    for key, our_qty in our_pos_map.items():
        ib_qty = ib_pos_map.get(key, 0)
        if ib_qty == 0:
            mismatches.append({
                "type": "PHANTOM",
                "symbol": key[0],
                "side": key[1],
                "portfolio_contracts": our_qty,
                "ib_contracts": 0,
                "message": f"Position in portfolio but NOT at IB: {key[0]} {key[1]} {our_qty}ct",
            })
        elif abs(ib_qty - our_qty) > 0.01:
            mismatches.append({
                "type": "QTY_MISMATCH",
                "symbol": key[0],
                "side": key[1],
                "portfolio_contracts": our_qty,
                "ib_contracts": ib_qty,
                "message": f"Quantity mismatch: {key[0]} {key[1]} portfolio={our_qty} IB={ib_qty}",
            })

    # Check for orphan positions (at IB but not in portfolio)
    for key, ib_qty in ib_pos_map.items():
        if key not in our_pos_map:
            mismatches.append({
                "type": "ORPHAN",
                "symbol": key[0],
                "side": key[1],
                "portfolio_contracts": 0,
                "ib_contracts": ib_qty,
                "message": f"Position at IB but NOT in portfolio: {key[0]} {key[1]} {ib_qty}ct",
            })

    report = {
        "run_id": run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "portfolio_positions": len(our_positions),
        "ib_positions": len([p for p in ib_positions if p.position != 0]),
        "mismatches": mismatches,
        "reconciled": len(mismatches) == 0,
    }

    if mismatches:
        for m in mismatches:
            print(f"  [RECONCILE] MISMATCH: {m['message']}")

        ledger.append(C.EventType.ALERT, run_id, "RECONCILIATION", {
            "alert_type": "POSITION_MISMATCH",
            "mismatches": mismatches,
        })

        alerting.alert(
            "HALT",
            f"POSITION MISMATCH: {len(mismatches)} discrepancies detected",
            {
                "run_id": run_id,
                "mismatches": "; ".join(m["message"] for m in mismatches),
            },
        )

        # Set posture to HALT on mismatch
        posture_state = store.load_posture_state()
        posture_state["posture"] = C.Posture.HALT
        posture_state["last_halt_at"] = datetime.now(timezone.utc).isoformat()
        store.save_posture_state(posture_state)

    ledger.append(C.EventType.RECONCILIATION, run_id, "IB_RECONCILE", {
        "reconciled": report["reconciled"],
        "portfolio_count": report["portfolio_positions"],
        "ib_count": report["ib_positions"],
        "mismatch_count": len(mismatches),
    })

    return report


# ---------------------------------------------------------------------------
# IB bracket verification — confirm stops are active at IB
# ---------------------------------------------------------------------------

def verify_ib_brackets(run_id: str) -> dict:
    """
    Query IB open orders and verify every open position has an active stop.
    Returns verification report. Alerts on missing stops.
    """
    from ib_gateway import get_connection

    portfolio = store.load_portfolio()
    positions = portfolio.get("positions", [])
    if not positions:
        return {"run_id": run_id, "status": "OK", "positions_checked": 0, "missing_stops": []}

    ib = get_connection()
    ib.sleep(1)

    # Get all open orders from IB
    open_trades = ib.openTrades()
    # Build set of active stop order IDs
    active_stop_ids: set[str] = set()
    for trade in open_trades:
        order = trade.order
        # StopOrder has orderType "STP"
        if order.orderType in ("STP", "STP LMT"):
            active_stop_ids.add(f"IB_{order.orderId}")

    # Check each position
    missing_stops: list[dict] = []
    for pos in positions:
        bracket = pos.get("bracket_status", {})
        stop_order_id = bracket.get("stop_order_id", "")

        # Only check IB-placed brackets (those starting with "IB_")
        if not stop_order_id.startswith("IB_"):
            continue

        if stop_order_id not in active_stop_ids:
            missing_stops.append({
                "position_id": pos["position_id"],
                "symbol": pos.get("symbol", ""),
                "side": pos.get("side", ""),
                "contracts": pos.get("contracts", 0),
                "stop_order_id": stop_order_id,
                "stop_price": pos.get("stop_price"),
            })

    report = {
        "run_id": run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "positions_checked": len([p for p in positions
                                  if p.get("bracket_status", {}).get("stop_order_id", "").startswith("IB_")]),
        "active_stops_at_ib": len(active_stop_ids),
        "missing_stops": missing_stops,
        "status": "OK" if not missing_stops else "ALERT",
    }

    if missing_stops:
        for m in missing_stops:
            print(f"  [BRACKET] MISSING STOP: {m['position_id']} {m['symbol']} "
                  f"{m['side']} — expected {m['stop_order_id']}")

        ledger.append(C.EventType.ALERT, run_id, "BRACKET_VERIFY", {
            "alert_type": "MISSING_STOP_ORDERS",
            "missing": missing_stops,
        })

        alerting.alert(
            "HALT",
            f"MISSING STOP ORDERS: {len(missing_stops)} positions unprotected",
            {
                "run_id": run_id,
                "positions": "; ".join(
                    f"{m['symbol']} {m['side']} {m['contracts']}ct"
                    for m in missing_stops
                ),
            },
        )

        # Set posture to HALT — unprotected positions are critical
        posture_state = store.load_posture_state()
        posture_state["posture"] = C.Posture.HALT
        posture_state["last_halt_at"] = datetime.now(timezone.utc).isoformat()
        store.save_posture_state(posture_state)

    return report


# ---------------------------------------------------------------------------
# Bracket trigger processing — called every reconcile cycle
# ---------------------------------------------------------------------------

def process_bracket_triggers(
    snapshots: dict[str, dict],
    run_id: str,
    paper: bool = True,
) -> list[dict]:
    """
    Check all open positions for stop/TP/T1/T2/trailing triggers.
    Handles both full closes and partial closes (scale-out).
    Returns the list of close records.
    """
    if not paper:
        return []  # Live bracket monitoring is exchange-driven

    portfolio = store.load_portfolio()
    positions = portfolio.get("positions", [])
    if not positions:
        return []

    # Build bar lookup by symbol — prefer 5m for intraday, fall back to 15m/1H.
    # Also map micro symbols (MES→ES, MNQ→NQ) so micro positions find their bars.
    _micro_to_standard = {"MES": "ES", "MNQ": "NQ", "MCL": "CL", "MGC": "GC", "MBT": "BTC"}
    bars_by_symbol: dict[str, list[dict]] = {}
    atr_by_symbol: dict[str, float] = {}
    for sym, snap in snapshots.items():
        bars = (snap.get("bars", {}).get("5m")
                or snap.get("bars", {}).get("15m")
                or snap.get("bars", {}).get("1H", []))
        if bars:
            bars_by_symbol[sym] = bars
        atr_val = snap.get("indicators", {}).get("atr_14_1H", 0.0) or snap.get("indicators", {}).get("atr_14_4H", 0.0)
        if atr_val:
            atr_by_symbol[sym] = atr_val
    # Add micro-symbol aliases
    for micro, standard in _micro_to_standard.items():
        if standard in bars_by_symbol and micro not in bars_by_symbol:
            bars_by_symbol[micro] = bars_by_symbol[standard]
        if standard in atr_by_symbol and micro not in atr_by_symbol:
            atr_by_symbol[micro] = atr_by_symbol[standard]

    triggered = check_bracket_triggers(positions, bars_by_symbol, atr_by_symbol=atr_by_symbol)
    closed: list[dict] = []

    for event in triggered:
        pos       = event["position"]
        trigger   = event["trigger"]
        exit_px   = event["exit_price"]

        if trigger == "T1":
            # Partial close — scale out T1
            sop = pos.get("scale_out_plan", {})
            t1_pct = sop.get("t1_pct", 50) / 100.0
            total = pos.get("contracts", 0)
            contracts_to_close = max(1, int(total * t1_pct))
            record = partial_close_position(pos, exit_px, contracts_to_close, "T1", run_id)
            closed.append(record)
        else:
            # Full close — STOP, T2, TRAILING_STOP, TAKE_PROFIT, TIME_EXIT
            record = close_position(pos, exit_px, trigger, run_id)
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

        intent_type = intent.get("intent_type", approval.get("intent_type"))
        if intent_type == C.IntentType.ROLL:
            receipt = execute_roll(approval, intent, snapshots, run_id, paper=paper)
            receipts.append(receipt)
            continue

        symbol   = intent.get("symbol", "ES")
        snapshot = snapshots.get(symbol, next(iter(snapshots.values()), {}))

        receipt = execute_approval(approval, intent, snapshot, run_id, paper=paper)
        receipts.append(receipt)

    return receipts
