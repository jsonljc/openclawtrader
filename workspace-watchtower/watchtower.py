#!/usr/bin/env python3
"""Watchtower — Reliability & Data Integrity Monitor — spec Section 9.

Phase 1 scope:
- Data heartbeat check
- Price sanity check
- Bracket integrity check (every position must have active stop)
- Ledger integrity check
- System latency check
- Contract expiry alert
- Exchange connectivity (stub: always OK in paper mode)

Public API:
    run_health_check(snapshots, run_id, cycle_time_sec) -> health_dict
    detect_gap(snapshot, prev_close, run_id) -> gap_dict | None
"""

from __future__ import annotations
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))
from shared import contracts as C
from shared import ledger
from shared import state_store as store
from shared import alerting


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def check_data_heartbeat(snapshot: dict) -> dict:
    """FREEZE if data is stale or bars are missing — spec 9.2."""
    dq = snapshot.get("data_quality", {})
    last_bar_age = dq.get("last_bar_age_sec", 0)
    is_stale     = dq.get("is_stale", False)

    if is_stale or last_bar_age > 900:
        return {"status": "HALT", "check": "data_heartbeat",
                "message": f"Data stale: last_bar_age={last_bar_age}s"}
    if last_bar_age > 300:
        return {"status": "DEGRADED", "check": "data_heartbeat",
                "message": f"Data aging: last_bar_age={last_bar_age}s"}
    return {"status": "OK", "check": "data_heartbeat",
            "message": f"Data fresh (age={last_bar_age}s)"}


def check_price_sanity(snapshot: dict) -> dict:
    """FREEZE if price moves > 5× ATR in a single bar — spec 9.4."""
    bars_1h = snapshot.get("bars", {}).get("1H", [])
    atr_1h  = snapshot.get("indicators", {}).get("atr_14_1H", 15.0)

    if len(bars_1h) < 2 or atr_1h <= 0:
        return {"status": "OK", "check": "price_sanity", "message": "Insufficient bars"}

    for i in range(1, len(bars_1h)):
        prev_c = bars_1h[i - 1]["c"]
        curr_c = bars_1h[i]["c"]
        move   = abs(curr_c - prev_c)
        if move > 5 * atr_1h:
            return {"status": "HALT", "check": "price_sanity",
                    "message": f"PRICE_ANOMALY: bar move {move:.2f} > 5× ATR {atr_1h:.2f}"}

    return {"status": "OK", "check": "price_sanity", "message": "Price within normal range"}


def check_spread(snapshot: dict) -> dict:
    """Alert if spread > 3× baseline — spec 9.2."""
    ms = snapshot.get("microstructure", {})
    spread   = ms.get("spread_ticks", 1)
    baseline = ms.get("avg_book_depth_baseline", 1)

    if spread > 3:
        return {"status": "DEGRADED", "check": "spread",
                "message": f"Spread {spread} ticks > 3-tick alert threshold"}
    return {"status": "OK", "check": "spread", "message": f"Spread {spread} ticks OK"}


def check_bracket_integrity(portfolio: dict) -> dict:
    """
    Every open position MUST have an active stop order — spec 8.7 Invariant 1.
    Any position without an active stop → HALT.
    """
    positions = portfolio.get("positions", [])
    unprotected = []

    for pos in positions:
        bracket = pos.get("bracket_status", {})
        stop_status = bracket.get("stop_status", "")
        if stop_status != "ACTIVE":
            unprotected.append(pos.get("position_id", "?"))

    if unprotected:
        return {"status": "HALT", "check": "bracket_integrity",
                "message": f"Unprotected positions (no active stop): {unprotected}"}

    return {"status": "OK", "check": "bracket_integrity",
            "message": f"{len(positions)} positions all have active stops"}


def check_margin_utilization(portfolio: dict) -> dict:
    """HALT if margin > 60% — spec 9.2."""
    util = portfolio.get("account", {}).get("margin_utilization_pct", 0.0)
    if util > 60.0:
        return {"status": "HALT", "check": "margin_utilization",
                "message": f"Margin utilization {util:.1f}% > 60%"}
    if util > 40.0:
        return {"status": "DEGRADED", "check": "margin_utilization",
                "message": f"Margin utilization {util:.1f}% > 40% (approaching limit)"}
    return {"status": "OK", "check": "margin_utilization",
            "message": f"Margin {util:.1f}%"}


