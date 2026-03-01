#!/usr/bin/env python3
"""
status_console.py — C3PO read-only status reporter for Telegram.

Usage:
    python3 status_console.py status
    python3 status_console.py detail
    python3 status_console.py lasttrade

All functions are READ-ONLY. No writes to out/ or workspace files.
No execution paths (run_cycle, sentinel, forge) are touched.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# ── Path constants ────────────────────────────────────────────────────────────

OUT_DIR          = Path.home() / "openclaw-trader" / "out"
LATEST_PATH      = OUT_DIR / "latest.json"
RISK_DECISION    = OUT_DIR / "risk_decision.json"
EXEC_REPORT      = OUT_DIR / "execution_report.json"
EXEC_QUALITY     = OUT_DIR / "execution_quality.json"
POSTURE_STATE    = Path.home() / ".openclaw-elyra" / "workspace-sentinel" / "posture_state.json"
PAPER_POSITIONS  = Path.home() / ".openclaw-elyra" / "workspace-forge" / "forge" / "paper_positions.json"


# ── Safe I/O helpers ──────────────────────────────────────────────────────────

def read_json(path) -> dict | None:
    """Safely read and parse a JSON file. Returns None on any error."""
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return None


def tail_jsonl(path, n: int = 3) -> list[dict]:
    """Return the last n parsed lines of a JSONL file. Skips malformed lines."""
    path = Path(path)
    if not path.exists():
        return []
    lines = []
    try:
        with open(path, "r") as f:
            raw = f.readlines()
        for line in raw:
            line = line.strip()
            if not line:
                continue
            try:
                lines.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    except Exception:
        return []
    return lines[-n:]


def get_today_ledger_path() -> Path:
    """Return the path for today's (UTC) paper ledger file."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return OUT_DIR / f"paper_ledger_{today}.jsonl"


# ── Mode detection ────────────────────────────────────────────────────────────

def _detect_mode() -> str:
    """Detect PAPER / LIVE / UNKNOWN trading mode."""
    # 1. execution_report.kind is most authoritative
    er = read_json(EXEC_REPORT)
    if er:
        kind = er.get("kind", "")
        if kind == "PAPER":
            return "PAPER"
        if kind in ("LIVE", "BINANCE", "MARKET"):
            return "LIVE"

    # 2. Today's ledger file exists → paper mode
    if get_today_ledger_path().exists():
        return "PAPER"

    # 3. risk_decision carries venue info sometimes
    rd = read_json(RISK_DECISION)
    if rd:
        venue = rd.get("venue", "")
        if venue and venue.lower() not in ("binance", ""):
            return "LIVE"
        if rd.get("kind") in ("ApprovedOrder",) and get_today_ledger_path().exists():
            return "PAPER"

    return "UNKNOWN"


# ── Shared field extractors ───────────────────────────────────────────────────

def _posture_block(ps: dict | None) -> str:
    if ps is None:
        return "Posture: (missing)"
    posture = ps.get("posture", "UNKNOWN")
    halt = ps.get("halt_reason")
    if halt:
        return f"Posture: {posture} | halt={halt}"
    return f"Posture: {posture}"


def _position_block(pp: dict | None) -> str:
    if pp is None:
        return "Position: (missing)"
    pos = pp.get("position")
    if not pos:
        return "Position: NONE"
    side        = pos.get("side", "?")
    qty         = pos.get("qty", "?")
    entry       = pos.get("entry_price", "?")
    stop        = pos.get("stop_price", "?")
    tp          = pos.get("tp_price") or pos.get("take_profit_price", "?")
    return (
        f"Position: OPEN {side} {qty} BTC\n"
        f"  entry={entry}  stop={stop}  tp={tp}"
    )


def _last_action_block(er: dict | None) -> str:
    if er is None:
        return "Last action: (missing)"
    status      = er.get("status", "UNKNOWN")
    exit_reason = er.get("exit_reason", "")
    intent_id   = er.get("intent_id", "")
    short_id    = intent_id[:12] if intent_id else "?"
    ts          = er.get("closed_at_utc") or er.get("generated_at_utc") or ""
    ts_short    = ts[:16].replace("T", " ") if ts else "?"
    if exit_reason:
        return f"Last action: {status} ({exit_reason}) @ {ts_short} [{short_id}]"
    return f"Last action: {status} @ {ts_short} [{short_id}]"


def _pnl_block(ps: dict | None) -> str:
    if ps is None:
        return "PnL: (missing)"
    daily_loss  = ps.get("daily_loss_pct", 0.0) or 0.0
    cons_losses = ps.get("consecutive_losses", 0) or 0
    trades_today = ps.get("trades_today", 0) or 0

    # Today's realized PnL — sum ledger
    ledger_trades = tail_jsonl(get_today_ledger_path(), n=999)
    today_pnl = sum(t.get("realized_pnl_usd", 0) for t in ledger_trades if isinstance(t, dict))

    return (
        f"Today PnL: ${today_pnl:+.2f} USD  |  trades={trades_today}\n"
        f"Daily loss: {daily_loss:.2f}%  |  consec losses={cons_losses}"
    )


