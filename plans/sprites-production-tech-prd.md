# PRD: Visual Polish, Multi-Turn Production, and a Tech Tree

> **Scope:** Parley (codename `fourex`) needs (1) real sprites in place of coloured rectangles and letter labels, (2) a proper multi-turn production arc so cities don't spawn units and buildings instantly the same turn they're ordered, and (3) a tech tree that gates units and buildings behind research so the early game has a recognisable progression. Animations are deferred to a later initiative.

## Problem Statement

Playing Parley today feels flat on three axes.

**The map looks like a diagram, not a world.** Terrain is solid 32×32 colour blocks. Units are rounded rectangles with two-letter labels (`Sc`, `Wk`, `So`, `Ar`). Cities are coloured circles ringed by small dots that stand in for buildings. Resources are single letters (`F`, `W`, `O`, `C`) placed at tile corners. A new player looking at the screen can't tell what anything is without the legend; a returning player still has to read text to parse the board. There are no sprites, no art assets, no icons — just procedural shapes drawn in PixiJS.

**Cities produce instantly.** Queueing `TRAIN_UNIT` drops the unit on the city tile in the same turn. Queueing `BUILD_BUILDING` adds the building to the city's building set in the same turn. A player with enough resources on turn 3 can found a city, train a soldier, and build walls in one turn — the strategic arc of "commit to a project, wait several turns for it to finish, plan around that delay" is completely absent. The engine already has a `BuildJob` model with `progress` and `total_cost` fields, and `City.build_queue` is typed to hold one, but none of that is wired into turn resolution. It's a half-landed feature.

**Everything is available turn 1.** All six buildings, all four unit types, all three worker improvements can be constructed from the opening turn if the player has the resources. There's no reason to build a Library before a Temple, no reason to prefer one unit type over another beyond raw cost, and no long-term research axis to invest in. A 20-turn game and a 200-turn game have the same menu of options.

These three gaps compound. Without sprites, even a richer game would look threadbare. Without multi-turn production, there's no meaningful decision about what to queue next. Without tech-gated progression, there's no reason to queue advanced things at all.

## Solution

Three tracks, shippable independently but designed against a shared city-state model.

**Sprites.** Replace procedural shapes with a sprite atlas sourced from a free/open asset pack (Kenney.nl or equivalent CC0/CC-BY pixel art). Terrain, units, cities, buildings, resources, and improvements all render as sprites of the appropriate type. Per-player identification is achieved via a coloured outline or tint overlay on unit and city sprites rather than a full re-colour, so the art stays readable. No animations in this initiative — sprites are still static between turns.

**Multi-turn production with an ordered queue.** Cities accumulate production points per turn, modified by their buildings and population. Each unit and building has a production cost; queueing an item deducts the resource cost upfront and creates a `BuildJob` that accrues production each turn until it completes. Cities hold an ordered queue of jobs: the head is active, the rest wait. Players can add, remove, and reorder entries; cancelling the active job loses accumulated progress but does not refund resources. The orphaned `BuildJob` model is wired into the resolver and `execute_train_unit` / `execute_build_building` stop materialising items instantly.

**Tech tree with science resource.** A new `SCIENCE` resource joins `FOOD`, `WOOD`, `ORE`, `CRYSTAL`. Cities produce science per turn, boosted by culture buildings (Library, Temple). Each player picks one active tech; accumulated science drains from their stockpile into the active tech until it completes and unlocks whatever units and/or buildings that tech gates. Tech prerequisites form a DAG — starter techs are free, later techs require their predecessors. The MCP toolbelt gains a matching `set_active_research` / `get_tech_tree` pair so agents and humans stay at parity.

From the player's perspective, after this ships:

1. The map looks like an RTS, not a spreadsheet.
2. Cities show "Building Soldier — 3 turns remaining" instead of instantly growing their army.
3. A tech panel in the UI shows what's currently being researched, what's unlocked, and what's next.
4. Early-game menus are shorter (only starter options) and grow as research completes.

## User Stories

**Visual fidelity — map and board**

