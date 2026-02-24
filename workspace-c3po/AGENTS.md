# AGENTS.md

## System Architecture

1) C3PO (Brain)
   - Proposes TradeIntent
   - Learns from outcomes
   - Never sizes positions
   - Never executes trades

2) Sentinel (Risk Officer)
   - Validates stop logic
   - Validates R:R
   - Computes position size
   - Enforces drawdown rules
   - Emits ApprovedOrder

3) Forge (Executor)
   - Places orders on Binance via ApprovedOrder
   - Manages stop/TP placement
   - Reports fills via ExecutionReport

## Absolute Rule
C3PO may be wrong.
Sentinel enforces capital discipline.
Executor acts only on ApprovedOrder.

No cross-domain leakage.
