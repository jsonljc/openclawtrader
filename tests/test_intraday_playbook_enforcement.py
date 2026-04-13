from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from run_intraday import _blocked_by_playbook
import run_intraday
import setups.orb as orb


def test_blocked_by_playbook_rejects_disallowed_setup_family():
    playbook = {
        "disallowed_setups": ["ORB", "VWAP"],
        "blocked_windows_et": [],
    }

    allowed, reason = _blocked_by_playbook(playbook, "ORB", "10:15")

    assert allowed is False
    assert reason == "setup_disallowed"


def test_blocked_by_playbook_rejects_time_inside_blocked_window():
    playbook = {
        "disallowed_setups": [],
        "blocked_windows_et": [{"start": "09:30", "end": "10:00"}],
    }

    allowed, reason = _blocked_by_playbook(playbook, "TREND_PULLBACK", "09:45")

    assert allowed is False
    assert reason == "window_blocked"


def test_scan_setups_journals_blocked_opportunity(monkeypatch):
    captured: list[tuple[str, str, str, dict]] = []

    monkeypatch.setattr(
        run_intraday.store,
        "load_strategy_registry",
        lambda: {
            "STRAT_ORB_ES": {
                "timeframe": "5m",
                "status": "ACTIVE",
                "symbol": "ES",
                "contract_month": "ESM6",
                "signal": {"setup_family": "ORB"},
            }
        },
    )
    monkeypatch.setattr(
        run_intraday,
        "_load_session_playbook",
        lambda session_date: {
            "session_date": session_date,
            "disallowed_setups": ["ORB"],
            "blocked_windows_et": [],
        },
    )
    monkeypatch.setattr(
        orb,
        "detect",
        lambda **kwargs: {
            "side": "BUY",
            "entry_price": 5000.0,
            "stop_price": 4990.0,
            "target_price": 5020.0,
        },
    )
    monkeypatch.setattr(
        run_intraday.ledger,
        "append",
        lambda event_type, run_id, entity_id, payload: captured.append(
            (event_type, run_id, entity_id, payload)
        ),
    )

    intents = run_intraday._scan_setups(
        snapshots={
            "ES": {
                "bars": {
                    "5m": [{"t": "2026-04-13T13:55:00Z"}],
                }
            }
        },
        regime_report={"regime_type": "TREND"},
        session_report={"session": "MORNING_DRIVE"},
        structure_levels={"ES": {}},
        run_id="RUN_123",
        param_version="PV_0001",
    )

    assert intents == []
    assert captured[0][0] == run_intraday.C.EventType.INTRADAY_SETUP_BLOCKED
    assert captured[0][2] == "STRAT_ORB_ES"
    assert captured[0][3]["block_reason"] == "setup_disallowed"
    assert captured[0][3]["strategy_id"] == "STRAT_ORB_ES"
    assert captured[0][3]["symbol"] == "ES"
    assert captured[0][3]["setup_family"] == "ORB"
    assert captured[0][3]["bar_ts"] == "2026-04-13T13:55:00Z"
    assert captured[0][3]["entry_price"] == 5000.0
    assert captured[0][3]["stop_price"] == 4990.0
    assert captured[0][3]["target_price"] == 5020.0
