from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
import builtins

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from run_intraday import _blocked_by_playbook
import run_intraday
import setups.orb as orb


class _LateSessionDatetime(datetime):
    @classmethod
    def now(cls, tz=None):  # type: ignore[override]
        return datetime(2026, 4, 13, 20, 30, 0, tzinfo=timezone.utc)


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
        lambda session_date, symbol=None, strategy=None: {
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
        run_intraday,
        "score_opportunity",
        lambda **kwargs: {"total": 75},
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
    assert captured[0][3]["side"] == "BUY"
    assert captured[0][3]["bar_ts"] == "2026-04-13T13:55:00Z"
    assert captured[0][3]["entry_price"] == 5000.0
    assert captured[0][3]["stop_price"] == 4990.0
    assert captured[0][3]["target_price"] == 5020.0


def test_scan_setups_blocks_replay_bar_using_bar_timestamp(monkeypatch):
    captured: list[tuple[str, str, str, dict]] = []

    monkeypatch.setattr(run_intraday, "datetime", _LateSessionDatetime)
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
        lambda session_date, symbol=None, strategy=None: {
            "session_date": session_date,
            "disallowed_setups": [],
            "blocked_windows_et": [{"start": "09:30", "end": "10:00"}],
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
        run_intraday,
        "score_opportunity",
        lambda **kwargs: {"total": 75},
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
                    "5m": [{"t": "2026-04-13T13:35:00Z"}],
                }
            }
        },
        regime_report={"regime_type": "TREND"},
        session_report={"session": "MORNING_DRIVE"},
        structure_levels={"ES": {}},
        run_id="RUN_REPLAY",
        param_version="PV_0001",
    )

    assert intents == []
    assert captured[0][0] == run_intraday.C.EventType.INTRADAY_SETUP_BLOCKED
    assert captured[0][3]["block_reason"] == "window_blocked"
    assert captured[0][3]["bar_ts"] == "2026-04-13T13:35:00Z"


