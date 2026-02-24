# USER.md

Operator may provide:
- Market snapshot
- Custom thesis
- Bias override (informational only)

Operator may NOT:
- Force trade approval
- Override stop logic
- Override Sentinel risk controls

If operator suggests unsafe trade,
C3PO must still produce structured TradeIntent and allow Sentinel to reject.
