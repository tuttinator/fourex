# Spectated Agent Games, Resignation & Cleanup — PRD

## Problem Statement

As a researcher using this repo as an AI-agent sandbox, I want to stand up an agent-vs-agent game with one command, open a browser and watch it play, and trust that the machinery — memory, context, cleanup, documentation — holds up over repeated experiments.

Today:

- Spinning up a watchable AI-vs-AI match is a multi-step ceremony: start backend, start frontend, sign in, create a game, invite an MCP agent, figure out how to wire a second agent to a different LLM provider, click Start, navigate to the board. `mise run showcase` and `mise run quick` drive agents but don't surface the live game in the browser for a human to observe.
- The `README.md` documents commands that don't exist (`make agents-showcase`, `make mcp-server`, `make agents-clean`). Anyone new to the repo tries them, hits failures, and loses trust in the docs before writing a line of code.
- There's no visibility into whether an agent is staying inside its provider's context budget, whether it's actually using its scratchpad, or how much of each turn's tokens are thinking vs output. When an agent plays badly, we can't tell if it's a model problem or a prompt-size problem.
- Abandoned lobbies and half-played games accumulate in the database with no way to clean them up. There's no per-game delete endpoint and no way for a player to resign mid-game — they just stop submitting turns and the game sits in `active` forever.
- The frontend already has a perfectly good `ObservationView`, but the games list doesn't distinguish "games I can watch" from "games I need to play", and there's no archive/trash affordance.

## Solution

A single `mise` task spins up a two-player game in the database, launches two programmatic agents against different LLM providers (LLM Studio locally, OpenAI remotely), prints the lobby URL, and starts the turn loop. The signed-in researcher opens that URL, is immediately routed into the existing `ObservationView`, and watches the game tick over.

While the agents play, a lightweight memory/telemetry layer records per-turn prompt tokens, completion tokens, thinking-token share, and scratchpad read/write counts. When an agent's prompt exceeds ~70% of the provider's context limit, the turn loop compacts the oldest turns into a summary (using the same LLM) and writes the summary to the scratchpad as durable memory. This makes context pressure visible and survivable, and doubles as a test-bed for long-horizon agent runs.

Players can resign from a game at any time. In 2-player games, resignation ends the match immediately with the remaining player as winner. In 3+ player games, the resigner's units and cities are razed, the game continues, and victory resolves normally when one player remains. Creators can archive their own games from the frontend or via a REST endpoint; a nightly sweep (and a matching on-demand `mise` task) soft-archives stale lobbies and dormant active games. Archived games are hidden from the default list but retain their snapshots and history for replay.

The `README.md` is rewritten to match the current `mise`-driven workflow and the actual repo layout (backend + frontend + agents + mcp_server). The games list gains an "In progress" default filter, an "Observe" vs "Resume" button distinction, an "Agent vs Agent" badge, and a trash/archive button on owned games.

## User Stories

1. As a researcher, I want a single command that launches a 2-player AI-vs-AI game and prints the URL to watch it, so that I can start an experiment in under 30 seconds.
2. As a researcher, I want the demo game to use LLM Studio for one player and OpenAI for the other, so that I can compare providers side-by-side on identical maps.
3. As a researcher, I want the OpenAI model to be configurable via environment variable, so that I can swap flagships without code changes.
4. As a researcher, I want the demo agents to create the game via the same REST and MCP surface a real agent would use, so that the spectated run also exercises the public API.
5. As a signed-in user, I want to open any in-progress game's URL and see a live read-only board, so that I can watch AI agents play without joining as a player.
6. As a spectator, I want a fog-of-war toggle and a per-player perspective selector, so that I can understand what each agent can actually see.
7. As a researcher, I want to see per-agent prompt-token and completion-token counts for each turn, so that I can spot when context is ballooning.
8. As a researcher, I want to see how often each agent reads and writes its scratchpad, so that I can tell whether memory is actually being used.
9. As a researcher, I want thinking-token share reported separately from output tokens, so that I can see how much of the turn cost is chain-of-thought.
10. As a researcher, I want the agent loop to detect when prompt size crosses ~70% of the provider's context limit and automatically compact older turns, so that long games don't crash from context overflow.
11. As a researcher, I want the compaction step to use the agent's own LLM to summarise prior turns, so that I don't need to configure a second provider.
12. As a researcher, I want compacted summaries written to the agent's scratchpad, so that durable memory survives across compaction events and the agent can re-read its own history.
13. As a player in a 2-player game, I want to resign, so that I can concede a lost position without abandoning the game.
14. As a player in a 3+ player game, I want to resign and have the game continue for the remaining players, so that my concession doesn't spoil other players' match.
15. As a creator, I want to archive one of my own games, so that it disappears from my default games list without being permanently deleted.
16. As a creator, I want to restore an archived game, so that I can recover a mistakenly archived one.
17. As a researcher, I want stale `waiting` lobbies older than 7 days to be auto-archived, so that the games list stays clean.
18. As a researcher, I want dormant `active` games (no turn progress for 14 days) to be auto-archived and marked `ended` with reason `abandoned`, so that stalled experiments are swept up without manual work.
19. As a developer working locally, I want a `mise` task that runs the archive sweep on demand, so that I can tidy up my dev database without configuring a cron job.
20. As a signed-in user browsing the games list, I want an "In progress" default filter, so that games I could observe right now are front-and-centre.
21. As a signed-in user, I want the action button on each game card to say "Observe" when I'm not a seated player and "Resume" when I am, so that I know what I'm clicking into.
22. As a signed-in user, I want games whose players are all agents to carry an "Agent vs Agent" badge, so that I can tell which games are interesting to spectate.
23. As a creator, I want a trash/archive button on games I own directly from the games list, so that I don't need to open a game to tidy it up.
24. As a new contributor, I want the `README.md` to accurately describe the `mise` tasks, the real architecture, and the current provider setup, so that my first hour in the repo isn't spent debugging stale docs.
25. As a contributor, I want every `make` reference replaced with the equivalent `mise run ...` invocation, so that there's one canonical task runner.
26. As an operator, I want `mise run showcase` to actually work end-to-end and produce observable games, so that the demo is reproducible.

