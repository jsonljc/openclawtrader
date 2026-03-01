#!/usr/bin/env python3
"""
run_weekly.py — Weekly maintenance routine
Runs once per week (recommended: Sunday 01:00 UTC).

Tasks:
  1. Run walk-forward backtest (90-day train / 30-day test)
  2. Compute edge metrics
  3. Write EDGE_HEALTH.json → Sentinel reads on next run
  4. Review fill quality metrics (7-day window)
  5. Log weekly summary to field_notes.md
  6. Operator review prompt (summary printed to stdout)

Usage:
    python3 run_weekly.py
    python3 run_weekly.py --demo    # use synthetic backtest data

Cron example:
    0 1 * * 0 cd /home/elyra/.openclaw-elyra/workspace-c3po && python3 scheduler/run_weekly.py >> ~/openclaw-trader/logs/weekly.log 2>&1
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE    = Path(__file__).parent.parent
FORGE_DIR    = WORKSPACE.parent / "workspace-forge"
SIGNAL_LOG   = Path.home() / "openclaw-trader" / "out" / "c3po-log"
EDGE_HEALTH  = Path.home() / "openclaw-trader" / "out" / "EDGE_HEALTH.json"
LOGS_DIR     = Path.home() / "openclaw-trader" / "logs"

EDGE_SCRIPTS = WORKSPACE / "skills" / "edge-health" / "scripts"
QUALITY_SCRIPT = FORGE_DIR / "skills" / "execution-quality" / "scripts" / "track_fill.py"
MEMORY_SCRIPT  = WORKSPACE / "skills" / "memory-append" / "scripts" / "append_field_note.py"


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log(msg: str) -> None:
    line = f"[{now_utc()}] {msg}"
    print(line)
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOGS_DIR / "weekly.log", "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def run_cmd(cmd: list[str], cwd: Path = None) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           cwd=str(cwd) if cwd else None, timeout=120)
        return r.returncode, r.stdout
    except Exception as e:
        return -1, str(e)


def parse_json_safe(text: str) -> dict | None:
    try:
        return json.loads(text)
    except Exception:
        return None


def append_field_note(note: str) -> None:
    if not MEMORY_SCRIPT.exists():
        return
    subprocess.run(
        [sys.executable, str(MEMORY_SCRIPT), "--type", "OBSERVATION", "--note", note[:200]],
        capture_output=True
    )


def main():
    parser = argparse.ArgumentParser(description="Weekly maintenance routine")
    parser.add_argument("--demo", action="store_true",
                        help="Use synthetic backtest data (no real signal log required)")
    args = parser.parse_args()

    log("=== WEEKLY ROUTINE START ===")
    results = {"ran_at": now_utc(), "steps": {}}

    # ── Step 1: Walk-forward backtest ────────────────────────────────────────
    log("Running walk-forward backtest...")
    bt_args = [
        sys.executable, str(EDGE_SCRIPTS / "run_backtest.py"),
        "--signal-log-dir", str(SIGNAL_LOG),
        "--out", "/tmp/backtest_result.json",
    ]
    if args.demo:
        bt_args.append("--demo")

    code, stdout = run_cmd(bt_args, cwd=WORKSPACE)
    bt_result = parse_json_safe(stdout)
    n_trades = bt_result.get("signal_count", 0) if bt_result else 0
    log(f"Backtest: {n_trades} trades analyzed (exit={code})")
    results["steps"]["backtest"] = {"ok": code == 0, "signal_count": n_trades}

    if code != 0:
        log("ERROR: backtest failed — aborting weekly routine")
        sys.exit(1)

    # ── Step 2: Compute edge metrics ─────────────────────────────────────────
    log("Computing edge metrics...")
    code, stdout = run_cmd([
        sys.executable, str(EDGE_SCRIPTS / "compute_edge_metrics.py"),
        "--backtest-file", "/tmp/backtest_result.json",
        "--out", "/tmp/edge_metrics.json",
    ], cwd=WORKSPACE)

    metrics = parse_json_safe(stdout)
    if metrics and not metrics.get("error"):
        exp = metrics.get("expectancy_r", 0)
        wr  = metrics.get("win_rate", 0)
        dd  = metrics.get("max_drawdown_r", 0)
        log(f"Metrics: expectancy={exp:.3f}R win_rate={wr:.1%} max_dd={dd:.1f}R")
        results["steps"]["metrics"] = {"ok": True, "expectancy_r": exp, "win_rate": wr, "max_dd_r": dd}
    else:
        log("ERROR: metrics computation failed")
        results["steps"]["metrics"] = {"ok": False}

    # ── Step 3: Write EDGE_HEALTH.json ───────────────────────────────────────
    log("Writing EDGE_HEALTH.json...")
    code, stdout = run_cmd([
        sys.executable, str(EDGE_SCRIPTS / "write_edge_health.py"),
        "--metrics-file", "/tmp/edge_metrics.json",
        "--out", str(EDGE_HEALTH),
    ], cwd=WORKSPACE)

    eh = parse_json_safe(stdout)
    degrade = eh.get("degrade_flag", False) if eh else False
    posture_rec = eh.get("recommended_posture", "UNKNOWN") if eh else "UNKNOWN"
    log(f"EDGE_HEALTH: degrade_flag={degrade} recommended_posture={posture_rec}")
    results["steps"]["edge_health"] = {"ok": code == 0, "degrade_flag": degrade, "recommended_posture": posture_rec}

    if degrade:
        log(f"WARNING: degrade_flag=true. Sentinel will move to {posture_rec} on next run.")
        for r in (eh.get("degrade_reason") or []):
            log(f"  - {r}")

    # ── Step 4: Review fill quality (7-day) ──────────────────────────────────
    if QUALITY_SCRIPT.exists():
        log("Checking 7-day fill quality...")
        code, stdout = run_cmd([
            sys.executable, str(QUALITY_SCRIPT), "--days", "7"
        ], cwd=FORGE_DIR)
        quality = parse_json_safe(stdout)
        if quality:
            avg_slip = quality.get("avg_slippage_bps")
            log(f"Fill quality (7d): trades={quality.get('trade_count')} avg_slip={avg_slip}bps")
            results["steps"]["fill_quality"] = quality
            if quality.get("warnings"):
                for w in quality["warnings"]:
                    log(f"  SLIPPAGE WARNING: {w}")
    else:
        log("Skip fill quality — track_fill.py not found")

    # ── Step 5: Log to field_notes ───────────────────────────────────────────
    exp_val = results.get("steps", {}).get("metrics", {}).get("expectancy_r", 0)
    wr_val  = results.get("steps", {}).get("metrics", {}).get("win_rate", 0)
    note = (
        f"WEEKLY: exp={exp_val:.3f}R wr={wr_val:.1%} degrade={degrade} "
        f"rec_posture={posture_rec} trades={n_trades}"
    )
    append_field_note(note)
    log(f"Field note appended: {note}")

    # ── Step 6: Operator summary ─────────────────────────────────────────────
    print("\n" + "="*60)
    print("WEEKLY SYSTEM REVIEW — OPERATOR REQUIRED")
    print("="*60)
    print(f"Date:            {now_utc()}")
    print(f"Backtest trades: {n_trades}")
    if metrics and not metrics.get("error"):
        print(f"Expectancy:      {metrics.get('expectancy_r'):.3f}R")
        print(f"Win rate:        {metrics.get('win_rate'):.1%}")
        print(f"Max drawdown:    {metrics.get('max_drawdown_r'):.1f}R")
        print(f"Sharpe (approx): {metrics.get('sharpe_approx'):.2f}")
    print(f"Edge degrade:    {'YES — review field_notes.md' if degrade else 'No'}")
    print(f"Sentinel posture (rec): {posture_rec}")
    print(f"EDGE_HEALTH.json: {EDGE_HEALTH}")
    print(f"\nAction required: Review field_notes.md for this week's lessons.")
    print("="*60 + "\n")

    results["edge_degrade"] = degrade
    print(json.dumps(results, indent=2))

    log("=== WEEKLY ROUTINE COMPLETE ===")
    sys.exit(0 if not degrade else 2)  # exit 2 signals degradation to cron monitoring


if __name__ == "__main__":
    main()
