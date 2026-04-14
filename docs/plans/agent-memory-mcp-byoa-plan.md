# Plan: Agent Memory, Real MCP Server & BYOA Interface

> Source PRD: `docs/plans/agent-memory-mcp-byoa.md`

## Architectural decisions

Durable decisions that apply across all phases:

- **MCP framework**: FastMCP v3 with `mcp.http_app(transport="streamable-http")` for HTTP mode and `mcp.run()` for stdio mode. Starlette wrapper with CORS middleware and `/healthz` health check.
- **MCP tool registration**: Each tool domain lives in its own module with a `register(mcp: FastMCP) -> None` function. Tool annotations include `title`, `readOnlyHint`, `openWorldHint`, and `tags`.
- **Database**: Same PostgreSQL instance as the game engine. Four new tables:
  - `agent_memory` — `(game_id, player_id, turn_number)` unique, `scratchpad_text` varchar(4000)
  - `turn_snapshots` — `(game_id, player_id, turn_number)` unique, `state_json` JSONB
  - `turn_actions` — `(game_id, player_id, turn_number)` unique, `actions_json` JSONB
  - `player_api_keys` — `(game_id, player_id)`, `key_hash`, `expires_at`
- **Authentication**: Short-lived API key per player per game. Keys are generated on game create/join, stored as SHA-256 hashes, passed as a parameter on every player-scoped MCP tool call. The server derives `(game_id, player_id)` from the key.
- **Turn progression**: Server advances the turn once all players have submitted via `submit_actions`. 10-minute per-turn timeout skips non-submitting players. `is_my_turn` tool for polling.
- **Fog-of-war**: All player-facing state (MCP tools, snapshots, memory) is redacted per-player using the existing `redact_state()` function. No player can read another player's memory or see beyond their sight range.
- **Scratchpad cap**: 4,000 characters, enforced on write, documented in tool description.
- **Task runner**: `mise.toml` at project root, replacing the Makefile. Pins Python 3.12 and Node LTS.
- **REST API**: Remains as a parallel interface. Frontend continues to use it. MCP is the primary agent interface.

---

## Phase 1: Mise migration

**User stories**: 23, 24

### What to build

Replace the root `Makefile` (and `agents/Makefile`) with a single `mise.toml` at the project root. All existing tasks carry over: `install`, `run-dev`, `backend-test`, `test`, `format`, `lint`, `db-reset`, `db-check`, `quick`. Pin Python 3.12 and Node LTS in `[tools]`. Add placeholder tasks for `serve`, `serve-http`, `inspect`, and `inspect-http` that will be implemented in Phase 4.

### Acceptance criteria

- [ ] `mise.toml` exists at project root with `[tools]` pinning Python 3.12 and Node LTS
- [ ] All tasks from the root Makefile are available via `mise run <task>`
- [ ] Agent-specific tasks (quick, showcase, etc.) are available via mise
- [ ] `mise run install` installs all dependencies (uv sync)
- [ ] `mise run run-dev` starts the FastAPI backend on :8000
- [ ] `mise run format` and `mise run lint` work as before
- [ ] `mise run backend-test` and `mise run test` run their respective test suites
- [ ] Root Makefile and agents/Makefile are removed
- [ ] Placeholder tasks for `serve`, `serve-http`, `inspect`, `inspect-http` exist (can print "not yet implemented")

---

## Phase 2: Database schema for memory, snapshots, keys, and actions

**User stories**: 25, 26

### What to build

Add four new SQLAlchemy models (`AgentMemory`, `TurnSnapshot`, `TurnAction`, `PlayerApiKey`) and create an Alembic migration. Add repository methods for CRUD operations on each table. This phase is persistence-only — no API or MCP exposure yet. Verify with integration tests against a real database.

### Acceptance criteria

- [ ] Four new tables created via Alembic migration
- [ ] `AgentMemory` model with unique constraint on `(game_id, player_id, turn_number)` and `scratchpad_text` capped at 4,000 chars
- [ ] `TurnSnapshot` model with unique constraint on `(game_id, player_id, turn_number)` and `state_json` JSONB column
- [ ] `TurnAction` model with unique constraint on `(game_id, player_id, turn_number)` and `actions_json` JSONB column
- [ ] `PlayerApiKey` model with `key_hash`, `expires_at`, foreign key to game
- [ ] Repository methods: create/read/upsert for memory, snapshots, actions; create/validate/expire for API keys
- [ ] Tests pass against a real PostgreSQL instance (docker-compose)
- [ ] Migration is reversible (downgrade works)

