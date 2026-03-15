"""Tests for NEWS_RESPONSE_MAP loading and querying."""
import pytest
from openclaw_trader.signals.response_matrix import ResponseMatrix


@pytest.fixture
def matrix():
    return ResponseMatrix()


class TestResponseMatrix:
    def test_load_all_events(self, matrix):
        assert len(matrix.events()) >= 22

    def test_fed_rate_cut_es_long(self, matrix):
        r = matrix.get("FED_RATE_CUT_SURPRISE", "ES")
        assert r["action"] == "DIRECTIONAL_LONG"
        assert r["confirm_bars"] == 1

    def test_fed_rate_hike_gc_short(self, matrix):
        r = matrix.get("FED_RATE_HIKE_SURPRISE", "GC")
        assert r["action"] == "DIRECTIONAL_SHORT"
        assert r["confirm_bars"] == 2

    def test_middle_east_escalation_es_halt(self, matrix):
        r = matrix.get("MIDDLE_EAST_ESCALATION", "ES")
        assert r["action"] == "HALT"

    def test_middle_east_escalation_cl_long(self, matrix):
        r = matrix.get("MIDDLE_EAST_ESCALATION", "CL")
        assert r["action"] == "DIRECTIONAL_LONG"
        assert r["confirm_bars"] == 2

    def test_nuclear_all_halt(self, matrix):
        for sym in ("ES", "NQ", "CL", "GC", "ZB"):
            r = matrix.get("NUCLEAR_ANY_REFERENCE", sym)
            assert r["action"] == "HALT"
            assert r.get("human_required") is True

    def test_opec_cut_only_cl(self, matrix):
        assert matrix.get("OPEC_PRODUCTION_CUT", "CL")["action"] == "DIRECTIONAL_LONG"
        assert matrix.get("OPEC_PRODUCTION_CUT", "ES")["action"] == "IGNORE"
        assert matrix.get("OPEC_PRODUCTION_CUT", "GC")["action"] == "IGNORE"

    def test_unknown_event_returns_monitor(self, matrix):
        r = matrix.get("TOTALLY_UNKNOWN_EVENT", "ES")
        assert r["action"] == "MONITOR"

    def test_unknown_instrument_returns_monitor(self, matrix):
        r = matrix.get("FED_RATE_CUT_SURPRISE", "FAKE")
        assert r["action"] == "MONITOR"

    def test_trump_tariff_nq_short(self, matrix):
        r = matrix.get("TRUMP_NEW_TARIFF", "NQ")
        assert r["action"] == "DIRECTIONAL_SHORT"

    def test_trump_rollback_gc_short(self, matrix):
        r = matrix.get("TRUMP_TARIFF_ROLLBACK", "GC")
        assert r["action"] == "DIRECTIONAL_SHORT"

    def test_bank_failure_major_human_required(self, matrix):
        r = matrix.get("BANK_FAILURE_MAJOR", "ES")
        assert r["action"] == "HALT"
        assert r.get("human_required") is True

    def test_cpi_hot_gc_long(self, matrix):
        r = matrix.get("CPI_HOT", "GC")
        assert r["action"] == "DIRECTIONAL_LONG"

    def test_eia_bullish_cl_long(self, matrix):
        r = matrix.get("EIA_INVENTORY_BULLISH_SURPRISE", "CL")
        assert r["action"] == "DIRECTIONAL_LONG"

    def test_get_all_instruments(self, matrix):
        actions = matrix.get_all("MIDDLE_EAST_ESCALATION")
        assert actions["ES"]["action"] == "HALT"
        assert actions["CL"]["action"] == "DIRECTIONAL_LONG"
        assert len(actions) == 5
