#!/usr/bin/env bash
# run_4h_cycle.sh — Full evaluation cycle (every 4 hours during market hours)
#
# Schedule: 09:30, 13:30, 17:30 ET (core session 4H boundaries)
# Pipeline: Watchtower → C3PO → Sentinel → Forge

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Data source: "ib" for live IB data, "stub" for synthetic
export OPENCLAW_DATA_SOURCE="${OPENCLAW_DATA_SOURCE:-ib}"
export OPENCLAW_DATA="${OPENCLAW_DATA:-$HOME/openclaw-trader/data}"

# Logging
LOG_DIR="$HOME/openclaw-trader/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/cycle_4h_$(date +%Y%m%d_%H%M%S).log"

# Activate venv if present
if [ -f "$PROJECT_DIR/.venv/bin/activate" ]; then
    source "$PROJECT_DIR/.venv/bin/activate"
elif [ -f "$PROJECT_DIR/venv/bin/activate" ]; then
    source "$PROJECT_DIR/venv/bin/activate"
fi

echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] Starting 4H full cycle (source=$OPENCLAW_DATA_SOURCE)" | tee -a "$LOG_FILE"

cd "$PROJECT_DIR"
python run_cycle.py --mode full --no-paper 2>&1 | tee -a "$LOG_FILE"

EXIT_CODE=${PIPESTATUS[0]}
echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] 4H cycle finished (exit=$EXIT_CODE)" | tee -a "$LOG_FILE"
exit $EXIT_CODE
