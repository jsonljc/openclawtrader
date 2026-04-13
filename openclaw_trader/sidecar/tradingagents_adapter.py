from __future__ import annotations

import json
import os
import shlex
import subprocess
from datetime import datetime, timezone
from collections.abc import Mapping, Sequence
from typing import Any

from .models import TradingAgentsSignal


def _coerce_command(command: Sequence[str] | str) -> list[str]:
    if isinstance(command, str):
        return shlex.split(command)
    return list(command)


def _extract_json(stdout: str) -> dict[str, Any]:
    text = stdout.strip()
    if not text:
        raise RuntimeError("TradingAgents produced no JSON output")

    decoder = json.JSONDecoder()
    candidate_starts = [
        idx
        for idx, char in enumerate(text)
        if char in "{["
    ]
    for start in reversed(candidate_starts):
        try:
            parsed, end = decoder.raw_decode(text, idx=start)
        except json.JSONDecodeError:
            continue
        if text[end:].strip():
            continue
        if isinstance(parsed, dict):
            return parsed
        if isinstance(parsed, list):
            continue

    raise RuntimeError(f"TradingAgents stdout was not valid JSON: {stdout!r}")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def run_tradingagents(
    command: Sequence[str] | str,
    payload: Mapping[str, Any],
    *,
    cwd: str | None = None,
    env: Mapping[str, str] | None = None,
    timeout: float | None = None,
) -> TradingAgentsSignal:
    merged_env = dict(os.environ)
    if env is not None:
        merged_env.update(env)

    completed = subprocess.run(
        _coerce_command(command),
        input=json.dumps(dict(payload)),
        capture_output=True,
        text=True,
        cwd=cwd,
        env=merged_env,
        check=True,
        timeout=timeout,
    )

    parsed = _extract_json(completed.stdout)
    signal_payload: dict[str, Any]
    if isinstance(parsed.get("signal"), Mapping):
        signal_payload = dict(parsed["signal"])
        raw_payload = dict(parsed)
    else:
        signal_payload = dict(parsed)
        raw_payload = dict(parsed.get("raw_payload", parsed))

    signal_payload.setdefault("generated_at", _utc_now_iso())
    signal_payload["raw_payload"] = raw_payload
    return TradingAgentsSignal(**signal_payload)
