#!/usr/bin/env python3
"""All data contracts, event types, and state constants.

Section references: 3.2 (IntentState), 3.4 (EventType), 5.x (schema helpers),
7.3 (RiskDecision), 7.4 (Posture), 8.3 (ExecStatus), 9.3 (WatchtowerStatus)
"""

from __future__ import annotations
from datetime import datetime, timezone
from typing import Any


# ---------------------------------------------------------------------------
# Event Types — spec 3.4
# ---------------------------------------------------------------------------
class EventType:
    SYSTEM_START            = "SYSTEM_START"
    SYSTEM_STOP             = "SYSTEM_STOP"
    RECONCILIATION          = "RECONCILIATION"
    REGIME_COMPUTED         = "REGIME_COMPUTED"
    HEALTH_COMPUTED         = "HEALTH_COMPUTED"
    INTENT_CREATED          = "INTENT_CREATED"
    INTENT_DENIED           = "INTENT_DENIED"
    INTENT_DEFERRED         = "INTENT_DEFERRED"
    APPROVAL_ISSUED         = "APPROVAL_ISSUED"
    ORDER_SENT              = "ORDER_SENT"
    ORDER_FILLED            = "ORDER_FILLED"
    ORDER_PARTIALLY_FILLED  = "ORDER_PARTIALLY_FILLED"
    ORDER_REJECTED          = "ORDER_REJECTED"
    ORDER_TIMED_OUT         = "ORDER_TIMED_OUT"
    ORDER_CANCELLED         = "ORDER_CANCELLED"
    BRACKET_CONFIRMED       = "BRACKET_CONFIRMED"
    POSITION_CLOSED         = "POSITION_CLOSED"
    DAILY_SNAPSHOT          = "DAILY_SNAPSHOT"
    POSTURE_CHANGE          = "POSTURE_CHANGE"
    ALERT                   = "ALERT"
    PARAMETER_CHANGE        = "PARAMETER_CHANGE"
    STRATEGY_STATUS_CHANGE  = "STRATEGY_STATUS_CHANGE"
    SESSION_CHANGE          = "SESSION_CHANGE"
    MISSED_OPPORTUNITY      = "MISSED_OPPORTUNITY"
    GAP_EVENT               = "GAP_EVENT"
    LEARNING_PROPOSAL       = "LEARNING_PROPOSAL"
    INTRADAY_REGIME         = "INTRADAY_REGIME"
    INTRADAY_SETUP_DETECTED = "INTRADAY_SETUP_DETECTED"
    INTRADAY_SETUP_SCORED   = "INTRADAY_SETUP_SCORED"
    POSITION_PARTIALLY_CLOSED = "POSITION_PARTIALLY_CLOSED"
    TRAILING_STOP_UPDATED     = "TRAILING_STOP_UPDATED"


# ---------------------------------------------------------------------------
# Intent Lifecycle States — spec 3.2
# ---------------------------------------------------------------------------
class IntentState:
    PROPOSED             = "PROPOSED"
    DENIED               = "DENIED"
    DEFERRED             = "DEFERRED"
    APPROVED             = "APPROVED"
    EXPIRED              = "EXPIRED"
    SENT                 = "SENT"
    FILLED               = "FILLED"
    PARTIALLY_FILLED     = "PARTIALLY_FILLED"
    CANCELLED_REMAINDER  = "CANCELLED_REMAINDER"
    REJECTED             = "REJECTED"
    TIMED_OUT            = "TIMED_OUT"
    COMPLETE             = "COMPLETE"

    TERMINAL: frozenset[str] = frozenset({
        DENIED, EXPIRED, CANCELLED_REMAINDER, REJECTED, TIMED_OUT, COMPLETE
    })

    @classmethod
    def is_terminal(cls, state: str) -> bool:
        return state in cls.TERMINAL

    NON_TERMINAL: frozenset[str] = frozenset({
        PROPOSED, DEFERRED, APPROVED, SENT, FILLED, PARTIALLY_FILLED
    })


# ---------------------------------------------------------------------------
# Execution Status — spec 5.8
# ---------------------------------------------------------------------------
class ExecStatus:
    PENDING              = "PENDING"
    SENT                 = "SENT"
    PARTIALLY_FILLED     = "PARTIALLY_FILLED"
    FILLED               = "FILLED"
    COMPLETE             = "COMPLETE"
    REJECTED             = "REJECTED"
    TIMED_OUT            = "TIMED_OUT"
    CANCELLED            = "CANCELLED"
    FAILED               = "FAILED"
    EMERGENCY_FLATTENED  = "EMERGENCY_FLATTENED"

    TERMINAL: frozenset[str] = frozenset({
        COMPLETE, REJECTED, TIMED_OUT, CANCELLED, FAILED, EMERGENCY_FLATTENED
    })

    @classmethod
    def is_terminal(cls, status: str) -> bool:
        return status in cls.TERMINAL


