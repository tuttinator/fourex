# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

4X ("eXplore, eXpand, eXploit, eXterminate") turn-based strategy game designed as a sandbox for AI agent research. The game engine is deterministic: same seed + same actions = identical outcomes.

## Commands

```bash
# Install dependencies (uses uv, managed via mise)
mise run install

# Run backend dev server (FastAPI on :8010)
mise run backend

# Run frontend dev server (Next.js on :3000)
mise run frontend

# Run backend tests
mise run backend-test          # backend tests only
mise run test                  # root-level tests (tests/ dir)
uv run pytest tests/test_turn_progression.py -k "test_name"  # single test

# Run AI agents (profile-driven, deterministic — no LLM required)
mise run quick                 # 2-player quick test game (30 turns)
mise run classic               # 3-player classic game (75 turns)
mise run showcase              # 4-player profile showcase (100 turns)
mise run self-play             # self-play smoke test with invariant checks
mise run run-cli               # pure-engine CLI (no MCP, no DB)

# Run MCP server (single canonical server in backend/src/mcp_server/)
mise run serve                 # stdio mode (via fourex-mcp entry point)
mise run serve-http            # streamable-http mode, port 8020 (via fourex-mcp-http)
mise run inspect               # MCP Inspector against stdio server
mise run inspect-http          # MCP Inspector against HTTP server

# Formatting and linting
mise run format                # black + ruff --fix
mise run lint                  # black --check + ruff + pyrefly

# Database (schema managed by alembic; migrations in backend/migrations/)
mise run db-migrate            # apply pending migrations (alembic upgrade head)
mise run db-reset              # downgrade base + upgrade head (drops all data)
mise run db-check              # verify connection

# Frontend feedback loops (run all four before committing any frontend
# change — vitest/tsc/eslint don't exercise the Auth.js request pipeline,
# so runtime config errors like MissingAdapter only surface in `build`)
cd frontend && npm run type-check
cd frontend && npm run lint
cd frontend && npm run test -- --run
cd frontend && npm run build
```

## Architecture

Source trees:

### backend/ — Game Engine + API + Agent Runtime + MCP Server

- `src/game/models.py` — Pydantic models: `GameState`, `Unit`, `City`, `Tile`, `Action` (discriminated union of `MoveAction | AttackAction | FoundCityAction | TrainUnitAction | ...`), `ResourceBag`, enums for `Terrain`, `Resource`, `UnitType`, `BuildingType`
- `src/game/rules.py` — Pure deterministic game logic: `resolve_turn()` is the core entry point, processes all player actions, collects resources, advances turn counter. Map generation uses seeded RNG
- `src/game/rules_reference.py` — Single-source constants backing the `/rules` endpoint and the `get_rules_reference` MCP tool
- `src/api/rest.py` — FastAPI REST endpoints under `/api/v1`: game CRUD, state queries with fog-of-war, action submission, valid-moves, queueable-tiles, rules reference
- `src/api/websocket.py` — Authenticated lobby + game WebSocket
- `src/api/persistent_game_controller.py` — Game state management with database persistence
- `src/api/turn_resolution.py` — Action parsing for REST + MCP
- `src/database/` — SQLAlchemy async (asyncpg) with Alembic migrations
- `src/agents/` — Profile-driven MCP agent runtime: `orchestrator.py`, `agent_runtime.py`, `planner.py` (deterministic heuristic planner), `profiles.py` (`aggressive` / `economic` / `explorer` / `balanced`), `selfplay.py`, `mcp_client.py` (in-process + streamable-HTTP)
- `src/config.py` — `pydantic-settings` based config, reads from `.env`

### backend/src/mcp_server/ — MCP Server (single canonical server)

- `server.py` — FastMCP server with stdio and streamable-http transports, CORS, `/healthz`
- `tools/lifecycle.py` — Game creation and joining (`create_game`, `join_game`, `get_game_info`)
- `tools/gameplay.py` — Turn flow (`get_game_state`, `submit_actions`, `validate_actions`, `get_valid_moves`, `is_my_turn`, `get_rules_reference`)
- `tools/analysis.py` — Strategic analysis (`analyze_territory`, `evaluate_military_position`, `find_resource_opportunities`, `calculate_distances`)
- `tools/memory.py` — Agent memory (`write_scratchpad`, `read_scratchpad`, `write_strategic_goals`, `write_opponent_model`, `write_turn_notes` + readers)
- `tools/diplomacy.py` — Treaties, messaging, declare-war
- `tools/rendering.py` — ASCII / SVG / PNG map renderers
- `tools/history.py` — Turn history (`get_turn_history`, `get_turn_snapshot`)
- All tools use FastMCP v3 annotations (`readOnlyHint`, `openWorldHint`) and `tags` for categorisation
- Entry points: `fourex-mcp` (stdio), `fourex-mcp-http` (HTTP on :8020)

### agents/ — CLI shims

Thin CLI wrappers around `backend.src.agents`. No game logic lives here.

- `run_agents.py` — preset runner used by `mise run quick|classic|showcase`
- `run_selfplay.py` — used by `mise run self-play`
- `src/llm_providers.py` — `MultiLLMClient` with provider fallback chain: Modal Ollama > LLM Studio (local, default :1234) > OpenAI. All providers extract `<think>...</think>` tokens from responses. Only needed if you build an LLM-driven agent on top of the MCP surface; the bundled planner is offline.
- `src/enhanced_logging.py` — structured logging setup shared by the shims

### frontend/ — Next.js UI

- Next.js + TypeScript + Tailwind CSS + shadcn/ui (Radix primitives)
- React Query for server state
- Pixi.js for the map canvas

## Key Design Decisions

- **Deterministic game engine**: `rules.py` functions are pure — no randomness except seeded RNG in map generation. This enables reproducible testing and replay
- **Fog-of-war**: `redact_state()` filters game state per-player based on unit/city sight ranges. The API always returns redacted state
- **Coordinates use Manhattan distance** (`abs(dx) + abs(dy)`) for movement, sight, and combat range. Map wraps at edges (toroidal)
- **LLM thinking tokens**: All providers strip `<think>...</think>` tags from responses, returning cleaned content + thinking separately in `LLMResponse`
- **Provider environment variables**: `MODAL_OLLAMA_URL`, `LLM_STUDIO_URL` (default localhost:1234), `OPENAI_API_KEY`, `REPLICATE_API_TOKEN`, `HF_TOKEN`, `LOGFIRE_ENABLED`

## Tech Stack

- Python 3.12+, uv for package management
- FastAPI + Pydantic v2
- SQLAlchemy async + asyncpg + PostgreSQL
- Observability: logfire + structlog
- Resilience: tenacity + backoff for LLM retries
- Frontend: Next.js, TypeScript, Tailwind, Radix UI, React Query
