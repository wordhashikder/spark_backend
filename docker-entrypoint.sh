#!/bin/sh
# Apply migrations and reference data, then start the API.
set -e

alembic upgrade head
python -m app.cli seed-locations

# Content batches (blog articles, the imported installer directory listings and,
# where allowed, the showcase installers). Each batch is added once, ever: what the
# admin edits or deletes afterwards is never re-added. Safe with several replicas.
python -m app.cli seed-content

# The API runs behind Coolify's Traefik proxy on a private network, so the
# forwarded headers are trusted.
exec uvicorn app.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers "${WEB_CONCURRENCY:-2}" \
    --proxy-headers \
    --no-server-header \
    --forwarded-allow-ips '*'
