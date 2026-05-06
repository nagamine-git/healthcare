#!/usr/bin/env bash
# Garmin Connect の対話ログイン (MFA 必須時)。トークンは backend コンテナの
# 永続ボリューム /data/garmin_tokens に保存される。
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose exec backend python -m app.cli garmin-login
