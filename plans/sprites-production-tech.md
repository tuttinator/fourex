# Plan: Visual Polish, Multi-Turn Production, and a Tech Tree

> Source PRD: `plans/sprites-production-tech-prd.md`

## Architectural decisions

Durable decisions that apply across all phases:

- **Asset pipeline**
  - A single CC0/CC-BY sprite atlas (Kenney.nl-tier or equivalent) lives under `frontend/public/sprites/`.
  - `ATTRIBUTION.md` + the pack's `LICENSE.txt` sit alongside the atlas so licence compliance is self-evident.
  - The atlas loads once at Pixi app init via `Assets.load`; no per-tile image fetches.
  - A sprite-resolver module maps `(enum, variant) → sprite_id → Pixi.Texture`, keyed off the existing `Terrain` / `UnitType` / `BuildingType` / `Resource` / improvement enums rather than string literals — adding a new enum member is a one-line data change.
  - Per-player identification is achieved via PixiJS `tint` or an outline overlay sprite, not via per-player base art.
  - No animations, tickers, or tweens are introduced by this initiative.
- **Schema**
  - `City.build_queue` changes type from `BuildJob | None` to `list[BuildJob]` (index 0 = active).
  - `BuildJob` keeps its existing shape (`type`, `target`, `progress`, `total_cost`); no new fields required.
  - `Resource` enum gains `SCIENCE`; `ResourceBag` gains a `science` field.
  - `GameState` gains `research: dict[PlayerId, ResearchState]` where `ResearchState = {completed: set[TechId], active: TechId | None, progress: int}`.
  - `UNIT_STATS` and `BUILDING_STATS` each gain an optional `required_tech: TechId | None` field.
  - A module-level `TECH_TREE: dict[TechId, Tech]` defines the static graph; techs carry `cost_science`, `requires`, `unlocks_units`, `unlocks_buildings`.
  - Starter techs (empty `requires`) are pre-populated in `ResearchState.completed` at game creation.
- **Key models**
  - `BuildJob` is the unit-of-work for production. `TrainUnitAction` and `BuildBuildingAction` become thin wrappers that enqueue one; the instant-resolution path is deleted.
  - `ResearchState` is the unit-of-work for research, one per player per game.
  - `Tech` is a static data record; tech state lives in `ResearchState`.
- **Actions** (discriminated-union additions)
  - `SetCityProductionAction(city_id, item_spec)` — append to queue.
  - `CancelCityProductionAction(city_id, queue_index)` — remove entry (index 0 forfeits progress).
  - `ReorderCityQueueAction(city_id, new_order)` — permute queue.
  - `SetActiveResearchAction(tech_id)` — set the player's active tech; mid-research switch preserves `progress`.
- **Turn resolution order**
  - Cities iterate in sorted `city_id` order during production advancement.
  - Players iterate in sorted `player_id` order during research advancement.
  - No RNG in production or research; deterministic-engine invariant `same seed + same actions ⇒ identical state` is preserved.
- **Fog-of-war**
  - `build_queue` contents are elided for non-owners in `redact_state`.
  - Each player's `ResearchState` is visible only to itself.
  - Sprite render layer keys off redacted state exactly as today.
- **Events** (WebSocket)
  - `city.production_completed` — payload `{city_id, item_spec, turn}`; scoped to city owner (and optionally players with visibility on the city).
  - `research.completed` — payload `{player_id, tech_id, turn}`; scoped to the researching player's connection only.
- **MCP parity**
  - Every new action type is reachable via an MCP tool (`set_city_production`, `cancel_city_production`, `reorder_city_queue`, `set_active_research`).
  - Read-only tools: `get_tech_tree` returns the full static graph plus caller's `ResearchState`.
  - Existing `train_unit` / `build_building` tools are kept as convenience wrappers that enqueue a single-item production.
  - Each phase lands a cross-front-door integration test (human + agent in one game observe identical timings).