def test_run_intraday_cycle_emits_scorecard_for_blocked_setups(monkeypatch):
    captured: list[tuple[str, str, str, dict]] = []

    monkeypatch.setattr(
        run_intraday,
        "get_session_report",
        lambda now_utc, symbol="ES": {
            "session": "MORNING_DRIVE",
            "modifier": 1.0,
            "minutes_into_session": 45,
            "is_rth": True,
        },
    )
    monkeypatch.setattr(run_intraday, "is_any_rth", lambda now_utc: True)
    monkeypatch.setattr(
        run_intraday,
        "get_all_snapshots",
        lambda force_signal=False: {
            "ES": {
                "bars": {
                    "5m": [
                        {"t": "2026-04-13T13:55:00Z", "h": 5010.0, "l": 4995.0},
                        {"t": "2026-04-13T14:00:00Z", "h": 5015.0, "l": 5000.0},
                        {"t": "2026-04-13T14:05:00Z", "h": 5025.0, "l": 5005.0},
                    ],
                    "1D": [],
                }
            }
        },
    )
    monkeypatch.setattr(run_intraday.store, "load_portfolio", lambda: {"positions": []})
    monkeypatch.setattr(run_intraday.posture, "update_posture", lambda *args, **kwargs: None)
    monkeypatch.setattr(run_intraday.watchtower, "run_health_check", lambda snapshots, run_id: {"status": "HEALTHY"})
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
        "compute_structure",
        lambda bars_5m, bars_daily, now_utc, symbol="ES", tick_size=0.25: type(
            "Levels",
            (),
            {"to_dict": lambda self: {}},
        )(),
    )
    monkeypatch.setattr(
        run_intraday,
        "classify_regime",
        lambda snapshot, structure, session: {"regime_type": "TREND"},
    )
    monkeypatch.setattr(run_intraday.store, "load_state", lambda name: {})
    monkeypatch.setattr(run_intraday.store, "save_state", lambda name, state: None)
    monkeypatch.setattr(run_intraday.forge, "process_bracket_triggers", lambda snapshots, run_id, paper=True: [])
    monkeypatch.setattr(
        run_intraday,
        "_load_session_playbook",
        lambda session_date, symbol=None, strategy=None: {
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
    monkeypatch.setattr(
        run_intraday.ledger,
        "query",
        lambda **kwargs: [
            {
                "event_type": run_intraday.C.EventType.INTRADAY_SETUP_BLOCKED,
                "run_id": "RUN_000",
                "ref_id": "STRAT_ORB_ES",
                "payload": {
                    "strategy_id": "STRAT_ORB_ES",
                    "symbol": "ES",
                    "side": "BUY",
                    "setup_family": "ORB",
                    "block_reason": "setup_disallowed",
                    "bar_ts": "2026-04-13T14:00:00Z",
                    "entry_price": 5000.0,
                    "stop_price": 4990.0,
                    "target_price": 5020.0,
                },
            }
        ],
    )

    result = run_intraday.run_intraday_cycle(run_id="RUN_789", cycle_count=0)

    assert result["status"] == "NO_SIGNAL"
    assert captured[0][0] == run_intraday.C.EventType.INTRADAY_SETUP_BLOCKED
    assert captured[0][3]["side"] == "BUY"
    assert captured[1][0] == run_intraday.C.EventType.HERMES_SCORECARD
    assert captured[1][1] == "RUN_789"
    assert captured[1][2] == "ES"
    assert captured[1][3]["symbol"] == "ES"
    assert captured[1][3]["session_date"] == "2026-04-13"
    assert captured[1][3]["blocked_events"] == 1
    assert captured[1][3]["blocked_good"] == 0
    assert captured[1][3]["blocked_bad"] == 1
    assert captured[1][3]["blocked_unresolved"] == 0


def test_scan_setups_ignores_playbook_for_other_symbol(monkeypatch):
    captured: list[tuple[str, str, str, dict]] = []
    current_session_date = datetime.now(timezone.utc).astimezone(run_intraday._ET).date().isoformat()

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
        "read_json",
        lambda name: {
            "session_date": current_session_date,
            "symbol": "MNQ",
            "disallowed_setups": ["ORB"],
            "blocked_windows_et": [{"start": "09:30", "end": "10:00"}],
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
        run_intraday,
        "score_opportunity",
        lambda **kwargs: {"total": 75},
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
        run_id="RUN_456",
        param_version="PV_0001",
    )

    assert len(intents) == 1
    assert intents[0]["strategy_id"] == "STRAT_ORB_ES"
    assert len(captured) == 1
    assert captured[0][0] == run_intraday.C.EventType.INTENT_CREATED
    assert captured[0][1] == "RUN_456"
    assert captured[0][2] == intents[0]["intent_id"]
    assert captured[0][3] == intents[0]


def test_load_session_playbook_uses_symbol_scoped_artifact(monkeypatch):
    reads: list[str] = []

    def _read_json(name: str):
        reads.append(name)
        payloads = {
            "session_playbook_ES.json": {
                "session_date": "2026-04-13",
                "symbol": "ES",
                "disallowed_setups": ["ORB"],
                "blocked_windows_et": [{"start": "09:30", "end": "10:00"}],
            },
            "session_playbook_MNQ.json": {
                "session_date": "2026-04-13",
                "symbol": "MNQ",
                "disallowed_setups": [],
                "blocked_windows_et": [],
            },
        }
        return payloads.get(name)

    monkeypatch.setattr(run_intraday, "read_json", _read_json)

    es_playbook = run_intraday._load_session_playbook("2026-04-13", symbol="ES")
    mnq_playbook = run_intraday._load_session_playbook("2026-04-13", symbol="MNQ")

    assert reads == ["session_playbook_ES.json", "session_playbook_MNQ.json"]
    assert es_playbook["symbol"] == "ES"
    assert es_playbook["disallowed_setups"] == ["ORB"]
    assert mnq_playbook["symbol"] == "MNQ"
    assert mnq_playbook["disallowed_setups"] == []


def test_build_eastern_timezone_falls_back_to_fixed_offset_when_zoneinfo_missing(monkeypatch):
    original_import = builtins.__import__

    def _raising_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "zoneinfo":
            raise ImportError("zoneinfo unavailable")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _raising_import)

    et = run_intraday._build_eastern_timezone()

    assert et.utcoffset(datetime(2026, 4, 14, 14, 0, tzinfo=timezone.utc)) == timedelta(hours=-5)
    assert run_intraday._session_date_from_timestamp("2026-04-14T02:30:00Z") == "2026-04-13"


def test_append_blocked_setup_scorecards_skips_duplicate_totals_for_same_session_symbol(monkeypatch):
    captured: list[tuple[str, str, str, dict]] = []
    now_utc = datetime(2026, 4, 13, 14, 10, tzinfo=timezone.utc)
    blocked_events = [
        {
            "payload": {
                "symbol": "ES",
                "setup_family": "ORB",
                "bar_ts": "2026-04-13T14:00:00Z",
                "side": "BUY",
                "stop_price": 4990.0,
                "target_price": 5020.0,
            }
        }
    ]

    monkeypatch.setattr(run_intraday, "_blocked_scorecard_totals", {})
    monkeypatch.setattr(run_intraday.ledger, "query", lambda **kwargs: list(blocked_events))
    monkeypatch.setattr(
        run_intraday.ledger,
        "append",
        lambda event_type, run_id, entity_id, payload: captured.append(
            (event_type, run_id, entity_id, payload)
        ),
    )

    snapshots = {
        "ES": {
            "bars": {
                "5m": [
                    {"t": "2026-04-13T14:05:00Z", "h": 5025.0, "l": 4995.0},
                ]
            }
        }
    }

    first = run_intraday._append_blocked_setup_scorecards("RUN_A", snapshots, now_utc=now_utc)
    second = run_intraday._append_blocked_setup_scorecards("RUN_B", snapshots, now_utc=now_utc)

    blocked_events.append(
        {
            "payload": {
                "symbol": "ES",
                "setup_family": "VWAP",
                "bar_ts": "2026-04-13T14:05:00Z",
                "side": "BUY",
                "stop_price": 5000.0,
                "target_price": 5030.0,
            }
        }
    )
    third = run_intraday._append_blocked_setup_scorecards("RUN_C", snapshots, now_utc=now_utc)

    assert len(first) == 1
    assert second == []
    assert len(third) == 1
    assert [entry[1] for entry in captured] == ["RUN_A", "RUN_C"]
    assert captured[0][0] == run_intraday.C.EventType.HERMES_SCORECARD
    assert captured[0][3]["blocked_events"] == 1
    assert captured[1][3]["blocked_events"] == 2


def test_scan_setups_applies_micro_symbol_playbook_to_canonical_symbol_strategy(monkeypatch):
    captured: list[tuple[str, str, str, dict]] = []
    reads: list[str] = []

    monkeypatch.setattr(
        run_intraday.store,
        "load_strategy_registry",
        lambda: {
            "STRAT_ORB_MNQ": {
                "timeframe": "5m",
                "status": "ACTIVE",
                "symbol": "NQ",
                "micro_symbol": "MNQ",
                "contract_month": "NQM6",
                "signal": {"setup_family": "ORB"},
            }
        },
    )

    def _read_json(name: str):
        reads.append(name)
        payloads = {
            "session_playbook_MNQ.json": {
                "session_date": "2026-04-13",
                "symbol": "MNQ",
                "disallowed_setups": ["ORB"],
                "blocked_windows_et": [],
            }
        }
        return payloads.get(name)

    monkeypatch.setattr(run_intraday, "read_json", _read_json)
    monkeypatch.setattr(
        orb,
        "detect",
        lambda **kwargs: {
            "side": "BUY",
            "entry_price": 21000.0,
            "stop_price": 20970.0,
            "target_price": 21060.0,
        },
    )
    monkeypatch.setattr(run_intraday, "score_opportunity", lambda **kwargs: {"total": 75})
    monkeypatch.setattr(
        run_intraday.ledger,
        "append",
        lambda event_type, run_id, entity_id, payload: captured.append(
            (event_type, run_id, entity_id, payload)
        ),
    )

    intents = run_intraday._scan_setups(
        snapshots={
            "NQ": {
                "bars": {
                    "5m": [{"t": "2026-04-13T13:55:00Z"}],
                }
            }
        },
        regime_report={"regime_type": "TREND"},
        session_report={"session": "MORNING_DRIVE"},
        structure_levels={"NQ": {}},
        run_id="RUN_MNQ_ALIAS",
        param_version="PV_0001",
    )

    assert intents == []
    assert reads == ["session_playbook_MNQ.json"]
    assert captured[0][0] == run_intraday.C.EventType.INTRADAY_SETUP_BLOCKED
    assert captured[0][2] == "STRAT_ORB_MNQ"
    assert captured[0][3]["symbol"] == "NQ"
    assert captured[0][3]["setup_family"] == "ORB"
    assert captured[0][3]["block_reason"] == "setup_disallowed"


def test_load_session_playbook_prefers_micro_symbol_artifact_when_both_aliases_exist(monkeypatch):
    reads: list[str] = []

    def _read_json(name: str):
        reads.append(name)
        payloads = {
            "session_playbook_MNQ.json": {
                "session_date": "2026-04-13",
                "symbol": "MNQ",
                "disallowed_setups": ["ORB"],
                "blocked_windows_et": [],
            },
            "session_playbook_NQ.json": {
                "session_date": "2026-04-13",
                "symbol": "NQ",
                "disallowed_setups": [],
                "blocked_windows_et": [],
            },
        }
        return payloads.get(name)

    monkeypatch.setattr(run_intraday, "read_json", _read_json)

    playbook = run_intraday._load_session_playbook(
        "2026-04-13",
        symbol="NQ",
        strategy={"symbol": "NQ", "micro_symbol": "MNQ"},
    )

    assert reads == ["session_playbook_MNQ.json"]
    assert playbook["symbol"] == "MNQ"
    assert playbook["disallowed_setups"] == ["ORB"]
