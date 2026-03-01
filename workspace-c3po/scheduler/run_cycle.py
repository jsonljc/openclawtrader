#!/usr/bin/env python3
"""
run_cycle.py — 15-minute cycle driver
Runs the full C3PO → Sentinel → Forge pipeline on each 15m candle close.

Usage:
    python3 run_cycle.py                  # run once, Forge in dry-run (default)
    python3 run_cycle.py --loop           # loop forever, fire at each 15m boundary
    python3 run_cycle.py --dry-run        # run once, Forge dry-run (no real orders)
    python3 run_cycle.py --live           # run once, Binance live (real orders; needs BINANCE_API_KEY/SECRET)
    python3 run_cycle.py --paper          # run once, paper_broker (simulated with Binance market data)

Cron example (every 15 minutes, dry-run):
    */15 * * * * cd /home/elyra/.openclaw-elyra/workspace-c3po && python3 scheduler/run_cycle.py --dry-run >> ~/openclaw-trader/logs/cycle.log 2>&1

Binance direct (live) execution:
    export BINANCE_API_KEY=... BINANCE_API_SECRET=...
    python3 run_cycle.py --live
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE        = Path(__file__).parent.parent
SENTINEL_DIR     = WORKSPACE.parent / "workspace-sentinel"
FORGE_DIR        = WORKSPACE.parent / "workspace-forge"

OUTPUT_DIR       = Path.home() / "openclaw-trader" / "out"
CYCLE_LOG        = Path.home() / "openclaw-trader" / "logs" / "cycle.log"


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log(msg: str) -> None:
    line = f"[{now_utc()}] {msg}"
    print(line)
    try:
        CYCLE_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(CYCLE_LOG, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def run(cmd: list[str], cwd: Path = None, timeout: int = 60) -> tuple[int, str, str]:
    """Run a subprocess, return (returncode, stdout, stderr)."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           cwd=str(cwd) if cwd else None, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "TIMEOUT"
    except Exception as e:
        return -1, "", str(e)


def parse_json_safe(text: str) -> dict | None:
    try:
        return json.loads(text)
    except Exception:
        return None


def _append_signals_jsonl(intent_id: str, ts: str, score: int, tier: str, posture: str,
                          decision_kind: str, execution_status: str | None, dry_run: bool) -> None:
    """Append one JSONL line to ~/openclaw-trader/out/signals.jsonl (Risk Layer v1)."""
    if dry_run:
        return
    try:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        path = OUTPUT_DIR / "signals.jsonl"
        line = {
            "intent_id": intent_id,
            "ts": ts,
            "score": score,
            "tier": tier,
            "posture": posture,
            "decision_kind": decision_kind,
            "execution_status": execution_status,
        }
        with open(path, "a") as f:
            f.write(json.dumps(line, separators=(",", ":")) + "\n")
    except Exception:
        pass


