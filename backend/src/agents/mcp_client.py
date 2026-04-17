"""
MCP client adapters used by the Phase 6 agent runtime.

The agent runtime is deliberately transport-agnostic: it only needs an
object with an async ``call_tool(name, arguments) -> dict`` method. Two
adapters ship here:

- ``InProcessMCPClient`` wraps a FastMCP server instance and dispatches
  tool calls directly in-process. This is what tests and self-play
  drivers use — no network hop, no stdio pipe, just a function call.
- ``StreamableHTTPMCPClient`` is a thin wrapper around ``httpx`` for
  talking to a running ``fourex-mcp-http`` server. Optional; the
  in-process adapter is sufficient for self-play and the integration
  tests.

Both adapters return already-decoded dicts so the rest of the agent
code does not have to care whether the tool ran in-process or remotely.
"""

from __future__ import annotations

import json
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
