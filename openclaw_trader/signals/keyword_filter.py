"""Layer 1 (relevance) and Layer 2 (immediate action) keyword filtering."""
from __future__ import annotations

from pathlib import Path

import yaml

_CONFIG_DIR = Path(__file__).parent.parent / "config"


def load_keywords(path: Path | None = None) -> dict:
    """Load keyword config from YAML."""
    p = path or (_CONFIG_DIR / "keywords.yaml")
    with open(p) as f:
        return yaml.safe_load(f)


def layer_1_filter(
    headline: str,
    keywords: dict,
    summary: str = "",
) -> bool:
    """Return True if item is relevant (contains at least one Layer 1 keyword)."""
    text = (headline + " " + summary).lower()
    if not text.strip():
        return False
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
