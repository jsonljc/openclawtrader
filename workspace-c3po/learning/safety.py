#!/usr/bin/env python3
"""Safety layer — bounds, circuit breakers, drift tracking.

Ensures parameter adjustments stay within safe ranges, prevents
catastrophic drift, and provides circuit breakers for emergencies.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared import state_store as store


# ---------------------------------------------------------------------------
# Per-parameter safety bounds
# ---------------------------------------------------------------------------

BOUNDS: dict[str, tuple[float, float]] = {
    # Sentinel limits
    "sentinel.max_risk_per_trade_pct":          (0.25, 2.0),
    "sentinel.max_open_risk_pct":               (2.0, 8.0),
    "sentinel.max_slippage_ticks":              (2, 8),
    # Regime weights
    "regime.weight_trend":                      (0.10, 0.50),
    "regime.weight_vol":                        (0.10, 0.50),
    "regime.weight_corr":                       (0.10, 0.50),
    "regime.weight_liquidity":                  (0.10, 0.50),
    # Strategy signal params
    "strategy.*.adx_min":                       (15, 40),
    "strategy.*.stop_atr_multiple":             (1.0, 3.0),
    "strategy.*.tp_atr_multiple":               (1.5, 5.0),
    # Strategy health expectations
    "strategy.*.expected_hit_rate":             (0.20, 0.70),
    "strategy.*.expected_sharpe":               (0.1, 3.0),
    "strategy.*.expected_max_dd_pct":           (3.0, 25.0),
    "strategy.*.expected_avg_slippage_ticks":   (0.5, 5.0),
    # Slippage model
    "slippage.base_ticks":                      (0.5, 3.0),
    "slippage.vol_factor_low_slope":            (1.0, 10.0),
    "slippage.vol_factor_high_slope":           (5.0, 25.0),
    "slippage.session_factor_extended":         (1.0, 3.0),
    "slippage.session_factor_boundary":         (1.0, 4.0),
    "slippage.session_factor_pre_open":         (1.5, 5.0),
    # Overnight policy
    "overnight.flatten_vol_pct_threshold":      (0.60, 0.95),
    "overnight.partial_exit_profit_progress":   (0.30, 0.80),
}

# Max single-adjustment change: 20% from current value
MAX_SINGLE_CHANGE_PCT = 0.20

# Max cumulative drift from baseline: 50%
MAX_CUMULATIVE_DRIFT_PCT = 0.50

# Min trades between applying adjustments to the same surface
MIN_TRADES_BETWEEN_APPLIES = 30

# Sentinel limits can only be loosened by max 10% per proposal
SENTINEL_MAX_LOOSEN_PCT = 0.10


# ---------------------------------------------------------------------------
# Bound lookup
# ---------------------------------------------------------------------------

def _get_bounds(param_path: str) -> tuple[float, float] | None:
    """Look up safety bounds for a parameter path.

    Handles wildcard strategy patterns like "strategy.*.adx_min".
    """
    # Direct match
    if param_path in BOUNDS:
        return BOUNDS[param_path]

    # Wildcard match for strategy params: strategy.<sid>.<key> → strategy.*.<key>
    parts = param_path.split(".")
    if len(parts) == 3 and parts[0] == "strategy":
        wildcard = f"strategy.*.{parts[2]}"
        if wildcard in BOUNDS:
            return BOUNDS[wildcard]

    return None


# ---------------------------------------------------------------------------
# Safety checks
# ---------------------------------------------------------------------------

def clamp_to_bounds(param_path: str, value: float) -> float:
    """Clamp a proposed value to its safety bounds."""
    bounds = _get_bounds(param_path)
    if bounds is None:
        return value
    lo, hi = bounds
    return max(lo, min(hi, value))


def check_single_change(
    param_path: str,
    current_value: float,
    proposed_value: float,
) -> tuple[float, str | None]:
    """Enforce max 20% change per adjustment. Returns (clamped_value, warning).

    For sentinel params, loosening is capped at 10%.
    """
    if current_value == 0:
        return proposed_value, None

    change_pct = abs(proposed_value - current_value) / abs(current_value)

    # Sentinel loosening cap
    is_sentinel = param_path.startswith("sentinel.")
    if is_sentinel:
        is_loosening = proposed_value > current_value  # higher limits = looser
        if is_loosening and change_pct > SENTINEL_MAX_LOOSEN_PCT:
            direction = 1 if proposed_value > current_value else -1
            clamped = current_value + direction * abs(current_value) * SENTINEL_MAX_LOOSEN_PCT
            clamped = round(clamped, 4)
            return clamped, (
                f"Sentinel loosening capped at {SENTINEL_MAX_LOOSEN_PCT:.0%}: "
                f"{proposed_value} → {clamped}"
            )

    # General 20% cap
    if change_pct > MAX_SINGLE_CHANGE_PCT:
        direction = 1 if proposed_value > current_value else -1
        clamped = current_value + direction * abs(current_value) * MAX_SINGLE_CHANGE_PCT
        clamped = round(clamped, 4)
        return clamped, (
            f"Change capped at {MAX_SINGLE_CHANGE_PCT:.0%}: "
            f"{proposed_value} → {clamped}"
        )

    return proposed_value, None


def check_cumulative_drift(
    param_path: str,
    proposed_value: float,
    baseline_value: float,
    drift_record: dict[str, float],
) -> tuple[bool, str | None]:
    """Check if cumulative drift from baseline exceeds 50%.

    Returns (allowed, warning_if_blocked).
    """
    if baseline_value == 0:
        return True, None

    drift_pct = abs(proposed_value - baseline_value) / abs(baseline_value)
    if drift_pct > MAX_CUMULATIVE_DRIFT_PCT:
        current_drift = drift_record.get(param_path, 0.0)
        return False, (
            f"Cumulative drift for {param_path} would be {drift_pct:.0%} "
            f"(limit {MAX_CUMULATIVE_DRIFT_PCT:.0%}). "
            f"Current drift: {current_drift:.0%}. "
            f"Requires explicit operator override."
        )

    return True, None


def check_min_trades_between_applies(
    surface: str,
    current_trade_count: int,
    surface_trade_counts: dict[str, int],
) -> tuple[bool, str | None]:
    """Check that enough trades have elapsed since last apply to this surface.

    Returns (allowed, warning_if_blocked).
    """
    last_count = surface_trade_counts.get(surface, 0)
    trades_since = current_trade_count - last_count

    if trades_since < MIN_TRADES_BETWEEN_APPLIES:
        return False, (
            f"Only {trades_since} trades since last {surface} adjustment "
            f"(minimum {MIN_TRADES_BETWEEN_APPLIES}). "
            f"Skipping this surface."
        )

    return True, None


# ---------------------------------------------------------------------------
# Circuit breakers
# ---------------------------------------------------------------------------

def check_dd_circuit_breaker(
    portfolio: dict,
    learning_state: dict,
) -> tuple[bool, str | None]:
    """If portfolio DD > 10% since last param change, trigger revert.

    Returns (should_revert, message).
    """
    pnl = portfolio.get("pnl", {})
    dd_pct = pnl.get("portfolio_dd_pct", 0.0)

    if dd_pct > 10.0:
        applied = learning_state.get("applied_versions", [])
        if len(applied) > 1:
            return True, (
                f"Portfolio DD = {dd_pct:.1f}% (> 10% threshold). "
                f"Circuit breaker triggered — suggest reverting from "
                f"{applied[-1]} to {applied[-2]}."
            )

    return False, None


def check_directional_consistency(
    param_path: str,
    proposed_direction: str,  # "increase" or "decrease"
    learning_state: dict,
    max_consecutive: int = 3,
) -> tuple[bool, str | None]:
    """If 3 consecutive proposals move a param in the same direction, require override.

    Returns (allowed, warning_if_blocked).
    """
    history = learning_state.get("param_direction_history", {})
    directions = history.get(param_path, [])

    if len(directions) >= max_consecutive:
        recent = directions[-max_consecutive:]
        if all(d == proposed_direction for d in recent):
            return False, (
                f"{param_path} has moved {proposed_direction} "
                f"for {max_consecutive} consecutive proposals. "
                f"Requires explicit operator override."
            )

    return True, None


# ---------------------------------------------------------------------------
# Full validation pipeline
# ---------------------------------------------------------------------------

def validate_adjustment(
    adjustment: dict,
    baseline_params: dict,
    learning_state: dict,
    current_trade_count: int,
) -> dict:
    """Run all safety checks on a single adjustment.

    Returns the adjustment dict with possible modifications:
    - proposed_value may be clamped
    - 'warnings' key added with list of warning strings
    - 'blocked' key set to True if adjustment should be skipped
    """
    result = dict(adjustment)
    warnings: list[str] = []
    blocked = False

    param_path = result["param_path"]
    current_value = result["current_value"]
    proposed_value = result["proposed_value"]
    surface = result["surface"]

    # 1. Clamp to bounds
    bounded = clamp_to_bounds(param_path, proposed_value)
    if bounded != proposed_value:
        warnings.append(
            f"Clamped to bounds: {proposed_value} → {bounded} "
            f"(bounds: {_get_bounds(param_path)})"
        )
        proposed_value = bounded

    # 2. Check single-change limit
    clamped, warn = check_single_change(param_path, current_value, proposed_value)
    if warn:
        warnings.append(warn)
        proposed_value = clamped

    # 3. Check cumulative drift
    baseline_value = _resolve_baseline_value(param_path, baseline_params)
    if baseline_value is not None:
        drift_record = learning_state.get("drift_from_baseline", {})
        allowed, warn = check_cumulative_drift(
            param_path, proposed_value, baseline_value, drift_record
        )
        if not allowed:
            warnings.append(warn)
            blocked = True

    # 4. Check min trades between applies
    surface_counts = learning_state.get("surface_trade_counts", {})
    allowed, warn = check_min_trades_between_applies(
        surface, current_trade_count, surface_counts
    )
    if not allowed:
        warnings.append(warn)
        blocked = True

    # 5. Check directional consistency
    direction = "increase" if proposed_value > current_value else "decrease"
    allowed, warn = check_directional_consistency(
        param_path, direction, learning_state
    )
    if not allowed:
        warnings.append(warn)
        blocked = True

    # 6. Confidence gate: CI width < 30% of current value
    confidence = result.get("confidence", 0.0)
    if confidence < 0.30:
        warnings.append(
            f"Low confidence ({confidence:.2f} < 0.30 threshold). "
            f"Adjustment may be unreliable."
        )
        blocked = True

    result["proposed_value"] = proposed_value
    result["warnings"] = warnings
    result["blocked"] = blocked
    return result


def _resolve_baseline_value(param_path: str, baseline_params: dict) -> float | None:
    """Resolve a param_path to a value in the baseline params dict.

    param_path examples:
        "sentinel.max_slippage_ticks" → baseline_params["sentinel"]["max_slippage_ticks"]
        "regime.weight_trend" → baseline_params["regime"]["weight_trend"]
        "strategy.trend_reclaim_4H_ES.adx_min" → strategy file (not in params)
        "slippage.base_ticks" → baseline_params["slippage"]["base_ticks"]
        "overnight.flatten_vol_pct_threshold" → baseline_params["overnight"][...]
    """
    parts = param_path.split(".")

    if parts[0] == "strategy":
        # Strategy-level params are in strategy JSONs, not PV file
        # Load from registry if available
        if len(parts) == 3:
            registry = store.load_strategy_registry()
            strat = registry.get(parts[1], {})
            # Check nested in signal config
            signal = strat.get("signal", {})
            if parts[2] in signal:
                return signal[parts[2]]
            return strat.get(parts[2])
        return None

    # Navigate the params dict
    current: Any = baseline_params
    for part in parts:
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None

    return float(current) if current is not None else None
