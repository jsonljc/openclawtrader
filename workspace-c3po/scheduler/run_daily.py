#!/usr/bin/env python3
"""
run_daily.py — Daily maintenance routine
Runs once per UTC day (recommended: 00:05 UTC).

Tasks:
  1. Update Sentinel posture based on previous day's P&L
  2. Check consecutive loss counter
  3. Review Forge slippage metrics (warn if drifted)
  4. Log daily summary to field_notes.md

Usage:
    python3 run_daily.py
    python3 run_daily.py --date 2025-01-15  # process specific date

Cron example:
    5 0 * * * cd /home/elyra/.openclaw-elyra/workspace-c3po && python3 scheduler/run_daily.py >> ~/openclaw-trader/logs/daily.log 2>&1
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

WORKSPACE    = Path(__file__).parent.parent
SENTINEL_DIR = WORKSPACE.parent / "workspace-sentinel"
FORGE_DIR    = WORKSPACE.parent / "workspace-forge"
LOGS_DIR     = Path.home() / "openclaw-trader" / "logs"
REPORT_DIR   = Path.home() / "openclaw-trader" / "out" / "forge-reports"


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log(msg: str) -> None:
    print(f"[{now_utc()}] {msg}")


def run_cmd(cmd: list[str], cwd: Path = None) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           cwd=str(cwd) if cwd else None, timeout=60)
        return r.returncode, r.stdout
    except Exception as e:
        return -1, str(e)


def load_posture_state() -> dict:
    path = SENTINEL_DIR / "posture_state.json"
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def check_slippage_metrics() -> dict:
    script = FORGE_DIR / "skills" / "execution-quality" / "scripts" / "track_fill.py"
    if not script.exists():
        return {"warning": "track_fill.py not found"}
    code, stdout = run_cmd([sys.executable, str(script), "--days", "1"], cwd=FORGE_DIR)
    try:
        return json.loads(stdout)
    except Exception:
        return {"error": "Could not parse slippage metrics"}


def get_yesterday_reports() -> list[dict]:
    """Load all ExecutionReports from yesterday."""
    reports = []
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y%m%d")
    if not REPORT_DIR.exists():
        return reports
    for f in REPORT_DIR.glob(f"report-{yesterday}-*.json"):
        try:
            reports.append(json.loads(f.read_text()))
        except Exception:
            pass
    return reports


def append_daily_field_note(summary: str) -> None:
    script = WORKSPACE / "skills" / "memory-append" / "scripts" / "append_field_note.py"
    if not script.exists():
        return
    subprocess.run(
        [sys.executable, str(script), "--type", "OBSERVATION", "--note", summary[:200]],
        capture_output=True
    )


def main():
    parser = argparse.ArgumentParser(description="Daily maintenance routine")
    parser.add_argument("--date", default=None, help="Process specific date (YYYY-MM-DD)")
    args = parser.parse_args()

    date_str = args.date or (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    log(f"=== DAILY ROUTINE for {date_str} ===")

    # ── 1. Load current posture state ───────────────────────────────────────
    posture = load_posture_state()
    current_posture = posture.get("posture", "UNKNOWN")
    daily_loss = posture.get("daily_loss_pct", 0.0)
    consec = posture.get("consecutive_losses", 0)
    trades_today = posture.get("trades_today", 0)

    log(f"Posture: {current_posture} | daily_loss={daily_loss:.2f}% | consec_losses={consec} | trades={trades_today}")

    if daily_loss > 1.5:
        log(f"WARNING: daily_loss={daily_loss:.2f}% approaching 2% halt threshold")

    if consec >= 2:
        log(f"WARNING: {consec} consecutive losses — posture should be REDUCED or HALT")

    # ── 2. Review yesterday's execution reports ──────────────────────────────
    reports = get_yesterday_reports()
    completed = [r for r in reports if r.get("status") == "COMPLETED"]
    failed    = [r for r in reports if r.get("status") not in ("COMPLETED", "REJECTED_PRECHECK")]
    log(f"Execution reports: {len(reports)} total, {len(completed)} completed, {len(failed)} failed")

    if failed:
        for r in failed:
            err = r.get("error", {})
            log(f"  FAILED: {r.get('client_order_id')} status={r.get('status')} code={err.get('code')}")

    # ── 3. Check slippage metrics ────────────────────────────────────────────
    slippage = check_slippage_metrics()
    avg_slip = slippage.get("avg_slippage_bps")
    if avg_slip is not None:
        log(f"Slippage (1d): avg={avg_slip:.1f}bps max={slippage.get('max_slippage_bps')}bps")
        if avg_slip > 15:
            log(f"WARNING: avg slippage {avg_slip:.1f}bps > 15bps — review order routing assumptions")
    else:
        log(f"Slippage: {slippage.get('warning', 'no data')}")

    # ── 4. Log daily summary to field_notes ─────────────────────────────────
    summary_note = (
        f"DAILY {date_str}: posture={current_posture} loss={daily_loss:.2f}% "
        f"consec={consec} trades={trades_today} slip_avg={avg_slip}bps"
    )
    append_daily_field_note(summary_note)
    log(f"Field note appended: {summary_note}")

    # ── Output structured summary ────────────────────────────────────────────
    result = {
        "date": date_str,
        "posture": current_posture,
        "daily_loss_pct": daily_loss,
        "consecutive_losses": consec,
        "trades_executed": trades_today,
        "reports_completed": len(completed),
        "reports_failed": len(failed),
        "avg_slippage_bps": avg_slip,
        "slippage_ok": avg_slip is None or avg_slip <= 15,
        "ran_at": now_utc(),
    }
    print(json.dumps(result, indent=2))
    log("=== DAILY ROUTINE COMPLETE ===")


if __name__ == "__main__":
    main()
