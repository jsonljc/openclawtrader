"""Tests for Layer 1 and Layer 2 keyword filtering."""
import pytest
from openclaw_trader.signals.keyword_filter import (
    load_keywords,
    layer_1_filter,
    layer_2_check,
)


@pytest.fixture
def keywords():
    return load_keywords()


# -- Layer 1 --

class TestLayer1:
    def test_relevant_headline_passes(self, keywords):
        assert layer_1_filter("Fed raises interest rate by 25bp", keywords) is True

    def test_irrelevant_headline_discarded(self, keywords):
        assert layer_1_filter("Local cat wins dog show in Ohio", keywords) is False

    def test_case_insensitive(self, keywords):
        assert layer_1_filter("FOMC DECIDES ON RATES", keywords) is True

    def test_partial_word_no_false_positive(self, keywords):
        # "Federation" should NOT match "fed" — word boundary prevents it
        assert layer_1_filter("Federation of bakers meets", keywords) is False

    def test_short_keyword_standalone_matches(self, keywords):
        # "fed" as a standalone word should still match
        assert layer_1_filter("The fed announces new policy", keywords) is True

    def test_empty_headline_discarded(self, keywords):
        assert layer_1_filter("", keywords) is False

    def test_keyword_in_summary_passes(self, keywords):
        assert layer_1_filter(
            "Breaking news update",
            keywords,
            summary="The Federal Reserve announced new policy",
        ) is True

    def test_discard_rate_above_90_pct(self, keywords):
        """Feed 100 generic headlines, confirm >90 are discarded."""
        generic = [
            f"Local news story number {i} about weather and sports"
            for i in range(100)
        ]
        discarded = sum(1 for h in generic if not layer_1_filter(h, keywords))
        assert discarded >= 90

    def test_all_critical_keywords_individually(self, keywords):
        critical = ["fomc", "tariff", "nuclear", "opec", "missile", "fdic"]
        for kw in critical:
            assert layer_1_filter(f"Breaking: {kw} related news", keywords) is True


# -- Layer 2 --

class TestLayer2:
    def test_halt_on_circuit_breaker(self, keywords):
        result = layer_2_check(
            "NYSE circuit breaker activated after 7% drop",
            keywords,
            source_id="REUTERS_WORLD",
        )
        assert result == "HALT"

    def test_halt_on_nuclear(self, keywords):
        result = layer_2_check(
            "Reports of nuclear launch detected by NORAD",
            keywords,
            source_id="AP_BREAKING",
        )
        assert result == "HALT"

    def test_halt_on_emergency_fed(self, keywords):
        result = layer_2_check(
            "Federal Reserve calls emergency fed meeting",
            keywords,
            source_id="FED_PRESS_RELEASES",
        )
        assert result == "HALT"

    def test_all_halt_keywords_fire(self, keywords):
        for phrase in keywords["layer_2_halt"]:
            result = layer_2_check(
                f"Breaking: {phrase} confirmed by officials",
                keywords,
                source_id="REUTERS_WORLD",
            )
            assert result == "HALT", f"HALT not fired for: {phrase}"

    def test_caution_tariff_from_trump(self, keywords):
        result = layer_2_check(
            "New tariff on Chinese goods announced",
            keywords,
            source_id="TRUMP_TRUTH_SOCIAL",
        )
        assert result == "CAUTION"

    def test_tariff_not_caution_from_reuters(self, keywords):
        result = layer_2_check(
            "New tariff on Chinese goods announced",
            keywords,
            source_id="REUTERS_WORLD",
        )
        assert result is None

    def test_caution_oil_field_attack(self, keywords):
        result = layer_2_check(
            "Oil field attack in Saudi Arabia disrupts production",
            keywords,
            source_id="AP_BREAKING",
        )
        assert result == "CAUTION"

    def test_no_action_on_normal_headline(self, keywords):
        result = layer_2_check(
            "Fed governor gives routine speech on inflation outlook",
            keywords,
            source_id="FED_SPEECHES",
        )
        assert result is None

    def test_halt_takes_priority_over_caution(self, keywords):
        result = layer_2_check(
            "Bank run triggers fdic receivership at major bank",
            keywords,
            source_id="REUTERS_WORLD",
        )
        assert result == "HALT"
