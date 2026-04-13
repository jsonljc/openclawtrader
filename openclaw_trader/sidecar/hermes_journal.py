from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .storage import sidecar_path


_JOURNAL_NAME = "hermes_journal.jsonl"


def _normalize_json_value(value: Any) -> Any:
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _normalize_json_value(value.to_dict())
    if isinstance(value, Mapping):
        return {key: _normalize_json_value(inner) for key, inner in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_normalize_json_value(inner) for inner in value]
    if hasattr(value, "__dict__") and not isinstance(value, type):
        return _normalize_json_value(vars(value))
    return value


def _journal_path() -> Path:
    return sidecar_path(_JOURNAL_NAME)


def append_journal_entry(kind: str, payload: Any) -> Path:
    path = _journal_path()
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "kind": kind,
        "payload": _normalize_json_value(payload),
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, separators=(",", ":"), sort_keys=True, default=str) + "\n")
    return path


def read_journal_entries(kind: str | None = None) -> list[dict[str, Any]]:
    path = _journal_path()
    if not path.exists():
        return []

    rows: list[dict[str, Any]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        if kind is None or row.get("kind") == kind:
            rows.append(row)
    return rows
