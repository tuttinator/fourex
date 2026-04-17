# Plan: Autonomous Agents & MCP Overhaul

> Source PRD: `plans/autonomous-agents-mcp-overhaul.md`

## Architectural decisions

Durable decisions that apply across all phases:

- **Single MCP server**: `backend/src/mcp_server/` is the only MCP server. The legacy `agents/src/fastmcp_server.py` and `agents/src/fastmcp_client.py` are deleted. All clients (AI agents, Goose, Claude Code) connect here.
- **Transport modes**: stdio (for local dev, Claude Code, Goose) and streamable-http on `:8020` (for remote clients, MCP Inspector). Both via `pyproject.toml` entry points: `fourex-mcp` and `fourex-mcp-http`.
- **Tool organisation**: Each tool domain is a module under `backend/src/mcp_server/tools/` with a `register(mcp: FastMCP)` function. Domains: `lifecycle`, `gameplay`, `analysis`, `memory`, `history`, `rendering`.
- **FastMCP v3 conventions**: All tools use annotations (`readOnlyHint`, `destructiveHint`, `openWorldHint`), `tags` for categorisation, and return `{"error": "message"}` on failure.
- **Authentication**: Bearer token via hashed API keys in `player_api_keys` table. MCP tools receive `player_id` via the `authenticate()` helper. Same auth for agents and humans.
- **Game state**: JSON blob in `games.state` column. Fog-of-war applied by `redact_state()` before any client sees data. All MCP tools return redacted state.
- **Memory schema**: `agent_memory` table stores structured JSON (strategic goals, opponent models, turn notes) in the existing `scratchpad_text` column. No new tables — just richer content.
- **Agent profiles**: `AgentProfile` dataclass/Pydantic model replaces prompt-only personalities. Defines `tool_priorities`, `memory_priorities`, `action_biases`, `thresholds`, and a short `system_prompt`. Stored in code, not database.
- **Map rendering**: SVG generated server-side with `xml.etree.ElementTree`. PNG via `cairosvg`. ASCII via string formatting. All rendering tools accept `game_id` + `player_id` and apply fog of war.
- **Claude Code `/play-4x` skill**: Thin MCP client wrapper. Present from Phase 1 as the primary test harness and progressively enhanced each phase. Lives in `.claude/skills/play-4x/`.
- **Testing**: pytest with async fixtures. MCP tool tests use `mcp.call_tool()` against in-memory state. Self-play tests use deterministic seeds. `mise run self-play` for the full autonomous test suite.

---

## Phase 1: MCP Server Consolidation + Claude Code Smoke Skill

**User stories**: 14, 15, 16

### What to build

Delete the legacy agent-side MCP server (`agents/src/fastmcp_server.py`, `agents/src/fastmcp_client.py`, `agents/run_mcp_server.py`, `agents/run_fastmcp_server.py`). Remove the `mise run mcp-server` task and all imports of the legacy server from `agents/src/agent.py`.

Refactor the backend MCP server to follow autoscript-agents best practices: add FastMCP v3 annotations (`readOnlyHint`, `destructiveHint`, `tags`) to all existing tools. Add `pyproject.toml` entry points (`fourex-mcp` for stdio, `fourex-mcp-http` for HTTP). Update `mise run serve` and `mise run serve-http` to use the entry points. Ensure the HTTP mode has CORS middleware and a `/healthz` endpoint.

Build a minimal Claude Code `/play-4x` skill that connects to the MCP server (stdio) and can: create a game, join as a player, query game state, and display the result. This skill is the test harness for every subsequent phase — if it can't talk to the server, the phase isn't done.

### Acceptance criteria

- [ ] `agents/src/fastmcp_server.py`, `agents/src/fastmcp_client.py`, `agents/run_mcp_server.py`, and `agents/run_fastmcp_server.py` are deleted
- [ ] `mise run mcp-server` task is removed from `mise.toml`
- [ ] All remaining agent code compiles without importing the deleted files (imports may be stubbed pending Phase 6 rewrite)
- [ ] All existing backend MCP tools have FastMCP v3 `annotations` and `tags`
- [ ] `pyproject.toml` defines `fourex-mcp` and `fourex-mcp-http` entry points
- [ ] `mise run serve` and `mise run serve-http` launch the server via entry points
- [ ] `npx @modelcontextprotocol/inspector` can connect and list all tools
- [ ] HTTP mode serves `/healthz` returning 200
- [ ] Claude Code `/play-4x` skill exists and can create a game, join it, and display game state via MCP tools
- [ ] All existing backend MCP tests pass
- [ ] CLAUDE.md and README.md updated to reflect the single-server setup

---

## Phase 2: Implement BUILD_IMPROVEMENT & BUILD_BUILDING

**User stories**: 11, 25

### What to build