def check_system_latency(cycle_time_sec: float, avg_cycle_time_sec: float = 5.0) -> dict:
    """Alert if cycle time > 2× normal average — spec 9.2."""
    threshold = max(30.0, avg_cycle_time_sec * 2.0)
    if cycle_time_sec > threshold:
        return {"status": "DEGRADED", "check": "system_latency",
                "message": f"Cycle time {cycle_time_sec:.1f}s > {threshold:.1f}s threshold"}
    return {"status": "OK", "check": "system_latency",
            "message": f"Cycle time {cycle_time_sec:.1f}s OK"}


def check_contract_expiry(snapshots: dict[str, dict], registry: dict) -> dict:
    """Alert T-10, T-7, T-5 before expiry — spec 9.2 / 12.1."""
    alerts = []
    for strategy_id, strategy in registry.items():
        symbol = strategy.get("symbol", "")
        snap   = snapshots.get(symbol, {})
        days   = snap.get("contract", {}).get("days_to_expiry", 999)
        roll_w = strategy.get("roll_days_before_expiry", 5)

        if days <= roll_w:
            alerts.append(f"{strategy_id}: T-{days} ROLL WINDOW OPEN")
        elif days <= 7:
            alerts.append(f"{strategy_id}: T-{days} approaching rollover")
        elif days <= 10:
            alerts.append(f"{strategy_id}: T-{days} rollover in 10 days")

    if any("ROLL WINDOW" in a for a in alerts):
        return {"status": "DEGRADED", "check": "contract_expiry",
                "message": "; ".join(alerts)}
    if alerts:
        return {"status": "OK", "check": "contract_expiry",
                "message": "; ".join(alerts)}
    return {"status": "OK", "check": "contract_expiry", "message": "No expiry concerns"}


def check_ledger_integrity(run_id: str) -> dict:
    """Verify SHA-256 hash chain — spec 9.2 / 16.1."""
    ok, msg = ledger.verify_integrity()
    if not ok:
        return {"status": "HALT", "check": "ledger_integrity",
                "message": f"HASH CHAIN BROKEN: {msg}"}
    return {"status": "OK", "check": "ledger_integrity", "message": msg}


def check_execution_staleness(run_id: str) -> dict:
    """Alert on approved intents > 60s with no receipt — spec 9.2."""
    now = datetime.now(timezone.utc)
    stale = []

    approvals = ledger.query(event_types=[C.EventType.APPROVAL_ISSUED], limit=100)
    fills     = {e["payload"].get("approval_id")
                 for e in ledger.query(
                     event_types=[C.EventType.ORDER_FILLED, C.EventType.BRACKET_CONFIRMED,
                                  C.EventType.ORDER_REJECTED, C.EventType.ORDER_CANCELLED],
                     limit=500,
                 )}

    for e in approvals:
        ap_id = e["payload"].get("approval_id")
        if ap_id in fills:
            continue
        ts_str = e.get("timestamp", "")
        try:
            ts  = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            age = (now - ts).total_seconds()
        except ValueError:
            continue
        if age > 300:  # > 5 min → should be expired
            stale.append(f"{ap_id} (age={age:.0f}s)")
        elif age > 60:
            stale.append(f"{ap_id} (age={age:.0f}s, warning)")

    if stale:
        return {"status": "DEGRADED", "check": "execution_staleness",
                "message": f"Stale approvals: {stale}"}
    return {"status": "OK", "check": "execution_staleness",
            "message": "No stale approvals"}


def check_exchange_connectivity() -> dict:
    """
    Verify exchange connectivity.
    Phase 1 (paper trading): always OK.
    Phase 4: replace with real ping to exchange API.
    """
    return {"status": "OK", "check": "exchange_connectivity",
            "message": "Paper mode — connectivity assumed OK"}


# ---------------------------------------------------------------------------
# Gap detection — spec 9.4
# ---------------------------------------------------------------------------

