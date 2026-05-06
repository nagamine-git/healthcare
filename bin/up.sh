#!/usr/bin/env bash
# 1Password で env を解決し、ヘルスケアスタック全体を起動する。
# 1Password CLI の認証 (Touch ID 等) が走ります。

set -euo pipefail

cd "$(dirname "$0")/.."

if ! command -v op >/dev/null 2>&1; then
  echo "1Password CLI (op) が見つかりません。https://1password.com/downloads/command-line/" >&2
  exit 1
fi

if ! op account list >/dev/null 2>&1; then
  echo "op がサインインしていません。'op signin' を先に実行してください。" >&2
  exit 1
fi

echo "==> docker compose up -d --build (op run で env を解決)"
op run --env-file=.env.tmpl -- docker compose up -d --build

echo
echo "==> サービス状態"
docker compose ps

echo
echo "==> Tailscale 上のホスト名 / 証明書ドメインを確認"
docker compose logs --tail=50 tailscale 2>&1 | grep -E "(Tailscale started|cert|MagicDNS|Logging in)" || true

cat <<'NEXT'

次のステップ:
  1. Garmin Connect の初回ログイン (MFA 入力に対応)
       bin/garmin-login.sh
  2. https://<hostname>.<tailnet>.ts.net/healthz が 200 を返すか確認
  3. iPhone の Health Auto Export に URL と Bearer を設定
       URL:    https://<hostname>.<tailnet>.ts.net/ingest/health-auto-export
       Header: Authorization = Bearer $(op item get 3jtudssyhgh3kajjjvq7ek3v6y --field password --reveal)
NEXT
