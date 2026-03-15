"""Web scraping collector stub -- Tier 2 implementation."""
from __future__ import annotations

from typing import Any

from openclaw_trader.signals.base_collector import BaseCollector


class ScrapeCollector(BaseCollector):
    """Placeholder for Tier 2 scraping sources (OPEC, USTR, etc.)."""

    def __init__(self, source_id: str, url: str, poll_interval: int, priority: str = "MEDIUM"):
        super().__init__(source_id, poll_interval, priority)
        self.url = url

    async def poll(self) -> list[dict[str, Any]]:
        return []

    def parse(self, raw_item: dict[str, Any]) -> dict[str, Any]:
        return raw_item