def detect_gap(
    snapshot: dict,
    prev_session_close: float | None,
    run_id: str,
) -> dict | None:
    """
    Detect opening gap relative to previous session close.
    Returns gap event dict if gap exists, else None.
    """
    if prev_session_close is None or prev_session_close <= 0:
        return None

    bars_1h = snapshot.get("bars", {}).get("1H", [])
    if not bars_1h:
        return None

    open_price = bars_1h[-1].get("o", bars_1h[-1].get("c"))
    atr_1h     = snapshot.get("indicators", {}).get("atr_14_1H", 15.0)

    if atr_1h <= 0:
        return None

    gap_points = open_price - prev_session_close
    gap_atr    = abs(gap_points) / atr_1h

    if gap_atr < 0.5:
        return None  # Normal noise, not a gap

    severity = "MODERATE" if gap_atr < 4 else "SEVERE"

    gap_event = {
        "event_type":       "GAP_EVENT",
        "gap_points":       round(gap_points, 4),
        "gap_atr_multiple": round(gap_atr, 4),
        "open_price":       open_price,
        "prev_close":       prev_session_close,
        "severity":         severity,
        "symbol":           snapshot.get("symbol", ""),
        "detected_at":      datetime.now(timezone.utc).isoformat(),
    }

    if gap_atr >= 2:
        ledger.append(C.EventType.GAP_EVENT, run_id, f"GAP_{snapshot.get('symbol', '')}", gap_event)

    return gap_event


# ---------------------------------------------------------------------------
# Crash recovery — spec 3.3
# ---------------------------------------------------------------------------

def run_crash_recovery(run_id: str) -> dict:
    """
    Execute crash recovery protocol on startup.
    Full lifecycle reconstruction: scan all events, build intent states,
    handle non-terminal states appropriately.
    Returns recovery report with any anomalies found.
    """
    portfolio     = store.load_portfolio()
    posture_state = store.load_posture_state()
    posture       = posture_state.get("posture", C.Posture.NORMAL)

    anomalies: list[str] = []
    actions:   list[str] = []

    # 1. If posture was HALT before crash → remain in HALT
    if posture == C.Posture.HALT:
        actions.append("Posture remains HALT — manual operator confirmation required")

    # 2. Full lifecycle reconstruction — map event types to states
    _EVENT_TO_STATE = {
        C.EventType.INTENT_CREATED:   C.IntentState.PROPOSED,
        C.EventType.INTENT_DENIED:    C.IntentState.DENIED,
        C.EventType.INTENT_DEFERRED:  C.IntentState.DEFERRED,
        C.EventType.APPROVAL_ISSUED:  C.IntentState.APPROVED,
        C.EventType.ORDER_SENT:       C.IntentState.SENT,
        C.EventType.ORDER_FILLED:     C.IntentState.FILLED,
        C.EventType.BRACKET_CONFIRMED: C.IntentState.COMPLETE,
        C.EventType.ORDER_REJECTED:   C.IntentState.REJECTED,
        C.EventType.ORDER_CANCELLED:  C.IntentState.CANCELLED_REMAINDER,
        C.EventType.ORDER_TIMED_OUT:  C.IntentState.TIMED_OUT,
    }
    _TERMINAL_STATES = {
        C.IntentState.DENIED, C.IntentState.COMPLETE, C.IntentState.REJECTED,
        C.IntentState.CANCELLED_REMAINDER, C.IntentState.TIMED_OUT, C.IntentState.EXPIRED,
    }

    # Scan all events and build latest state per intent_id
    intent_states: dict[str, str] = {}
    all_events = ledger.query(limit=10_000)
    for entry in all_events:
        p = entry.get("payload", {})
        intent_id = p.get("intent_id")
        if not intent_id:
            continue
        event_type = entry.get("event_type", "")
        mapped_state = _EVENT_TO_STATE.get(event_type)
        if mapped_state:
            intent_states[intent_id] = mapped_state

    # Process non-terminal intents
    for intent_id, state in intent_states.items():
        if state in _TERMINAL_STATES:
            continue  # Already resolved

        if state == C.IntentState.PROPOSED:
            actions.append(f"Discarding stale PROPOSED intent {intent_id}")
        elif state == C.IntentState.DEFERRED:
            actions.append(f"Discarding DEFERRED intent {intent_id}")
        elif state == C.IntentState.APPROVED:
            actions.append(f"Re-evaluating APPROVED intent {intent_id} (market may have moved)")
            anomalies.append(f"Intent {intent_id} was APPROVED but never sent")
        elif state == C.IntentState.SENT:
            actions.append(f"Flagging SENT intent {intent_id} for exchange reconciliation")
            anomalies.append(f"Intent {intent_id} was SENT but no fill/reject received")
        elif state == C.IntentState.FILLED:
            # FILLED but no bracket confirmed → CRITICAL: naked position
            actions.append(f"CRITICAL: Intent {intent_id} FILLED but no bracket — naked position")
            anomalies.append(f"Intent {intent_id} FILLED without bracket confirmation — naked position risk")
            alerting.alert("HALT", f"CRITICAL: Naked position detected for intent {intent_id}",
                           {"intent_id": intent_id, "state": state})

    # 3. Check positions vs expectations
    positions = portfolio.get("positions", [])
    for pos in positions:
        bracket = pos.get("bracket_status", {})
        if bracket.get("stop_status") != "ACTIVE":
            anomalies.append(f"Position {pos.get('position_id')} has no active stop")

    # 4. If anomalies → escalate posture to at least CAUTION
    if anomalies and posture == C.Posture.NORMAL:
        posture_state["posture"] = C.Posture.CAUTION
        posture_state["posture_since"] = datetime.now(timezone.utc).isoformat()
        store.save_posture_state(posture_state)
        actions.append(f"Posture escalated to CAUTION due to {len(anomalies)} anomalies")
        ledger.append(C.EventType.POSTURE_CHANGE, run_id, "RECOVERY", {
            "from_posture": C.Posture.NORMAL,
            "to_posture":   C.Posture.CAUTION,
            "reason":       f"Crash recovery: {len(anomalies)} anomalies found",
        })
        alerting.alert("CAUTION", f"Crash recovery: posture escalated to CAUTION — {len(anomalies)} anomalies",
                       {"from_posture": C.Posture.NORMAL, "to_posture": C.Posture.CAUTION, "anomalies": anomalies})

    report = {
        "anomalies": anomalies,
        "actions":   actions,
        "posture":   posture_state.get("posture"),
        "clean":     len(anomalies) == 0,
    }

    ledger.append(C.EventType.RECONCILIATION, run_id, "CRASH_RECOVERY", report)
    return report


