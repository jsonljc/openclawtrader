#!/usr/bin/env python3
"""Main orchestrator — Futures Trading System v1.1 — spec Section 2.3 / 2.4.

Modes:
    full        4H bar close: Watchtower → C3PO → Sentinel → Forge
    refresh     1H bar close: C3PO regime+health update only (no new intents unless strong)
    reconcile   Every 15 min: bracket triggers, position MTM, bracket integrity
    recovery    On startup: crash recovery protocol

Usage:
    python run_cycle.py --mode full
    python run_cycle.py --mode reconcile
    python run_cycle.py --mode recovery
    python run_cycle.py --mode full --force-signal   # force entry signal (dev/test)
"""

from __future__ import annotations
import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Path setup: each workspace has its own module namespace
# ---------------------------------------------------------------------------
_ROOT = Path(__file__).parent
sys.path.insert(0, str(_ROOT))                              # shared/
sys.path.insert(0, str(_ROOT / "workspace-c3po"))           # brain, data_stub
sys.path.insert(0, str(_ROOT / "workspace-sentinel"))       # sentinel
sys.path.insert(0, str(_ROOT / "workspace-forge"))          # forge, paper_broker
sys.path.insert(0, str(_ROOT / "workspace-watchtower"))     # watchtower

from shared import contracts as C
from shared import identifiers as IDs
from shared import ledger
from shared import state_store as store
from shared.correlation import update_portfolio_heat_correlations

import brain
import sentinel
import forge
import watchtower
import posture
from data_source import get_all_snapshots


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log(msg: str) -> None:
    print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {msg}")


# ---------------------------------------------------------------------------
# Full evaluation cycle — spec 2.4 "Full evaluation"
# ---------------------------------------------------------------------------

def run_full(
    run_id: str,
    param_version: str = "PV_0001",
    paper: bool = True,
    force_signal: bool = False,
) -> dict:
    """
    Watchtower → C3PO → Sentinel → Forge.
    Returns summary dict with counts of intents, approvals, executions.
    """
    t0 = time.perf_counter()
    _log(f"[FULL] {run_id}")

    # 1. Get market data
    try:
        snapshots = get_all_snapshots(force_signal=force_signal)
    except Exception as exc:
        _log(f"  FATAL: data fetch failed: {exc}")
        ledger.append(C.EventType.ALERT, run_id, "ORCHESTRATOR", {
            "alert_type": "DATA_FETCH_ERROR", "error": str(exc),
        })
        return {"run_id": run_id, "status": "ERROR", "reason": f"Data fetch failed: {exc}"}
    _log(f"  Snapshots loaded: {list(snapshots.keys())}")

    # 2. Posture update (Phase 2: auto-escalate/recover)
    try:
        portfolio = store.load_portfolio()
        posture.update_posture(portfolio, param_version, run_id)
    except Exception as exc:
        _log(f"  ERROR in posture update: {exc}")
        ledger.append(C.EventType.ALERT, run_id, "ORCHESTRATOR", {
            "alert_type": "POSTURE_ERROR", "error": str(exc),
        })
        # Continue — posture failure shouldn't block the whole cycle

    # 3. Watchtower health check
    try:
        health = watchtower.run_health_check(snapshots, run_id)
    except Exception as exc:
        _log(f"  ERROR in watchtower: {exc}")
        ledger.append(C.EventType.ALERT, run_id, "ORCHESTRATOR", {
            "alert_type": "WATCHTOWER_ERROR", "error": str(exc),
        })
        return {"run_id": run_id, "status": "ERROR", "reason": f"Watchtower failed: {exc}"}
    _log(f"  Watchtower: {health['status']}"
         + (f" — {health['active_alerts']}" if health["active_alerts"] else ""))

    if health["status"] == C.WatchtowerStatus.HALT:
        _log("  HALT: stopping cycle")
        return {"run_id": run_id, "status": "HALTED", "reason": "Watchtower HALT",
                "alerts": health["active_alerts"]}

    wt_status = health["status"]

    # 4. C3PO: compute regime, health, emit intents
    try:
        intents, regime_report, health_by_strategy = brain.run_brain(
            snapshots, run_id, param_version, wt_status
        )
    except Exception as exc:
        _log(f"  ERROR in brain: {exc}")
        ledger.append(C.EventType.ALERT, run_id, "ORCHESTRATOR", {
            "alert_type": "BRAIN_ERROR", "error": str(exc),
        })
        return {"run_id": run_id, "status": "ERROR", "reason": f"Brain failed: {exc}"}
    _log(f"  C3PO intents: {len(intents)}")
    for i in intents:
        _log(f"    → {i['intent_type']} {i.get('symbol')} {i.get('side', '')} | {i['intent_id']}")

    if not intents:
        elapsed = time.perf_counter() - t0
        return {"run_id": run_id, "status": "NO_SIGNAL", "intents": 0,
                "approvals": 0, "executions": 0, "cycle_sec": round(elapsed, 2)}

    # 5. Sentinel: validate + size
    try:
        approvals = sentinel.run_sentinel(
            intents, snapshots, run_id, param_version,
            regime_report=regime_report,
            health_by_strategy=health_by_strategy,
        )
    except Exception as exc:
        _log(f"  ERROR in sentinel: {exc}")
        ledger.append(C.EventType.ALERT, run_id, "ORCHESTRATOR", {
            "alert_type": "SENTINEL_ERROR", "error": str(exc),
        })
        return {"run_id": run_id, "status": "ERROR", "reason": f"Sentinel failed: {exc}"}
    _log(f"  Sentinel decisions: {len(approvals)}")
    for a in approvals:
        _log(f"    → {a['decision']} | {a.get('approval_id')} | {a.get('reasons', [])}")

    approved_list = [a for a in approvals
                     if a["decision"] in (C.RiskDecision.APPROVE, C.RiskDecision.APPROVE_REDUCED)]

    if not approved_list:
        elapsed = time.perf_counter() - t0
        return {"run_id": run_id, "status": "DENIED", "intents": len(intents),
                "approvals": 0, "executions": 0, "cycle_sec": round(elapsed, 2)}

    # 6. Forge: execute
    try:
        intents_by_id = {i["intent_id"]: i for i in intents}
        receipts = forge.run_forge(approvals, intents_by_id, snapshots, run_id, paper=paper)
    except Exception as exc:
        _log(f"  ERROR in forge: {exc}")
        ledger.append(C.EventType.ALERT, run_id, "ORCHESTRATOR", {
            "alert_type": "FORGE_ERROR", "error": str(exc),
            "partial_execution": True,
        })
        return {"run_id": run_id, "status": "ERROR",
                "reason": f"Forge failed (partial execution possible): {exc}",
                "intents": len(intents), "approvals": len(approved_list)}
    _log(f"  Forge receipts: {len(receipts)}")
    for r in receipts:
        _log(f"    → {r['status']} | {r.get('execution_id')} "
             f"fill={r.get('fill', {}).get('avg_fill_price')}")

    # 7. Portfolio heat: update correlations_20d (Phase 3)
    portfolio = store.load_portfolio()
    update_portfolio_heat_correlations(portfolio)

    elapsed = time.perf_counter() - t0
    return {
        "run_id":          run_id,
        "status":          "OK",
        "intents":         len(intents),
        "approvals":       len(approved_list),
        "executions":      len(receipts),
        "open_positions":  len(portfolio.get("positions", [])),
        "equity_usd":      portfolio["account"]["equity_usd"],
        "cycle_sec":       round(elapsed, 2),
        "wt_status":       wt_status,
    }


