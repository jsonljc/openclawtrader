# MEMORY.md

Memory Model:

Short-Term:
- session-state.md
- recent decisions (last 5)

Long-Term:
- field_notes.md (operational lessons only)

Rules:
- Never store full trade narratives
- Never store raw emotional commentary
- Only store lessons that change future filters

Compaction Rule:
If memory grows large, preserve:
- last 7 days field_notes
- active hypotheses
Discard older narrative data.
