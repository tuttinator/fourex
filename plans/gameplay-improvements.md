# Plan: Gameplay Improvements — Movement, Stacking, Queued Orders, Rules Reference

> Source PRD: `plans/gameplay-improvements-prd.md`

## Architectural decisions

Durable decisions that apply across all phases:

- **REST routes**:
  - `GET /api/v1/rules` — canonical rules reference payload (unit stats, building costs, improvement effects, terrain entry costs, combat formulas, stacking rules, order cancellation conditions, `schema_version`).
  - `GET /api/v1/games/{game_id}/valid-moves` — extended to return `{tile, cost, path: list[Coord]}` per reachable tile.
- **MCP tools**:
  - `get_rules_reference` — read-only wrapper over `/api/v1/rules`.
- **Schema changes (Alembic migrations required)**:
  - `Tile.unit_id: int | None` → `Tile.unit_ids: list[int]` (ordered, cap 5, enforced engine-side).
  - `Unit.orders_queue: list[QueuedOrder]` — server-persisted queue of multi-turn orders.
  - `Unit.automation: UnitAutomation | None` — automation mode (initially `AutoImprove` or null).
- **Key models**:
  - `QueuedOrder` — discriminated union by `type` (`"move"` with `destination: Coord`; extensible).
  - `UnitAutomation` — string enum, initial member `AutoImprove`.
  - `Action` discriminated union gains: `QueueOrderAction`, `CancelOrderAction`, `SetAutomationAction`, `ClearAutomationAction`. `AttackAction` gains optional `target_tile: Coord` alongside existing `target_id`.
- **Movement model**: server-side Dijkstra over per-tile entry costs from the rules reference. Mountains and water impassable for land units. Movement cost deducted = sum of entry costs along the chosen path. Path returned with valid-moves response so the client can preview.
- **Combat**: defenders on a friendly city tile receive +25% defence. When `target_tile` is used on a stacked enemy tile, the engine picks a random defender via the game's seeded RNG so replays stay deterministic.
- **Stacking cap**: 5 units per tile regardless of owner, enforced at validation and move execution.
- **Frontend source-of-truth**: valid-moves and valid-attacks come exclusively from server responses — no client-side duplication of movement or attack-range rules.
- **Hotkeys**: `N` cycles idle units, `B` cycles idle cities. "Idle unit" = `moves_left > 0 AND orders_queue empty AND automation is None`. "Idle city" = no production queued.
- **Determinism**: all new randomness routes through the existing seeded RNG threaded through `resolve_turn`.

---

## Phase 1: Rules reference (REST + MCP)

**User stories**: 1, 2, 3, 4

### What to build

A canonical rules reference, exposed as both a REST endpoint (`GET /api/v1/rules`) and an MCP tool (`get_rules_reference`). The payload contains every game constant an agent or UI consumer needs: unit stats (cost, HP, attack, attack range, movement, sight, special rules), building stats (cost, effect, prerequisites), improvement stats (cost, terrain compatibility, yield), terrain entry costs, combat formulas, stacking rules, queued-order cancellation conditions, and a `schema_version` field. The engine and frontend both consume this payload so constants live in one place. Frontend surfaces a simple rules panel reading from the endpoint.

### Acceptance criteria

- [ ] `GET /api/v1/rules` returns a structured payload covering all categories listed above.
- [ ] MCP tool `get_rules_reference` returns the same payload, tagged read-only.
- [ ] Payload includes `schema_version`.
- [ ] Engine-side constants (`UNIT_STATS`, `BUILDING_STATS`, `IMPROVEMENT_STATS`, terrain cost table) are sourced from the same single module the endpoint reads from.
- [ ] Frontend rules panel renders unit and building stats from the endpoint.
- [ ] Tests cover: payload shape snapshot, MCP tool parity with REST, schema version present.

---

## Phase 2: Pathfinding movement + valid-move display fix

**User stories**: 5, 6, 7, 8, 11, 12, 13, 14

### What to build

