#!/usr/bin/env bash
# healthcare DB の日次バックアップ。
# sqlite3 backup API で整合スナップショットを取り、docker volume の外
# (既定: ~/HealthcareBackups) へ gzip で保存。KEEP_DAYS 日でローテーション。
# launchd (com.nagamine.healthcare-backup) から毎日 04:00 に呼ばれる想定。
set -euo pipefail

DEST="${HEALTHCARE_BACKUP_DIR:-$HOME/HealthcareBackups}"
KEEP_DAYS="${HEALTHCARE_BACKUP_KEEP_DAYS:-14}"
mkdir -p "$DEST"

stamp=$(date +%Y%m%d-%H%M%S)

# コンテナ内で整合バックアップを作成 (稼働中でも安全)
docker exec -i healthcare-backend python - <<'PY'
import sqlite3
src = sqlite3.connect("/data/healthcare.sqlite3")
dst = sqlite3.connect("/tmp/healthcare-backup.sqlite3")
src.backup(dst)
dst.close()
src.close()
PY

docker cp healthcare-backend:/tmp/healthcare-backup.sqlite3 "$DEST/healthcare-$stamp.sqlite3"
docker exec healthcare-backend rm -f /tmp/healthcare-backup.sqlite3
gzip -f "$DEST/healthcare-$stamp.sqlite3"

# 古いバックアップを削除
find "$DEST" -name 'healthcare-*.sqlite3.gz' -mtime "+$KEEP_DAYS" -delete

echo "backup ok: $DEST/healthcare-$stamp.sqlite3.gz"
