# MCP Integration

This project currently uses a local FastMCP-style analysis layer for agent planning.

## Current State

- The agent integration lives in `agents/src/fastmcp_client.py` and `agents/src/fastmcp_server.py`.
- The client class is `FastMCPGameClient`.
- The agent wires this client automatically in `agents/src/agent.py`.
- The current client does not connect over a real MCP transport yet. It imports the FastMCP server module directly and calls the tool functions in-process.
- The real transport-backed MCP server is planned separately. Do not treat this document as a description of the future BYOA server in the PRD.

## Available Analysis Tools

The current FastMCP layer exposes these analysis helpers:

- `get_game_state`
- `analyze_territory`
- `evaluate_military_position`
- `find_resource_opportunities`
- `validate_actions`
- `calculate_distances`

These are used to enrich the agent prompt before turn planning.

## How Agents Use It

`FourXAgent` creates a `FastMCPGameClient` automatically. Before planning a turn, it checks whether the client is available and, if so, runs `comprehensive_analysis(game_id, game_state)`.

That analysis may include:

- summarized game state
- military analysis
- resource opportunities
- territory analysis
- strategic distance calculations

If FastMCP initialization fails, the agent continues without MCP analysis.

## Example

```python
from src.fastmcp_client import FastMCPGameClient

mcp_client = FastMCPGameClient(
    player_id="player_alice",
    game_backend_url="http://localhost:8010/api/v1",
)

if mcp_client.is_available():
    analysis = await mcp_client.comprehensive_analysis("test_game", game_state)
```

## Configuration

There is no separate MCP transport configuration in the current implementation.

The relevant setting is the backend URL passed to the agent or client, which defaults to:

```text
http://localhost:8010/api/v1
```

## Notes

- `use_persistent_client=True` controls use of the resilient game backend client, not whether MCP exists as a network service.
- The FastMCP analysis layer is optional prompt enrichment.
- If you are looking for the planned external MCP server, use the PRD/plan documents rather than this file.
