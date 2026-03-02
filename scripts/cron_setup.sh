#!/usr/bin/env bash
# cron_setup.sh — Generate macOS launchd plist files for OpenClaw trading schedules
#
# Usage:
#   bash scripts/cron_setup.sh              # Generate plist files
#   bash scripts/cron_setup.sh --load       # Generate + load into launchd
#   bash scripts/cron_setup.sh --unload     # Unload from launchd
#   bash scripts/cron_setup.sh --status     # Show launchd status
#
# Schedule (all times Eastern):
#   4H cycle:       09:30, 13:30, 17:30 Mon-Fri
#   15m reconcile:  Every 15 min, Mon-Fri 09:30-16:00
#   EOD:            16:15 Mon-Fri
#   Weekly learning: Sunday 20:00

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PLIST_DIR="$HOME/Library/LaunchAgents"
LOG_DIR="$HOME/openclaw-trader/logs"

mkdir -p "$PLIST_DIR" "$LOG_DIR"

ACTION="${1:-generate}"

# ---------------------------------------------------------------------------
# Unload
# ---------------------------------------------------------------------------
if [ "$ACTION" = "--unload" ]; then
    echo "Unloading OpenClaw launchd jobs..."
    for plist in "$PLIST_DIR"/com.openclaw.*.plist; do
        if [ -f "$plist" ]; then
            launchctl unload "$plist" 2>/dev/null || true
            echo "  Unloaded: $(basename "$plist")"
        fi
    done
    echo "Done."
    exit 0
fi

# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------
if [ "$ACTION" = "--status" ]; then
    echo "OpenClaw launchd jobs:"
    launchctl list 2>/dev/null | grep openclaw || echo "  No OpenClaw jobs loaded"
    echo ""
    echo "Plist files in $PLIST_DIR:"
    ls -la "$PLIST_DIR"/com.openclaw.*.plist 2>/dev/null || echo "  No plist files found"
    exit 0
fi

# ---------------------------------------------------------------------------
# Generate plist files
# ---------------------------------------------------------------------------
echo "Generating launchd plist files in $PLIST_DIR..."

# --- 4H Full Cycle (09:30, 13:30, 17:30 ET = 14:30, 18:30, 22:30 UTC / 13:30, 17:30, 21:30 UTC-DST)
# Using StartCalendarInterval with multiple entries.
# Note: launchd uses LOCAL time, so these are ET-aware if system TZ is set.
cat > "$PLIST_DIR/com.openclaw.cycle-4h.plist" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.openclaw.cycle-4h</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>$SCRIPT_DIR/run_4h_cycle.sh</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$PROJECT_DIR</string>
    <key>StartCalendarInterval</key>
    <array>
        <!-- 09:30 ET Mon-Fri -->
        <dict><key>Weekday</key><integer>1</integer><key>Hour</key><integer>9</integer><key>Minute</key><integer>30</integer></dict>
        <dict><key>Weekday</key><integer>2</integer><key>Hour</key><integer>9</integer><key>Minute</key><integer>30</integer></dict>
        <dict><key>Weekday</key><integer>3</integer><key>Hour</key><integer>9</integer><key>Minute</key><integer>30</integer></dict>
        <dict><key>Weekday</key><integer>4</integer><key>Hour</key><integer>9</integer><key>Minute</key><integer>30</integer></dict>
        <dict><key>Weekday</key><integer>5</integer><key>Hour</key><integer>9</integer><key>Minute</key><integer>30</integer></dict>
        <!-- 13:30 ET Mon-Fri -->
        <dict><key>Weekday</key><integer>1</integer><key>Hour</key><integer>13</integer><key>Minute</key><integer>30</integer></dict>
        <dict><key>Weekday</key><integer>2</integer><key>Hour</key><integer>13</integer><key>Minute</key><integer>30</integer></dict>
        <dict><key>Weekday</key><integer>3</integer><key>Hour</key><integer>13</integer><key>Minute</key><integer>30</integer></dict>
        <dict><key>Weekday</key><integer>4</integer><key>Hour</key><integer>13</integer><key>Minute</key><integer>30</integer></dict>
        <dict><key>Weekday</key><integer>5</integer><key>Hour</key><integer>13</integer><key>Minute</key><integer>30</integer></dict>
        <!-- 17:30 ET Mon-Fri -->
        <dict><key>Weekday</key><integer>1</integer><key>Hour</key><integer>17</integer><key>Minute</key><integer>30</integer></dict>
        <dict><key>Weekday</key><integer>2</integer><key>Hour</key><integer>17</integer><key>Minute</key><integer>30</integer></dict>
        <dict><key>Weekday</key><integer>3</integer><key>Hour</key><integer>17</integer><key>Minute</key><integer>30</integer></dict>
        <dict><key>Weekday</key><integer>4</integer><key>Hour</key><integer>17</integer><key>Minute</key><integer>30</integer></dict>
        <dict><key>Weekday</key><integer>5</integer><key>Hour</key><integer>17</integer><key>Minute</key><integer>30</integer></dict>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>OPENCLAW_DATA_SOURCE</key>
        <string>ib</string>
        <key>OPENCLAW_DATA</key>
        <string>$HOME/openclaw-trader/data</string>
    </dict>
    <key>StandardOutPath</key>
    <string>$LOG_DIR/launchd_4h_stdout.log</string>
    <key>StandardErrorPath</key>
    <string>$LOG_DIR/launchd_4h_stderr.log</string>
