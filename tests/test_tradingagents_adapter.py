from __future__ import annotations

import sys
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import openclaw_trader.sidecar.tradingagents_adapter as adapter
from openclaw_trader.sidecar.models import TradingAgentsSignal
from openclaw_trader.sidecar.tradingagents_adapter import run_tradingagents


class _FixedDatetime(datetime):
    @classmethod
    def now(cls, tz=None):  # type: ignore[override]
        return datetime(2026, 4, 13, 7, 11, 0, tzinfo=timezone.utc)


def test_run_tradingagents_normalizes_subprocess_stdout_into_signal() -> None:
    command = [
        sys.executable,
        "-c",
        (
            "import json, sys; "
            "payload = json.loads(sys.stdin.read()); "
            "print(json.dumps({"
            "\"session_date\": payload[\"session_date\"], "
            "\"generated_at\": \"2026-04-13T07:10:00Z\", "
            "\"symbol\": payload[\"symbol\"], "
            "\"blocked_windows_et\": [{\"start\": \"09:30\", \"end\": \"09:45\"}], "
            "\"disallowed_setups\": [\"ORB\", \"VWAP\", \"ORB\"], "
            "\"narrative\": \"avoid the open\", "
            "\"confidence\": 0.82, "
            "\"raw_payload\": {\"source\": \"tradingagents\", \"echo\": payload}"
            "}))"
        ),
    ]

    signal = run_tradingagents(
        command=command,
        payload={
            "session_date": "2026-04-13",
            "symbol": "MNQ",
            "upcoming_events": [{"name": "CPI", "minutes_until": 45.0}],
            "recent_trades": [{"event_type": "ORDER_FILLED", "ref_id": "T1"}],
            "active_strategies": [{"strategy_id": "orb_5m_MNQ"}],
        },
    )

    assert isinstance(signal, TradingAgentsSignal)
    assert signal.session_date == "2026-04-13"
    assert signal.generated_at == "2026-04-13T07:10:00Z"
    assert signal.symbol == "MNQ"
    assert signal.blocked_windows_et == ({"start": "09:30", "end": "09:45"},)
    assert signal.disallowed_setups == ("ORB", "VWAP", "ORB")
    assert signal.narrative == "avoid the open"
    assert signal.confidence == 0.82
    assert signal.to_dict() == {
        "session_date": "2026-04-13",
        "generated_at": "2026-04-13T07:10:00Z",
        "symbol": "MNQ",
        "blocked_windows_et": [{"start": "09:30", "end": "09:45"}],
        "disallowed_setups": ["ORB", "VWAP", "ORB"],
        "narrative": "avoid the open",
        "confidence": 0.82,
        "raw_payload": {
            "source": "tradingagents",
            "echo": {
                "session_date": "2026-04-13",
                "symbol": "MNQ",
                "upcoming_events": [{"name": "CPI", "minutes_until": 45.0}],
                "recent_trades": [{"event_type": "ORDER_FILLED", "ref_id": "T1"}],
                "active_strategies": [{"strategy_id": "orb_5m_MNQ"}],
            },
            "request_payload": {
                "session_date": "2026-04-13",
                "symbol": "MNQ",
                "upcoming_events": [{"name": "CPI", "minutes_until": 45.0}],
                "recent_trades": [{"event_type": "ORDER_FILLED", "ref_id": "T1"}],
                "active_strategies": [{"strategy_id": "orb_5m_MNQ"}],
            },
        },
    }


def test_run_tradingagents_synthesizes_generated_at_when_missing(monkeypatch) -> None:
    monkeypatch.setattr(adapter, "datetime", _FixedDatetime)

    command = [
        sys.executable,
        "-c",
        (
            "import json, sys; "
            "payload = json.loads(sys.stdin.read()); "
            "print(json.dumps({"
            "\"session_date\": payload[\"session_date\"], "
            "\"symbol\": payload[\"symbol\"], "
            "\"blocked_windows_et\": [], "
            "\"disallowed_setups\": [], "
            "\"narrative\": \"fallback clock\", "
            "\"confidence\": 0.5, "
            "\"raw_payload\": {\"source\": \"tradingagents\"}"
            "}))"
        ),
    ]

    signal = run_tradingagents(
        command=command,
        payload={
            "session_date": "2026-04-13",
            "symbol": "MNQ",
        },
    )

    assert signal.generated_at == "2026-04-13T07:11:00Z"
    assert signal.to_dict()["generated_at"] == "2026-04-13T07:11:00Z"


def test_run_tradingagents_parses_noisy_stdout_with_braces() -> None:
    command = [
        sys.executable,
        "-c",
        (
            "import json, sys; "
            "payload = json.loads(sys.stdin.read()); "
            "print('[warn] stats={\"rows\": 3, \"bad\": true}') ; "
            "print('[info] preparing output {phase=pre}') ; "
            "print(json.dumps({"
            "\"session_date\": payload[\"session_date\"], "
            "\"generated_at\": \"2026-04-13T07:12:00Z\", "
            "\"symbol\": payload[\"symbol\"], "
            "\"blocked_windows_et\": [], "
            "\"disallowed_setups\": [\"ORB\"], "
            "\"narrative\": \"noisy logs\", "
            "\"confidence\": 0.61, "
            "\"raw_payload\": {\"source\": \"tradingagents\"}"
            "}))"
        ),
    ]

    signal = run_tradingagents(
        command=command,
        payload={
            "session_date": "2026-04-13",
            "symbol": "MNQ",
        },
    )

    assert signal.generated_at == "2026-04-13T07:12:00Z"
    assert signal.disallowed_setups == ("ORB",)


def test_build_runner_summary_returns_exact_phrase() -> None:
    summary = {
        "disallowed_setups": ["ORB", "VWAP"],
        "blocked_windows_et": [
            {"start": "09:30", "end": "09:45"},
            {"start": "13:55", "end": "14:20"},
        ],
    }

    from run_tradingagents_premarket import build_runner_summary

    assert build_runner_summary(summary) == "playbook ready: 2 setup bans, 2 blocked windows"
