# forge/BOOTSTRAP.md — Startup Procedure

On startup:
1) Load forge/state.json (idempotency ledger, last reports)
2) Connect to exchange in read-only verify mode
3) Fetch symbol rules for BTCUSDT
4) Fetch open orders + positions
5) If any position exists without a corresponding known stop order:
   - emit CRITICAL_UNPROTECTED_POSITION
   - halt automatic execution until operator intervenes

Forge must not execute anything during bootstrap.
