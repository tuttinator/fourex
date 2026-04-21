# PRD: Gameplay Improvements — Movement, Stacking, Queued Orders, Rules Reference

## Problem Statement

Recent playtesting surfaced a cluster of friction points that hurt both human and AI players:

- **Terrain feels cumbersome.** Movement uses Manhattan-distance teleport ignoring intermediate terrain, yet a single-tile move into a forest costs 2. The rules are inconsistent, and the map regularly produces dead-end pockets where a unit is surrounded by water, mountain, and friendly units with no legal move — purely a UI-level gridlock, not a tactical one.
- **No friendly unit stacking.** Two friendly units cannot share a tile, so regrouping, garrisoning, or moving through your own army is impossible. This drove most of the playtest's gridlock.
- **No multi-turn orders.** Every unit must be re-issued an order every turn. Long marches across the map and repeated worker improvements are tedious for humans and expensive in turns/tokens for agents.
- **No idle-entity cycling.** Players cannot easily find the units or cities still awaiting orders, so turns end with idle units that were simply missed.
- **Stacked-tile UI is clumsy.** When a friendly unit is on a city tile, clicking the tile is ambiguous — the player cannot reliably pick the city vs the unit.
- **Frontend valid-move display has bugs.** The highlighted reachable/attackable tiles sometimes misrepresent what the server will actually accept.
- **Agents must read the source to play well.** There is no canonical endpoint exposing unit stats, building costs, terrain costs, or combat formulas. MCP agents are at a significant disadvantage versus anyone who can open `rules.py`.

## Solution

A single coordinated pass across backend, API, MCP, and frontend:

- Replace the movement model with true pathfinding over per-tile entry costs (mountains remain impassable). The frontend shows the planned path when previewing a move.
- Allow up to 5 friendly units to share a tile. Enemy stacks may also form. Ranged/melee attacks on a stacked enemy tile let the engine pick a random defender; `target_id` remains available for deterministic targeting. Units defending on a friendly city tile receive a fortification defence bonus.
- Persist unit orders server-side. A player may queue a multi-turn move to any reachable destination; the engine resumes the path each turn. Orders auto-cancel on (a) newly visible enemy, (b) obstruction, (c) the unit being attacked.
- Add a worker "auto-improve" automation mode. The worker picks the nearest unimproved tile inside friendly territory, moves there, builds the terrain-appropriate improvement, and repeats — across turns — until cancelled or an enemy is adjacent.
- Add `N` (next idle unit) and `B` (next idle city) hotkeys plus matching UI buttons. Automated workers and units with queued orders do not count as idle.
- When a tile has both a city and one or more units, clicking opens a selector so the player can pick which entity to inspect/command. Support keyboard cycling within the stack.
- Fix the valid-move and valid-attack highlight logic so it matches server validation exactly, including for stacked tiles and queued-move previews.
- Add a canonical rules-reference REST endpoint and MCP tool that returns every unit stat, building cost, improvement effect, terrain cost, and combat formula in one structured payload.

## User Stories

### Rules reference

1. As an MCP agent, I want to fetch canonical game mechanics through an MCP tool, so that I can play the game without reading source code.
2. As an MCP agent, I want unit stats, building costs, improvement effects, terrain entry costs, and combat formulas in one structured response, so that I can parse the ruleset in a single call.
3. As a human player, I want to see unit and building stats in the UI, so that I understand my options without guessing.
4. As a developer, I want a single authoritative rules source, so that the engine, the API, and the UI never disagree about costs or ranges.

### Movement and terrain

5. As a player, I want unit movement to cost the terrain's entry cost per tile traversed, so that movement feels predictable and consistent.
6. As a player, I want mountains to remain impassable, so that the map has meaningful geographic structure.
7. As a player, I want to see the planned path highlighted when I hover a destination, so that I can verify the route before committing.
8. As an agent, I want deterministic per-tile movement costs exposed through the rules reference, so that I can compute optimal paths.
9. As a player, I want a unit surrounded by impassable tiles and friendly units to still have somewhere to move (via stacking), so that I am not gridlocked by the map.
10. As a player, I want queued moves that exceed this turn's movement budget to resume next turn, so that long marches don't require re-issuing orders.

### Valid-move display

11. As a player, I want the reachable-tile highlights to match exactly what the server will accept, so that I don't submit an invalid move.
12. As a player, I want the highlighted attack range to reflect my unit's actual range and line-of-sight rules, so that I don't miss legitimate targets.
13. As a player, I want the highlights to update immediately when I queue a move, so that the displayed options reflect my in-progress plan.
14. As a player, I want queued destinations to not be re-offered as valid moves for the same unit, so that the display stays coherent.

### Friendly unit stacking

