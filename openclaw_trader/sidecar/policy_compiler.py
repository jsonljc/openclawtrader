from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any

try:
    from zoneinfo import ZoneInfo

    ET = ZoneInfo("America/New_York")
except ImportError:
    ET = timezone(timedelta(hours=-5))

from .models import SessionPlaybook, TradingAgentsSignal


def _session_expiry(session_date: str) -> str:
    session_day = date.fromisoformat(session_date)
    closing_bell_et = datetime.combine(session_day, time(hour=16), tzinfo=ET)
    return _format_utc_timestamp(closing_bell_et)


def _parse_utc_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _format_utc_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _baseline_generated_at(session_date: str) -> str:
    now = datetime.now(timezone.utc)
    expiry = _parse_utc_timestamp(_session_expiry(session_date))
    return _format_utc_timestamp(min(now, expiry))


def _stale_generated_at(session_date: str, generated_at: str) -> str:
    expiry = _parse_utc_timestamp(_session_expiry(session_date))
    return _format_utc_timestamp(min(_parse_utc_timestamp(generated_at), expiry))


def _bounded_generated_at(session_date: str, generated_at: str) -> str:
    return _stale_generated_at(session_date, generated_at)


def _source_attribution(source: str, field: str) -> tuple[dict[str, Any], ...]:
    entry: dict[str, Any] = {"source": source, "field": field}
    return (entry,)


def _signal_source_attribution(signal: TradingAgentsSignal) -> tuple[dict[str, Any], ...]:
    attributions: list[dict[str, Any]] = []
    if signal.disallowed_setups:
        attributions.append({"source": "TradingAgents", "field": "disallowed_setups"})
    if signal.blocked_windows_et:
        attributions.append({"source": "TradingAgents", "field": "blocked_windows_et"})
    return tuple(attributions)


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
            generated_at=_stale_generated_at(session_date, signal.generated_at),
            expires_at=expires_at,
            symbol=symbol,
            disallowed_setups=(),
            blocked_windows_et=(),
            source_attribution=_source_attribution("TradingAgents", "disallowed_setups"),
            fallback_reason="stale_signal",
        )

    return SessionPlaybook(
        session_date=session_date,
        generated_at=_bounded_generated_at(session_date, signal.generated_at),
        expires_at=expires_at,
        symbol=symbol,
        disallowed_setups=tuple(sorted(set(signal.disallowed_setups))),
        blocked_windows_et=signal.blocked_windows_et,
        source_attribution=_signal_source_attribution(signal),
        fallback_reason=None,
    )
