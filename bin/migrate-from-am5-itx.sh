#!/usr/bin/env bash
# am5-itx で動いている healthcare スタックを Mac に引っ越す。
#
# やること (順番に):
#   1. am5-itx 側のスタックを停止 (docker compose down)
#      これで tailscale ノード "healthcare" がオフラインになり、Mac 側が
#      同名で上書き登録できる。
#   2. ./data (SQLite + Garmin token + 各種キャッシュ) を rsync で取得
#   3. tailscale-state volume の中身も取得 (任意 — ノード ID を引き継げる)
#   4. 次の手順を表示して終了 (Mac での起動は bin/up-mac.sh)
#
# 前提:
#   - tailnet で am5-itx に SSH で入れる (~/.ssh/config 等で設定済み)
#   - 既にこのリポを Mac 側 ($PWD) に clone 済み
#
# 使い方:
#   REMOTE_HOST=am5-itx \
#   REMOTE_USER=tsuyoshi \
#   REMOTE_PATH=~/ghq/github.com/nagamine-git/healthcare \
#     bin/migrate-from-am5-itx.sh
set -euo pipefail
cd "$(dirname "$0")/.."

REMOTE_HOST="${REMOTE_HOST:-am5-itx}"
REMOTE_USER="${REMOTE_USER:-tsuyoshi}"
REMOTE_PATH="${REMOTE_PATH:-~/ghq/github.com/nagamine-git/healthcare}"
REMOTE="${REMOTE_USER}@${REMOTE_HOST}"

echo "==> remote: ${REMOTE}:${REMOTE_PATH}"

echo "==> 1. am5-itx 側のスタックを停止"
ssh "$REMOTE" "cd ${REMOTE_PATH} && docker compose --env-file .env.runtime down"

echo
echo "==> 2. ./data を取得 (SQLite WAL safe: 停止後なので read-only コピーで OK)"
mkdir -p data
rsync -avz --delete \
  "${REMOTE}:${REMOTE_PATH}/data/" \
  ./data/

echo
echo "==> 3. tailscale-state volume (ノード ID 引き継ぎ用) を取得 → /tmp/healthcare-tailscale-state.tar"
ssh "$REMOTE" "docker run --rm -v healthcare_tailscale-state:/state alpine tar -C /state -czf - ." \
  > /tmp/healthcare-tailscale-state.tar.gz

cat <<NEXT

==> 完了。次の手順:

  # (1) ノード ID を引き継ぎたい場合: 空の volume を作って tar を流し込む
  docker volume create healthcare_tailscale-state
  docker run --rm -v healthcare_tailscale-state:/state -v /tmp:/host alpine \
    sh -c 'cd /state && tar -xzf /host/healthcare-tailscale-state.tar.gz'

  # (1b) または引き継がず新規ノードで上書きする場合:
  #   Tailscale admin で healthcare ノードを delete してから bin/up-mac.sh

  # (2) 起動
  bin/up-mac.sh

  # (3) 疎通確認
  curl -fsS https://healthcare.\$(tailscale status --json | jq -r .MagicDNSSuffix)/healthz

NEXT
