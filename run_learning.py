#!/usr/bin/env python3
"""CLI entry point for the OpenClaw adaptive learning pipeline.

Usage:
    python run_learning.py analyze              # Collect data + run all 6 analyzers
    python run_learning.py propose              # Generate ParamProposal from analysis
    python run_learning.py review               # Show proposal diff with rationale
    python run_learning.py apply                # Apply approved proposal
    python run_learning.py reject [reason]      # Reject proposal with reason
    python run_learning.py status               # Show learning state, drift, history
    python run_learning.py revert               # Revert to previous param version
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "workspace-c3po"))
sys.path.insert(0, str(_ROOT / "workspace-c3po" / "learning"))

from shared import state_store as store
from shared import ledger
from shared import contracts as C

from learning.collector import collect_trades, collect_regime_snapshots, collect_denied_intents
from learning.analyzers.signal_analyzer import analyze_signals
from learning.analyzers.regime_analyzer import analyze_regime
from learning.analyzers.health_analyzer import analyze_health
from learning.analyzers.sentinel_analyzer import analyze_sentinel
from learning.analyzers.overnight_analyzer import analyze_overnight
from learning.analyzers.slippage_analyzer import analyze_slippage
from learning.proposer import build_proposal, apply_proposal, revert_to_previous, ParamProposal
from learning.safety import check_dd_circuit_breaker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _print_header(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def _print_section(title: str) -> None:
    print(f"\n  [{title}]")


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_analyze(lookback_days: int = 90) -> dict:
    """Collect data and run all 6 analyzers."""
    _print_header("Learning Pipeline — Analysis")

    # Load state
    learning_state = store.load_learning_state()
    portfolio = store.load_portfolio()
    param_version = portfolio.get("param_version", "PV_0001")
    params = store.load_params(param_version)
    registry = store.load_strategy_registry()
    exec_quality = store.load_exec_quality()

    print(f"  Param version: {param_version}")
    print(f"  Lookback: {lookback_days} days")
    print(f"  Strategies: {', '.join(registry.keys())}")

    # Collect data
    print("\n  Collecting data from ledger...")
    all_trades = collect_trades(lookback_days=lookback_days)
    regime_snapshots = collect_regime_snapshots(lookback_days=lookback_days)
    all_denied = collect_denied_intents(lookback_days=lookback_days)

    total_trades = len(all_trades)
    print(f"  Trades found: {total_trades}")
    print(f"  Regime snapshots: {len(regime_snapshots)}")
    print(f"  Denied intents: {len(all_denied)}")

    # Cold-start check
    if total_trades < 15:
        print(f"\n  Cold start: only {total_trades} trades (< 15 minimum).")
        print("  Running in COLLECT-ONLY mode — no proposals will be generated.")
    elif total_trades < 30:
        print(f"\n  Early phase: {total_trades} trades (< 30).")
        print("  Only low-risk surfaces (health, slippage) will generate proposals.")

    # Run analyzers
    all_adjustments: list[dict] = []

    for sid, strategy in registry.items():
        strat_trades = [t for t in all_trades if t.strategy_id == sid]
        strat_denied = [d for d in all_denied if d.get("strategy_id") == sid]

        _print_section(f"SIGNAL — {sid}")
        signal_adjs = analyze_signals(strat_trades, strategy)
        print(f"    Trades: {len(strat_trades)} | Adjustments: {len(signal_adjs)}")
        for a in signal_adjs:
            print(f"    → {a['param_path']}: {a['current_value']} → {a['proposed_value']}")
        all_adjustments.extend(signal_adjs)

        _print_section(f"HEALTH — {sid}")
        health_adjs = analyze_health(strat_trades, strategy)
        print(f"    Trades: {len(strat_trades)} | Adjustments: {len(health_adjs)}")
        for a in health_adjs:
            print(f"    → {a['param_path']}: {a['current_value']} → {a['proposed_value']}")
        all_adjustments.extend(health_adjs)

        _print_section(f"SENTINEL — {sid}")
        sentinel_adjs = analyze_sentinel(strat_trades, strat_denied, exec_quality, params)
        print(f"    Events: {len(strat_trades) + len(strat_denied)} | Adjustments: {len(sentinel_adjs)}")
        for a in sentinel_adjs:
            print(f"    → {a['param_path']}: {a['current_value']} → {a['proposed_value']}")
        all_adjustments.extend(sentinel_adjs)

        _print_section(f"OVERNIGHT — {sid}")
        overnight_adjs = analyze_overnight(strat_trades, params)
        print(f"    Trades: {len(strat_trades)} | Adjustments: {len(overnight_adjs)}")
        for a in overnight_adjs:
            print(f"    → {a['param_path']}: {a['current_value']} → {a['proposed_value']}")
        all_adjustments.extend(overnight_adjs)

        _print_section(f"SLIPPAGE — {sid}")
        slippage_adjs = analyze_slippage(strat_trades, params)
        print(f"    Trades: {len(strat_trades)} | Adjustments: {len(slippage_adjs)}")
        for a in slippage_adjs:
            print(f"    → {a['param_path']}: {a['current_value']} → {a['proposed_value']}")
        all_adjustments.extend(slippage_adjs)

    # Regime analysis (portfolio-wide, not per-strategy)
    _print_section("REGIME (portfolio-wide)")
    current_weights = params.get("regime", {})
    regime_adjs = analyze_regime(regime_snapshots, all_trades, current_weights)
    print(f"    Snapshots: {len(regime_snapshots)} | Adjustments: {len(regime_adjs)}")
    for a in regime_adjs:
        print(f"    → {a['param_path']}: {a['current_value']} → {a['proposed_value']}")
    all_adjustments.extend(regime_adjs)

    # Summary
    _print_header("Analysis Summary")
    print(f"  Total adjustments proposed: {len(all_adjustments)}")
    surfaces = set(a["surface"] for a in all_adjustments)
    for s in sorted(surfaces):
        count = sum(1 for a in all_adjustments if a["surface"] == s)
        print(f"    {s}: {count}")

    # Update learning state
    learning_state["last_analysis_at"] = _utcnow_iso()
    store.save_learning_state(learning_state)

    # Store analysis results in state for the propose command
    analysis_cache = {
        "raw_adjustments": all_adjustments,
        "total_trades": total_trades,
        "param_version": param_version,
        "analyzed_at": _utcnow_iso(),
    }

    # Save to a temp file for the propose step
    cache_path = Path(store._DATA_DIR) / "learning_analysis_cache.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cache_path, "w") as f:
        json.dump(analysis_cache, f, indent=2)

    print(f"\n  Analysis cached. Run 'python run_learning.py propose' to generate proposal.")
    return analysis_cache


def cmd_propose() -> ParamProposal | None:
    """Generate a ParamProposal from the latest analysis."""
    _print_header("Learning Pipeline — Proposal Generation")

    # Load cached analysis
    cache_path = Path(store._DATA_DIR) / "learning_analysis_cache.json"
    if not cache_path.exists():
        print("  No analysis cache found. Run 'python run_learning.py analyze' first.")
        return None

    with open(cache_path) as f:
        cache = json.load(f)

    raw_adjustments = cache["raw_adjustments"]
    total_trades = cache["total_trades"]
    param_version = cache["param_version"]

    learning_state = store.load_learning_state()

    # Check circuit breaker
    portfolio = store.load_portfolio()
    should_revert, msg = check_dd_circuit_breaker(portfolio, learning_state)
    if should_revert:
        print(f"\n  CIRCUIT BREAKER: {msg}")
        print("  Run 'python run_learning.py revert' to revert parameters.")
        return None

    # Build proposal
    proposal = build_proposal(
        raw_adjustments=raw_adjustments,
        total_trades=total_trades,
        learning_state=learning_state,
        param_version=param_version,
    )

    if proposal.status == "INSUFFICIENT_DATA":
        print(f"\n  Insufficient data ({total_trades} trades). No proposal generated.")
        print("  Continue collecting data and re-analyze later.")
        return proposal

    active = [a for a in proposal.adjustments if not a.blocked]
    blocked = [a for a in proposal.adjustments if a.blocked]

    print(f"\n  Proposal: {proposal.proposal_id}")
    print(f"  Base: {proposal.base_version} → {proposal.new_version}")
    print(f"  Active adjustments: {len(active)}")
    print(f"  Blocked adjustments: {len(blocked)}")
    print(f"  Overall confidence: {proposal.overall_confidence:.2f}")

    if blocked:
        print("\n  Blocked adjustments:")
        for a in blocked:
            print(f"    {a.param_path}: {a.current_value} → {a.proposed_value}")
            for w in a.warnings:
                print(f"      ! {w}")

    # Save proposal to learning state
    learning_state["proposals"].append(proposal.to_dict())
    # Keep last 20 proposals
    learning_state["proposals"] = learning_state["proposals"][-20:]
    store.save_learning_state(learning_state)

    print(f"\n  Proposal saved. Run 'python run_learning.py review' to inspect.")
    return proposal


def cmd_review() -> None:
    """Show the latest proposal diff with rationale."""
    learning_state = store.load_learning_state()
    proposals = learning_state.get("proposals", [])

    if not proposals:
        print("\n  No proposals found. Run 'analyze' then 'propose' first.")
        return

    latest = proposals[-1]
    proposal = ParamProposal.from_dict(latest)

    active = [a for a in proposal.adjustments if not a.blocked]

    _print_header(f"Param Proposal {proposal.new_version} ({proposal.status})")
    print(f"  Base: {proposal.base_version} | "
          f"Trades analyzed: {proposal.total_trades_analyzed} | "
          f"Confidence: {proposal.overall_confidence:.2f}")

    if not active:
        print("\n  No active adjustments in this proposal.")
        if proposal.status == "INSUFFICIENT_DATA":
            print("  Reason: Insufficient data for reliable inference.")
        return

    for a in active:
        surface_label = a.surface.upper()
        print(f"\n  [{surface_label}] {a.param_path}: {a.current_value} → {a.proposed_value}")
        # Wrap rationale text
        rationale_lines = _wrap_text(a.rationale, width=70, indent="    ")
        for line in rationale_lines:
            print(line)
        print(f"    Confidence: {a.confidence:.2f} | Sample: {a.sample_size}")
        if a.warnings:
            for w in a.warnings:
                print(f"    ! {w}")

    blocked = [a for a in proposal.adjustments if a.blocked]
    if blocked:
        print(f"\n  --- Blocked ({len(blocked)}) ---")
        for a in blocked:
            print(f"  [{a.surface.upper()}] {a.param_path}: {a.current_value} → {a.proposed_value}")
            for w in a.warnings:
                print(f"    ! {w}")

    if proposal.status == "DRAFT":
        print(f"\n  Actions: [a]pply  [r]eject  [s]kip")
        try:
            choice = input("  > ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n  Skipped.")
            return

        if choice == "a":
            proposal.status = "APPROVED"
            latest["status"] = "APPROVED"
            store.save_learning_state(learning_state)
            print("  Proposal APPROVED. Run 'python run_learning.py apply' to persist.")
        elif choice == "r":
            reason = input("  Rejection reason: ").strip() if sys.stdin.isatty() else ""
            proposal.status = "REJECTED"
            proposal.rejection_reason = reason
            latest["status"] = "REJECTED"
            latest["rejection_reason"] = reason
            store.save_learning_state(learning_state)
            print("  Proposal REJECTED.")
        else:
            print("  Skipped — proposal remains as DRAFT.")


def cmd_apply() -> None:
    """Apply the latest approved proposal."""
    _print_header("Learning Pipeline — Apply Proposal")

    learning_state = store.load_learning_state()
    proposals = learning_state.get("proposals", [])

    if not proposals:
        print("  No proposals found.")
        return

    latest = proposals[-1]
    if latest.get("status") != "APPROVED":
        print(f"  Latest proposal status is '{latest.get('status')}', not APPROVED.")
        print("  Run 'python run_learning.py review' to approve first.")
        return

    proposal = ParamProposal.from_dict(latest)

    try:
        apply_proposal(proposal)
        latest["status"] = "APPLIED"
        store.save_learning_state(learning_state)
        print(f"\n  Proposal {proposal.proposal_id} APPLIED.")
        print(f"  New param version: {proposal.new_version}")
        print(f"  PV file: params/{proposal.new_version}.json")

        active = [a for a in proposal.adjustments if not a.blocked]
        print(f"\n  Changes applied ({len(active)}):")
        for a in active:
            print(f"    {a.param_path}: {a.current_value} → {a.proposed_value}")

    except Exception as e:
        print(f"\n  ERROR applying proposal: {e}")
        raise


def cmd_reject(reason: str = "") -> None:
    """Reject the latest draft/approved proposal."""
    learning_state = store.load_learning_state()
    proposals = learning_state.get("proposals", [])

    if not proposals:
        print("  No proposals found.")
        return

    latest = proposals[-1]
    if latest.get("status") not in ("DRAFT", "APPROVED"):
        print(f"  Latest proposal status is '{latest.get('status')}'. Nothing to reject.")
        return

    latest["status"] = "REJECTED"
    latest["rejection_reason"] = reason
    store.save_learning_state(learning_state)
    print(f"  Proposal REJECTED. Reason: {reason or '(none given)'}")


def cmd_status() -> None:
    """Show learning state, drift, and history."""
    _print_header("Learning Pipeline — Status")

    learning_state = store.load_learning_state()
    portfolio = store.load_portfolio()
    param_version = portfolio.get("param_version", "PV_0001")

    print(f"  Current param version: {param_version}")
    print(f"  Last analysis: {learning_state.get('last_analysis_at', 'Never')}")
    print(f"  Trades at last apply: {learning_state.get('trade_count_at_last_apply', 0)}")
    print(f"  Applied versions: {' → '.join(learning_state.get('applied_versions', []))}")

    # Drift tracking
    drift = learning_state.get("drift_from_baseline", {})
    if drift:
        print("\n  Drift from baseline (PV_0001):")
        for param, pct in sorted(drift.items()):
            bar = "█" * int(pct * 20)
            warn = " ⚠" if pct > 0.40 else ""
            print(f"    {param:45s} {pct:6.1%} {bar}{warn}")
    else:
        print("\n  No drift recorded (still on baseline).")

    # Recent proposals
    proposals = learning_state.get("proposals", [])
    if proposals:
        print(f"\n  Recent proposals ({len(proposals)}):")
        for p in proposals[-5:]:
            adj_count = len([
                a for a in p.get("adjustments", [])
                if not a.get("blocked", False)
            ])
            print(f"    {p['proposal_id'][:30]:30s}  "
                  f"{p['status']:18s}  "
                  f"{adj_count} adjustments  "
                  f"conf={p.get('overall_confidence', 0):.2f}")
    else:
        print("\n  No proposals yet.")

    # Circuit breaker check
    should_revert, msg = check_dd_circuit_breaker(portfolio, learning_state)
    if should_revert:
        print(f"\n  ⚠ CIRCUIT BREAKER: {msg}")

    # Surface trade counts
    surface_counts = learning_state.get("surface_trade_counts", {})
    if surface_counts:
        print("\n  Trades at last surface apply:")
        for surface, count in sorted(surface_counts.items()):
            print(f"    {surface:20s} {count}")


def cmd_revert() -> None:
    """Revert to previous param version."""
    _print_header("Learning Pipeline — Revert")

    learning_state = store.load_learning_state()
    applied = learning_state.get("applied_versions", [])

    if len(applied) < 2:
        print("  No previous version to revert to.")
        return

    current = applied[-1]
    previous = applied[-2]

    print(f"  Current: {current}")
    print(f"  Revert to: {previous}")

    if sys.stdin.isatty():
        try:
            confirm = input("  Confirm revert? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n  Cancelled.")
            return
        if confirm != "y":
            print("  Cancelled.")
            return

    result = revert_to_previous(learning_state)
    if result:
        print(f"\n  Reverted to {result}.")
    else:
        print("  Revert failed — no previous version found.")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _wrap_text(text: str, width: int = 70, indent: str = "") -> list[str]:
    """Simple word-wrap for rationale text."""
    words = text.split()
    lines: list[str] = []
    current_line = indent

    for word in words:
        if len(current_line) + len(word) + 1 > width + len(indent):
            lines.append(current_line)
            current_line = indent + word
        else:
            if current_line == indent:
                current_line += word
            else:
                current_line += " " + word

    if current_line.strip():
        lines.append(current_line)

    return lines


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1].lower()

    if command == "analyze":
        lookback = int(sys.argv[2]) if len(sys.argv) > 2 else 90
        cmd_analyze(lookback_days=lookback)
    elif command == "propose":
        cmd_propose()
    elif command == "review":
        cmd_review()
    elif command == "apply":
        cmd_apply()
    elif command == "reject":
        reason = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else ""
        cmd_reject(reason)
    elif command == "status":
        cmd_status()
    elif command == "revert":
        cmd_revert()
    else:
        print(f"  Unknown command: {command}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
