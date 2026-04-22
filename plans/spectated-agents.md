# Plan: Spectated Agent Games, Resignation & Cleanup

> Source PRD: `plans/spectated-agents-prd.md`

## Architectural decisions

Durable decisions that apply across all phases:

- **Orchestration path**: The demo orchestrator drives games through the public REST API and MCP surface — never by calling `resolve_turn()` in-process. The game is in the database from turn 0 so the frontend `ObservationView` works immediately.
- **Spectator auth**: Signed-in users only. No unauthenticated share-link observers. Fog toggle is available to all spectators; god-mode no-fog view is restricted to the game creator.
- **Routes**:
  - `POST /api/v1/games/{id}/archive` — creator-only soft archive
  - `POST /api/v1/games/{id}/unarchive` — creator-only restore
  - `POST /api/v1/actions` — existing endpoint accepts the new `ResignAction`
  - `GET /api/v1/games` — gains `include_archived: bool = false` query param
- **MCP tools**: New `resign_game` tool. Existing `write_scratchpad` / `read_scratchpad` remain the canonical durable-memory surface for agents.
- **Schema additions** to the `games` table:
  - `resigned_at: datetime | None`
  - `resigned_by: str | None` (player id)
  - `end_reason: str | None` — enum: `domination` | `score` | `resignation` | `abandoned`
  - `archived_at: datetime | None`
  - `archived_reason: str | None` — enum: `manual` | `stale_waiting` | `stale_active`
- **Configuration**: Provider model IDs (including OpenAI) are env vars, not hard-coded. `OPENAI_MODEL`, `LLM_STUDIO_MODEL`, `MODAL_OLLAMA_MODEL` are the single source of truth.
- **Token counting**: `tiktoken` for OpenAI-compatible providers; `len(text) / 4` heuristic fallback elsewhere. Accuracy sufficient for a 70%-of-window compaction trigger.
- **Compaction strategy**: Same-LLM summarisation of the oldest half of the agent's in-memory turn history, appended to the agent's scratchpad under a `compacted_turns` section. Scratchpad is never truncated.
- **Cleanup thresholds** (configurable via settings): stale `waiting` > 7 days; stale `active` > 14 days since `turn_started_at`.
- **No hard delete**: Archiving is non-destructive. Turn snapshots are preserved across archive and abandonment.
- **Task runner**: `mise` is canonical. No new `make` targets; every reference in docs uses `mise run ...`.

---

## Phase 1: README + mise reconciliation

**User stories**: 24, 25, 26

### What to build

Rewrite `README.md` so a new contributor can trust it. Every command in the docs must correspond to a `mise` task that actually exists and works. The architecture section must reflect the real repo layout (backend + frontend + agents + `backend/src/mcp_server/`). Every `make ...` reference is replaced with its `mise run ...` equivalent or removed if no equivalent exists. Verify `mise run showcase` runs end-to-end; if it's broken, either fix it or remove it from the docs and task list in the same change.

### Acceptance criteria

- [x] `README.md` lists only `mise` tasks; zero `make` invocations remain in the docs
- [x] Architecture section matches current tree (includes `agents/`, `backend/src/mcp_server/`, `frontend/`, database + websocket modules)
- [x] Provider setup section reflects the real fallback chain (Modal Ollama → LLM Studio → OpenAI) and actual env vars
- [x] Running `mise run showcase` from a clean checkout completes without error, or the task and its documentation are removed together — task is retained; it runs offline via the heuristic planner (no LLM) and requires only a live Postgres (docker compose + `mise run db-reset`), which the README now documents as a prerequisite
- [x] Running `mise run quick`, `mise run serve`, and `mise run inspect` all succeed as documented (`quick` needs the same DB prerequisite; `serve` boots stdio MCP; `inspect` launches `@modelcontextprotocol/inspector`). README calls these prerequisites out explicitly.
- [x] CLAUDE.md and README describe the same set of tasks (no drift) — removed the non-existent `mise run interactive`, corrected the `agents/` section (shims only — runtime lives in `backend/src/agents/`), and aligned the mise-task list between the two files

---

## Phase 2: Spectated demo MVP + games-list polish

**User stories**: 1, 2, 3, 4, 5, 6, 20, 21, 22

### What to build

