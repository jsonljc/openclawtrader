# BOOTSTRAP.md

On startup:

1) Load last 3 days of c3po/field_notes.
2) Load c3po/session-state.
3) Determine:
   - current regime
   - recent failure patterns
   - active bias state

4) If insufficient data:
   - default to neutral bias
   - require stronger confirmation

5) Never trade on first cycle after restart without fresh data.
