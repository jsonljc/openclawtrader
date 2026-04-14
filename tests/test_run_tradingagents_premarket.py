from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import run_tradingagents_premarket as runner
from openclaw_trader.sidecar.models import SessionPlaybook, TradingAgentsSignal


class _FixedDatetime(datetime):
    @classmethod
    def now(cls, tz=None):  # type: ignore[override]
        return datetime(2026, 4, 13, 11, 15, 0, tzinfo=timezone.utc)


def test_run_tradingagents_premarket_builds_payload_and_persists(monkeypatch, capsys) -> None:
    captured: dict[str, object] = {}
    writes: dict[str, object] = {}
    journal: dict[str, object] = {}
    appended: dict[str, object] = {}

    monkeypatch.setattr(runner, "datetime", _FixedDatetime)
    monkeypatch.setattr(
        runner,
        "get_calendar",
        lambda: SimpleNamespace(
            upcoming_events=lambda now_utc, hours_ahead: [
                {
                    "name": "CPI",
                    "time_utc": "2026-04-13T13:30:00Z",
                    "tier": 1,
                    "minutes_until": 135.0,
                }
            ]
        ),
    )
    monkeypatch.setattr(
        runner,
        "ledger",
        SimpleNamespace(
            query=lambda **kwargs: [
                {"event_type": "ORDER_FILLED", "ref_id": "T1", "payload": {"symbol": "MNQ"}}
            ],
            append=lambda *args, **kwargs: appended.setdefault("call", {"args": args, "kwargs": kwargs}),
        ),
    )
    monkeypatch.setattr(
        runner,
        "load_strategy_registry",
        lambda: {
            "orb_5m_MNQ": {
                "strategy_id": "orb_5m_MNQ",
                "symbol": "MNQ",
                "status": "ACTIVE",
            },
            "vwap_5m_ES": {
                "strategy_id": "vwap_5m_ES",
                "symbol": "ES",
                "status": "ACTIVE",
            },
            "disabled": {
                "strategy_id": "disabled",
                "symbol": "MNQ",
                "status": "DISABLED",
            },
        },
    )
    monkeypatch.setattr(
        runner,
        "run_tradingagents",
        lambda command, payload: (
            captured.setdefault("command", command),
            captured.setdefault("payload", payload),
            TradingAgentsSignal(
                session_date="2026-04-13",
                generated_at="2026-04-13T11:16:00Z",
                symbol="MNQ",
                blocked_windows_et=[{"start": "09:30", "end": "09:45"}],
                disallowed_setups=["ORB", "VWAP"],
                narrative="avoid noisy open",
                confidence=0.88,
                raw_payload={"command": command, "payload": payload},
            ),
        )[2],
    )
    monkeypatch.setattr(
        runner,
        "compile_session_playbook",
        lambda session_date, symbol, signal: SessionPlaybook(
            session_date=session_date,
            generated_at=signal.generated_at,
            expires_at="2026-04-13T20:00:00Z",
            symbol=symbol,
            disallowed_setups=signal.disallowed_setups,
            blocked_windows_et=signal.blocked_windows_et,
            source_attribution=[
                {"source": "TradingAgents", "field": "disallowed_setups"},
                {"source": "TradingAgents", "field": "blocked_windows_et"},
            ],
            fallback_reason=None,
        ),
    )
    monkeypatch.setattr(runner, "write_json", lambda name, payload: writes.setdefault(name, payload))
    monkeypatch.setattr(
        runner,
        "append_journal_entry",
        lambda kind, payload: journal.setdefault("call", {"kind": kind, "payload": payload}),
    )

    result = runner.run_tradingagents_premarket(
        session_date="2026-04-13",
        symbol="MNQ",
        command=["tradingagents", "premarket"],
    )

    assert captured["payload"] == {
        "session_date": "2026-04-13",
        "symbol": "MNQ",
        "upcoming_events": [
            {
                "name": "CPI",
                "time_utc": "2026-04-13T13:30:00Z",
                "tier": 1,
                "minutes_until": 135.0,
            }
        ],
        "recent_trades": [
            {"event_type": "ORDER_FILLED", "ref_id": "T1", "payload": {"symbol": "MNQ"}}
        ],
        "active_strategies": [
            {
                "strategy_id": "orb_5m_MNQ",
                "symbol": "MNQ",
                "status": "ACTIVE",
            }
        ],
    }
    assert writes["tradingagents_signal_MNQ.json"] == {
        "session_date": "2026-04-13",
        "generated_at": "2026-04-13T11:16:00Z",
        "symbol": "MNQ",
        "blocked_windows_et": [{"start": "09:30", "end": "09:45"}],
        "disallowed_setups": ["ORB", "VWAP"],
        "narrative": "avoid noisy open",
        "confidence": 0.88,
        "raw_payload": {
            "command": ["tradingagents", "premarket"],
            "payload": captured["payload"],
        },
    }
    assert writes["session_playbook_MNQ.json"] == {
        "session_date": "2026-04-13",
        "generated_at": "2026-04-13T11:16:00Z",
        "expires_at": "2026-04-13T20:00:00Z",
        "symbol": "MNQ",
        "disallowed_setups": ["ORB", "VWAP"],
        "blocked_windows_et": [{"start": "09:30", "end": "09:45"}],
        "source_attribution": [
            {"source": "TradingAgents", "field": "disallowed_setups"},
            {"source": "TradingAgents", "field": "blocked_windows_et"},
        ],
        "fallback_reason": None,
    }
    assert appended["call"]["args"][0] == "SESSION_PLAYBOOK_PUBLISHED"
    assert journal["call"] == {
        "kind": "tradingagents_premarket",
        "payload": {
            "session_date": "2026-04-13",
            "symbol": "MNQ",
            "summary": "playbook ready: 2 setup bans, 1 blocked windows",
            "signal": writes["tradingagents_signal_MNQ.json"],
            "playbook": writes["session_playbook_MNQ.json"],
        },
    }
    assert result["summary"] == "playbook ready: 2 setup bans, 1 blocked windows"
    assert "playbook ready: 2 setup bans, 1 blocked windows" in capsys.readouterr().out


