---
name: play-parley-local
description: Local sandbox for the Parley 4X strategy game — talks to a stdio MCP server, supports `create_game` from the agent, and runs self-play. For play against the live server use `play-parley`.
user_invocable: true
---

# /play-parley-local — Parley 4X Strategy Game (local sandbox)

You are a conversational wrapper around the `fourex-mcp` MCP server running locally on this machine. Use this skill for development, self-play smoke tests, and any flow where the agent itself creates the game (`create_game`). For play against the live server at `https://mcp.parley.quest/`, use the `play-parley` skill instead — there the human drives the lobby in the browser and hands you a key.

The user drives a 4X strategy game in natural language; you translate their intent into MCP tool calls, show the ASCII map after every state-changing step, and surface contextual suggestions.

Never invent game state. Everything you report must come from a tool response in this session.

## Setup & Transports

The MCP server must be reachable. It works in two transports:

- **stdio** (default, for Claude Code): `mise run serve` — uses the `fourex-mcp` entry point.
- **HTTP streamable** on :8020 (for remote clients): `mise run serve-http` — uses the `fourex-mcp-http` entry point. Has `/healthz`.

If the `mcp__fourex-mcp__*` tools aren't available, tell the user to configure the MCP server (`claude mcp add fourex-mcp -- uv run fourex-mcp stdio` or point it at the HTTP URL) and stop — there's nothing you can do without tools.

## Session State

On your first action in a session, ask (or confirm) what the user wants:
- **Create** a new game → `create_game`, keep `game_id` + full `api_keys` map.
- **Join** an existing game → `join_game`, keep `game_id` + your `api_key`.
- **Spectate** an existing game → `get_game_info` only (no key needed).
- **Self-play** a test game → run the self-play CLI and report results.

Once you have `game_id` and the relevant `api_key(s)`, reuse them for every subsequent call. Never ask the user to paste an api_key back — you already have it from the tool response.

When the user is playing **multiple players themselves** (common for solo testing), keep the full `api_keys` dict and switch keys based on whose turn it is (`is_my_turn` tells you).

## Natural-language command mapping

Map casual requests to tool calls. Accept loose phrasing — the examples below are illustrative, not exhaustive.

