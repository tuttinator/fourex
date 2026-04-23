#!/bin/sh
# Production container entrypoint. Runs Alembic migrations against
# ``PARLEY_DATABASE_URL`` (or ``DATABASE_URL`` as a fallback) before
# handing off to the server command.

set -eu

cd "${PARLEY_MIGRATIONS_DIR:-/app/backend}"

echo "[docker-entrypoint] Running Alembic migrations..."
uv run alembic upgrade head

cd /app
echo "[docker-entrypoint] Starting: $*"
exec "$@"
