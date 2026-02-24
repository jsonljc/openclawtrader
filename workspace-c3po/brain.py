#!/usr/bin/env python3
"""
C3PO - Learning Strategy Agent (Brain)
Generates TradeIntent proposals in strict JSON format.
No execution. No sizing. Intent only.
"""

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional

# Paths (Sentinel reads from latest.json)
OUTPUT_DIR = Path.home() / "openclaw-trader" / "out"
LATEST_PATH = OUTPUT_DIR / "latest.json"  # C3PO → Sentinel handoff
LOG_DIR = OUTPUT_DIR / "c3po-log"
FIELD_NOTES_PATH = Path(__file__).parent / "c3po" / "field_notes.md"


def now_utc() -> str:
    """Return ISO format UTC timestamp."""
    return datetime.now(timezone.utc).isoformat()


def generate_setup_id(symbol: str, timeframe: str, side: str, entry_type: str, 
                      entry_price: Optional[float], stop_price: Optional[float]) -> str:
    """Generate deterministic setup_id."""
    # Round entry/stop for ID: nearest 10 for BTC, nearest 1 for others
    if symbol.startswith("BTC"):
        r_entry = round(entry_price / 10) * 10 if entry_price else 0
        r_stop = round(stop_price / 10) * 10 if stop_price else 0
    else:
        r_entry = round(entry_price) if entry_price else 0
        r_stop = round(stop_price) if stop_price else 0
    
    return f"{symbol}-{timeframe}-{side}-{entry_type}-{int(r_entry)}-{int(r_stop)}-v0"


def calculate_expiry(timeframe: str) -> str:
    """Calculate expiry based on timeframe."""
    now = datetime.now(timezone.utc)
    
    # Intraday: +60 minutes, Swing: +1 day
    if timeframe in ["1m", "5m", "15m", "1h", "4h"]:
        expiry = now + timedelta(minutes=60)
    else:
        expiry = now + timedelta(days=1)
    
    return expiry.isoformat()


def write_intent(intent: dict) -> None:
    """Write intent to latest.json (for Sentinel) and timestamped log copy."""
    try:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        with open(LATEST_PATH, "w") as f:
            json.dump(intent, f, indent=2)
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        with open(LOG_DIR / f"intent-{ts}.json", "w") as f:
            json.dump(intent, f, indent=2)
    except Exception as e:
        print(f"Warning: Failed to write intent: {e}", file=sys.stderr)


def append_field_note(setup_id: str, outcome: str, lesson: str) -> None:
    """Append learning note to field_notes.md."""
    try:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        note = f"Setup {setup_id} -> outcome {outcome} -> lesson {lesson}"
        
        # Read existing content
        content = ""
        if FIELD_NOTES_PATH.exists():
            content = FIELD_NOTES_PATH.read_text()
        
        # Check if today's header exists
        if f"## {today}" not in content:
            content += f"\n## {today}\n"
        
        # Append note
        content += f"- {note}\n"
        
        # Write back
        FIELD_NOTES_PATH.write_text(content)
        
    except Exception as e:
        print(f"Warning: Failed to append field note: {e}", file=sys.stderr)


def generate_trade_intent(
    symbol: str,
    side: str,
    entry_price: Optional[float],
    stop_price: Optional[float],
    target_prices: list[float],
    timeframe: str,
    confidence: float,
    thesis: str,
    entry_type: str = "MARKET",
    stop_logic: str = "",
    target_logics: Optional[list[str]] = None,
    key_levels: Optional[list[str]] = None,
    assumptions: Optional[list[str]] = None,
    invalidated_by: Optional[list[str]] = None
) -> dict:
    """Generate TradeIntent JSON."""
    
    # Calculate setup_id
    setup_id = generate_setup_id(symbol, timeframe, side, entry_type, entry_price, stop_price)
    
    # Calculate expiry
    expiry = calculate_expiry(timeframe)
    
    # Build targets
    targets = []
    for i, price in enumerate(target_prices):
        logic = target_logics[i] if target_logics and i < len(target_logics) else f"Target {i+1}"
        targets.append({"price": price, "logic": logic})
    
    # Build intent
    intent = {
        "type": "TradeIntent",
        "version": "0.1",
        "timestamp_utc": now_utc(),
        "intent": {
            "symbol": symbol,
            "side": side,
            "entry": {
                "type": entry_type,
                "price": entry_price
            },
            "stop": {
                "price": stop_price,
                "logic": stop_logic or "Standard stop"
            },
            "targets": targets,
            "timeframe": timeframe,
            "setup_id": setup_id,
            "expiry_ts_utc": expiry,
            "confidence": round(confidence, 2)
        },
        "notes": {
            "thesis": thesis,
            "key_levels": key_levels or [],
            "assumptions": assumptions or [],
            "invalidation": invalidated_by or []
        }
    }
    
    return intent


