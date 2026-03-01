# Sentinel Tools

## Core Modules

| Module | Purpose |
|--------|---------|
| `sentinel.py` | Main risk engine: posture, validation, sizing, feedback |
| `posture.py` | Posture state machine (escalation + recovery with cooldowns) |

## Configuration

| File | Purpose |
|------|---------|
| `data/state/posture_state.json` | Current posture and metrics |
| `parameters/PV_0001.json` | All risk parameters (versioned) |

## Key Operations

```python
# Check posture
from sentinel import run_sentinel
posture_state, decisions = run_sentinel(intents, snapshots, regime_reports, wt_status, session, run_id)

# Force posture (operator override for HALT recovery)
# Edit data/state/posture_state.json: set "halt_manually_cleared": true
```

## Posture Thresholds (PV_0001)

| Trigger | Threshold | Action |
|---------|-----------|--------|
| Daily PnL | < -1.0% | CAUTION |
| Daily PnL | < -1.5% | DEFENSIVE |
| Daily PnL | < -3.0% | HALT |
| Portfolio DD | > 5% | CAUTION |
| Portfolio DD | > 10% | DEFENSIVE |
| Portfolio DD | > 15% | HALT |
| Margin util | > 30% | CAUTION |
| Margin util | > 40% | DEFENSIVE |
| Margin util | > 60% | HALT |
| Vol percentile | > 0.85 | CAUTION |
| Vol percentile | > 0.95 | DEFENSIVE |

## Manual HALT Recovery

HALT posture survives crash recovery. To resume after HALT:

```bash
# Edit posture state
python3 -c "
import json
with open('data/state/posture_state.json') as f:
    s = json.load(f)
s['halt_manually_cleared'] = True
with open('data/state/posture_state.json', 'w') as f:
    json.dump(s, f, indent=2)
print('HALT cleared — will transition to DEFENSIVE on next cycle')
"
```

## Parameter Changes

Never modify parameters mid-session. All changes:
1. Create new `parameters/PV_XXXX.json`
2. Effective from start of next trading day
3. Lock period: 60 days minimum
4. Document in ledger: `event_type: PARAMETER_CHANGE`
