from __future__ import annotations

import pytest

from openclaw_trader.sidecar.models import (
    BlockedWindow,
    SessionPlaybook,
    SidecarValidationError,
    TradingAgentsSignal,
)
from openclaw_trader.sidecar import storage


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


def test_blocked_window_rejects_invalid_time_values() -> None:
    with pytest.raises(SidecarValidationError):
        BlockedWindow(start="25:00", end="26:00")


def test_signal_rejects_naive_timestamp() -> None:
    with pytest.raises(SidecarValidationError):
        TradingAgentsSignal(
            session_date="2026-04-12",
            generated_at="2026-04-12T07:00:00",
            symbol="MNQ",
            blocked_windows_et=[],
            disallowed_setups=[],
            narrative="",
            confidence=0.5,
            raw_payload={},
        )


def test_signal_rejects_boolean_confidence() -> None:
    with pytest.raises(SidecarValidationError, match="confidence"):
        TradingAgentsSignal(
            session_date="2026-04-12",
            generated_at="2026-04-12T07:00:00Z",
            symbol="MNQ",
            blocked_windows_et=[],
            disallowed_setups=[],
            narrative="avoid noisy open",
            confidence=True,
            raw_payload={},
        )


@pytest.mark.parametrize(
    ("kwargs", "field_name"),
    [
        (
            {
                "session_date": 20260412,
                "generated_at": "2026-04-12T07:00:00Z",
                "symbol": "MNQ",
                "blocked_windows_et": [],
                "disallowed_setups": [],
                "narrative": "avoid noisy open",
                "confidence": 0.5,
                "raw_payload": {},
            },
            "session_date",
        ),
        (
            {
                "session_date": "2026-04-12",
                "generated_at": "2026-04-12T07:00:00Z",
                "symbol": 123,
                "blocked_windows_et": [],
                "disallowed_setups": [],
                "narrative": "avoid noisy open",
                "confidence": 0.5,
                "raw_payload": {},
            },
            "symbol",
        ),
        (
            {
                "session_date": "2026-04-12",
                "generated_at": "2026-04-12T07:00:00Z",
                "symbol": "MNQ",
                "blocked_windows_et": [],
                "disallowed_setups": [],
                "narrative": 456,
                "confidence": 0.5,
                "raw_payload": {},
            },
            "narrative",
        ),
    ],
)
def test_signal_rejects_invalid_scalar_values(kwargs: dict[str, object], field_name: str) -> None:
    with pytest.raises(SidecarValidationError, match=field_name):
        TradingAgentsSignal(**kwargs)


def test_signal_freezes_inputs_and_serializes_cleanly() -> None:
    blocked_windows = [{"start": "09:30", "end": "09:45"}]
    disallowed_setups = ["ORB"]
    raw_payload = {"source": "test"}

    signal = TradingAgentsSignal(
        session_date="2026-04-12",
        generated_at="2026-04-12T07:00:00Z",
        symbol="MNQ",
        blocked_windows_et=blocked_windows,
        disallowed_setups=disallowed_setups,
        narrative="avoid noisy open",
        confidence=0.72,
        raw_payload=raw_payload,
    )

    blocked_windows[0]["start"] = "10:00"
    disallowed_setups.append("VWAP")
    raw_payload["source"] = "changed"

    assert signal.blocked_windows_et[0]["start"] == "09:30"
    assert signal.disallowed_setups == ("ORB",)
    assert signal.raw_payload["source"] == "test"
    assert signal.to_dict() == {
        "session_date": "2026-04-12",
        "generated_at": "2026-04-12T07:00:00Z",
        "symbol": "MNQ",
        "blocked_windows_et": [{"start": "09:30", "end": "09:45"}],
        "disallowed_setups": ["ORB"],
        "narrative": "avoid noisy open",
        "confidence": 0.72,
        "raw_payload": {"source": "test"},
    }

    with pytest.raises(AttributeError):
        signal.blocked_windows_et.append({"start": "10:00", "end": "10:15"})

    with pytest.raises(TypeError):
        signal.raw_payload["source"] = "changed"