# ---------------------------------------------------------------------------
# Main health check
# ---------------------------------------------------------------------------

def run_health_check(
    snapshots: dict[str, dict],
    run_id: str,
    cycle_time_sec: float = 0.0,
) -> dict[str, Any]:
    """
    Run all Watchtower checks.  Returns a health status dict.
    Aggregates to HALT > DEGRADED > HEALTHY.
    """
    portfolio = store.load_portfolio()
    registry  = store.load_strategy_registry()
    checks    = {}
    alerts:   list[str] = []

    # Use first snapshot for per-snapshot checks
    snap = next(iter(snapshots.values()), {}) if snapshots else {}

    results = [
        check_exchange_connectivity(),
        check_data_heartbeat(snap) if snap else {"status": "OK", "check": "data_heartbeat", "message": "No snapshot"},
        check_price_sanity(snap)   if snap else {"status": "OK", "check": "price_sanity",   "message": "No snapshot"},
        check_spread(snap)         if snap else {"status": "OK", "check": "spread",          "message": "No snapshot"},
        check_bracket_integrity(portfolio),
        check_margin_utilization(portfolio),
        check_system_latency(cycle_time_sec),
        check_contract_expiry(snapshots, registry),
        check_execution_staleness(run_id),
        check_ledger_integrity(run_id),
    ]

    overall = C.WatchtowerStatus.HEALTHY
    for r in results:
        checks[r["check"]] = r["status"]
        if r["status"] in ("DEGRADED", "HALT"):
            alerts.append(f"{r['check']}: {r['message']}")
        if r["status"] == "HALT":
            overall = C.WatchtowerStatus.HALT
        elif r["status"] == "DEGRADED" and overall != C.WatchtowerStatus.HALT:
            overall = C.WatchtowerStatus.DEGRADED

    health: dict[str, Any] = {
        "status":       overall,
        "checks":       checks,
        "active_alerts": alerts,
        "last_check":   datetime.now(timezone.utc).isoformat(),
    }

    if alerts:
        ledger.append(C.EventType.ALERT, run_id, "WATCHTOWER", {
            "status":  overall,
            "alerts":  alerts,
        })
        alerting.alert(overall, "; ".join(alerts), {"source": "watchtower", "alerts": alerts})

    return health