---

## Phase 3: Player API key authentication

**User stories**: 2, 30

### What to build

A shared authentication layer that generates short-lived API keys, hashes and stores them, and validates incoming keys to resolve a `(game_id, player_id)` tuple. This is transport-agnostic — it will be used by both MCP tools and (optionally) REST endpoints. Key generation returns the plaintext key to the caller once; only the hash is stored. Keys expire when the game ends or after a configurable inactivity timeout. Invalid or expired keys return clear error messages.

### Acceptance criteria

- [ ] Key generation produces a cryptographically random token, stores SHA-256 hash in `player_api_keys`
- [ ] Validation function accepts a plaintext key, returns `(game_id, player_id)` or raises an auth error
- [ ] Expired keys are rejected with a descriptive error message
- [ ] Keys are expired when a game ends
- [ ] Unit tests cover: valid key, expired key, invalid key, key for ended game
- [ ] Auth layer is importable as a dependency by both REST and MCP code paths

---

## Phase 4: MCP server skeleton with game lifecycle tools

**User stories**: 1, 3, 4, 20, 21, 22, 29

### What to build

A new FastMCP v3 server with two transport modes: stdio and streamable-http. The server uses the modular `register(mcp)` pattern — one module per tool category. First tool module: game lifecycle (`create_game`, `join_game`, `get_game_info`). `create_game` returns game ID and API keys for all player slots. `join_game` assigns a player slot and returns an API key. `get_game_info` returns game metadata. Wire up the mise placeholder tasks (`serve`, `serve-http`, `inspect`, `inspect-http`) to actually start the server and inspector.

### Acceptance criteria

- [ ] MCP server starts in stdio mode via `mise run serve`
- [ ] MCP server starts in streamable-http mode via `mise run serve-http` with CORS and `/healthz`
- [ ] `mise run inspect` launches MCP Inspector against stdio server
- [ ] `mise run inspect-http` launches MCP Inspector against HTTP server
- [ ] `create_game` tool creates a game and returns game ID + player API keys
- [ ] `join_game` tool assigns a player slot and returns an API key
- [ ] `get_game_info` tool returns game metadata (players, turn, status)
- [ ] All tools have descriptive docstrings, annotations (`title`, `readOnlyHint`, `tags`), and parameter documentation
- [ ] Tool modules follow `register(mcp)` pattern in separate files
- [ ] Demoable: create and join a game via MCP Inspector

---

## Phase 5: Game state and turn flow via MCP

**User stories**: 5, 6, 7, 8, 9, 17

### What to build

The core gameplay tools: `get_game_state` (fog-of-war-redacted for the authenticated player), `submit_actions` (accepts a list of actions, records them in `turn_actions`), `validate_actions` (dry-run validation without submitting), and `is_my_turn` (returns turn number, whether the server is waiting for this player, and time remaining). When all players have submitted, the server calls `resolve_turn()` and advances the game. A 10-minute per-turn timeout skips players who haven't submitted. Turn resolution also stores fog-of-war-redacted snapshots in `turn_snapshots` for each player.

### Acceptance criteria

- [ ] `get_game_state` returns the fog-of-war-redacted state for the authenticated player
- [ ] `submit_actions` accepts and validates a list of actions, stores them in `turn_actions`
- [ ] Turn auto-advances when all players have submitted
- [ ] 10-minute timeout skips non-submitting players and advances the turn
- [ ] `is_my_turn` returns current turn number, waiting status, and seconds remaining
- [ ] `validate_actions` validates without submitting and returns per-action results
- [ ] Fog-of-war-redacted snapshots are saved to `turn_snapshots` on turn resolution (one per player)
- [ ] Submitted actions are saved to `turn_actions`
- [ ] Invalid API key or wrong-turn submissions return clear errors
- [ ] Demoable: two players play a complete turn via MCP tools

---

## Phase 6: Agent memory tools

