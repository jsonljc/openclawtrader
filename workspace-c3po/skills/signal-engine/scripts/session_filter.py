#!/usr/bin/env python3
"""
session_filter.py
Returns the current session window and its score adjustment per spec §8.
Hard BLOCK 22:00–07:00 UTC (dead zone). Otherwise score adjustment only.

Session windows (UTC):
  07:00–12:00  London open         → preferred,  status=PASS, adjustment =   0
  13:00–17:00  London/NY overlap   → preferred,  status=PASS, adjustment =   0
  12:00–13:00  Transition          → allowed,   status=PASS, adjustment =  -5
  17:00–22:00  NY / off-hours      → allowed,    status=PASS, adjustment = -10
  22:00–07:00  Dead zone           → BLOCK       status=BLOCK, exit 1 (no signals)

Output JSON (PASS):
  {"status": "PASS", "session": "...", "quality": "...", "score_adjustment": N, "hour_utc": N}

Output JSON (BLOCK):
  {"status": "BLOCK", "hour_utc": N, "session": "dead_zone", "reason": "..."}

Exit code: 0 = PASS, 1 = BLOCK
"""

import json
import sys
from datetime import datetime, timezone


# Dead zone: hard block (no new signals). §8.
BLOCK_START_HOUR = 22
BLOCK_END_HOUR   = 7   # exclusive end: 0..6 are blocked

# (start_hour_inclusive, end_hour_exclusive, name, quality, score_adjustment)
SESSIONS = [
    ( 7, 12, "london",         "preferred",  0),
    (12, 13, "transition",     "allowed",   -5),
    (13, 17, "london_ny",      "preferred",  0),
    (17, 22, "ny_offhours",    "allowed",  -10),
    (22, 24, "dead_zone",     "block",      0),
    ( 0,  7, "dead_zone",     "block",      0),
]


def get_session(hour: int) -> dict:
    for start, end, name, quality, adj in SESSIONS:
        if start <= hour < end:
            if quality == "block":
                return {
                    "status": "BLOCK",
                    "hour_utc": hour,
                    "session": name,
                    "reason": "Low liquidity window — no new signals (22:00–07:00 UTC)",
                }
            return {
                "status": "PASS",
                "session": name,
                "quality": quality,
                "score_adjustment": adj,
                "hour_utc": hour,
            }
    return {
        "status": "PASS",
        "session": "unknown",
        "quality": "avoid",
        "score_adjustment": -10,
        "hour_utc": hour,
    }


def main():
    hour = datetime.now(timezone.utc).hour
    result = get_session(hour)
    print(json.dumps(result))
    if result.get("status") == "BLOCK":
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
