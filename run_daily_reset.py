#!/usr/bin/env python3
"""Daily Reset Audit — runs at 06:00 ET (pre-market).

Actions:
    1. Position reconciliation vs broker (IB) or portfolio state (paper)
    2. Bracket integrity verification
    3. Daily counter reset (trade counts, PnL counters)
    4. Opening equity snapshot
    5. Ledger chain integrity check
    6. FREEZE on critical issues

Usage:
    python run_daily_reset.py
    python run_daily_reset.py --dry-run
    python run_daily_reset.py --paper  (default)
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

_ROOT = Path(__file__).parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "workspace-c3po"))
sys.path.insert(0, str(_ROOT / "workspace-forge"))
sys.path.insert(0, str(_ROOT / "workspace-watchtower"))

from shared import contracts as C
from shared import identifiers as IDs
from shared import ledger
from shared import state_store as store
from shared import alerting

try:
    import zoneinfo
    ET = zoneinfo.ZoneInfo("America/New_York")
except ImportError:
    ET = timezone(timedelta(hours=-5))


def _log(msg: str) -> None:
    print(f"[DAILY_RESET {datetime.now(timezone.utc).strftime('%H:%M:%S')}] {msg}")


def run_daily_reset(dry_run: bool = False, paper: bool = True) -> dict:
    """
    Execute the pre-market daily reset audit.

    Returns a result dict with status and any issues found.
    """
    run_id = IDs.make_run_id()
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y-%m-%d")
    issues: list[str] = []
    actions: list[str] = []
    freeze = False

    _log(f"Starting daily reset audit (dry_run={dry_run})")

    portfolio = store.load_portfolio()
    posture_state = store.load_posture_state()
    positions = portfolio.get("positions", [])
    equity = portfolio["account"]["equity_usd"]

    # 1. Position reconciliation
    _log("  [1/6] Position reconciliation")
    if not paper:
        try:
            sys.path.insert(0, str(_ROOT / "workspace-forge"))
            import forge
            recon = forge.run_reconciliation_ib(run_id)
            if not recon.get("reconciled", True):
                for m in recon.get("mismatches", []):
                    issues.append(f"Position mismatch: {m.get('type', '?')}: {m.get('message', '?')}")
                _log(f"    MISMATCH: {len(recon.get('mismatches', []))} discrepancies")
            else:
                _log("    OK — positions reconciled with IB")
                actions.append("positions_reconciled_ib")
        except Exception as exc:
            issues.append(f"IB reconciliation failed: {exc}")
            _log(f"    ERROR: {exc}")
    else:
        # Paper mode: verify portfolio state consistency
        for pos in positions:
            if not pos.get("position_id"):
                issues.append(f"Position missing position_id: {pos.get('symbol', '?')}")
            if pos.get("contracts", 0) <= 0:
                issues.append(f"Position {pos.get('position_id', '?')} has 0 contracts")
            if pos.get("stop_price") is None:
                issues.append(f"Position {pos.get('position_id', '?')} missing stop_price")
        if not issues:
            _log(f"    OK — {len(positions)} positions verified")
        actions.append("positions_verified_paper")

    # 2. Bracket integrity
    _log("  [2/6] Bracket integrity")
    for pos in positions:
        bs = pos.get("bracket_status", {})
        if bs.get("stop_status") != "ACTIVE":
            issues.append(
                f"Position {pos.get('position_id', '?')} stop not ACTIVE: {bs.get('stop_status')}"
            )
        if bs.get("tp_status") != "ACTIVE":
            issues.append(
                f"Position {pos.get('position_id', '?')} TP not ACTIVE: {bs.get('tp_status')}"
            )
    if not any("stop not ACTIVE" in i or "TP not ACTIVE" in i for i in issues):
        _log(f"    OK — all {len(positions)} positions have active brackets")
    actions.append("brackets_checked")

    # 3. Daily counter reset
    _log("  [3/6] Resetting daily counters")
    pnl = portfolio.get("pnl", {})
    prev_today = pnl.get("total_today_usd", 0.0)
    if not dry_run:
        pnl["realized_today_usd"] = 0.0
        pnl["total_today_usd"] = 0.0
        pnl["total_today_pct"] = 0.0
    _log(f"    Previous day PnL: ${prev_today:.2f} → reset to 0")
    actions.append("daily_counters_reset")

    # 4. Opening equity snapshot
    _log("  [4/6] Opening equity snapshot")
    opening_equity = portfolio["account"]["equity_usd"]
    if not dry_run:
        portfolio["account"]["opening_equity_usd"] = opening_equity
    _log(f"    Opening equity: ${opening_equity:,.2f}")
    actions.append(f"opening_equity_set_{opening_equity:.2f}")

    # 5. Ledger chain integrity
    _log("  [5/6] Ledger chain integrity check")
    try:
        chain_ok, chain_msg = ledger.verify_integrity()
        if not chain_ok:
            issues.append("Ledger chain integrity FAILED — possible corruption")
            _log("    FAILED — chain broken")
            freeze = True
        else:
            _log("    OK — chain verified")
    except Exception as exc:
        issues.append(f"Ledger verification error: {exc}")
        _log(f"    ERROR: {exc}")
    actions.append("ledger_chain_checked")

    # 6. FREEZE check
    _log("  [6/6] Critical issue assessment")
    critical_issues = [i for i in issues if "FAILED" in i or "mismatch" in i.lower()]
    if critical_issues or freeze:
        freeze = True
        _log(f"    FREEZE: {len(critical_issues)} critical issues")
        if not dry_run:
            posture_state["posture"] = C.Posture.HALT
            posture_state["posture_since"] = now.isoformat()
            posture_state["freeze_reason"] = "; ".join(critical_issues)
            alerting.alert("HALT", f"DAILY RESET FREEZE: {'; '.join(critical_issues)}",
                           {"issues": critical_issues, "date": date_str})
    else:
        _log("    OK — no critical issues")
    actions.append("freeze_check_done")

    # Persist
    if not dry_run:
        store.save_portfolio(portfolio)
        store.save_posture_state(posture_state)

        ledger.append(C.EventType.DAILY_SNAPSHOT, run_id, f"RESET_{date_str}", {
            "type": "DAILY_RESET",
            "date": date_str,
            "opening_equity_usd": opening_equity,
            "positions_open": len(positions),
            "issues": issues,
            "actions": actions,
            "freeze": freeze,
            "posture": posture_state.get("posture", C.Posture.NORMAL),
        })
        _log("  State persisted")
    else:
        _log("  DRY RUN — no state changes written")

    result = {
        "run_id": run_id,
        "date": date_str,
        "opening_equity_usd": opening_equity,
        "positions_open": len(positions),
        "issues": issues,
        "actions": actions,
        "freeze": freeze,
        "dry_run": dry_run,
    }
    _log(f"Daily reset complete: {len(issues)} issues, freeze={freeze}")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Daily Reset Audit — 06:00 ET pre-market")
    parser.add_argument("--dry-run", action="store_true", default=False,
                        help="Preview actions without persisting state")
    parser.add_argument("--paper", action="store_true", default=True)
    parser.add_argument("--no-paper", action="store_true", default=False)
    args = parser.parse_args()

    paper = args.paper and not args.no_paper
    result = run_daily_reset(dry_run=args.dry_run, paper=paper)
    if result["freeze"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
