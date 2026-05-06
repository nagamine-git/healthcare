#!/usr/bin/env bash
# Google Calendar 認可フロー (1 回のみ)。
#
# OAuth はブラウザを使うのでホスト側で実行する。
# 完了すると ./data/google_tokens/token.json が生成され、
# bind mount 経由で backend コンテナから読まれる。

set -euo pipefail
cd "$(dirname "$0")/.."

GCAL_ITEM_ID="${GCAL_ITEM_ID:-eqrl4kw24dm7mazrhpwdshiipq}"
TOKEN_DIR="data/google_tokens"
CLIENT_SECRET="$TOKEN_DIR/client_secret.json"
mkdir -p "$TOKEN_DIR"

if [ ! -w "$TOKEN_DIR" ]; then
  echo "$TOKEN_DIR に書き込み権限がありません。" >&2
  echo "コンテナの root が作った可能性があるので、以下で消してから再実行してください:" >&2
  echo "  docker exec healthcare-backend rm -rf /data/google_tokens && mkdir -p $TOKEN_DIR && chmod 700 $TOKEN_DIR" >&2
  exit 1
fi

if [ ! -f "$CLIENT_SECRET" ]; then
  echo "==> 1Password から client_secret を取得 (item: $GCAL_ITEM_ID)"
  if ! op document get "$GCAL_ITEM_ID" > "$CLIENT_SECRET" 2>/dev/null; then
    echo "1Password CLI から取得失敗。client_secret.json を以下に手動配置してください:" >&2
    echo "  $CLIENT_SECRET" >&2
    rm -f "$CLIENT_SECRET"
    exit 1
  fi
  chmod 600 "$CLIENT_SECRET"
fi

if [ ! -d backend/.venv ]; then
  echo "backend/.venv が無い。先にローカル開発環境をセットアップしてください:"
  echo "  cd backend && uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -e ."
  exit 1
fi

echo "==> OAuth フロー開始"
echo "    ブラウザが自動で開かなければ、表示される URL を手動でブラウザに貼り付けてください。"
echo "    認可後、ローカルにリダイレクトされて自動完了します。"
echo
APP_DATA_DIR="$(pwd)/data" backend/.venv/bin/python -m app.cli gcal-login
