from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, time
from types import MappingProxyType
from typing import Any


class SidecarValidationError(ValueError):
    pass


def _parse_iso_datetime(value: str, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError) as exc:
        raise SidecarValidationError(f"invalid {field_name}: {value!r}") from exc

    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SidecarValidationError(f"invalid {field_name}: {value!r}")

    return parsed


def _parse_et_time(value: str, field_name: str) -> time:
    try:
        return datetime.strptime(value, "%H:%M").time()
    except (TypeError, ValueError) as exc:
        raise SidecarValidationError(f"invalid {field_name}: {value!r}") from exc


def _deep_freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _deep_freeze(inner) for key, inner in value.items()})
    if isinstance(value, list):
        return tuple(_deep_freeze(inner) for inner in value)
    if isinstance(value, tuple):
        return tuple(_deep_freeze(inner) for inner in value)
    if isinstance(value, set):
        return tuple(_deep_freeze(inner) for inner in value)
    return value


def _deep_thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _deep_thaw(inner) for key, inner in value.items()}
    if isinstance(value, tuple):
        return [_deep_thaw(inner) for inner in value]
    return value


def _freeze_mapping(value: Mapping[str, Any], field_name: str) -> Mapping[str, Any]:
    try:
        return MappingProxyType({key: _deep_freeze(inner) for key, inner in dict(value).items()})
    except (TypeError, ValueError) as exc:
        raise SidecarValidationError(f"invalid {field_name}: {value!r}") from exc


def _freeze_str_tuple(values: Any, field_name: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise SidecarValidationError(f"invalid {field_name}: {values!r}")

    try:
        normalized = tuple(values)
    except TypeError as exc:
        raise SidecarValidationError(f"invalid {field_name}: {values!r}") from exc

    if any(not isinstance(item, str) for item in normalized):
        raise SidecarValidationError(f"invalid {field_name}: {values!r}")

    return normalized


def _freeze_window(value: Any) -> Mapping[str, Any]:
    if isinstance(value, BlockedWindow):
        normalized = value.to_dict()
    else:
        try:
            normalized = dict(value)
        except (TypeError, ValueError) as exc:
            raise SidecarValidationError(f"invalid blocked window: {value!r}") from exc

    validated = BlockedWindow(**normalized)
    return MappingProxyType(_deep_freeze(validated.to_dict()))


def _freeze_window_tuple(values: Any) -> tuple[Mapping[str, Any], ...]:
    if isinstance(values, (str, bytes)):
        raise SidecarValidationError(f"invalid blocked windows: {values!r}")

    try:
        return tuple(_freeze_window(value) for value in values)
    except TypeError as exc:
        raise SidecarValidationError(f"invalid blocked windows: {values!r}") from exc


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

    def to_dict(self) -> dict[str, str]:
        return {"start": self.start, "end": self.end}


@dataclass(frozen=True)
class TradingAgentsSignal:
    session_date: str
    generated_at: str
    symbol: str
    blocked_windows_et: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)
    disallowed_setups: tuple[str, ...] = field(default_factory=tuple)
    narrative: str = ""
    confidence: float = 0.0
    raw_payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        try:
            _parse_iso_datetime(self.generated_at, "generated_at")
            object.__setattr__(self, "blocked_windows_et", _freeze_window_tuple(self.blocked_windows_et))
            object.__setattr__(self, "disallowed_setups", _freeze_str_tuple(self.disallowed_setups, "disallowed_setups"))
            object.__setattr__(self, "raw_payload", _freeze_mapping(self.raw_payload, "raw_payload"))
            if not 0.0 <= self.confidence <= 1.0:
                raise SidecarValidationError("confidence must be between 0 and 1")
        except SidecarValidationError:
            raise
        except (TypeError, ValueError) as exc:
            raise SidecarValidationError("invalid trading agents signal") from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_date": self.session_date,
            "generated_at": self.generated_at,
            "symbol": self.symbol,
            "blocked_windows_et": [_deep_thaw(window) for window in self.blocked_windows_et],
            "disallowed_setups": list(self.disallowed_setups),
            "narrative": self.narrative,
            "confidence": self.confidence,
            "raw_payload": _deep_thaw(self.raw_payload),
        }


@dataclass(frozen=True)
class SessionPlaybook:
    session_date: str
    generated_at: str
    expires_at: str
    symbol: str
    disallowed_setups: tuple[str, ...] = field(default_factory=tuple)
    blocked_windows_et: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)
    source_attribution: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)
    fallback_reason: str | None = None

    def __post_init__(self) -> None:
        try:
            generated_at = _parse_iso_datetime(self.generated_at, "generated_at")
            expires_at = _parse_iso_datetime(self.expires_at, "expires_at")
            if expires_at < generated_at:
                raise SidecarValidationError("expires_at must not be earlier than generated_at")
            object.__setattr__(self, "disallowed_setups", _freeze_str_tuple(self.disallowed_setups, "disallowed_setups"))
            object.__setattr__(self, "blocked_windows_et", _freeze_window_tuple(self.blocked_windows_et))
            object.__setattr__(self, "source_attribution", tuple(_freeze_mapping(item, "source_attribution") for item in self.source_attribution))
        except SidecarValidationError:
            raise
        except (TypeError, ValueError) as exc:
            raise SidecarValidationError("invalid session playbook") from exc

    def is_active_for_session(self, session_date: str) -> bool:
        return self.session_date == session_date

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_date": self.session_date,
            "generated_at": self.generated_at,
            "expires_at": self.expires_at,
            "symbol": self.symbol,
            "disallowed_setups": list(self.disallowed_setups),
            "blocked_windows_et": [_deep_thaw(window) for window in self.blocked_windows_et],
            "source_attribution": [_deep_thaw(item) for item in self.source_attribution],
            "fallback_reason": self.fallback_reason,
        }