15. As a player, I want to move a unit onto a tile already occupied by my own unit, so that I can regroup forces.
16. As a player, I want up to 5 friendly units to share a tile, so that I can form a concentrated army.
17. As a player, I want the engine to block a friendly move onto a tile already at the 5-unit cap, so that the cap is enforced consistently.
18. As a player, I want units defending on a friendly city tile to receive a fortification defence bonus, so that cities are meaningfully defensible.
19. As an agent, I want `validate_actions` to accept friendly co-location, so that my plans don't fail for stacking reasons.
20. As an attacker, I want to target a stacked enemy tile and have the engine pick a random defender, so that I don't need to enumerate defenders.
21. As an agent, I want to still target a specific enemy by `target_id`, so that I retain deterministic tactical control.
22. As a player, I want enemy units to also be allowed to stack (subject to the same cap), so that the rule is symmetric.

### Stacked-tile UI

23. As a player, I want clicking a tile that contains both a city and one or more units to open a selector, so that I can pick which entity to inspect.
24. As a player, I want to cycle through the units on a stacked tile with a keyboard shortcut, so that I can issue orders to each in turn.
25. As a player, I want a visual indicator on stacked tiles showing the count of units present, so that I can see stacks at a glance.
26. As a player, I want the stack selector to show each unit's type and HP, so that I can pick the right one quickly.

### Queued multi-turn orders

27. As a player, I want to issue a move order to a tile further than my unit's remaining moves, so that I don't have to micromanage long marches.
28. As a player, I want the engine to advance queued moves automatically at the start of each turn, so that my plan progresses without re-issuing.
29. As a player, I want a queued move to cancel automatically when a newly visible enemy enters my unit's sight, so that I don't walk into an ambush.
30. As a player, I want a queued move to cancel automatically when the next step becomes obstructed, so that I can replan.
31. As a player, I want a queued move to cancel automatically when my unit is attacked, so that I can respond.
32. As a player, I want the queued path drawn on the map for selected units, so that I can verify the plan.
33. As a player, I want queued orders to persist across sessions, so that I don't lose my plan if I reload.
34. As a player, I want to cancel a queued order with a single click, so that I can regain manual control.
35. As an agent, I want to submit a queued destination via the API, so that I can plan multi-turn campaigns without polling every turn.

### Worker automation

36. As a player, I want to toggle a worker to "auto-improve" mode, so that I don't have to manage each worker every turn.
37. As a player, I want the auto-improve worker to pick the nearest unimproved tile inside friendly territory, so that it stays productive without manual targeting.
38. As a player, I want auto-improve to move the worker across multiple turns to reach the selected tile, so that it doesn't need babysitting.
39. As a player, I want auto-improve to build the terrain-appropriate improvement on arrival, so that the worker acts without further input.
40. As a player, I want auto-improve to cancel when an enemy unit is adjacent to the worker, so that my worker doesn't get killed.
41. As a player, I want auto-improve to cancel with a single click or a manual order, so that I can redirect the worker.
42. As a player, I want a visual indicator on automated workers, so that I can distinguish them from idle workers at a glance.

### Idle cycling

43. As a player, I want to press `N` to cycle to the next unit with moves remaining and no queued order or automation, so that I don't miss units awaiting orders.
44. As a player, I want to press `B` to cycle to the next city with nothing in its production queue, so that I don't skip idle cities.
45. As a player, I want UI buttons that mirror the `N` and `B` hotkeys, so that mouse-only players have the same control.
46. As a player, I want automated workers and units with queued orders to be excluded from the idle cycle, so that the cycle only surfaces entities that need attention.
47. As a player, I want a counter showing how many idle units and cities remain, so that I know when my turn is truly done.
48. As a player, I want the idle counter to zero out when I've addressed everything, so that I have a clear "ready to end turn" signal.

## Implementation Decisions

### Rules reference

- New REST endpoint returning a single structured payload covering: unit stats (cost, HP, attack, attack range, movement, sight, special rules), building stats (cost, effect, prerequisites), improvement stats (cost, terrain compatibility, yield), terrain entry costs, combat formulas (damage calculation, fortification bonus, counter-attack rules), stacking rules, and queued-order cancellation conditions.
- New MCP tool wrapping the same payload, tagged read-only and safe for parallel calls.
- The rules reference is the single source of truth for constants; the engine and frontend both consume it rather than duplicating values.

### Movement and pathfinding

- `is_valid_move` and `execute_move` replaced with BFS/Dijkstra pathfinding over terrain entry costs.
- Terrain entry cost table: plains 1, forest 2, hills 2, water impassable (non-naval), mountain impassable, other terrain values published via the rules reference.
- Movement cost deducted is the sum of entry costs along the computed path, not Manhattan distance.
- Rivers and other future terrain types extend the table without engine changes.
- Path is computed server-side and the chosen path returned alongside `valid-moves` responses so the frontend can preview it.

### Unit stacking

