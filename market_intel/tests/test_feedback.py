"""Tests for feedback loop — conviction snapshots and outcome linking."""
import json
from pathlib import Path

import pytest

from market_intel.feedback import log_conviction_at_entry, link_outcome


@pytest.fixture
def ledger_file(tmp_path):
    return tmp_path / "ledger.jsonl"


def _sample_conviction(**overrides):
    base = {
        "has_data": True,
        "conviction": 75,
        "hold_conviction": 70,
        "clarity": "HIGH",
        "matched_pattern": "TREND_ACCELERATION",
        "regime_transition": {"detected": False},
        "sizing_modifier": 1.0,
        "factors": ["velocity_15m_bullish"],
        "timestamp": "2026-03-17T10:30:00+00:00",
    }
    base.update(overrides)
    return base


class TestLogConvictionSnapshot:
    def test_log_conviction_snapshot(self, ledger_file):
        log_conviction_at_entry("POS_001", "ES", _sample_conviction(), ledger_path=ledger_file)
        assert ledger_file.exists()
        lines = [json.loads(l) for l in ledger_file.read_text().strip().split("\n")]
        assert len(lines) == 1
        assert lines[0]["event_type"] == "CONVICTION_SNAPSHOT"
        assert lines[0]["ref_id"] == "POS_001"

    def test_snapshot_has_required_fields(self, ledger_file):
        log_conviction_at_entry("POS_002", "NQ", _sample_conviction(), ledger_path=ledger_file)
        entry = json.loads(ledger_file.read_text().strip())
        assert "ledger_seq" in entry
        assert "timestamp" in entry
        assert entry["payload"]["symbol"] == "NQ"
        assert entry["payload"]["conviction"] == 75
        assert entry["payload"]["matched_pattern"] == "TREND_ACCELERATION"

    def test_log_to_custom_path(self, tmp_path):
        custom = tmp_path / "subdir" / "custom_ledger.jsonl"
        log_conviction_at_entry("POS_003", "CL", _sample_conviction(), ledger_path=custom)
        assert custom.exists()
        entry = json.loads(custom.read_text().strip())
        assert entry["ref_id"] == "POS_003"


class TestLinkOutcome:
    def test_link_outcome_found(self, ledger_file):
        log_conviction_at_entry("POS_010", "ES", _sample_conviction(conviction=82, matched_pattern="REGIME_FLIP"), ledger_path=ledger_file)
        result = link_outcome("POS_010", realized_pnl=500.0, ledger_path=ledger_file)
        assert result is not None
        assert result["conviction_at_entry"] == 82
        assert result["pattern"] == "REGIME_FLIP"
        assert result["realized_pnl"] == 500.0

    def test_link_outcome_not_found(self, ledger_file):
        log_conviction_at_entry("POS_010", "ES", _sample_conviction(), ledger_path=ledger_file)
        result = link_outcome("POS_999", realized_pnl=100.0, ledger_path=ledger_file)
        assert result is None

    def test_multiple_snapshots(self, ledger_file):
        log_conviction_at_entry("POS_A", "ES", _sample_conviction(conviction=60), ledger_path=ledger_file)
        log_conviction_at_entry("POS_B", "NQ", _sample_conviction(conviction=85, matched_pattern="BREAKOUT_IMMINENT"), ledger_path=ledger_file)
        log_conviction_at_entry("POS_C", "CL", _sample_conviction(conviction=40), ledger_path=ledger_file)
        result = link_outcome("POS_B", realized_pnl=-200.0, ledger_path=ledger_file)
        assert result is not None
        assert result["conviction_at_entry"] == 85
        assert result["pattern"] == "BREAKOUT_IMMINENT"
        assert result["realized_pnl"] == -200.0