**User stories**: 10, 11, 12, 13, 18, 19

### What to build

Two MCP tools: `write_scratchpad` and `read_scratchpad`. `write_scratchpad` upserts free-form text into `agent_memory` for the current turn, enforcing the 4,000-character cap. The cap is documented in the tool description. `read_scratchpad` returns the scratchpad for the current turn by default, or a specific past turn if requested. Memory is private — a player can only access their own scratchpad.

### Acceptance criteria

- [ ] `write_scratchpad` stores text in `agent_memory` for the authenticated player's current turn
- [ ] Writing more than 4,000 characters returns a clear error
- [ ] Writing to the same turn overwrites the previous entry (upsert)
- [ ] `read_scratchpad` returns the current turn's scratchpad by default
- [ ] `read_scratchpad` accepts an optional `turn_number` parameter to read past entries
- [ ] A player cannot read another player's scratchpad (returns error or empty)
- [ ] Tool descriptions document the 4,000-character cap
- [ ] Demoable: write a scratchpad entry, advance a turn, read it back from the previous turn

---

## Phase 7: Turn history and state snapshots via MCP

**User stories**: 14, 15, 25, 27

### What to build

Two MCP tools: `get_turn_history` and `get_turn_snapshot`. `get_turn_history` returns a list of past turns with the actions the authenticated player submitted on each. `get_turn_snapshot` returns the fog-of-war-redacted game state for a specific past turn (from the `turn_snapshots` table populated in Phase 5). Both are scoped to the authenticated player — no access to other players' actions or unredacted state.

### Acceptance criteria

- [ ] `get_turn_history` returns a list of `{turn_number, actions}` for all past turns
- [ ] `get_turn_history` only returns the authenticated player's own actions
- [ ] `get_turn_snapshot` returns the fog-of-war-redacted state for a given turn number
- [ ] Requesting a snapshot for a turn that hasn't happened returns a clear error
- [ ] Requesting another player's snapshot is not possible (scoped by API key)
- [ ] Demoable: play several turns, then query history and past snapshots via MCP Inspector

---

## Phase 8: Analysis tools (port to real MCP)

**User stories**: 16

### What to build

Port the four existing analysis tools from the fake MCP server to the new FastMCP v3 server: `analyze_territory`, `evaluate_military_position`, `find_resource_opportunities`, `calculate_distances`. Each becomes a registered MCP tool in its own module (or grouped as an analysis module). They accept the player's API key, fetch the fog-of-war-redacted state internally, and return the same analysis output as before. The old `fastmcp_server.py` and `fastmcp_client.py` can be removed or deprecated.

### Acceptance criteria

- [ ] `analyze_territory` tool registered and functional via MCP
- [ ] `evaluate_military_position` tool registered and functional via MCP
- [ ] `find_resource_opportunities` tool registered and functional via MCP
- [ ] `calculate_distances` tool registered and functional via MCP
- [ ] All analysis tools use fog-of-war-redacted state (no cheating)
- [ ] All tools have proper annotations, tags, and documentation
- [ ] Old `fastmcp_server.py` and `fastmcp_client.py` are removed or clearly deprecated
- [ ] Demoable: run analysis tools against a live game via MCP Inspector

---

## Phase 9: Built-in agent adaptation

**User stories**: 28

### What to build

Wire the existing `FourXAgent` and orchestrator to persist agent memory to the new database tables. When a built-in agent plays a turn, its scratchpad and actions are written to `agent_memory` and `turn_actions`. The `turn_history` in-memory list is backed by the database so it survives restarts. The orchestrator's `quick` workflow continues to work end-to-end. The built-in agents do not need to connect via MCP — they can continue calling the game engine directly, but their memory is now observable in the database.

### Acceptance criteria

- [ ] `mise run quick` runs a full game end-to-end without errors
- [ ] Built-in agent scratchpad entries are persisted to `agent_memory` after each turn
- [ ] Built-in agent actions are persisted to `turn_actions` after each turn
- [ ] Fog-of-war-redacted snapshots are stored for built-in agent games
- [ ] Agent memory is queryable in the database after a game completes
- [ ] No regressions in existing orchestrator behaviour (turn flow, logging, game summary)
