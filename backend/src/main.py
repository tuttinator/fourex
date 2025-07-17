"""
FastAPI application entry point.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware

from .api.rest import router as rest_router
from .api.websocket import router as websocket_router
from .config import settings
from .database.connection import close_db, init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    # Startup: Initialize database
    try:
        await init_db()
        print("Database initialized successfully")
    except Exception as e:
        print(f"Database initialization failed: {e}")
        raise

    yield

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


@app.websocket("/test-ws", tags=["websockets"])
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
