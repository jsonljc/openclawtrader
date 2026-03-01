#!/usr/bin/env python3
"""C3PO — Portfolio Strategist — spec Section 6.

Phase 1 scope:
- Single strategy: trend_reclaim_4H_ES
- Fixed risk (no regime scaling, no health scaling from ledger)
- Full proposal gating (all 9 gates)
- Full intent construction with stop/TP/sizing
- Micro-contract fallback
- All intent types emitted to ledger

Public API:
    run_brain(snapshots, run_id, param_version, watchtower_status) -> list[intent]
"""

from __future__ import annotations
import math
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))
from shared import contracts as C
from shared import identifiers as IDs
from shared import ledger
from shared import state_store as store


# ---------------------------------------------------------------------------
# Regime scoring stub (Phase 1: returns fixed neutral score)
# Phase 2 will replace with full computation from spec 6.4
# ---------------------------------------------------------------------------

def compute_regime(snapshot: dict, param_version: str = "PV_0001") -> dict:
    """
    Phase 1: return a neutral-to-risk-on regime report.
    The risk_multiplier is hardcoded to 1.0 (no scaling).
    Phase 2 will implement full sigmoid-weighted computation.
    """
    now = snapshot.get("asof", datetime.now(timezone.utc).isoformat())
    ind = snapshot.get("indicators", {})
    adx = ind.get("adx_14", 25.0)

    # Simple linear trend_score from ADX
    trend_score = min(1.0, adx / 50.0)

    return {
        "report_id":              f"RR_{now[:16].replace('-', '').replace('T', '_').replace(':', '')}",
        "run_id":                 "",
        "asof":                   now,
        "param_version":          param_version,
        "regime_score":           round(trend_score, 4),
        "confidence":             0.70,
        "effective_regime_score": round(trend_score, 4),
        "risk_multiplier":        1.0,
        "drivers": {
            "trend_score":       {"raw": trend_score, "weight": 0.35},
            "vol_percentile":    {"raw": 0.50,        "weight": 0.30},
            "corr_stress":       {"raw": 0.30,        "weight": 0.20},
            "liquidity_score":   {"raw": 0.85,        "weight": 0.15},
        },
        "mode_hint": "NEUTRAL" if trend_score < 0.4 else "NEUTRAL_TO_RISK_ON",
    }


# ---------------------------------------------------------------------------
# Strategy health stub (Phase 1: returns neutral health from ledger stats)
# Phase 2 will add full Sharpe/DD/hit-rate computation — spec 6.6
# ---------------------------------------------------------------------------