Implement `execute_build_improvement()` and `execute_build_building()` in `rules.py`. For improvements: validate worker ownership, check the worker is on the target tile, verify terrain supports the improvement type (e.g. FARM on plains/forest, MINE on mountain, CRYSTAL_EXTRACTOR on crystal tiles), deduct resources, place improvement on the tile, consume the worker. For buildings: validate city ownership, check the city doesn't already have that building, deduct resources per `BUILDING_STATS`, add building to the city.

Add `IMPROVEMENT_STATS` to `models.py` (resource costs and effects per improvement type) if not already present.

Update the `validate_actions` MCP tool to support these two action types.

Write comprehensive unit tests: happy path for each, plus edge cases — building on water, building without resources, duplicate buildings, improvements on wrong terrain, improvements without a worker, building in an enemy city.

Extend the `/play-4x` skill to submit build actions and verify the results.

### Acceptance criteria

- [ ] `execute_build_improvement()` implemented: validates ownership, terrain, resources; places improvement; consumes worker
- [ ] `execute_build_building()` implemented: validates ownership, uniqueness, resources; adds building to city
- [ ] `IMPROVEMENT_STATS` defined in `models.py` with costs and effects for FARM, MINE, CRYSTAL_EXTRACTOR
- [ ] `collect_resources()` accounts for improvement effects (FARM boosts food, MINE produces ore, CRYSTAL_EXTRACTOR produces crystal)
- [ ] `validate_actions` MCP tool accepts BUILD_IMPROVEMENT and BUILD_BUILDING
- [ ] Unit tests cover: valid build improvement, valid build building, wrong terrain, insufficient resources, duplicate building, enemy city, no worker on tile, worker on water
- [ ] `/play-4x` skill can submit BUILD_IMPROVEMENT and BUILD_BUILDING actions and display results
- [ ] All existing tests still pass (no regressions in movement, attack, city founding, unit training)

---

## Phase 3: ASCII & SVG Map Rendering

**User stories**: 7, 10, 17, 18

### What to build

Add a `rendering` tool domain to the MCP server with three tools:

`render_map_ascii`: returns a text grid of the visible map (fog of war applied). Terrain as characters (`.` plains, `T` forest, `^` mountain, `~` water), units and cities overlaid with player-coloured markers, unexplored tiles as `?`. Includes a legend and coordinate axes.

`render_map_svg`: returns an SVG string. Tiles as coloured rectangles, units/cities as simple shapes or text labels, fog-of-war areas greyed/hidden. Colour palette references the frontend's existing `TERRAIN_COLORS` and `PLAYER_COLORS`. Viewbox scales to map dimensions.

`render_map_image`: accepts a format parameter (PNG default), renders the SVG to a raster image via `cairosvg`, returns base64-encoded data. Add `cairosvg` to project dependencies.

All three tools accept `game_id` and `player_id`, authenticate, and apply fog of war via `redact_state()`.

Update the `/play-4x` skill to display the ASCII map after every state query. The skill calls `render_map_ascii` — it does not generate the ASCII itself.

### Acceptance criteria

- [ ] `render_map_ascii` MCP tool returns a text representation with terrain, units, cities, fog of war, legend, and coordinates
- [ ] `render_map_svg` MCP tool returns valid SVG with terrain colours, unit/city markers, and fog-of-war masking
- [ ] `render_map_image` MCP tool returns a base64-encoded PNG generated from the SVG
- [ ] `cairosvg` added to project dependencies
- [ ] `rendering` module follows the `register(mcp)` pattern with appropriate annotations and tags
- [ ] Unit tests verify ASCII output contains expected characters for known game states
- [ ] Unit tests verify SVG output is valid XML with expected elements
- [ ] `/play-4x` skill displays ASCII map inline after state queries
- [ ] Fog of war is correctly applied — unexplored tiles show `?` in ASCII, are hidden/greyed in SVG/PNG
- [ ] All existing tests still pass

---

## Phase 4: Structured Memory System

**User stories**: 3, 4, 19, 23

### What to build

Extend the MCP memory tools beyond the flat scratchpad. Add structured memory tools that store JSON in the existing `agent_memory` table (reusing the `scratchpad_text` column with a larger limit, or adding a `structured_data` JSONB column if cleaner):

`write_strategic_goals`: accepts a list of goals with priority and status. Persists per player per turn.

`read_strategic_goals`: returns the most recent goals for the player in this game.

`write_opponent_model`: accepts per-opponent observations (stance, unit count, threat level, last known positions). Persists per player per turn.

`read_opponent_models`: returns the most recent opponent models for the player.

`write_turn_notes`: freeform observations for the current turn (replaces raw scratchpad for new agents, though `write_scratchpad` remains for backwards compatibility).

`read_turn_notes`: returns notes from recent turns (configurable lookback).

