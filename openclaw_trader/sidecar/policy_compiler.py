from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .models import SessionPlaybook, TradingAgentsSignal


def _session_expiry(session_date: str) -> str:
    return f"{session_date}T20:00:00Z"


def _current_utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _source_attribution(source: str, field: str) -> tuple[dict[str, Any], ...]:
    entry: dict[str, Any] = {"source": source, "field": field}
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
            generated_at=_current_utc_timestamp(),
            expires_at=expires_at,
            symbol=symbol,
            disallowed_setups=(),
            blocked_windows_et=(),
            source_attribution=(
                {"source": "baseline", "field": "fallback"},
            ),
            fallback_reason="missing_signal",
        )

    stale_signal = signal.session_date != session_date
    if stale_signal:
        return SessionPlaybook(
            session_date=session_date,
            generated_at=signal.generated_at,
            expires_at=expires_at,
            symbol=symbol,
            disallowed_setups=(),
            blocked_windows_et=(),
            source_attribution=_source_attribution("TradingAgents", "disallowed_setups"),
            fallback_reason="stale_signal",
        )

    return SessionPlaybook(
        session_date=session_date,
        generated_at=signal.generated_at,
        expires_at=expires_at,
        symbol=symbol,
        disallowed_setups=signal.disallowed_setups,
        blocked_windows_et=signal.blocked_windows_et,
        source_attribution=_source_attribution("TradingAgents", "disallowed_setups"),
        fallback_reason=None,
    )
