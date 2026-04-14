# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

4X ("eXplore, eXpand, eXploit, eXterminate") turn-based strategy game designed as a sandbox for AI agent research. The game engine is deterministic: same seed + same actions = identical outcomes.

## Commands

```bash
# Install dependencies (uses uv, managed via mise)
mise run install

# Run backend dev server (FastAPI on :8000)
mise run run-dev
# Or: cd backend && uv run python src/main.py

# Run frontend dev server (Next.js on :3000)
cd frontend && npm run dev

# Run backend tests
mise run backend-test          # backend tests only
mise run test                  # root-level tests (tests/ dir)
uv run pytest tests/test_turn_progression.py -k "test_name"  # single test

# Run quick agent game
mise run quick

# Formatting and linting
mise run format                # black + ruff --fix
mise run lint                  # black --check + ruff + mypy

# Database (requires docker-compose up -d postgres)
mise run db-reset              # drop + recreate tables
mise run db-check              # verify connection
```

## Architecture

Three main components, each with its own source tree:

### backend/ — Game Engine + API
- `src/game/models.py` — Pydantic models: `GameState`, `Unit`, `City`, `Tile`, `Action` (discriminated union of `MoveAction | AttackAction | FoundCityAction | TrainUnitAction | ...`), `ResourceBag`, enums for `Terrain`, `Resource`, `UnitType`, `BuildingType`
- `src/game/rules.py` — Pure deterministic game logic: `resolve_turn()` is the core entry point, processes all player actions, collects resources, advances turn counter. Map generation uses seeded RNG
- `src/api/rest.py` — FastAPI REST endpoints under `/api/v1`: game CRUD, state queries with fog-of-war, action submission
- `src/api/websocket.py` — Real-time game updates via WebSocket
- `src/api/persistent_game_controller.py` — Game state management with database persistence
- `src/database/` — SQLAlchemy async (asyncpg) with Alembic migrations
- `src/config.py` — `pydantic-settings` based config, reads from `.env`

### agents/ — AI Agent System
- `src/agent.py` — `FourXAgent` class: LLM-driven agent that observes game state, plans, and submits actions
- `src/orchestrator.py` — `GameOrchestrator`: runs a full game loop, creates agents with personalities (aggressive/defensive/economic), manages turn execution
- `src/llm_providers.py` — `MultiLLMClient` with provider fallback chain: Modal Ollama > LLM Studio (local, default :1234) > OpenAI. All providers extract `<think>...</think>` tokens from responses
- `src/fastmcp_server.py` — FastMCP server exposing game analysis tools (territory, military, resources, action validation) for MCP-compatible clients
- `src/personalities.py` — Agent personality definitions

### frontend/ — Next.js UI
- Next.js + TypeScript + Tailwind CSS + shadcn/ui (Radix primitives)
- React Query for server state

## Key Design Decisions

- **Deterministic game engine**: `rules.py` functions are pure — no randomness except seeded RNG in map generation. This enables reproducible testing and replay
- **Fog-of-war**: `redact_state()` filters game state per-player based on unit/city sight ranges. The API always returns redacted state
- **Coordinates use Manhattan distance** (`abs(dx) + abs(dy)`) for movement, sight, and combat range. Map wraps at edges (toroidal)
- **LLM thinking tokens**: All providers strip `<think>...</think>` tags from responses, returning cleaned content + thinking separately in `LLMResponse`
- **Provider environment variables**: `MODAL_OLLAMA_URL`, `LLM_STUDIO_URL` (default localhost:1234), `OPENAI_API_KEY`, `REPLICATE_API_TOKEN`, `HF_TOKEN`, `LOGFIRE_ENABLED`

## Tech Stack

- Python 3.12+, uv for package management
- FastAPI + Pydantic v2
- SQLAlchemy async + asyncpg + PostgreSQL (via docker-compose)
- Observability: logfire + structlog
- Resilience: tenacity + backoff for LLM retries
- Frontend: Next.js, TypeScript, Tailwind, Radix UI, React Query
