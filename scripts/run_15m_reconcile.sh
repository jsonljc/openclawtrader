#!/usr/bin/env bash
# run_15m_reconcile.sh — Reconciliation cycle (every 15 minutes during market hours)
#
# Schedule: Mon-Fri 09:30-16:00 ET, every 15 minutes
# Actions: bracket triggers, position MTM, bracket integrity check

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

export OPENCLAW_DATA_SOURCE="${OPENCLAW_DATA_SOURCE:-ib}"
export OPENCLAW_DATA="${OPENCLAW_DATA:-$HOME/openclaw-trader/data}"

LOG_DIR="$HOME/openclaw-trader/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/reconcile_$(date +%Y%m%d_%H%M%S).log"

if [ -f "$PROJECT_DIR/.venv/bin/activate" ]; then
    source "$PROJECT_DIR/.venv/bin/activate"
elif [ -f "$PROJECT_DIR/venv/bin/activate" ]; then
    source "$PROJECT_DIR/venv/bin/activate"
fi

echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] Starting 15m reconciliation" | tee -a "$LOG_FILE"

cd "$PROJECT_DIR"
python run_cycle.py --mode reconcile --no-paper 2>&1 | tee -a "$LOG_FILE"

EXIT_CODE=${PIPESTATUS[0]}
echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] Reconciliation finished (exit=$EXIT_CODE)" | tee -a "$LOG_FILE"
exit $EXIT_CODE
