#!/bin/sh
# Production container entrypoint. Applies pending migrations and
# hands off to the server command.
#
# Migrations run from ``/app/backend`` because ``alembic.ini``'s
# ``prepend_sys_path = .`` and ``script_location = migrations`` are
# both relative to that directory. ``PARLEY_DATABASE_URL`` (falling
# back to ``DATABASE_URL``) is read by ``migrations/env.py``.

set -eu

cd /app/backend

echo "[docker-entrypoint] Running alembic upgrade head..."
uv run alembic upgrade head

cd /app
echo "[docker-entrypoint] Starting: $*"
exec "$@"
