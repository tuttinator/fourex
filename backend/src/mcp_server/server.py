"""
4X Game MCP Server.

Supports stdio and streamable-http transports. The streamable-http
transport includes CORS middleware and a /healthz endpoint.
"""

import argparse
import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from ..database.connection import close_db, init_db
from .tools import analysis, gameplay, history, lifecycle, memory


def create_mcp_server() -> FastMCP:
    """Create and configure the FastMCP server with all tool modules."""
    mcp = FastMCP(
        "4X Game Server",
        instructions=(
            "This MCP server lets AI agents play a 4X turn-based strategy game. "
            "Start by creating or joining a game to get an API key. "
            "Use that key in all subsequent tool calls."
        ),
    )

    # Register tool modules
    lifecycle.register(mcp)
    gameplay.register(mcp)
    memory.register(mcp)
    history.register(mcp)
    analysis.register(mcp)

    return mcp


def create_http_app(mcp: FastMCP) -> Starlette:
    """Wrap the MCP server in a Starlette app with CORS and /healthz."""

    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        await init_db()
        yield
        await close_db()

    async def healthz(request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "server": "4x-mcp"})

    # Get the base MCP streamable-http app
    mcp_app = mcp.streamable_http_app()

    # Build a wrapper Starlette app with healthz + CORS
    app = Starlette(
        routes=[
            Route("/healthz", healthz, methods=["GET"]),
        ],
        middleware=[
            Middleware(
                CORSMiddleware,
                allow_origins=["*"],
                allow_methods=["*"],
                allow_headers=["*"],
            ),
        ],
        lifespan=lifespan,
    )

    # Mount the MCP app at /mcp
    app.mount("/mcp", mcp_app)

    return app


async def run_stdio(mcp: FastMCP) -> None:
    """Run the MCP server over stdio."""
    await init_db()
    try:
        await mcp.run_stdio_async()
    finally:
        await close_db()


def main() -> None:
    """CLI entry point for the MCP server."""
    parser = argparse.ArgumentParser(description="4X Game MCP Server")
    parser.add_argument(
        "transport",
        choices=["stdio", "http"],
        default="stdio",
        nargs="?",
        help="Transport mode (default: stdio)",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="HTTP host (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8020,
        help="HTTP port (default: 8020)",
    )
    args = parser.parse_args()

    mcp = create_mcp_server()

    if args.transport == "stdio":
        asyncio.run(run_stdio(mcp))
    else:
        import uvicorn

        app = create_http_app(mcp)
        uvicorn.run(app, host=args.host, port=args.port)


def main_http() -> None:
    """CLI entry point for the MCP server in HTTP mode (used by fourex-mcp-http)."""
    import uvicorn

    mcp = create_mcp_server()
    app = create_http_app(mcp)
    uvicorn.run(app, host="0.0.0.0", port=8020)


if __name__ == "__main__":
    main()