def run_cycle(dry_run: bool = False, paper: bool = False) -> dict:
    """Execute one full pipeline cycle. Returns cycle summary."""
    ts = now_utc()
    log(f"=== CYCLE START dry_run={dry_run} ===")
    summary = {
        "ts": ts,
        "dry_run": dry_run,
        "steps": {},
        "outcome": "UNKNOWN",
    }

    # ── Step 1: C3PO brain (writes latest.json; never dry-run so intent is persisted) ──
    code, stdout, stderr = run(
        [sys.executable, str(WORKSPACE / "brain.py")],
        cwd=WORKSPACE,
        timeout=90,
    )

    intent = parse_json_safe(stdout)
    side = intent.get("intent", {}).get("side", "UNKNOWN") if intent else "ERROR"
    tier = intent.get("intent", {}).get("confidence_tier", "") or (intent.get("confidence", {}) or {}).get("tier", "") if intent else ""
    score = intent.get("intent", {}).get("confidence_score", 0) or (intent.get("confidence", {}) or {}).get("score", 0) if intent else 0
    intent_id = intent.get("intent_id", "") if intent else ""

    summary["steps"]["brain"] = {
        "code": code, "side": side, "tier": tier, "score": score, "intent_id": intent_id
    }

    if side == "NO_TRADE" or code != 0:
        reason = intent.get("notes", {}).get("thesis", "no signal") if intent else "brain error"
        log(f"brain → NO_TRADE: {reason}")
        summary["outcome"] = "NO_TRADE"
        _append_signals_jsonl(intent_id, summary["ts"], score, tier, "NORMAL", "NO_TRADE" if side == "NO_TRADE" else "REJECT", None, dry_run)
        return summary

    log(f"brain → {side} {tier} score={score}")

    # ── Step 2: Sentinel risk evaluation ────────────────────────────────────
    code, stdout, stderr = run(
        [sys.executable, str(SENTINEL_DIR / "sentinel.py")],
        cwd=SENTINEL_DIR,
        timeout=30,
    )

    decision = parse_json_safe(stdout)
    kind = decision.get("kind", "ERROR") if decision else "ERROR"
    posture = decision.get("posture", "") if decision else ""
    summary["steps"]["sentinel"] = {"code": code, "kind": kind, "posture": posture}

    if kind != "ApprovedOrder":
        reason = decision.get("reason", "rejected") if decision else "sentinel error"
        log(f"sentinel → REJECT: {reason}")
        summary["outcome"] = "REJECTED"
        _append_signals_jsonl(intent_id, summary["ts"], score, tier, posture or "NORMAL", kind, None, dry_run)
        return summary

    log(f"sentinel → ApprovedOrder size={decision.get('size')} posture={decision.get('posture')}")

    # ── Step 3: Forge execution ────────────────────────────────────────────────
    # HARD GUARD: --paper MUST ONLY route to paper_broker.py — never to forge.py
    if paper:
        forge_script = FORGE_DIR / "paper_broker.py"
        forge_cmd = [sys.executable, str(forge_script)]
        # Paper mode uses only public Binance endpoints — warn if credentials are present
        for cred in ("BINANCE_API_KEY", "BINANCE_API_SECRET"):
            if os.environ.get(cred):
                log(f"WARNING: {cred} is set but --paper mode only uses public endpoints — credential is NOT used")
    else:
        forge_script = FORGE_DIR / "forge.py"
        forge_cmd = [sys.executable, str(forge_script)]
        if dry_run:
            forge_cmd.append("--dry-run")
    code, stdout, stderr = run(forge_cmd, cwd=FORGE_DIR, timeout=60)

    report = parse_json_safe(stdout)
    status = report.get("status", "ERROR") if report else "IDEMPOTENT_SKIP" if code == 0 and stdout and "IDEMPOTENT_SKIP" in stdout else "ERROR"
    summary["steps"]["forge"] = {"code": code, "status": status, "paper": paper}

    if status in ("FILLED", "COMPLETED", "OPENED", "CLOSED"):
        fills = report.get("fills", {})
        log(f"forge → {status} fill@{fills.get('avg_entry_price')} size={fills.get('filled_size')}")
        summary["outcome"] = "EXECUTED"
    else:
        log(f"forge → {status}")
        summary["outcome"] = f"FORGE_{status}"

    _append_signals_jsonl(intent_id, summary["ts"], score, tier, posture or "NORMAL", kind, status, dry_run)

    # ── Step 4: Log to field_notes ───────────────────────────────────────────
    note = f"cycle {side} {tier} score={score} → {kind} → forge={status}"
    run(
        [sys.executable, str(WORKSPACE / "skills" / "memory-append" / "scripts" / "append_field_note.py"),
         "--type", "OBSERVATION", "--note", note[:200]],
        cwd=WORKSPACE,
    )

    log(f"=== CYCLE END outcome={summary['outcome']} ===")
    return summary


def seconds_to_next_15m() -> float:
    """Return seconds until the next 15-minute boundary."""
    now = datetime.now(timezone.utc)
    minute = now.minute
    second = now.second
    microsecond = now.microsecond
    next_quarter = ((minute // 15) + 1) * 15
    delta_min = next_quarter - minute
    remaining_secs = delta_min * 60 - second - microsecond / 1_000_000
    return max(remaining_secs, 1.0)


def main():
    parser = argparse.ArgumentParser(description="15-minute cycle runner")
    parser.add_argument("--loop", action="store_true",
                        help="Run in loop mode, fire at each 15m boundary")
    parser.add_argument("--dry-run", action="store_true",
                        help="Run Forge in dry-run mode (no real orders)")
    parser.add_argument("--live", action="store_true",
                        help="Binance live execution (forge.py, no dry-run; requires BINANCE_API_KEY/SECRET)")
    parser.add_argument("--paper", action="store_true",
                        help="Phase A: run paper_broker.py instead of forge.py (no real orders)")
    args = parser.parse_args()
    if args.live:
        args.dry_run = False
        args.paper = False
    elif args.paper:
        # Paper mode: routes to paper_broker.py; disable dry_run so signals.jsonl is written
        args.dry_run = False
    else:
        # Unqualified run (no --live, no --paper): default to dry-run to prevent real orders
        args.dry_run = True

    if not args.loop:
        summary = run_cycle(dry_run=args.dry_run, paper=args.paper)
        print(json.dumps(summary, indent=2))
        return

    log(f"Loop mode started. dry_run={args.dry_run} paper={args.paper}")
    while True:
        wait = seconds_to_next_15m()
        log(f"Next cycle in {wait:.0f}s")
        time.sleep(wait)
        try:
            run_cycle(dry_run=args.dry_run, paper=args.paper)
        except Exception as e:
            log(f"ERROR in cycle: {e}")
        time.sleep(2)  # small buffer after boundary


if __name__ == "__main__":
    main()
