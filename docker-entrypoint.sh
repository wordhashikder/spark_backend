#!/bin/sh
# Apply migrations and reference data, then start the API.
set -e

alembic upgrade head
python -m app.cli seed-locations

# The API runs behind Coolify's Traefik proxy on a private network, so the
# forwarded headers are trusted.
exec uvicorn app.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers "${WEB_CONCURRENCY:-2}" \
    --proxy-headers \
    --no-server-header \
    --forwarded-allow-ips '*'
