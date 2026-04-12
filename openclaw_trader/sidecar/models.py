from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


class SidecarValidationError(ValueError):
    pass


@dataclass(frozen=True)
class BlockedWindow:
    start: str
    end: str

    def __post_init__(self) -> None:
        if self.start >= self.end:
            raise SidecarValidationError(f"blocked window must increase: {self.start} -> {self.end}")


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
        datetime.fromisoformat(self.generated_at.replace("Z", "+00:00"))
        for window in self.blocked_windows_et:
            BlockedWindow(**window)
        if not 0.0 <= self.confidence <= 1.0:
            raise SidecarValidationError("confidence must be between 0 and 1")


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

    def is_active_for_session(self, session_date: str) -> bool:
        return self.session_date == session_date
