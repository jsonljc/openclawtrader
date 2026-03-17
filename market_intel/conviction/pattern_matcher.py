"""Pattern matcher: evaluates named conditional patterns against analytics data.

Uses a simple condition parser (no eval()) to check each condition.
All conditions in a pattern must be true for a match.
Returns the FIRST matching pattern (ordered by priority in config).

Pure functions — no IB or Redis dependency.
"""
from __future__ import annotations

import re
from typing import Any

# Supported operators
_OPERATORS = {
    ">=": lambda a, b: a >= b,
    "<=": lambda a, b: a <= b,
    ">": lambda a, b: a > b,
    "<": lambda a, b: a < b,
    "==": lambda a, b: a == b,
}

# Regex: lhs  operator  rhs
# Operator must be matched longest-first (>= before >)
_CONDITION_RE = re.compile(
    r"^\s*(\S+)\s*(>=|<=|>|<|==)\s*(\S+)\s*$"
)


def match_pattern(analytics: dict, patterns_config: list[dict]) -> dict | None:
    """Find the first pattern whose conditions are all satisfied by analytics.

    Args:
        analytics: Dict of current analytics values (e.g., {"gex": -30, "velocity_5m": 55}).
        patterns_config: List of pattern dicts, each with:
            - name: str
            - direction: "LONG" | "SHORT" | "NEUTRAL" | "BOTH"
            - base_score: int (0-100)
            - confidence: "HIGH" | "MEDIUM" | "LOW"
            - conditions: list[str] — e.g., ["gex < 0", "velocity_15m > velocity_5m"]

    Returns:
        {"name": str, "direction": str, "base_score": int, "confidence": str} or None
    """
    for pattern in patterns_config:
        conditions = pattern.get("conditions", [])
        if all(_evaluate_condition(cond, analytics) for cond in conditions):
            return {
                "name": pattern["name"],
                "direction": pattern["direction"],
                "base_score": pattern["base_score"],
                "confidence": pattern["confidence"],
            }
    return None


def _evaluate_condition(condition: str, analytics: dict) -> bool:
    """Evaluate a single condition string against analytics.

    Supports:
      - "field > 50"            (compare field to literal number)
      - "field >= other_field"  (compare two analytics fields)
      - "field == 1"            (equality with number)

    Returns False if a referenced field is missing from analytics.
    """
    match = _CONDITION_RE.match(condition)
    if not match:
        return False

    lhs_key, op, rhs_token = match.groups()

    # Resolve left-hand side — must be an analytics key
    if lhs_key not in analytics:
        return False
    lhs_val = analytics[lhs_key]

    # Resolve right-hand side — either a literal number or another analytics key
    rhs_val = _resolve_value(rhs_token, analytics)
    if rhs_val is None:
        return False

    return _OPERATORS[op](lhs_val, rhs_val)


def _resolve_value(token: str, analytics: dict) -> float | None:
    """Resolve a token to a numeric value: literal number or analytics key lookup."""
    # Try parsing as a number first
    try:
        return float(token)
    except ValueError:
        pass

    # Try as an analytics key
    if token in analytics:
        val = analytics[token]
        if isinstance(val, (int, float)):
            return float(val)

    return None
