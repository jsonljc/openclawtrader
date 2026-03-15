"""NEWS_DIRECTIONAL setup scanner -- generates trade candidates from news signals."""
from __future__ import annotations

from typing import Any


def detect(
    regime: dict,
    session: dict,
    structure: dict | None,
    bars_5m: list[dict],
    snapshot: dict,
    strategy: dict,
    signals: list[dict] | None = None,
    traded_signal_ids: set | None = None,
) -> dict[str, Any] | None:
    """Scan for a NEWS_DIRECTIONAL setup.

    Args:
        signals: list of active DIRECTIONAL signals from Redis (pre-filtered to this instrument)
        traded_signal_ids: set of signal_ids already traded this session

    Returns SetupCandidate dict or None.
    """
    if not signals or not bars_5m:
        return None

    traded = traded_signal_ids or set()

    # Session gate: must be RTH
    if not session.get("is_rth", False):
        return None

    # Session gate: no entries within 30 min of close (MOC_CLOSE)
    session_name = session.get("session", "CLOSED")
    if session_name == "MOC_CLOSE":
        return None

    # Session gate: no entries in first 2 min
    minutes_in = session.get("minutes_into_session", 0)
    if minutes_in < 2:
        return None

    atr = snapshot.get("indicators", {}).get("atr_14_1H", 0)
    if atr <= 0:
        atr = snapshot.get("indicators", {}).get("atr_14_4H", 10.0)

    for signal in signals:
        signal_id = signal.get("signal_id", "")
        if signal_id in traded:
            continue

        direction = signal.get("direction", "")
        if direction not in ("LONG", "SHORT"):
            continue

        confirm_bars_needed = signal.get("confirm_bars", 1)

        # Check we have enough bars for confirmation
        if len(bars_5m) < 20 + confirm_bars_needed:
            continue

        # Volume average from first 20 bars
        vol_avg = sum(b.get("v", 0) for b in bars_5m[:20]) / 20.0

        # Check confirmation bars
        confirm_slice = bars_5m[-(confirm_bars_needed):]
        confirmed = True
        for bar in confirm_slice:
            bar_open = bar.get("o", 0)
            bar_close = bar.get("c", 0)
            bar_high = bar.get("h", 0)
            bar_low = bar.get("l", 0)
            bar_vol = bar.get("v", 0)
            bar_range = bar_high - bar_low
            bar_body = abs(bar_close - bar_open)

            # Body must be > 30% of range
            if bar_range > 0 and bar_body / bar_range < 0.30:
                confirmed = False
                break

            # Volume must be above 20-bar average
            if bar_vol < vol_avg:
                confirmed = False
                break

            # Bar must close in expected direction
            if direction == "LONG" and bar_close <= bar_open:
                confirmed = False
                break
            if direction == "SHORT" and bar_close >= bar_open:
                confirmed = False
                break

        if not confirmed:
            continue

        # Build SetupCandidate
        last_bar = bars_5m[-1]
        entry_price = last_bar.get("c", 0)
        stop_distance = 0.75 * atr
        tick_size = strategy.get("tick_size", 0.25)

        if direction == "LONG":
            stop_price = entry_price - stop_distance
            target_price = entry_price + (1.5 * stop_distance)
        else:
            stop_price = entry_price + stop_distance
            target_price = entry_price - (1.5 * stop_distance)

        def _round_tick(price: float) -> float:
            if tick_size > 0:
                return round(round(price / tick_size) * tick_size, 6)
            return price

        return {
            "side": direction,
            "entry_price": _round_tick(entry_price),
            "stop_price": _round_tick(stop_price),
            "target_price": _round_tick(target_price),
            "setup_family": "NEWS_DIRECTIONAL",
            "sizing_modifier": 0.5,
            "signal_id": signal_id,
            "event_type": signal.get("event_type", ""),
            "metadata": {
                "source_id": signal.get("source_id", ""),
                "headline": signal.get("headline", ""),
                "confirm_bars": confirm_bars_needed,
                "atr": atr,
                "stop_distance": stop_distance,
            },
        }

    return None
