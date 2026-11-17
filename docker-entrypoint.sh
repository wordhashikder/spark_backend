#!/bin/sh
set -e

alembic upgrade head
python -m app.cli seed-locations

python -m app.cli seed-content

# The one administrator (ADMIN_EMAIL / ADMIN_PASSWORD). A mistake here is reported but must
# never keep the API from starting; fix the variables and redeploy.
python -m app.cli seed-admin || echo "WARNING: the administrator was not created (see above)." >&2

exec uvicorn app.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers "${WEB_CONCURRENCY:-2}" \
    --proxy-headers \
    --no-server-header \
    --forwarded-allow-ips '*'
