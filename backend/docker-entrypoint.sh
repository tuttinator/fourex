#!/bin/sh
# Production container entrypoint. Bootstraps the database against
# ``PARLEY_DATABASE_URL`` (or ``DATABASE_URL`` as a fallback) before
# handing off to the server command.
#
# ``db_bootstrap`` handles both fresh databases (runs ``create_all`` +
# ``alembic stamp head``) and already-initialised ones (runs
# ``alembic upgrade head``). See ``backend/src/db_bootstrap.py`` for
# why the fresh-db path differs from a plain ``alembic upgrade``.

set -eu

cd /app

echo "[docker-entrypoint] Bootstrapping database..."
uv run python -m backend.src.db_bootstrap

echo "[docker-entrypoint] Starting: $*"
exec "$@"
