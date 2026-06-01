"""
MCP client adapters used by the Phase 6 agent runtime.

The agent runtime is deliberately transport-agnostic: it only needs an
object with an async ``call_tool(name, arguments) -> dict`` method. Two
adapters ship here:

- ``InProcessMCPClient`` wraps a FastMCP server instance and dispatches
  tool calls directly in-process. This is what tests and self-play
  drivers use — no network hop, no stdio pipe, just a function call.
- ``StreamableHTTPMCPClient`` is a thin wrapper around ``httpx`` for
  talking to a running ``fourex-mcp-http`` server. It does a single bare
  JSON-RPC POST with no ``initialize`` handshake — fine only against a
  *stateless* server. The deployed server (mcp.parley.quest) is
  **stateful** and rejects this with ``400 Missing session ID``.
- ``OfficialStreamableHTTPMCPClient`` wraps the official ``mcp`` Python
  streamable-http client. It performs the real handshake (``initialize``
  + ``notifications/initialized``), carries the ``Mcp-Session-Id`` header
  on every call, and parses SSE responses. This is the adapter to use
  against any live FastMCP streamable-http deployment.

All adapters return already-decoded dicts so the rest of the agent
code does not have to care whether the tool ran in-process or remotely.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import AsyncExitStack
from typing import Any, Protocol

from mcp.server.fastmcp import FastMCP


class MCPClient(Protocol):
    """Structural protocol the agent runtime consumes."""

    async def call_tool(
        self, name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]: ...


def _unwrap_tool_result(result: Any) -> dict[str, Any]:
    """Normalise FastMCP tool results into a plain dict.

    FastMCP v3's ``call_tool`` returns either a tuple
    ``(content_list, structured_dict)`` or a list of ``TextContent``
    depending on whether the tool is annotated to return structured
    content. We support both shapes.
    """
    if isinstance(result, tuple) and len(result) == 2:
        _content, structured = result
        if isinstance(structured, dict):
            return structured
    # Fallback: single TextContent with a JSON body.
    if isinstance(result, list) and result:
        first = result[0]
        text = getattr(first, "text", None)
        if text:
            try:
                parsed = json.loads(text)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                return {"raw": text}
    return {"error": "Unrecognised tool result shape"}


class InProcessMCPClient:
    """Dispatches tool calls straight to a FastMCP server instance.

    Useful for tests, self-play drivers, and any code that already owns
    the backend process. Avoids the overhead of stdio or HTTP for what
    is otherwise just a function call.
    """

    def __init__(self, mcp: FastMCP):
        self._mcp = mcp

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = await self._mcp.call_tool(name, arguments)
        return _unwrap_tool_result(result)


class StreamableHTTPMCPClient:
    """Minimal HTTP client for a ``fourex-mcp-http`` server.

    The full ``mcp`` Python client would also work, but the JSON-RPC
    handshake adds several dependencies we don't need — for Phase 6 we
    only need to call tools, and the streamable-http endpoint accepts a
    single JSON-RPC request per call.
    """

    def __init__(self, url: str = "http://localhost:8020/mcp"):
        self._url = url
        self._request_id = 0

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        import httpx

        self._request_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                self._url,
                json=payload,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                },
            )
            resp.raise_for_status()
            body = resp.json()

        if "error" in body:
            return {"error": body["error"].get("message", str(body["error"]))}

        result = body.get("result", {})
        structured = result.get("structuredContent")
        if isinstance(structured, dict):
            return structured

        content = result.get("content") or []
        if content and isinstance(content, list):
            text = content[0].get("text")
            if text:
                try:
                    parsed = json.loads(text)
                    if isinstance(parsed, dict):
                        return parsed
                except json.JSONDecodeError:
                    return {"raw": text}

        return {"error": "Empty tool response"}


def _unwrap_call_tool_result(result: Any) -> dict[str, Any]:
    """Normalise an official-client ``CallToolResult`` into a plain dict.

    The official ``mcp`` client returns a ``CallToolResult`` with a
    ``structuredContent`` dict (when the tool declares structured output)
    and/or a ``content`` list of typed blocks. We prefer the structured
    payload and fall back to JSON-decoding the first text block.
    """
    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict):
        return structured
    for block in getattr(result, "content", None) or []:
        text = getattr(block, "text", None)
        if text:
            try:
                parsed = json.loads(text)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                return {"raw": text}
    if getattr(result, "isError", False):
        return {"error": "tool call returned isError with no parseable content"}
    return {"error": "Unrecognised CallToolResult shape"}


class OfficialStreamableHTTPMCPClient:
    """Stateful streamable-HTTP adapter built on the official ``mcp`` client.

    Unlike :class:`StreamableHTTPMCPClient`, this performs the full MCP
    handshake and carries the session id, so it works against the live
    (stateful) FastMCP deployment at e.g. ``https://mcp.parley.quest/``.

    Lifecycle: open it as an async context manager (or call
    :meth:`connect` / :meth:`aclose`). One long-lived session is held for
    the duration — the agent runtime issues many ``call_tool`` calls
    sequentially over a single game, all on the same session::

        async with OfficialStreamableHTTPMCPClient(url) as client:
            resp = await client.call_tool("create_game", {...})
    """

    def __init__(
        self, url: str = "https://mcp.parley.quest/", *, call_timeout_s: float = 90.0
    ):
        self._url = url
        # Per-call timeout so a stalled tool call can't hang a whole game for
        # hours (a long agent run otherwise wedged until per_game_timeout, and
        # even that didn't cancel the MCP read stream cleanly).
        self._call_timeout_s = call_timeout_s
        self._stack: AsyncExitStack | None = None
        self._session: Any = None

    async def connect(self) -> OfficialStreamableHTTPMCPClient:
        from mcp import ClientSession
        from mcp.client.streamable_http import (  # pyrefly: ignore[import-error]
            streamablehttp_client,
        )

        self._stack = AsyncExitStack()
        read, write, _get_session_id = await self._stack.enter_async_context(
            streamablehttp_client(self._url)
        )
        session = await self._stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        self._session = session
        return self

    async def aclose(self) -> None:
        if self._stack is not None:
            await self._stack.aclose()
            self._stack = None
            self._session = None

    async def __aenter__(self) -> OfficialStreamableHTTPMCPClient:
        return await self.connect()

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if self._session is None:
            raise RuntimeError(
                "OfficialStreamableHTTPMCPClient is not connected — use "
                "`async with` or call connect() first"
            )
        result = await asyncio.wait_for(
            self._session.call_tool(name, arguments), timeout=self._call_timeout_s
        )
        return _unwrap_call_tool_result(result)
