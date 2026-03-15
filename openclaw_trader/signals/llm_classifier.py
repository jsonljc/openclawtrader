"""Layer 3 LLM classification using Claude Haiku."""
from __future__ import annotations

import json
import re
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from anthropic import Anthropic

MODEL = "claude-haiku-4-5-20251001"
MAX_INPUT_TOKENS = 200
MAX_OUTPUT_TOKENS = 100
TIMEOUT_SECONDS = 3

_CAUTION_DEFAULT = {
    "tier": "CAUTION",
    "direction": "NEUTRAL",
    "instruments": ["ES", "NQ", "CL", "GC", "ZB"],
    "confidence": 0.5,
}

PROMPT_TEMPLATES = {
    "FED": (
        "Fed news classifier. Respond JSON only.\n"
        "Headline: {headline}\n"
        "Summary: {summary}\n"
        '{{"tier":"HALT|CAUTION|MONITOR","direction":"HAWKISH|DOVISH|NEUTRAL",'
        '"instruments":["ES","NQ","GC","ZB"],"confidence":0.0-1.0}}\n'
        "HAWKISH=rate hike/less cuts=ES down GC down ZB down\n"
        "DOVISH=rate cut/more cuts=ES up GC up ZB up"
    ),
    "TRUMP": (
        "Trump/White House post market classifier. JSON only.\n"
        "Post: {headline}\n"
        "Context: {summary}\n"
        '{{"tier":"HALT|CAUTION|MONITOR",'
        '"topic":"TARIFF_NEW|TARIFF_ROLLBACK|FED_ATTACK|ENERGY_DRILL|'
        'CHINA_HOSTILE|TRADE_DEAL_POSITIVE|GEOPOLITICAL|OTHER",'
        '"instruments":["ES","NQ","CL","GC","ZB"],"confidence":0.0-1.0}}'
    ),
    "GEO": (
        "Geopolitical/conflict news classifier. JSON only.\n"
        "Headline: {headline}\n"
        "Summary: {summary}\n"
        '{{"tier":"HALT|CAUTION|MONITOR",'
        '"conflict_type":"ESCALATION|DE_ESCALATION|NEUTRAL",'
        '"region":"MIDDLE_EAST|UKRAINE_RUSSIA|TAIWAN_CHINA|OTHER",'
        '"instruments":["ES","NQ","CL","GC","ZB"],"confidence":0.0-1.0}}'
    ),
    "ENERGY": (
        "Energy market news classifier. JSON only.\n"
        "Headline: {headline}\n"
        "Summary: {summary}\n"
        '{{"tier":"HALT|CAUTION|MONITOR","direction":"BULLISH|BEARISH|NEUTRAL",'
        '"instruments":["CL"],"confidence":0.0-1.0}}'
    ),
    "DEFAULT": (
        "Market news classifier. JSON only.\n"
        "Headline: {headline}\n"
        "Summary: {summary}\n"
        '{{"tier":"HALT|CAUTION|MONITOR","direction":"BULLISH|BEARISH|NEUTRAL",'
        '"instruments":["ES","NQ","CL","GC","ZB"],"confidence":0.0-1.0}}'
    ),
}

_SOURCE_TO_TEMPLATE = {
    "FED_PRESS_RELEASES": "FED",
    "FED_SPEECHES": "FED",
    "NY_FED": "FED",
    "TRUMP_TRUTH_SOCIAL": "TRUMP",
    "TRUMP_TWITTER": "TRUMP",
    "WHITE_HOUSE_OFFICIAL": "TRUMP",
    "WHITE_HOUSE_PRESS_SEC": "TRUMP",
    "REUTERS_WORLD": "GEO",
    "AP_BREAKING": "GEO",
    "BBC_WORLD": "GEO",
    "AL_JAZEERA": "GEO",
    "KYIV_INDEPENDENT": "GEO",
    "TIMES_OF_ISRAEL": "GEO",
    "SCMP": "GEO",
    "EIA_PETROLEUM": "ENERGY",
    "OPEC_OFFICIAL": "ENERGY",
}


def _build_prompt(headline: str, summary: str, source_id: str) -> str:
    template_key = _SOURCE_TO_TEMPLATE.get(source_id, "DEFAULT")
    template = PROMPT_TEMPLATES[template_key]
    return template.format(
        headline=headline[:200],
        summary=summary[:150],
    )


def _parse_response(raw: str) -> dict[str, Any]:
    """Extract JSON from LLM response. Fall back to CAUTION on failure."""
    match = re.search(r"\{[^{}]+\}", raw)
    if match:
        try:
            data = json.loads(match.group())
            return {
                "tier": data.get("tier", "CAUTION"),
                "direction": data.get("direction", "NEUTRAL"),
                "instruments": data.get("instruments", ["ES", "NQ", "CL", "GC", "ZB"]),
                "confidence": data.get("confidence", 0.5),
                **{k: v for k, v in data.items()
                   if k not in ("tier", "direction", "instruments", "confidence")},
            }
        except (json.JSONDecodeError, ValueError):
            pass
    return dict(_CAUTION_DEFAULT)


def classify_headline(
    headline: str,
    summary: str,
    source_id: str,
    client: "Anthropic",
) -> dict[str, Any]:
    """Classify a headline using Haiku. Returns result dict with 'classification' field."""
    prompt = _build_prompt(headline, summary, source_id)
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_OUTPUT_TOKENS,
            messages=[{"role": "user", "content": prompt}],
            timeout=TIMEOUT_SECONDS,
        )
        raw = response.content[0].text
        result = _parse_response(raw)
        result["classification"] = "LLM"
        return result
    except TimeoutError:
        return {**_CAUTION_DEFAULT, "classification": "TIMEOUT"}
    except Exception:
        return {**_CAUTION_DEFAULT, "classification": "ERROR"}
