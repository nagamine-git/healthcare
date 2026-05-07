#!/usr/bin/env bash
# Install / re-install the "Healthcare Critical Watch" cron job into openclaw.
# Idempotent: removes any existing job with the same name first.
set -euo pipefail

cd "$(dirname "$0")/.."

JOB_NAME="Healthcare Critical Watch"
JOB_FILE="systemd/openclaw-healthcare-watch.json"

if ! command -v openclaw >/dev/null 2>&1; then
  echo "openclaw CLI not found in PATH" >&2
  exit 1
fi

if [[ ! -f "$JOB_FILE" ]]; then
  echo "$JOB_FILE not found (run from healthcare repo root)" >&2
  exit 1
fi

MSG=$(jq -r '.payload.message' "$JOB_FILE")

EXISTING_ID=$(openclaw cron list --json 2>/dev/null \
  | jq -r --arg n "$JOB_NAME" '.jobs[] | select(.name==$n) | .id' \
  | head -n1 || true)
if [[ -n "${EXISTING_ID:-}" ]]; then
  echo "removing existing job: $EXISTING_ID"
  openclaw cron rm "$EXISTING_ID"
fi

openclaw cron add \
  --name "$JOB_NAME" \
  --agent main \
  --session-key 'agent:main:main' \
  --session isolated \
  --cron '50 6 * * *' \
  --tz 'Asia/Tokyo' \
  --announce \
  --channel last \
  --wake now \
  --timeout-seconds 60 \
  --message "$MSG"

echo
echo '--- openclaw cron list ---'
openclaw cron list
