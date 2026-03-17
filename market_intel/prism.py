"""Prism — Market Intel daemon. Polls IB, computes analytics, publishes conviction to Redis."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_MI_ROOT = Path(__file__).parent
if str(_MI_ROOT) not in sys.path:
    sys.path.insert(0, str(_MI_ROOT))

# Optional imports — daemon degrades gracefully
try:
    import redis as _redis_mod
    _HAS_REDIS = True
except ImportError:
    _HAS_REDIS = False

try:
    from ib_insync import IB
    _HAS_IB = True
except ImportError:
    _HAS_IB = False

# Symbols for options rotation
_OPTIONS_SYMBOLS = ["ES", "NQ", "CL"]
_CORE_SYMBOLS = ["ES", "NQ", "CL", "GC", "ZB"]


class PrismDaemon:
    """Market intel daemon orchestrator."""

    def __init__(
        self,
        ib_host: str = "127.0.0.1",
        ib_port: int = 4002,
        ib_client_id: int = 10,
        redis_url: str = "redis://localhost:6379",
    ):
        self.ib_host = ib_host
        self.ib_port = ib_port
        self.ib_client_id = ib_client_id
        self.redis_url = redis_url

        self._ib: Any = None
        self._rc: Any = None
        self._dm: Any = None  # IBDataManager instance
        self._running = False
        self._options_index = 0  # rotation index for options subscriptions
        self._ib_connected = False

    async def start(self) -> None:
        """Connect IB + Redis and start all polling loops."""
        self._running = True

        # Connect Redis
        if _HAS_REDIS:
            try:
                self._rc = _redis_mod.from_url(self.redis_url, decode_responses=True)
                self._rc.ping()
                logger.info("Redis connected: %s", self.redis_url)
            except Exception as exc:
                logger.warning("Redis connection failed: %s — continuing without publish", exc)
                self._rc = None

        # Connect IB
        if _HAS_IB:
            try:
                self._ib = IB()
                await self._ib.connectAsync(self.ib_host, self.ib_port, clientId=self.ib_client_id)
                self._ib_connected = True
                self._ib.disconnectedEvent += self._on_ib_disconnect
                logger.info("IB connected: %s:%d (client %d)", self.ib_host, self.ib_port, self.ib_client_id)
            except Exception as exc:
                logger.warning("IB connection failed: %s — running with stale data", exc)
                self._ib = None
                self._ib_connected = False

        # Create data manager
        try:
            from data_layer import IBDataManager
            self._dm = IBDataManager(ib=self._ib, redis_client=self._rc)
            logger.info("IBDataManager initialised")
        except ImportError:
            logger.warning("data_layer not importable — no polling")

        # Start polling tasks
        tasks = [
            asyncio.create_task(self._run_quote_poller(), name="quote_poller"),
            asyncio.create_task(self._run_cross_poller(), name="cross_poller"),
            asyncio.create_task(self._run_options_poller(), name="options_poller"),
            asyncio.create_task(self._run_analytics_cycle(), name="analytics"),
            asyncio.create_task(self._run_conviction_cycle(), name="conviction"),
        ]

        logger.info("Prism daemon started — %d polling tasks", len(tasks))
        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            logger.info("Prism daemon tasks cancelled")

    async def stop(self) -> None:
        """Disconnect IB and clean up."""
        self._running = False
        if self._ib and self._ib_connected:
            try:
                self._ib.disconnect()
                logger.info("IB disconnected")
            except Exception:
                pass
        self._ib = None
        self._ib_connected = False
        self._rc = None
        logger.info("Prism daemon stopped")

    def _on_ib_disconnect(self) -> None:
        """Handle unexpected IB disconnection."""
        logger.warning("IB disconnected unexpectedly — data will be marked stale")
        self._ib_connected = False

    async def _run_quote_poller(self) -> None:
        """Poll core futures quotes every 5 seconds."""
        while self._running:
            try:
                if self._ib_connected and self._ib:
                    await self._poll_quotes()
            except Exception as exc:
                logger.error("Quote poll error: %s", exc)
            await asyncio.sleep(5)

    async def _run_cross_poller(self) -> None:
        """Poll cross-market data every 10 seconds."""
        while self._running:
            try:
                if self._ib_connected and self._ib:
                    await self._poll_cross_market()
            except Exception as exc:
                logger.error("Cross-market poll error: %s", exc)
            await asyncio.sleep(10)

    async def _run_options_poller(self) -> None:
        """Poll options chains every 60 seconds, rotating symbols."""
        while self._running:
            try:
                if self._ib_connected and self._ib:
                    sym = _OPTIONS_SYMBOLS[self._options_index % len(_OPTIONS_SYMBOLS)]
                    await self._poll_options(sym)
                    self._options_index += 1
            except Exception as exc:
                logger.error("Options poll error: %s", exc)
            await asyncio.sleep(60)

    async def _run_analytics_cycle(self) -> None:
        """Run all analytics engines every 10 seconds."""
        while self._running:
            try:
                await self._compute_analytics()
            except Exception as exc:
                logger.error("Analytics cycle error: %s", exc)
            await asyncio.sleep(10)

    async def _run_conviction_cycle(self) -> None:
        """Run conviction scorer every 10 seconds (after analytics)."""
        await asyncio.sleep(2)
        while self._running:
            try:
                await self._compute_conviction()
            except Exception as exc:
                logger.error("Conviction cycle error: %s", exc)
            await asyncio.sleep(10)

    async def _poll_quotes(self) -> None:
        """Poll quotes for core futures via IBDataManager."""
        if not self._dm:
            return
        self._dm.poll_quotes(_CORE_SYMBOLS)

    async def _poll_cross_market(self) -> None:
        """Poll cross-market symbols via IBDataManager."""
        if not self._dm:
            return
        self._dm.poll_cross_market(["VIX", "DXY", "TNX", "HYG", "XLF"])

    async def _poll_options(self, symbol: str) -> None:
        """Poll options chain for a single symbol via IBDataManager."""
        if not self._dm:
            return
        self._dm.poll_options(symbol)

    async def _compute_analytics(self) -> None:
        """Run all analytics engines and publish results to Redis."""
        try:
            from analytics.velocity import compute_velocity
            from analytics.divergence import compute_divergences
        except ImportError:
            return

        for sym in _CORE_SYMBOLS:
            analytics = {}
            try:
                if self._rc:
                    raw = self._rc.get(f"market_intel:quotes:{sym}")
                    if raw:
                        analytics["velocity"] = compute_velocity(json.loads(raw))
            except Exception:
                pass

            if self._rc and analytics:
                self._rc.set(
                    f"market_intel:analytics:{sym}",
                    json.dumps(analytics),
                    ex=30,
                )

    async def _compute_conviction(self) -> None:
        """Run conviction scorer for all symbols and publish to Redis."""
        try:
            from conviction.scorer import compute_conviction
        except ImportError:
            return

        for sym in _CORE_SYMBOLS:
            try:
                analytics_raw = self._rc.get(f"market_intel:analytics:{sym}") if self._rc else None
                analytics = json.loads(analytics_raw) if analytics_raw else {}
                now = datetime.now(timezone.utc)
                conviction = compute_conviction(
                    analytics=analytics,
                    regime="NEUTRAL",
                    hour=now.hour,
                    minute=now.minute,
                    patterns_config=[],
                    weights_config={},
                )
                if self._rc and conviction:
                    self._rc.set(
                        f"market_intel:conviction:{sym}",
                        json.dumps(conviction),
                        ex=30,
                    )
            except Exception as exc:
                logger.debug("Conviction compute failed for %s: %s", sym, exc)

    async def _poll_cycle(self) -> None:
        """Run one full cycle: poll data, compute analytics, compute conviction.

        Primarily used for testing.
        """
        if self._ib_connected and self._ib:
            await self._poll_quotes()
            await self._poll_cross_market()
        await self._compute_analytics()
        await self._compute_conviction()


def main() -> None:
    """Entry point — reads config from env vars and runs the daemon."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    ib_host = os.environ.get("IB_HOST", "127.0.0.1")
    ib_port = int(os.environ.get("IB_PORT", "4002"))
    ib_client_id = int(os.environ.get("IB_CLIENT_ID", "10"))
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")

    daemon = PrismDaemon(
        ib_host=ib_host,
        ib_port=ib_port,
        ib_client_id=ib_client_id,
        redis_url=redis_url,
    )

    loop = asyncio.new_event_loop()

    def _shutdown(sig, frame):
        logger.info("Received signal %s — shutting down", sig)
        loop.create_task(daemon.stop())

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    try:
        loop.run_until_complete(daemon.start())
    except KeyboardInterrupt:
        loop.run_until_complete(daemon.stop())
    finally:
        loop.close()


if __name__ == "__main__":
    main()
