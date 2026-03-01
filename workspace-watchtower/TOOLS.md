# Watchtower Tools

## Core Module

| Module | Purpose |
|--------|---------|
| `watchtower.py` | All monitoring checks, health assessment, crash recovery |

## Running Watchtower

```bash
# Reconciliation cycle (every 15 min)
python3 run_cycle.py --mode reconcile

# Post-crash recovery
python3 run_cycle.py --mode recovery
```

## Health Check Output

```json
{
  "status": "HEALTHY | DEGRADED | HALT",
  "checks": {
    "data_heartbeat": "OK",
    "price_sanity": "OK",
    "spread": "OK",
    "exchange_connectivity": "OK",
    "position_reconciliation": "OK",
    "bracket_integrity": "OK",
    "margin_safety": "OK",
    "system_latency": "OK",
    "execution_staleness": "OK",
    "disk_memory": "OK",
    "ledger_integrity": "OK"
  },
  "active_alerts": [],
  "roll_alerts": []
}
```

## Ledger Integrity Verification

```bash
python3 -c "
import sys; sys.path.insert(0, '.')
from shared.ledger import verify_integrity
ok, msg = verify_integrity()
print(msg)
"
```

## Manual Crash Recovery

```bash
python3 run_cycle.py --mode recovery
```

Recovery actions:
- DISCARD stale PROPOSED/DEFERRED intents
- RE-EVALUATE APPROVED intents (market may have moved)
- TIMEOUT SENT intents (query fill status)
- Set CAUTION if anomalies found
- Preserve HALT (never auto-recover)

## Monitoring Cron Schedule

```
# Every 4H: full evaluation cycle
0 */4 * * * python3 /home/elyra/.openclawtrader/run_cycle.py --mode full

# Every 1H: lightweight refresh
0 * * * * python3 /home/elyra/.openclawtrader/run_cycle.py --mode refresh

# Every 15 min: reconciliation
*/15 * * * * python3 /home/elyra/.openclawtrader/run_cycle.py --mode reconcile
```