def test_write_json_normalizes_frozen_model_payloads(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(storage, "_DATA_DIR", tmp_path)

    signal = TradingAgentsSignal(
        session_date="2026-04-12",
        generated_at="2026-04-12T07:00:00Z",
        symbol="MNQ",
        blocked_windows_et=[{"start": "09:30", "end": "09:45"}],
        disallowed_setups=["ORB"],
        narrative="avoid noisy open",
        confidence=0.72,
        raw_payload={"source": "test", "meta": {"tags": ["alpha", "beta"]}},
    )

    storage.write_json("signal.json", signal.__dict__)

    assert storage.read_json("signal.json") == signal.to_dict()


def test_nested_inputs_are_deep_frozen() -> None:
    raw_payload = {
        "source": "test",
        "meta": {"tags": ["alpha", "beta"]},
    }
    source_attribution = [
        {
            "source": "baseline",
            "field": "disallowed_setups",
            "details": {"groups": ["orb", "trend"]},
        }
    ]

    signal = TradingAgentsSignal(
        session_date="2026-04-12",
        generated_at="2026-04-12T07:00:00Z",
        symbol="MNQ",
        blocked_windows_et=[],
        disallowed_setups=[],
        narrative="",
        confidence=0.5,
        raw_payload=raw_payload,
    )
    playbook = SessionPlaybook(
        session_date="2026-04-12",
        generated_at="2026-04-12T07:05:00Z",
        expires_at="2026-04-12T20:00:00Z",
        symbol="MNQ",
        disallowed_setups=["ORB"],
        blocked_windows_et=[],
        source_attribution=source_attribution,
        fallback_reason=None,
    )

    raw_payload["meta"]["tags"].append("gamma")
    source_attribution[0]["details"]["groups"].append("vwap")

    assert signal.raw_payload["meta"]["tags"] == ("alpha", "beta")
    assert playbook.source_attribution[0]["details"]["groups"] == ("orb", "trend")
    assert signal.to_dict() == {
        "session_date": "2026-04-12",
        "generated_at": "2026-04-12T07:00:00Z",
        "symbol": "MNQ",
        "blocked_windows_et": [],
        "disallowed_setups": [],
        "narrative": "",
        "confidence": 0.5,
        "raw_payload": {"source": "test", "meta": {"tags": ["alpha", "beta"]}},
    }
    assert playbook.to_dict() == {
        "session_date": "2026-04-12",
        "generated_at": "2026-04-12T07:05:00Z",
        "expires_at": "2026-04-12T20:00:00Z",
        "symbol": "MNQ",
        "disallowed_setups": ["ORB"],
        "blocked_windows_et": [],
        "source_attribution": [
            {
                "source": "baseline",
                "field": "disallowed_setups",
                "details": {"groups": ["orb", "trend"]},
            }
        ],
        "fallback_reason": None,
    }


def test_playbook_rejects_expiry_before_generation() -> None:
    with pytest.raises(SidecarValidationError):
        SessionPlaybook(
            session_date="2026-04-12",
            generated_at="2026-04-12T07:05:00Z",
            expires_at="2026-04-12T07:00:00Z",
            symbol="MNQ",
            disallowed_setups=["ORB"],
            blocked_windows_et=[{"start": "09:30", "end": "09:45"}],
            source_attribution=[],
            fallback_reason=None,
        )


@pytest.mark.parametrize(
    ("kwargs", "field_name"),
    [
        (
            {
                "session_date": 20260412,
                "generated_at": "2026-04-12T07:05:00Z",
                "expires_at": "2026-04-12T20:00:00Z",
                "symbol": "MNQ",
                "disallowed_setups": ["ORB"],
                "blocked_windows_et": [],
                "source_attribution": [],
                "fallback_reason": None,
            },
            "session_date",
        ),
        (
            {
                "session_date": "2026-04-12",
                "generated_at": "2026-04-12T07:05:00Z",
                "expires_at": "2026-04-12T20:00:00Z",
                "symbol": ["MNQ"],
                "disallowed_setups": ["ORB"],
                "blocked_windows_et": [],
                "source_attribution": [],
                "fallback_reason": None,
            },
            "symbol",
        ),
        (
            {
                "session_date": "2026-04-12",
                "generated_at": "2026-04-12T07:05:00Z",
                "expires_at": "2026-04-12T20:00:00Z",
                "symbol": "MNQ",
                "disallowed_setups": ["ORB"],
                "blocked_windows_et": [],
                "source_attribution": [],
                "fallback_reason": 789,
            },
            "fallback_reason",
        ),
    ],
)
def test_playbook_rejects_invalid_scalar_values(kwargs: dict[str, object], field_name: str) -> None:
    with pytest.raises(SidecarValidationError, match=field_name):
        SessionPlaybook(**kwargs)


def test_playbook_freezes_inputs_and_serializes_cleanly() -> None:
    blocked_windows = [{"start": "09:30", "end": "09:45"}]
    disallowed_setups = ["ORB"]
    source_attribution = [{"source": "baseline", "field": "disallowed_setups"}]

    playbook = SessionPlaybook(
        session_date="2026-04-12",
        generated_at="2026-04-12T07:05:00Z",
        expires_at="2026-04-12T20:00:00Z",
        symbol="MNQ",
        disallowed_setups=disallowed_setups,
        blocked_windows_et=blocked_windows,
        source_attribution=source_attribution,
        fallback_reason=None,
    )

    blocked_windows[0]["start"] = "10:00"
    disallowed_setups.append("VWAP")
    source_attribution[0]["source"] = "changed"

    assert playbook.disallowed_setups == ("ORB",)
    assert playbook.blocked_windows_et[0]["start"] == "09:30"
    assert playbook.source_attribution[0]["source"] == "baseline"
    assert playbook.to_dict() == {
        "session_date": "2026-04-12",
        "generated_at": "2026-04-12T07:05:00Z",
        "expires_at": "2026-04-12T20:00:00Z",
        "symbol": "MNQ",
        "disallowed_setups": ["ORB"],
        "blocked_windows_et": [{"start": "09:30", "end": "09:45"}],
        "source_attribution": [
            {"source": "baseline", "field": "disallowed_setups"},
        ],
        "fallback_reason": None,
    }

    with pytest.raises(AttributeError):
        playbook.disallowed_setups.append("VWAP")

    with pytest.raises(AttributeError):
        playbook.blocked_windows_et.append({"start": "10:00", "end": "10:15"})

    with pytest.raises(TypeError):
        playbook.source_attribution[0]["source"] = "changed"


def test_playbook_rejects_invalid_datetimes_and_windows() -> None:
    with pytest.raises(SidecarValidationError):
        SessionPlaybook(
            session_date="2026-04-12",
            generated_at="not-a-datetime",
            expires_at="2026-04-12T20:00:00Z",
            symbol="MNQ",
            disallowed_setups=["ORB"],
            blocked_windows_et=[{"start": "09:30", "end": "09:45"}],
            source_attribution=[],
            fallback_reason=None,
        )

    with pytest.raises(SidecarValidationError):
        SessionPlaybook(
            session_date="2026-04-12",
            generated_at="2026-04-12T07:05:00Z",
            expires_at="2026-04-12T20:00:00Z",
            symbol="MNQ",
            disallowed_setups=["ORB"],
            blocked_windows_et=[{"start": "11:00", "end": "10:30"}],
            source_attribution=[],
            fallback_reason=None,
        )
