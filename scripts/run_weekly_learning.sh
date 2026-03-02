#!/usr/bin/env bash
# run_weekly_learning.sh — Weekly learning analysis (Sunday 20:00 ET)
#
# Schedule: Sunday 20:00 ET
# Actions: collect trade data, run analyzers, generate param proposal

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

export OPENCLAW_DATA_SOURCE="${OPENCLAW_DATA_SOURCE:-stub}"
export OPENCLAW_DATA="${OPENCLAW_DATA:-$HOME/openclaw-trader/data}"

LOG_DIR="$HOME/openclaw-trader/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/learning_$(date +%Y%m%d).log"

if [ -f "$PROJECT_DIR/.venv/bin/activate" ]; then
    source "$PROJECT_DIR/.venv/bin/activate"
elif [ -f "$PROJECT_DIR/venv/bin/activate" ]; then
    source "$PROJECT_DIR/venv/bin/activate"
fi

echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] Starting weekly learning analysis" | tee -a "$LOG_FILE"

cd "$PROJECT_DIR"

# Step 1: Analyze — collect data + run all 6 analyzers
echo "--- Phase 1: Analyze ---" | tee -a "$LOG_FILE"
python run_learning.py analyze 2>&1 | tee -a "$LOG_FILE"

# Step 2: Propose — generate ParamProposal from analysis
echo "--- Phase 2: Propose ---" | tee -a "$LOG_FILE"
python run_learning.py propose 2>&1 | tee -a "$LOG_FILE"

# Step 3: Review — show proposal diff (logged for operator review)
echo "--- Phase 3: Review ---" | tee -a "$LOG_FILE"
python run_learning.py review 2>&1 | tee -a "$LOG_FILE"

EXIT_CODE=${PIPESTATUS[0]}
echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] Weekly learning finished (exit=$EXIT_CODE)" | tee -a "$LOG_FILE"
echo "NOTE: Proposal requires manual 'python run_learning.py apply' to take effect" | tee -a "$LOG_FILE"
exit $EXIT_CODE
