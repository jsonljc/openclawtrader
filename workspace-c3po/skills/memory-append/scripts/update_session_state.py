#!/usr/bin/env python3
"""
update_session_state.py
Overwrites c3po/session-state.md with the current session state.
This file represents NOW only. History lives in field_notes.md.

Usage:
    python3 update_session_state.py --state-json '{"session_id": "c3po-001", ...}'
    python3 update_session_state.py --state-json '...' --state-file /path/to/c3po/session-state.md
    python3 update_session_state.py --read   # Print current state and exit
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

DEFAULT_STATE_FILE = "c3po/session-state.md"

REQUIRED_FIELDS = {
    "session_id",
    "started_at",
}

OPTIONAL_FIELDS_WITH_DEFAULTS = {
    "snapshots_fetched": 0,
    "stale_skips": 0,
    "regime_calls": 0,
    "signals_generated": 0,
    "signals_passed_to_sentinel": 0,
    "signals_rejected_by_sentinel": 0,
    "current_regime": "UNKNOWN",
    "current_htf_bias": "UNKNOWN",
    "tradeable": True,
    "halt_reason": None,
}


def get_state_path(override: str | None) -> str:
    if override:
        return override
    # scripts/ -> memory-append/ -> skills/ -> workspace-c3po/ -> c3po/session-state.md
    script_dir = os.path.dirname(os.path.abspath(__file__))
    candidate = os.path.normpath(os.path.join(script_dir, "..", "..", "..", DEFAULT_STATE_FILE))
    return candidate


def validate_state(state: dict) -> list:
    """Returns list of validation errors. Empty = valid."""
    errors = []
    for field in REQUIRED_FIELDS:
        if field not in state:
            errors.append(f"Missing required field: {field}")
    return errors


def render_markdown(state: dict) -> str:
    """Renders state dict as a readable markdown document."""
    ts = state.get("last_updated", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    tradeable_icon = "✅" if state.get("tradeable") else "🔴"
    regime = state.get("current_regime", "UNKNOWN")
    htf_bias = state.get("current_htf_bias", "UNKNOWN")
    halt = state.get("halt_reason")

    lines = [
        "# C3PO Session State",
        f"<!-- auto-generated — do not edit manually — last updated: {ts} -->\n",
        f"**Session:** `{state.get('session_id', 'UNKNOWN')}`  ",
        f"**Started:** {state.get('started_at', 'UNKNOWN')}  ",
        f"**Updated:** {ts}\n",
        "## Status",
        "| Field | Value |",
        "|-------|-------|",
        f"| Tradeable | {tradeable_icon} `{state.get('tradeable')}` |",
        f"| Regime | `{regime}` |",
        f"| HTF Bias | `{htf_bias}` |",
        f"| Halt Reason | `{halt or '—'}` |\n",
        "## Counters",
        "| Metric | Count |",
        "|--------|-------|",
        f"| Snapshots Fetched | {state.get('snapshots_fetched', 0)} |",
        f"| Stale Skips | {state.get('stale_skips', 0)} |",
        f"| Regime Calls | {state.get('regime_calls', 0)} |",
        f"| Signals Generated | {state.get('signals_generated', 0)} |",
        f"| Signals → Sentinel | {state.get('signals_passed_to_sentinel', 0)} |",
        f"| Signals Rejected | {state.get('signals_rejected_by_sentinel', 0)} |\n",
        "## Raw JSON",
        "```json",
        json.dumps(state, indent=2),
        "```",
    ]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description="Update C3PO session state file")
    parser.add_argument("--state-json", default=None,
                        help="JSON string of state object to write")
    parser.add_argument("--state-file", default=None,
                        help="Override path to session-state.md")
    parser.add_argument("--read", action="store_true",
                        help="Read and print current state then exit")
    args = parser.parse_args()

    state_path = get_state_path(args.state_file)

    if args.read:
        if not os.path.exists(state_path):
            print(json.dumps({"error": f"State file not found: {state_path}"}))
            sys.exit(1)
        with open(state_path) as f:
            print(f.read())
        return

    if not args.state_json:
        print(json.dumps({"error": "Must provide --state-json or --read"}))
        sys.exit(1)

    try:
        state = json.loads(args.state_json)
    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"Invalid JSON: {e}"}))
        sys.exit(1)

    for field, default in OPTIONAL_FIELDS_WITH_DEFAULTS.items():
        if field not in state:
            state[field] = default

    state["last_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    errors = validate_state(state)
    if errors:
        print(json.dumps({"error": "Validation failed", "errors": errors}))
        sys.exit(1)

    dir_path = os.path.dirname(state_path)
    if dir_path:
        os.makedirs(dir_path, exist_ok=True)
    with open(state_path, "w") as f:
        f.write(render_markdown(state))

    result = {
        "status": "ok",
        "state_file": state_path,
        "last_updated": state["last_updated"],
        "tradeable": state["tradeable"],
        "regime": state["current_regime"],
        "htf_bias": state["current_htf_bias"],
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
