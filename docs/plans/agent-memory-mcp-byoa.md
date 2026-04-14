# Agent Memory, Real MCP Server & BYOA Interface

## Problem Statement

The 4X game engine has AI agents that suffer from two key limitations. First, agents have no meaningful memory — they only see the last 1–2 turns inlined into the LLM prompt, with no scratchpad for recording observations, intentions, or evolving strategy. There is no persistence of this context, making agents reactive rather than strategic.

Second, the MCP server is not a real MCP server. The "client" imports tools directly in-process — there is no transport layer, no stdio, no HTTP. This means external agents cannot connect to the game. The project aspires to be a BYOA (Bring Your Own Agent) platform where anyone can connect their own AI agent to play, but the current architecture only supports the built-in orchestrator-driven agents.

Additionally, the build system uses a Makefile, which should be modernised to mise for better monorepo task management and tool version pinning.

## Solution

Build three things:

1. **Agent memory system** — A per-player, per-game memory system with two components: a free-form scratchpad (overwritten each turn, hard-capped) and structured turn history (actions submitted + fog-of-war-redacted game state snapshots per turn). Memory is private to each player and persisted to PostgreSQL.

2. **Real MCP server as the primary agent interface** — Replace the fake MCP setup with a proper FastMCP v3 server supporting both stdio and streamable-http transports. This becomes the primary interface for agents to play the game — reading state, submitting actions, querying analysis tools, and managing memory. The existing REST API remains as a parallel interface (used by the frontend).

3. **Mise migration** — Replace the Makefile with `mise.toml` for task management and tool version pinning (Python, Node).

## User Stories

1. As an external agent developer, I want to connect to the game via MCP (streamable-http), so that I can build my own AI agent without depending on the built-in orchestrator.
2. As an external agent developer, I want to authenticate with a short-lived API key per player, so that my agent's identity is verified and other players cannot impersonate me.
3. As an external agent developer, I want to create a new game via an MCP tool, so that I can set up games programmatically.
4. As an external agent developer, I want to join an existing game via an MCP tool, so that I can participate in multiplayer games.
5. As an external agent developer, I want to read my fog-of-war-redacted game state via an MCP tool, so that I can observe the world without cheating.
6. As an external agent developer, I want to submit actions via an MCP tool, so that I can play my turn.
7. As an external agent developer, I want to check whether it is my turn via an MCP tool, so that I can poll or wait for my turn without guessing.
8. As an external agent developer, I want the server to advance the turn automatically once all players have submitted, so that I do not need to coordinate turn progression manually.
9. As an external agent developer, I want a 10-minute timeout per turn, so that the game does not stall indefinitely if a player disconnects.
10. As an agent (built-in or external), I want a free-form scratchpad that I can write to each turn, so that I can record observations, intentions, and evolving strategy.
11. As an agent, I want my scratchpad to be overwritten each turn with a hard character cap, so that token budgets remain predictable and I am forced to distil my notes.
12. As an agent, I want my scratchpad to be private, so that other players cannot read my strategic notes.
13. As an agent, I want to read my scratchpad from a previous turn via an MCP tool, so that I can recall what I was thinking.
14. As an agent, I want to read my turn history (actions I submitted on past turns) via an MCP tool, so that I can reason about what I have done.
15. As an agent, I want to read the fog-of-war-redacted game state snapshot from any past turn via an MCP tool, so that I can compare how the world has changed.
16. As an agent, I want to analyse territory, military position, resource opportunities, and distances via MCP tools, so that I can make informed strategic decisions.
17. As an agent, I want to validate proposed actions before submitting them via an MCP tool, so that I can avoid wasting my turn on invalid moves.
18. As an agent, I want to write to my memory scratchpad via an MCP tool, so that I can persist notes for future turns.
19. As an agent, I want to read my memory scratchpad via an MCP tool, so that I can retrieve my notes from the current or previous turns.
20. As a developer, I want to run the MCP server in stdio mode, so that I can use it with Claude Desktop, Claude Code, or Cursor.
21. As a developer, I want to run the MCP server in streamable-http mode, so that I can connect remote agents over the network.
22. As a developer, I want an MCP Inspector task in mise, so that I can test and debug MCP tools interactively.
23. As a developer, I want `mise.toml` to replace the Makefile, covering all existing tasks (install, run-dev, test, format, lint, db-reset, db-check, quick) plus MCP server tasks.
24. As a developer, I want mise to pin Python and Node versions, so that the development environment is reproducible.
25. As the game engine, I want to store fog-of-war-redacted game state snapshots per player per turn in the database, so that historical state is available without recomputation.
26. As the game engine, I want to store agent scratchpad entries per player per turn in the database, so that memory is durable and observable.
27. As a researcher, I want to query the database to observe how agent memory evolves over a game, so that I can study agent reasoning and strategy formation.
28. As the built-in orchestrator, I want to continue working alongside the new MCP interface, so that existing quick-run workflows are not broken.
29. As an external agent developer, I want clear tool descriptions with parameter documentation, so that I can discover the API without reading source code.
30. As an external agent developer, I want meaningful error messages from MCP tools when I submit invalid actions or authenticate incorrectly, so that I can debug my agent.

## Implementation Decisions

### MCP Server Architecture