- `Tile.unit_id: int | None` replaced with `Tile.unit_ids: list[int]` (ordered; max length 5).
- `Tile.city_id` unchanged — a tile still holds at most one city, and stacked units may share that tile.
- Stack cap of 5 applied per-tile regardless of owner (friendly or enemy).
- Movement validation rejects a move into a tile already at the cap.
- Fortification bonus: units on a friendly city tile receive +25% defence (applied in combat resolution, exposed via rules reference).
- `AttackAction` accepts either `target_id` (deterministic) or `target_tile` (engine picks a random valid defender on that tile using the game's seeded RNG so replays remain deterministic).
- Ranged attacks follow the same targeting rules; AOE is out of scope.

### Queued orders

- New `orders_queue: list[QueuedOrder]` field on `Unit`. Each `QueuedOrder` carries a type (move, auto-improve) and parameters (destination tile, etc.).
- Server resumes the head of the queue at the start of each turn before player action submission: advances the unit along the remaining path using that turn's movement budget, consuming moves until the budget is spent or the destination is reached.
- Cancellation conditions checked at resume time and between steps within a turn: (a) any enemy unit newly inside the moving unit's sight radius, (b) next step blocked by terrain change or tile at cap, (c) unit took damage during the previous turn's combat resolution.
- Cancellation emits a game event consumed by the UI to notify the player and by the agent via `get_game_state`.
- Queued orders persist in the database alongside unit state.
- `submit_actions` gains new action types for queueing and cancelling orders. Single-turn move actions remain supported unchanged.

### Worker automation

- New `automation: UnitAutomation | None` field on `Unit`. Initial enum values: `AutoImprove`.
- Set/cleared via a new action type in the discriminated union.
- At turn resolution, for each auto-improve worker: if no current target, select the nearest unimproved own-territory tile; enqueue a move order to it; on arrival, issue the terrain-appropriate improvement build; on completion, pick the next target.
- Cancellation condition: any enemy unit adjacent (Chebyshev distance 1) to the worker clears automation and emits an event.
- Manual action submission for the worker also clears automation.

### Idle cycling

- "Idle unit" definition: `owner == current_player AND moves_left > 0 AND orders_queue is empty AND automation is None`.
- "Idle city" definition: `owner == current_player AND production queue is empty`.
- Idle sets computed client-side from the redacted game state; no new API needed.
- Frontend hotkeys: `N` cycles idle units, `B` cycles idle cities. Both scroll the map to the entity and select it. Buttons in the HUD mirror the hotkeys and display remaining counts.

### Stacked-tile UI

- Clicking a tile containing 2+ selectable entities (city + units, or 2+ units) opens a popover listing each entity with its type, HP, and (for units) moves remaining.
- Keyboard shortcut cycles selection within the current tile's stack.
- Tiles with a stack show a small badge indicating unit count.

### Valid-move display fix

- Frontend reachable-tile and attack-range computations replaced with a thin wrapper over the server's `valid-moves` and `valid-attacks` responses; no client-side duplication of movement rules.
- Queued-move destinations excluded from the reachable set for the same unit (existing behaviour, corrected).
- Path preview rendered as a connected chain using the server-returned path.

## Out of Scope

- Economy rebalancing (resource yields, unit costs, starting resources). Playtest disparities were not clearly attributable to economic imbalance.
- Diplomacy and reputation systems (treaty teeth, trust scores, treacherous-attack penalties). Not yet justified.
- Enemy tactical AI improvements for stacks (how AI agents choose to stack or attack stacks is left to agents).
- Replay, undo, or branching of queued orders.
- Area-of-effect attacks against stacks.
- Naval movement rules and water-tile traversal.
- New automation modes beyond `AutoImprove` (e.g. auto-explore scout, sentry, patrol).
- New unit or building types.
- Map generation changes to reduce dead-end pockets (stacking alone resolves the observed gridlock).

## Further Notes

- Determinism must be preserved. Random defender selection on stacked-tile attacks uses the seeded RNG already threaded through `resolve_turn`, so replays with the same seed and actions remain identical.
- The rules reference endpoint should be versioned implicitly via the payload structure (include a `schema_version` field) so agents can detect breaking changes.
- Server-side order persistence is a schema change — an Alembic migration is required for the new `Unit.orders_queue` and `Unit.automation` fields and for the `Tile.unit_ids` replacement.
- Frontend-side, queued-move action tracking currently lives in a client-only `QueuedAction[]` buffer. With server persistence landing, that buffer becomes a thin cache over the server state and should no longer be the source of truth for multi-turn orders.
- Worker automation cancellation on enemy adjacency intentionally uses Chebyshev distance 1 rather than sight range, so workers retreat only from immediate threats rather than distant scouts.
- The fortification bonus is a simple +25% defence multiplier to keep the first iteration tractable; a richer fortification system (turns-to-entrench, terrain-based bonuses) is deferred.