# ── Build functions ───────────────────────────────────────────────────────────

def build_status() -> str:
    """Default status — ~15 lines, Telegram friendly."""
    mode   = _detect_mode()
    ps     = read_json(POSTURE_STATE)
    pp     = read_json(PAPER_POSITIONS)
    er     = read_json(EXEC_REPORT)

    lines = [
        f"📊 OpenClaw Status  [{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC]",
        f"Mode: {mode}",
        _posture_block(ps),
        _position_block(pp),
        _last_action_block(er),
        _pnl_block(ps),
    ]
    return "\n".join(lines)


def build_detail() -> str:
    """Extended status — adds confidence, fill quality, candle time."""
    base = build_status()

    latest = read_json(LATEST_PATH)
    er     = read_json(EXEC_REPORT)
    eq     = read_json(EXEC_QUALITY)

    extras = ["", "── Detail ──────────────────"]

    # Confidence from latest intent
    if latest:
        intent = latest.get("intent", {})
        score = intent.get("confidence_score", latest.get("confidence", {}).get("score", "?"))
        tier  = intent.get("confidence_tier", latest.get("confidence", {}).get("tier", "?"))
        side  = intent.get("side", "?")
        extras.append(f"Last intent: {side}  score={score}  tier={tier}")
    else:
        extras.append("Last intent: (missing)")

    # Fill quality
    if eq:
        spread  = eq.get("spread_bps_at_entry", "?")
        slip    = eq.get("slippage_bps", "?")
        fvm     = eq.get("fill_vs_mid_bps", "?")
        extras.append(f"Spread: {spread} bps  |  slip={slip} bps  |  fill_vs_mid={fvm} bps")
    else:
        extras.append("Fill quality: (missing)")

    # Candle close time
    if er:
        cct = er.get("candle_close_time_utc", None)
        extras.append(f"Candle close UTC: {cct if cct else '(not logged)'}")
    else:
        extras.append("Candle close UTC: (missing)")

    return base + "\n" + "\n".join(extras)


def build_lasttrade() -> str:
    """Last closed trade from today's paper ledger."""
    ledger_path = get_today_ledger_path()
    trades = tail_jsonl(ledger_path, n=3)

    # Find most recent closed trade (all ledger entries are closed)
    if not trades:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return f"Last trade: no ledger entries for {today}"

    t = trades[-1]
    intent_id   = t.get("intent_id", "?")
    short_id    = intent_id[:16] if intent_id else "?"
    side        = t.get("side", "?")
    qty         = t.get("qty", "?")
    entry       = t.get("entry_price", "?")
    exit_p      = t.get("exit_price", "?")
    pnl         = t.get("realized_pnl_usd", "?")
    exit_r      = t.get("exit_reason", "?")
    closed_at   = t.get("closed_at_utc", "?")

    if isinstance(pnl, (int, float)):
        pnl_str = f"${pnl:+.4f}"
    else:
        pnl_str = str(pnl)

    closed_short = str(closed_at)[:16].replace("T", " ") if closed_at else "?"

    return (
        f"📋 Last Trade\n"
        f"ID: {short_id}\n"
        f"Side: {side}  Qty: {qty} BTC\n"
        f"Entry: {entry}  Exit: {exit_p}\n"
        f"PnL: {pnl_str} USD\n"
        f"Exit reason: {exit_r}\n"
        f"Closed: {closed_short} UTC"
    )


# ── Command dispatch ──────────────────────────────────────────────────────────

HELP_TEXT = "Commands: status | detail | lasttrade"

COMMAND_MAP = {
    "status":       build_status,
    "report":       build_status,   # /report is the safe Telegram slash alias (/status is reserved by openclaw)
    "paper status": build_status,
    "risk":         build_status,
    "position":     build_status,
    "detail":       build_detail,
    "lasttrade":    build_lasttrade,
    "last trade":   build_lasttrade,
}


def dispatch(raw_text: str) -> str:
    """
    Normalize and dispatch a Telegram message text to a build function.
    Returns the formatted reply string, or a help message for unknowns.
    """
    normalized = raw_text.strip().lower().lstrip("/")
    fn = COMMAND_MAP.get(normalized)
    if fn:
        return fn()
    return HELP_TEXT


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} status|detail|lasttrade", file=sys.stderr)
        print(HELP_TEXT)
        sys.exit(1)

    cmd = " ".join(sys.argv[1:]).strip().lower()
    print(dispatch(cmd))