- Use FastMCP v3 with the modular tool registration pattern: each tool domain (game lifecycle, game state, actions, analysis, memory) lives in its own module with a `register(mcp)` function.
- Support two transports: stdio (for local dev with Claude Desktop/Code/Cursor) and streamable-http with CORS (for remote agents). Use `mcp.http_app(transport="streamable-http")` with a Starlette wrapper, matching the autoscript-agents pattern.
- Add a `/healthz` endpoint on the HTTP transport for load balancer and readiness probes.
- Tool annotations should include `title`, `readOnlyHint`, `openWorldHint`, and `tags` for discoverability.

### MCP Tool Categories

**Game Lifecycle Tools:**
- `create_game` — Create a new game, returns game ID and player API keys.
- `join_game` — Join an existing game, returns a player API key.
- `get_game_info` — Get game metadata (players, turn, status).

**Game State Tools:**
- `get_game_state` — Returns fog-of-war-redacted state for the authenticated player's current turn.
- `get_turn_snapshot` — Returns fog-of-war-redacted state for a specific past turn.
- `is_my_turn` — Returns whether the game is waiting for this player's actions, plus current turn number and time remaining.

**Action Tools:**
- `submit_actions` — Submit a list of actions for the current turn. Once all players submit (or timeout), the turn resolves.
- `validate_actions` — Validate proposed actions without submitting.

**Analysis Tools (carried over, now real MCP):**
- `analyze_territory` — Territorial control analysis.
- `evaluate_military_position` — Military strength assessment.
- `find_resource_opportunities` — Resource discovery and prioritisation.
- `calculate_distances` — Manhattan distance calculations.

**Memory Tools:**
- `write_scratchpad` — Write free-form text to the agent's scratchpad for the current turn. Overwrites any previous entry for this turn. Hard-capped at 4,000 characters; the cap is documented in the tool description.
- `read_scratchpad` — Read the agent's scratchpad, optionally for a specific past turn. Defaults to the most recent entry.
- `get_turn_history` — Returns a summary of the agent's submitted actions for past turns (turn number, action list).

### Authentication

- When a game is created, the server generates a short-lived API key per player slot. Keys are returned to the game creator.
- When a player joins, they receive their own key.
- Every MCP tool call that is player-scoped requires the API key as a parameter. The server validates the key and derives the player ID from it.
- Keys expire when the game ends or after a configurable inactivity timeout.
- Keys are stored in the database alongside the game, hashed.

### Turn Progression

- The game waits for all players to submit actions (via `submit_actions`).
- Once all players have submitted, `resolve_turn()` runs and the turn advances.
- A 10-minute per-turn timeout is enforced. If a player has not submitted when the timeout fires, their turn is skipped (no actions) and the game advances.
- `is_my_turn` returns the current turn number, whether the game is waiting for this player, and the time remaining before timeout.

### Database Schema (new tables)

**`agent_memory`** — Stores scratchpad entries.
- `id` (PK), `game_id` (FK), `player_id`, `turn_number`, `scratchpad_text` (max 4,000 chars), `created_at`, `updated_at`.
- Unique constraint on `(game_id, player_id, turn_number)`.

**`turn_snapshots`** — Stores fog-of-war-redacted game state per player per turn.
- `id` (PK), `game_id` (FK), `player_id`, `turn_number`, `state_json` (JSONB), `created_at`.
- Unique constraint on `(game_id, player_id, turn_number)`.
- Written automatically when a turn resolves, one row per player.

**`player_api_keys`** — Stores hashed API keys.
- `id` (PK), `game_id` (FK), `player_id`, `key_hash`, `expires_at`, `created_at`.

**`turn_actions`** — Stores submitted actions per player per turn.
- `id` (PK), `game_id` (FK), `player_id`, `turn_number`, `actions_json` (JSONB), `submitted_at`.
- Unique constraint on `(game_id, player_id, turn_number)`.

### Mise Migration

- Replace `Makefile` with `mise.toml` at the project root.
- Pin `python = "3.12"` and `node = "lts"` in `[tools]`.
- Migrate all Makefile targets to `[tasks]`: `install`, `run-dev`, `test`, `backend-test`, `format`, `lint`, `db-reset`, `db-check`, `quick`.
- Add new tasks: `serve` (MCP stdio), `serve-http` (MCP streamable-http), `inspect` (MCP Inspector against stdio), `inspect-http` (MCP Inspector against HTTP).
- Remove the Makefile once mise.toml is verified.

### Built-in Agent Adaptation

- The existing `FourXAgent` and orchestrator continue to work. They can optionally be refactored to use the MCP tools as a client, but this is not required for this PRD — they can continue calling the game engine directly.
- The in-memory `turn_history` on `FourXAgent` should be backed by the new database tables so that memory is durable and observable.

## Out of Scope

- Frontend changes — the Next.js UI is unaffected by this PRD.
- Cross-game agent memory (learning across games) — memory is scoped to a single game.
- Agent personality or LLM provider changes.
- Deployment configuration (EKS manifests, Docker images).
- Rate limiting or abuse prevention on the MCP interface.
- Spectator mode or replays (though turn snapshots enable this in future).
- WebSocket real-time updates for MCP-connected agents (polling via `is_my_turn` is sufficient for now).

## Further Notes

- The 4,000-character scratchpad cap is a starting point. It should be easy to adjust via configuration. The cap exists to keep LLM token budgets predictable when the scratchpad is included in prompts.
- Turn snapshots will grow the database significantly for long games with many players. Consider a retention policy in future, but for this PRD, store everything — observability for research is the priority.
- The streamable-http transport enables future deployment behind a reverse proxy or load balancer, which is useful if the project moves to hosted multiplayer.
- The MCP Inspector integration via mise is valuable for onboarding external agent developers — they can explore available tools interactively before writing code.
