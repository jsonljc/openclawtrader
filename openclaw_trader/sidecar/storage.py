from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


_REPO_ROOT = Path(__file__).resolve().parents[2]
_DATA_DIR = Path(os.environ.get("OPENCLAW_DATA", _REPO_ROOT / "data")) / "sidecar"


def sidecar_path(name: str) -> Path:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    return _DATA_DIR / name


def write_json(name: str, payload: dict[str, Any]) -> Path:
    path = sidecar_path(name)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)
    return path


def read_json(name: str) -> dict[str, Any] | None:
    path = sidecar_path(name)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