def test_build_runner_summary_includes_baseline_fallback() -> None:
    summary = runner.build_runner_summary(
        {
            "disallowed_setups": ["ORB"],
            "blocked_windows_et": [{"start": "09:30", "end": "09:45"}],
            "fallback_reason": "missing_signal",
        }
    )

    assert summary == "playbook ready: 1 setup bans, 1 blocked windows (baseline fallback: missing_signal)"


def test_run_tradingagents_premarket_continues_when_journaling_fails(monkeypatch, capsys) -> None:
    writes: dict[str, object] = {}
    appended: dict[str, object] = {}

    monkeypatch.setattr(runner, "datetime", _FixedDatetime)
    monkeypatch.setattr(
        runner,
        "get_calendar",
        lambda: SimpleNamespace(upcoming_events=lambda now_utc, hours_ahead: []),
    )
    monkeypatch.setattr(
        runner,
        "ledger",
        SimpleNamespace(
            query=lambda **kwargs: [],
            append=lambda *args, **kwargs: appended.setdefault("call", {"args": args, "kwargs": kwargs}),
        ),
    )
    monkeypatch.setattr(
        runner,
        "load_strategy_registry",
        lambda: {
            "orb_5m_MNQ": {
                "strategy_id": "orb_5m_MNQ",
                "symbol": "MNQ",
                "status": "ACTIVE",
            }
        },
    )
    monkeypatch.setattr(
        runner,
        "run_tradingagents",
        lambda command, payload: TradingAgentsSignal(
            session_date="2026-04-13",
            generated_at="2026-04-13T11:16:00Z",
            symbol="MNQ",
            blocked_windows_et=[],
            disallowed_setups=["ORB"],
            narrative="baseline signal",
            confidence=0.5,
            raw_payload={"command": command, "payload": payload},
        ),
    )
    monkeypatch.setattr(
        runner,
        "compile_session_playbook",
        lambda session_date, symbol, signal: SessionPlaybook(
            session_date=session_date,
            generated_at=signal.generated_at,
            expires_at="2026-04-13T20:00:00Z",
            symbol=symbol,
            disallowed_setups=signal.disallowed_setups,
            blocked_windows_et=signal.blocked_windows_et,
            source_attribution=[
                {"source": "TradingAgents", "field": "disallowed_setups"},
                {"source": "TradingAgents", "field": "blocked_windows_et"},
            ],
            fallback_reason=None,
        ),
    )
    monkeypatch.setattr(runner, "write_json", lambda name, payload: writes.setdefault(name, payload))
    monkeypatch.setattr(
        runner,
        "append_journal_entry",
        lambda kind, payload: (_ for _ in ()).throw(RuntimeError("hermes offline")),
    )

    result = runner.run_tradingagents_premarket(
        session_date="2026-04-13",
        symbol="MNQ",
        command=["tradingagents", "premarket"],
    )

    assert result["summary"] == "playbook ready: 1 setup bans, 0 blocked windows"
    assert appended["call"]["args"][0] == "SESSION_PLAYBOOK_PUBLISHED"
    assert "playbook ready: 1 setup bans, 0 blocked windows" in capsys.readouterr().out


