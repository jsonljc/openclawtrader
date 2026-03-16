"""Layer 1 (relevance) and Layer 2 (immediate action) keyword filtering."""
from __future__ import annotations

import re
from pathlib import Path

import yaml

_CONFIG_DIR = Path(__file__).parent.parent / "config"

# Short keywords (<=5 chars) that need word-boundary matching to avoid
# false positives like "federated" matching "fed" or "reward" matching "war".
_SHORT_KEYWORD_THRESHOLD = 5


def load_keywords(path: Path | None = None) -> dict:
    """Load keyword config from YAML."""
    p = path or (_CONFIG_DIR / "keywords.yaml")
    with open(p) as f:
        data = yaml.safe_load(f)
    # Pre-compile word-boundary regexes for short Layer 1 keywords
    compiled = []
    for kw in data.get("layer_1", []):
        kw_lower = kw.lower()
        if len(kw_lower) <= _SHORT_KEYWORD_THRESHOLD:
            compiled.append(re.compile(r"\b" + re.escape(kw_lower) + r"\b"))
        else:
            compiled.append(kw_lower)
    data["_layer_1_compiled"] = compiled
    return data


def layer_1_filter(
    headline: str,
    keywords: dict,
    summary: str = "",
) -> bool:
    """Return True if item is relevant (contains at least one Layer 1 keyword)."""
    text = (headline + " " + summary).lower()
    if not text.strip():
        return False
    compiled = keywords.get("_layer_1_compiled")
    if compiled:
        for matcher in compiled:
            if isinstance(matcher, re.Pattern):
                if matcher.search(text):
                    return True
            else:
                if matcher in text:
                    return True
        return False
    # Fallback if keywords loaded without compilation
    for kw in keywords.get("layer_1", []):
        if kw.lower() in text:
            return True
    return False


def layer_2_check(
    headline: str,
    keywords: dict,
    source_id: str = "",
) -> str | None:
    """Return 'HALT', 'CAUTION', or None based on Layer 2 keyword match."""
    text = headline.lower()

    # Check HALT first (highest priority)
    for phrase in keywords.get("layer_2_halt", []):
        if phrase.lower() in text:
            return "HALT"

    # Check CAUTION
    tariff_sources = set(keywords.get("layer_2_caution_tariff_sources", []))
    for phrase in keywords.get("layer_2_caution", []):
        p = phrase.lower()
        if p == "tariff":
            if source_id in tariff_sources and p in text:
                return "CAUTION"
        elif p in text:
            return "CAUTION"

    return None
