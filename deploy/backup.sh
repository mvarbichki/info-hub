#!/bin/sh
# Nightly job: clean up unused uploads, then dump the database.
#   1. cleanup_media: deletes media nothing uses, page versions older than 90 days, old sessions.
#   2. Database dump (kept 14 days). The uploaded files themselves are covered by the backup of the
#      whole VM; the dump adds a clean, consistent copy of the database to restore from.
# Cron example (as root, 02:30 every night):
#   30 2 * * * /opt/infohub/deploy/backup.sh >> /var/log/infohub-backup.log 2>&1
set -e
cd "$(dirname "$0")/.."

DEST="${BACKUP_DIR:-/srv/backups/infohub}"
STAMP="$(date +%F_%H%M)"
mkdir -p "$DEST/db"

docker compose exec -T web python manage.py cleanup_media

docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' | gzip > "$DEST/db/infohub_$STAMP.sql.gz"
find "$DEST/db" -name '*.sql.gz' -mtime +14 -delete

echo "$(date '+%F %T') cleanup + database dump OK -> $DEST/db"
