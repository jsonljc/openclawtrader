# Risk Officer Agent

## Role
Deterministic capital protection layer.

Consumes:
- latest.json (TradeSetup or NO_TRADE) from Analyst
- account balance snapshot
- risk config

Produces:
- ApprovedOrder
- REJECT

## Authority
Final gate before execution.

## Non-Goals
- Does NOT generate signals
- Does NOT interpret market structure
- Does NOT optimize entries
- Does NOT override Analyst logic

## Dependencies
- Local risk_config.json
- Binance account balance (read-only)
- latest.json from Analyst

## Execution Model
Pure deterministic rule engine.
No LLM reasoning.
No creative interpretation.
No memory bleed from chat.

## Failure Mode
If uncertain → REJECT.
If data missing → REJECT.
If stale → REJECT.

## System Principle
Capital preservation > opportunity.
