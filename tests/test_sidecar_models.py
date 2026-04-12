from __future__ import annotations

import pytest

from openclaw_trader.sidecar.models import (
    SessionPlaybook,
    SidecarValidationError,
    TradingAgentsSignal,
)


def test_signal_rejects_reversed_time_window() -> None:
    with pytest.raises(SidecarValidationError):
        TradingAgentsSignal(
            session_date="2026-04-12",
            generated_at="2026-04-12T07:00:00Z",
            symbol="MNQ",
            blocked_windows_et=[{"start": "11:00", "end": "10:30"}],
            disallowed_setups=["ORB"],
            narrative="avoid noisy open",
            confidence=0.72,
            raw_payload={"source": "test"},
        )


def test_playbook_knows_when_it_is_active() -> None:
    playbook = SessionPlaybook(
        session_date="2026-04-12",
        generated_at="2026-04-12T07:05:00Z",
        expires_at="2026-04-12T20:00:00Z",
        symbol="MNQ",
        disallowed_setups=["ORB"],
        blocked_windows_et=[{"start": "09:30", "end": "09:45"}],
        source_attribution=[{"source": "baseline", "field": "disallowed_setups"}],
        fallback_reason=None,
    )

    assert playbook.is_active_for_session("2026-04-12") is True
    assert playbook.is_active_for_session("2026-04-13") is False
