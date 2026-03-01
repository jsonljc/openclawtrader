# C3PO Tools

## Core Modules

| Module | Purpose |
|--------|---------|
| `brain.py` | Main evaluation cycle: regime → health → signals → intents |
| `regime.py` | Regime scoring engine (Section 6.4–6.5) |
| `health.py` | Strategy health scoring (Section 6.6) |
| `data_stub.py` | Market data stub for Phase 1 development |

## Running C3PO

```bash
# Full evaluation cycle (via orchestrator)
python3 run_cycle.py --mode full

# Lightweight 1H refresh
python3 run_cycle.py --mode refresh
```

## Key Outputs

- `RegimeReport` — regime_score, confidence, effective_regime_score, risk_multiplier
- `StrategyHealthReport` — health_score, action (NORMAL/HALF_SIZE/DISABLE), components
- `TradeIntent` — full intent with entry/stop/TP plan, sizing, thesis

## Data Flow

```
MarketSnapshot → compute_regime() → RegimeReport
                                  ↓
MarketSnapshot → evaluate_strategy_health() → HealthReport
                                  ↓
SignalHandler → check_proposal_gates() → TradeIntent (or nothing)
```

## Adding a New Strategy

1. Add signal handler function (e.g., `_evaluate_mean_reversion_4H`)
2. Register in `_SIGNAL_HANDLERS` dict
3. Create strategy JSON in `strategies/`
4. Load registry (or add directly to state store)

## Phase Roadmap

- **Phase 1 (current)**: 1 strategy, stub data, fixed sizing
- **Phase 2**: Regime + health scaling, real session management
- **Phase 3**: Portfolio of strategies, correlation tracking
- **Phase 4**: Live data feed, slippage calibration
