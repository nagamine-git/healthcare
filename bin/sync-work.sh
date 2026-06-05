#!/usr/bin/env bash
# orion (仕事) の活動量を healthcare の「仕事ドメイン」に取り込む。
# 指標: Step Gate 完遂率 + 直近7日の git コミット + 直近30日の council 議事録 を等配で合成。
#
# 使い方:
#   HEALTHCARE_URL=https://healthcare.<tailnet>.ts.net bin/sync-work.sh [YYYY-MM-DD]
# 環境変数:
#   LAB_DIR         lab リポジトリのパス (既定: ~/ghq/github.com/efg-technologies/lab)
#   HEALTHCARE_URL  healthcare の URL (必須)
set -euo pipefail

LAB="${LAB_DIR:-$HOME/ghq/github.com/efg-technologies/lab}"
HC_URL="${HEALTHCARE_URL:?HEALTHCARE_URL is required (例: https://healthcare.<tailnet>.ts.net)}"
DATE="${1:-$(date +%F)}"
[ -d "$LAB" ] || { echo "lab リポジトリが見つかりません: $LAB" >&2; exit 1; }

# Step Gate 完遂率 (orion の step*.md のチェックボックス)
done_n=$(grep -rho "\[x\]" "$LAB"/plans/orion/step*.md 2>/dev/null | wc -l | tr -d ' ')
todo_n=$(grep -rho "\[ \]" "$LAB"/plans/orion/step*.md 2>/dev/null | wc -l | tr -d ' ')
total=$((done_n + todo_n)); [ "$total" -eq 0 ] && total=1
step=$((done_n * 100 / total))

# 直近7日の git コミット (7 commit で 100)
commits=$(git -C "$LAB" log --oneline --since="7 days ago" 2>/dev/null | wc -l | tr -d ' ')
gitscore=$((commits * 14)); [ "$gitscore" -gt 100 ] && gitscore=100

# 直近30日の council 議事録 (5 件で 100)
council=$(find "$LAB/council" -maxdepth 1 -name "*.md" ! -name "README.md" -mtime -30 2>/dev/null | wc -l | tr -d ' ')
cscore=$((council * 20)); [ "$cscore" -gt 100 ] && cscore=100

ach=$(((step + gitscore + cscore) / 3))
detail="step ${step} / git ${gitscore} / council ${cscore}"
echo "work achievement: $ach  ($detail)"
curl -fsS -X POST "$HC_URL/api/domain/work/ingest" -H 'Content-Type: application/json' \
  -d "{\"date\":\"$DATE\",\"achievement\":$ach,\"detail\":\"$detail\"}"
echo