- **Migration**
  - No migration of in-progress games. Games in `active` status at deploy time are archived by an operator.
  - Alembic migration adds new columns/fields with defaults; `research` populated on new `GameState` creation only.

---

## Phase 1: Sprite atlas tracer — terrain + resources

**User stories**: 1, 2, 41, 42

### What to build

Swap the two simplest rendering layers — terrain tiles and resource indicators — from procedural `Graphics.rect()` + text labels to `Pixi.Sprite` instances backed by a chosen free asset pack. Everything else on the map (units, cities, buildings, improvements) continues to render as it does today. This is the smallest slice that proves the atlas-loading pipeline, the sprite-resolver module, and the licence-compliance story end-to-end, and it produces an immediately visible change for anyone who opens the game.

### Acceptance criteria

- [ ] A sprite atlas from a CC0 or CC-BY pack is committed under `frontend/public/sprites/`, with `ATTRIBUTION.md` and the pack's `LICENSE.txt` alongside it.
- [ ] The Pixi app loads the atlas once at init via `Assets.load` before the first map render.
- [ ] Every terrain tile type renders as a sprite from the atlas — no solid colour rectangles remain in the terrain layer.
- [ ] Every on-map resource indicator renders as a sprite, replacing the single-letter labels (F / W / O / C).
- [ ] The sprite-resolver module takes an enum value and returns a `Pixi.Texture`; no string sprite IDs appear in render code.
- [ ] Fog-of-war redaction on terrain and resources behaves identically to pre-change.
- [ ] Adding a new `Terrain` or `Resource` enum member requires only a sprite-resolver data-table entry to render correctly.
- [ ] Frontend feedback loops pass: `npm run type-check`, `npm run lint`, `npm run test -- --run`, `npm run build`.

---

## Phase 2: Sprite atlas completion — units, cities, buildings, improvements

**User stories**: 3, 4, 5, 6, 7, 8

### What to build

Complete the sprite overhaul: units, cities with building indicators, and worker improvements all render from the atlas. Per-player identification lands in this phase — units and cities carry a colour cue (tint or outline overlay) rather than the base art being recoloured. City sprites vary by developedness (e.g. a frontier outpost sprite vs a fortified town sprite) driven by building count or a small set of thresholds; the authoritative building list still renders as indicator sprites around the city for clarity. Fog-of-war continues to gate visibility. After this phase, no procedural shapes remain on the map.

### Acceptance criteria

- [ ] Every unit type (scout, worker, soldier, archer) renders as a distinct sprite; the two-letter label overlay is removed.
- [ ] Units carry a visible per-player colour cue (tint or outline) that survives on shared / contested tiles.
- [ ] City sprites select from a small set of variants based on development level; walls, when present, are visible.
- [ ] Each building indicator around a city renders as a per-building sprite, not a generic dot.
- [ ] Worker improvements (farm, mine, extractor) render as sprites on their tiles, replacing the ASCII symbols.
- [ ] Fog-of-war-hidden units, cities, and improvements are not rendered, matching pre-change behaviour.
- [ ] No `Graphics.rect()`, `Graphics.roundRect()`, or `Pixi.Text` calls remain in the map-rendering code for gameplay entities.
- [ ] Frontend feedback loops pass.

---

## Phase 3: Multi-turn production tracer — single-slot `BuildJob`

**User stories**: 9, 13, 14, 15, 16, 17, 18, 19, 20, 21

### What to build

The instant-production bug dies. `BuildJob` is wired into turn resolution for both `TRAIN_UNIT` and `BUILD_BUILDING`: queueing an item deducts its resource cost immediately, creates a `BuildJob` with `progress = 0` and `total_cost` derived from the item's production cost, and makes the job the city's active work. Each turn, the city's production rate (base + Barracks bonus for unit jobs) advances the active job's `progress`; on completion the item materialises and `city.production_completed` fires. Cancelling an active job forfeits progress and does not refund resources. Cities still hold at most one active job in this phase — no queue reordering yet. Existing `TrainUnitAction` and `BuildBuildingAction` continue to exist but become thin enqueue-single-item wrappers; the legacy instant-resolution code is deleted, not kept behind a flag. The city UI gains a progress indicator (turns-remaining or progress bar) on the active job. MCP tools produce identical timing to the REST path, verified by a cross-front-door integration test.

