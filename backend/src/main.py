"""
FastAPI application entry point.
"""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware

from .api.api_keys import router as api_keys_router
from .api.archive_sweep import archive_sweep_loop
from .api.identities import router as identities_router
from .api.rest import router as rest_router
from .api.websocket import router as websocket_router
from .config import settings
from .database.connection import close_db, init_db
from .mcp_server.server import create_mcp_server

# Create MCP server and its HTTP app early so the lifespan can start its session manager.
_mcp = create_mcp_server()
_mcp_http = _mcp.streamable_http_app()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    # Startup: Initialize database
    try:
        await init_db()
        print("Database migrations applied successfully")
    except Exception as e:
        print(f"Database initialization failed: {e}")
        raise

    # Phase 5 (spectated-agents): background sweep that soft-archives
    # stale waiting lobbies and dormant active games. The first tick
    # fires after ``archive_sweep_interval_seconds`` — never immediately
    # at startup — so boot stays cheap and tests don't catch an eager
    # pass. Gated by ``archive_sweep_enabled`` so tests can disable it.
    sweep_task: asyncio.Task[None] | None = None
    if settings.archive_sweep_enabled:
        sweep_task = asyncio.create_task(archive_sweep_loop())

    # Start the MCP session manager (manages async task groups for MCP sessions).
    # Must run inside the lifespan because mounted sub-apps don't get their own.
    assert _mcp._session_manager is not None
    try:
        async with _mcp._session_manager.run():
            yield
    finally:
        if sweep_task is not None:
            sweep_task.cancel()
            try:
                await sweep_task
            except asyncio.CancelledError:
                pass

    # Shutdown: Close database connections
    try:
        await close_db()
        print("Database connections closed")
    except Exception as e:
        print(f"Error closing database: {e}")


app = FastAPI(
    title="4X Game Backend",
    description="Turn-based strategy sandbox for AI agents",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    openapi_tags=[
        {
            "name": "health",
            "description": "Health check and status endpoints",
        },
        {
            "name": "games",
            "description": "Game management operations",
        },
        {
            "name": "state",
            "description": "Game state and player actions",
        },
        {
            "name": "websockets",
            "description": "Real-time game updates via WebSocket",
        },
        {
            "name": "identity",
            "description": "Server-to-server identity upsert called by the Next.js Auth.js adapter",
        },
    ],
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(rest_router, prefix="/api/v1")
app.include_router(websocket_router, prefix="/api/v1")
app.include_router(identities_router, prefix="/api/v1")
app.include_router(api_keys_router, prefix="/api/v1")


# Mount MCP streamable-http server — shares DB, CORS, and autoreload.
# streamable_http_path="/" in create_mcp_server(), so mounting at /mcp
# gives a clean /mcp external endpoint.
app.mount("/mcp", _mcp_http)


@app.get("/", tags=["health"])
async def root():
    """Health check endpoint."""
    return {"status": "ok", "message": "4X Game Backend"}


@app.get("/health", tags=["health"])
async def health():
    """Detailed health check."""
    return {
        "status": "healthy",
        "version": "0.1.0",
        "debug": settings.debug,
    }


@app.get("/healthz", tags=["health"])
async def healthz():
    """Kubernetes/Railway-style health probe (api.parley.quest/healthz)."""
    return {"status": "ok", "server": "4x-api"}


@app.websocket("/test-ws")
async def test_websocket(websocket: WebSocket):
    """Test WebSocket endpoint."""
    await websocket.accept()
    await websocket.send_text("Hello WebSocket!")
    await websocket.close()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.debug,
    )