# ---------------------------------------------------------------------------
# Refresh cycle — spec 2.4 "Lightweight refresh"
# ---------------------------------------------------------------------------

def run_refresh(
    run_id: str,
    param_version: str = "PV_0001",
) -> dict:
    """
    1H bar close: update regime and health only.
    No new entry intents unless signal is strong.
    """
    _log(f"[REFRESH] {run_id}")
    snapshots = get_all_snapshots()
    intents, regime_report, health_by_strategy = brain.run_brain(
        snapshots, run_id, param_version, C.WatchtowerStatus.HEALTHY
    )
    _log(f"  C3PO: {len(intents)} intents (refresh — not sent to Sentinel)")

    portfolio = store.load_portfolio()
    return {
        "run_id":         run_id,
        "status":         "OK",
        "regime_updated": True,
        "intents_pending": len(intents),
        "equity_usd":     portfolio["account"]["equity_usd"],
    }


# ---------------------------------------------------------------------------
# Reconciliation cycle — spec 2.4 / 8.7
# ---------------------------------------------------------------------------

def run_reconciliation(
    run_id: str,
    param_version: str = "PV_0001",
    paper: bool = True,
) -> dict:
    """
    Every 15 min:
    1. Check bracket triggers
    2. Update MTM on open positions
    3. Verify bracket integrity
    Returns summary.
    """
    _log(f"[RECONCILE] {run_id}")
    snapshots = get_all_snapshots()
    portfolio = store.load_portfolio()
    positions = portfolio.get("positions", [])

    # 1. Process bracket triggers
    closed: list[dict] = []
    if positions and paper:
        closed = forge.process_bracket_triggers(snapshots, run_id, paper=paper)
        if closed:
            _log(f"  Bracket triggers fired: {len(closed)}")
            for c in closed:
                _log(f"    → CLOSED {c['position_id']} via {c['trigger']} "
                     f"PnL=${c['realized_pnl']:.2f}")
            portfolio = store.load_portfolio()  # reload after closings
            positions = portfolio.get("positions", [])

    # 2. Mark-to-market open positions
    for pos in positions:
        sym  = pos.get("symbol", "")
        snap = snapshots.get(sym, {})
        if not snap:
            continue
        current_price = snap.get("indicators", {}).get("last_price",
                        snap["bars"]["1H"][-1]["c"] if snap.get("bars", {}).get("1H") else pos["entry_price"])
        pos["current_price"] = current_price

        side       = pos.get("side", "LONG")
        entry      = pos.get("entry_price", current_price)
        contracts  = pos.get("contracts", 1)
        pv         = pos.get("point_value_usd", 50.0)
        if side == "LONG":
            unrealized = (current_price - entry) * pv * contracts
        else:
            unrealized = (entry - current_price) * pv * contracts
        pos["unrealized_pnl_usd"] = round(unrealized, 2)

    # 3. Bracket integrity check
    wt_health = watchtower.run_health_check(snapshots, run_id)
    bracket_ok = wt_health["checks"].get("bracket_integrity") == "OK"

    # Save MTM updates
    equity_base = portfolio["account"]["equity_usd"]
    unrealized  = sum(p.get("unrealized_pnl_usd", 0) for p in positions)
    margin_used = portfolio["account"].get("margin_used_usd", 0)
    cash        = portfolio["account"].get("cash_usd", equity_base)
    portfolio["account"]["equity_usd"]    = round(cash + margin_used + unrealized, 2)
    portfolio["pnl"]["unrealized_usd"]    = round(unrealized, 2)
    peak = portfolio["account"].get("peak_equity_usd", portfolio["account"]["equity_usd"])
    portfolio["account"]["peak_equity_usd"] = max(peak, portfolio["account"]["equity_usd"])
    dd = (peak - portfolio["account"]["equity_usd"]) / peak * 100.0 if peak > 0 else 0.0
    portfolio["pnl"]["portfolio_dd_pct"]  = round(dd, 4)
    store.save_portfolio(portfolio)

    # Update correlations_20d (Phase 3)
    update_portfolio_heat_correlations(portfolio)

    ledger.append(C.EventType.RECONCILIATION, run_id, "RECONCILE", {
        "positions_open":   len(positions),
        "positions_closed": len(closed),
        "bracket_ok":       bracket_ok,
        "unrealized_usd":   unrealized,
        "wt_status":        wt_health["status"],
    })

    return {
        "run_id":            run_id,
        "status":            "OK",
        "positions_open":    len(positions),
        "positions_closed":  len(closed),
        "bracket_ok":        bracket_ok,
        "unrealized_usd":    round(unrealized, 2),
        "equity_usd":        portfolio["account"]["equity_usd"],
    }


