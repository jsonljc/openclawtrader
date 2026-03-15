"""Tests for Redis-based headline deduplication."""
import pytest
import fakeredis

from openclaw_trader.signals.deduplicator import Deduplicator


@pytest.fixture
def dedup():
    r = fakeredis.FakeRedis()
    return Deduplicator(redis_client=r, ttl_seconds=5)


class TestDeduplicator:
    def test_first_seen_returns_false(self, dedup):
        assert dedup.is_duplicate("Fed raises rates by 25bp") is False

    def test_second_seen_returns_true(self, dedup):
        dedup.is_duplicate("Fed raises rates by 25bp")
        assert dedup.is_duplicate("Fed raises rates by 25bp") is True

    def test_different_headline_not_duplicate(self, dedup):
        dedup.is_duplicate("Fed raises rates by 25bp")
        assert dedup.is_duplicate("OPEC cuts production quotas") is False

    def test_uses_first_80_chars(self, dedup):
        base = "A" * 80
        h1 = base + " extra words here"
        h2 = base + " completely different suffix"
        dedup.is_duplicate(h1)
        assert dedup.is_duplicate(h2) is True

    def test_expired_entry_allows_reprocess(self, dedup):
        dedup.is_duplicate("Fed raises rates by 25bp")
        dedup._redis.flushall()
        assert dedup.is_duplicate("Fed raises rates by 25bp") is False

    def test_empty_headline(self, dedup):
        assert dedup.is_duplicate("") is False
        assert dedup.is_duplicate("") is True

    def test_case_insensitive(self, dedup):
        dedup.is_duplicate("FED RAISES RATES")
        assert dedup.is_duplicate("fed raises rates") is True