Replace Manhattan-distance movement with true pathfinding over per-tile entry costs. The engine computes the optimal path via Dijkstra using the terrain cost table (plains 1, forest 2, hills 2, mountain impassable, water impassable for land units — exact table published via the rules reference). Movement cost deducted is the sum of entry costs along the path, not the Manhattan distance. `valid-moves` returns each reachable tile with its cumulative cost and the chosen path. The frontend drops any client-side movement-rule duplication, consumes the server response directly, and draws the path preview as a connected chain of highlighted tiles when the player hovers a destination. Queued destinations (from the existing client-side move buffer) are excluded from the reachable set for the same unit.

### Acceptance criteria

- [ ] Move validation and execution use path-cost, not Manhattan distance.
- [ ] Mountain tiles are impassable; water is impassable for land units.
- [ ] `valid-moves` response includes `{tile, cost, path}` per reachable tile.
- [ ] Frontend reachable-tile highlights match server `valid-moves` exactly.
- [ ] Hovering a reachable tile draws the planned path on the map.
- [ ] Attack-range highlights match server `valid-attacks` exactly.
- [ ] Previewed path excludes tiles already queued as destinations for the same unit.
- [ ] Tests: path cost across mixed terrain; mountain blocks path; forest entry cost applied; existing single-turn move regression passes.

---

## Phase 3: Friendly unit stacking (engine + validation + combat)

**User stories**: 9, 15, 16, 17, 18, 19, 20, 21, 22

### What to build

Migrate tile occupancy from a single `unit_id` to an ordered `unit_ids: list[int]` with a cap of 5. The cap applies to any owner — friendly or enemy — so the rule is symmetric. Move validation accepts a destination that already holds friendly units as long as the cap is not exceeded; rejects at-cap destinations regardless of owner. `AttackAction` gains an optional `target_tile` field; when supplied against a stacked enemy tile the engine picks a random defender using the game's seeded RNG. `target_id` remains supported for deterministic targeting. Units defending on a friendly city tile receive a +25% defence bonus, applied in combat resolution and documented in the rules reference. No dedicated stacking UI in this phase — demoable via API, validation, and combat tests.

### Acceptance criteria

- [ ] `Tile.unit_ids: list[int]` replaces `Tile.unit_id` in models, database, and redaction.
- [ ] Alembic migration converts existing data.
- [ ] Up to 5 units may occupy a single tile; the 6th move is rejected.
- [ ] `validate_actions` accepts moves onto friendly-occupied tiles under the cap.
- [ ] `AttackAction.target_tile` picks a random defender via seeded RNG; same seed + actions produces identical defender choice across replays.
- [ ] `AttackAction.target_id` still resolves against a specific stacked unit.
- [ ] Units on a friendly city tile take 25% less damage when attacked.
- [ ] Rules reference payload documents stack cap and fortification bonus.
- [ ] Tests: stack cap enforcement; friendly pass-through; random defender determinism; fortification damage reduction; redacted state exposes only visible stacked units.

---

## Phase 4: Stacked-tile UI

**User stories**: 23, 24, 25, 26

### What to build

Make stacked tiles usable in the frontend. Clicking a tile that contains a city plus one or more units, or 2+ units alone, opens a selector popover listing each entity with its type, HP, and (for units) moves remaining. A keyboard shortcut cycles selection within the current stack. Tiles with 2+ selectable entities show a small badge indicating the count.

### Acceptance criteria

- [ ] Clicking a multi-entity tile opens a selector popover.
- [ ] Popover lists each unit with type, HP, moves remaining, and the city if present.
- [ ] Selecting an entry in the popover sets the active selection and closes the popover.
- [ ] A keyboard shortcut cycles selection through entities on the currently-selected tile.
- [ ] Tiles with 2+ selectable entities render a stack-count badge.
- [ ] Single-entity tiles behave exactly as before (no popover).

---

## Phase 5: Queued multi-turn unit moves

**User stories**: 10, 27, 28, 29, 30, 31, 32, 33, 34, 35

### What to build