def generate_no_trade(symbol: str, timeframe: str, reasons: list[str]) -> dict:
    """Generate NO_TRADE intent."""
    return {
        "type": "TradeIntent",
        "version": "0.1",
        "timestamp_utc": now_utc(),
        "intent": {
            "symbol": symbol,
            "side": "NO_TRADE",
            "entry": {"type": "NONE", "price": None},
            "stop": {"price": None, "logic": "N/A"},
            "targets": [],
            "timeframe": timeframe,
            "setup_id": f"{symbol}-{timeframe}-NO_TRADE-v0",
            "expiry_ts_utc": calculate_expiry(timeframe),
            "confidence": 0.0
        },
        "notes": {
            "thesis": "Quality gates not met",
            "key_levels": [],
            "assumptions": [],
            "invalidation": reasons
        }
    }


def validate_intent(intent: dict) -> tuple[bool, list[str]]:
    """Validate TradeIntent structure."""
    errors = []
    
    # Check top-level fields
    if intent.get("type") != "TradeIntent":
        errors.append("type must be 'TradeIntent'")
    
    if intent.get("version") != "0.1":
        errors.append("version must be '0.1'")
    
    # Check intent object
    inner = intent.get("intent", {})
    
    required = ["symbol", "side", "entry", "stop", "targets", "timeframe", 
                "setup_id", "expiry_ts_utc", "confidence"]
    for field in required:
        if field not in inner:
            errors.append(f"Missing required field: intent.{field}")
    
    # Validate side
    if inner.get("side") not in ["LONG", "SHORT", "NO_TRADE"]:
        errors.append("side must be LONG, SHORT, or NO_TRADE")
    
    # Validate confidence range
    conf = inner.get("confidence", -1)
    if not (0 <= conf <= 1):
        errors.append("confidence must be 0-1")
    
    # Check notes
    notes = intent.get("notes", {})
    if "thesis" not in notes:
        errors.append("Missing required field: notes.thesis")
    
    return len(errors) == 0, errors


def quality_gate_check(
    stop_price: Optional[float],
    entry_price: Optional[float],
    side: str,
    thesis: str,
    confidence: float,
    prior_setup_ids: list[str],
    new_setup_id: str
) -> tuple[bool, list[str]]:
    """Run quality gates. Returns (pass, reasons)."""
    reasons = []
    
    # Check for duplicate setup_id
    if new_setup_id in prior_setup_ids:
        reasons.append(f"Duplicate setup_id: {new_setup_id}")
    
    # Check stop validity
    if side in ["LONG", "SHORT"]:
        if stop_price is None:
            reasons.append("Stop price missing")
        elif entry_price is not None:
            if side == "LONG" and stop_price >= entry_price:
                reasons.append("Long stop above entry")
            elif side == "SHORT" and stop_price <= entry_price:
                reasons.append("Short stop below entry")
    
    # Check thesis quality
    if len(thesis) < 10 or thesis.lower() in ["feels bullish", "feels bearish", "looks good"]:
        reasons.append("Thesis too vague or emotional")
    
    # Check confidence threshold
    if confidence < 0.55:
        reasons.append(f"Confidence {confidence:.2f} below 0.55 threshold")
    
    return len(reasons) == 0, reasons


def main():
    """Example usage and test."""
    # Example: Generate a valid LONG intent
    intent = generate_trade_intent(
        symbol="BTCUSDT",
        side="LONG",
        entry_price=60000.0,
        stop_price=59400.0,
        target_prices=[61200.0, 61800.0],
        timeframe="15m",
        confidence=0.72,
        thesis="BOS above EMA200 with volume confirmation",
        entry_type="MARKET",
        stop_logic="Below swing low and 1.5x ATR",
        target_logics=["2R target", "3R target"],
        key_levels=["60000", "59400", "61200", "61800"],
        assumptions=["Volatility remains medium", "No major news events"],
        invalidated_by=["Close below 59400 before entry", "Volume spike down"]
    )
    
    # Validate
    valid, errors = validate_intent(intent)
    
    if valid:
        # Quality gate check (empty prior_setup_ids for example)
        passes, reasons = quality_gate_check(
            stop_price=60000.0,
            entry_price=59400.0,
            side="LONG",
            thesis="BOS above EMA200 with volume confirmation",
            confidence=0.72,
            prior_setup_ids=[],
            new_setup_id=intent["intent"]["setup_id"]
        )
        
        if passes:
            write_intent(intent)
            print(json.dumps(intent, indent=2))
            print("\nTradeIntent generated and written successfully.")
        else:
            # Convert to NO_TRADE
            no_trade = generate_no_trade("BTCUSDT", "15m", reasons)
            write_intent(no_trade)
            print(json.dumps(no_trade, indent=2))
            print("\nQuality gates failed. NO_TRADE generated.")
    else:
        print(f"Validation errors: {errors}")
        sys.exit(1)


if __name__ == "__main__":
    main()