def evaluate_strategy_health(
    strategy: dict,
    param_version: str = "PV_0001",
) -> dict:
    """
    Phase 1: compute health from available POSITION_CLOSED events.
    Returns neutral defaults if fewer than 3 closed trades exist.
    """
    strategy_id = strategy.get("strategy_id", "")
    params      = store.load_params(param_version)
    hp          = params.get("health", {})
    now         = datetime.now(timezone.utc).isoformat()
    cutoff      = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()

    closes = [
        e for e in ledger.query(event_types=[C.EventType.POSITION_CLOSED], limit=500)
        if e.get("payload", {}).get("strategy_id") == strategy_id
        and e.get("timestamp", "") >= cutoff
    ]

    n = len(closes)
    min_trades = hp.get("min_trades_for_full_health", 10)

    if n < 3:
        health_score = 0.60
        capped       = True
        action       = C.HealthAction.NORMAL
        stats = {
            "realized_dd_pct":         0.0,
            "expected_dd_pct":         strategy.get("expected_max_dd_pct", 10.0),
            "realized_sharpe_30d":     0.0,
            "expected_sharpe":         strategy.get("expected_sharpe", 1.2),
            "realized_hit_rate_30d":   0.0,
            "expected_hit_rate":       strategy.get("expected_hit_rate", 0.45),
            "avg_slippage_ticks_30d":  1.0,
            "expected_slippage_ticks": strategy.get("expected_avg_slippage_ticks", 1.0),
            "trade_count_30d":         n,
            "profit_factor_30d":       1.0,
            "avg_win_loss_ratio":      1.0,
            "consecutive_losses_current": 0,
            "consecutive_losses_max_30d": 0,
        }
    else:
        pnls = [e["payload"].get("realized_pnl", 0.0) for e in closes]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        hit_rate   = len(wins) / n
        avg_win    = sum(wins) / len(wins)   if wins   else 0.0
        avg_loss   = abs(sum(losses) / len(losses)) if losses else 0.01
        wl_ratio   = avg_win / avg_loss

        # Sharpe approximation from daily PnL sequence (simplified)
        import statistics
        std  = statistics.stdev(pnls) if len(pnls) > 1 else 0.01
        mean = statistics.mean(pnls)
        sharpe = (mean / std * math.sqrt(252 / 20)) if std > 0 else 0.0

        pf = abs(sum(wins)) / abs(sum(losses)) if losses else 2.0

        # Drawdown from equity curve
        equity = 0.0
        peak   = 0.0
        max_dd = 0.0
        for p in pnls:
            equity += p
            peak    = max(peak, equity)
            dd      = (peak - equity) / peak * 100.0 if peak > 0 else 0.0
            max_dd  = max(max_dd, dd)

        # Consecutive losses
        consec = 0
        max_consec = 0
        for p in pnls:
            if p < 0:
                consec += 1
                max_consec = max(max_consec, consec)
            else:
                consec = 0

        # Health score per spec 6.6
        exp_dd      = strategy.get("expected_max_dd_pct", 10.0)
        exp_sharpe  = strategy.get("expected_sharpe", 1.2)
        exp_hr      = strategy.get("expected_hit_rate", 0.45)
        exp_slip    = strategy.get("expected_avg_slippage_ticks", 1.0)

        exec_quality_raw = store.load_exec_quality().get(strategy_id, {})
        avg_slip_30d     = exec_quality_raw.get("avg_realized_slippage_ticks_20", 1.0)

        dd_ratio    = max(0.0, min(1.0, 1.0 - max_dd / exp_dd)) if exp_dd > 0 else 1.0
        sharpe_rat  = max(0.0, min(1.0, sharpe / exp_sharpe))   if exp_sharpe > 0 else 0.5
        hr_ratio    = max(0.0, min(1.0, hit_rate / exp_hr))      if exp_hr > 0 else 0.5
        eq_ratio    = max(0.0, min(1.0, 1.0 - (avg_slip_30d - exp_slip) / (exp_slip + 0.001)))

        w = hp
        health_score = (
            w.get("weight_dd", 0.35)        * dd_ratio  +
            w.get("weight_sharpe", 0.25)    * sharpe_rat +
            w.get("weight_hit_rate", 0.20)  * hr_ratio  +
            w.get("weight_execution", 0.20) * eq_ratio
        )
        capped = n < min_trades
        if capped:
            health_score = min(health_score, 0.60)

        disable_thresh   = hp.get("disable_threshold", 0.30)
        half_thresh      = hp.get("half_size_threshold", 0.50)
        if health_score < disable_thresh:
            action = C.HealthAction.DISABLE
        elif health_score < half_thresh:
            action = C.HealthAction.HALF_SIZE
        else:
            action = C.HealthAction.NORMAL

        stats = {
            "realized_dd_pct":         round(max_dd, 4),
            "expected_dd_pct":         exp_dd,
            "realized_sharpe_30d":     round(sharpe, 4),
            "expected_sharpe":         exp_sharpe,
            "realized_hit_rate_30d":   round(hit_rate, 4),
            "expected_hit_rate":       exp_hr,
            "avg_slippage_ticks_30d":  round(avg_slip_30d, 2),
            "expected_slippage_ticks": exp_slip,
            "trade_count_30d":         n,
            "profit_factor_30d":       round(pf, 4),
            "avg_win_loss_ratio":      round(wl_ratio, 4),
            "consecutive_losses_current": consec,
            "consecutive_losses_max_30d": max_consec,
        }

    report = C.make_health_report(
        strategy_id=strategy_id,
        asof=now,
        param_version=param_version,
        health_score=health_score,
        health_score_capped=capped,
        action=action,
        components={},
        stats=stats,
    )
    return report


