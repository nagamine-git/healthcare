#!/usr/bin/env bash
# 環境疎通の確認。
#  - .env.tmpl の op:// 参照がすべて解決できるか
#  - tailnet 越しの /healthz が 200 か
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> .env.tmpl の op:// 参照"
ok=0; fail=0
while read -r ref; do
  printf '  %-70s ' "$ref"
  if op read "$ref" >/dev/null 2>&1; then
    echo OK
    ok=$((ok+1))
  else
    echo FAIL
    fail=$((fail+1))
  fi
done < <(grep -oE 'op://[^"]+' .env.tmpl | sort -u)
echo "  -> ${ok} OK / ${fail} FAIL"

echo
echo "==> ローカルからの /healthz"
hostname=$(grep -E '^TS_HOSTNAME=' .env.tmpl | cut -d= -f2)
tailnet=$(tailscale status --json 2>/dev/null | jq -r '.MagicDNSSuffix' 2>/dev/null || echo '')
if [ -n "$tailnet" ]; then
  url="https://${hostname}.${tailnet}/healthz"
  echo "  GET $url"
  curl -fsS "$url" || echo "  (failed — まだコンテナが立ち上がっていない可能性)"
else
  echo "  tailscale CLI が無い、または tailscaled が動いていない。スキップ。"
fi
