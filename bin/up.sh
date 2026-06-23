#!/usr/bin/env bash
# 1Password で env を解決し、ヘルスケアスタック全体を起動する。
# 1Password CLI の認証 (Touch ID 等) が走ります。
#
# 解決した値は .env.runtime (chmod 600) に書き出し、systemd 経由の
# 自動起動でも同じ env が使えるようにする。

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

echo "==> .env.tmpl を 1Password で解決して .env.runtime に書き出し"
# .env.tmpl から変数名を抽出 (コメント・空行を除く)
keys=$(grep -E '^[A-Z_][A-Z0-9_]*=' .env.tmpl | cut -d= -f1 | tr '\n' ' ')

umask 077
op run --no-masking --env-file=.env.tmpl -- bash -c '
  for k in '"$keys"'; do
    printf "%s=%s\n" "$k" "${!k}"
  done
' > .env.runtime

# gitignore したローカル秘密 overlay (.env.secrets.local) を追記する。
# 1Password に置けない/置きたくない秘密 (例: Web Push VAPID 秘密鍵) をここで合流させる。
if [[ -f .env.secrets.local ]]; then
  echo "==> .env.secrets.local を .env.runtime に追記"
  grep -E '^[A-Z_][A-Z0-9_]*=' .env.secrets.local >> .env.runtime
fi
chmod 600 .env.runtime

echo "==> docker compose up -d --build"
docker compose --env-file .env.runtime up -d --build

echo
echo "==> サービス状態"
docker compose --env-file .env.runtime ps

echo
echo "==> Tailscale 上のホスト名 / 証明書ドメインを確認"
docker compose --env-file .env.runtime logs --tail=50 tailscale 2>&1 | grep -E "(Tailscale started|cert|MagicDNS|Logging in)" || true

cat <<'NEXT'

次のステップ:
  1. Garmin Connect の初回ログイン (MFA 入力に対応)
       bin/garmin-login.sh
  2. https://<hostname>.<tailnet>.ts.net/healthz が 200 を返すか確認
  3. iPhone の Health Auto Export に URL と Bearer を設定
       URL:    https://<hostname>.<tailnet>.ts.net/ingest/health-auto-export
       Header: Authorization = Bearer $(op item get 3jtudssyhgh3kajjjvq7ek3v6y --field password --reveal)
NEXT
