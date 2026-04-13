from __future__ import annotations

import sys
from pathlib import Path
from datetime import datetime as real_datetime, timezone

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from openclaw_trader.sidecar.models import SessionPlaybook, TradingAgentsSignal
from openclaw_trader.sidecar.policy_compiler import compile_session_playbook


class _FixedDatetime(real_datetime):
    @classmethod
    def now(cls, tz=None):  # type: ignore[override]
        return real_datetime(2026, 4, 12, 8, 15, 0, tzinfo=timezone.utc)


def test_compile_session_playbook_uses_signal_restrictions() -> None:
    signal = TradingAgentsSignal(
        session_date="2026-04-12",
        generated_at="2026-04-12T07:00:00Z",
        symbol="MNQ",
        blocked_windows_et=[
            {"start": "09:30", "end": "09:45"},
            {"start": "13:55", "end": "14:20"},
        ],
        disallowed_setups=["VWAP", "ORB", "ORB"],
        narrative="avoid early volatility and late macro risk",
        confidence=0.83,
        raw_payload={"source": "TradingAgents"},
    )

    playbook = compile_session_playbook(
        session_date="2026-04-12",
        symbol="MNQ",
        signal=signal,
    )

    assert isinstance(playbook, SessionPlaybook)
    assert playbook.session_date == "2026-04-12"
    assert playbook.symbol == "MNQ"
    assert playbook.generated_at == "2026-04-12T07:00:00Z"
    assert playbook.expires_at == "2026-04-12T20:00:00Z"
    assert playbook.disallowed_setups == ("ORB", "VWAP")
    assert playbook.blocked_windows_et == (
        {"start": "09:30", "end": "09:45"},
        {"start": "13:55", "end": "14:20"},
    )
    assert playbook.source_attribution == (
        {"source": "TradingAgents", "field": "disallowed_setups"},
    )
    assert playbook.fallback_reason is None


def test_compile_session_playbook_falls_back_when_signal_is_missing(monkeypatch) -> None:
    from openclaw_trader.sidecar import policy_compiler

    monkeypatch.setattr(policy_compiler, "datetime", _FixedDatetime)

    playbook = compile_session_playbook(
        session_date="2026-04-12",
        symbol="MNQ",
        signal=None,
    )

    assert playbook.session_date == "2026-04-12"
    assert playbook.symbol == "MNQ"
    assert playbook.generated_at == "2026-04-12T08:15:00Z"
    assert playbook.disallowed_setups == ()
    assert playbook.blocked_windows_et == ()
    assert playbook.source_attribution == (
        {"source": "baseline", "field": "fallback"},
    )
    assert playbook.fallback_reason == "missing_signal"


def test_compile_session_playbook_falls_back_when_signal_is_stale() -> None:
    signal = TradingAgentsSignal(
        session_date="2026-04-11",
        generated_at="2026-04-11T07:00:00Z",
        symbol="MNQ",
        blocked_windows_et=[{"start": "09:30", "end": "09:45"}],
        disallowed_setups=["ORB"],
        narrative="prior-session signal",
        confidence=0.5,
        raw_payload={"source": "TradingAgents"},
    )

    playbook = compile_session_playbook(
        session_date="2026-04-12",
        symbol="MNQ",
        signal=signal,
    )

    assert playbook.session_date == "2026-04-12"
    assert playbook.symbol == "MNQ"
    assert playbook.generated_at == "2026-04-11T07:00:00Z"
    assert playbook.disallowed_setups == ()
    assert playbook.blocked_windows_et == ()
    assert playbook.source_attribution == (
        {"source": "TradingAgents", "field": "disallowed_setups"},
    )
    assert playbook.fallback_reason == "stale_signal"
