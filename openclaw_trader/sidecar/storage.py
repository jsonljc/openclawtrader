from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any


_REPO_ROOT = Path(__file__).resolve().parents[2]
_DATA_DIR = Path(os.environ.get("OPENCLAW_DATA", _REPO_ROOT / "data")) / "sidecar"


def sidecar_path(name: str) -> Path:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    return _DATA_DIR / name


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


def write_json(name: str, payload: Any) -> Path:
    path = sidecar_path(name)
    tmp = path.with_suffix(path.suffix + ".tmp")
    normalized = _normalize_json_value(payload)
    tmp.write_text(json.dumps(normalized, indent=2), encoding="utf-8")
    tmp.replace(path)
    return path


def read_json(name: str) -> dict[str, Any] | None:
    path = sidecar_path(name)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