### Acceptance criteria

- [ ] Queueing `TRAIN_UNIT` or `BUILD_BUILDING` creates a `BuildJob` on the city and deducts resources; the unit or building does not exist yet.
- [ ] Each turn advances the active job's `progress` by the city's production rate; Barracks boosts rate for unit jobs.
- [ ] On `progress >= total_cost` the job completes, the unit or building materialises, and the job is removed.
- [ ] Cancelling the active job via the existing action surface removes the job and forfeits accumulated progress; no resources are refunded.
- [ ] `city.production_completed` fires on every completion, scoped to the city owner's WebSocket connection.
- [ ] `redact_state` elides `build_queue` contents for non-owners.
- [ ] Cities iterate in sorted `city_id` order during resolution; a replay test proves determinism under the new resolver.
- [ ] The instant-resolution code path in the train / build executors is deleted outright; grep confirms no "materialise immediately" branch remains.
- [ ] Every existing test asserting "unit appears this turn" is migrated to assert "unit appears after N turns".
- [ ] Cross-front-door integration test: a human and an MCP agent in the same game observe identical production completion turns.
- [ ] Frontend surfaces turns-remaining / progress for the active job on the city.
- [ ] All backend and frontend feedback loops pass.

---

## Phase 4: Ordered production queue + reorder/cancel

**User stories**: 10, 11, 12, 37, 38

### What to build

`City.build_queue` becomes an ordered list. Three new actions land: `SetCityProductionAction` (append to queue), `CancelCityProductionAction(queue_index)` (remove entry; index 0 still forfeits progress), `ReorderCityQueueAction(new_order)` (permute). When the active job completes, the next queued job becomes active automatically at the next turn — no player action required to advance. The city UI gains a queue panel with reorder controls (drag or up/down arrows) and per-item cancel. MCP gains `set_city_production`, `cancel_city_production`, `reorder_city_queue` tools matching the human surface exactly. The existing `TrainUnitAction` / `BuildBuildingAction` paths continue to work (enqueue one item) for backwards compatibility with any test harnesses.

### Acceptance criteria

- [ ] `City.build_queue` is a `list[BuildJob]`; index 0 is active, tail entries wait.
- [ ] `SetCityProductionAction` appends to the queue; resources deduct at append time as in Phase 3.
- [ ] `CancelCityProductionAction(queue_index)` removes the specified entry; cancelling index 0 forfeits progress, cancelling non-active entries does not.
- [ ] `ReorderCityQueueAction(new_order)` permutes the queue; validation rejects permutations that are not a permutation of the current entries.
- [ ] When the active job completes, the next queued job becomes active on the following turn without explicit player action.
- [ ] `redact_state` elides all queue entries for non-owners (not just the active slot).
- [ ] The city UI renders the full queue with reorder + per-item cancel controls.
- [ ] MCP `set_city_production`, `cancel_city_production`, `reorder_city_queue` tools submit identically-shaped actions to the REST path.
- [ ] Cross-front-door integration test: human and MCP agent both reorder and cancel queue entries with identical observable state.
- [ ] All feedback loops pass.

---

## Phase 5: Tech tree foundation — `SCIENCE` and research loop

**User stories**: 22, 23, 24, 25, 26, 30, 33, 34, 35, 36, 38, 39

### What to build