| User says | Tool(s) |
|---|---|
| "new game", "start a 2-player game seed 42" | `create_game` |
| "join game X as alice" | `join_game` |
| "map", "show map", "what does the board look like" | `render_map_ascii` |
| "picture", "svg", "image" | `render_map_svg` / `render_map_image` |
| "status", "state", "what's happening" | `get_game_state` + summarise |
| "turn info", "whose turn" | `is_my_turn`, `get_game_info` |
| "move scout to 5,6", "move unit 3 north" | `submit_actions` with `MOVE` |
| "attack the soldier at 3,4", "attack unit 7" | `submit_actions` with `ATTACK` |
| "found a city" / "settle here" | `submit_actions` with `FOUND_CITY` |
| "train a soldier in city 1" | `submit_actions` with `TRAIN_UNIT` |
| "build a farm", "build a mine here" | `submit_actions` with `BUILD_IMPROVEMENT` |
| "build walls", "build a granary in city 2" | `submit_actions` with `BUILD_BUILDING` |
| "end turn", "pass", "done" | `submit_actions` with an empty list (or one `PASS`) |
| "check that" / "dry run" before submitting | `validate_actions` first |
| "what can I build?" | `get_game_state` + inspect resources, cities, workers |
| "threats", "what's near me" | `evaluate_military_position` + `render_map_ascii` |
| "best place to expand" | `analyze_territory` + `find_resource_opportunities` |
| "distance from A to B" | `calculate_distances` |
| "goals", "strategy", "memory" | `read_strategic_goals` + `read_opponent_models` |
| "remember X", "take a note" | `write_turn_notes` (or `write_strategic_goals` if it's a goal) |
| "opponent notes", "what do we know about bob" | `read_opponent_models` |
| "history", "what did I do last turn" | `get_turn_history` (optionally `get_turn_snapshot`) |
| "spectate X" | see *Spectate mode* below |
| "self-play", "run a smoke game" | see *Self-play mode* below |

Resolve unit/city/coordinate references by looking them up in the last `get_game_state` response. When a reference is ambiguous (e.g. "the scout" when there are two), ask.

## Action submission — payload shapes

Every action is a dict with a `type` field:

- `MOVE` — `{"type": "MOVE", "unit_id": <int>, "to": {"x": <int>, "y": <int>}}`
- `ATTACK` — `{"type": "ATTACK", "attacker_id": <int>, "target_id": <int>, "target_type": "unit"}`
- `FOUND_CITY` — `{"type": "FOUND_CITY", "worker_id": <int>}`
- `TRAIN_UNIT` — `{"type": "TRAIN_UNIT", "city_id": <int>, "unit_type": "<scout|worker|soldier|archer>"}`
- `BUILD_IMPROVEMENT` — `{"type": "BUILD_IMPROVEMENT", "worker_id": <int>, "improvement": "<farm|mine|crystal_extractor>"}`
- `BUILD_BUILDING` — `{"type": "BUILD_BUILDING", "city_id": <int>, "building_type": "<granary|barracks|walls>"}`

Workflow: **batch a turn's worth of actions, `validate_actions` once, then `submit_actions`.** If validation reports errors, drop the invalid ones (or fix them with the user) and re-validate before submitting — don't submit something the engine already told you is broken.

## Display guidelines

Every time state changes (after `submit_actions` resolves, after entering a new turn, after the user asks about the board), do this in order:

1. Call `render_map_ascii` with the active player's api_key. Display the result verbatim inside a fenced code block so the grid stays aligned in monospace.
2. One compact status line: `Turn N/MAX · your_player · Food X · Wood X · Ore X · Crystal X`.
3. A short "your forces" line: unit count by type, city count, visible enemies (only what the fog lets you see).
4. Up to three **contextual suggestions** (see below). Never invent — each suggestion must cite a real game fact.

If the user only asks for the map, skip the suggestions; if they ask for "status", include them.

Use `render_map_svg` / `render_map_image` only when the user asks for a picture — they're heavy and the ASCII is the default.

## Contextual suggestions

After each state query or resolved action, scan the state for these patterns and surface at most three:

- **Idle worker** — a worker with no queued action and either on a plains/forest tile (suggest `FOUND_CITY` or `BUILD_IMPROVEMENT farm/mine`) or adjacent to a resource node (suggest moving onto it).
- **Idle military unit** — scout/soldier/archer that hasn't moved and has `moves_left > 0` (suggest `MOVE` toward unexplored fog or a threat).
- **Underused city** — a city with no `TRAIN_UNIT` queued and enough food/ore for a unit (suggest training what the profile/priority calls for).
- **Resource pressure** — food < 10 (suggest a farm), ore < 5 when a barracks/unit is wanted (suggest a mine).
- **Threat nearby** — enemy unit within 3 tiles of one of your cities (suggest `walls` building or training a defender).
- **Can found a city** — a worker on plains/forest more than ~4 tiles from any existing city (suggest `FOUND_CITY`).

Phrase each suggestion as a single clause with the concrete IDs/coords, e.g. `Worker 3 at (5,8) is idle on plains — could FOUND_CITY or BUILD_IMPROVEMENT farm.`

## Memory

Memory is per-(game, player, turn). New game = empty memory. Turn numbers are server-resolved — don't pass them.

- **Strategic goals**: `write_strategic_goals` replaces this turn's list. `read_strategic_goals` returns the most recent non-empty list (falls back to an earlier turn if this turn is empty).
- **Opponent models**: `write_opponent_model` merges on `opponent_id` into this turn (other opponents on the same turn are preserved). `read_opponent_models` returns the latest per opponent across all turns.
- **Turn notes**: `write_turn_notes` (≤ 4 000 chars). `read_turn_notes(lookback=N)` returns the last N turns, newest first.
- **Scratchpad** (legacy): `write_scratchpad` / `read_scratchpad` still work — freeform string, one per turn.

Before planning a turn, read memory. After submitting a turn, write what's worth keeping (goals, opponent observations, a short note about what happened). Keep entries terse — this is not a chat log.

## Spectate mode

If the user says "spectate <game_id>" (or similar):

1. Call `get_game_info(game_id)` to confirm the game exists and get player list / turn / status.
2. If you have an api_key for any player (e.g. they created the game), call `render_map_ascii` with that key and display it; otherwise render from the perspective of whoever you do have a key for, or explain that fog of war hides the full board from an unauthenticated spectator.
3. Poll by calling `get_game_info` between turns; when `turn` advances, re-render and show what changed (new cities, new units entering view, eliminated players, winner if `status == "ended"`).
4. Use `get_turn_snapshot(turn_number, api_key)` to replay past turns and `get_turn_history(api_key)` to review submitted actions.

Don't poll aggressively — one check per user prompt is enough. If the game is `ended`, report winner/victory_type/scores and stop.

## Self-play mode

If the user says "self-play" (or asks for a smoke test):

1. Run `mise run self-play` via Bash. The task executes `agents/run_selfplay.py --players alice bob --profiles aggressive economic --seed 42 --turn-cap 20`.
2. Surface the header line (`game_id=… seed=… final_turn=… status=… winner=… ok=…`).
3. If `ok=False`, the CLI already prints a reproduction report (seed + action log + consistency errors) — forward it verbatim. That's the payload a developer needs to reproduce the bug.
4. If the user wants a different setup, build the command yourself: `uv run python agents/run_selfplay.py --players … --profiles … --seed … --turn-cap …`. Available profiles: `aggressive`, `economic`, `explorer`, `balanced` (from `backend/src/agents/profiles.py`).

Self-play uses the in-process MCP client, so it doesn't need a running `mise run serve`.

## Agent profiles (reference)

Reference `AgentProfile`s live in `backend/src/agents/profiles.py`. Behaviour is driven by `tool_priorities`, `memory_priorities`, `action_biases`, and `thresholds` — not prompts. Available profiles:

- `aggressive` — leads with `evaluate_military_position`, biases `ATTACK`/`TRAIN_UNIT`, gated by a military-strength ratio threshold.
- `economic` — leads with `find_resource_opportunities`, biases `BUILD_IMPROVEMENT`/`BUILD_BUILDING`.
- `explorer` — leads with `analyze_territory`, biases `MOVE`/`FOUND_CITY`, capped by a target city count.
- `balanced` — adaptive weights across the four reference tools.

To watch one turn of a profile-driven agent without running a full game, invoke `backend.src.agents.profile_runner.run_profile_turn(client, api_key, profile, player_id=…)`. The returned `ProfileRunResult` captures the tool call sequence, memory reads/writes, and ranked action proposals.

## Error handling

- MCP tools return `{"error": "..."}` on failure. Surface the error to the user, don't retry blindly. Typical causes:
  - `api_key invalid` — wrong player or game mixed up; re-check which key you should be using.
  - `not your turn` — wait for `is_my_turn` to return `my_turn=True`.
  - `game not found` — the user probably mistyped the id; confirm and retry.
  - Action rejected during `validate_actions` — drop that action, explain why, ask the user how to adjust.
- If the MCP connection itself dies mid-session (tool call raises / times out), say so and ask the user to restart the server. Do not fabricate state to fill the gap.
- If `submit_actions` partially succeeds (some actions accepted, some rejected), the response lists both — show the user which were dropped and why.
- Never retry `submit_actions` on a turn where the resolve-turn flag came back true. The turn has already moved on; re-querying `get_game_state` is the right next step.

## End of session / game completion

When `get_game_info` or `is_my_turn` shows `status == "ended"`:

1. Announce the outcome: winner, victory_type, final scores.
2. Render the final map once.
3. Offer a short post-mortem using `get_turn_history` if the user wants it, or a fresh `create_game` if they want to play again.

## Cheat sheet — MCP tool inventory

- **Lifecycle**: `create_game`, `join_game`, `get_game_info`, `whoami`
- **Gameplay**: `get_game_state`, `submit_actions`, `validate_actions`, `is_my_turn`
- **Analysis**: `analyze_territory`, `evaluate_military_position`, `find_resource_opportunities`, `calculate_distances`
- **Memory**: `write_scratchpad`, `read_scratchpad`, `write_strategic_goals`, `read_strategic_goals`, `write_opponent_model`, `read_opponent_models`, `write_turn_notes`, `read_turn_notes`
- **History**: `get_turn_history`, `get_turn_snapshot`
- **Rendering**: `render_map_ascii`, `render_map_svg`, `render_map_image`

All tools except `get_game_info` and `create_game`/`join_game` require an `api_key` that you got from `create_game` or `join_game`.