</dict>
</plist>
PLIST
echo "  Created: com.openclaw.cycle-4h.plist"

# --- 15m Reconciliation (every 15 min during market hours)
# launchd doesn't support "only between 09:30-16:00", so we run every 15 min
# and the script itself can check session state. For simplicity, schedule
# at :00, :15, :30, :45 during 09:00-16:00 Mon-Fri.
cat > "$PLIST_DIR/com.openclaw.reconcile-15m.plist" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.openclaw.reconcile-15m</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>$SCRIPT_DIR/run_15m_reconcile.sh</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$PROJECT_DIR</string>
    <key>StartInterval</key>
    <integer>900</integer>
    <key>EnvironmentVariables</key>
    <dict>
        <key>OPENCLAW_DATA_SOURCE</key>
        <string>ib</string>
        <key>OPENCLAW_DATA</key>
        <string>$HOME/openclaw-trader/data</string>
    </dict>
    <key>StandardOutPath</key>
    <string>$LOG_DIR/launchd_reconcile_stdout.log</string>
    <key>StandardErrorPath</key>
    <string>$LOG_DIR/launchd_reconcile_stderr.log</string>
</dict>
</plist>
PLIST
echo "  Created: com.openclaw.reconcile-15m.plist"

# --- EOD Routine (16:15 ET Mon-Fri)
cat > "$PLIST_DIR/com.openclaw.eod.plist" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.openclaw.eod</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>$SCRIPT_DIR/run_eod.sh</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$PROJECT_DIR</string>
    <key>StartCalendarInterval</key>
    <array>
        <dict><key>Weekday</key><integer>1</integer><key>Hour</key><integer>16</integer><key>Minute</key><integer>15</integer></dict>
        <dict><key>Weekday</key><integer>2</integer><key>Hour</key><integer>16</integer><key>Minute</key><integer>15</integer></dict>
        <dict><key>Weekday</key><integer>3</integer><key>Hour</key><integer>16</integer><key>Minute</key><integer>15</integer></dict>
        <dict><key>Weekday</key><integer>4</integer><key>Hour</key><integer>16</integer><key>Minute</key><integer>15</integer></dict>
        <dict><key>Weekday</key><integer>5</integer><key>Hour</key><integer>16</integer><key>Minute</key><integer>15</integer></dict>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>OPENCLAW_DATA_SOURCE</key>
        <string>ib</string>
        <key>OPENCLAW_DATA</key>
        <string>$HOME/openclaw-trader/data</string>
    </dict>
    <key>StandardOutPath</key>
    <string>$LOG_DIR/launchd_eod_stdout.log</string>
    <key>StandardErrorPath</key>
    <string>$LOG_DIR/launchd_eod_stderr.log</string>
</dict>
</plist>
PLIST
echo "  Created: com.openclaw.eod.plist"

# --- Weekly Learning (Sunday 20:00 ET)
cat > "$PLIST_DIR/com.openclaw.learning-weekly.plist" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.openclaw.learning-weekly</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>$SCRIPT_DIR/run_weekly_learning.sh</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$PROJECT_DIR</string>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Weekday</key>
        <integer>0</integer>
        <key>Hour</key>
        <integer>20</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>EnvironmentVariables</key>
    <dict>
        <key>OPENCLAW_DATA_SOURCE</key>
        <string>stub</string>
        <key>OPENCLAW_DATA</key>
        <string>$HOME/openclaw-trader/data</string>
    </dict>
    <key>StandardOutPath</key>
    <string>$LOG_DIR/launchd_learning_stdout.log</string>
    <key>StandardErrorPath</key>
    <string>$LOG_DIR/launchd_learning_stderr.log</string>
</dict>
</plist>
PLIST
echo "  Created: com.openclaw.learning-weekly.plist"

echo ""
echo "All plist files generated in $PLIST_DIR"

# ---------------------------------------------------------------------------
# Load if requested
# ---------------------------------------------------------------------------
if [ "$ACTION" = "--load" ]; then
    echo ""
    echo "Loading OpenClaw launchd jobs..."
    for plist in "$PLIST_DIR"/com.openclaw.*.plist; do
        launchctl unload "$plist" 2>/dev/null || true
        launchctl load "$plist"
        echo "  Loaded: $(basename "$plist")"
    done
    echo ""
    echo "Verify with: launchctl list | grep openclaw"
fi

echo ""
echo "Commands:"
echo "  Load all:   launchctl load ~/Library/LaunchAgents/com.openclaw.*.plist"
echo "  Unload all: launchctl unload ~/Library/LaunchAgents/com.openclaw.*.plist"
echo "  Status:     bash $0 --status"
echo "  Logs:       ls -la $LOG_DIR/"
