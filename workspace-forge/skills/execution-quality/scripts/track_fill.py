#!/usr/bin/env python3
"""
track_fill.py
Reads forge/execution_quality.json and produces a rolling summary
for Sentinel's daily review. Aggregates slippage, fill quality, and fees.

Usage:
    python3 track_fill.py
    python3 track_fill.py --quality-file /path/to/execution_quality.json
    python3 track_fill.py --days 7
"""

import argparse
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

DEFAULT_QUALITY_FILE = Path(__file__).parent.parent.parent.parent / "forge" / "execution_quality.json"


def parse_iso(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def summarize(records: list, days: int) -> dict:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    recent = [r for r in records if parse_iso(r["ts"]) >= cutoff]

    if not recent:
        return {
            "period_days": days,
            "trade_count": 0,
            "avg_slippage_bps": None,
            "max_slippage_bps": None,
            "p95_slippage_bps": None,
            "avg_fill_vs_mid": None,
            "total_fees_usd": None,
            "dry_run_count": 0,
            "live_count": 0,
            "warning": "No records in period",
        }

    slippages  = [r["slippage_bps"] for r in recent if r.get("slippage_bps") is not None]
    fill_mids  = [r["fill_vs_mid"]   for r in recent if r.get("fill_vs_mid")   is not None]
    fees       = [r.get("fees_usd", 0) or 0 for r in recent]
    dry_runs   = sum(1 for r in recent if r.get("dry_run"))
    live       = len(recent) - dry_runs

    slippages_sorted = sorted(slippages)
    p95_idx = int(len(slippages_sorted) * 0.95) if slippages else 0

    warnings = []
    if slippages and max(slippages) > 30:
        warnings.append(f"MAX slippage {max(slippages):.1f}bps > 30bps threshold")
    avg_slip = sum(slippages) / len(slippages) if slippages else 0
    if avg_slip > 15:
        warnings.append(f"AVG slippage {avg_slip:.1f}bps > 15bps — review order routing")

    return {
        "period_days": days,
        "trade_count": len(recent),
        "dry_run_count": dry_runs,
        "live_count": live,
        "avg_slippage_bps": round(avg_slip, 3) if slippages else None,
        "max_slippage_bps": round(max(slippages), 3) if slippages else None,
        "p95_slippage_bps": round(slippages_sorted[p95_idx], 3) if slippages_sorted else None,
        "avg_fill_vs_mid": round(sum(fill_mids) / len(fill_mids), 2) if fill_mids else None,
        "total_fees_usd": round(sum(fees), 4),
        "slippage_assumption_ok": avg_slip <= 15,
        "warnings": warnings,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def main():
    parser = argparse.ArgumentParser(description="Summarize Forge execution quality metrics")
    parser.add_argument("--quality-file", default=None,
                        help="Path to execution_quality.json")
    parser.add_argument("--days", type=int, default=7,
                        help="Rolling window in days (default: 7)")
    args = parser.parse_args()

    quality_path = Path(args.quality_file) if args.quality_file else DEFAULT_QUALITY_FILE

    if not quality_path.exists():
        print(json.dumps({
            "trade_count": 0,
            "warning": f"No execution quality file at {quality_path}",
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }, indent=2))
        return

    try:
        records = json.loads(quality_path.read_text())
        if not isinstance(records, list):
            records = []
    except Exception as e:
        print(json.dumps({"error": f"Could not load quality file: {e}"}))
        sys.exit(1)

    summary = summarize(records, args.days)
    print(json.dumps(summary, indent=2))

    if summary.get("warnings"):
        for w in summary["warnings"]:
            print(f"[track-fill] WARNING: {w}", file=sys.stderr)


if __name__ == "__main__":
    main()
