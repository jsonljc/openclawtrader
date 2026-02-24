#!/usr/bin/env python3
"""
staleness_check.py
Validates the freshness of a snapshot timestamp against wall clock.
Exits 0 if fresh, exits 2 if stale.

Usage:
    python3 staleness_check.py --ts 2025-01-15T14:23:01.123Z
    python3 staleness_check.py --ts 2025-01-15T14:23:01.123Z --threshold-ms 3000
"""

import argparse
import json
import sys
from datetime import datetime, timezone


def parse_iso(ts: str) -> datetime:
    """Parse ISO 8601 UTC timestamp. Accepts trailing Z."""
    ts = ts.replace("Z", "+00:00")
    return datetime.fromisoformat(ts)


def main():
    parser = argparse.ArgumentParser(description="Check snapshot timestamp staleness")
    parser.add_argument("--ts", required=True, help="ISO 8601 UTC timestamp from snapshot")
    parser.add_argument("--threshold-ms", type=int, default=5000,
                        help="Max acceptable age in ms (default: 5000)")
    args = parser.parse_args()

    try:
        snapshot_dt = parse_iso(args.ts)
    except ValueError as e:
        print(json.dumps({"status": "error", "reason": f"Invalid timestamp: {e}"}))
        sys.exit(1)

    now = datetime.now(timezone.utc)
    age_ms = (now - snapshot_dt).total_seconds() * 1000

    is_stale = age_ms > args.threshold_ms

    output = {
        "status": "stale" if is_stale else "ok",
        "ts": args.ts,
        "age_ms": round(age_ms, 2),
        "threshold_ms": args.threshold_ms,
        "checked_at": now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
    }

    print(json.dumps(output, indent=2))

    if is_stale:
        print(f"[staleness-check] STALE: age={round(age_ms)}ms exceeds threshold={args.threshold_ms}ms",
              file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
