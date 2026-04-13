#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).parent
sys.path.insert(0, str(_ROOT))

try:
    import zoneinfo

    ET = zoneinfo.ZoneInfo("America/New_York")
except ImportError:
    ET = timezone(timedelta(hours=-5))

from openclaw_trader.sidecar.policy_compiler import compile_session_playbook
from openclaw_trader.sidecar.hermes_journal import append_journal_entry
from openclaw_trader.sidecar.storage import write_json
from openclaw_trader.sidecar.tradingagents_adapter import run_tradingagents
from shared import contracts as C
from shared import ledger
from shared.event_calendar import get_calendar
from shared.identifiers import make_run_id
from shared.state_store import load_strategy_registry


def _session_date_for(now_utc: datetime) -> str:
    return now_utc.astimezone(ET).date().isoformat()


def _active_strategies(symbol: str) -> list[dict[str, Any]]:
    registry = load_strategy_registry()
    active: list[dict[str, Any]] = []
    for strategy in registry.values():
        if strategy.get("status") != C.StrategyStatus.ACTIVE:
            continue
        strategy_symbol = strategy.get("symbol")
        if strategy_symbol is not None and strategy_symbol != symbol:
            symbols = strategy.get("symbols")
            if not isinstance(symbols, (list, tuple, set)) or symbol not in symbols:
                continue
        active.append(dict(strategy))
    return active


def _recent_trades(limit: int = 50) -> list[dict[str, Any]]:
    return ledger.query(
        event_types=[
            C.EventType.ORDER_FILLED,
            C.EventType.ORDER_PARTIALLY_FILLED,
            C.EventType.POSITION_CLOSED,
        ],
        limit=limit,
    )


def build_runner_summary(playbook_dict: Mapping[str, Any]) -> str:
    setup_bans = len(playbook_dict.get("disallowed_setups", []))
    blocked_windows = len(playbook_dict.get("blocked_windows_et", []))
    summary = f"playbook ready: {setup_bans} setup bans, {blocked_windows} blocked windows"
    fallback_reason = playbook_dict.get("fallback_reason")
    if fallback_reason:
        summary += f" (baseline fallback: {fallback_reason})"
    return summary


def build_runner_payload(session_date: str, symbol: str, now_utc: datetime | None = None) -> dict[str, Any]:
    current_utc = now_utc or datetime.now(timezone.utc)
    calendar = get_calendar()
    return {
        "session_date": session_date,
        "symbol": symbol,
        "upcoming_events": calendar.upcoming_events(now_utc=current_utc, hours_ahead=24),
        "recent_trades": _recent_trades(),
        "active_strategies": _active_strategies(symbol),
    }


def _symbol_sidecar_name(prefix: str, symbol: str) -> str:
    return f"{prefix}_{symbol}.json"


def run_tradingagents_premarket(
    *,
    session_date: str | None = None,
    symbol: str | None = None,
    command: Sequence[str] | str | None = None,
) -> dict[str, Any]:
    now_utc = datetime.now(timezone.utc)
    resolved_session_date = session_date or _session_date_for(now_utc)
    resolved_symbol = symbol or os.environ.get("OPENCLAW_SYMBOL", "MNQ")
    resolved_command = command or os.environ.get("OPENCLAW_TRADINGAGENTS_COMMAND")
    if not resolved_command:
        raise RuntimeError("OPENCLAW_TRADINGAGENTS_COMMAND is required")

    run_id = make_run_id()
    payload = build_runner_payload(resolved_session_date, resolved_symbol, now_utc=now_utc)
    try:
        signal = run_tradingagents(command=resolved_command, payload=payload)
    except Exception:
        signal = None
    playbook = compile_session_playbook(
        session_date=resolved_session_date,
        symbol=resolved_symbol,
        signal=signal,
    )

    signal_dict = signal.to_dict() if signal is not None else None
    playbook_dict = playbook.to_dict()
    signal_path = None
    if signal_dict is not None:
        signal_path = write_json(
            _symbol_sidecar_name("tradingagents_signal", resolved_symbol),
            signal_dict,
        )
    playbook_path = write_json(
        _symbol_sidecar_name("session_playbook", resolved_symbol),
        playbook_dict,
    )
    summary = build_runner_summary(playbook_dict)
    try:
        append_journal_entry(
            "tradingagents_premarket",
            {
                "session_date": resolved_session_date,
                "symbol": resolved_symbol,
                "summary": summary,
                "signal": signal_dict,
                "playbook": playbook_dict,
            },
        )
    except Exception:
        pass

    ledger.append(
        C.EventType.SESSION_PLAYBOOK_PUBLISHED,
        run_id,
        f"{resolved_session_date}:{resolved_symbol}",
        {
            "session_date": resolved_session_date,
            "symbol": resolved_symbol,
            "summary": summary,
            "signal": signal_dict,
            "playbook": playbook_dict,
            "signal_path": str(signal_path) if signal_path is not None else None,
            "playbook_path": str(playbook_path),
        },
    )

    print(summary)
    return {
        "run_id": run_id,
        "session_date": resolved_session_date,
        "symbol": resolved_symbol,
        "summary": summary,
        "signal_path": str(signal_path) if signal_path is not None else None,
        "playbook_path": str(playbook_path),
        "signal": signal_dict,
        "playbook": playbook_dict,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="TradingAgents premarket runner")
    parser.add_argument("--session-date", default=None)
    parser.add_argument("--symbol", default=None)
    parser.add_argument("--command", default=None)
    args = parser.parse_args()

    run_tradingagents_premarket(
        session_date=args.session_date,
        symbol=args.symbol,
        command=args.command,
    )


if __name__ == "__main__":
    main()
