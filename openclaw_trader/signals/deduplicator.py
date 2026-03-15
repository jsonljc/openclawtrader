"""Redis-based headline deduplication with 30-minute TTL."""
from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from redis import Redis


class Deduplicator:
    """Track seen headlines via Redis SET with TTL."""

    PREFIX = "openclaw:dedup:"

    def __init__(self, redis_client: "Redis", ttl_seconds: int = 1800):
        self._redis = redis_client
        self._ttl = ttl_seconds

    def _hash(self, headline: str) -> str:
        text = headline[:80].lower()
        return hashlib.sha256(text.encode()).hexdigest()[:16]

    def is_duplicate(self, headline: str) -> bool:
        """Return True if headline was seen within the TTL window."""
        key = self.PREFIX + self._hash(headline)
        was_new = self._redis.set(key, "1", nx=True, ex=self._ttl)
        return not was_new