# ---------------------------------------------------------------------------
# Proposal gates — spec 6.7
# ---------------------------------------------------------------------------

def _check_gates(
    strategy: dict,
    health: dict,
    snapshot: dict,
    portfolio: dict,
    posture: str,
    wt_status: str,
    run_id: str,
) -> tuple[bool, list[str]]:
    """
    Check all 9 proposal gates.
    Returns (all_passed, list_of_failures).
    """
    failures: list[str] = []

    # Gate 1: Strategy status ACTIVE
    status = strategy.get("status", C.StrategyStatus.ACTIVE)
    if status != C.StrategyStatus.ACTIVE:
        failures.append(f"Gate 1: strategy status={status} (need ACTIVE)")

    # Gate 2: Health score >= min_health_score
    min_hs = strategy.get("min_health_score", 0.30)
    hs     = health.get("health_score", 0.60)
    if hs < min_hs:
        failures.append(f"Gate 2: health_score={hs:.2f} < min {min_hs}")

    # Gate 3: Health action != DISABLE (effective_regime_score check is Phase 2)
    if health.get("action") == C.HealthAction.DISABLE:
        failures.append("Gate 3: strategy health action=DISABLE")

    # Gate 4: Sentinel posture allows entries
    if posture in (C.Posture.DEFENSIVE, C.Posture.HALT):
        failures.append(f"Gate 4: posture={posture} blocks entries")

    # Gate 5: Session state allows entries
    session = snapshot.get("session_state", C.SessionState.CORE)
    if session in (C.SessionState.CLOSED, C.SessionState.POST_CLOSE, C.SessionState.PRE_OPEN):
        failures.append(f"Gate 5: session={session} — no new entries")

    # Gate 6: Days to expiry > roll window
    days_exp = snapshot.get("contract", {}).get("days_to_expiry", 999)
    roll_win  = strategy.get("roll_days_before_expiry", 5)
    if days_exp <= roll_win:
        failures.append(f"Gate 6: days_to_expiry={days_exp} <= roll_window={roll_win}")

    # Gate 7: Watchtower not HALT
    if wt_status == C.WatchtowerStatus.HALT:
        failures.append("Gate 7: Watchtower status=HALT")

    # Gate 8: No duplicate intent (no open position for same strategy+symbol+side already enforced
    # by Sentinel idempotency check; C3PO pre-screens here to avoid emitting unnecessary intents)
    strategy_id = strategy.get("strategy_id", "")
    symbol      = strategy.get("symbol", "")
    for pos in portfolio.get("positions", []):
        if pos.get("strategy_id") == strategy_id and pos.get("symbol") == symbol:
            failures.append(f"Gate 8: active position already exists for {strategy_id}/{symbol}")
            break

    # Gate 9: Data not stale
    if snapshot.get("data_quality", {}).get("is_stale", False):
        failures.append("Gate 9: snapshot is_stale=True")

    return len(failures) == 0, failures


# ---------------------------------------------------------------------------
# Signal: Trend Reclaim 4H — spec strategy signal_engine
# ---------------------------------------------------------------------------

