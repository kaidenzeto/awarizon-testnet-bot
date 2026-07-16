#!/usr/bin/env bash
# Awarizon daily check-in cron wrapper
# Runs at 15:00 WIB
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BOT="$SCRIPT_DIR/awarizon_bot.py"
PYTHON="${PYTHON:-python3}"
LOG_DIR="$SCRIPT_DIR/logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/checkin_$(date +%Y%m%d).log"

{
  echo "=== Awarizon check-in $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
  "$PYTHON" "$BOT" --action auto "$@" 2>&1
  echo "=== done ==="
} | tee -a "$LOG"
