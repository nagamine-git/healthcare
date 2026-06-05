#!/usr/bin/env bash
# macOS 版 up: docker-compose.mac.yml overlay 込みで起動する。
# bin/up.sh と同じく 1Password で env を解決して .env.runtime に書き出す。
set -euo pipefail
cd "$(dirname "$0")/.."

if ! command -v op >/dev/null 2>&1; then
  echo "1Password CLI (op) が見つかりません。" >&2
  exit 1
fi
if ! op account list >/dev/null 2>&1; then
  echo "op がサインインしていません。'op signin' を先に実行してください。" >&2
  exit 1
fi
if ! command -v docker >/dev/null 2>&1; then
  echo "docker が見つかりません。Docker Desktop / OrbStack / Colima のいずれかを入れてください。" >&2
  exit 1
fi

echo "==> .env.tmpl を 1Password で解決して .env.runtime に書き出し"
keys=$(grep -E '^[A-Z_][A-Z0-9_]*=' .env.tmpl | cut -d= -f1 | tr '\n' ' ')
umask 077
# op が失敗しても既存の .env.runtime を壊さないよう一時ファイル経由で書く
tmpenv=$(mktemp .env.runtime.XXXXXX)
trap 'rm -f "$tmpenv"' EXIT
op run --no-masking --env-file=.env.tmpl -- bash -c '
  for k in '"$keys"'; do
    printf "%s=%s\n" "$k" "${!k}"
  done
' > "$tmpenv"
chmod 600 "$tmpenv"
mv "$tmpenv" .env.runtime
trap - EXIT

echo "==> docker compose up -d --build (mac overlay)"
docker compose \
  -f docker-compose.yml \
  -f docker-compose.mac.yml \
  --env-file .env.runtime \
  up -d --build

echo
echo "==> サービス状態"
docker compose -f docker-compose.yml -f docker-compose.mac.yml --env-file .env.runtime ps

echo
echo "==> tailscale sidecar ログ (起動/cert 周り)"
docker compose -f docker-compose.yml -f docker-compose.mac.yml --env-file .env.runtime \
  logs --tail=80 tailscale 2>&1 | grep -E "(Tailscale started|cert|MagicDNS|Logging in|userspace)" || true

cat <<'NEXT'

次のステップ:
  1. Garmin 初回ログイン (am5-itx からデータ移送する場合は不要):
       bin/garmin-login.sh
  2. ブラウザで https://healthcare.<tailnet>.ts.net/healthz が 200 を返すか確認
NEXT