def _evaluate_trend_reclaim_4H(
    snapshot: dict,
    strategy: dict,
) -> dict | None:
    """
    Entry signal: 4H close above MA20 with ADX > 25 and positive MA slope.
    Returns signal dict or None if no signal.
    """
    ind  = snapshot.get("indicators", {})
    bars = snapshot.get("bars", {})

    price     = ind.get("last_price")
    ma20      = ind.get("ma_20_value")
    ma50      = ind.get("ma_50_value")
    adx       = ind.get("adx_14", 0.0)
    ma_slope  = ind.get("ma_20_slope", 0.0)
    atr_4h    = ind.get("atr_14_4H", 40.0)
    atr_1h    = ind.get("atr_14_1H", 15.0)

    if price is None or ma20 is None:
        return None

    adx_min    = strategy.get("signal", {}).get("adx_min", 25)
    stop_mult  = strategy.get("signal", {}).get("stop_atr_multiple", 1.5)
    tp_mult    = strategy.get("signal", {}).get("tp_atr_multiple", 1.5)

    # LONG: price above MA20, ADX confirming trend, positive slope
    if price > ma20 and adx >= adx_min and ma_slope > 0:
        stop_dist = atr_1h * stop_mult
        tp_dist   = atr_1h * tp_mult
        return {
            "side":       "BUY",
            "stop_price": round(price - stop_dist, 2),
            "tp_price":   round(price + tp_dist, 2),
            "stop_dist":  round(stop_dist, 4),
            "tp_dist":    round(tp_dist, 4),
            "atr_used":   atr_1h,
            "direction":  "LONG",
        }

    # SHORT: price below MA20, ADX confirming trend, negative slope
    if price < ma20 and adx >= adx_min and ma_slope < 0:
        stop_dist = atr_1h * stop_mult
        tp_dist   = atr_1h * tp_mult
        return {
            "side":       "SELL",
            "stop_price": round(price + stop_dist, 2),
            "tp_price":   round(price - tp_dist, 2),
            "stop_dist":  round(stop_dist, 4),
            "tp_dist":    round(tp_dist, 4),
            "atr_used":   atr_1h,
            "direction":  "SHORT",
        }

    return None


# ---------------------------------------------------------------------------
# Sizing (Steps 1–4 + incubation) — spec Section 10
# Phase 1: no regime/health multipliers; posture mod applied by Sentinel
# ---------------------------------------------------------------------------

def _suggest_sizing(
    strategy: dict,
    health: dict,
    snapshot: dict,
    signal: dict,
    equity: float,
) -> dict:
    """Compute C3PO's sizing suggestion (before Sentinel applies posture mod)."""
    base_risk_pct = strategy.get("risk_budget_pct", 0.50)
    base_risk_usd = equity * base_risk_pct / 100.0

    # Health modifier
    health_mod = {
        C.HealthAction.NORMAL:    1.0,
        C.HealthAction.HALF_SIZE: 0.5,
        C.HealthAction.DISABLE:   0.0,
    }.get(health.get("action", C.HealthAction.NORMAL), 1.0)

    # Session modifier
    session = snapshot.get("session_state", C.SessionState.CORE)
    session_mod = 0.5 if session == C.SessionState.EXTENDED else 1.0

    # Incubation modifier
    incub = strategy.get("incubation", {})
    incub_mod = (incub.get("incubation_size_pct", 5) / 100.0) if incub.get("is_incubating") else 1.0

    final_risk_usd = base_risk_usd * health_mod * session_mod * incub_mod

    # Contract sizing
    stop_dist_pts  = signal["stop_dist"]
    point_val      = strategy.get("point_value_usd", 50.0)
    micro_pv       = strategy.get("micro_point_value_usd", 5.0)
    micro_avail    = strategy.get("micro_available", False)

    risk_per_c     = stop_dist_pts * point_val
    contracts      = math.floor(final_risk_usd / risk_per_c) if risk_per_c > 0 else 0
    use_micro      = False

    if contracts == 0 and micro_avail:
        micro_risk = stop_dist_pts * micro_pv
        contracts  = math.floor(final_risk_usd / micro_risk) if micro_risk > 0 else 0
        use_micro  = contracts > 0

    actual_pv     = micro_pv if use_micro else point_val
    risk_at_stop  = stop_dist_pts * actual_pv * max(1, contracts)
    risk_pct      = risk_at_stop / equity * 100.0 if equity > 0 else 0.0

    return {
        "risk_per_contract_usd":   round(stop_dist_pts * actual_pv, 2),
        "contracts_suggested":     max(1, contracts),
        "use_micro":               use_micro,
        "risk_pct_suggested":      round(base_risk_pct, 4),
        "risk_pct_after_health":   round(base_risk_pct * health_mod * session_mod * incub_mod, 4),
        "risk_multiplier_regime":  1.0,
        "risk_multiplier_health":  health_mod,
        "risk_multiplier_session": session_mod,
        "final_risk_usd":          round(final_risk_usd, 2),
    }