1. As a player opening the game for the first time, I want terrain tiles to look like the thing they represent (grass, forest, mountain, water, desert), so that I can parse the map at a glance without reading a legend.
2. As a player, I want resource tiles to show a recognisable icon for food/wood/ore/crystal, so that I don't have to decode single-letter labels.
3. As a player, I want my cities to render as a sprite that visually changes (e.g. additional buildings, walls, banners) as they develop, so that I can tell a thriving capital from a frontier outpost without opening the city panel.
4. As a player, I want worker improvements (farm, mine, extractor) to render as sprites on the tiles they occupy, so that I can see my economy at a glance.
5. As a player, I want friendly vs hostile units to be visually distinguishable beyond the outline colour (e.g. per-type sprite plus a tinted banner), so that I can scan a crowded map and find targets quickly.

**Visual fidelity — units**

6. As a player, I want each unit type (scout, worker, soldier, archer) to have a distinct sprite, so that I can identify units without reading the label overlay.
7. As a player, I want my own units to be identifiable at a glance via a consistent player colour cue, so that I don't confuse them with opponents' units on a shared tile or an adjacent skirmish.
8. As a player with partial unit visibility via fog-of-war, I want the sprite to respect fog-of-war redaction (no sprite if the unit isn't visible to me), so that the visual layer doesn't leak information the REST layer hides.

**Production — queueing and progress**

9. As a player, I want to open a city and see its current production queue (active item + waiting items) with turn counts, so that I know exactly what's happening and when it finishes.
10. As a player, I want to queue a unit or building with a click and see it appended to the city's queue, so that I can plan several turns ahead without micromanaging each turn.
11. As a player, I want to reorder the queue before End Turn, so that I can promote or demote items as circumstances change.
12. As a player, I want to cancel a queued item before End Turn, so that I can correct mistakes.
13. As a player, I want production cost resources deducted at queue time, so that I can't queue infinitely more than I can afford and the commitment is immediate.
14. As a player, I want the active item's progress to render as a progress bar or turns-remaining counter on the city, so that I don't need to open a panel to track what's happening.
15. As a player, I want cancelling the active item to forfeit accumulated progress (no refund), so that switching projects mid-build carries a real cost and there's a tension between sticking with a choice and pivoting.
16. As a player, I want the production rate to be visibly influenced by buildings (e.g. Barracks boosts unit production speed), so that my building choices have a legible effect on my queue.
17. As a player, I want `turn.resolved` and a new `city.production_completed` event to drive live UI updates when items finish, so that I don't need to reload to see new units.

**Production — bug parity and determinism**

18. As a developer, I want `execute_train_unit` and `execute_build_building` to route through the multi-turn `BuildJob` path, so that the "instant training" bug — a city producing multiple units in one turn — stops being possible by construction.
19. As a developer, I want the MCP `submit_actions` path and the REST `/actions` path to share the production resolver, so that an agent and a human in the same game observe identical timing.
20. As a developer, I want the production resolver to run in a deterministic order across all cities each turn (sorted by city ID), so that the deterministic-engine invariant `same seed + same actions = identical outcomes` survives the rewrite.
21. As a developer, I want all existing tests that assert "unit appears this turn" to be migrated to assert "unit appears after N turns", so that the test suite encodes the new invariant and the old assumption cannot creep back in.

**Tech tree — research loop**

22. As a player, I want a new `SCIENCE` resource to appear in my resource bar alongside food/wood/ore/crystal, so that I can see my scientific output as a first-class currency.
23. As a player, I want cities to produce science passively per turn, with Library and Temple providing a boost, so that my existing building choices feed the research system.
24. As a player, I want to pick one active tech to research at a time, so that commitment matters and I can't multiplex research infinitely.
25. As a player, I want the cost of the active tech to drain from my science stockpile each turn until it completes, so that the progression is legible and predictable.
26. As a player, I want switching my active tech mid-research to preserve the science already invested in it (not refund, not forfeit), so that I can pause a line and resume it later without losing work.
27. As a player, I want a tech tree panel (separate from diplomacy) showing researched / in-progress / available / locked techs with their prerequisites, so that I can plan multi-tech strategies visually.
28. As a player, I want completing a tech to unlock every unit and building it gates and surface that unlock in the UI (toast, log entry, or panel highlight), so that I notice when a new option becomes available.
29. As a player, I want locked units and buildings to appear greyed out with "Requires: <tech name>" rather than being hidden entirely, so that I can see what's on the horizon and plan toward it.
30. As a player, I want a `research.completed` event over WebSocket, so that my UI updates live when a tech finishes.

**Tech tree — gating**

31. As a player, I want advanced units (e.g. Archer, Knight-tier) to require specific techs, so that the early game is played with a constrained unit roster and later-game armies feel earned.
32. As a player, I want advanced buildings (e.g. Library requires Writing, Temple requires Mysticism) to be locked until their gating tech completes, so that the turn-1 menu is short and strategic sequencing emerges.
33. As a player, I want starter techs (zero prerequisites) to already be researched from turn 1, so that the base game is playable without forcing research to even build anything.
34. As a player, I want each player's research state to be private until revealed via diplomacy or direct interaction, so that the research layer respects fog-of-war.

**Cross-front-door parity**

35. As an MCP agent, I want a `set_active_research(tech_id)` tool, so that I can direct my civ's science the same way a human can.
36. As an MCP agent, I want a `get_tech_tree()` tool returning the full tech graph plus my current research state, so that I can plan my tech path programmatically.
37. As an MCP agent, I want `set_city_production(city_id, item)`, `cancel_city_production(city_id)`, and `reorder_city_queue(city_id, order)` tools matching the human UI, so that neither front door has gameplay capabilities the other lacks.
38. As an MCP agent, I want the existing `submit_actions` tool to accept the new action types with the same "queued-until-End-Turn" semantics, so that the MCP flow doesn't diverge from the human flow.
39. As a developer, I want a backend test proving a human and an MCP agent in the same game both see identical production and research timings, so that the cross-front-door promise is regression-protected.

**Configuration and content**

40. As a developer, I want the tech tree, production costs, production rates, and unit/building gating to live in data tables (Python dicts) rather than hardcoded into the resolver, so that iterating on balance doesn't require touching resolution logic.
41. As a developer, I want the sprite atlas pack choice (and its attribution file) to live in `frontend/public` with a README noting the licence, so that we can prove licence compliance and swap packs later without hunting for the source.
42. As a developer, I want sprite IDs referenced by terrain/unit/building/resource/improvement enums rather than strings in the render code, so that adding a new terrain or unit type is a one-line data change, not a render-layer hunt.

## Implementation Decisions

### Sprite rendering

- **Art pack:** a free CC0 or CC-BY pack matching the existing 32×32 tile grid. Kenney.nl's strategy / RTS packs are the first candidate; final choice made in the implementation phase after inspecting candidate packs for coverage (needs sprites for at least 5 terrain types, 4 unit types, 6 building variants, 4 resources, 3 improvements). Attribution goes in a `public/sprites/ATTRIBUTION.md` file.
- **Renderer change:** the existing PixiJS layers swap `Graphics.rect()` terrain draws and `Graphics.roundRect()` unit draws for `Pixi.Sprite` instances backed by a single loaded texture atlas. The existing layer structure (terrain → grid → improvements → borders → cities → units → selection) is preserved; only the draw primitive changes.
- **Player identification:** unit sprites get a coloured outline or tint band via PixiJS `tint` or an overlay sprite, so the player-colour cue stays but the base art is shared across players.
- **City evolution:** city sprite is selected from an array based on building count / building set, so players can visually read how developed a city is. Buildings still render as indicator sprites around the city for the authoritative list.
- **Fog-of-war:** the render layer continues to key off redacted state. No new fog plumbing required.
- **No animations:** `Ticker`-driven tweens, idle loops, and transition effects are out of scope. Adding them is a follow-up initiative.

### Multi-turn production

- **`BuildJob` wired in:** `City.build_queue` changes from `BuildJob | None` to `list[BuildJob]` (ordered; index 0 is active). The active job's `progress` field is incremented each turn by the city's production rate; completion fires when `progress >= total_cost`.
- **Cost semantics:** resource cost is deducted at queue time (as today). `total_cost` is a separate "production points to complete" number derived from the item's `production_cost` stat, not the same as the resource cost.
- **Production rate per city:** a base per-turn value plus modifiers. Barracks adds to unit-job production rate; a new "Workshop"-tier building (deferred; not shipped this phase unless cheap) would have added to building-job production rate. Initial balance: base rate = 2, Barracks = +1 for unit jobs.
- **New actions:** `SetCityProductionAction(city_id, item_spec)` appends to the queue; `CancelCityProductionAction(city_id, queue_index)` removes an entry (index 0 forfeits progress); `ReorderCityQueueAction(city_id, new_order)` permutes queue entries. Existing `TrainUnitAction` and `BuildBuildingAction` become thin wrappers that enqueue a job; legacy behaviour (instant resolution) is deleted, not kept for compatibility.
- **Determinism:** cities iterate in sorted `city_id` order during `resolve_turn`; each city's queue advances deterministically. No RNG introduced.
- **Events:** a new `city.production_completed` WebSocket event fires per completion, scoped to the owning player's connection. Turn resolution still fires `turn.resolved` as today.
- **Fog-of-war:** production queue contents are private to the city owner. `redact_state` elides `build_queue` for non-owners.

### Tech tree

- **`SCIENCE` resource:** a new enum value in `Resource` and a new field on `ResourceBag`. Passive science income is computed in the same per-turn collection step as other resources, driven by a new `science_per_turn()` method on `City` that sums base + building bonuses.
- **Tech data model:** a `Tech` Pydantic model with `id: TechId`, `name: str`, `cost_science: int`, `requires: list[TechId]`, `unlocks_units: list[UnitType]`, `unlocks_buildings: list[BuildingType]`. A module-level `TECH_TREE: dict[TechId, Tech]` defines the graph.
- **Starter techs:** techs with empty `requires` are considered available from turn 1. A small set (e.g. `agriculture`, `stoneworking`) is pre-researched for each player at game creation so the game is immediately playable.
- **Per-player research state:** `GameState` gains a per-player `research: dict[PlayerId, ResearchState]` where `ResearchState` holds `completed: set[TechId]`, `active: TechId | None`, and `progress: int`. Science income flows into `progress` each turn when `active` is set.
- **Tech resolution:** at turn end, the resolver increments `progress` by the player's net science income; on completion, `active` is moved to `completed`, `progress` resets, and a `research.completed` event fires. The player must submit a `SetActiveResearchAction(tech_id)` to start the next one — no auto-advance.
- **Action:** `SetActiveResearchAction(tech_id)` is validated against prereqs and completed state. Switching mid-research preserves `progress` (carries over to whatever tech is set next, clamped).
- **Unit/building gating:** `UNIT_STATS` and `BUILDING_STATS` each gain a `required_tech: TechId | None` field. Validation in `execute_train_unit` / `execute_build_building` (or their new enqueue-job equivalents) rejects items whose required tech the player hasn't researched.
- **Fog-of-war:** each player's `research` state is private. `redact_state` returns only the caller's own `ResearchState`.

### API, MCP, and WebSocket contracts

- **REST:** existing `/actions` endpoint accepts the new action types in the same discriminated union. No new endpoints required; the action queue batch remains atomic.
- **MCP tools:** new read tool `get_tech_tree` returns the full static graph plus the caller's `ResearchState`. New write tools `set_active_research`, `set_city_production`, `cancel_city_production`, `reorder_city_queue` all produce actions that submit via the shared queue path. Existing `train_unit` / `build_building` are retained as convenience wrappers that enqueue a single-item production.
- **WebSocket events:** `city.production_completed` (payload: `city_id`, `item_spec`, `turn`), `research.completed` (payload: `player_id`, `tech_id`, `turn`). Both scoped to the relevant player's connection; production events optionally fan out to players with visibility on the city.

### Frontend structure

- **Sprite atlas loading:** a new PixiJS `Assets.load` call at app init loads the atlas before the map first renders. A sprite-resolver module maps `(enum, variant) → sprite_id → Pixi.Texture`.
- **City panel:** the existing city view (if any) gains a production queue section showing the active item + waiting items with turns-remaining, a reorder control (drag or up/down arrows), and a cancel control per item.
- **Tech panel:** a new panel parallel to the diplomacy panel shows researched / in-progress / available / locked techs, with prerequisite arrows or tree layout. Clicking an available tech queues a `SetActiveResearchAction`.
- **Resource bar:** extends to include `SCIENCE` alongside the existing four resources.
- **Event handling:** the existing `useLobbyEvents` hook gains cases for `city.production_completed` and `research.completed`, which invalidate the relevant React Query caches.

### Migration and testing

- **No migration of in-progress games.** The schema change is disruptive enough that running games are abandoned at deploy. The DB migration adds the new columns/fields with defaults; games already in `active` status at deploy time simply won't have research state populated and should be archived by an operator.
- **Test coverage:** rules-layer tests cover multi-turn training, multi-turn building, queue reorder, cancel-active-forfeits-progress, tech-prereq validation, science income, mid-research tech switch. A cross-front-door integration test covers human + MCP agent seeing identical timings.
- **Backend feedback loops remain unchanged:** `mise run format`, `mise run lint`, `mise run test`, plus the full frontend suite (`type-check`, `lint`, `test`, `build`) before any commit.

## Out of Scope

- **Animations of any kind.** No idle loops, no move tweens, no attack animations, no ambient map effects. The entire animation surface is a follow-up initiative.
- **Commissioned or AI-generated sprite art.** This initiative uses a free asset pack only.
- **Mobile-responsive and touch-first gameplay UI.**
- **Retroactive migration of in-progress games.** Games running at deploy time are abandoned.
- **Worker improvements gated by tech.** The user elected "units and buildings" coverage; improvements remain available from turn 1 and can be extended into the tech tree in a later initiative.
- **Tech trading, espionage, or any diplomatic interaction with research state.**
- **Production-rate boosts from buildings other than Barracks.** No Workshop/Stable-tier building is introduced in this initiative.
- **Great People, civic trees, golden ages, or any other meta-progression layer beyond the tech tree itself.**
- **Replay or undo of submitted production or research actions once a turn is resolved.**
- **History of prior research paths per player surfaced in the UI.**
- **Auto-advance research** when a tech completes with no queued next pick. Players must explicitly set their next active tech.
- **Analysis tools reflecting production / tech state.** Existing MCP analysis tools (`analyze_territory`, `evaluate_military_position`, etc.) are not extended as part of this PRD.

## Further Notes

- **Sprite pack licensing.** Kenney.nl packs are predominantly CC0 (public domain) with no attribution required, but any chosen pack's `LICENSE.txt` is included verbatim in `frontend/public/sprites/` alongside an `ATTRIBUTION.md` crediting source and pack name, so the repo stays legally clean regardless of which pack wins out.
- **The orphaned `BuildJob` model is a prior half-landed feature.** This PRD treats it as the starting skeleton rather than rewriting from scratch; the shape (`progress`, `total_cost`, `type`, `target`) is kept. The only structural change is `City.build_queue: BuildJob | None` → `list[BuildJob]` to support the ordered-queue policy.
- **Determinism invariant:** the engine's core guarantee (same seed + same actions ⇒ identical outcomes) must continue to hold. Production and research resolution introduce no RNG and iterate collections in sorted order. A new property-based test replays a recorded game twice and asserts full `GameState` equality.
- **Starter tech set keeps the turn-1 menu sane.** Without at least `agriculture` (gates farms? — no, improvements aren't tech-gated this initiative) and basic building techs being free, players open turn 1 with zero options and the game stalls. Exact starter set is a balance decision made during implementation, but the UX principle is "turn 1 offers a real choice, not an empty screen".
- **Phase ordering is up to the implementation plan.** A likely sequence: (1) sprite rendering — lowest engine-touch, highest visual impact, ships confidence; (2) multi-turn production — the core engine change, closes the "instant unit" bug; (3) tech tree — builds on production since tech completion unlocks production options. This ordering also means each phase is independently shippable and observable.
- **The "immediate unit production bug" becomes un-buggable by construction** once phase 2 ships, rather than being patched in isolation. Any place in the codebase that tries to instantiate a unit or building outside the `BuildJob` path is a test failure by design.
- **MCP parity is a per-phase acceptance criterion**, matching the pattern established in the `human-frontend-parity` plan: every new action type and event must be reachable from both front doors, and a cross-front-door integration test lands with each phase.
- **Follow-up:** after this PRD is approved, run `/prd-to-plan` to generate tracer-bullet implementation phases, then iterate implementation via the usual loop.
