#!/usr/bin/env python3
"""Posture state machine — spec Section 7.4.

NORMAL → CAUTION → DEFENSIVE → HALT (escalation)
HALT → DEFENSIVE → CAUTION → NORMAL (recovery, with cooldowns)

Escalation triggers: daily loss %, portfolio DD %.
Recovery: cooldown hours/days + positive PnL.
"""

from __future__ import annotations
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))
from shared import contracts as C
from shared import ledger
from shared import state_store as store


def _parse_ts(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _hours_since(ts: str | None) -> float:
    t = _parse_ts(ts)
    if not t:
        return 0.0
    return (datetime.now(timezone.utc) - t).total_seconds() / 3600.0


def _days_since(ts: str | None) -> float:
    return _hours_since(ts) / 24.0


def compute_posture(
    portfolio: dict,
    param_version: str = "PV_0001",
    cycle_interval_hours: float = 0.25,
    run_id: str = "",
) -> tuple[str, dict]:
    """
    Compute and persist the next posture state.
    Returns (new_posture, state_dict).
    Escalation is immediate; recovery requires cooldown + positive conditions.
    """
    params = store.load_params(param_version)
    sp = params.get("sentinel", {})
    state = store.load_posture_state()
    current = state.get("posture", C.Posture.NORMAL)
    posture_since = state.get("posture_since")
    consec_pos = state.get("consecutive_positive_days", 0)
    caution_hours = state.get("caution_hours_clean", 0.0)
    defensive_days = state.get("defensive_days_clean", 0.0)
    last_halt = state.get("last_halt_at")
    recovery_pending = state.get("recovery_pending", False)

    pnl = portfolio.get("pnl", {})
    daily_pct = pnl.get("total_today_pct", 0.0)
    dd_pct = pnl.get("portfolio_dd_pct", 0.0)

    # Thresholds (stored as negative, e.g. -1.0 for -1%)
    daily_caution = sp.get("daily_loss_caution_pct", -1.0)
    daily_defensive = sp.get("daily_loss_defensive_pct", -1.5)
    daily_halt = sp.get("daily_loss_halt_pct", -3.0)
    dd_caution = sp.get("dd_caution_pct", 5.0)
    dd_defensive = sp.get("dd_defensive_pct", 10.0)
    dd_halt = sp.get("dd_halt_pct", 15.0)
    cooldown_caution_hours = sp.get("recovery_cooldown_caution_to_normal_hours", 4)
    cooldown_defensive_days = sp.get("recovery_cooldown_defensive_to_caution_days", 2)

    now = datetime.now(timezone.utc).isoformat()
    target_escalate: str | None = None

    # --- Escalation (immediate) ---
    if daily_pct <= daily_halt or dd_pct >= dd_halt:
        target_escalate = C.Posture.HALT
    elif daily_pct <= daily_defensive or dd_pct >= dd_defensive:
        target_escalate = C.Posture.DEFENSIVE
    elif daily_pct <= daily_caution or dd_pct >= dd_caution:
        target_escalate = C.Posture.CAUTION

    if target_escalate:
        new_posture = C.Posture.escalate(current, target_escalate)
        if new_posture != current:
            state["posture"] = new_posture
            state["posture_since"] = now
            state["caution_hours_clean"] = 0.0
            state["defensive_days_clean"] = 0.0
            if new_posture == C.Posture.HALT:
                state["last_halt_at"] = now
            store.save_posture_state(state)
            ledger.append(C.EventType.POSTURE_CHANGE, run_id, "POSTURE", {
                "from_posture": current,
                "to_posture": new_posture,
                "reason": f"Escalation: daily_pct={daily_pct:.2f}% dd_pct={dd_pct:.2f}%",
            })
            return new_posture, state

    # --- Recovery (cooldown + positive) ---
    positive_today = daily_pct >= 0
    can_recover = positive_today or consec_pos > 0

    if current == C.Posture.HALT:
        # HALT recovery requires manual operator action
        return current, state

    if current == C.Posture.DEFENSIVE and can_recover:
        defensive_days += cycle_interval_hours / 24.0
        state["defensive_days_clean"] = defensive_days
        if defensive_days >= cooldown_defensive_days:
            new_posture = C.Posture.CAUTION
            state["posture"] = new_posture
            state["posture_since"] = now
            state["defensive_days_clean"] = 0.0
            store.save_posture_state(state)
            ledger.append(C.EventType.POSTURE_CHANGE, run_id, "POSTURE", {
                "from_posture": current,
                "to_posture": new_posture,
                "reason": f"Recovery: {defensive_days:.1f} days clean, positive PnL",
            })
            return new_posture, state
        store.save_posture_state(state)
        return current, state

    if current == C.Posture.CAUTION and can_recover:
        caution_hours += cycle_interval_hours
        state["caution_hours_clean"] = caution_hours
        if caution_hours >= cooldown_caution_hours:
            new_posture = C.Posture.NORMAL
            state["posture"] = new_posture
            state["posture_since"] = now
            state["caution_hours_clean"] = 0.0
            store.save_posture_state(state)
            ledger.append(C.EventType.POSTURE_CHANGE, run_id, "POSTURE", {
                "from_posture": current,
                "to_posture": new_posture,
                "reason": f"Recovery: {caution_hours:.1f}h clean, positive PnL",
            })
            return new_posture, state
        store.save_posture_state(state)
        return current, state

    return current, state


def update_posture(
    portfolio: dict,
    param_version: str = "PV_0001",
    run_id: str = "",
) -> str:
    """
    Convenience: compute posture and return the current posture string.
    Called at start of each full cycle.
    """
    posture, _ = compute_posture(portfolio, param_version, 0.25, run_id)
    return posture