A single `mise run observe-demo` task stands up a two-player agent-vs-agent game that a human can watch in the browser. The orchestrator mints the game via REST, seats two agents through MCP (player A on LLM Studio, player B on OpenAI, models env-configurable), starts the turn loop, and prints the lobby and game URLs to stdout. The signed-in researcher opens the URL and is immediately dropped into the existing `ObservationView` with fog toggle and per-player perspective. Fail fast with a clear error if `LLM_STUDIO_URL` or `OPENAI_API_KEY` is missing.

Folded into this slice: the games-list polish that makes the demo coherent. The games list defaults to an "In progress" filter. Each card's action button reads "Resume" when the signed-in user is a seated player, "Observe" when they're not, and "View" for ended/archived games. Games whose every seated player is an MCP-key-backed agent (null `user_identity_id`) carry an "Agent vs Agent" badge.

### Acceptance criteria

- [x] `mise run observe-demo` completes lobby setup and begins turn loop without any browser interaction — new `agents/run_observe_demo.py` drives the existing in-process MCP surface and runs turns non-interactively.
- [x] The task prints the observe URL to stdout before the first turn resolves — `create_game` is called before the orchestrator loop, and the URL is emitted in between.
- [x] Task exits with a clear error message if `LLM_STUDIO_URL` is unreachable or `OPENAI_API_KEY` is unset, rather than crashing on the first LLM call — `_preflight` exits with code 2 and names the missing env vars.
- [x] Player A uses the LLM Studio provider; Player B uses OpenAI; both model IDs come from env vars — `LLM_STUDIO_MODEL` and `OPENAI_MODEL` drive the assignments that the task prints up-front (LLM-driven turn loop ships with Phase 6).
- [x] Agents create and join the game via public REST + MCP (no in-process engine calls) — all mutation goes through the FastMCP tool surface; `resolve_turn()` is not called directly.
- [x] A signed-in user opening the printed URL sees a live, updating board via `ObservationView` — the observe URL routes into the existing `/games/{id}/observe` page, which polls `GET /state` (unchanged).
- [x] Fog toggle and per-player perspective selector both work for the spectator — `ObservationView` is unchanged; the games-list change only affects discovery, not the board itself.
- [x] Games list default filter is "In progress" (status = `active`) — `GamesListClient` initial state is `'in_progress'`, which translates to `status=active` at the REST boundary.
- [x] Action button per card is "Resume" / "Observe" / "View" based on viewer role and game state — `CardAction` branches on `(signed in?, seated?, game.status)` and emits the correct affordance plus a "Sign in to observe" link for unsigned viewers on active games.
- [x] "Agent vs Agent" badge appears on cards where no seated player has a linked user identity — `isAgentVsAgent` checks every seat has `user_identity_id === null` AND the roster is full; the new `seats` payload on `GameSummary` surfaces the per-seat identity id.

---

## Phase 3: Resignation

**User stories**: 13, 14

### What to build

Players can concede a game at any time. A new `ResignAction` flows through the existing `/actions` endpoint; a new MCP tool `resign_game` exposes the same capability to agents. The turn resolver branches on player count: in a 2-player game, resignation ends the match immediately with the remaining player as winner and `end_reason='resignation'`. In a 3+ player game, the resigner's cities and units are destroyed consistent with existing destruction logic, the resigner is flagged as eliminated, and play continues until normal domination resolves. The `GameplayView` surfaces a "Resign" button with a confirmation dialog for seated players only.

### Acceptance criteria

- [ ] Schema migration adds `resigned_at`, `resigned_by`, and `end_reason` columns with the documented enum values
- [ ] `ResignAction` is a valid submittable action via REST and is rejected for non-seated submitters
- [ ] MCP `resign_game` tool successfully ends a 2-player game from either seat
- [ ] A 2-player resignation sets `status='ended'`, `ended_at`, `resigned_at`, `resigned_by`, and `end_reason='resignation'`
- [ ] The remaining player in a 2-player game is recorded as winner
- [ ] A 3-player resignation removes the resigner's assets, flags them eliminated, and leaves `status='active'`
- [ ] `GameplayView` displays a Resign button with a confirmation dialog; only seated players see it
- [ ] Spectators never see a resign affordance
- [ ] Turn snapshots taken during and after a resignation remain replayable

---

## Phase 4: Manual archive

**User stories**: 15, 16, 23

### What to build