All memory is scoped to a single game. New game = empty memory. The memory tools should handle the common pattern of "read previous turn's memory, update it, write to current turn" without requiring the caller to manage turn numbers explicitly.

Update the `/play-4x` skill to read and write memory — proving the tools work for any MCP client.

### Acceptance criteria

- [ ] `write_strategic_goals` and `read_strategic_goals` MCP tools implemented with JSON persistence
- [ ] `write_opponent_model` and `read_opponent_models` MCP tools implemented
- [ ] `write_turn_notes` and `read_turn_notes` MCP tools implemented with configurable lookback
- [ ] Memory is scoped per game — querying memory for a new game returns empty results
- [ ] Turn number management is handled by the server (caller doesn't need to track it)
- [ ] Existing `write_scratchpad` / `read_scratchpad` tools still work (backwards compatible)
- [ ] Unit tests verify read/write round-trips for each memory type
- [ ] Unit tests verify game-scoped isolation (memory from game A not visible in game B)
- [ ] `/play-4x` skill can write strategic goals, read them back, write opponent notes, and read turn history
- [ ] All existing tests still pass

---

## Phase 5: Structured Agent Profiles (Replace Personalities)

**User stories**: 5, 21

### What to build

Define an `AgentProfile` model (Pydantic or dataclass) that replaces the prompt-only personality system. An `AgentProfile` contains:

- `name` and `description`: identity.
- `tool_priorities`: ordered list of analysis tools to run each turn, with weight/importance. E.g. an aggressive profile always runs `evaluate_military_position` first and weights it heavily.
- `memory_priorities`: what to track — aggressive tracks enemy positions, economic tracks resource rates, explorer tracks unexplored territory.
- `action_biases`: weights that influence action selection. E.g. explorer biases toward MOVE, economic toward BUILD_IMPROVEMENT, aggressive toward ATTACK.
- `thresholds`: numeric triggers for strategic decisions. E.g. "attack when military ratio > 1.5", "expand when city count < 3", "build walls when threat level > 0.7".
- `system_prompt`: a short (paragraph-length) prompt that sets tone. The mechanical behaviour comes from the structured fields.

Create reference profiles that map to the most useful existing personalities: aggressive, economic, explorer, balanced. These are the profiles used in testing.

Build a simple profile-driven agent runner that demonstrates: given a profile, it calls the prioritised MCP analysis tools, writes to memory based on memory priorities, and generates an action plan influenced by action biases and thresholds. This doesn't need to be the full agent rewrite (that's Phase 6) — just prove the profile system works end-to-end.

Update the `/play-4x` skill to display an agent's profile and observe how it influences tool calls during a test turn.

### Acceptance criteria

- [ ] `AgentProfile` model defined with all fields: `tool_priorities`, `memory_priorities`, `action_biases`, `thresholds`, `system_prompt`
- [ ] Reference profiles created: aggressive, economic, explorer, balanced
- [ ] Profile-driven runner demonstrates: tool call order matches `tool_priorities`, memory writes match `memory_priorities`, action selection reflects `action_biases`
- [ ] Old `personalities.py` prompt-only system is deprecated (can be deleted in Phase 6)
- [ ] Unit tests verify that different profiles produce different tool call sequences and memory patterns
- [ ] `/play-4x` skill can list available profiles and observe a profile-driven agent playing a test turn
- [ ] All existing tests still pass

---

## Phase 6: Full Agent Rewrite (MCP-Only)

**User stories**: 1, 2, 6, 8, 22, 24

### What to build

Rewrite the agent runtime to operate exclusively through MCP tools. No direct REST calls to the backend. The agent is an MCP client that connects to the backend MCP server (stdio or HTTP).

Agent turn loop:
1. **Observe**: call `get_game_state` and `is_my_turn`
2. **Remember**: call `read_strategic_goals`, `read_opponent_models`, `read_turn_notes`
3. **Analyse**: call analysis tools in the order specified by the agent's `AgentProfile.tool_priorities`
4. **Plan**: send state + memory + analysis to the LLM with the profile's `system_prompt`. LLM returns structured actions (Pydantic model / structured output).
5. **Validate**: call `validate_actions` to check the plan before committing
6. **Submit**: call `submit_actions`
7. **Memorise**: call `write_strategic_goals`, `write_opponent_model`, `write_turn_notes` based on `memory_priorities`

Delete the old `agents/src/agent.py` approach (direct REST + legacy MCP client) and the `personalities.py` prompt system. The orchestrator (`orchestrator.py`) is updated to manage MCP-connected agents instead of REST-connected ones.

The same MCP interface now works for AI agents, a human via Goose, and the Claude Code `/play-4x` skill. A human follows the same loop manually: observe, analyse, plan, validate, submit.

Update the `/play-4x` skill to play alongside or spectate agents running through this loop.

### Acceptance criteria

