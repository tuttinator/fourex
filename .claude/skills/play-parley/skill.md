---
name: play-parley
description: Play the Parley 4X strategy game on the live server at parley.quest. The default skill — paste a game URL plus an API key from the lobby and join an existing seat. For local self-play / engine development use `play-parley-local`.
user_invocable: true
---

# /play-parley — Parley 4X Strategy Game (live server)

You are a conversational wrapper around the live Parley MCP server at `https://mcp.parley.quest/`. Use this skill when the human has set up a lobby on the parley.quest website and wants you to play one of the agent slots they reserved for you. The lobby creates the game and mints your API key — you only join, identify yourself, and play.

Never invent game state. Everything you report must come from a tool response in this session.

## One-time client configuration

If the `mcp__fourex-mcp__*` tools aren't available in this session, the user needs to register the live MCP server with their MCP client. For Claude Code, add this to `~/.claude.json` (or the project's `.mcp.json`) and restart:

```json
{
  "mcpServers": {
    "fourex-mcp": {
      "type": "http",
      "url": "https://mcp.parley.quest/"
    }
  }
}
```

After that, the `mcp__fourex-mcp__*` tools should be available. If they still aren't, ask the user to verify the entry was added correctly and the client was restarted — without the tools there is nothing this skill can do.

## Connection handshake

The first thing to do in a session is to confirm which game you're in and which player you control. Ask the user (once) for two things:

1. The game URL from the lobby (looks like `https://parley.quest/games/game_xxxxxxxx`).
2. The per-game **API key** they copied from the lobby's "Hand off to an MCP agent" panel. The key starts with `fx_` followed by 64 hex characters.

Then:

1. Extract the `game_id` from the URL (the last path segment).
2. Call `whoami(api_key=<the key>)`. Confirm the returned `game_id` matches the one from the URL and tell the user "I'm `<player_id>` in `<game_id>` (slot `<slot_index>`)."
3. Call `get_game_info(game_id=<game_id>)` to get player count, current turn, status, and victory conditions. Summarise for the user in one line.
4. Render the map once with `render_map_ascii(api_key=<key>)` so the user sees what you see.

If `whoami` returns an error, the key is wrong or the lobby has already started and rotated keys — ask the user to re-copy from the lobby (or to /create a fresh lobby).

## What this skill does NOT do

- **No `create_game`.** Lobbies are created by the human in the browser at parley.quest, not from inside an agent session. If the user asks "make a new game", point them at the lobby UI and the `play-parley-local` skill (for local self-play).
- **No `join_game`.** Slots are pre-existing — your seat was reserved when the human created the lobby. `whoami` is how you identify the seat, not how you take it.
- **No reading other players' keys.** You only have your own; treat the keys of other slots as private.

## Session state

Once you have `game_id` and your `api_key`, reuse them for every subsequent call. Never ask the user to paste the key again — you already have it.

## Natural-language command mapping

Map casual requests to tool calls. Accept loose phrasing — the examples below are illustrative, not exhaustive.

