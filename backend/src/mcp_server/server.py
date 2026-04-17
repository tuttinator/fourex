"""
4X Game MCP Server.

Supports stdio and streamable-http transports. The streamable-http
transport includes CORS middleware and a /healthz endpoint.
"""

import argparse
import asyncio

from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
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
        # Internal path set to "/" so mounting at "/mcp" gives a clean "/mcp" external path
        streamable_http_path="/",
    )

    # Register tool modules
    lifecycle.register(mcp)
    gameplay.register(mcp)
    memory.register(mcp)
    history.register(mcp)
    analysis.register(mcp)

    return mcp


def create_http_app(mcp: FastMCP) -> Starlette:
    """Build the MCP streamable-http app with CORS and /healthz.

    We inject extra routes and middleware into the MCP app itself rather
    than wrapping it in another Starlette app — the MCP app's lifespan
    manages internal task groups that break if a wrapper intercepts them.
    """

    async def healthz(request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "server": "4x-mcp"})

    # Get the base MCP streamable-http app (has its own lifespan)
    app = mcp.streamable_http_app()

    # Inject /healthz route
    app.routes.insert(0, Route("/healthz", healthz, methods=["GET"]))

    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    return app


async def run_stdio(mcp: FastMCP) -> None:
    """Run the MCP server over stdio."""
    try:
        await init_db()
    except Exception:
        # DB may be unavailable at startup — tools will fail individually
        # when they try to open a session, but the server stays alive so
        # the MCP client can still discover tools.
        pass
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

        asyncio.run(init_db())
        app = create_http_app(mcp)
        uvicorn.run(app, host=args.host, port=args.port)


def main_http() -> None:
    """CLI entry point for the MCP server in HTTP mode (used by fourex-mcp-http)."""
    import uvicorn

    # Init DB before server starts (MCP app lifespan doesn't handle it)
    asyncio.run(init_db())

    mcp = create_mcp_server()
    app = create_http_app(mcp)
    uvicorn.run(app, host="0.0.0.0", port=8020)


if __name__ == "__main__":
    main()
