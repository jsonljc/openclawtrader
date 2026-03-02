#!/usr/bin/env python3
"""IB execution adapter — order submission via Interactive Brokers.

Implements the same return dict shapes as paper_broker.simulate_market_fill()
so forge.py processes fills identically regardless of paper vs IB execution.

Functions:
    execute_market_order(ib, contract, side, contracts, ...) -> fill dict
    place_bracket_orders(ib, contract, parent_order_id, ...) -> bracket dict
    cancel_bracket(ib, bracket_order_ids) -> None
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Fill wait timeout (seconds)
FILL_TIMEOUT_SEC = 30

# IB uses this as "not yet reported" sentinel for commission
_IB_COMMISSION_SENTINEL = 1e+300


def execute_market_order(
    ib,
    contract,
    side: str,
    contracts: int,
    tick_size: float = 0.25,
    tick_value_usd: float = 12.50,
    point_value_usd: float = 50.0,
    fee_per_contract_round_trip_usd: float = 4.62,
    **kwargs,
) -> dict:
    """
    Submit a market order to IB and wait for fill.

    Returns a dict with the same shape as paper_broker.simulate_market_fill()
    so forge.py can process it identically.

    Args:
        ib:          Connected ib_insync.IB instance.
        contract:    Qualified IB contract.
        side:        "BUY" or "SELL"
        contracts:   Number of contracts.
        tick_size:   Contract tick size (0.25 for ES/NQ).
        tick_value_usd:  Dollar value per tick.
        point_value_usd: Dollar value per point.
        fee_per_contract_round_trip_usd: Round-trip fee per contract.

    Returns:
        Fill dict matching paper_broker schema:
        {status, fill_price, contracts_filled, contracts_requested,
         slippage_ticks, slippage_usd, fees_usd, fill_latency_ms,
         prng_seed, noise_ticks, reason}
    """
    from ib_insync import MarketOrder

    t0 = time.perf_counter()

    order = MarketOrder(side.upper(), contracts)
    trade = ib.placeOrder(contract, order)

    # Wait for fill
    filled = False
    deadline = time.time() + FILL_TIMEOUT_SEC

    while time.time() < deadline:
        ib.sleep(0.5)
        if trade.isDone():
            filled = True
            break

    latency_ms = int((time.perf_counter() - t0) * 1000)

    if not filled:
        # Timeout — cancel the order
        try:
            ib.cancelOrder(order)
            ib.sleep(1)
        except Exception:
            pass

        return {
            "status": "TIMED_OUT",
            "fill_price": None,
            "contracts_filled": 0,
            "contracts_requested": contracts,
            "slippage_ticks": 0,
            "slippage_usd": 0.0,
            "fees_usd": 0.0,
            "fill_latency_ms": latency_ms,
            "prng_seed": 0,
            "noise_ticks": 0,
            "reason": f"Order did not fill within {FILL_TIMEOUT_SEC}s",
        }

    # Check fill status
    order_status = trade.orderStatus.status
    if order_status in ("Cancelled", "ApiCancelled", "Inactive"):
        return {
            "status": "REJECTED",
            "reason": f"Order {order_status}: {trade.orderStatus.whyHeld or 'unknown'}",
            "prng_seed": 0,
            "reject_roll": 0.0,
            "fill_price": None,
            "contracts_filled": 0,
            "slippage_ticks": 0,
            "slippage_usd": 0.0,
            "fees_usd": 0.0,
            "fill_latency_ms": latency_ms,
        }

    # Extract fill info
    fills = trade.fills
    if not fills:
        return {
            "status": "REJECTED",
            "reason": "No fills received",
            "prng_seed": 0,
            "reject_roll": 0.0,
            "fill_price": None,
            "contracts_filled": 0,
            "slippage_ticks": 0,
            "slippage_usd": 0.0,
            "fees_usd": 0.0,
            "fill_latency_ms": latency_ms,
        }

    # Calculate weighted average fill price
    total_qty = 0
    total_cost = 0.0
    total_commission = 0.0

    for fill in fills:
        qty = fill.execution.shares
        px = fill.execution.avgPrice
        total_qty += qty
        total_cost += qty * px
        if fill.commissionReport:
            comm = fill.commissionReport.commission
            # Guard against IB's "not yet reported" sentinel (max float)
            if 0 < comm < _IB_COMMISSION_SENTINEL:
                total_commission += comm

    avg_fill_price = round(total_cost / total_qty, 4) if total_qty > 0 else 0.0
    contracts_filled = int(total_qty)

    # Slippage: estimate based on reference price (last known price before order)
    # We don't have a reference price here, so slippage is computed as 0
    # forge.py will handle slippage tracking via exec_quality
    slippage_ticks = 0
    slippage_usd = 0.0

    # Fees: use actual commission if available, else estimate
    if total_commission > 0:
        fees_usd = round(total_commission, 2)
    else:
        fees_usd = round(contracts_filled * fee_per_contract_round_trip_usd / 2.0, 2)

    status = "PARTIALLY_FILLED" if contracts_filled < contracts else "FILLED"

    return {
        "status": status,
        "fill_price": avg_fill_price,
        "contracts_filled": contracts_filled,
        "contracts_requested": contracts,
        "slippage_ticks": slippage_ticks,
        "slippage_usd": slippage_usd,
        "fees_usd": fees_usd,
        "fill_latency_ms": latency_ms,
        "prng_seed": 0,
        "noise_ticks": 0,
        "reason": None,
    }


def place_bracket_orders(
    ib,
    contract,
    parent_order_id: int,
    side: str,
    contracts: int,
    stop_price: float,
    tp_price: float,
) -> dict:
    """
    Place OCA bracket (stop + take-profit) linked to parent fill.

    The bracket orders are linked via IB's OCA (One-Cancels-All) group
    so when one fills, the other is automatically cancelled.

    Args:
        ib:              Connected ib_insync.IB instance.
        contract:        Qualified IB contract.
        parent_order_id: Order ID of the parent fill (for reference).
        side:            Parent order side ("BUY" or "SELL").
        contracts:       Number of contracts to protect.
        stop_price:      Stop-loss trigger price.
        tp_price:        Take-profit limit price.

    Returns:
        Bracket dict matching forge.py's expected shape:
        {"stop": {order_id, type, price, status, placed_at, placement_latency_ms},
         "take_profit": {order_id, type, price, status, placed_at, placement_latency_ms}}
    """
    from ib_insync import StopOrder, LimitOrder

    t0 = time.perf_counter()
    placed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    # Bracket side is opposite to parent
    bracket_side = "SELL" if side.upper() == "BUY" else "BUY"

    # OCA group name links the two orders
    oca_group = f"OCA_{parent_order_id}_{int(time.time())}"

    # Stop-loss order
    stop_order = StopOrder(bracket_side, contracts, round(stop_price, 2))
    stop_order.ocaGroup = oca_group
    stop_order.ocaType = 1  # Cancel remaining on fill
    stop_trade = ib.placeOrder(contract, stop_order)

    # Take-profit order
    tp_order = LimitOrder(bracket_side, contracts, round(tp_price, 2))
    tp_order.ocaGroup = oca_group
    tp_order.ocaType = 1
    tp_trade = ib.placeOrder(contract, tp_order)

    ib.sleep(1)  # Allow orders to be acknowledged

    latency_ms = int((time.perf_counter() - t0) * 1000)

    bracket = {
        "stop": {
            "order_id": f"IB_{stop_order.orderId}",
            "type": "STOP_MARKET",
            "price": stop_price,
            "status": "ACTIVE",
            "placed_at": placed_at,
            "placement_latency_ms": latency_ms,
        },
        "take_profit": {
            "order_id": f"IB_{tp_order.orderId}",
            "type": "LIMIT",
            "price": tp_price,
            "status": "ACTIVE",
            "placed_at": placed_at,
            "placement_latency_ms": latency_ms,
        },
    }

    logger.info(
        "Bracket placed: stop=%s @ %.2f, TP=%s @ %.2f (OCA=%s)",
        bracket["stop"]["order_id"], stop_price,
        bracket["take_profit"]["order_id"], tp_price,
        oca_group,
    )

    return bracket


def cancel_bracket(ib, bracket_order_ids: list[str]) -> None:
    """
    Cancel bracket orders (used for position close, roll, partial exit).

    Args:
        ib:                Connected ib_insync.IB instance.
        bracket_order_ids: List of order ID strings (e.g. ["IB_123", "IB_456"]).
    """
    for order_id_str in bracket_order_ids:
        try:
            # Extract numeric IB order ID
            ib_order_id = int(order_id_str.replace("IB_", ""))

            # Find the open order
            for open_order in ib.openOrders():
                if open_order.orderId == ib_order_id:
                    ib.cancelOrder(open_order)
                    logger.info("Cancelled bracket order %s", order_id_str)
                    break
            else:
                logger.warning("Bracket order %s not found in open orders", order_id_str)
        except Exception as exc:
            logger.error("Failed to cancel bracket order %s: %s", order_id_str, exc)

    ib.sleep(1)  # Allow cancellations to process