- [ ] Agent runtime connects to backend MCP server as a client (stdio or HTTP)
- [ ] Agent turn loop follows the 7-step sequence: observe, remember, analyse, plan, validate, submit, memorise
- [ ] Agent uses `AgentProfile` from Phase 5 to drive tool priorities, memory, and action biases
- [ ] No direct REST calls remain in the agent code path
- [ ] Old `personalities.py` is deleted
- [ ] Orchestrator manages MCP-connected agents
- [ ] A human using Goose can connect to the same MCP server and play using the same tools
- [ ] `/play-4x` skill can spectate an agent game (watch turns resolve, see state updates)
- [ ] `/play-4x` skill can play in a game alongside AI agents
- [ ] Integration test: 2 agents play a 10-turn game entirely through MCP with no errors
- [ ] All existing tests still pass (or are updated to reflect the new architecture)

---

## Phase 7: Self-Play Testing & Edge-Case Hardening

**User stories**: 12, 13, 20, 25

### What to build

Build a comprehensive testing layer that catches gameplay bugs automatically.

**Unit test expansion**: add tests for every edge case identified during development — water-tile movement, attacking allies, founding cities on mountains/water, training units without resources, building improvements on wrong terrain, negative resource states, units moving beyond range, combat against cities with walls, resource collection with improvements, fog-of-war boundary conditions.

**Integration tests**: run a full multi-turn game through the MCP server with scripted agents (deterministic action sequences). Verify turn resolution, resource accumulation, fog-of-war correctness, and game termination (victory or turn limit).

**Self-play test mode**: a pytest suite and `mise run self-play` task that:
1. Creates a game with deterministic seed.
2. Spawns N reference agents (from Phase 5 profiles) connected via MCP.
3. Plays the game to completion (or configurable turn limit).
4. Asserts: no unhandled exceptions, no invalid actions accepted, game state remains consistent (no negative resources, no units on impassable tiles, no orphaned city/unit references), game terminates correctly.
5. On failure: logs the seed + full action history for deterministic reproduction.

Reference agents start with a clean slate each game (no cross-game memory).

Update the `/play-4x` skill with a "self-play" mode that runs a test game and reports results inline.

### Acceptance criteria

- [ ] Edge-case unit tests cover: water movement, ally attacks, mountain/water city founding, insufficient resources for all action types, duplicate buildings, out-of-range movement, walls combat bonus, improvement terrain validation
- [ ] Integration test runs a full 20-turn game through MCP with scripted actions and verifies final state
- [ ] Self-play test runs N agents through a complete game with no exceptions
- [ ] Self-play validates state consistency after every turn (no negative resources, no units on impassable tiles, no orphaned references)
- [ ] Self-play logs seed + action history on failure for reproduction
- [ ] `mise run self-play` task exists with configurable turn count and player count
- [ ] Reference agents use clean-slate memory (no cross-game persistence)
- [ ] `/play-4x` skill can trigger and observe a self-play test game
- [ ] Deterministic seeds produce identical game outcomes across runs
- [ ] All tests pass in CI (no database required for unit tests, optional for integration)

---

## Phase 8: Claude Code `/play-4x` Skill (Full)

**User stories**: 9, 10, 24

### What to build

Polish the `/play-4x` skill from a test harness into a full conversational game interface. The skill should support natural-language commands mapped to MCP tool calls:

- "show map" / "map" -> `render_map_ascii`
- "status" / "state" -> `get_game_state` (formatted summary)
- "move scout to 5,6" -> `submit_actions` with MOVE
- "build farm" -> `submit_actions` with BUILD_IMPROVEMENT
- "what can I build?" -> `get_game_state` + resource/city analysis
- "attack soldier at 3,4" -> `submit_actions` with ATTACK
- "end turn" / "pass" -> `submit_actions` with PASS
- "memory" -> `read_strategic_goals` + `read_opponent_models`
- "spectate" -> read-only mode showing each turn as it resolves
- "self-play" -> trigger a self-play game and stream results

The skill should display the ASCII map after each action, show resource summaries, highlight threats, and provide contextual suggestions (e.g. "You have a worker idle at 3,2 — consider building a farm").

Add skill documentation and usage instructions.

### Acceptance criteria

- [ ] `/play-4x` skill supports all listed natural-language commands
- [ ] ASCII map displayed after every action or state change
- [ ] Resource summary shown with state queries
- [ ] Spectate mode streams turn-by-turn updates for an ongoing game
- [ ] Self-play mode runs a test game and reports results
- [ ] Contextual suggestions provided based on game state (idle units, available builds, threats)
- [ ] Skill handles errors gracefully (invalid moves, server disconnection, game not found)
- [ ] Skill documentation and usage instructions included
- [ ] Works with both stdio and HTTP MCP server connections
- [ ] End-to-end: a user can create a game, play multiple turns against AI agents, and reach a game conclusion using only the `/play-4x` skill
