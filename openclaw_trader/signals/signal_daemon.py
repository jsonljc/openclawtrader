"""Main signal daemon -- asyncio loop running all collectors."""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

import redis
import yaml

_ROOT = str(Path(__file__).parent.parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from openclaw_trader.signals.rss_collector import RSSCollector
from openclaw_trader.signals.polymarket_collector import PolymarketCollector
from openclaw_trader.signals.keyword_filter import load_keywords, layer_1_filter, layer_2_check
from openclaw_trader.signals.llm_classifier import classify_headline
from openclaw_trader.signals.deduplicator import Deduplicator
from openclaw_trader.signals.signal_publisher import publish_news_signal, publish_polymarket_signal
from openclaw_trader.signals.response_matrix import ResponseMatrix
from openclaw_trader.signals import telegram_alerter

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("signal_daemon")

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")


def _load_sources() -> list[dict]:
    config_path = Path(__file__).parent.parent / "config" / "sources_tier1.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f).get("sources", [])


def _build_rss_collectors(sources: list[dict]) -> list[RSSCollector]:
    return [
        RSSCollector(
            source_id=s["source_id"],
            url=s["url"],
            poll_interval=s["poll_interval_seconds"],
            priority=s.get("priority", "MEDIUM"),
        )
        for s in sources
        if s.get("type") == "rss"
    ]


async def _run_rss_collector(
    collector: RSSCollector,
    redis_client: redis.Redis,
    dedup: Deduplicator,
    keywords: dict,
    matrix: ResponseMatrix,
    anthropic_client,
):
    logger.info(f"Starting {collector.source_id} (poll={collector.poll_interval}s)")
    while True:
        try:
            items = await collector.poll()
            for item in items:
                headline = item.get("headline", "")
                summary = item.get("summary", "")
                source_id = collector.source_id

                if dedup.is_duplicate(headline):
                    continue

                if not layer_1_filter(headline, keywords, summary=summary):
                    continue

                l2_action = layer_2_check(headline, keywords, source_id=source_id)

                if l2_action:
                    instruments = ["ES", "NQ", "CL", "GC", "ZB"]
                    publish_news_signal(
                        redis_client, source_id, headline, summary,
                        tier=l2_action, direction=None, confidence=1.0,
                        instruments=instruments, classification="KEYWORD",
                        source_url=item.get("url", ""),
                    )
                    alert_text = telegram_alerter.format_news_alert({
                        "tier": l2_action, "source_id": source_id,
                        "headline": headline, "instruments": instruments,
                    })
                    if alert_text:
                        telegram_alerter.send_message(alert_text)

                # Run LLM even after Layer 2 fires — Layer 2 publishes the
                # immediate action (HALT/CAUTION) while LLM provides a richer
                # classification that may upgrade to a DIRECTIONAL signal.
                if anthropic_client:
                    result = classify_headline(headline, summary, source_id, anthropic_client)
                    tier = result.get("tier", "MONITOR")
                    if tier != "IGNORE":
                        event_type = result.get("topic", result.get("conflict_type", ""))
                        llm_direction = result.get("direction")

                        # Map through ResponseMatrix for per-instrument actions
                        responses = matrix.get_all(event_type) if event_type else {}
                        if responses:
                            instruments = []
                            direction = llm_direction
                            for sym, resp in responses.items():
                                action = resp.get("action", "MONITOR")
                                if action in ("LONG", "SHORT", "HALT", "REDUCE"):
                                    instruments.append(sym)
                                    if action in ("LONG", "SHORT") and not direction:
                                        direction = action
                            if not instruments:
                                instruments = result.get("instruments", ["ES", "NQ", "CL", "GC", "ZB"])
                        else:
                            instruments = result.get("instruments", ["ES", "NQ", "CL", "GC", "ZB"])
                            direction = llm_direction

                        publish_news_signal(
                            redis_client, source_id, headline, summary,
                            tier=tier, direction=direction,
                            confidence=result.get("confidence", 0.5),
                            instruments=instruments, classification="LLM",
                            source_url=item.get("url", ""),
                            event_type=event_type,
                        )
                        alert_text = telegram_alerter.format_news_alert({
                            "tier": tier, "direction": direction,
                            "source_id": source_id, "headline": headline,
                            "instruments": instruments, "event_type": event_type,
                        })
                        if alert_text:
                            telegram_alerter.send_message(alert_text)

        except Exception as exc:
            logger.error(f"[{collector.source_id}] Error: {exc}")

        await asyncio.sleep(collector.poll_interval)


async def _run_polymarket(
    collector: PolymarketCollector,
    redis_client: redis.Redis,
):
    logger.info(f"Starting Polymarket (poll={collector.poll_interval}s)")
    while True:
        try:
            signals = await collector.poll()
            for signal in signals:
                publish_polymarket_signal(
                    redis_client,
                    signal_type=signal.get("type", ""),
                    market_question=signal.get("market_question", ""),
                    instruments=signal.get("instruments", []),
                    direction=signal.get("direction"),
                    strength=signal.get("strength", "MEDIUM"),
                    value_usd=signal.get("value_usd"),
                    drift_magnitude=signal.get("drift_magnitude"),
                )
                alert_text = telegram_alerter.format_polymarket_alert(signal)
                if alert_text:
                    telegram_alerter.send_message(alert_text)

        except Exception as exc:
            logger.error(f"[POLYMARKET] Error: {exc}")

        await asyncio.sleep(collector.poll_interval)


async def main():
    logger.info("Signal daemon starting")

    redis_client = redis.from_url(REDIS_URL, decode_responses=True)
    redis_client.ping()
    logger.info(f"Redis connected: {REDIS_URL}")

    telegram_alerter.init_redis(redis_client)
    keywords = load_keywords()
    matrix = ResponseMatrix()
    dedup = Deduplicator(redis_client)
    sources = _load_sources()
    rss_collectors = _build_rss_collectors(sources)
    polymarket = PolymarketCollector(poll_interval=60)

    anthropic_client = None
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if api_key:
        try:
            import anthropic
            anthropic_client = anthropic.Anthropic(api_key=api_key)
            logger.info("Anthropic client initialized (Haiku)")
        except ImportError:
            logger.warning("anthropic package not installed -- LLM classification disabled")

    telegram_alerter.send_message(
        f"Signal daemon started\n"
        f"Sources: {len(rss_collectors)} RSS + Polymarket\n"
        f"LLM: {'enabled' if anthropic_client else 'disabled'}"
    )

    tasks = []
    for collector in rss_collectors:
        tasks.append(
            asyncio.create_task(
                _run_rss_collector(collector, redis_client, dedup, keywords, matrix, anthropic_client)
            )
        )
    tasks.append(asyncio.create_task(_run_polymarket(polymarket, redis_client)))

    logger.info(f"Running {len(tasks)} collector tasks")
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Signal daemon stopped")
