#!/usr/bin/env bash
# Daily pg_dump into $BACKUP_DIR, keeps 14 days. Connection: PGHOST/PGUSER/PGPASSWORD/PGDATABASE.
#   BACKUP_ONCE=1 scripts/backup.sh   one pass and exit
set -euo pipefail

DIR="${BACKUP_DIR:-/backups}"
mkdir -p "$DIR"

while true; do
  file="$DIR/veydranox-$(date -u +%F).dump"
  # Write to a temp name first so a failed dump never replaces a good one.
  if pg_dump -Fc -f "$file.tmp"; then
    mv "$file.tmp" "$file" && echo "backup: $file"
  else
    rm -f "$file.tmp"; echo "backup failed" >&2; ok=1
  fi
  # -mtime +13: 14 full days or older.
  find "$DIR" -maxdepth 1 -name 'veydranox-*.dump' -mtime +13 -delete
  [[ "${BACKUP_ONCE:-}" == "1" ]] && exit "${ok:-0}"
  sleep 86400
done
