"""Tests for Layer 3 LLM classification using mocked Anthropic client."""
import json
import pytest
from unittest.mock import MagicMock

from openclaw_trader.signals.llm_classifier import (
    classify_headline,
    _build_prompt,
    _parse_response,
    PROMPT_TEMPLATES,
)


class TestBuildPrompt:
    def test_fed_source_uses_fed_template(self):
        prompt = _build_prompt(
            headline="Fed raises rates",
            summary="25bp hike announced",
            source_id="FED_PRESS_RELEASES",
        )
        assert "HAWKISH" in prompt
        assert "Fed raises rates" in prompt

    def test_geopolitical_source_uses_geo_template(self):
        prompt = _build_prompt(
            headline="Missiles launched",
            summary="Conflict escalation",
            source_id="REUTERS_WORLD",
        )
        assert "ESCALATION" in prompt or "conflict" in prompt.lower()

    def test_trump_source_uses_trump_template(self):
        prompt = _build_prompt(
            headline="New tariffs on China",
            summary="50% tariff",
            source_id="TRUMP_TRUTH_SOCIAL",
        )
        assert "TARIFF" in prompt

    def test_summary_truncated_to_150_chars(self):
        long_summary = "x" * 300
        prompt = _build_prompt(
            headline="test",
            summary=long_summary,
            source_id="FED_PRESS_RELEASES",
        )
        assert "x" * 151 not in prompt


class TestParseResponse:
    def test_valid_json(self):
        raw = '{"tier":"CAUTION","direction":"HAWKISH","instruments":["ES","NQ"],"confidence":0.85}'
        result = _parse_response(raw)
        assert result["tier"] == "CAUTION"
        assert result["direction"] == "HAWKISH"
        assert result["confidence"] == 0.85
        assert "ES" in result["instruments"]

    def test_malformed_json_returns_caution(self):
        result = _parse_response("this is not json at all")
        assert result["tier"] == "CAUTION"
        assert result["confidence"] == 0.5

    def test_missing_fields_get_defaults(self):
        raw = '{"tier":"MONITOR"}'
        result = _parse_response(raw)
        assert result["tier"] == "MONITOR"
        assert result["direction"] == "NEUTRAL"
        assert result["confidence"] == 0.5

    def test_json_embedded_in_text(self):
        raw = 'Here is my analysis: {"tier":"HALT","direction":"NEUTRAL","instruments":["ES"],"confidence":0.95} end'
        result = _parse_response(raw)
        assert result["tier"] == "HALT"


class TestClassifyHeadline:
    def test_timeout_returns_caution(self):
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = TimeoutError("timeout")
        result = classify_headline(
            headline="Some ambiguous headline",
            summary="",
            source_id="REUTERS_WORLD",
            client=mock_client,
        )
        assert result["tier"] == "CAUTION"
        assert result["classification"] == "TIMEOUT"

    def test_successful_classification(self):
        mock_response = MagicMock()
        mock_response.content = [MagicMock()]
        mock_response.content[0].text = json.dumps({
            "tier": "CAUTION",
            "direction": "HAWKISH",
            "instruments": ["ES", "NQ", "GC", "ZB"],
            "confidence": 0.8,
        })
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        result = classify_headline(
            headline="Fed signals fewer rate cuts",
            summary="Dot plot revised",
            source_id="FED_PRESS_RELEASES",
            client=mock_client,
        )
        assert result["tier"] == "CAUTION"
        assert result["direction"] == "HAWKISH"
        assert result["classification"] == "LLM"

    def test_api_error_returns_caution(self):
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = Exception("API error")
        result = classify_headline(
            headline="Something happened",
            summary="",
            source_id="REUTERS_WORLD",
            client=mock_client,
        )
        assert result["tier"] == "CAUTION"
        assert result["classification"] == "ERROR"