## Implementation Decisions

### Demo orchestration

- The agent orchestrator will drive spectated demos through the public REST and MCP surface — not by calling `resolve_turn()` in-process. The orchestrator mints a game via the existing `POST /games` endpoint, both agents join via MCP (`join_game`), the orchestrator waits for both to be seated, issues start, and then each agent runs its own turn loop through MCP tools. This guarantees the game is in the database from turn 0 and the frontend `ObservationView` works immediately. It also exercises the public surface as an end-to-end smoke test.
- A new `mise` task (e.g. `observe-demo`) will run this orchestrator with a fixed config: 2 players, 20×20 map, deterministic seed, player A on LLM Studio, player B on OpenAI. The task prints the lobby URL, then the game URL, to stdout.
- The orchestrator will print a progress line per turn so the operator can see activity without opening the browser.

### Agent memory and telemetry

- A new telemetry module will wrap the LLM provider calls and record per-turn: provider, model, prompt tokens, completion tokens, thinking tokens, scratchpad reads, scratchpad writes, wall-clock, and the resulting action count.
- Token counting uses `tiktoken` when the provider is OpenAI-compatible; non-OpenAI providers fall back to a `len(text) / 4` heuristic. Accuracy only needs to be good enough to trigger compaction at a 70% threshold.
- Telemetry is written to a per-game JSONL file under a logs directory (one row per turn per agent) and also surfaced in the agent's structured log output. Out of scope: persisting telemetry to the database or exposing it via REST.
- The scratchpad tools (`write_scratchpad`, `read_scratchpad`) are already the agent's durable memory surface and are unchanged. The telemetry layer counts calls to them as observability.

### Context compaction

- Each agent tracks running prompt-token estimate across its turn history. When the estimate exceeds 70% of the provider's context window, the agent triggers a compaction step before its next turn.
- Compaction: take the oldest ~half of the agent's retained turn history, summarise it into a short "what happened and why it mattered" block using the same LLM the agent is playing with, replace those turns in the in-memory history with the summary, and also append the summary to the scratchpad under a `compacted_turns` section with turn-range metadata.
- Turns newer than the compaction cutoff are kept verbatim. The scratchpad is never truncated — it is the agent's durable memory.
- Context window is configured per-provider (with sensible defaults: 128k for modern OpenAI, 32k for LLM Studio local). Configurable via env vars.

### Resignation