# ---------------------------------------------------------------------------
# Build intent — spec 5.6
# ---------------------------------------------------------------------------

def _build_intent(
    strategy: dict,
    signal: dict,
    sizing: dict,
    snapshot: dict,
    regime: dict,
    health: dict,
    run_id: str,
    param_version: str,
) -> dict:
    now       = datetime.now(timezone.utc)
    intent_id = IDs.make_intent_id()
    session   = snapshot.get("session_state", C.SessionState.CORE)
    price     = snapshot.get("indicators", {}).get("last_price", 0.0)
    adx       = snapshot.get("indicators", {}).get("adx_14", 0.0)
    ma20      = snapshot.get("indicators", {}).get("ma_20_value", 0.0)

    tick_size = strategy.get("tick_size", 0.25)

    stop_price = signal["stop_price"]
    tp_price   = signal["tp_price"]
    stop_dist  = signal["stop_dist"]
    tp_dist    = signal["tp_dist"]

    # Expiry: next 15-min boundary
    slot_start = now.replace(minute=(now.minute // 15) * 15, second=0, microsecond=0)
    expires_at = slot_start + timedelta(minutes=15)

    thesis = (
        f"4H close {'above' if signal['side'] == 'BUY' else 'below'} MA20 ({ma20:.2f})"
        f" with ADX {adx:.1f} > {strategy['signal']['adx_min']};"
        f" price {price:.2f} {'reclaiming trend structure' if signal['side'] == 'BUY' else 'breaking below'};"
        f" session={session}; health={health['health_score']:.2f} {health['action']}"
    )

    sym  = strategy.get("micro_symbol") if sizing.get("use_micro") else strategy.get("symbol", "ES")
    pv   = strategy.get("micro_point_value_usd") if sizing.get("use_micro") else strategy.get("point_value_usd", 50.0)
    tv   = strategy.get("micro_tick_value_usd") if sizing.get("use_micro") else strategy.get("tick_value_usd", 12.50)

    return {
        "intent_id":    intent_id,
        "run_id":       run_id,
        "param_version": param_version,
        "strategy_id":  strategy["strategy_id"],
        "intent_type":  C.IntentType.ENTRY,
        "symbol":       sym,
        "contract_month": strategy.get("contract_month", ""),
        "side":         signal["side"],
        "thesis":       thesis,
        "entry_plan":   {"type": "MARKET", "price": price},
        "stop_plan": {
            "type":                  "STOP_MARKET",
            "price":                 stop_price,
            "distance_points":       round(stop_dist, 4),
            "distance_ticks":        int(stop_dist / tick_size),
            "distance_atr_multiple": round(stop_dist / signal["atr_used"], 4),
        },
        "take_profit_plan": {
            "type":                "LIMIT",
            "price":               tp_price,
            "distance_points":     round(tp_dist, 4),
            "distance_ticks":      int(tp_dist / tick_size),
            "reward_risk_ratio":   round(tp_dist / stop_dist, 4) if stop_dist > 0 else 0.0,
        },
        "sizing": sizing,
        "time_in_force":            "GTC",
        "session_state_at_creation": session,
        "created_at":               now.isoformat(),
        "expires_at":               expires_at.isoformat(),
        "state":                    C.IntentState.PROPOSED,
    }


# ---------------------------------------------------------------------------
# Roll intent — spec 6.10
# ---------------------------------------------------------------------------

def _build_roll_intent(
    strategy: dict,
    position: dict,
    snapshot: dict,
    run_id: str,
    param_version: str,
) -> dict:
    intent_id = IDs.make_intent_id()
    sym = strategy.get("symbol", "ES")
    cur_month  = strategy.get("contract_month", "")
    # Phase 1: next contract month is a placeholder; Phase 2 adds calendar lookup
    next_month = cur_month + "_NEXT"

    return {
        "intent_id":     intent_id,
        "run_id":        run_id,
        "param_version": param_version,
        "strategy_id":   strategy["strategy_id"],
        "intent_type":   C.IntentType.ROLL,
        "symbol":        sym,
        "roll_from":     position.get("contract_month", cur_month),
        "roll_to":       next_month,
        "current_contracts": position.get("contracts", 1),
        "side":          "BUY" if position.get("side") == "LONG" else "SELL",
        "estimated_calendar_spread_usd": None,
        "estimated_roll_cost_total_usd": None,
        "reason":        f"{strategy.get('roll_days_before_expiry', 5)} days to expiry; standard roll window",
        "created_at":    datetime.now(timezone.utc).isoformat(),
        "state":         C.IntentState.PROPOSED,
    }


# ---------------------------------------------------------------------------
# Signal dispatch table
# ---------------------------------------------------------------------------

_SIGNAL_HANDLERS = {
    "trend_reclaim_4H_ES":  _evaluate_trend_reclaim_4H,
    "trend_reclaim_4H_NQ":  _evaluate_trend_reclaim_4H,
    "trend_reclaim_4H_BTC": _evaluate_trend_reclaim_4H,
}


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_brain(
    snapshots: dict[str, dict],
    run_id: str,
    param_version: str = "PV_0001",
    watchtower_status: str = C.WatchtowerStatus.HEALTHY,
) -> list[dict]:
    """
    Run the C3PO evaluation cycle.
    Returns list of trade intents to pass to Sentinel.
    """
    registry  = store.load_strategy_registry()
    portfolio = store.load_portfolio()
    posture_state = store.load_posture_state()
    posture   = posture_state.get("posture", C.Posture.NORMAL)
    equity    = portfolio["account"]["equity_usd"]

    intents: list[dict] = []

    for strategy_id, strategy in registry.items():
        if strategy.get("status") not in (C.StrategyStatus.ACTIVE, C.StrategyStatus.INCUBATING):
            continue

        symbol = strategy.get("symbol", "ES")
        micro  = strategy.get("micro_symbol")
        snap   = snapshots.get(symbol) or snapshots.get(micro) or next(iter(snapshots.values()), None)
        if snap is None:
            continue

        # Compute regime and health reports
        regime = compute_regime(snap, param_version)
        health = evaluate_strategy_health(strategy, param_version)

        # Log reports
        ledger.append(C.EventType.REGIME_COMPUTED, run_id, regime["report_id"], regime)
        ledger.append(C.EventType.HEALTH_COMPUTED, run_id,
                      f"HLT_{strategy_id}", health)

        # Gate check
        gates_ok, gate_failures = _check_gates(
            strategy, health, snap, portfolio, posture, watchtower_status, run_id
        )
        if not gates_ok:
            continue  # Log failure reason without intent

        # Check for rollover
        days_exp = snap.get("contract", {}).get("days_to_expiry", 999)
        roll_win = strategy.get("roll_days_before_expiry", 5)
        if days_exp <= roll_win:
            for pos in portfolio.get("positions", []):
                if pos.get("strategy_id") == strategy_id:
                    roll = _build_roll_intent(strategy, pos, snap, run_id, param_version)
                    ledger.append(C.EventType.INTENT_CREATED, run_id, roll["intent_id"], roll)
                    intents.append(roll)
            continue  # No new entries when rolling

        # Evaluate signal
        handler = _SIGNAL_HANDLERS.get(strategy_id)
        if handler is None:
            continue
        signal = handler(snap, strategy)
        if signal is None:
            continue  # No signal this cycle

        # Size the trade
        sizing = _suggest_sizing(strategy, health, snap, signal, equity)
        if sizing.get("contracts_suggested", 0) == 0:
            continue

        # Build and log intent
        intent = _build_intent(strategy, signal, sizing, snap, regime, health,
                               run_id, param_version)
        ledger.append(C.EventType.INTENT_CREATED, run_id, intent["intent_id"], intent)
        intents.append(intent)

    return intents
