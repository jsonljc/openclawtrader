#!/usr/bin/env python3
"""Opportunity Scorer — simplified 3-dimension scoring for intraday setups.

Dimensions:
    1. Regime alignment (0-35)   — how well does the regime support this setup?
    2. R:R ratio (0-35)          — reward-to-risk quality
    3. Structure confluence (0-30) — how many key levels support the trade?

Minimum score: 50 to pass to Sentinel.
"""

from __future__ import annotations

from typing import Any

from regime_intraday import IntradayRegime, is_setup_compatible


def _regime_score(candidate: dict, regime: dict) -> tuple[int, dict]:
    """
    Regime alignment score (0-35).
    Full marks if setup is compatible and regime confidence is high.
    """
    setup_family = candidate.get("setup_family", "")
    regime_type = regime.get("regime_type", IntradayRegime.NEUTRAL)
    confidence = regime.get("confidence", 0.5)

    if not is_setup_compatible(setup_family, regime_type):
        return 0, {"compatible": False, "regime_type": regime_type}

    # Base 20 for compatibility, up to 15 more for high confidence
    score = 20 + int(15 * min(1.0, confidence))
    score = min(35, score)

    return score, {
        "compatible": True,
        "regime_type": regime_type,
        "confidence": round(confidence, 3),
    }


def _rr_score(candidate: dict) -> tuple[int, dict]:
    """
    Reward:Risk ratio score (0-35).
    R:R < 1.0 = 0, R:R = 1.5 = 20, R:R = 2.0 = 25, R:R >= 3.0 = 35.
    """
    entry = candidate.get("entry_price", 0.0)
    stop = candidate.get("stop_price", 0.0)
    target = candidate.get("target_price", 0.0)

    risk = abs(entry - stop)
    reward = abs(target - entry)

    if risk <= 0:
        return 0, {"rr_ratio": 0.0}

    rr = reward / risk

    if rr < 1.0:
        score = 0
    elif rr < 1.5:
        score = int(20 * (rr - 1.0) / 0.5)
    elif rr < 2.0:
        score = 20 + int(5 * (rr - 1.5) / 0.5)
    elif rr < 3.0:
        score = 25 + int(10 * (rr - 2.0) / 1.0)
    else:
        score = 35

    score = min(35, max(0, score))

    return score, {"rr_ratio": round(rr, 3), "risk_pts": round(risk, 2), "reward_pts": round(reward, 2)}


def _structure_score(candidate: dict, structure: dict | None) -> tuple[int, dict]:
    """
    Structure confluence score (0-30).
    How many key structural levels support this trade?

    For LONG: support levels nearby (VWAP, prior day low, OR low, overnight low)
    For SHORT: resistance levels nearby (VWAP, prior day high, OR high, overnight high)
    """
    if not structure:
        return 10, {"confluence_count": 0, "note": "no structure data"}

    side = candidate.get("side", "BUY")
    entry = candidate.get("entry_price", 0.0)
    stop = candidate.get("stop_price", 0.0)
    risk = abs(entry - stop)

    if risk <= 0:
        return 0, {"confluence_count": 0}

    # Define proximity threshold: within 0.5 × risk distance
    proximity = risk * 0.5

    # Levels that act as support (for longs) or resistance (for shorts)
    confluence_count = 0
    supporting_levels: list[str] = []

    if side == "BUY":
        # Support levels: things below entry that could bounce price
        support_levels = {
            "vwap": structure.get("vwap", 0.0),
            "or_low": structure.get("or_low", 0.0),
            "ib_low": structure.get("ib_low", 0.0),
            "prior_day_close": structure.get("prior_day_close", 0.0),
            "overnight_low": structure.get("overnight_low", 0.0),
        }
        for name, level in support_levels.items():
            if level > 0 and abs(entry - level) <= proximity:
                confluence_count += 1
                supporting_levels.append(name)
    else:
        # Resistance levels: things above entry that could push price down
        resistance_levels = {
            "vwap": structure.get("vwap", 0.0),
            "or_high": structure.get("or_high", 0.0),
            "ib_high": structure.get("ib_high", 0.0),
            "prior_day_close": structure.get("prior_day_close", 0.0),
            "overnight_high": structure.get("overnight_high", 0.0),
        }
        for name, level in resistance_levels.items():
            if level > 0 and abs(entry - level) <= proximity:
                confluence_count += 1
                supporting_levels.append(name)

    # Score: 0 levels = 5, 1 = 12, 2 = 20, 3+ = 30
    if confluence_count == 0:
        score = 5
    elif confluence_count == 1:
        score = 12
    elif confluence_count == 2:
        score = 20
    else:
        score = 30

    return score, {
        "confluence_count": confluence_count,
        "supporting_levels": supporting_levels,
    }


def score_opportunity(
    candidate: dict,
    regime: dict,
    structure: dict | None = None,
) -> dict[str, Any]:
    """
    Score an opportunity across all 3 dimensions.

    Args:
        candidate:  SetupCandidate dict from a setup scanner.
        regime:     Intraday regime report.
        structure:  Structure levels dict.

    Returns:
        Score dict: {total, regime, rr, structure, details, passed}
    """
    regime_pts, regime_detail = _regime_score(candidate, regime)
    rr_pts, rr_detail = _rr_score(candidate)
    struct_pts, struct_detail = _structure_score(candidate, structure)

    total = regime_pts + rr_pts + struct_pts

    return {
        "total": total,
        "regime": regime_pts,
        "rr": rr_pts,
        "structure": struct_pts,
        "passed": total >= 50,
        "details": {
            "regime": regime_detail,
            "rr": rr_detail,
            "structure": struct_detail,
        },
    }