def test_run_tradingagents_premarket_falls_back_to_baseline_when_tradingagents_fails(
    monkeypatch, capsys
) -> None:
    writes: dict[str, object] = {}
    appended: dict[str, object] = {}
    compiled: dict[str, object] = {}

    monkeypatch.setattr(runner, "datetime", _FixedDatetime)
    monkeypatch.setattr(
        runner,
        "get_calendar",
        lambda: SimpleNamespace(upcoming_events=lambda now_utc, hours_ahead: []),
    )
    monkeypatch.setattr(
        runner,
        "ledger",
        SimpleNamespace(
            query=lambda **kwargs: [],
            append=lambda *args, **kwargs: appended.setdefault("call", {"args": args, "kwargs": kwargs}),
        ),
    )
    monkeypatch.setattr(runner, "load_strategy_registry", lambda: {})
    monkeypatch.setattr(
        runner,
        "run_tradingagents",
        lambda command, payload: (_ for _ in ()).throw(RuntimeError("adapter failed")),
    )
    monkeypatch.setattr(runner, "read_json", lambda name: None)

    def _compile(session_date, symbol, signal):
        compiled["call"] = {
            "session_date": session_date,
            "symbol": symbol,
            "signal": signal,
        }
        return SessionPlaybook(
            session_date=session_date,
            generated_at="2026-04-13T11:15:00Z",
            expires_at="2026-04-13T20:00:00Z",
            symbol=symbol,
            disallowed_setups=(),
            blocked_windows_et=(),
            source_attribution=[{"source": "baseline", "field": "fallback"}],
            fallback_reason="missing_signal",
        )

    monkeypatch.setattr(runner, "compile_session_playbook", _compile)
    monkeypatch.setattr(runner, "write_json", lambda name, payload: writes.setdefault(name, payload))
    monkeypatch.setattr(
        runner,
        "append_journal_entry",
        lambda kind, payload: None,
    )

    result = runner.run_tradingagents_premarket(
        session_date="2026-04-13",
        symbol="MNQ",
        command=["tradingagents", "premarket"],
    )

    assert compiled["call"] == {
        "session_date": "2026-04-13",
        "symbol": "MNQ",
        "signal": None,
    }
    assert "tradingagents_signal_MNQ.json" not in writes
    assert writes["session_playbook_MNQ.json"] == {
        "session_date": "2026-04-13",
        "generated_at": "2026-04-13T11:15:00Z",
        "expires_at": "2026-04-13T20:00:00Z",
        "symbol": "MNQ",
        "disallowed_setups": [],
        "blocked_windows_et": [],
        "source_attribution": [{"source": "baseline", "field": "fallback"}],
        "fallback_reason": "missing_signal",
    }
    assert result["summary"] == "playbook ready: 0 setup bans, 0 blocked windows (baseline fallback: missing_signal)"
    assert result["signal"] is None
    assert result["playbook"] == writes["session_playbook_MNQ.json"]
    assert appended["call"]["args"][0] == "SESSION_PLAYBOOK_PUBLISHED"
    assert appended["call"]["args"][3]["signal"] is None
    assert appended["call"]["args"][3]["playbook"] == writes["session_playbook_MNQ.json"]
    assert "playbook ready: 0 setup bans, 0 blocked windows (baseline fallback: missing_signal)" in capsys.readouterr().out


