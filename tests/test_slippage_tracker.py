#!/usr/bin/env python3
"""Unit tests for slippage_tracker.py — micro/full classification, rolling stats, alerts.

Covers:
  - contract_type_for_symbol(): micro vs full classification
  - record_fill(): recording, rolling avg, truncation
  - Alert: micro avg > 2x full avg triggers alert
  - get_stats(): returns current statistics
"""

from __future__ import annotations
import os
import sys
import json
import tempfile
from pathlib import Path

import pytest

_test_data_dir = tempfile.mkdtemp(prefix="slippage_test_")
os.environ["OPENCLAW_DATA"] = _test_data_dir

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "workspace-forge"))

import slippage_tracker as _st_mod
_st_mod._DATA_DIR = Path(_test_data_dir)
_st_mod._SLIPPAGE_PATH = Path(_test_data_dir) / "slippage_tracker.json"

from slippage_tracker import (
    contract_type_for_symbol,
    record_fill,
    get_stats,
    _load_tracker,
    _is_micro,
    MAX_RECORDS,
    ROLLING_WINDOW,
)


# ── contract_type_for_symbol ──

class TestContractType:
    def test_es_is_full(self):
        assert contract_type_for_symbol("ES") == "full"

    def test_mes_is_micro(self):
        assert contract_type_for_symbol("MES") == "micro"

    def test_nq_is_full(self):
        assert contract_type_for_symbol("NQ") == "full"

    def test_mnq_is_micro(self):
        assert contract_type_for_symbol("MNQ") == "micro"

    def test_cl_is_full(self):
        assert contract_type_for_symbol("CL") == "full"

    def test_mcl_is_micro(self):
        assert contract_type_for_symbol("MCL") == "micro"

    def test_gc_is_full(self):
        assert contract_type_for_symbol("GC") == "full"

    def test_mgc_is_micro(self):
        assert contract_type_for_symbol("MGC") == "micro"

    def test_zb_is_full(self):
        assert contract_type_for_symbol("ZB") == "full"

    def test_case_insensitive(self):
        assert _is_micro("mes")
        assert _is_micro("MES")
        assert not _is_micro("es")


# ── record_fill ──

class TestRecordFill:
    def setup_method(self):
        # Clean tracker state before each test
        tracker_path = Path(_test_data_dir) / "slippage_tracker.json"
        if tracker_path.exists():
            tracker_path.unlink()

    def test_basic_fill_recording(self):
        result = record_fill(
            symbol="ES", strategy_id="trend_reclaim_4H_ES",
            slippage_ticks=1.0, slippage_usd=12.50,
            contracts=1, fill_price=5000.0, side="BUY", run_id="R001",
        )
        assert result["contract_type"] == "full"
        assert result["alert"] is False

    def test_micro_fill_recording(self):
        result = record_fill(
            symbol="MES", strategy_id="trend_reclaim_4H_ES",
            slippage_ticks=2.0, slippage_usd=2.50,
            contracts=1, fill_price=5000.0, side="BUY", run_id="R001",
        )
        assert result["contract_type"] == "micro"

    def test_rolling_average_computed(self):
        for i in range(5):
            result = record_fill(
                symbol="ES", strategy_id="test",
                slippage_ticks=2.0, slippage_usd=25.0,
                contracts=1, fill_price=5000.0, side="BUY",
            )
        assert result["full_avg"] == pytest.approx(2.0, abs=0.01)

    def test_fills_persist_to_file(self):
        record_fill(
            symbol="ES", strategy_id="test",
            slippage_ticks=1.5, slippage_usd=18.75,
            contracts=1, fill_price=5000.0, side="BUY",
        )
        tracker = _load_tracker()
        assert len(tracker["full"]["fills"]) == 1
        assert tracker["full"]["fills"][0]["slippage_ticks"] == 1.5

    def test_max_records_truncation(self):
        for i in range(MAX_RECORDS + 10):
            record_fill(
                symbol="ES", strategy_id="test",
                slippage_ticks=1.0, slippage_usd=12.50,
                contracts=1, fill_price=5000.0, side="BUY",
            )
        tracker = _load_tracker()
        assert len(tracker["full"]["fills"]) == MAX_RECORDS


# ── Alert condition ──

class TestAlert:
    def setup_method(self):
        tracker_path = Path(_test_data_dir) / "slippage_tracker.json"
        if tracker_path.exists():
            tracker_path.unlink()

    def test_alert_when_micro_exceeds_2x_full(self):
        # Record 10+ full fills with low slippage
        for _ in range(15):
            record_fill(
                symbol="ES", strategy_id="test",
                slippage_ticks=1.0, slippage_usd=12.50,
                contracts=1, fill_price=5000.0, side="BUY",
            )
        # Record 10+ micro fills with high slippage (> 2x full)
        result = None
        for _ in range(15):
            result = record_fill(
                symbol="MES", strategy_id="test",
                slippage_ticks=3.0, slippage_usd=3.75,
                contracts=1, fill_price=5000.0, side="BUY",
            )
        assert result["alert"] is True
        assert "2x" in result["alert_message"]

    def test_no_alert_when_micro_below_2x(self):
        for _ in range(15):
            record_fill(symbol="ES", strategy_id="test",
                        slippage_ticks=1.0, slippage_usd=12.50,
                        contracts=1, fill_price=5000.0, side="BUY")
        result = None
        for _ in range(15):
            result = record_fill(symbol="MES", strategy_id="test",
                                 slippage_ticks=1.5, slippage_usd=1.88,
                                 contracts=1, fill_price=5000.0, side="BUY")
        assert result["alert"] is False

    def test_no_alert_with_insufficient_micro_data(self):
        for _ in range(15):
            record_fill(symbol="ES", strategy_id="test",
                        slippage_ticks=1.0, slippage_usd=12.50,
                        contracts=1, fill_price=5000.0, side="BUY")
        # Only 5 micro fills (< 10 needed)
        result = None
        for _ in range(5):
            result = record_fill(symbol="MES", strategy_id="test",
                                 slippage_ticks=5.0, slippage_usd=6.25,
                                 contracts=1, fill_price=5000.0, side="BUY")
        assert result["alert"] is False


# ── get_stats ──

class TestGetStats:
    def setup_method(self):
        tracker_path = Path(_test_data_dir) / "slippage_tracker.json"
        if tracker_path.exists():
            tracker_path.unlink()

    def test_empty_stats(self):
        stats = get_stats()
        assert stats["micro"]["total_fills"] == 0
        assert stats["full"]["total_fills"] == 0

    def test_stats_after_fills(self):
        record_fill(symbol="ES", strategy_id="test",
                    slippage_ticks=1.0, slippage_usd=12.50,
                    contracts=1, fill_price=5000.0, side="BUY")
        record_fill(symbol="MES", strategy_id="test",
                    slippage_ticks=2.0, slippage_usd=2.50,
                    contracts=1, fill_price=5000.0, side="BUY")
        stats = get_stats()
        assert stats["full"]["total_fills"] == 1
        assert stats["micro"]["total_fills"] == 1
        assert stats["full"]["avg_slippage_ticks"] == pytest.approx(1.0, abs=0.01)
        assert stats["micro"]["avg_slippage_ticks"] == pytest.approx(2.0, abs=0.01)