Persist unit orders server-side. `Unit` gains an `orders_queue` field holding `QueuedOrder` entries. Players may issue a move order to any reachable destination — including tiles further than the current turn's movement budget. At the start of each turn, before action submission, the engine resumes the head of each unit's queue: advances the unit along the remaining path using that turn's budget, consuming moves until the budget is spent or the destination is reached. Cancellation conditions checked at resume time and between steps: (a) any enemy unit newly inside the moving unit's sight radius, (b) next step blocked by a terrain change or a stacked tile at cap, (c) unit took damage during the previous turn's combat resolution. Cancellations emit game events surfaced to the player and visible via `get_game_state`. New action types `QueueOrderAction` and `CancelOrderAction` are added to the discriminated union. The frontend draws the queued path on the map for selected units and offers a single-click cancel.

### Acceptance criteria

- [ ] `Unit.orders_queue` persists via Alembic migration.
- [ ] `QueueOrderAction` accepts a destination; validation rejects unreachable destinations (impassable terrain, no path).
- [ ] `CancelOrderAction` clears the queue for a specified unit.
- [ ] Engine advances queued moves at the start of each turn using that turn's movement budget.
- [ ] Queue cancels automatically on any of: newly visible enemy in sight, obstructed next step, unit attacked in previous turn.
- [ ] Cancellation events appear in the game event stream and in `get_game_state`.
- [ ] Frontend renders the queued path for the selected unit.
- [ ] Frontend offers a one-click cancel for a unit's queued order.
- [ ] Orders persist across reload / reconnect.
- [ ] Tests: multi-turn completion; cancel on enemy sight; cancel on obstruction; cancel on attack; persistence; replay determinism.

---

## Phase 6: Worker auto-improve automation

**User stories**: 36, 37, 38, 39, 40, 41, 42

### What to build

Add an "auto-improve" mode for workers. `Unit.automation` is persisted server-side and can be `AutoImprove` or null. New actions `SetAutomationAction` and `ClearAutomationAction` toggle the mode. At each turn's resume phase, for every auto-improve worker without an active target, the engine selects the nearest unimproved own-territory tile, enqueues a move order to it (reusing the Phase 5 queue machinery), and on arrival issues the terrain-appropriate improvement build. Automation cancels if an enemy unit is within Chebyshev distance 1 of the worker, or if the player submits any manual action for that worker. Cancellations emit events. Automated workers render a distinct visual indicator.

### Acceptance criteria

- [ ] `Unit.automation` persists via Alembic migration.
- [ ] `SetAutomationAction` activates `AutoImprove`; `ClearAutomationAction` clears it.
- [ ] Engine auto-targets the nearest unimproved own-territory tile and routes the worker there across turns.
- [ ] Worker builds the terrain-appropriate improvement on arrival.
- [ ] Worker picks a new target after completing the previous improvement.
- [ ] Automation cancels when an enemy unit is within Chebyshev distance 1.
- [ ] Automation cancels when the player submits a manual action for the worker.
- [ ] Cancellation events appear in the game event stream.
- [ ] Frontend shows an automation indicator on automated workers.
- [ ] Tests: end-to-end auto-improve over multiple turns; enemy-adjacency cancel; manual-override cancel; no-target-available behaviour.

---

## Phase 7: Idle unit & city cycling

**User stories**: 43, 44, 45, 46, 47, 48

### What to build

Surface idle entities to the player. "Idle unit" is defined as `owner == current_player AND moves_left > 0 AND orders_queue empty AND automation is None`. "Idle city" is `owner == current_player AND production queue empty`. The idle sets are computed client-side from the already-redacted game state. Hotkeys `N` and `B` cycle through idle units and idle cities respectively, scrolling the map to the entity and selecting it. HUD buttons mirror the hotkeys. Counters next to each button show how many idle entities remain, reaching zero when the player has addressed everything — a clear "ready to end turn" signal.

### Acceptance criteria

- [ ] `N` cycles to the next idle unit; wraps around.
- [ ] `B` cycles to the next idle city; wraps around.
- [ ] HUD buttons trigger the same cycling as the hotkeys.
- [ ] Units with a queued order or `AutoImprove` automation are excluded from the idle cycle.
- [ ] Cities with a production queued are excluded from the idle cycle.
- [ ] Idle counters reflect the current counts and update live as orders are issued.
- [ ] Counters reach zero when nothing is idle.
- [ ] Tests: idle definitions; exclusion of queued/automated units; counter updates after order submission.
