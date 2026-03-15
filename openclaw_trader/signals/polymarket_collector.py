"""Polymarket API collector with drift and anomaly detection."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Any

import aiohttp

from openclaw_trader.signals.base_collector import BaseCollector

logger = logging.getLogger(__name__)

API_URL = "https://gamma-api.polymarket.com/markets"

INSTRUMENT_KEYWORDS = {
    "ES": ["fed rate", "federal reserve", "recession", "gdp", "inflation", "cpi", "s&p", "spx"],
    "NQ": ["fed rate", "nasdaq", "tech", "semiconductor", "nvidia", "apple"],
    "CL": ["oil price", "crude", "opec", "iran", "saudi", "energy"],
    "GC": ["gold price", "inflation", "fed rate", "dollar"],
    "ZB": ["fed rate", "treasury", "yield", "interest rate", "debt ceiling"],
}

DRIFT_THRESHOLD_PP = 15.0
DRIFT_HIGH_PP = 25.0
LIQUIDITY_SPIKE_USD = 25_000
LIQUIDITY_HIGH_USD = 100_000


def detect_drift(
    snapshots: list[dict],
    current_prob: float,
) -> dict[str, Any] | None:
    if not snapshots:
        return None
    oldest_prob = snapshots[0].get("probability", current_prob)
    drift_pp = (current_prob - oldest_prob) * 100.0
    if abs(drift_pp) < DRIFT_THRESHOLD_PP:
        return None
    strength = "HIGH" if abs(drift_pp) >= DRIFT_HIGH_PP else "MEDIUM"
    return {
        "drift_magnitude": round(drift_pp, 1),
        "strength": strength,
        "oldest_prob": oldest_prob,
        "current_prob": current_prob,
    }


def detect_liquidity_spike(
    previous_liquidity: float,
    current_liquidity: float,
) -> dict[str, Any] | None:
    delta = current_liquidity - previous_liquidity
    if delta < LIQUIDITY_SPIKE_USD:
        return None
    strength = "HIGH" if delta >= LIQUIDITY_HIGH_USD else "MEDIUM"
    return {
        "delta_usd": round(delta, 2),
        "strength": strength,
    }


def compute_regime_confidence_mod(
    signals: list[dict],
    instrument: str,
    current_direction: str | None = None,
) -> float:
    high_for_instrument = [
        s for s in signals
        if s.get("strength") == "HIGH" and instrument in s.get("instruments", [])
    ]
    if len(high_for_instrument) < 2:
        return 1.0
    directions = [s.get("direction") for s in high_for_instrument]
    most_common = max(set(directions), key=directions.count)
    count = directions.count(most_common)
    if count < 2:
        return 1.0
    if current_direction and most_common != current_direction:
        return 0.8
    return 1.2


def match_instruments(question: str) -> list[str]:
    q_lower = question.lower()
    matched = []
    for instrument, keywords in INSTRUMENT_KEYWORDS.items():
        if any(kw in q_lower for kw in keywords):
            matched.append(instrument)
    return matched or ["ES"]


class PolymarketCollector(BaseCollector):
    def __init__(self, poll_interval: int = 60):
        super().__init__("POLYMARKET_MONITOR", poll_interval, "MEDIUM")
        self._snapshots: dict[str, list[dict]] = {}
        self._prev_liquidity: dict[str, float] = {}

    async def poll(self) -> list[dict[str, Any]]:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(API_URL, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status != 200:
                        logger.warning(f"[POLYMARKET] HTTP {resp.status}")
                        return []
                    markets = await resp.json()
        except Exception as exc:
            logger.error(f"[POLYMARKET] Fetch failed: {exc}")
            return []

        signals = []
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=4)

        for market in (markets if isinstance(markets, list) else []):
            question = market.get("question", "")
            instruments = match_instruments(question)
            if not instruments:
                continue

            market_id = market.get("id", "")
            current_prob = float(market.get("outcomePrices", [0.5])[0] if isinstance(market.get("outcomePrices"), list) else 0.5)
            current_liquidity = float(market.get("liquidity", 0) or 0)

            if market_id not in self._snapshots:
                self._snapshots[market_id] = []
            self._snapshots[market_id].append({
                "probability": current_prob,
                "timestamp": now.isoformat(),
            })
            self._snapshots[market_id] = [
                s for s in self._snapshots[market_id]
                if datetime.fromisoformat(s["timestamp"]) > cutoff
            ]

            drift = detect_drift(self._snapshots[market_id], current_prob)
            if drift:
                signals.append({
                    "type": "PROBABILITY_DRIFT",
                    "market_question": question,
                    "instruments": instruments,
                    "direction": "YES" if drift["drift_magnitude"] > 0 else "NO",
                    "strength": drift["strength"],
                    "drift_magnitude": drift["drift_magnitude"],
                    "source_id": self.source_id,
                })

            prev_liq = self._prev_liquidity.get(market_id, current_liquidity)
            spike = detect_liquidity_spike(prev_liq, current_liquidity)
            if spike:
                signals.append({
                    "type": "LIQUIDITY_SPIKE",
                    "market_question": question,
                    "instruments": instruments,
                    "direction": None,
                    "strength": spike["strength"],
                    "value_usd": spike["delta_usd"],
                    "source_id": self.source_id,
                })
            self._prev_liquidity[market_id] = current_liquidity

        return signals

    def parse(self, raw_item: dict[str, Any]) -> dict[str, Any]:
        return raw_item
