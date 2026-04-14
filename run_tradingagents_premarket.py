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
from openclaw_trader.sidecar.storage import read_json, write_json
from openclaw_trader.sidecar.tradingagents_adapter import run_tradingagents
from openclaw_trader.sidecar.models import SessionPlaybook
from shared import contracts as C
from shared import ledger
from shared.event_calendar import get_calendar
from shared.identifiers import make_run_id
from shared.state_store import load_strategy_registry


def _session_date_for(now_utc: datetime) -> str:
    return now_utc.astimezone(ET).date().isoformat()


def _strategy_symbol_aliases(strategy: Mapping[str, Any]) -> tuple[str, ...]:
    aliases: list[str] = []
    for key in ("symbol", "micro_symbol"):
        value = strategy.get(key)
        if isinstance(value, str) and value and value not in aliases:
            aliases.append(value)
    symbols = strategy.get("symbols")
    if isinstance(symbols, (list, tuple, set)):
        for value in symbols:
            if isinstance(value, str) and value and value not in aliases:
                aliases.append(value)
    return tuple(aliases)


def _strategy_matches_symbol(strategy: Mapping[str, Any], symbol: str) -> bool:
    return symbol in _strategy_symbol_aliases(strategy)


def _active_strategies(symbol: str) -> list[dict[str, Any]]:
    registry = load_strategy_registry()
    active: list[dict[str, Any]] = []
    for strategy in registry.values():
        if strategy.get("status") != C.StrategyStatus.ACTIVE:
            continue
        if not _strategy_matches_symbol(strategy, symbol):
            continue
        active.append(dict(strategy))
    return active


def _recent_trades(limit: int = 50) -> list[dict[str, Any]]:
    if limit <= 0:
        return []

    event_types = [
        C.EventType.ORDER_FILLED,
        C.EventType.ORDER_PARTIALLY_FILLED,
        C.EventType.POSITION_CLOSED,
    ]
    chunk_size = max(limit, 1_000)
    since_seq = 0
    trades: list[dict[str, Any]] = []

    while True:
        batch = ledger.query(
            event_types=event_types,
            since_seq=since_seq,
            limit=chunk_size,
        )
        if not batch:
            break
        trades.extend(batch)
        last_seq = batch[-1].get("ledger_seq")
        if not isinstance(last_seq, int):
            break
        since_seq = last_seq
        if len(batch) < chunk_size:
            break

    return trades[-limit:]


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


def _parse_utc_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _load_retained_playbook(
    *,
    session_date: str,
    symbol: str,
    now_utc: datetime,
) -> SessionPlaybook | None:
    payload = read_json(_symbol_sidecar_name("session_playbook", symbol))
    if payload is None:
        return None

    try:
        playbook = SessionPlaybook(**payload)
    except Exception:
        return None

    if playbook.session_date != session_date or playbook.symbol != symbol:
        return None
    if _parse_utc_timestamp(playbook.expires_at) < now_utc:
        return None

    return playbook


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
    retained_playbook = None
    if signal is None:
        retained_playbook = _load_retained_playbook(
            session_date=resolved_session_date,
            symbol=resolved_symbol,
            now_utc=now_utc,
        )
    playbook = retained_playbook or compile_session_playbook(
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
