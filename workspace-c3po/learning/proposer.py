#!/usr/bin/env python3
"""Proposer — merges analyzer outputs into a single ParamProposal.

Validates adjustments through the safety layer and produces
a reviewable proposal for the human operator.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared import state_store as store
from shared import ledger
from shared import contracts as C

from . import safety


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class Adjustment:
    """A single parameter adjustment proposal."""

    surface: str              # "signal", "regime", "health", "sentinel", "overnight", "slippage"
    param_path: str           # e.g. "sentinel.max_slippage_ticks"
    current_value: float
    proposed_value: float
    confidence: float         # 0-1 from Bayesian CI width
    sample_size: int
    rationale: str
    warnings: list[str] = field(default_factory=list)
    blocked: bool = False


@dataclass
class ParamProposal:
    """Complete parameter change proposal."""

    proposal_id: str
    created_at: str
    base_version: str         # e.g. "PV_0001"
    new_version: str          # e.g. "PV_0002"
    adjustments: list[Adjustment]
    overall_confidence: float
    status: str               # "DRAFT", "APPROVED", "APPLIED", "REJECTED"
    total_trades_analyzed: int = 0
    rejection_reason: str = ""

    def to_dict(self) -> dict:
        return {
            "proposal_id": self.proposal_id,
            "created_at": self.created_at,
            "base_version": self.base_version,
            "new_version": self.new_version,
            "adjustments": [asdict(a) for a in self.adjustments],
            "overall_confidence": self.overall_confidence,
            "status": self.status,
            "total_trades_analyzed": self.total_trades_analyzed,
            "rejection_reason": self.rejection_reason,
        }

    @staticmethod
    def from_dict(d: dict) -> "ParamProposal":
        adjs = [Adjustment(**a) for a in d.get("adjustments", [])]
        return ParamProposal(
            proposal_id=d["proposal_id"],
            created_at=d["created_at"],
            base_version=d["base_version"],
            new_version=d["new_version"],
            adjustments=adjs,
            overall_confidence=d["overall_confidence"],
            status=d["status"],
            total_trades_analyzed=d.get("total_trades_analyzed", 0),
            rejection_reason=d.get("rejection_reason", ""),
        )


# ---------------------------------------------------------------------------
# Cold-start thresholds
# ---------------------------------------------------------------------------

COLD_START_COLLECT_ONLY = 15      # < 15 trades: collect only
COLD_START_LOW_RISK = 30          # 15-30 trades: health + slippage only
LOW_RISK_SURFACES = {"health", "slippage"}


# ---------------------------------------------------------------------------
# Proposer
# ---------------------------------------------------------------------------

def _next_version(current_version: str) -> str:
    """Increment PV_XXXX to PV_XXXX+1."""
    prefix = current_version.split("_")[0]
    num = int(current_version.split("_")[1])
    return f"{prefix}_{num + 1:04d}"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def build_proposal(
    raw_adjustments: list[dict],
    total_trades: int,
    learning_state: dict,
    param_version: str = "PV_0001",
) -> ParamProposal:
    """Build a validated proposal from raw analyzer outputs.

    Args:
        raw_adjustments: Combined output from all analyzers.
        total_trades: Total trades in analysis window.
        learning_state: Current learning state from state_store.
        param_version: Current active parameter version.

    Returns:
        ParamProposal with validated, safety-checked adjustments.
    """
    baseline_params = store.load_params("PV_0001")
    current_params = store.load_params(param_version)

    # Cold-start gating
    if total_trades < COLD_START_COLLECT_ONLY:
        return ParamProposal(
            proposal_id=f"LP_{_utcnow_iso().replace(':', '').replace('-', '').replace('.', '_')}",
            created_at=_utcnow_iso(),
            base_version=param_version,
            new_version=_next_version(param_version),
            adjustments=[],
            overall_confidence=0.0,
            status="INSUFFICIENT_DATA",
            total_trades_analyzed=total_trades,
        )

    # Filter surfaces by cold-start phase
    active_adjustments = raw_adjustments
    if total_trades < COLD_START_LOW_RISK:
        active_adjustments = [
            a for a in raw_adjustments
            if a.get("surface", "") in LOW_RISK_SURFACES
        ]

    # Validate each adjustment through safety layer
    validated: list[Adjustment] = []
    for adj in active_adjustments:
        checked = safety.validate_adjustment(
            adjustment=adj,
            baseline_params=baseline_params,
            learning_state=learning_state,
            current_trade_count=total_trades,
        )
        validated.append(Adjustment(
            surface=checked["surface"],
            param_path=checked["param_path"],
            current_value=checked["current_value"],
            proposed_value=checked["proposed_value"],
            confidence=checked.get("confidence", 0.0),
            sample_size=checked.get("sample_size", 0),
            rationale=checked.get("rationale", ""),
            warnings=checked.get("warnings", []),
            blocked=checked.get("blocked", False),
        ))

    # Normalize regime weights if any were adjusted
    _normalize_regime_weights(validated, current_params)

    # Filter out blocked adjustments for confidence calculation
    active = [a for a in validated if not a.blocked]
    if active:
        overall_conf = sum(a.confidence for a in active) / len(active)
    else:
        overall_conf = 0.0

    proposal_id = f"LP_{_utcnow_iso().replace(':', '').replace('-', '').replace('.', '_')}"

    return ParamProposal(
        proposal_id=proposal_id,
        created_at=_utcnow_iso(),
        base_version=param_version,
        new_version=_next_version(param_version),
        adjustments=validated,
        overall_confidence=round(overall_conf, 4),
        status="DRAFT",
        total_trades_analyzed=total_trades,
    )


def _normalize_regime_weights(
    adjustments: list[Adjustment],
    current_params: dict,
) -> None:
    """Ensure regime weights sum to 1.0 after adjustments.

    Modifies adjustments in place.
    """
    regime_keys = ["weight_trend", "weight_vol", "weight_corr", "weight_liquidity"]
    regime_adjs = {
        a.param_path: a for a in adjustments
        if a.param_path.startswith("regime.weight_") and not a.blocked
    }

    if not regime_adjs:
        return

    rp = current_params.get("regime", {})
    weights = {}
    for key in regime_keys:
        path = f"regime.{key}"
        if path in regime_adjs:
            weights[key] = regime_adjs[path].proposed_value
        else:
            weights[key] = rp.get(key, 0.25)

    total = sum(weights.values())
    if total == 0 or abs(total - 1.0) < 0.001:
        return

    # Normalize all weights
    for key in weights:
        weights[key] = round(weights[key] / total, 4)

    # Update existing adjustments and add new ones for unchanged weights
    for key, val in weights.items():
        path = f"regime.{key}"
        if path in regime_adjs:
            regime_adjs[path].proposed_value = val
        else:
            # Add a normalization adjustment for unchanged weights
            current_val = rp.get(key, 0.25)
            if abs(val - current_val) > 0.001:
                adjustments.append(Adjustment(
                    surface="regime",
                    param_path=path,
                    current_value=current_val,
                    proposed_value=val,
                    confidence=1.0,
                    sample_size=0,
                    rationale="Normalized to maintain weight sum = 1.0.",
                ))


# ---------------------------------------------------------------------------
# Applier
# ---------------------------------------------------------------------------

def apply_proposal(
    proposal: ParamProposal,
    run_id: str = "RUN_LEARNING",
) -> None:
    """Apply an approved proposal: write new PV file, update strategies, log event.

    Args:
        proposal: The approved proposal to apply.
        run_id: Run ID for ledger events.
    """
    if proposal.status != "APPROVED":
        raise ValueError(f"Cannot apply proposal with status '{proposal.status}'")

    active_adjustments = [a for a in proposal.adjustments if not a.blocked]
    if not active_adjustments:
        raise ValueError("No active (non-blocked) adjustments to apply")

    # 1. Load current params and create new version
    current_params = store.load_params(proposal.base_version)
    new_params = json.loads(json.dumps(current_params))  # deep copy
    new_params["param_version"] = proposal.new_version
    new_params["created_at"] = _utcnow_iso()
    new_params["created_by"] = "learning_pipeline"
    new_params["effective_from"] = _utcnow_iso()
    new_params["based_on"] = proposal.base_version
    new_params["proposal_id"] = proposal.proposal_id

    strategy_updates: dict[str, dict[str, Any]] = {}

    for adj in active_adjustments:
        parts = adj.param_path.split(".")

        if parts[0] == "strategy" and len(parts) == 3:
            # Strategy-level params go into strategy JSONs
            sid = parts[1]
            key = parts[2]
            strategy_updates.setdefault(sid, {})[key] = adj.proposed_value
        else:
            # Param-level: navigate into the params dict
            target = new_params
            for p in parts[:-1]:
                target = target.setdefault(p, {})
            target[parts[-1]] = adj.proposed_value

    # 2. Write new PV file
    params_dir = Path(store._PARAMS_DIR)
    params_dir.mkdir(parents=True, exist_ok=True)
    pv_path = params_dir / f"{proposal.new_version}.json"
    with open(pv_path, "w") as f:
        json.dump(new_params, f, indent=2)
        f.write("\n")

    # 3. Update strategy JSONs
    registry = store.load_strategy_registry()
    for sid, updates in strategy_updates.items():
        strat = registry.get(sid)
        if not strat:
            continue
        for key, val in updates.items():
            # Check if it's a signal param
            if key in strat.get("signal", {}):
                strat["signal"][key] = val
            else:
                strat[key] = val
        store.save_strategy(strat)

    # 4. Update portfolio param_version
    portfolio = store.load_portfolio()
    portfolio["param_version"] = proposal.new_version
    store.save_portfolio(portfolio)

    # 5. Log PARAMETER_CHANGE event to ledger
    change_payload = {
        "proposal_id": proposal.proposal_id,
        "previous_version": proposal.base_version,
        "new_version": proposal.new_version,
        "adjustments": [
            {
                "surface": a.surface,
                "param_path": a.param_path,
                "old_value": a.current_value,
                "new_value": a.proposed_value,
                "confidence": a.confidence,
                "sample_size": a.sample_size,
            }
            for a in active_adjustments
        ],
        "overall_confidence": proposal.overall_confidence,
        "total_trades_analyzed": proposal.total_trades_analyzed,
    }

    ledger.append(
        event_type=C.EventType.PARAMETER_CHANGE,
        run_id=run_id,
        ref_id=proposal.proposal_id,
        payload=change_payload,
    )

    # 6. Log LEARNING_PROPOSAL event
    ledger.append(
        event_type=C.EventType.LEARNING_PROPOSAL,
        run_id=run_id,
        ref_id=proposal.proposal_id,
        payload={
            "status": "APPLIED",
            "proposal": proposal.to_dict(),
        },
    )

    # 7. Update learning state
    state = store.load_learning_state()
    state["applied_versions"].append(proposal.new_version)

    # Update drift tracking
    baseline_params = store.load_params("PV_0001")
    drift = state.get("drift_from_baseline", {})
    for adj in active_adjustments:
        baseline_val = safety._resolve_baseline_value(adj.param_path, baseline_params)
        if baseline_val is not None and baseline_val != 0:
            drift[adj.param_path] = round(
                abs(adj.proposed_value - baseline_val) / abs(baseline_val), 4
            )

    # Update direction history
    direction_history = state.get("param_direction_history", {})
    for adj in active_adjustments:
        direction = "increase" if adj.proposed_value > adj.current_value else "decrease"
        history = direction_history.get(adj.param_path, [])
        history.append(direction)
        direction_history[adj.param_path] = history[-5:]  # keep last 5

    # Update surface trade counts
    total_trades = proposal.total_trades_analyzed
    for adj in active_adjustments:
        state["surface_trade_counts"][adj.surface] = total_trades

    state["drift_from_baseline"] = drift
    state["param_direction_history"] = direction_history
    state["trade_count_at_last_apply"] = total_trades
    store.save_learning_state(state)

    proposal.status = "APPLIED"


def revert_to_previous(
    learning_state: dict,
    run_id: str = "RUN_LEARNING",
) -> str | None:
    """Revert to the previous parameter version.

    Returns the version reverted to, or None if no previous version.
    """
    applied = learning_state.get("applied_versions", [])
    if len(applied) < 2:
        return None

    previous = applied[-2]
    current = applied[-1]

    # Update portfolio to use previous version
    portfolio = store.load_portfolio()
    portfolio["param_version"] = previous
    store.save_portfolio(portfolio)

    # Log the revert
    ledger.append(
        event_type=C.EventType.PARAMETER_CHANGE,
        run_id=run_id,
        ref_id=f"REVERT_{current}_to_{previous}",
        payload={
            "action": "REVERT",
            "reverted_from": current,
            "reverted_to": previous,
            "reason": "Circuit breaker or operator decision",
        },
    )

    # Update learning state
    applied.append(previous)
    learning_state["applied_versions"] = applied
    store.save_learning_state(learning_state)

    return previous
