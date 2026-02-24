# forge/TOOLS.md — Forge Tool Allowlist

## Allowed Tools (Execution + Read for verification)
- exchange.get_account_state()
- exchange.get_symbol_rules(symbol)  # lot size, tick size, min notional
- exchange.get_open_orders(symbol)
- exchange.get_positions(symbol)
- exchange.place_order(payload)
- exchange.cancel_order(order_id)
- exchange.get_order(order_id)
- exchange.get_price(symbol)  # only for validation/slippage checks

## Disallowed
- any tool that generates strategy signals
- any tool that changes risk policy
- any tool that edits Sentinel or C3PO memory

Forge may only touch the exchange and its own logs/state.