def test_run_tradingagents_premarket_retains_active_playbook_when_tradingagents_fails(
    monkeypatch, capsys
) -> None:
    writes: dict[str, object] = {}
    appended: dict[str, object] = {}

    monkeypatch.setattr(runner, "datetime", _FixedDatetime)
    monkeypatch.setattr(
        runner,
        "get_calendar",
        lambda: SimpleNamespace(upcoming_events=lambda now_utc, hours_ahead: []),
    )
    monkeypatch.setattr(
        runner,
        "ledger",
        SimpleNamespace(
            query=lambda **kwargs: [],
            append=lambda *args, **kwargs: appended.setdefault("call", {"args": args, "kwargs": kwargs}),
        ),
    )
    monkeypatch.setattr(runner, "load_strategy_registry", lambda: {})
    monkeypatch.setattr(
        runner,
        "run_tradingagents",
        lambda command, payload: (_ for _ in ()).throw(RuntimeError("adapter failed")),
    )
    monkeypatch.setattr(
        runner,
        "read_json",
        lambda name: {
            "session_date": "2026-04-13",
            "generated_at": "2026-04-13T10:45:00Z",
            "expires_at": "2026-04-13T20:00:00Z",
            "symbol": "MNQ",
            "disallowed_setups": ["ORB"],
            "blocked_windows_et": [{"start": "09:30", "end": "09:45"}],
            "source_attribution": [
                {"source": "TradingAgents", "field": "disallowed_setups"},
                {"source": "TradingAgents", "field": "blocked_windows_et"},
            ],
            "fallback_reason": None,
        },
    )
    monkeypatch.setattr(
        runner,
        "compile_session_playbook",
        lambda session_date, symbol, signal: (_ for _ in ()).throw(
            AssertionError("baseline fallback should not compile when retained playbook is still valid")
        ),
    )
    monkeypatch.setattr(runner, "write_json", lambda name, payload: writes.setdefault(name, payload))
    monkeypatch.setattr(runner, "append_journal_entry", lambda kind, payload: None)

    result = runner.run_tradingagents_premarket(
        session_date="2026-04-13",
        symbol="MNQ",
        command=["tradingagents", "premarket"],
    )

    assert "tradingagents_signal_MNQ.json" not in writes
    assert writes["session_playbook_MNQ.json"] == {
        "session_date": "2026-04-13",
        "generated_at": "2026-04-13T10:45:00Z",
        "expires_at": "2026-04-13T20:00:00Z",
        "symbol": "MNQ",
        "disallowed_setups": ["ORB"],
        "blocked_windows_et": [{"start": "09:30", "end": "09:45"}],
        "source_attribution": [
            {"source": "TradingAgents", "field": "disallowed_setups"},
            {"source": "TradingAgents", "field": "blocked_windows_et"},
        ],
        "fallback_reason": None,
    }
    assert result["summary"] == "playbook ready: 1 setup bans, 1 blocked windows"
    assert result["signal"] is None
    assert result["playbook"] == writes["session_playbook_MNQ.json"]
    assert appended["call"]["args"][0] == "SESSION_PLAYBOOK_PUBLISHED"
    assert appended["call"]["args"][3]["signal"] is None
    assert appended["call"]["args"][3]["playbook"] == writes["session_playbook_MNQ.json"]
    assert "playbook ready: 1 setup bans, 1 blocked windows" in capsys.readouterr().out
