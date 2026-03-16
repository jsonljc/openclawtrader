"""Tests for sentinel_bridge — Redis signal → Sentinel modifier mapping."""
import json
import pytest

try:
    import fakeredis
except ImportError:
    pytest.skip("fakeredis not installed", allow_module_level=True)

from openclaw_trader.signals.sentinel_bridge import check_external_signals


@pytest.fixture
def redis_client():
    return fakeredis.FakeRedis(decode_responses=True)


def _publish_news(rc, tier, instruments, event_type="", direction=""):
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    rc.xadd("news_signals", {
        "source_id": "TEST",
        "headline": f"Test headline {tier}",
        "summary": "",
        "tier": tier,
        "direction": direction,
        "confidence": "0.9",
        "instruments": json.dumps(instruments),
        "duration_minutes": "30",
        "classification": "LLM",
        "source_url": "",
        "event_type": event_type,
        "timestamp": now,
    })


class TestCheckExternalSignals:
    def test_no_redis_returns_default(self):
        result = check_external_signals("ES", redis_client=None)
        assert result["has_signal"] is False
        assert result["sizing_modifier"] == 1.0
        assert result["stop_modifier"] == 1.0
        assert result["halt"] is False
        assert result["human_required"] is False

    def test_no_signals_returns_default(self, redis_client):
        result = check_external_signals("ES", redis_client=redis_client)
        assert result["has_signal"] is False

    def test_halt_signal_detected(self, redis_client):
        _publish_news(redis_client, "HALT", ["ES", "NQ"])
        result = check_external_signals("ES", redis_client=redis_client)
        assert result["has_signal"] is True
        assert result["halt"] is True
        assert result["sizing_modifier"] == 0.0

    def test_caution_sizing_and_stop(self, redis_client):
        _publish_news(redis_client, "CAUTION", ["ES"])
        result = check_external_signals("ES", redis_client=redis_client)
        assert result["has_signal"] is True
        assert result["halt"] is False
        assert result["sizing_modifier"] == 0.75
        assert result["stop_modifier"] == 1.25

    def test_reduce_sizing(self, redis_client):
        _publish_news(redis_client, "REDUCE", ["CL"])
        result = check_external_signals("CL", redis_client=redis_client)
        assert result["sizing_modifier"] == 0.50

    def test_irrelevant_instrument_ignored(self, redis_client):
        _publish_news(redis_client, "HALT", ["CL"])
        result = check_external_signals("ES", redis_client=redis_client)
        assert result["has_signal"] is False

    def test_worst_tier_wins(self, redis_client):
        _publish_news(redis_client, "CAUTION", ["ES"])
        _publish_news(redis_client, "HALT", ["ES"])
        result = check_external_signals("ES", redis_client=redis_client)
        assert result["tier"] == "HALT"
        assert result["halt"] is True

    def test_human_required_from_response_matrix(self, redis_client):
        _publish_news(redis_client, "HALT", ["ES"], event_type="NUCLEAR_ANY_REFERENCE")
        result = check_external_signals("ES", redis_client=redis_client)
        assert result["human_required"] is True

    def test_non_human_required_event(self, redis_client):
        _publish_news(redis_client, "CAUTION", ["ES"], event_type="NFP_STRONG")
        result = check_external_signals("ES", redis_client=redis_client)
        assert result["human_required"] is False

    def test_expired_signal_filtered(self, redis_client):
        """Signals with timestamp > duration_minutes ago are filtered by read_active_signals."""
        from datetime import datetime, timezone, timedelta
        old = (datetime.now(timezone.utc) - timedelta(minutes=60)).isoformat()
        redis_client.xadd("news_signals", {
            "source_id": "TEST",
            "headline": "Old news",
            "summary": "",
            "tier": "HALT",
            "direction": "",
            "confidence": "1.0",
            "instruments": json.dumps(["ES"]),
            "duration_minutes": "30",
            "classification": "LLM",
            "source_url": "",
            "event_type": "",
            "timestamp": old,
        })
        result = check_external_signals("ES", redis_client=redis_client)
        assert result["has_signal"] is False
