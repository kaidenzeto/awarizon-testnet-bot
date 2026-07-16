#!/usr/bin/env bash
# Awarizon daily check-in cron wrapper
# Runs at 15:00 WIB
set -euo pipefail

BOT="/root/awarizon-bot/awarizon_bot.py"
PYTHON="${PYTHON:-python3}"
NOTIFY="/root/syntrax-bot/notify.py"
LOG_DIR="/root/awarizon-bot/logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/checkin_$(date +%Y%m%d).log"

{
  echo "=== Awarizon check-in $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
  "$PYTHON" "$BOT" --action auto 2>&1
  echo "=== done ==="
} | tee -a "$LOG"

# Optional Telegram notify if notify.py exists
if [[ -x "$NOTIFY" || -f "$NOTIFY" ]]; then
  # extract last score line-ish
  SUMMARY=$(tail -n 40 "$LOG" | tr '\n' ' ' | head -c 500)
  "$PYTHON" "$NOTIFY" "Awarizon daily ✅ $(date -u +%Y-%m-%d)
$SUMMARY" 2>/dev/null || true
fi
