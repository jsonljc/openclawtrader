from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time
from typing import Any


class SidecarValidationError(ValueError):
    pass


def _parse_iso_datetime(value: str, field_name: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError) as exc:
        raise SidecarValidationError(f"invalid {field_name}: {value!r}") from exc


def _parse_et_time(value: str, field_name: str) -> time:
    try:
        return datetime.strptime(value, "%H:%M").time()
    except (TypeError, ValueError) as exc:
        raise SidecarValidationError(f"invalid {field_name}: {value!r}") from exc


@dataclass(frozen=True)
class BlockedWindow:
    start: str
    end: str

    def __post_init__(self) -> None:
        start = _parse_et_time(self.start, "blocked window start")
        end = _parse_et_time(self.end, "blocked window end")
        if start >= end:
            raise SidecarValidationError(
                f"blocked window must increase: {self.start} -> {self.end}"
            )


@dataclass(frozen=True)
class TradingAgentsSignal:
    session_date: str
    generated_at: str
    symbol: str
    blocked_windows_et: list[dict[str, str]] = field(default_factory=list)
    disallowed_setups: list[str] = field(default_factory=list)
    narrative: str = ""
    confidence: float = 0.0
    raw_payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        try:
            _parse_iso_datetime(self.generated_at, "generated_at")
            for window in self.blocked_windows_et:
                BlockedWindow(**window)
            if not 0.0 <= self.confidence <= 1.0:
                raise SidecarValidationError("confidence must be between 0 and 1")
        except SidecarValidationError:
            raise
        except (TypeError, ValueError) as exc:
            raise SidecarValidationError("invalid trading agents signal") from exc


@dataclass(frozen=True)
class SessionPlaybook:
    session_date: str
    generated_at: str
    expires_at: str
    symbol: str
    disallowed_setups: list[str] = field(default_factory=list)
    blocked_windows_et: list[dict[str, str]] = field(default_factory=list)
    source_attribution: list[dict[str, str]] = field(default_factory=list)
    fallback_reason: str | None = None

    def __post_init__(self) -> None:
        try:
            _parse_iso_datetime(self.generated_at, "generated_at")
            _parse_iso_datetime(self.expires_at, "expires_at")
            for window in self.blocked_windows_et:
                BlockedWindow(**window)
        except SidecarValidationError:
            raise
        except (TypeError, ValueError) as exc:
            raise SidecarValidationError("invalid session playbook") from exc

    def is_active_for_session(self, session_date: str) -> bool:
        return self.session_date == session_date