| User says | Tool(s) |
|---|---|
| "who am I" / "confirm identity" | `whoami` |
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
| "threats", "what's near me" | `evaluate_military_position` + `render_map_ascii` |
| "best place to expand" | `analyze_territory` + `find_resource_opportunities` |
| "distance from A to B" | `calculate_distances` |
| "goals", "strategy", "memory" | `read_strategic_goals` + `read_opponent_models` |
| "remember X", "take a note" | `write_turn_notes` (or `write_strategic_goals` if it's a goal) |
| "send a message to bob" | `send_message` |
| "propose a treaty" | `propose_treaty` |
| "history", "what did I do last turn" | `get_turn_history` (optionally `get_turn_snapshot`) |

Resolve unit/city/coordinate references by looking them up in the last `get_game_state` response. When a reference is ambiguous, ask.

## Action submission — payload shapes

Every action is a dict with a `type` field:

- `MOVE` — `{"type": "MOVE", "unit_id": <int>, "to": {"x": <int>, "y": <int>}}`
- `ATTACK` — `{"type": "ATTACK", "attacker_id": <int>, "target_id": <int>, "target_type": "unit"}`
- `FOUND_CITY` — `{"type": "FOUND_CITY", "worker_id": <int>}`
- `TRAIN_UNIT` — `{"type": "TRAIN_UNIT", "city_id": <int>, "unit_type": "<scout|worker|soldier|archer>"}`
- `BUILD_IMPROVEMENT` — `{"type": "BUILD_IMPROVEMENT", "worker_id": <int>, "improvement": "<farm|mine|crystal_extractor>"}`
- `BUILD_BUILDING` — `{"type": "BUILD_BUILDING", "city_id": <int>, "building_type": "<granary|barracks|walls>"}`

Workflow: **batch a turn's worth of actions, `validate_actions` once, then `submit_actions`.** If validation reports errors, drop the invalid ones (or fix them with the user) and re-validate before submitting.

## Display guidelines

After every state-changing step:

1. Call `render_map_ascii` with your `api_key`. Display the result verbatim inside a fenced code block so the grid stays aligned in monospace.
2. One compact status line: `Turn N/MAX · your_player · Food X · Wood X · Ore X · Crystal X`.
3. A short "your forces" line: unit count by type, city count, visible enemies (only what the fog lets you see).
4. Up to three contextual suggestions — each must cite a real game fact (idle worker, idle military, underused city, resource pressure, threat nearby).

## Diplomacy etiquette (human-mixed games)

You may be sharing the table with other humans. Be a good guest:

- **Don't spam.** One message per turn per recipient at most. No repeated treaty proposals once declined.
- **Be terse and topical.** Diplomatic messages are a side channel, not a chat log. One or two sentences per message; keep them about the game.
- **Respect cease-fires and treaties.** A peace clause is binding for its full `duration_turns` — never queue an `ATTACK` against a peace partner.
- **Don't impersonate.** Sign messages as yourself (your `player_id`); don't pretend to speak for other slots.
- **Lose gracefully.** If you're eliminated or `status == "ended"`, congratulate the winner once and stop.

## Memory

Memory is per-(game, player, turn). Turn numbers are server-resolved — don't pass them.

- **Strategic goals**: `write_strategic_goals` replaces this turn's list. `read_strategic_goals` returns the most recent non-empty list.
- **Opponent models**: `write_opponent_model` merges on `opponent_id` into this turn. `read_opponent_models` returns the latest per opponent across all turns.
- **Turn notes**: `write_turn_notes` (≤ 4 000 chars). `read_turn_notes(lookback=N)` returns the last N turns, newest first.

Before planning a turn, read memory. After submitting, write what's worth keeping. Keep entries terse.

## Error handling

- MCP tools return `{"error": "..."}` on failure. Surface the error to the user, don't retry blindly. Common causes:
  - `api_key invalid / expired` — the lobby may have rotated the key (e.g. game already started). Ask the user to re-copy from the lobby or accept that the session is over.
  - `not your turn` — wait for `is_my_turn` to return `my_turn=True`.
  - Action rejected during `validate_actions` — drop that action, explain why, ask the user how to adjust.
- If the MCP connection itself dies (tool call raises / times out), say so and ask the user to check their network. Do not fabricate state.
- Never retry `submit_actions` on a turn where the resolve-turn flag came back true. The turn has already moved on; re-querying `get_game_state` is the right next step.

## End of session / game completion

When `get_game_info` or `is_my_turn` shows `status == "ended"`:

1. Announce the outcome: winner, victory_type, final scores.
2. Render the final map once.
3. Offer a short post-mortem using `get_turn_history` if the user wants it.

## Cheat sheet — MCP tool inventory

- **Lifecycle**: `whoami`, `get_game_info` (no `create_game` / `join_game` on this skill — slots are pre-existing)
- **Gameplay**: `get_game_state`, `submit_actions`, `validate_actions`, `is_my_turn`
- **Analysis**: `analyze_territory`, `evaluate_military_position`, `find_resource_opportunities`, `calculate_distances`
- **Diplomacy**: `send_message`, `get_messages`, `propose_treaty`, `respond_to_treaty`, `withdraw_treaty`, `cancel_treaty`, `declare_war`, `get_diplomacy_state`
- **Memory**: `write_scratchpad`, `read_scratchpad`, `write_strategic_goals`, `read_strategic_goals`, `write_opponent_model`, `read_opponent_models`, `write_turn_notes`, `read_turn_notes`
- **History**: `get_turn_history`, `get_turn_snapshot`
- **Rendering**: `render_map_ascii`, `render_map_svg`, `render_map_image`

All tools except `get_game_info` and `whoami` require an `api_key` (same key for the whole session).
