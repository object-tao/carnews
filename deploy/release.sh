#!/usr/bin/env bash
set -Eeuo pipefail
cd /opt/kunteng-truck
exec 9>.deploy.lock
flock -n 9 || { echo "Another release is running"; exit 1; }
image="${1:?Pass versioned image}"
[[ "$image" =~ ^ghcr\.io/object-tao/carnews:[a-f0-9]{40}$ ]] || { echo "Unexpected image reference"; exit 1; }
test -f .env
test -f compose.yml
mkdir -p backups
chmod 700 backups
previous="$(cat .current-image 2>/dev/null || true)"
export APP_IMAGE="$image"
docker compose pull web
# SQLite backup API creates a consistent snapshot even if the old web process is running.
if test -f data/db.sqlite3; then
    python3 - "backups/$(date -u +%Y%m%dT%H%M%SZ).sqlite3" <<'PY'
import sqlite3, sys
with sqlite3.connect('data/db.sqlite3') as source, sqlite3.connect(sys.argv[1]) as target:
    source.backup(target)
PY
fi
docker compose run --rm web python manage.py migrate --noinput
docker compose run --rm web python manage.py seed_content
docker compose run --rm web python manage.py import_ports --publish-reviewed
docker compose run --rm web python manage.py publish_reviewed_ports
docker compose run --rm web python manage.py backfill_port_images
docker compose run --rm web python manage.py upgrade_port_images
docker compose run --rm web python manage.py import_knowledge --publish
docker compose run --rm web python manage.py import_vehicles --publish
docker compose run --rm web python manage.py import_bridges --publish
docker compose run --rm web python manage.py import_loading_rules --publish
docker compose up -d --no-deps web
for i in $(seq 1 30); do
    container="$(docker compose ps -q web)"
    if test -n "$container" && test "$(docker inspect --format '{{.State.Health.Status}}' "$container")" = healthy; then
        printf '%s\n' "$previous" > .previous-image
        printf '%s\n' "$image" > .current-image
        echo "Release healthy: $image"
        exit 0
    fi
    sleep 2
done
echo "Health check failed"
docker compose logs --tail=60 web
if test -n "$previous"; then
    APP_IMAGE="$previous" docker compose up -d --no-deps web
    echo "Previous application image restored; database was NOT rolled back. Review migration compatibility."
fi
exit 1
