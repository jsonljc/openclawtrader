#!/usr/bin/env python3
"""
Sentinel - Deterministic Risk Officer
Pure rule engine. No LLM. No randomness.
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

# Hardcoded stub - will be replaced with Binance API later
EQUITY = 10000.0

# Paths
LATEST_PATH = Path.home() / "openclaw-trader" / "out" / "latest.json"
CONFIG_PATH = Path(__file__).parent / "risk_config.json"
OUTPUT_PATH = Path.home() / "openclaw-trader" / "out" / "risk_decision.json"
LOG_DIR = Path.home() / "openclaw-trader" / "out" / "risk-log"


def load_json(path: Path) -> dict | None:
    """Load JSON file. Returns None on any error."""
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return None


def now_utc() -> str:
    """Return ISO format UTC timestamp."""
    return datetime.now(timezone.utc).isoformat()


def write_reject(reason: str, snapshot: dict) -> dict:
    """Generate and return REJECT decision."""
    decision = {
        "kind": "REJECT",
        "reason": reason,
        "ts_utc": now_utc(),
        "snapshot": snapshot
    }
    return decision


def write_approve(
    symbol: str,
    side: str,
    size: float,
    entry: dict,
    stop: dict,
    take_profit: dict,
    risk_pct: float
) -> dict:
    """Generate and return ApprovedOrder in Forge-compatible format."""
    approved_at = now_utc()
    valid_until = (datetime.now(timezone.utc) + timedelta(seconds=120)).isoformat()
    return {
        "kind": "ApprovedOrder",
        "client_order_id": f"{symbol}-{side}-{approved_at}",
        "symbol": symbol,
        "side": side,
        "venue": "binance",
        "instrument_type": "spot",      # hard-coded until perps are enabled
        "order_type": "MARKET",
        "entry_price": entry.get("price"),
        "size": round(size, 4),
        "stop_price": stop.get("price"),
        "stop_order_type": "STOP_LIMIT",
        "targets": [take_profit],
        "valid_until_ts_utc": valid_until,
        "posture": "normal",
        "constraints": {
            "max_slippage_bps": 30,
            "time_in_force": "IOC",
            "reduce_only_flags": False
        },
        "risk_pct": risk_pct,
        "approved_at": approved_at
    }


def log_decision(decision: dict) -> None:
    """Append decision to timestamped log file."""
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d")
        log_path = LOG_DIR / f"risk-log-{ts}.jsonl"
        with open(log_path, "a") as f:
            f.write(json.dumps(decision, separators=(",", ":")) + "\n")
    except Exception:
        pass  # Logging failure must not block decision


def check_staleness(signal_ts: str, max_seconds: int) -> bool:
    """Return True if signal is fresh."""
    try:
        signal_time = datetime.fromisoformat(signal_ts.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        diff = (now - signal_time).total_seconds()
        return diff <= max_seconds
    except Exception:
        return False


def calculate_stop_pct(entry: float, stop: float) -> float:
    """Calculate stop distance as percentage."""
    if entry <= 0:
        return 0.0
    stop_distance = abs(entry - stop)
    if stop_distance <= 0:
        return 0.0
    return (stop_distance / entry) * 100


def calculate_rr(entry: float, stop: float, take_profit: float) -> float:
    """Calculate Risk:Reward ratio."""
    risk = abs(entry - stop)
    reward = abs(take_profit - entry)
    if risk <= 0:
        return 0.0
    return reward / risk


def calculate_position_size(equity: float, risk_pct: float, stop_distance: float) -> float:
    """Calculate position size. No rounding - validation happens first."""
    if stop_distance <= 0:
        return 0.0
    risk_pct_decimal = risk_pct / 100.0
    risk_capital = equity * risk_pct_decimal
    size = risk_capital / stop_distance
    return size


def trade_intent_to_signal(raw: dict) -> dict | None:
    """
    Convert C3PO TradeIntent JSON to internal signal format for Sentinel.
    Returns None if raw is not a TradeIntent or is NO_TRADE.
    """
    if raw.get("type") != "TradeIntent":
        return None
    inner = raw.get("intent", {})
    if inner.get("side") == "NO_TRADE":
        return {"kind": "NO_TRADE"}
    targets = inner.get("targets") or []
    if not targets:
        return None  # Cannot compute R:R without at least one target
    ts = raw.get("timestamp_utc") or inner.get("expiry_ts_utc") or now_utc()
    return {
        "kind": "TradeIntent",
        "symbol": inner.get("symbol", ""),
        "side": inner.get("side", ""),
        "entry": inner.get("entry", {}),
        "stop": inner.get("stop", {}),
        "take_profit": {"price": targets[0].get("price"), "logic": targets[0].get("logic", "")},
        "ts_utc": ts,
    }


def validate_signal(signal: dict) -> tuple[bool, str]:
    """Validate required fields exist. Returns (ok, error_message)."""
    required = ["kind", "symbol", "side", "entry", "stop", "take_profit", "ts_utc"]
    for field in required:
        if field not in signal:
            return False, f"missing_field:{field}"
    
    # Validate nested structure
    if not isinstance(signal["entry"], dict) or "price" not in signal["entry"]:
        return False, "missing:entry.price"
    if not isinstance(signal["stop"], dict) or "price" not in signal["stop"]:
        return False, "missing:stop.price"
    if not isinstance(signal["take_profit"], dict) or "price" not in signal["take_profit"]:
        return False, "missing:take_profit.price"
    
    return True, ""


def run() -> dict:
    """Main risk engine. Returns decision dict."""
    snapshot = {
        "equity": EQUITY,
        "ts_utc": now_utc()
    }
    
    # Load config
    config = load_json(CONFIG_PATH)
    if config is None:
        decision = write_reject("config_missing", snapshot)
        save_and_log(decision)
        return decision
    
    snapshot["config"] = config
    
    # Load signal (C3PO writes TradeIntent to latest.json)
    raw = load_json(LATEST_PATH)
    if raw is None:
        decision = write_reject("signal_missing", snapshot)
        save_and_log(decision)
        return decision
    
    # Normalize C3PO TradeIntent to internal signal format
    if raw.get("type") == "TradeIntent":
        signal = trade_intent_to_signal(raw)
        if signal is None:
            decision = write_reject("invalid_trade_intent", snapshot)
            save_and_log(decision)
            return decision
        if signal.get("kind") == "NO_TRADE":
            decision = write_reject("no_trade_signal", snapshot)
            save_and_log(decision)
            return decision
    else:
        signal = raw
    
    snapshot["signal"] = signal
    
    # Check NO_TRADE
    if signal.get("kind") == "NO_TRADE":
        decision = write_reject("no_trade_signal", snapshot)
        save_and_log(decision)
        return decision
    
    # Validate fields
    ok, error = validate_signal(signal)
    if not ok:
        decision = write_reject(f"invalid_signal:{error}", snapshot)
        save_and_log(decision)
        return decision
    
    # Check staleness
    if not check_staleness(signal["ts_utc"], config["max_staleness_seconds"]):
        decision = write_reject("signal_stale", snapshot)
        save_and_log(decision)
        return decision
    
    # Extract values
    entry_price = float(signal["entry"]["price"])
    stop_price = float(signal["stop"]["price"])
    tp_price = float(signal["take_profit"]["price"])
    side = signal["side"]
    symbol = signal["symbol"]
    
    # Validate all prices are positive
    if entry_price <= 0 or stop_price <= 0 or tp_price <= 0:
        decision = write_reject("invalid_price_data", snapshot)
        save_and_log(decision)
        return decision
    
    # Calculate risk distance and validate
    risk = abs(entry_price - stop_price)
    if risk <= 0:
        decision = write_reject("invalid_risk_distance", snapshot)
        save_and_log(decision)
        return decision
    
    # Calculate reward distance and validate
    reward = abs(tp_price - entry_price)
    if reward <= 0:
        decision = write_reject("invalid_reward_distance", snapshot)
        save_and_log(decision)
        return decision
    
    # Calculate stop percentage
    stop_pct = calculate_stop_pct(entry_price, stop_price)
    
    # Validate stop bounds
    if stop_pct < config["min_stop_pct"]:
        decision = write_reject(f"stop_too_small:{stop_pct:.4f}", snapshot)
        save_and_log(decision)
        return decision
    
    if stop_pct > config["max_stop_pct"]:
        decision = write_reject(f"stop_too_large:{stop_pct:.4f}", snapshot)
        save_and_log(decision)
        return decision
    
    # Calculate R:R
    rr = calculate_rr(entry_price, stop_price, tp_price)
    
    # Validate R:R threshold
    if rr < config["min_rr"]:
        decision = write_reject(f"rr_below_threshold:{rr:.2f}", snapshot)
        save_and_log(decision)
        return decision
    
    # Calculate position size using stop_distance (not stop_pct)
    size = calculate_position_size(EQUITY, config["max_risk_per_trade_pct"], risk)
    
    # Calculate notional and validate
    notional = size * entry_price
    if notional > EQUITY:
        decision = write_reject(f"insufficient_balance:notional={notional:.2f}", snapshot)
        save_and_log(decision)
        return decision
    
    # Round size to 4 decimals after validation
    size = round(size, 4)
    
    # All checks passed - approve
    decision = write_approve(
        symbol=symbol,
        side=side,
        size=size,
        entry=signal["entry"],
        stop=signal["stop"],
        take_profit=signal["take_profit"],
        risk_pct=config["max_risk_per_trade_pct"]
    )
    
    save_and_log(decision)
    return decision


def save_and_log(decision: dict) -> None:
    """Save decision to output file and log."""
    try:
        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(OUTPUT_PATH, "w") as f:
            json.dump(decision, f, indent=2)
    except Exception:
        pass  # Best effort
    log_decision(decision)


if __name__ == "__main__":
    result = run()
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["kind"] == "ApprovedOrder" else 1)
