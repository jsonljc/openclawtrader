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
            source_attribution=[{"source": "TradingAgents", "field": "disallowed_setups"}],
            fallback_reason=None,
        ),
    )
    monkeypatch.setattr(runner, "write_json", lambda name, payload: writes.setdefault(name, payload))

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
    assert writes["tradingagents_signal.json"] == {
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
    assert writes["session_playbook.json"] == {
        "session_date": "2026-04-13",
        "generated_at": "2026-04-13T11:16:00Z",
        "expires_at": "2026-04-13T20:00:00Z",
        "symbol": "MNQ",
        "disallowed_setups": ["ORB", "VWAP"],
        "blocked_windows_et": [{"start": "09:30", "end": "09:45"}],
        "source_attribution": [{"source": "TradingAgents", "field": "disallowed_setups"}],
        "fallback_reason": None,
    }
    assert appended["call"]["args"][0] == "SESSION_PLAYBOOK_PUBLISHED"
    assert result["summary"] == "playbook ready: 2 setup bans, 1 blocked windows"
    assert "playbook ready: 2 setup bans, 1 blocked windows" in capsys.readouterr().out
