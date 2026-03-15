"""Load and query the NEWS_RESPONSE_MAP for per-instrument actions."""
from __future__ import annotations

from pathlib import Path

import yaml

_CONFIG_DIR = Path(__file__).parent.parent / "config"
_DEFAULT_RESPONSE = {"action": "MONITOR"}


class ResponseMatrix:
    """Lookup event type + instrument -> response action."""

    def __init__(self, path: Path | None = None):
        p = path or (_CONFIG_DIR / "NEWS_RESPONSE_MAP.yaml")
        with open(p) as f:
            self._map: dict = yaml.safe_load(f) or {}

    def events(self) -> list[str]:
        return list(self._map.keys())

    def get(self, event_type: str, instrument: str) -> dict:
        """Return response dict for event + instrument. Defaults to MONITOR."""
        event = self._map.get(event_type)
        if event is None:
            return dict(_DEFAULT_RESPONSE)
        resp = event.get(instrument)
        if resp is None:
            return dict(_DEFAULT_RESPONSE)
        return dict(resp)

    def get_all(self, event_type: str) -> dict[str, dict]:
        """Return response dict for all instruments on an event."""
        event = self._map.get(event_type, {})
        return {sym: dict(resp) for sym, resp in event.items()}
