#!/usr/bin/env python3
"""Write-ahead state persistence for all durable system state — spec Section 3.1.

All state is written to disk before the action it describes so crash
recovery can always reconstruct a consistent state.

File layout (under OPENCLAW_DATA, default ~/openclaw-trader/data/):
    portfolio.json
    posture_state.json
    pending_intents.json
    exec_quality.json

Strategy registry and parameter files live in the repo under:
    strategies/<strategy_id>.json
    params/<version>.json
"""

from __future__ import annotations
import fcntl
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

_REPO_ROOT = Path(__file__).parent.parent
_DATA_DIR = Path(os.environ.get("OPENCLAW_DATA", _REPO_ROOT / "data"))
_STRATEGIES_DIR = Path(os.environ.get("OPENCLAW_STRATEGIES", _REPO_ROOT / "strategies"))
_PARAMS_DIR = Path(os.environ.get("OPENCLAW_PARAMS", _REPO_ROOT / "params"))

_lock = Lock()


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure() -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)


def _read(path: Path) -> Any:
    try:
        with open(path) as fh:
            return json.load(fh)
    except FileNotFoundError:
        return None
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Corrupt state file {path}: {exc}") from exc


def _write(path: Path, data: Any) -> None:
    """Atomic write via tmp file (POSIX rename is atomic) with fsync + backup."""
    _ensure()
    tmp = path.with_suffix(".tmp")
    # Create .bak backup if file already exists
    if path.exists():
        bak = path.with_suffix(".bak")
        try:
            bak.write_bytes(path.read_bytes())
        except OSError:
            pass  # Best-effort backup
    with open(tmp, "w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            json.dump(data, fh, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)
    tmp.rename(path)
    # fsync the directory to ensure the rename is durable
    dir_fd = os.open(str(path.parent), os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


# ---------------------------------------------------------------------------
# Strategy Registry
# ---------------------------------------------------------------------------

def load_strategy_registry() -> dict[str, dict]:
    """Load all strategy JSON files. Returns {strategy_id: record}."""
    registry: dict[str, dict] = {}
    if not _STRATEGIES_DIR.exists():
        return registry
    for path in sorted(_STRATEGIES_DIR.glob("*.json")):
        try:
            rec = _read(path)
            sid = rec.get("strategy_id") if rec else None
            if sid:
                registry[sid] = rec
        except Exception:
            continue
    return registry


def save_strategy(strategy: dict) -> None:
    sid = strategy["strategy_id"]
    _STRATEGIES_DIR.mkdir(parents=True, exist_ok=True)
    _write(_STRATEGIES_DIR / f"{sid}.json", strategy)


# ---------------------------------------------------------------------------
# Portfolio State — spec 5.5
# ---------------------------------------------------------------------------

_PORTFOLIO_PATH = _DATA_DIR / "portfolio.json"
_DEFAULT_EQUITY = float(os.environ.get("OPENCLAW_EQUITY", "100000"))


def _default_portfolio() -> dict:
    now = _utcnow()
    return {
        "asof": now,
        "param_version": "PV_0001",
        "account": {
            "equity_usd":             _DEFAULT_EQUITY,
            "opening_equity_usd":     _DEFAULT_EQUITY,
            "peak_equity_usd":        _DEFAULT_EQUITY,
            "cash_usd":               _DEFAULT_EQUITY,
            "margin_used_usd":        0.0,
            "margin_available_usd":   _DEFAULT_EQUITY,
            "margin_utilization_pct": 0.0,
        },
        "pnl": {
            "unrealized_usd":      0.0,
            "realized_today_usd":  0.0,
            "total_today_usd":     0.0,
            "total_today_pct":     0.0,
            "portfolio_dd_pct":    0.0,
            "portfolio_dd_peak_date": now[:10],
        },
        "positions": [],
        "heat": {
            "total_open_risk_usd": 0.0,
            "total_open_risk_pct": 0.0,
            "cluster_exposure":    {},
            "correlations_20d":    {},
        },
        "sentinel_posture":       "NORMAL",
        "sentinel_posture_since": now,
    }


def load_portfolio() -> dict:
    data = _read(_PORTFOLIO_PATH)
    if data is None:
        return _default_portfolio()
    # Validate essential keys
    if "account" not in data or "equity_usd" not in data.get("account", {}):
        raise RuntimeError(
            f"Corrupt portfolio state: missing 'account' or 'equity_usd' in {_PORTFOLIO_PATH}"
        )
    return data


def save_portfolio(portfolio: dict) -> None:
    with _lock:
        portfolio["asof"] = _utcnow()
        _write(_PORTFOLIO_PATH, portfolio)


# ---------------------------------------------------------------------------
# Posture State
# ---------------------------------------------------------------------------

_POSTURE_PATH = _DATA_DIR / "posture_state.json"


def _default_posture() -> dict:
    now = _utcnow()
    return {
        "posture":                   "NORMAL",
        "posture_since":             now,
        "consecutive_positive_days": 0,
        "last_halt_at":              None,
        "recovery_pending":          False,
        "caution_hours_clean":       0,
        "defensive_days_clean":      0,
    }


def load_posture_state() -> dict:
    data = _read(_POSTURE_PATH)
    return data if data is not None else _default_posture()


def save_posture_state(state: dict) -> None:
    with _lock:
        _write(_POSTURE_PATH, state)


# ---------------------------------------------------------------------------
# Parameter Registry — spec Section 17
# ---------------------------------------------------------------------------

def load_params(version: str = "PV_0001") -> dict:
    data = _read(_PARAMS_DIR / f"{version}.json")
    return data if data is not None else _default_params()


def _default_params() -> dict:
    return {
        "param_version": "PV_0001",
        "created_at": "2026-02-28T00:00:00Z",
        "created_by": "operator",
        "effective_from": "2026-02-28T00:00:00Z",
        "regime": {
            "weight_trend": 0.35,
            "weight_vol": 0.30,
            "weight_corr": 0.20,
            "weight_liquidity": 0.15,
            "sigmoid_steepness": 10,
            "risk_multiplier_floor": 0.30,
        },
        "health": {
            "weight_dd": 0.35,
            "weight_sharpe": 0.25,
            "weight_hit_rate": 0.20,
            "weight_execution": 0.20,
            "min_trades_for_full_health": 10,
            "disable_threshold": 0.30,
            "half_size_threshold": 0.50,
        },
        "sentinel": {
            "max_risk_per_trade_pct": 1.0,
            "max_open_risk_pct": 5.0,
            "max_daily_loss_pct": 3.0,
            "max_portfolio_dd_pct": 15.0,
            "max_margin_utilization_pct": 40.0,
            "max_cluster_exposure_pct": 3.0,
            "max_instrument_exposure_pct": 2.0,
            "max_intra_cluster_corr": 0.85,
            "max_concurrent_strategies": 4,
            "max_slippage_ticks": 4,
            "min_reward_risk_ratio": 1.5,
            "max_intent_age_sec": 900,
            "daily_loss_caution_pct": -1.0,
            "daily_loss_defensive_pct": -1.5,
            "daily_loss_halt_pct": -3.0,
            "dd_caution_pct": 5.0,
            "dd_defensive_pct": 10.0,
            "dd_halt_pct": 15.0,
            "recovery_cooldown_caution_to_normal_hours": 4,
            "recovery_cooldown_defensive_to_caution_days": 2,
        },
        "sizing": {
            "posture_modifier_normal": 1.0,
            "posture_modifier_caution": 0.6,
            "posture_modifier_defensive": 0.25,
            "session_modifier_extended": 0.5,
            "target_vol_normal_pct": 12.0,
            "target_vol_caution_pct": 8.0,
            "target_vol_defensive_pct": 4.0,
        },
        "overnight": {
            "flatten_vol_pct_threshold": 0.80,
            "flatten_loss_pct_of_stop": 0.50,
            "partial_exit_profit_progress": 0.50,
            "partial_exit_pct": 50,
            "stop_tightening_pct": 0.30,
        },
        "slippage": {
            "base_ticks": 1,
            "vol_threshold_low": 0.50,
            "vol_threshold_high": 0.80,
            "vol_factor_low_slope": 4.0,
            "vol_factor_high_slope": 15.0,
            "session_factor_extended": 1.5,
            "session_factor_boundary": 2.0,
            "session_factor_pre_open": 3.0,
            "ev_ratio_min": 0.5,
        },
    }


# ---------------------------------------------------------------------------
# Pending Intents (non-terminal intents awaiting processing)
# ---------------------------------------------------------------------------

_PENDING_PATH = _DATA_DIR / "pending_intents.json"


def load_pending_intents() -> list[dict]:
    data = _read(_PENDING_PATH)
    return data if isinstance(data, list) else []


def save_pending_intents(intents: list[dict]) -> None:
    with _lock:
        _write(_PENDING_PATH, intents)


# ---------------------------------------------------------------------------
# Execution Quality (rolling per-strategy metrics) — spec 7.8
# ---------------------------------------------------------------------------

_EXEC_QUALITY_PATH = _DATA_DIR / "exec_quality.json"


def load_exec_quality() -> dict:
    data = _read(_EXEC_QUALITY_PATH)
    return data if isinstance(data, dict) else {}


def save_exec_quality(quality: dict) -> None:
    with _lock:
        _write(_EXEC_QUALITY_PATH, quality)


# ---------------------------------------------------------------------------
# Learning State — adaptive learning pipeline
# ---------------------------------------------------------------------------

_LEARNING_STATE_PATH = _DATA_DIR / "learning_state.json"


def _default_learning_state() -> dict:
    return {
        "last_analysis_at": None,
        "trade_count_at_last_apply": 0,
        "proposals": [],
        "applied_versions": ["PV_0001"],
        "drift_from_baseline": {},
        "surface_trade_counts": {},
        "param_direction_history": {},
    }


def load_learning_state() -> dict:
    data = _read(_LEARNING_STATE_PATH)
    if data is None:
        return _default_learning_state()
    # Ensure all keys exist (forward compat)
    defaults = _default_learning_state()
    for key, val in defaults.items():
        data.setdefault(key, val)
    return data


def save_learning_state(state: dict) -> None:
    with _lock:
        _write(_LEARNING_STATE_PATH, state)


# ---------------------------------------------------------------------------
# Generic state persistence (for intraday regime, session counters, etc.)
# ---------------------------------------------------------------------------

def load_state(name: str) -> dict | None:
    """Load arbitrary named state from data dir. Returns None if missing."""
    path = _DATA_DIR / f"{name}.json"
    return _read(path)


def save_state(name: str, data: dict) -> None:
    """Save arbitrary named state to data dir."""
    with _lock:
        path = _DATA_DIR / f"{name}.json"
        _write(path, data)


def update_exec_quality_slippage(strategy_id: str, realized_slippage_ticks: float) -> None:
    """Phase 4: Append realized slippage for calibration; keep last 50, avg last 20."""
    with _lock:
        data = _read(_EXEC_QUALITY_PATH)
        if not isinstance(data, dict):
            data = {}
        rec = data.setdefault(strategy_id, {"realized_slippage_ticks": [], "avg_realized_slippage_ticks_20": 0.0})
        ticks = rec.get("realized_slippage_ticks", [])
        ticks.append(round(realized_slippage_ticks, 4))
        rec["realized_slippage_ticks"] = ticks[-50:]
        last20 = rec["realized_slippage_ticks"][-20:]
        rec["avg_realized_slippage_ticks_20"] = round(sum(last20) / len(last20), 4) if last20 else 0.0
        _write(_EXEC_QUALITY_PATH, data)
