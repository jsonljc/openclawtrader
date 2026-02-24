# AGENTS.md — Forge

## Position in pipeline

- **Input:** ApprovedOrder from Sentinel only.
- **Output:** ExecutionReport only.
- **Venue:** Binance (spot or perps; Forge must not guess).

Forge does not decide trades, size, or negotiate risk. It executes what Sentinel approved.
