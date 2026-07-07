#!/bin/sh
# 毎晩のバックアップ: DB+チラシ+申込原本+PocketBase を rclone でオフサイトへ。
# 保持14日。個人情報を含むため、送り先は機関管理の領域とすること(docs/04)。
set -eu

STAMP=$(date +%Y%m%d)
WORK=/srv/seminar/backup
REMOTE="offsite:seminar-backup"  # rclone のリモート名(機関管理)

mkdir -p "$WORK"
pg_dump seminar | gzip > "$WORK/db-$STAMP.sql.gz"
tar czf "$WORK/files-$STAMP.tar.gz" -C /srv/seminar flyers received pb_data

rclone copy "$WORK" "$REMOTE/$STAMP/"
find "$WORK" -type f -mtime +14 -delete
rclone delete --min-age 14d "$REMOTE" || true
