#!/usr/bin/env bash
# run_eod.sh — End-of-day routine (daily at 16:15 ET)
#
# Schedule: Mon-Fri 16:15 ET (after POST_CLOSE)
# Actions: daily snapshot, overnight hold policy, bars_held increment, PnL reset

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

export OPENCLAW_DATA_SOURCE="${OPENCLAW_DATA_SOURCE:-ib}"
export OPENCLAW_DATA="${OPENCLAW_DATA:-$HOME/openclaw-trader/data}"

LOG_DIR="$HOME/openclaw-trader/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/eod_$(date +%Y%m%d).log"

if [ -f "$PROJECT_DIR/.venv/bin/activate" ]; then
    source "$PROJECT_DIR/.venv/bin/activate"
elif [ -f "$PROJECT_DIR/venv/bin/activate" ]; then
    source "$PROJECT_DIR/venv/bin/activate"
fi

echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] Starting EOD routine" | tee -a "$LOG_FILE"

cd "$PROJECT_DIR"
python run_eod.py 2>&1 | tee -a "$LOG_FILE"

EXIT_CODE=${PIPESTATUS[0]}
echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] EOD routine finished (exit=$EXIT_CODE)" | tee -a "$LOG_FILE"
exit $EXIT_CODE
