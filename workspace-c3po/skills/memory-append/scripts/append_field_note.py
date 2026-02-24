#!/usr/bin/env python3
"""
append_field_note.py
Appends a single timestamped log line to c3po/field_notes.md.
Write-only. Never reads existing content. Rotates if file > 5MB.

Usage:
    python3 append_field_note.py --type REGIME --note "ELEVATED vol 78th pct, TREND_DOWN 4h"
    python3 append_field_note.py --type HALT --note "EXTREME volatility, posture halted"
    python3 append_field_note.py --notes-file /path/to/c3po/field_notes.md --type SIGNAL --note "..."
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

VALID_TYPES = {"REGIME", "SIGNAL", "MISS", "FALSE_POSITIVE", "STALE_SKIP", "HALT", "OBSERVATION", "ERROR"}
MAX_NOTE_LEN = 200
MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024  # 5MB
DEFAULT_NOTES_FILE = "c3po/field_notes.md"
HEADER = "# C3PO Field Notes\n<!-- append-only log — do not edit manually -->\n\n"


def get_notes_path(override: str | None) -> str:
    if override:
        return override
    # scripts/ -> memory-append/ -> skills/ -> workspace-c3po/ -> c3po/field_notes.md
    script_dir = os.path.dirname(os.path.abspath(__file__))
    candidate = os.path.normpath(os.path.join(script_dir, "..", "..", "..", DEFAULT_NOTES_FILE))
    if os.path.exists(os.path.dirname(candidate)):
        return candidate
    return DEFAULT_NOTES_FILE


def rotate_if_needed(notes_path: str) -> bool:
    """Rotate notes file if > MAX_FILE_SIZE_BYTES. Returns True if rotated."""
    if not os.path.exists(notes_path):
        return False
    if os.path.getsize(notes_path) < MAX_FILE_SIZE_BYTES:
        return False

    today = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    archive_path = notes_path.replace(".md", f"_archive_{today}.md")
    os.rename(notes_path, archive_path)
    print(f"[memory-append] Rotated {notes_path} → {archive_path}", file=sys.stderr)
    return True


def ensure_file(notes_path: str):
    """Create the file with header if it doesn't exist."""
    dir_path = os.path.dirname(notes_path)
    if dir_path:
        os.makedirs(dir_path, exist_ok=True)
    if not os.path.exists(notes_path):
        with open(notes_path, "w") as f:
            f.write(HEADER)
        print(f"[memory-append] Created {notes_path}", file=sys.stderr)


def format_line(ts: str, note_type: str, note: str) -> str:
    padded_type = note_type.ljust(15)
    return f"{ts} | {padded_type} | {note}\n"


def main():
    parser = argparse.ArgumentParser(description="Append a field note to c3po/field_notes.md")
    parser.add_argument("--type", required=True, choices=sorted(VALID_TYPES),
                        help=f"Note type. One of: {', '.join(sorted(VALID_TYPES))}")
    parser.add_argument("--note", required=True, help=f"Note text (max {MAX_NOTE_LEN} chars)")
    parser.add_argument("--notes-file", default=None,
                        help="Override path to field_notes.md")
    args = parser.parse_args()

    note = args.note.strip()
    if len(note) > MAX_NOTE_LEN:
        print(json.dumps({
            "error": f"Note too long: {len(note)} chars (max {MAX_NOTE_LEN})",
            "note_preview": note[:80] + "...",
        }))
        sys.exit(1)

    notes_path = get_notes_path(args.notes_file)
    rotate_if_needed(notes_path)
    ensure_file(notes_path)

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    line = format_line(ts, args.type, note)

    with open(notes_path, "a") as f:
        f.write(line)

    result = {
        "status": "ok",
        "appended": line.rstrip(),
        "notes_file": notes_path,
        "ts": ts,
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
