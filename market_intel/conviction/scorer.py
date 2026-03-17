"""Conviction scorer: pattern match → weighted fallback → TOD → clarity.

Produces per-instrument directional conviction scores.
Pure functions — no IB or Redis dependency.
"""
from __future__ import annotations

from datetime import datetime, timezone

from market_intel.analytics.volume_profile import get_tod_quality
from market_intel.analytics.regime_transition import detect_regime_transition
from market_intel.conviction.pattern_matcher import match_pattern


# Factor names used in weighted fallback (must match keys in weights config and analytics dict)
_FACTOR_NAMES = [
    "velocity_alignment",
    "divergence_score",
    "gex_tailwind",
    "options_flow",
    "signal_integration",
    "relative_volume",
]


def compute_conviction(
    analytics: dict,
    regime: str,
    hour: int,
    minute: int,
    patterns_config: list[dict],
    weights_config: dict,
) -> dict:
    """Compute directional conviction scores for an instrument.

    Logic:
    1. Try pattern matcher. If match -> use pattern's base_score and direction.
    2. If no match -> weighted fallback using regime-specific weights.
    3. Apply time-of-day modifier.
    4. Compute clarity from factor agreement.
    5. Compute long_conviction, short_conviction, hold_conviction.

    Args:
        analytics: Dict of current analytics values.
        regime: Current regime type ("TRENDING", "VOLATILE", "NEUTRAL").
        hour: Current hour (ET).
        minute: Current minute.
        patterns_config: List of pattern dicts for pattern_matcher.
        weights_config: Dict of regime -> factor weights.

    Returns:
        Conviction output dict per design doc Section 4.5.
    """
    tod_modifier = get_tod_quality(hour, minute)
    now_iso = datetime.now(timezone.utc).isoformat()

    # Step 1: Try pattern match
    matched = match_pattern(analytics, patterns_config)

    if matched is not None:
        long_raw, short_raw = _scores_from_pattern(matched)
        clarity = matched["confidence"]
        top_factors = [f"pattern:{matched['name']}"]
        opposing_factors: list[str] = []
    else:
        # Step 2: Weighted fallback
        regime_weights = weights_config.get(regime, weights_config.get("NEUTRAL", {}))
        long_raw, short_raw, top_factors, opposing_factors = _weighted_fallback(
            analytics, regime_weights
        )
        clarity = _compute_clarity(analytics, _FACTOR_NAMES)

    # Step 3: Apply TOD modifier
    long_score = int(max(0, min(100, long_raw * tod_modifier)))
    short_score = int(max(0, min(100, short_raw * tod_modifier)))

    # Step 5: Hold conviction = average, biased toward the dominant direction
    if long_score >= short_score:
        hold_score = int((long_score * 0.7 + short_score * 0.3))
    else:
        hold_score = int((short_score * 0.7 + long_score * 0.3))
    hold_score = max(0, min(100, hold_score))

    # Regime transition info
    regime_history = analytics.get("regime_history", [])
    if isinstance(regime_history, list) and len(regime_history) >= 3:
        regime_transition = detect_regime_transition(regime_history)
    else:
        regime_transition = {"detected": False, "from_regime": None, "to_regime": None, "confidence": 0.0}

    return {
        "long_conviction": long_score,
        "short_conviction": short_score,
        "hold_conviction": hold_score,
        "clarity": clarity,
        "matched_pattern": matched["name"] if matched else None,
        "regime_transition": regime_transition,
        "top_factors": top_factors,
        "opposing_factors": opposing_factors,
        "relative_volume": analytics.get("relative_volume", 0.0),
        "timestamp": now_iso,
    }


def _scores_from_pattern(matched: dict) -> tuple[float, float]:
    """Convert a matched pattern to long/short raw scores."""
    score = matched["base_score"]
    direction = matched["direction"]

    if direction == "LONG":
        return float(score), float(max(0, 100 - score))
    elif direction == "SHORT":
        return float(max(0, 100 - score)), float(score)
    else:
        # NEUTRAL or BOTH — equal low conviction both ways
        return float(score), float(score)


def _weighted_fallback(
    analytics: dict, regime_weights: dict
) -> tuple[float, float, list[str], list[str]]:
    """Compute conviction from weighted factor sum.

    Each factor value in analytics is expected to be a float:
      - Positive values indicate LONG bias
      - Negative values indicate SHORT bias
      - Magnitude indicates strength (0-100 scale)

    Returns:
        (long_raw, short_raw, top_factors, opposing_factors)
    """
    long_sum = 0.0
    short_sum = 0.0
    top_factors: list[str] = []
    opposing_factors: list[str] = []

    for factor_name in _FACTOR_NAMES:
        weight = regime_weights.get(factor_name, 0.0)
        value = analytics.get(factor_name, 0.0)

        if not isinstance(value, (int, float)):
            continue

        weighted = abs(value) * weight

        if value > 0:
            long_sum += weighted
            if abs(value) > 20:
                top_factors.append(f"{factor_name}_long")
        elif value < 0:
            short_sum += weighted
            if abs(value) > 20:
                top_factors.append(f"{factor_name}_short")

    return long_sum, short_sum, top_factors, opposing_factors


def _compute_clarity(analytics: dict, factor_names: list[str]) -> str:
    """Compute clarity based on factor agreement.

    HIGH: >70% of factors agree on direction
    MEDIUM: 50-70% agreement
    LOW: <50% agreement
    """
    positive = 0
    negative = 0
    total = 0

    for name in factor_names:
        val = analytics.get(name, 0.0)
        if not isinstance(val, (int, float)):
            continue
        if val == 0.0:
            continue
        total += 1
        if val > 0:
            positive += 1
        else:
            negative += 1

    if total == 0:
        return "LOW"

    dominant = max(positive, negative)
    agreement = dominant / total

    if agreement > 0.70:
        return "HIGH"
    elif agreement > 0.50:
        return "MEDIUM"
    else:
        return "LOW"
