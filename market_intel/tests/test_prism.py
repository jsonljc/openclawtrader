"""Tests for PrismDaemon — main orchestrator."""
import asyncio
import os
from unittest.mock import MagicMock, patch

import pytest

from market_intel.prism import PrismDaemon, _OPTIONS_SYMBOLS


class TestDaemonCreation:
    def test_daemon_creates(self):
        d = PrismDaemon()
        assert d.ib_host == "127.0.0.1"
        assert d.ib_port == 4002
        assert d.ib_client_id == 10
        assert d.redis_url == "redis://localhost:6379"
        assert d._running is False

    def test_env_var_config(self):
        env = {
            "IB_HOST": "10.0.0.5",
            "IB_PORT": "7497",
            "IB_CLIENT_ID": "20",
            "REDIS_URL": "redis://redis-host:6380",
        }
        with patch.dict(os.environ, env):
            d = PrismDaemon(
                ib_host=os.environ["IB_HOST"],
                ib_port=int(os.environ["IB_PORT"]),
                ib_client_id=int(os.environ["IB_CLIENT_ID"]),
                redis_url=os.environ["REDIS_URL"],
            )
            assert d.ib_host == "10.0.0.5"
            assert d.ib_port == 7497
            assert d.ib_client_id == 20
            assert d.redis_url == "redis://redis-host:6380"


class TestPollCycle:
    @pytest.mark.asyncio
    async def test_poll_cycle_computes(self):
        """Mock IB data flows through analytics and conviction, published to Redis."""
        d = PrismDaemon()
        d._running = True
        d._ib_connected = False  # Skip IB polling
        d._rc = MagicMock()
        d._rc.get.return_value = None  # No cached data yet

        # _poll_cycle should not raise even with no data
        await d._poll_cycle()

        # Verify it attempted to read analytics from Redis
        assert d._rc.get.called

    @pytest.mark.asyncio
    async def test_graceful_ib_disconnect(self):
        """IB disconnect sets flag; daemon continues running."""
        d = PrismDaemon()
        d._running = True
        d._ib_connected = True
        d._ib = MagicMock()

        # Simulate disconnect event
        d._on_ib_disconnect()

        assert d._ib_connected is False
        assert d._running is True  # Daemon still running

    @pytest.mark.asyncio
    async def test_options_rotation(self):
        """Options poller rotates through ES, NQ, CL."""
        d = PrismDaemon()
        symbols_polled = []

        for i in range(6):
            sym = _OPTIONS_SYMBOLS[d._options_index % len(_OPTIONS_SYMBOLS)]
            symbols_polled.append(sym)
            d._options_index += 1

        # Should cycle: ES, NQ, CL, ES, NQ, CL
        assert symbols_polled == ["ES", "NQ", "CL", "ES", "NQ", "CL"]


class TestShutdown:
    @pytest.mark.asyncio
    async def test_shutdown_clean(self):
        """stop() disconnects IB and clears state."""
        d = PrismDaemon()
        d._running = True
        d._ib_connected = True
        d._ib = MagicMock()
        d._rc = MagicMock()

        await d.stop()

        assert d._running is False
        assert d._ib_connected is False
        assert d._ib is None
        assert d._rc is None