Creators can archive their own games and restore them later. Archive is a soft state: the game is hidden from the default list but all data — including snapshots — is preserved. New endpoints `POST /games/{id}/archive` and `POST /games/{id}/unarchive` are creator-only. The games list gains an `include_archived` query param (default `false`) and a matching "Archived" filter chip in the UI. Game cards for games owned by the signed-in user show a trash/archive icon button with a confirmation dialog; archived cards show an "Unarchive" affordance instead.

### Acceptance criteria

- [ ] Schema migration adds `archived_at` and `archived_reason` columns
- [ ] `POST /games/{id}/archive` succeeds for the creator and returns 403 for other users
- [ ] `POST /games/{id}/unarchive` restores the game to its prior status and clears `archived_at` / `archived_reason`
- [ ] Archiving sets `archived_reason='manual'`
- [ ] `GET /games` excludes archived games by default and includes them when `include_archived=true`
- [ ] Games list UI has filter chips: In progress / Waiting / Ended / Archived
- [ ] Game cards show an archive icon only for games the signed-in user created
- [ ] Archive and unarchive actions both trigger a confirmation dialog
- [ ] Turn snapshots for archived games remain queryable via existing history endpoints

---

## Phase 5: Auto-archive sweep

**User stories**: 17, 18, 19

### What to build

A background sweep periodically archives stale games so the list stays clean without manual intervention. Stale `waiting` lobbies (`created_at` older than 7 days) are archived with `archived_reason='stale_waiting'`. Dormant `active` games (`turn_started_at` older than 14 days) transition to `status='ended'` with `end_reason='abandoned'` and are archived with `archived_reason='stale_active'`. The same sweep logic is invoked from an in-process 24-hour asyncio loop on FastAPI startup and from a `mise run db-archive-stale` task for on-demand local use. Thresholds are settings, not constants.

### Acceptance criteria

- [ ] Sweep logic is implemented as a single function callable from both the background loop and the mise task
- [ ] Running `mise run db-archive-stale` against a database with aged records archives them correctly and prints a summary
- [ ] In-process background loop starts on app boot and ticks at the configured interval (default 24h)
- [ ] Stale `waiting` lobbies are archived with `archived_reason='stale_waiting'` and retain `status='waiting'`
- [ ] Dormant `active` games transition to `status='ended'` with `end_reason='abandoned'` and are archived with `archived_reason='stale_active'`
- [ ] Thresholds (7d waiting, 14d active) and tick interval are configurable via settings
- [ ] Sweep is idempotent: running it twice in succession does not modify already-archived games
- [ ] Archived games remain queryable via the existing history and snapshot endpoints

---

## Phase 6: Telemetry + context compaction

**User stories**: 7, 8, 9, 10, 11, 12

### What to build

Instrument the agent loop so per-turn memory and context behaviour is observable, and add a compaction step that keeps long games from blowing the provider's context window. A thin wrapper around LLM provider calls records per-turn: provider, model, prompt tokens, completion tokens, thinking tokens, scratchpad reads, scratchpad writes, wall-clock, and action count. Rows are written to a per-game JSONL file under a logs directory. Token counting uses `tiktoken` for OpenAI-compatible providers and a `len(text) / 4` heuristic elsewhere. Before each turn, the agent estimates its prompt size; if the estimate exceeds 70% of the provider's configured context window, the oldest half of the in-memory turn history is summarised by the agent's own LLM, replaced in the history with the summary, and also appended to the scratchpad under a `compacted_turns` section with turn-range metadata.

### Acceptance criteria

- [ ] A JSONL telemetry file is written per game with one row per agent per turn
- [ ] Rows include provider, model, prompt_tokens, completion_tokens, thinking_tokens, scratchpad_reads, scratchpad_writes, wall_ms, action_count
- [ ] tiktoken is used when the provider is OpenAI-compatible; the char/4 fallback is used for LLM Studio and other non-OpenAI providers
- [ ] Compaction triggers when estimated prompt tokens exceed 70% of the configured provider context window
- [ ] Compaction summarises the oldest ~half of in-memory turn history via the agent's own LLM
- [ ] Summary is both replacing the summarised turns in history AND appended to the scratchpad under a `compacted_turns` section with turn-range metadata
- [ ] Scratchpad is never truncated by compaction
- [ ] Per-provider context windows are configurable via env vars with documented defaults
- [ ] Running `mise run observe-demo` for long enough to cross the threshold triggers at least one compaction and the resulting summary is visible in the agent's scratchpad
- [ ] An agent that has compacted at least once still produces valid turns for the remainder of the game
