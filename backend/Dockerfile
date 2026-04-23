# Production image for the Railway ``backend`` service.
#
# Builds a single container that runs the FastAPI REST/WS server on port 8010
# and the FastMCP streamable-HTTP server on port 8020 as two async tasks in
# one Python process (``backend.src.serve``). The entrypoint runs Alembic
# migrations against ``PARLEY_DATABASE_URL`` before starting the servers.

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_SYSTEM_PYTHON=1 \
    UV_LINK_MODE=copy

# cairo is required by cairosvg (PNG map rendering). libpq is pulled in as a
# transitive for some build tooling; the runtime actually uses asyncpg.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libcairo2 \
        libpango-1.0-0 \
        libpangocairo-1.0-0 \
        libgdk-pixbuf2.0-0 \
        libffi-dev \
        libpq-dev \
        curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

WORKDIR /app

# Copy metadata first so ``uv sync`` can cache its layer when sources change.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev

# Copy application code last — anything above here changes rarely.
COPY backend ./backend

ENV PYTHONPATH=/app \
    PARLEY_MIGRATIONS_DIR=/app/backend

# api.parley.quest → 8010, mcp.parley.quest → 8020.
EXPOSE 8010 8020

COPY backend/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["uv", "run", "python", "-m", "backend.src.serve"]
