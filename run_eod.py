#!/usr/bin/env python3
"""Daily end-of-day routine — spec Section 11.2 / 13.3.

Runs once at POST_CLOSE (after 15:45 ET) or manually.

Actions:
    1. DAILY_SNAPSHOT ledger event
    2. Overnight hold policy evaluation for each position
    3. Update consecutive_positive_days in posture state
    4. Reset daily PnL counters
    5. Increment bars_held on all open positions

Usage:
    python run_eod.py
    python run_eod.py --dry-run   # preview without persisting
"""

from __future__ import annotations
import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "workspace-c3po"))

from shared import contracts as C
from shared import identifiers as IDs
from shared import ledger
from shared import state_store as store
from data_stub import get_all_snapshots


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log(msg: str) -> None:
    print(f"[EOD {datetime.now(timezone.utc).strftime('%Y-%m-%d')}] {msg}")


# ---------------------------------------------------------------------------
# Overnight hold policy — spec 11.2
# ---------------------------------------------------------------------------

def evaluate_overnight_hold(
    positions: list[dict],
    snapshots: dict[str, dict],
    params: dict,
) -> list[dict]:
    """
    Evaluate each open position against overnight hold rules.
    Returns list of recommended actions.
    """
    op = params.get("overnight", {})
    flatten_vol_thresh  = op.get("flatten_vol_pct_threshold", 0.80)
    flatten_loss_thresh = op.get("flatten_loss_pct_of_stop", 0.50)
    partial_thresh      = op.get("partial_exit_profit_progress", 0.50)
    stop_tighten_pct    = op.get("stop_tightening_pct", 0.30)

    actions: list[dict] = []

    for pos in positions:
        sym    = pos.get("symbol", "")
        snap   = snapshots.get(sym, {})
        vol_pct = snap.get("external", {}).get("vix_percentile_252d", 0.3)
        price   = snap.get("indicators", {}).get("last_price", pos.get("current_price", 0.0))

        side         = pos.get("side", "LONG")
        entry        = pos.get("entry_price", price)
        stop         = pos.get("stop_price")
        tp           = pos.get("take_profit_price")
        pv           = pos.get("point_value_usd", 50.0)
        contracts    = pos.get("contracts", 1)
        risk_at_stop = pos.get("risk_at_stop_usd", 0.0)
        unrealized   = pos.get("unrealized_pnl_usd", 0.0)

        # Rule 1: High vol → flatten
        if vol_pct > flatten_vol_thresh:
            actions.append({
                "position_id": pos["position_id"],
                "action":      "FLATTEN",
                "reason":      f"vol_percentile={vol_pct:.2f} > {flatten_vol_thresh}; gap risk too high",
            })
            continue

        # Rule 2: Losing position with significant unrealized loss
        if unrealized < 0 and risk_at_stop > 0:
            loss_pct = abs(unrealized) / risk_at_stop
            if loss_pct > flatten_loss_thresh:
                actions.append({
                    "position_id": pos["position_id"],
                    "action":      "FLATTEN",
                    "reason":      f"Losing {loss_pct:.0%} of risk at stop; avoid overnight gap",
                })
            else:
                stop_dist = abs(entry - (stop or entry))
                new_stop  = (entry - stop_dist * (1 - stop_tighten_pct)
                             if side == "LONG"
                             else entry + stop_dist * (1 - stop_tighten_pct))
                actions.append({
                    "position_id": pos["position_id"],
                    "action":      "TIGHTEN_STOP",
                    "new_stop":    round(new_stop, 2),
                    "reason":      f"Minor loss ({loss_pct:.0%} of stop); tightening for overnight",
                })
            continue

        # Rule 3: Winning position
        if unrealized > 0 and tp and entry:
            tp_dist   = abs(tp - entry) * pv * contracts
            progress  = unrealized / tp_dist if tp_dist > 0 else 0.0
            if progress > partial_thresh:
                actions.append({
                    "position_id": pos["position_id"],
                    "action":      "PARTIAL_EXIT",
                    "exit_pct":    50,
                    "reason":      f"Profit at {progress:.0%} of target; locking 50%; move stop to b/e",
                })
            else:
                # Move stop to breakeven
                be_stop = entry + (0.01 if side == "LONG" else -0.01)
                curr_stop = stop or (entry - 50)
                if side == "LONG" and be_stop > curr_stop:
                    actions.append({
                        "position_id": pos["position_id"],
                        "action":      "MOVE_STOP_TO_BREAKEVEN",
                        "new_stop":    round(be_stop, 2),
                        "reason":      "In profit but < 50% of target; protecting entry",
                    })
                elif side == "SHORT" and be_stop < curr_stop:
                    actions.append({
                        "position_id": pos["position_id"],
                        "action":      "MOVE_STOP_TO_BREAKEVEN",
                        "new_stop":    round(be_stop, 2),
                        "reason":      "In profit but < 50% of target; protecting entry (short)",
                    })
                else:
                    actions.append({
                        "position_id": pos["position_id"],
                        "action":      "HOLD",
                        "reason":      "In profit; stop already above entry",
                    })
            continue

        # Rule 4: Flat / near breakeven
        actions.append({
            "position_id": pos["position_id"],
            "action":      "HOLD",
            "reason":      "Near breakeven; holding with current stop",
        })

    return actions


