#!/usr/bin/env bash
# One-time setup on the server: run deploy/auto-update.sh from cron every minute.
# Usage: bash deploy/install-autoupdate.sh
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT="$APP_DIR/deploy/auto-update.sh"
LOG="$APP_DIR/logs/autoupdate.log"

chmod +x "$SCRIPT"
mkdir -p "$APP_DIR/logs"

for tool in git flock curl; do
  command -v "$tool" >/dev/null || { echo "missing: $tool (apt-get install -y ${tool/flock/util-linux})"; exit 1; }
done
docker compose version >/dev/null 2>&1 || command -v docker-compose >/dev/null || { echo "missing: docker compose"; exit 1; }

# Cron entry (replaces any previous one for this script).
# Run through bash explicitly so a lost executable bit can never break deploys.
LINE="* * * * * /bin/bash $SCRIPT >> $LOG 2>&1"
( crontab -l 2>/dev/null | grep -vF "deploy/auto-update.sh" || true; echo "$LINE" ) | crontab -

echo "Installed: $LINE"
echo "Log: $LOG"
echo "A push to origin/main is now deployed within about a minute (build + tests + restart)."
