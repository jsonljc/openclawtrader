#!/usr/bin/env python3
"""Emergency flatten — cancel all orders, close all positions, set HALT.

This is the kill switch. When something goes wrong, run this to:
1. Cancel all open IB orders
2. Close all positions via IB market orders
3. Update portfolio state (remove closed positions, update cash/margin)
4. Set posture to HALT
5. Alert via Telegram

Usage:
    OPENCLAW_IB_PORT=4002 python3 run_emergency_flatten.py --dry-run   # preview
    OPENCLAW_IB_PORT=4001 python3 run_emergency_flatten.py             # live
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "workspace-forge"))

from shared import contracts as C
from shared import identifiers as IDs
from shared import ledger
from shared import state_store as store
from shared import alerting


def _log(msg: str) -> None:
    print(f"[EMERGENCY {datetime.now(timezone.utc).strftime('%H:%M:%S')}] {msg}")


def run_emergency_flatten(dry_run: bool = False) -> dict:
    """
    Cancel all open orders, flatten all positions, set HALT.
    Returns summary dict.
    """
    run_id = IDs.make_run_id()
    _log(f"Starting emergency flatten (dry_run={dry_run}) — {run_id}")

    portfolio = store.load_portfolio()
    positions = portfolio.get("positions", [])
    _log(f"  Open positions: {len(positions)}")

    if not positions:
        _log("  No positions to flatten")
        if not dry_run:
            # Still set HALT as a safety measure
            posture_state = store.load_posture_state()
            posture_state["posture"] = C.Posture.HALT
            posture_state["last_halt_at"] = datetime.now(timezone.utc).isoformat()
            store.save_posture_state(posture_state)
            alerting.alert("HALT", "Emergency flatten executed — no positions open, HALT set",
                           {"run_id": run_id})
        return {"run_id": run_id, "status": "OK", "positions_closed": 0, "dry_run": dry_run}

    # Preview all positions that will be closed
    for pos in positions:
        _log(f"    {pos.get('position_id')}: {pos.get('symbol')} {pos.get('side')} "
             f"{pos.get('contracts')}ct @ {pos.get('entry_price')}")

    if dry_run:
        _log("  DRY RUN — no actions taken")
        return {
            "run_id": run_id,
            "status": "DRY_RUN",
            "positions_to_close": len(positions),
            "positions": [
                {"position_id": p["position_id"], "symbol": p.get("symbol"),
                 "side": p.get("side"), "contracts": p.get("contracts")}
                for p in positions
            ],
        }

    # --- Live execution ---
    from ib_gateway import get_connection
    from ib_broker import execute_market_order, cancel_bracket

    ib = get_connection()
    _log("  IB connected")

    # Step 1: Cancel ALL open orders
    open_orders = ib.openOrders()
    _log(f"  Cancelling {len(open_orders)} open orders...")
    for order in open_orders:
        try:
            ib.cancelOrder(order)
        except Exception as exc:
            _log(f"    Failed to cancel order {order.orderId}: {exc}")
    if open_orders:
        ib.sleep(2)  # Allow cancellations to process
    _log(f"  Cancelled {len(open_orders)} orders")

    # Step 2: Close all positions via IB market orders
    closed = []
    failed = []
    for pos in positions:
        symbol = pos.get("symbol", "ES")
        side = pos.get("side", "LONG")
        contracts = pos.get("contracts", 0)
        if contracts <= 0:
            continue

        # Determine close side
        close_side = "SELL" if side == "LONG" else "BUY"

        # Resolve IB contract
        from ib_insync import Future
        # Check if it's a micro contract
        ib_symbol = symbol
        if symbol in ("ES", "NQ"):
            # Check if position was opened with micro
            bracket_status = pos.get("bracket_status", {})
            stop_id = bracket_status.get("stop_order_id", "")
            if stop_id.startswith("IB_"):
                # IB position — use whatever symbol is in portfolio
                pass
        ib_contract = Future(ib_symbol, exchange="CME", currency="USD")
        qualified = ib.qualifyContracts(ib_contract)
        if qualified:
            ib_contract = qualified[0]

        strategy = store.load_strategy_registry().get(pos.get("strategy_id", ""), {})
        tick_size = strategy.get("tick_size", 0.25)
        pv = pos.get("point_value_usd", 50.0)
        tv = tick_size * pv if pv == 50.0 else strategy.get("tick_value_usd", 12.50)

        _log(f"  Closing {pos['position_id']}: {close_side} {contracts}ct {ib_symbol}")
        try:
            fill = execute_market_order(
                ib, ib_contract, close_side, contracts,
                tick_size=tick_size, tick_value_usd=tv,
                point_value_usd=pv,
            )
            if fill["status"] in ("FILLED", "PARTIALLY_FILLED"):
                closed.append({
                    "position_id": pos["position_id"],
                    "symbol": symbol,
                    "side": side,
                    "contracts_closed": fill["contracts_filled"],
                    "fill_price": fill["fill_price"],
                })
                _log(f"    FILLED @ {fill['fill_price']}")
            else:
                failed.append({
                    "position_id": pos["position_id"],
                    "reason": fill.get("reason", fill["status"]),
                })
                _log(f"    FAILED: {fill.get('reason', fill['status'])}")
        except Exception as exc:
            failed.append({"position_id": pos["position_id"], "reason": str(exc)})
            _log(f"    ERROR: {exc}")

    # Step 3: Update portfolio state — close all positions in portfolio JSON
    import forge
    portfolio = store.load_portfolio()
    for close_info in closed:
        pos = next(
            (p for p in portfolio.get("positions", [])
             if p.get("position_id") == close_info["position_id"]),
            None,
        )
        if pos:
            forge.close_position(pos, close_info["fill_price"], "EMERGENCY_FLATTEN", run_id)
            # Reload portfolio after each close (close_position saves internally)
            portfolio = store.load_portfolio()

    # Step 4: Set posture to HALT
    posture_state = store.load_posture_state()
    posture_state["posture"] = C.Posture.HALT
    posture_state["last_halt_at"] = datetime.now(timezone.utc).isoformat()
    store.save_posture_state(posture_state)

    # Step 5: Ledger + Alert
    ledger.append(C.EventType.ALERT, run_id, "EMERGENCY_FLATTEN", {
        "alert_type": "EMERGENCY_FLATTEN",
        "positions_closed": len(closed),
        "positions_failed": len(failed),
        "orders_cancelled": len(open_orders),
    })

    alerting.alert(
        "HALT",
        f"EMERGENCY FLATTEN: {len(closed)} positions closed, "
        f"{len(failed)} failed, {len(open_orders)} orders cancelled",
        {
            "run_id": run_id,
            "closed": [c["position_id"] for c in closed],
            "failed": [f["position_id"] for f in failed],
        },
    )

    result = {
        "run_id": run_id,
        "status": "OK" if not failed else "PARTIAL",
        "positions_closed": len(closed),
        "positions_failed": len(failed),
        "orders_cancelled": len(open_orders),
        "closed": closed,
        "failed": failed,
        "dry_run": False,
    }
    _log(f"Emergency flatten complete: {result['status']} — "
         f"{len(closed)} closed, {len(failed)} failed")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Emergency flatten — cancel all orders, close all positions, set HALT"
    )
    parser.add_argument("--dry-run", action="store_true", default=False,
                        help="Preview actions without executing")
    args = parser.parse_args()

    result = run_emergency_flatten(dry_run=args.dry_run)
    if result.get("positions_failed"):
        _log("WARNING: Some positions failed to close — check IB manually!")
        sys.exit(1)


if __name__ == "__main__":
    main()
