"""Regime transition detector: detects when regime score is accelerating toward a boundary.

Pure functions — no IB or Redis dependency.
"""
from __future__ import annotations

# Regime boundaries (consistent with brain.py regime classification)
_TRENDING_THRESHOLD = 70
_VOLATILE_THRESHOLD = 70  # on the volatile axis; here we use score direction
_NEUTRAL_UPPER = 65       # below this = NEUTRAL


def detect_regime_transition(regime_history: list[dict]) -> dict:
    """Detect if regime score is accelerating toward a regime boundary.

    Args:
        regime_history: Recent regime entries, oldest first.
            Each: {"score": int, "regime_type": str, "timestamp": str}

    Returns:
        {"detected": bool, "from_regime": str|None, "to_regime": str|None, "confidence": float}
    """
    no_transition = {
        "detected": False,
        "from_regime": None,
        "to_regime": None,
        "confidence": 0.0,
    }

    if len(regime_history) < 3:
        return no_transition

    scores = [entry["score"] for entry in regime_history]
    current_regime = regime_history[-1]["regime_type"]

    # Compute velocity (first derivative) and acceleration (second derivative)
    deltas = [scores[i + 1] - scores[i] for i in range(len(scores) - 1)]

    # Average velocity over recent points
    avg_velocity = sum(deltas) / len(deltas)

    # Check acceleration: is the velocity increasing?
    if len(deltas) >= 2:
        accel = deltas[-1] - deltas[0]
    else:
        accel = 0.0

    # Project where score is heading
    latest_score = scores[-1]
    projected_score = latest_score + avg_velocity * 2  # project 2 intervals ahead

    # Determine if crossing a boundary
    target_regime = _classify_score(projected_score)

    if target_regime == current_regime:
        return no_transition

    # Must have consistent directional movement (not oscillating)
    if avg_velocity > 0 and projected_score <= latest_score:
        return no_transition
    if avg_velocity < 0 and projected_score >= latest_score:
        return no_transition

    # Require meaningful velocity (not just noise)
    if abs(avg_velocity) < 3.0:
        return no_transition

    # Confidence based on velocity magnitude and acceleration agreement
    velocity_factor = min(abs(avg_velocity) / 15.0, 1.0)
    accel_factor = 1.0 if (accel > 0 and avg_velocity > 0) or (accel < 0 and avg_velocity < 0) else 0.5
    confidence = round(velocity_factor * accel_factor, 2)

    return {
        "detected": True,
        "from_regime": current_regime,
        "to_regime": target_regime,
        "confidence": confidence,
    }


def _classify_score(score: float) -> str:
    """Classify a regime score into a regime type."""
    if score >= _TRENDING_THRESHOLD:
        return "TRENDING"
    if score <= 100 - _TRENDING_THRESHOLD:  # low scores = VOLATILE
        return "VOLATILE"
    return "NEUTRAL"