# ---------------------------------------------------------------------------
# Apply overnight actions to portfolio
# ---------------------------------------------------------------------------

def _apply_overnight_actions(portfolio: dict, actions: list[dict]) -> int:
    """Apply TIGHTEN_STOP and MOVE_STOP_TO_BREAKEVEN actions in-place."""
    applied = 0
    pos_map = {p["position_id"]: p for p in portfolio.get("positions", [])}
    for a in actions:
        pos = pos_map.get(a["position_id"])
        if pos is None:
            continue
        if a["action"] in ("TIGHTEN_STOP", "MOVE_STOP_TO_BREAKEVEN"):
            new_stop = a.get("new_stop")
            if new_stop is not None:
                pos["stop_price"] = new_stop
                applied += 1
    return applied


# ---------------------------------------------------------------------------
# Main EOD routine
# ---------------------------------------------------------------------------

def run_eod(dry_run: bool = False) -> dict:
    """
    Execute daily end-of-day routine.
    Returns result dict.
    """
    run_id    = IDs.make_run_id()
    now       = datetime.now(timezone.utc)
    date_str  = now.strftime("%Y-%m-%d")

    _log(f"Starting EOD routine (dry_run={dry_run})")

    portfolio     = store.load_portfolio()
    posture_state = store.load_posture_state()
    params        = store.load_params()
    snapshots     = get_all_snapshots()

    positions = portfolio.get("positions", [])
    equity    = portfolio["account"]["equity_usd"]
    pnl       = portfolio.get("pnl", {})

    # 1. Daily snapshot → ledger
    snapshot_payload = {
        "date":             date_str,
        "equity_usd":       equity,
        "peak_equity_usd":  portfolio["account"]["peak_equity_usd"],
        "realized_today":   pnl.get("realized_today_usd", 0.0),
        "unrealized":       pnl.get("unrealized_usd", 0.0),
        "total_today_usd":  pnl.get("total_today_usd", 0.0),
        "total_today_pct":  pnl.get("total_today_pct", 0.0),
        "portfolio_dd_pct": pnl.get("portfolio_dd_pct", 0.0),
        "open_positions":   len(positions),
        "posture":          posture_state.get("posture", C.Posture.NORMAL),
    }
    if not dry_run:
        ledger.append(C.EventType.DAILY_SNAPSHOT, run_id, f"EOD_{date_str}", snapshot_payload)
    _log(f"  Snapshot: equity=${equity:,.2f} PnL today={pnl.get('total_today_pct', 0):.2f}%")

    # 2. Overnight hold policy
    overnight_actions = evaluate_overnight_hold(positions, snapshots, params)
    _log(f"  Overnight actions: {len(overnight_actions)}")
    for a in overnight_actions:
        _log(f"    {a['position_id']}: {a['action']} — {a['reason']}")

    stops_adjusted = 0
    if not dry_run:
        stops_adjusted = _apply_overnight_actions(portfolio, overnight_actions)

    # 3. Increment bars_held
    for pos in positions:
        pos["bars_held"] = pos.get("bars_held", 0) + 1
    _log(f"  bars_held incremented on {len(positions)} positions")

    # 4. Update consecutive_positive_days
    today_pct = pnl.get("total_today_pct", 0.0)
    prev_consec = posture_state.get("consecutive_positive_days", 0)
    new_consec  = prev_consec + 1 if today_pct > 0 else 0
    posture_state["consecutive_positive_days"] = new_consec
    _log(f"  Consecutive positive days: {prev_consec} → {new_consec}")

    # 5. Reset daily PnL counters
    pnl["realized_today_usd"] = 0.0
    pnl["total_today_usd"]    = 0.0
    pnl["total_today_pct"]    = 0.0

    # 6. Persist
    if not dry_run:
        store.save_portfolio(portfolio)
        store.save_posture_state(posture_state)
        _log("  State persisted")
    else:
        _log("  DRY RUN — no state changes written")

    result = {
        "run_id":              run_id,
        "date":                date_str,
        "equity_usd":          equity,
        "positions_open":      len(positions),
        "overnight_actions":   len(overnight_actions),
        "stops_adjusted":      stops_adjusted,
        "consecutive_pos_days": new_consec,
        "dry_run":             dry_run,
    }
    _log(f"EOD complete: {result}")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="EOD routine for Futures Trading System")
    parser.add_argument("--dry-run", action="store_true", default=False,
                        help="Preview actions without persisting state")
    args = parser.parse_args()
    run_eod(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
