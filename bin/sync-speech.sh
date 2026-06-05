#!/usr/bin/env bash
# speech-coach の指定日 (既定: 今日) のサマリを healthcare に取り込む。
# speech-coach の sessions.db を読み、日次集計を /api/speech/ingest に POST する。
#
# 使い方:
#   HEALTHCARE_URL=https://healthcare.<tailnet>.ts.net bin/sync-speech.sh [YYYY-MM-DD]
# 環境変数:
#   SPEECH_COACH_DB  speech-coach の SQLite パス (既定: ~/.local/share/speech-coach/sessions.db)
#   HEALTHCARE_URL   healthcare の URL (必須)
set -euo pipefail

DB="${SPEECH_COACH_DB:-$HOME/.local/share/speech-coach/sessions.db}"
HC_URL="${HEALTHCARE_URL:?HEALTHCARE_URL is required (例: https://healthcare.<tailnet>.ts.net)}"
DATE="${1:-$(date +%F)}"

command -v sqlite3 >/dev/null 2>&1 || { echo "sqlite3 が必要です" >&2; exit 1; }
[ -f "$DB" ] || { echo "speech-coach DB が見つかりません: $DB" >&2; exit 1; }

row=$(sqlite3 -separator '|' "$DB" \
  "SELECT COUNT(*),
          IFNULL(ROUND(SUM(duration_sec)/60.0,1),0),
          IFNULL(ROUND(AVG(score_overall),1),''),
          IFNULL(ROUND(AVG(score_pace),1),''),
          IFNULL(ROUND(AVG(score_pitch),1),''),
          IFNULL(ROUND(AVG(score_clarity),1),''),
          IFNULL(ROUND(AVG(score_filler),1),'')
   FROM sessions WHERE DATE(started_at)='$DATE';")

IFS='|' read -r cnt dur ov pace pitch clar fil <<<"$row"

if [ "${cnt:-0}" -eq 0 ]; then
  echo "speech: $DATE のセッションなし、スキップ"
  exit 0
fi

j() { [ -z "$1" ] && echo null || echo "$1"; }
payload=$(cat <<JSON
{"date":"$DATE","session_count":$cnt,"duration_min":$(j "$dur"),"score_overall":$(j "$ov"),"score_pace":$(j "$pace"),"score_pitch":$(j "$pitch"),"score_clarity":$(j "$clar"),"score_filler":$(j "$fil")}
JSON
)

echo "POST $HC_URL/api/speech/ingest  ($DATE, $cnt sessions)"
curl -fsS -X POST "$HC_URL/api/speech/ingest" -H 'Content-Type: application/json' -d "$payload"
echo