# ---------------------------------------------------------------------------
# Crash recovery — spec 3.3
# ---------------------------------------------------------------------------

def run_recovery(run_id: str) -> dict:
    """
    On system startup: execute crash recovery protocol.
    """
    _log(f"[RECOVERY] {run_id}")
    report = watchtower.run_crash_recovery(run_id)

    _log(f"  Recovery: {'CLEAN' if report['clean'] else 'ANOMALIES FOUND'}")
    for a in report.get("anomalies", []):
        _log(f"    ANOMALY: {a}")
    for action in report.get("actions", []):
        _log(f"    ACTION: {action}")

    return {"run_id": run_id, **report}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Futures Trading System — cycle runner")
    parser.add_argument(
        "--mode", choices=["full", "refresh", "reconcile", "recovery"],
        default="full", help="Cycle mode (default: full)"
    )
    parser.add_argument(
        "--paper", action="store_true", default=True,
        help="Paper trading mode (default: True)"
    )
    parser.add_argument(
        "--param-version", default="PV_0001",
        help="Parameter set version (default: PV_0001)"
    )
    parser.add_argument(
        "--force-signal", action="store_true", default=False,
        help="Force market data to produce an entry signal (dev/test)"
    )
    args = parser.parse_args()

    run_id = IDs.make_run_id()

    # System start event
    if args.mode in ("full", "recovery"):
        ledger.append(C.EventType.SYSTEM_START, run_id, run_id, {
            "mode":          args.mode,
            "param_version": args.param_version,
            "paper":         args.paper,
        })

    t0 = time.perf_counter()

    if args.mode == "full":
        result = run_full(run_id, args.param_version, args.paper, args.force_signal)
    elif args.mode == "refresh":
        result = run_refresh(run_id, args.param_version)
    elif args.mode == "reconcile":
        result = run_reconciliation(run_id, args.param_version, args.paper)
    elif args.mode == "recovery":
        result = run_recovery(run_id)

    elapsed = time.perf_counter() - t0
    result["elapsed_sec"] = round(elapsed, 3)

    _log(f"Done in {elapsed:.2f}s — {result}")

    if args.mode in ("full", "recovery"):
        ledger.append(C.EventType.SYSTEM_STOP, run_id, run_id, {
            "mode":    args.mode,
            "elapsed": round(elapsed, 3),
            "result":  result.get("status", "?"),
        })


if __name__ == "__main__":
    main()
