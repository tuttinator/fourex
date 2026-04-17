# PRD: Autonomous Agents & MCP Overhaul

## Problem Statement

The 4X game has the foundations of an AI agent system but it's fragmented and incomplete. There are two MCP servers (one legacy, one production), two unimplemented game actions, agents that bypass the MCP server for action submission, a shallow memory system (4KB scratchpad + 2 turns in-context), and no way for a human to play using the same interface as AI agents. The personality system is just prompt injection with no structured influence on behaviour. There's also no testing strategy that exercises actual gameplay end-to-end, meaning logic bugs (e.g. units walking on water) go undetected until someone manually runs a game.

The goal is a unified system where AI agents and human players (via Block's Goose or any MCP client) share a single MCP server, agents play autonomously with structured decision-making and persistent in-game memory, and the whole thing is testable — including a self-play mode that catches gameplay bugs automatically.

## Solution

Consolidate onto a single MCP server (the backend one) following FastMCP v3 best practices from the autoscript-agents reference project. Delete the legacy agent-side server. Implement the missing game actions. Rewrite agents to operate entirely through MCP tools — the same tools a human would use via Goose. Replace the personality system with structured behavioural profiles that influence tool usage patterns and memory priorities rather than just system prompts. Add server-side map rendering (SVG with PNG export) as an MCP tool. Build a Claude Code skill as a thin wrapper around the MCP client. Implement comprehensive testing: unit tests for every game action, integration tests for full games, and a self-play mode that validates gameplay correctness.

## User Stories

1. As an AI agent, I want to observe game state through MCP tools, so that I use the same interface as every other client.
2. As an AI agent, I want to submit actions through MCP tools, so that I don't need a separate REST client.
3. As an AI agent, I want to persist strategic goals across turns within a game, so that I can execute multi-turn plans coherently.
4. As an AI agent, I want to track opponent behaviour across turns, so that I can adapt my strategy to what other players are doing.
5. As an AI agent, I want my personality to influence which tools I prioritise and what I write to memory, so that different agents play in genuinely different ways — not just differently-worded prompts over the same logic.
6. As a human player using Goose, I want to connect to the same MCP server as AI agents, so that I can use tools to analyse the map, validate moves, and submit actions.
7. As a human player using Goose, I want an ASCII or visual representation of the game map (with fog of war), so that I can understand the board state without a browser.
8. As a human player, I want the MCP server to tell me when it's my turn and what actions are available, so that I don't have to poll or guess.
9. As a Claude Code user, I want a `/play-4x` skill that connects to the MCP server and lets me play or spectate a game from the terminal.
10. As a Claude Code user, I want to see an ASCII map of the game state rendered in my terminal after each turn.
11. As a developer, I want unit tests for every game action (including BUILD_IMPROVEMENT and BUILD_BUILDING), so that I can refactor rules.py with confidence.
12. As a developer, I want integration tests that run a full multi-agent game headlessly, so that I catch turn-resolution bugs.
13. As a developer, I want a self-play test mode where agents play a complete game and the test asserts no errors occurred, so that logic bugs like movement-on-water are caught automatically.
14. As a developer, I want the MCP server to follow the modular `register(mcp)` pattern, so that adding new tool domains is straightforward.
15. As a developer, I want `pyproject.toml` entry points for the MCP server (stdio and HTTP modes), so that deployment and inspection are simple.
16. As a developer, I want the legacy agent-side MCP server deleted, so that there's one canonical server and no confusion.
17. As an MCP client, I want a `render_map` tool that returns an SVG (or PNG) of the current game state with fog of war applied, so that any client can display the map.
18. As an MCP client, I want a `render_map_ascii` tool that returns a text representation of the map, so that terminal-based clients can display it.
19. As an AI agent, I want my in-game memory cleared at the start of each new game, so that each game is a clean slate.
20. As a developer, I want reference agents that start fresh each game (no cross-game learning), so that tests are deterministic and reproducible.
21. As a developer, I want structured agent profiles (not just prompt strings) that define tool preferences, memory priorities, aggression thresholds, and expansion biases, so that personality differences are mechanically meaningful.
22. As a developer, I want the MCP server to expose action validation as a tool, so that agents and humans can check moves before committing.
23. As an AI agent, I want to read my scratchpad from previous turns, so that I can maintain continuity without relying on LLM context window.
24. As a human player, I want to see what resources I have and what I can build, so that I can make informed decisions.
25. As a developer, I want tests that specifically exercise edge cases like water-tile movement, attacking allied units, founding cities on mountains, and training units without resources, so that the rules engine is robust.

## Implementation Decisions

### MCP Server Consolidation

- Delete `agents/src/fastmcp_server.py` and `agents/src/fastmcp_client.py` entirely.
- Refactor the backend MCP server (`backend/src/mcp_server/`) to follow the autoscript-agents pattern:
  - Each tool domain gets a module with a `register(mcp: FastMCP)` function.
  - Tool domains: `lifecycle`, `gameplay`, `analysis`, `memory`, `history`, `rendering`.
  - Tools use FastMCP v3 annotations (`readOnlyHint`, `destructiveHint`, `tags`).
- Add `pyproject.toml` entry points: `fourex-mcp` (stdio) and `fourex-mcp-http` (HTTP with CORS).
- HTTP mode uses Starlette + Uvicorn with `/healthz` endpoint, matching the autoscript-agents pattern.
- Add corresponding `mise run` tasks: `serve` (stdio), `serve-http` (HTTP), `inspect` (MCP Inspector).

### Game Action Implementation

- Implement `BUILD_IMPROVEMENT` in `rules.py`:
  - Validates worker ownership, worker is on the target tile, tile terrain supports the improvement type.
  - Deducts resources per `IMPROVEMENT_STATS` (to be added to models.py alongside existing `BUILDING_STATS`).
  - Adds improvement to the tile model. Workers are consumed or remain (design follows FOUND_CITY pattern — worker consumed).
- Implement `BUILD_BUILDING` in `rules.py`:
  - Validates city ownership, city doesn't already have the building, player has resources.
  - Deducts resources per existing `BUILDING_STATS`.
  - Adds building to the city's building list.
- Both actions get corresponding MCP tool support in `gameplay.py` (validation) and inclusion in `submit_actions`.

### Agent Rewrite

- Agents operate exclusively through MCP tools. No direct REST calls.
- The agent runtime is an MCP client that connects to the backend MCP server (stdio or HTTP).
- Agent loop per turn: observe state (MCP) -> read memory (MCP) -> analyse (MCP) -> plan (LLM) -> validate (MCP) -> submit (MCP) -> write memory (MCP).
- The LLM receives: game state summary, memory context, analysis results, and the agent's behavioural profile. It returns structured actions (Pydantic models / structured output).

### Structured Personality System

- Replace the current 8 prompt-based personalities with structured `AgentProfile` configurations.
- An `AgentProfile` defines:
  - `tool_priorities`: ordered list of which analysis tools to run and how to weight their output (e.g. an aggressive agent always runs `evaluate_military_position` first).
  - `memory_priorities`: what to track in the scratchpad (e.g. economic agent tracks resource rates, aggressive agent tracks enemy unit positions).
  - `action_biases`: weights that influence action selection (e.g. explorer biases toward MOVE, economic toward BUILD_IMPROVEMENT).
  - `thresholds`: numeric triggers (e.g. "attack when military strength ratio > 1.5", "expand when city count < 3").
  - `system_prompt`: a short prompt that sets the agent's tone — but the mechanical behaviour comes from the structured fields above.
- These profiles are consumed by the agent runtime to decide which MCP tools to call, what to persist in memory, and how to frame the LLM planning prompt.

### Memory System

- Expand the existing scratchpad to support structured memory types within the 4KB (or larger) budget:
  - **Strategic goals**: list of current objectives with priority and status (e.g. `{"goal": "expand_north", "priority": 1, "status": "active", "since_turn": 3}`).
  - **Opponent models**: per-opponent notes (e.g. `{"player": "bob", "stance": "aggressive", "last_seen_units": 5, "threat_level": "high"}`).
  - **Turn notes**: freeform observations from the current turn.
- Memory is read at the start of each turn and written at the end.
- Memory is scoped to a single game. New game = empty memory.
- The MCP memory tools (`write_scratchpad`, `read_scratchpad`) may need to be extended or supplemented with structured variants (`write_strategic_goals`, `read_opponent_models`) — or the scratchpad can store JSON and the agent parses it. Prefer structured tools if the schema is stable.

### Map Rendering

- New MCP tool domain: `rendering`.
- `render_map_ascii` tool: returns a text grid representation of the visible map (fog of war applied). Uses Unicode box-drawing or simple characters. Includes legend.
- `render_map_svg` tool: returns an SVG string of the visible map. Tiles coloured by terrain, units/cities as icons, unexplored areas greyed out.
- `render_map_image` tool: returns a PNG (base64-encoded) generated from the SVG (using `cairosvg` or similar). Useful for clients that can display images but not render SVG.
- All rendering tools accept `game_id` and `player_id` and apply fog of war.

### Claude Code Skill

- A `/play-4x` skill for Claude Code that acts as a thin MCP client wrapper.
- The skill connects to the fourex MCP server and exposes a conversational interface: "show me the map", "move scout north", "what can I build?", "end turn".
- ASCII map rendering is done client-side in the skill (calls the `render_map_ascii` MCP tool and displays it).
- The skill is a separate concern from the MCP server — it translates natural language into MCP tool calls.
- The skill should also support spectating (read-only observation of an ongoing game).

### Testing Strategy

- **Unit tests** for every game action in `rules.py`:
  - Happy path for each action type (MOVE, ATTACK, FOUND_CITY, TRAIN_UNIT, BUILD_IMPROVEMENT, BUILD_BUILDING).
  - Edge cases: movement onto water, movement beyond range, attacking allies, founding on invalid terrain, building without resources, building duplicate buildings in a city.
- **MCP tool tests**: each tool module gets its own test file. Tests use in-memory game state (no database required).
- **Integration tests**: run a full multi-turn game through the MCP server with mock agents that submit scripted actions. Verify turn resolution, resource collection, fog of war.
- **Self-play test mode**: a pytest fixture or mise task that runs N agents through a full game (e.g. 20 turns) and asserts:
  - No unhandled exceptions.
  - No invalid action submissions accepted.
  - Game state remains consistent (no negative resources, no units on impassable tiles, no orphaned references).
  - Game terminates correctly (victory condition or turn limit).
- Self-play tests use deterministic seeds for reproducibility.
- The self-play mode should be runnable via `mise run self-play` with configurable turn count and player count.

## Out of Scope

- **Cross-game agent learning**: agents start fresh each game. Persistent learning across games is left to third-party agent developers.
- **Multiplayer networking / lobby system**: the MCP server handles one game at a time per connection. Matchmaking is not in scope.
- **Frontend changes**: the Next.js UI is unaffected. This work is backend + agents + CLI only.
- **New unit types, terrain types, or victory conditions**: the game mechanics stay as-is beyond implementing the two missing actions.
- **Agent vs agent ELO / ranking system**: out of scope for this PRD.
- **Mobile or web-based MCP clients**: only Goose and Claude Code are target clients.
- **LLM provider changes**: the multi-provider fallback chain stays as-is. Prompt improvements happen within the existing provider framework.
- **Database schema migrations beyond memory**: if new tables are needed for structured memory, they'll be added, but no broader schema overhaul.

## Further Notes

- The autoscript-agents project at `/Users/caleb/Projects/voicescript/autoscript-agents/` is the reference implementation for MCP server patterns (modular `register()`, entry points, annotations, error handling).
- The deterministic game engine (same seed + same actions = identical outcome) is a major asset for testing. Self-play tests should exploit this — if a test fails, the seed + action log is sufficient to reproduce.
- The existing 8 personalities (aggressive, defensive, explorer, economic, diplomatic, balanced, tech_focused, opportunist) should inform the new structured profiles. The *intent* of each is good; the *implementation* (pure prompt) is what's being replaced.
- The scratchpad size limit (currently 4KB) may need increasing for structured memory. 8KB or 16KB is reasonable — it's just a TEXT column.
- SVG rendering can use Python's `xml.etree.ElementTree` for generation (no external deps) and `cairosvg` for PNG conversion.
- The Claude Code `/play-4x` skill should be developed and tested last, as it depends on everything else being stable.
