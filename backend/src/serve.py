"""
Production entrypoint for the Railway ``backend`` service.

Runs two ``uvicorn`` servers concurrently in a single Python process:

- FastAPI REST + WebSocket on port ``8010`` (exposed as ``api.parley.quest``)
- FastMCP streamable-HTTP on port ``8020`` (exposed as ``mcp.parley.quest``)

The two servers share the process so Railway only needs to bill one
service, but Railway exposes each port through its own public domain —
see ``docs/deployment-setup.md``.

Local development still uses ``mise run backend`` / ``mise run serve-http``
which bypass this module entirely.
"""

from __future__ import annotations

import asyncio

import uvicorn

from .main import app as fastapi_app
from .mcp_server.server import create_http_app, create_mcp_server


async def _serve() -> None:
    mcp = create_mcp_server()
    mcp_app = create_http_app(mcp)

    api_config = uvicorn.Config(
        fastapi_app,
        host="0.0.0.0",
        port=8010,
        log_level="info",
        # Railway terminates TLS upstream of the container.
        proxy_headers=True,
        forwarded_allow_ips="*",
    )
    mcp_config = uvicorn.Config(
        mcp_app,
        host="0.0.0.0",
        port=8020,
        log_level="info",
        proxy_headers=True,
        forwarded_allow_ips="*",
    )

    api_server = uvicorn.Server(api_config)
    mcp_server = uvicorn.Server(mcp_config)

    await asyncio.gather(api_server.serve(), mcp_server.serve())


def main() -> None:
    asyncio.run(_serve())


if __name__ == "__main__":
    main()
