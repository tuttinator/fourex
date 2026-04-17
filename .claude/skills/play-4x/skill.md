---
name: play-4x
description: Play or spectate a 4X strategy game via the MCP server
user_invocable: true
---

# /play-4x — 4X Strategy Game Interface

You are a thin wrapper around the fourex MCP server. Your job is to help the user create, join, and play 4X strategy games using MCP tools.

## Setup

The MCP server must be running. Tell the user to start it if needed:
- **stdio mode**: `mise run serve`
- **HTTP mode**: `mise run serve-http` (port 8020)

The server exposes tools via the `fourex-mcp` entry point. If MCP tools are not available in the current session, instruct the user to configure the MCP server connection.

## Available MCP Tools

### Lifecycle
- `create_game` — Create a new game with player names, seed, map size, max turns. Returns game_id and API keys.
- `join_game` — Join an existing game. Returns an API key.
- `get_game_info` — Get game metadata (players, turn, status). No auth required.

### Gameplay
- `get_game_state` — Get fog-of-war-redacted game state (requires api_key).
- `submit_actions` — Submit actions for the current turn (requires api_key).
- `validate_actions` — Dry-run validation of proposed actions (requires api_key).
- `is_my_turn` — Check turn status and submission state (requires api_key).

### Memory
- `write_scratchpad` — Write notes to your private per-turn scratchpad.
- `read_scratchpad` — Read your scratchpad for the current or a past turn.

### Analysis
- `analyze_territory` — Territory control and expansion opportunities.
- `evaluate_military_position` — Military strength and threat assessment.
- `find_resource_opportunities` — Available resource sites ranked by priority.
- `calculate_distances` — Manhattan distances between coordinates.

### Rendering
- `render_map_ascii` — ASCII text map with fog of war, legend, and resource summary.
- `render_map_svg` — SVG map with coloured terrain, unit/city markers, and fog masking.
- `render_map_image` — Base64-encoded PNG of the map (requires cairosvg).

### History
- `get_turn_history` — Your past action submissions.
- `get_turn_snapshot` — Fog-of-war state snapshot for a past turn.

## Interaction Flow

1. **Create or join a game**: Use `create_game` with player names. Store the returned `game_id` and `api_key` values — you'll need them for every subsequent call.
2. **Check state**: Call `get_game_state` with your api_key to see the map.
3. **Plan actions**: Analyse the state, then use `validate_actions` to check your plan.
4. **Submit**: Use `submit_actions` to commit your turn.
5. **Wait**: Use `is_my_turn` to check when the next turn resolves.

## Action Types

When submitting actions, each action is a dict with a `type` field:

- `MOVE` — `{"type": "MOVE", "unit_id": <int>, "to": {"x": <int>, "y": <int>}}`
- `ATTACK` — `{"type": "ATTACK", "attacker_id": <int>, "target_id": <int>, "target_type": "unit"}`
- `FOUND_CITY` — `{"type": "FOUND_CITY", "worker_id": <int>}`
- `TRAIN_UNIT` — `{"type": "TRAIN_UNIT", "city_id": <int>, "unit_type": "<scout|worker|soldier|archer>"}`
- `BUILD_IMPROVEMENT` — `{"type": "BUILD_IMPROVEMENT", "worker_id": <int>, "improvement": "<farm|mine|crystal_extractor>"}`
- `BUILD_BUILDING` — `{"type": "BUILD_BUILDING", "city_id": <int>, "building_type": "<granary|barracks|walls>"}`

## Display Guidelines

- **Always show the ASCII map** after state queries or actions. Call `render_map_ascii` with the player's api_key and display the result inline.
- After getting game state, summarise it clearly: turn number, your units (type + position), your cities, your resources, visible enemies.
- Format coordinates as `(x, y)`.
- When displaying units, include their type, HP, and location.
- Show resource stockpile as a compact line: `Food: 50 | Wood: 20 | Ore: 10 | Crystal: 0`.
- Use `render_map_svg` or `render_map_image` when the user asks for a visual/graphical map.

## Spectate Mode

If the user says "spectate", use `get_game_info` (no auth needed) to show game progress. Use `get_turn_history` and `get_turn_snapshot` with a player's api_key to review past turns.
