from __future__ import annotations

from pathlib import Path

from openclaw_trader.sidecar import storage
from openclaw_trader.sidecar.hermes_journal import append_journal_entry, read_journal_entries
from openclaw_trader.sidecar.scoring import classify_blocked_trade_outcome


def test_classify_blocked_trade_outcome_marks_good_block_when_stop_hits_before_target() -> None:
    blocked = {
        "side": "BUY",
        "bar_ts": "2026-04-12T14:35:00Z",
        "entry_price": 20000.0,
        "stop_price": 19980.0,
        "target_price": 20030.0,
    }
    bars_5m = [
        {"t": "2026-04-12T14:40:00Z", "o": 20001.0, "h": 20008.0, "l": 19995.0, "c": 20002.0},
        {"t": "2026-04-12T14:45:00Z", "o": 20002.0, "h": 20006.0, "l": 19979.0, "c": 19982.0},
        {"t": "2026-04-12T14:50:00Z", "o": 19982.0, "h": 20035.0, "l": 19980.0, "c": 20020.0},
    ]

    assert classify_blocked_trade_outcome(blocked, bars_5m) == "good_block"


def test_classify_blocked_trade_outcome_treats_same_bar_stop_and_target_as_unresolved() -> None:
    blocked = {
        "side": "BUY",
        "bar_ts": "2026-04-12T14:35:00Z",
        "entry_price": 20000.0,
        "stop_price": 19980.0,
        "target_price": 20030.0,
    }
    bars_5m = [
        {"t": "2026-04-12T14:40:00Z", "o": 20001.0, "h": 20035.0, "l": 19979.0, "c": 20020.0},
        {"t": "2026-04-12T14:45:00Z", "o": 20020.0, "h": 20028.0, "l": 20005.0, "c": 20010.0},
    ]

    assert classify_blocked_trade_outcome(blocked, bars_5m) == "unresolved"


def test_journal_round_trip(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(storage, "_DATA_DIR", Path(tmp_path / "data" / "sidecar"))

    append_journal_entry("sidecar_run", {"session_date": "2026-04-12"})

    entries = read_journal_entries("sidecar_run")

    assert len(entries) == 1
    assert entries[0]["kind"] == "sidecar_run"
    assert entries[0]["payload"]["session_date"] == "2026-04-12"


def test_read_journal_entries_skips_malformed_lines(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(storage, "_DATA_DIR", Path(tmp_path / "data" / "sidecar"))

    path = append_journal_entry("sidecar_run", {"session_date": "2026-04-12"})
    path.write_text(
        '\n'.join(
            [
                '{"kind":"sidecar_run","payload":{"session_date":"2026-04-12"},"timestamp":"2026-04-12T14:00:00Z"}',
                '{"kind":"sidecar_run","payload":{"session_date":"2026-04-13"},"timestamp":"2026-04-12T14:05:00Z"',
                '{"kind":"sidecar_run","payload":{"session_date":"2026-04-14"},"timestamp":"2026-04-12T14:10:00Z"}',
                'not-json-at-all',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    entries = read_journal_entries("sidecar_run")

    assert len(entries) == 2
    assert [entry["payload"]["session_date"] for entry in entries] == ["2026-04-12", "2026-04-14"]
