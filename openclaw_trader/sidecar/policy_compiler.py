from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .models import SessionPlaybook, TradingAgentsSignal


def _session_expiry(session_date: str) -> str:
    return f"{session_date}T20:00:00Z"


def _parse_utc_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _format_utc_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _baseline_generated_at(session_date: str) -> str:
    now = datetime.now(timezone.utc)
    expiry = _parse_utc_timestamp(_session_expiry(session_date))
    return _format_utc_timestamp(min(now, expiry))


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
            generated_at=_baseline_generated_at(session_date),
            expires_at=expires_at,
            symbol=symbol,
            disallowed_setups=(),
            blocked_windows_et=(),
            source_attribution=(
                {"source": "baseline", "field": "fallback"},
            ),
            fallback_reason="missing_signal",
        )

    stale_signal = signal.session_date != session_date or signal.symbol != symbol
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
        disallowed_setups=tuple(sorted(set(signal.disallowed_setups))),
        blocked_windows_et=signal.blocked_windows_et,
        source_attribution=_source_attribution("TradingAgents", "disallowed_setups"),
        fallback_reason=None,
    )
