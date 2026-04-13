from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from openclaw_trader.sidecar.models import TradingAgentsSignal
from openclaw_trader.sidecar.tradingagents_adapter import run_tradingagents


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
        },
    }


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
