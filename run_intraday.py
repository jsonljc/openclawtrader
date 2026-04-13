#!/usr/bin/env python3
"""Intraday orchestrator — OpenClaw V2 — 5-minute cycle loop.

Runs during RTH (9:30-16:00 ET) with:
    - Setup scanning every 5 minutes
    - Regime re-classification every 15 minutes
    - Bracket monitoring every 5 minutes

Coexists with run_cycle.py (4H swing strategies).

Modes:
    full        One complete intraday cycle: Structure → Session → Regime → Scan → Sentinel → Forge
    loop        Continuous 5-minute loop during RTH
    reconcile   Bracket check + MTM only

Usage:
    python run_intraday.py --mode full
    python run_intraday.py --mode loop
    python run_intraday.py --mode full --force-signal  # dev/test
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_ROOT = Path(__file__).parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "workspace-c3po"))
sys.path.insert(0, str(_ROOT / "workspace-sentinel"))
sys.path.insert(0, str(_ROOT / "workspace-forge"))
sys.path.insert(0, str(_ROOT / "workspace-watchtower"))

from shared import contracts as C
from shared import identifiers as IDs
from shared import ledger
from shared import state_store as store
from shared.correlation import update_portfolio_heat_correlations
from openclaw_trader.sidecar.storage import read_json

# Optional: Redis for reading news signals (NEWS_DIRECTIONAL scanner).
try:
    import redis as _redis_mod
    from openclaw_trader.signals.signal_publisher import read_active_signals as _read_active_signals
    _HAS_REDIS = True
except ImportError:
    _HAS_REDIS = False

import sentinel
import forge
import watchtower
import posture
from data_source import get_all_snapshots
from session import detect_intra_session, get_session_report, IntraSession, is_rth, is_any_rth
from structure import compute_structure
from regime_intraday import classify_regime
from scorer import score_opportunity

try:
    import zoneinfo as _zoneinfo

    _ET = _zoneinfo.ZoneInfo("America/New_York")
except ImportError:  # pragma: no cover
    _ET = timezone.utc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_session_playbook(session_date: str) -> dict:
    playbook = read_json("session_playbook.json") or {}
    if playbook.get("session_date") != session_date:
        return {"disallowed_setups": [], "blocked_windows_et": []}
    return playbook


def _blocked_by_playbook(
    playbook: dict,
    setup_family: str,
    current_et_hhmm: str,
) -> tuple[bool, str | None]:
    if setup_family in set(playbook.get("disallowed_setups", [])):
        return False, "setup_disallowed"
    for window in playbook.get("blocked_windows_et", []):
        if window["start"] <= current_et_hhmm < window["end"]:
            return False, "window_blocked"
    return True, None


# Track signal IDs already traded to enforce one-trade-per-event (Section 16).
# Resets daily when the date changes.
_traded_signal_ids: set[str] = set()
_traded_signal_date: str = ""


def _log(msg: str) -> None:
    print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {msg}")


# ---------------------------------------------------------------------------
# Intraday setup scanners
# ---------------------------------------------------------------------------

def _scan_setups(
    snapshots: dict[str, dict],
    regime_report: dict,
    session_report: dict,
    structure_levels: dict[str, dict],
    run_id: str,
    param_version: str,
    force_signal: bool = False,
) -> list[dict]:
    """
    Run all intraday setup scanners and return trade intents.
    Each scanner returns SetupCandidate | None.
    """
    from setups.orb import detect as detect_orb
    from setups.vwap_reclaim import detect as detect_vwap
    from setups.trend_pullback import detect as detect_trend_pullback
    from setups.news_directional import detect as detect_news

    intents: list[dict] = []
    registry = store.load_strategy_registry()
    current_et = datetime.now(timezone.utc).astimezone(_ET)
    session_date = current_et.date().isoformat()
    playbook = _load_session_playbook(session_date)
    current_et_hhmm = current_et.strftime("%H:%M")

    # Intraday strategies to scan
    intraday_strategies = {
        sid: cfg for sid, cfg in registry.items()
        if cfg.get("timeframe") == "5m" and cfg.get("status") == "ACTIVE"
    }

    for strategy_id, strategy in intraday_strategies.items():
        symbol = strategy.get("symbol", "ES")
        snapshot = snapshots.get(symbol)
        if not snapshot:
            continue

        setup_family = strategy.get("signal", {}).get("setup_family", "")
        levels = structure_levels.get(symbol)

        # Collect 5m bars from snapshot
        bars_5m = snapshot.get("bars", {}).get("5m", [])

        # Common inputs
        detect_kwargs = {
            "regime": regime_report,
            "session": session_report,
            "structure": levels,
            "bars_5m": bars_5m,
            "snapshot": snapshot,
            "strategy": strategy,
        }

        candidate = None
        if setup_family == "ORB":
            candidate = detect_orb(**detect_kwargs)
        elif setup_family == "VWAP":
            candidate = detect_vwap(**detect_kwargs)
        elif setup_family == "TREND_PULLBACK":
            candidate = detect_trend_pullback(**detect_kwargs)
        elif setup_family == "NEWS_DIRECTIONAL":
            _news_signals = []
            if _HAS_REDIS:
                try:
                    _rc = _redis_mod.from_url(
                        os.environ.get("REDIS_URL", "redis://localhost:6379"),
                        decode_responses=True,
                    )
                    raw = _read_active_signals(_rc, "news_signals", count=50)
                    _news_signals = [
                        s for s in raw
                        if symbol in s.get("instruments", [])
                        and s.get("tier", "").startswith("DIRECTIONAL")
                    ]
                except Exception:
                    pass
            detect_kwargs["signals"] = _news_signals
            global _traded_signal_ids, _traded_signal_date
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            if _traded_signal_date != today:
                _traded_signal_ids = set()
                _traded_signal_date = today
            detect_kwargs["traded_signal_ids"] = _traded_signal_ids
            candidate = detect_news(**detect_kwargs)

        if candidate is None:
            continue

        allowed, block_reason = _blocked_by_playbook(playbook, setup_family, current_et_hhmm)
        if not allowed:
            ledger.append(
                C.EventType.INTRADAY_SETUP_BLOCKED,
                run_id,
                strategy_id,
                {
                    "strategy_id": strategy_id,
                    "symbol": symbol,
                    "setup_family": setup_family,
                    "block_reason": block_reason,
                    "bar_ts": bars_5m[-1].get("t") if bars_5m else "",
                    "entry_price": candidate["entry_price"],
                    "stop_price": candidate["stop_price"],
                    "target_price": candidate["target_price"],
                },
            )
            _log(f"  Setup {setup_family}/{symbol} blocked by playbook ({block_reason})")
            continue

        # Record traded signal ID for one-trade-per-event dedup
        if setup_family == "NEWS_DIRECTIONAL" and candidate.get("signal_id"):
            _traded_signal_ids.add(candidate["signal_id"])

        # Score the opportunity
        score = score_opportunity(
            candidate=candidate,
            regime=regime_report,
            structure=levels,
        )
        if score["total"] < 50:
            _log(f"  Setup {setup_family}/{symbol} scored {score['total']} < 50 — skipped")
            continue

        # Build trade intent
        intent = {
            "intent_id": IDs.make_intent_id(),
            "intent_type": C.IntentType.ENTRY,
            "strategy_id": strategy_id,
            "symbol": symbol,
            "side": candidate["side"],
            "contract_month": strategy.get("contract_month", ""),
            "param_version": param_version,
            "created_at": _utcnow(),
            "entry_plan": {
                "price": candidate["entry_price"],
                "order_type": "LIMIT",
            },
            "stop_plan": {
                "price": candidate["stop_price"],
            },
            "take_profit_plan": {
                "price": candidate["target_price"],
            },
            "sizing": {
                "contracts_suggested": 1,
                "use_micro": strategy.get("use_micro", True),
            },
            "setup_metadata": {
                "setup_family": setup_family,
                "score": score,
                "regime_type": regime_report.get("regime_type", "NEUTRAL"),
                "session": session_report.get("session", ""),
                "time_exit_minutes": strategy.get("signal", {}).get("time_exit_minutes"),
            },
            "max_hold_bars": strategy.get("max_hold_bars", 24),
        }
        # Propagate scale-out plan from setup scanner
        if candidate.get("scale_out_plan"):
            intent["scale_out_plan"] = candidate["scale_out_plan"]
        intents.append(intent)
        _log(f"  Setup detected: {setup_family} {symbol} {candidate['side']} "
             f"entry={candidate['entry_price']:.2f} stop={candidate['stop_price']:.2f} "
             f"target={candidate['target_price']:.2f} score={score['total']}")

    # Log intents to ledger
    for intent in intents:
        ledger.append(C.EventType.INTENT_CREATED, run_id, intent["intent_id"], intent)

    return intents


# ---------------------------------------------------------------------------
# Full intraday cycle
# ---------------------------------------------------------------------------

def run_intraday_cycle(
    run_id: str,
    param_version: str = "PV_0001",
    paper: bool = True,
    force_signal: bool = False,
    cycle_count: int = 0,
) -> dict:
    """
    One complete intraday cycle:
    1. Session check
    2. Watchtower health
    3. Structure levels
    4. Regime classification (every 3rd cycle = 15 min)
    5. Setup scanning
    6. Sentinel risk check
    7. Forge execution
    8. Bracket monitoring
    """
    t0 = time.perf_counter()
    now_utc = datetime.now(timezone.utc)
    _log(f"[INTRADAY] {run_id} cycle={cycle_count}")

    # 1. Session (use ES as primary session reference for the RTH gate;
    #    per-instrument sessions checked in setup scanners)
    session_report = get_session_report(now_utc, symbol="ES")
    session = session_report["session"]
    _log(f"  Session: {session} (modifier={session_report['modifier']}, "
         f"minutes_in={session_report['minutes_into_session']})")

    any_rth_active = is_any_rth(now_utc)
    if not any_rth_active and not force_signal:
        return {"run_id": run_id, "status": "OUTSIDE_RTH", "session": session}
    if force_signal and not any_rth_active:
        # Override session for dev/test — simulate MORNING_DRIVE
        session_report["is_rth"] = True
        session_report["session"] = "MORNING_DRIVE"
        session_report["modifier"] = 1.0
        session_report["minutes_into_session"] = 60
        session = "MORNING_DRIVE"
        _log("  [FORCE] Overriding session to MORNING_DRIVE for testing")

    # 2. Market data
    try:
        snapshots = get_all_snapshots(force_signal=force_signal)
    except Exception as exc:
        _log(f"  FATAL: data fetch failed: {exc}")
        ledger.append(C.EventType.ALERT, run_id, "INTRADAY", {
            "alert_type": "DATA_FETCH_ERROR", "error": str(exc),
        })
        return {"run_id": run_id, "status": "ERROR", "reason": f"Data fetch: {exc}"}

    # 3. Posture update
    portfolio = store.load_portfolio()
    try:
        posture.update_posture(portfolio, param_version, run_id)
    except Exception as exc:
        _log(f"  ERROR in posture: {exc}")

    # 4. Watchtower
    try:
        health = watchtower.run_health_check(snapshots, run_id)
    except Exception as exc:
        _log(f"  ERROR in watchtower: {exc}")
        return {"run_id": run_id, "status": "ERROR", "reason": f"Watchtower: {exc}"}

    if health["status"] == C.WatchtowerStatus.HALT:
        _log("  HALT: stopping cycle")
        return {"run_id": run_id, "status": "HALTED"}

    # 5. Structure levels
    structure_levels = {}
    registry = store.load_strategy_registry()
    # Build symbol → tick_size map from registry
    sym_tick = {}
    for cfg in registry.values():
        sym = cfg.get("symbol", "ES")
        if sym not in sym_tick:
            sym_tick[sym] = cfg.get("tick_size", 0.25)
    for symbol in snapshots:
        bars_5m = snapshots[symbol].get("bars", {}).get("5m", [])
        bars_daily = snapshots[symbol].get("bars", {}).get("1D", [])
        tick_size = sym_tick.get(symbol, 0.25)
        levels = compute_structure(bars_5m, bars_daily, now_utc, symbol=symbol, tick_size=tick_size)
        structure_levels[symbol] = levels.to_dict()

    # 6. Regime classification (every 15 min = every 3rd cycle)
    regime_state = store.load_state("intraday_regime") or {}
    do_regime = (cycle_count % 3 == 0) or not regime_state
    if do_regime:
        for symbol in snapshots:
            regime_report = classify_regime(
                snapshot=snapshots[symbol],
                structure=structure_levels.get(symbol, {}),
                session=session_report,
            )
            regime_state[symbol] = regime_report
        store.save_state("intraday_regime", regime_state)
        parts = [f"{s}={r.get('regime_type', '?')}" for s, r in regime_state.items()]
        _log(f"  Regime: {' | '.join(parts)}")

    # Use first symbol's regime as default
    default_regime = next(iter(regime_state.values()), {})

    # 7. Bracket monitoring (every cycle)
    closed = []
    if paper:
        try:
            closed = forge.process_bracket_triggers(snapshots, run_id, paper=paper)
            if closed:
                _log(f"  Brackets triggered: {len(closed)}")
                for c in closed:
                    _log(f"    → CLOSED {c['position_id']} via {c['trigger']} PnL=${c['realized_pnl']:.2f}")
                portfolio = store.load_portfolio()
        except Exception as exc:
            _log(f"  ERROR in bracket triggers: {exc}")
    else:
        # Live mode: IB position reconciliation + bracket verification
        portfolio = store.load_portfolio()
        if portfolio.get("positions"):
            try:
                recon = forge.run_reconciliation_ib(run_id)
                _log(f"  IB reconciliation: {'OK' if recon['reconciled'] else 'MISMATCH'}")
            except Exception as exc:
                _log(f"  ERROR in IB reconciliation: {exc}")

            try:
                bracket_report = forge.verify_ib_brackets(run_id)
                _log(f"  IB bracket check: {bracket_report['status']}")
            except Exception as exc:
                _log(f"  ERROR in IB bracket check: {exc}")

    # 8. Setup scanning
    intents = _scan_setups(
        snapshots=snapshots,
        regime_report=default_regime,
        session_report=session_report,
        structure_levels=structure_levels,
        run_id=run_id,
        param_version=param_version,
        force_signal=force_signal,
    )

    if not intents:
        elapsed = time.perf_counter() - t0
        return {
            "run_id": run_id, "status": "NO_SIGNAL",
            "session": session, "brackets_closed": len(closed),
            "cycle_sec": round(elapsed, 2),
        }

    # 9. Sentinel
    try:
        approvals = sentinel.run_sentinel(
            intents, snapshots, run_id, param_version,
            regime_report=default_regime,
        )
    except Exception as exc:
        _log(f"  ERROR in sentinel: {exc}")
        return {"run_id": run_id, "status": "ERROR", "reason": f"Sentinel: {exc}"}

    approved_list = [a for a in approvals
                     if a["decision"] in (C.RiskDecision.APPROVE, C.RiskDecision.APPROVE_REDUCED)]
    _log(f"  Sentinel: {len(approved_list)}/{len(approvals)} approved")

    if not approved_list:
        elapsed = time.perf_counter() - t0
        return {
            "run_id": run_id, "status": "DENIED",
            "intents": len(intents), "approvals": 0,
            "cycle_sec": round(elapsed, 2),
        }

    # 10. Forge
    try:
        intents_by_id = {i["intent_id"]: i for i in intents}
        receipts = forge.run_forge(approved_list, intents_by_id, snapshots, run_id, paper=paper)
    except Exception as exc:
        _log(f"  ERROR in forge: {exc}")
        return {"run_id": run_id, "status": "ERROR", "reason": f"Forge: {exc}"}

    _log(f"  Forge: {len(receipts)} executions")

    # Update correlations
    portfolio = store.load_portfolio()
    update_portfolio_heat_correlations(portfolio)

    elapsed = time.perf_counter() - t0
    return {
        "run_id": run_id,
        "status": "OK",
        "session": session,
        "intents": len(intents),
        "approvals": len(approved_list),
        "executions": len(receipts),
        "brackets_closed": len(closed),
        "cycle_sec": round(elapsed, 2),
    }


# ---------------------------------------------------------------------------
# Continuous loop
# ---------------------------------------------------------------------------

def _run_intraday_recon(run_id: str, paper: bool = True) -> None:
    """
    Fast 2-minute reconciliation: bracket triggers + MTM only.
    No setup scanning or regime classification.
    """
    try:
        snapshots = get_all_snapshots()
    except Exception as exc:
        _log(f"  [RECON] Data fetch failed: {exc}")
        return

    portfolio = store.load_portfolio()
    positions = portfolio.get("positions", [])
    if not positions:
        return

    if paper:
        try:
            closed = forge.process_bracket_triggers(snapshots, run_id, paper=True)
            if closed:
                _log(f"  [RECON] Brackets triggered: {len(closed)}")
                for c in closed:
                    _log(f"    -> CLOSED {c['position_id']} via {c['trigger']} PnL=${c['realized_pnl']:.2f}")
                portfolio = store.load_portfolio()
                positions = portfolio.get("positions", [])
        except Exception as exc:
            _log(f"  [RECON] Bracket error: {exc}")

    # MTM update
    for pos in positions:
        sym = pos.get("symbol", "")
        snap = snapshots.get(sym, {})
        if not snap:
            continue
        price = snap.get("indicators", {}).get("last_price")
        if price is None:
            bars = snap.get("bars", {}).get("1H", [])
            price = bars[-1]["c"] if bars else pos["entry_price"]
        pos["current_price"] = price
        side = pos.get("side", "LONG")
        entry = pos.get("entry_price", price)
        contracts = pos.get("contracts", 1)
        pv = pos.get("point_value_usd", 50.0)
        if side == "LONG":
            unrealized = (price - entry) * pv * contracts
        else:
            unrealized = (entry - price) * pv * contracts
        pos["unrealized_pnl_usd"] = round(unrealized, 2)

    store.save_portfolio(portfolio)


def run_intraday_loop(
    param_version: str = "PV_0001",
    paper: bool = True,
    force_signal: bool = False,
    cycle_interval_sec: int = 300,  # 5 minutes
    recon_interval_sec: int = 120,  # 2 minutes
) -> None:
    """
    Continuous loop during RTH with two cadences:
    - Full intraday cycle every 5 minutes (setup scanning + regime + sentinel + forge)
    - Fast reconciliation every 2 minutes (bracket triggers + MTM only)
    Exits when RTH ends or on keyboard interrupt.
    """
    _log("[LOOP] Starting intraday loop")
    cycle_count = 0
    last_full_cycle = 0.0
    last_recon = 0.0

    while True:
        now_utc = datetime.now(timezone.utc)
        now_ts = time.time()

        if not is_any_rth(now_utc):
            _log("[LOOP] Outside RTH (all instruments) — waiting...")
            time.sleep(60)
            continue

        # Determine whether to run full cycle or recon
        time_since_full = now_ts - last_full_cycle
        time_since_recon = now_ts - last_recon

        if time_since_full >= cycle_interval_sec or last_full_cycle == 0:
            # Full intraday cycle
            run_id = IDs.make_run_id()
            ledger.append(C.EventType.SYSTEM_START, run_id, run_id, {
                "mode": "intraday",
                "param_version": param_version,
                "paper": paper,
                "cycle": cycle_count,
            })

            try:
                result = run_intraday_cycle(
                    run_id=run_id,
                    param_version=param_version,
                    paper=paper,
                    force_signal=force_signal,
                    cycle_count=cycle_count,
                )
                _log(f"[LOOP] Cycle {cycle_count} result: {result.get('status')}")
            except Exception as exc:
                _log(f"[LOOP] Cycle {cycle_count} error: {exc}")
                result = {"status": "ERROR", "reason": str(exc)}

            ledger.append(C.EventType.SYSTEM_STOP, run_id, run_id, {
                "mode": "intraday",
                "cycle": cycle_count,
                "result": result.get("status", "?"),
            })

            cycle_count += 1
            last_full_cycle = time.time()
            last_recon = last_full_cycle  # full cycle includes recon

        elif time_since_recon >= recon_interval_sec:
            # Fast 2-minute reconciliation only
            run_id = IDs.make_run_id()
            _log(f"[RECON] Running 2-min reconciliation")
            _run_intraday_recon(run_id, paper=paper)
            last_recon = time.time()

        # Sleep until next action needed
        next_full = last_full_cycle + cycle_interval_sec
        next_recon = last_recon + recon_interval_sec
        next_action = min(next_full, next_recon)
        sleep_time = max(1, next_action - time.time())
        time.sleep(sleep_time)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="OpenClaw V2 — Intraday cycle runner")
    parser.add_argument(
        "--mode", choices=["full", "loop", "reconcile"],
        default="full", help="Cycle mode (default: full)"
    )
    parser.add_argument("--paper", action="store_true", default=True)
    parser.add_argument("--no-paper", action="store_true", default=False)
    parser.add_argument("--param-version", default=None)
    parser.add_argument("--force-signal", action="store_true", default=False)
    parser.add_argument("--cycle-interval", type=int, default=300,
                        help="Seconds between cycles in loop mode (default: 300)")

    args = parser.parse_args()

    if args.param_version:
        param_version = args.param_version
    else:
        portfolio = store.load_portfolio()
        param_version = portfolio.get("param_version", "PV_0001")

    paper = args.paper and not args.no_paper
    run_id = IDs.make_run_id()

    if args.mode == "full":
        ledger.append(C.EventType.SYSTEM_START, run_id, run_id, {
            "mode": "intraday_full",
            "param_version": param_version,
            "paper": paper,
        })

        result = run_intraday_cycle(
            run_id=run_id,
            param_version=param_version,
            paper=paper,
            force_signal=args.force_signal,
        )

        ledger.append(C.EventType.SYSTEM_STOP, run_id, run_id, {
            "mode": "intraday_full",
            "result": result.get("status", "?"),
        })

        _log(f"Done — {result}")

    elif args.mode == "loop":
        try:
            run_intraday_loop(
                param_version=param_version,
                paper=paper,
                force_signal=args.force_signal,
                cycle_interval_sec=args.cycle_interval,
            )
        except KeyboardInterrupt:
            _log("[LOOP] Interrupted — shutting down")

    elif args.mode == "reconcile":
        from run_cycle import run_reconciliation
        result = run_reconciliation(run_id, param_version, paper)
        _log(f"Done — {result}")


if __name__ == "__main__":
    main()
