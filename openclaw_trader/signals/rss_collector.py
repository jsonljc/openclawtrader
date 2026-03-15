"""RSS/Atom feed collector using feedparser."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import feedparser

from openclaw_trader.signals.base_collector import BaseCollector

logger = logging.getLogger(__name__)


class RSSCollector(BaseCollector):
    """Poll an RSS/Atom feed URL."""

    def __init__(self, source_id: str, url: str, poll_interval: int, priority: str = "MEDIUM"):
        super().__init__(source_id, poll_interval, priority)
        self.url = url
        self._etag: str | None = None
        self._modified: str | None = None

    async def poll(self) -> list[dict[str, Any]]:
        loop = asyncio.get_event_loop()
        feed = await loop.run_in_executor(None, self._fetch)
        if feed is None:
            return []
        self._etag = feed.get("etag", self._etag)
        self._modified = feed.get("modified", self._modified)
        return [self.parse(entry) for entry in feed.get("entries", [])]

    def _fetch(self) -> dict | None:
        try:
            kwargs = {}
            if self._etag:
                kwargs["etag"] = self._etag
            if self._modified:
                kwargs["modified"] = self._modified
            feed = feedparser.parse(self.url, **kwargs)
            if feed.get("status", 200) == 304:
                return None
            if feed.bozo and not feed.entries:
                logger.warning(f"[{self.source_id}] Feed parse error: {feed.bozo_exception}")
                return None
            return feed
        except Exception as exc:
            logger.error(f"[{self.source_id}] Fetch failed: {exc}")
            return None

    def parse(self, raw_item: dict[str, Any]) -> dict[str, Any]:
        return {
            "headline": raw_item.get("title", "")[:200],
            "summary": raw_item.get("summary", raw_item.get("description", ""))[:300],
            "url": raw_item.get("link", ""),
            "published": raw_item.get("published", ""),
            "source_id": self.source_id,
        }