# ---------------------------------------------------------------------------
# Sentinel Posture — spec 7.4
# ---------------------------------------------------------------------------
class Posture:
    NORMAL    = "NORMAL"
    CAUTION   = "CAUTION"
    DEFENSIVE = "DEFENSIVE"
    HALT      = "HALT"

    ORDER: tuple[str, ...] = (NORMAL, CAUTION, DEFENSIVE, HALT)

    @staticmethod
    def escalate(current: str, target: str) -> str:
        """Return the higher (more conservative) of current and target."""
        order = Posture.ORDER
        ci = order.index(current) if current in order else len(order) - 1
        ti = order.index(target) if target in order else len(order) - 1
        return order[max(ci, ti)]

    @staticmethod
    def is_at_least(posture: str, level: str) -> bool:
        """True if posture is >= level (more restrictive)."""
        order = Posture.ORDER
        pi = order.index(posture) if posture in order else len(order) - 1
        li = order.index(level) if level in order else len(order) - 1
        return pi >= li


# ---------------------------------------------------------------------------
# Strategy Status — spec 6.7 / 6.8
# ---------------------------------------------------------------------------
class StrategyStatus:
    ACTIVE     = "ACTIVE"
    COOLDOWN   = "COOLDOWN"
    DISABLED   = "DISABLED"
    INCUBATING = "INCUBATING"


# ---------------------------------------------------------------------------
# Health Action — spec 6.6
# ---------------------------------------------------------------------------
class HealthAction:
    NORMAL    = "NORMAL"
    HALF_SIZE = "HALF_SIZE"
    DISABLE   = "DISABLE"


# ---------------------------------------------------------------------------
# Watchtower Status — spec 9.3
# ---------------------------------------------------------------------------
class WatchtowerStatus:
    HEALTHY  = "HEALTHY"
    DEGRADED = "DEGRADED"
    HALT     = "HALT"


# ---------------------------------------------------------------------------
# Session States — spec 11.1
# ---------------------------------------------------------------------------
class SessionState:
    CORE       = "CORE"
    POST_CLOSE = "POST_CLOSE"
    CLOSED     = "CLOSED"
    EXTENDED   = "EXTENDED"
    PRE_OPEN   = "PRE_OPEN"

    # Intraday sessions (granular)
    PREMARKET     = "PREMARKET"
    US_OPEN       = "US_OPEN"
    MORNING_DRIVE = "MORNING_DRIVE"
    MIDDAY        = "MIDDAY"
    AFTERNOON     = "AFTERNOON"
    MOC_CLOSE     = "MOC_CLOSE"


# ---------------------------------------------------------------------------
# Risk Decision types — spec 5.7
# ---------------------------------------------------------------------------
class RiskDecision:
    APPROVE         = "APPROVE"
    APPROVE_REDUCED = "APPROVE_REDUCED"
    DENY            = "DENY"
    DEFER           = "DEFER"


# ---------------------------------------------------------------------------
# Intent Types — spec 5.6
# ---------------------------------------------------------------------------
class IntentType:
    ENTRY    = "ENTRY"
    EXIT     = "EXIT"
    SCALE_IN = "SCALE_IN"
    SCALE_OUT = "SCALE_OUT"
    ROLL     = "ROLL"
    HEDGE    = "HEDGE"
    FLATTEN  = "FLATTEN"

    # Types that always bypass regime/health gates in Sentinel
    RELAXED: frozenset[str] = frozenset({EXIT, SCALE_OUT, FLATTEN})


# ---------------------------------------------------------------------------
# Data schema builder helpers
# ---------------------------------------------------------------------------
def _utcnow_ms() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def make_ledger_entry(
    event_type: str,
    run_id: str,
    ref_id: str,
    payload: dict[str, Any],
    ledger_seq: int = 0,
) -> dict[str, Any]:
    """Construct a ledger entry dict; checksum is filled in by ledger.append()."""
    return {
        "ledger_seq": ledger_seq,
        "timestamp":  _utcnow_ms(),
        "event_type": event_type,
        "run_id":     run_id,
        "ref_id":     ref_id,
        "payload":    payload,
        "checksum":   None,
    }


def make_regime_report(
    report_id: str,
    run_id: str,
    asof: str,
    param_version: str,
    regime_score: float,
    confidence: float,
    effective_regime_score: float,
    risk_multiplier: float,
    drivers: dict[str, Any],
    mode_hint: str,
) -> dict[str, Any]:
    return {
        "report_id":              report_id,
        "run_id":                 run_id,
        "asof":                   asof,
        "param_version":          param_version,
        "regime_score":           round(regime_score, 4),
        "confidence":             round(confidence, 4),
        "effective_regime_score": round(effective_regime_score, 4),
        "risk_multiplier":        round(risk_multiplier, 4),
        "drivers":                drivers,
        "mode_hint":              mode_hint,
    }


def make_health_report(
    strategy_id: str,
    asof: str,
    param_version: str,
    health_score: float,
    health_score_capped: bool,
    action: str,
    components: dict[str, Any],
    stats: dict[str, Any],
    bars_since_last_disable: int | None = None,
    incubation_trades_remaining: int | None = None,
) -> dict[str, Any]:
    return {
        "strategy_id":                  strategy_id,
        "asof":                         asof,
        "param_version":                param_version,
        "health_score":                 round(health_score, 4),
        "health_score_capped":          health_score_capped,
        "action":                       action,
        "components":                   components,
        "stats":                        stats,
        "bars_since_last_disable":      bars_since_last_disable,
        "incubation_trades_remaining":  incubation_trades_remaining,
    }