Research becomes a first-class system, but without gating anything yet. `SCIENCE` joins the `Resource` enum and `ResourceBag`. Cities produce science per turn from a base rate plus Library and Temple bonuses. Each player has a `ResearchState` holding completed techs, the active tech (if any), and accumulated progress. `TECH_TREE` is a static module-level dict defining the full graph with prereqs, science costs, and what each tech unlocks. A small set of starter techs (empty `requires`) is seeded into every player's `completed` set at game creation so the game is playable from turn 1. `SetActiveResearchAction` picks the active tech; the resolver increments `progress` by the player's science income each turn; completion moves the tech from active to completed, fires `research.completed`, and requires the player to submit a new `SetActiveResearchAction` before research resumes (no auto-advance). Mid-research switching preserves `progress` rather than forfeiting or refunding. MCP `get_tech_tree` returns the full graph plus the caller's state; `set_active_research` matches the human action. The resource bar adds a SCIENCE readout and a minimal research indicator ("Researching X — N turns"); the full tech-tree panel waits for Phase 6. Nothing is gated on tech yet — this phase is cosmetic in gameplay terms, functional in data terms.

### Acceptance criteria

- [ ] `Resource.SCIENCE` exists; `ResourceBag.science` exists; both surface in the resource bar.
- [ ] Cities produce science per turn from a base rate; Library and Temple boost it per the balance table.
- [ ] `GameState.research` is populated at game creation with starter techs pre-completed for every player.
- [ ] `SetActiveResearchAction` sets the active tech; validation rejects techs whose prereqs are not in `completed` and techs already completed.
- [ ] Per-turn science income accrues into `ResearchState.progress` for the active tech; on `progress >= cost_science` the tech moves to `completed`, `progress` resets, `active` clears.
- [ ] `research.completed` fires on each completion, scoped to the researching player's connection only.
- [ ] Switching `active` to a different tech mid-research preserves the existing `progress` number (applied to whatever tech is active next, clamped to that tech's cost).
- [ ] `redact_state` returns only the caller's own `ResearchState`.
- [ ] Players iterate in sorted `player_id` order during research resolution; determinism replay test passes.
- [ ] MCP `get_tech_tree` returns the full static graph plus caller's state; `set_active_research` submits an action matching the REST path.
- [ ] Cross-front-door integration test: human and MCP agent complete the same research with identical timing.
- [ ] All feedback loops pass.

---

## Phase 6: Tech gates + tech tree panel UI

**User stories**: 27, 28, 29, 31, 32

### What to build

Tech starts gating gameplay, and the full tree UI lands. `UNIT_STATS` and `BUILDING_STATS` gain an optional `required_tech` field; the production resolver and action validators reject queueing items whose required tech is not in the calling player's `completed` set, with a clear per-item rejection message. The frontend gains a tech-tree panel (parallel to the diplomacy panel) that lays out the DAG with researched / in-progress / available / locked states, prerequisite arrows or a tree layout, and a click-to-set-active affordance on available techs. City-menu options for locked units and buildings are greyed out with a "Requires: \<tech name\>" tooltip rather than hidden — players can see the horizon and plan toward it. On `research.completed`, the UI surfaces the unlock via a toast or log entry so the moment lands. This phase ties together the engine changes from Phase 5 with the strategic layer the PRD promises.

### Acceptance criteria

- [ ] `UNIT_STATS` and `BUILDING_STATS` carry `required_tech` where applicable; the data tables are updated with the initial gating balance.
- [ ] Queueing a locked unit or building via any action path returns a per-item rejection naming the missing tech.
- [ ] The tech-tree panel lists every tech with its state (researched / in-progress / available / locked) and prereqs.
- [ ] Clicking an available tech in the panel queues a `SetActiveResearchAction`.
- [ ] City menus show locked units and buildings as greyed-out entries with "Requires: \<tech name\>" rather than hiding them.
- [ ] On `research.completed`, the UI surfaces an unlock toast or log entry naming the tech and what it unlocks.
- [ ] Fog-of-war: the tech panel shows only the caller's state; no opponent research is leaked.
- [ ] Starter techs (pre-researched at game creation) mean turn 1 has a non-empty menu of buildable units and buildings.
- [ ] Cross-front-door integration test: a human and an MCP agent both hit a tech gate, research through it, and unlock the gated item with identical observable behaviour.
- [ ] All feedback loops pass.
