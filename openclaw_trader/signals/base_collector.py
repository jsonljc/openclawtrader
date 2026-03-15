"""Abstract base class for all signal collectors."""
from __future__ import annotations

import abc
import logging
from typing import Any

logger = logging.getLogger(__name__)


class BaseCollector(abc.ABC):
    """All collectors implement poll() and parse()."""

    def __init__(self, source_id: str, poll_interval: int, priority: str = "MEDIUM"):
        self.source_id = source_id
        self.poll_interval = poll_interval
        self.priority = priority

    @abc.abstractmethod
    async def poll(self) -> list[dict[str, Any]]:
        """Fetch raw items from the source. Returns list of raw item dicts."""

    @abc.abstractmethod
    def parse(self, raw_item: dict[str, Any]) -> dict[str, Any]:
        """Parse a raw item into {headline, summary, url, published}."""
