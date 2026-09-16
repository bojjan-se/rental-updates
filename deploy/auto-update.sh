#!/usr/bin/env bash
# Auto-deploy: if origin/<branch> has moved, pull it, build the image, run the
# test suite inside the new image, and only then swap the running container.
# Safe to run from cron every minute; a lock prevents overlapping runs and a
# commit that fails its tests is skipped (and reported) instead of retried.
#
# Notifies via the ntfy topic in config.yaml, when one is configured.
set -euo pipefail

APP_DIR="${APP_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
BRANCH="${BRANCH:-main}"
SERVICE="${SERVICE:-rental-scraper}"
LOCK_FILE="${LOCK_FILE:-/tmp/rental-updates-autoupdate.lock}"
FAILED_MARKER="$APP_DIR/.autoupdate-failed"

cd "$APP_DIR"
exec 9>"$LOCK_FILE"
flock -n 9 || exit 0

if docker compose version >/dev/null 2>&1; then
  COMPOSE="docker compose"
else
  COMPOSE="docker-compose"
fi

ntfy() {  # ntfy TITLE TAGS BODY
  local topic server
  topic=$(sed -nE 's/^[[:space:]]*topic:[[:space:]]*"?([^"[:space:]]+)"?.*/\1/p' config.yaml 2>/dev/null | head -1 || true)
  server=$(sed -nE 's/^[[:space:]]*server:[[:space:]]*"?([^"[:space:]]+)"?.*/\1/p' config.yaml 2>/dev/null | head -1 || true)
  [ -n "$topic" ] || return 0
  curl -fsS --max-time 10 -H "Title: $1" -H "Tags: $2" -H "Priority: default" \
    -d "$3" "${server:-https://ntfy.sh}/$topic" >/dev/null 2>&1 || true
}

git fetch -q origin "$BRANCH"
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse "origin/$BRANCH")

if [ "$LOCAL" = "$REMOTE" ]; then
  exit 0
fi
if [ -f "$FAILED_MARKER" ] && [ "$(cat "$FAILED_MARKER")" = "$REMOTE" ]; then
  exit 0  # already tried this commit and it failed; wait for a new push
fi

echo "$(date -Is) updating ${LOCAL:0:7} -> ${REMOTE:0:7}"
# The checkout is deploy-only: config.yaml, data/ and logs/ are untracked, so
# a hard reset cannot touch them.
git reset -q --hard "origin/$BRANCH"
SUBJECT=$(git log -1 --pretty=%s)

if ! $COMPOSE build --quiet "$SERVICE"; then
  echo "$REMOTE" > "$FAILED_MARKER"
  ntfy "Deploy failed: build" "x" "Commit ${REMOTE:0:7} (${SUBJECT}) failed to build. Still running ${LOCAL:0:7}."
  exit 1
fi

if ! $COMPOSE run --rm --no-deps --entrypoint python3 "$SERVICE" -m pytest -q -p no:cacheprovider; then
  echo "$REMOTE" > "$FAILED_MARKER"
  ntfy "Deploy failed: tests" "x" "Commit ${REMOTE:0:7} (${SUBJECT}) failed its tests on the server. Still running ${LOCAL:0:7}."
  exit 1
fi

$COMPOSE up -d --remove-orphans "$SERVICE"
rm -f "$FAILED_MARKER"
echo "$(date -Is) deployed ${REMOTE:0:7}: $SUBJECT"
ntfy "Deployed ${REMOTE:0:7}" "rocket" "$SUBJECT"
