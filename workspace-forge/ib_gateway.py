#!/usr/bin/env python3
"""IB Gateway connection manager.

Manages the IB TWS/Gateway connection lifecycle using ib_insync.
Reused by both the data adapter (data_ib.py) and execution adapter (ib_broker.py).

Port conventions:
    4001 = TWS/Gateway live
    4002 = TWS/Gateway paper (default)

Env vars:
    OPENCLAW_IB_HOST      (default: 127.0.0.1)
    OPENCLAW_IB_PORT      (default: 4002 — paper trading)
    OPENCLAW_IB_CLIENT_ID (default: 1)
"""

from __future__ import annotations

import logging
import os
import time

logger = logging.getLogger(__name__)

# Singleton connection
_ib_instance = None


def _get_config() -> tuple[str, int, int]:
    """Read IB connection parameters from environment."""
    host = os.environ.get("OPENCLAW_IB_HOST", "127.0.0.1")
    port = int(os.environ.get("OPENCLAW_IB_PORT", "4002"))
    client_id = int(os.environ.get("OPENCLAW_IB_CLIENT_ID", "1"))
    return host, port, client_id


def connect(host: str = None, port: int = None, client_id: int = None):
    """
    Connect to IB Gateway/TWS and return the IB instance.

    Args:
        host:      Override OPENCLAW_IB_HOST (default: 127.0.0.1)
        port:      Override OPENCLAW_IB_PORT (default: 4002 for paper)
        client_id: Override OPENCLAW_IB_CLIENT_ID (default: 1)

    Returns:
        ib_insync.IB instance (connected)
    """
    from ib_insync import IB

    env_host, env_port, env_client_id = _get_config()
    host = host or env_host
    port = port or env_port
    client_id = client_id if client_id is not None else env_client_id

    ib = IB()
    ib.connect(host, port, clientId=client_id)
    logger.info("Connected to IB at %s:%d (clientId=%d)", host, port, client_id)
    return ib


def disconnect() -> None:
    """Disconnect the singleton IB instance if connected."""
    global _ib_instance
    if _ib_instance is not None:
        try:
            if _ib_instance.isConnected():
                _ib_instance.disconnect()
                logger.info("Disconnected from IB")
        except Exception as exc:
            logger.warning("Error during disconnect: %s", exc)
        _ib_instance = None


def is_connected() -> bool:
    """Check if the singleton IB instance is connected."""
    global _ib_instance
    if _ib_instance is None:
        return False
    try:
        return _ib_instance.isConnected()
    except Exception:
        return False


def reconnect(max_retries: int = 3):
    """
    Disconnect and reconnect with retries.

    Returns:
        ib_insync.IB instance (connected)

    Raises:
        ConnectionError: If all retries fail.
    """
    global _ib_instance
    disconnect()

    host, port, client_id = _get_config()
    last_exc = None

    for attempt in range(1, max_retries + 1):
        try:
            _ib_instance = connect(host, port, client_id)
            logger.info("Reconnected on attempt %d/%d", attempt, max_retries)
            return _ib_instance
        except Exception as exc:
            last_exc = exc
            logger.warning("Reconnect attempt %d/%d failed: %s", attempt, max_retries, exc)
            if attempt < max_retries:
                time.sleep(2 * attempt)

    raise ConnectionError(
        f"Failed to reconnect to IB after {max_retries} attempts: {last_exc}"
    )


def get_connection():
    """
    Get the singleton IB connection, auto-connecting/reconnecting as needed.

    Returns:
        ib_insync.IB instance (connected)
    """
    global _ib_instance
    if _ib_instance is not None and is_connected():
        return _ib_instance

    if _ib_instance is not None:
        logger.warning("IB connection lost — attempting reconnect")
        return reconnect()

    # First connection
    host, port, client_id = _get_config()
    _ib_instance = connect(host, port, client_id)
    return _ib_instance
