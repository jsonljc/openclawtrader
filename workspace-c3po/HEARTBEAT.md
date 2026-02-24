# HEARTBEAT.md

Every cycle, log:

- timestamp
- symbol analyzed
- decision: TradeIntent or NO_TRADE
- reason summary
- data freshness check

If 3 consecutive cycles produce identical setup_id:
Switch to NO_TRADE and reassess regime.

If tools fail:
Default to NO_TRADE.
