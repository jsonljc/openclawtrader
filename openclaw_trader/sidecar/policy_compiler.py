from __future__ import annotations

from typing import Any

from .models import SessionPlaybook, TradingAgentsSignal


def _session_start_timestamp(session_date: str) -> str:
    return f"{session_date}T00:00:00Z"


def _session_expiry(session_date: str) -> str:
    return f"{session_date}T20:00:00Z"


def _source_attribution(source: str, field: str, reason: str | None = None) -> tuple[dict[str, Any], ...]:
    entry: dict[str, Any] = {"source": source, "field": field}
    if reason is not None:
        entry["reason"] = reason
    return (entry,)


def compile_session_playbook(
    session_date: str,
    symbol: str,
    signal: TradingAgentsSignal | None,
) -> SessionPlaybook:
    expires_at = _session_expiry(session_date)

    if signal is None:
        return SessionPlaybook(
            session_date=session_date,
            generated_at=_session_start_timestamp(session_date),
            expires_at=expires_at,
            symbol=symbol,
            disallowed_setups=(),
            blocked_windows_et=(),
            source_attribution=_source_attribution("baseline", "fallback", "missing_signal"),
            fallback_reason="missing_signal",
        )

    stale_signal = signal.session_date != session_date
    if stale_signal:
        return SessionPlaybook(
            session_date=session_date,
            generated_at=_session_start_timestamp(session_date),
            expires_at=expires_at,
            symbol=symbol,
            disallowed_setups=(),
            blocked_windows_et=(),
            source_attribution=_source_attribution("baseline", "fallback", "stale_signal"),
            fallback_reason="stale_signal",
        )

    return SessionPlaybook(
        session_date=session_date,
        generated_at=signal.generated_at,
        expires_at=expires_at,
        symbol=symbol,
        disallowed_setups=signal.disallowed_setups,
        blocked_windows_et=signal.blocked_windows_et,
        source_attribution=(
            *_source_attribution("TradingAgents", "disallowed_setups"),
            *_source_attribution("TradingAgents", "blocked_windows_et"),
        ),
        fallback_reason=None,
    )
