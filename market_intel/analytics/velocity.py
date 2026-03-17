"""Velocity engine — rate-of-change computation for 5m/15m/1h windows."""

from typing import List, Dict
from datetime import datetime, timedelta


def compute_velocity(price_history: List[Dict]) -> Dict:
    """
    Compute velocity metrics from price history.

    Args:
        price_history: List of {"price": float, "volume": float, "timestamp": str}
                       entries, newest last

    Returns:
        Dict with {
            "velocity_5m": float (-100 to +100),
            "velocity_15m": float (-100 to +100),
            "velocity_1h": float (-100 to +100),
            "volume_accel": float (current 5min vol / avg 5min vol over hour)
        }
    """
    if not price_history:
        return {
            "velocity_5m": 0.0,
            "velocity_15m": 0.0,
            "velocity_1h": 0.0,
            "volume_accel": 0.0,
        }

    # Parse timestamps and sort (should already be sorted newest last)
    history = []
    for entry in price_history:
        try:
            ts = datetime.fromisoformat(entry["timestamp"])
            history.append({
                "price": entry["price"],
                "volume": entry["volume"],
                "timestamp": ts,
            })
        except Exception:
            continue

    if not history:
        return {
            "velocity_5m": 0.0,
            "velocity_15m": 0.0,
            "velocity_1h": 0.0,
            "volume_accel": 0.0,
        }

    # Current time (most recent entry)
    now = history[-1]["timestamp"]
    current_price = history[-1]["price"]

    # Compute velocities
    velocity_5m = _compute_window_velocity(history, now, minutes=5, current_price=current_price, max_pct=2.0)
    velocity_15m = _compute_window_velocity(history, now, minutes=15, current_price=current_price, max_pct=5.0)
    velocity_1h = _compute_window_velocity(history, now, minutes=60, current_price=current_price, max_pct=10.0)

    # Compute volume acceleration
    volume_accel = _compute_volume_accel(history, now)

    return {
        "velocity_5m": velocity_5m,
        "velocity_15m": velocity_15m,
        "velocity_1h": velocity_1h,
        "volume_accel": volume_accel,
    }


def _compute_window_velocity(history: List[Dict], now: datetime, minutes: int, current_price: float, max_pct: float) -> float:
    """
    Compute velocity for a specific time window.

    Args:
        history: Sorted price history
        now: Current timestamp
        minutes: Window size in minutes
        current_price: Current price
        max_pct: Maximum expected percentage change for normalization

    Returns:
        Velocity score -100 to +100
    """
    window_start = now - timedelta(minutes=minutes)

    # Find first entry in window
    window_entries = [e for e in history if e["timestamp"] >= window_start]

    if not window_entries:
        return 0.0

    if len(window_entries) < 2:
        # Fall back to closest entry before window start
        earlier = [e for e in history if e["timestamp"] < window_start]
        if not earlier:
            return 0.0
        window_entries = [earlier[-1]] + window_entries

    start_price = window_entries[0]["price"]
    if start_price == 0:
        return 0.0

    # Percentage change
    pct_change = ((current_price - start_price) / start_price) * 100.0

    # Normalize to -100..+100 scale
    normalized = (pct_change / max_pct) * 100.0

    # Cap at +/-100
    return max(-100.0, min(100.0, normalized))


def _compute_volume_accel(history: List[Dict], now: datetime) -> float:
    """
    Compute volume acceleration (current 5min vol / avg 5min vol over hour).

    Args:
        history: Sorted price history
        now: Current timestamp

    Returns:
        Volume acceleration ratio (>1.5 = surging, <0.7 = dying)
    """
    # Deduplicate: keep only last entry per timestamp
    deduped = {}
    for e in history:
        deduped[e["timestamp"]] = e
    deduped_list = sorted(deduped.values(), key=lambda e: e["timestamp"])

    # Current 5-minute window volume
    window_5m = now - timedelta(minutes=5)
    recent_entries = [e for e in deduped_list if e["timestamp"] >= window_5m]
    current_vol = sum(e["volume"] for e in recent_entries)

    # Average 5-minute volume over last hour (excluding current 5min window)
    window_1h = now - timedelta(minutes=60)
    hour_entries = [e for e in deduped_list if window_1h <= e["timestamp"] < window_5m]

    if not hour_entries:
        return 0.0

    # Split into 5-minute buckets
    buckets = []
    for i in range(11):  # 11 × 5min = 55min (excluding current 5min)
        bucket_start = window_1h + timedelta(minutes=i * 5)
        bucket_end = bucket_start + timedelta(minutes=5)
        bucket_vol = sum(e["volume"] for e in hour_entries if bucket_start <= e["timestamp"] < bucket_end)
        if bucket_vol > 0:
            buckets.append(bucket_vol)

    if not buckets:
        return 0.0

    avg_vol = sum(buckets) / len(buckets)
    if avg_vol == 0:
        return 0.0

    return current_vol / avg_vol