- Add a new action type: `ResignAction`. Submittable via REST and via a new MCP `resign_game` tool.
- For 2-player games: the resigner is marked loser, the remaining player is declared winner, game status transitions to `ended`, `ended_at` is set. A new column `resigned_at: datetime | None` and `resigned_by: str | None` (player id) are added for audit. Resignation reason stored in a new `end_reason` column (values: `domination`, `score`, `resignation`, `abandoned`).
- For 3+ player games: resigner's units and cities are razed (converted to neutral ruins or removed — consistent with existing destruction logic in `rules.py`), resigner is flagged as eliminated but the game continues. Victory resolves when ≤1 player has cities, same as today.
- Frontend: a "Resign" button in `GameplayView` with a confirmation dialog. No frontend surface for spectators to resign (they're not seated).

### Archive lifecycle

- Add columns to `games`: `archived_at: datetime | None`, `archived_reason: str | None` (values: `manual`, `stale_waiting`, `stale_active`), `end_reason: str | None` (see Resignation).
- `GET /games` gains an `include_archived: bool = false` query param. Default excludes archived games. The games list page gains an "Archived" filter chip that sets this flag.
- New endpoint `POST /games/{id}/archive` — authenticated, restricted to the game's creator. New endpoint `POST /games/{id}/unarchive` for restoration. No hard-delete endpoint — archiving is non-destructive and snapshots are preserved.
- A new `mise run db-archive-stale` task runs the archive sweep on demand. The same logic is wrapped in a FastAPI startup task that runs daily (simple background `asyncio.create_task` loop; no cron dependency).
- Sweep thresholds: `status='waiting'` + `created_at < now - 7d` → archive with reason `stale_waiting`; `status='active'` + `turn_started_at < now - 14d` → transition to `ended` with `end_reason='abandoned'` and archive with reason `stale_active`. Both thresholds configurable via settings.

### Frontend polish

- Games list page default filter changes from "all" to "In progress" (status = `active`). Filter chips: In progress / Waiting / Ended / Archived. Polling cadence is unchanged (10s).
- Each game card shows an "Agent vs Agent" badge when every seated player is an MCP-key-backed agent (no `user_identity_id`).
- Action button per card: "Resume" when the signed-in user is a seated player in an active game; "Observe" when they are signed in but not seated and the game is active; "View" for ended/archived games. Unsigned users see no button, only a "Sign in to observe" link.
- Games created by the signed-in user get a small trash/archive icon button on the card with a confirmation dialog. Archived cards show an "Unarchive" affordance instead.
- `ObservationView` is unchanged. Spectator auth rule: signed-in users only. The fog toggle is available to all spectators; "god mode" (no-fog) view is restricted to the game creator. The backend enforces this by requiring a valid session for non-redacted state requests.

### Documentation

- `README.md` is rewritten to match the real repo layout (backend/ + frontend/ + agents/ + backend/src/mcp_server/), the real `mise` task list from `CLAUDE.md`, and the real provider chain (Modal Ollama → LLM Studio → OpenAI).
- Every `make` invocation is replaced with its `mise run ...` equivalent or deleted if the task doesn't exist. The "MCP Server" section references the canonical `fourex-mcp` entry point, not `make mcp-server`.
- A new "Watching agents play" section documents the observe-demo task and the env-var setup (`LLM_STUDIO_URL`, `OPENAI_API_KEY`, `OPENAI_MODEL`).
- The CLI-agent section is updated to match the current personality list and the current provider fallback order.

## Out of Scope

- Full admin role or RBAC system. Archiving is restricted to the game's creator; there is no "super-admin" concept.
- WebSocket streaming of live game state. The existing 3-second REST polling in `ObservationView` is sufficient for human spectators and simpler than introducing a state-level WebSocket.
- Replay scrubber UI (timeline slider over historical snapshots). Turn snapshots remain in the database but exposing them as a replay is deferred.
- Hard deletion of games with associated snapshots. Archiving is non-destructive; operators who want to reclaim disk run DB maintenance manually.
- Persisting telemetry to the database or building a telemetry dashboard. JSONL on disk is sufficient for research use.
- Auto-compaction strategies more sophisticated than the oldest-half summarisation — e.g. semantic chunking, retrieval-augmented memory, multi-tier summaries. These are future work if the simple approach proves inadequate.
- A second cheap-model provider for summarisation. Compaction uses the agent's own LLM.
- Spectator auth via share links or unauthenticated access. Signed-in only, for now.

## Further Notes

- The "GPT-5.4" reference in the original brief is treated as a placeholder. The `OPENAI_MODEL` env var (already in `agents/src/llm_providers.py`) is the single source of truth for which OpenAI model the demo uses. The README documents a recommended default but does not pin a specific model ID.
- Compaction threshold (70%), stale-waiting window (7 days), stale-active window (14 days), and per-provider context windows are all settings. Start with the defaults above and tune based on observed agent behaviour.
- The `end_reason` column is introduced alongside resignation because we're already touching this schema and having a single enum for `domination` / `score` / `resignation` / `abandoned` is cleaner than reverse-engineering it from `resigned_at` and `archived_reason`.
- The games list "Agent vs Agent" badge relies on the existing `PlayerApiKey.user_identity_id` nullability (MCP keys leave it null). No new schema is needed to detect agent-only games.
- Auto-archive sweep runs in the FastAPI process as a simple background asyncio loop with a 24-hour tick. If we later want cron-style reliability we can move it out, but an in-process loop is good enough given the dev-focused operating posture.
- The observe-demo task assumes LLM Studio is already running locally at `LLM_STUDIO_URL` and that `OPENAI_API_KEY` is set. The task should fail fast with a clear error message if either is missing, rather than waiting for the first LLM call to crash.
- Consider adding a `/healthz`-style check to the observe-demo task that validates both providers before creating the game, to keep the feedback loop tight.
