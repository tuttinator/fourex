# Plan: Gameplay Dynamics — Economy, Territory, Victory & Healing

> Source PRD: `plans/gameplay-dynamics-prd.md`

## Architectural decisions

Durable decisions that apply across all phases:

- **State storage**: GameState remains a JSON blob in the `Game.state` column. New fields (city culture, border radius, victory settings) are added to the Pydantic models and serialised alongside existing state. No new database tables required.
- **City model extensions**: `City` gains `culture: int` (accumulated culture points) and `border_radius: int` (current expansion level, 0–3). Cultural buildings (Monument, Library, Temple) are added to the `BuildingType` enum and stored in the existing `City.buildings: set[BuildingType]` field.
- **ImprovementType extension**: `LUMBER_MILL` added to the existing `ImprovementType` enum.
- **Victory configuration**: `GameState` gains `victory_conditions: list[str]` (subset of `["domination", "economic", "elimination", "score"]`, default all four). Victory checking consolidates into `rules.py` as a pure function, replacing the existing `_check_victory` in the persistent game controller.
- **Tile ownership**: Tiles gain ownership through cultural border expansion, not just city founding. `tile.owner` is set/cleared by the border expansion logic during turn resolution.
- **Turn resolution order**: Sequential player-order action resolution is retained. The new systems slot into `resolve_turn()` in this order: reset moves → process actions → expand borders → heal units → collect resources → check victory → advance turn.
- **MCP tool surface**: Existing tools (`get_game_state`, `get_game_info`, `submit_actions`, `validate_actions`) return enriched data (culture, borders, victory progress). No new MCP tools are required — territory and victory info are embedded in the game state response.
- **Building costs**: Monument (20 wood), Library (30 wood + 10 ore), Temple (30 wood + 20 ore + 10 crystal). Improvement costs: Farm (10 wood), Mine (10 wood), Lumber mill (10 ore), Crystal extractor (10 ore + 5 crystal).
- **Culture thresholds**: Radius 1 at 10 culture, radius 2 at 30, radius 3 at 60. Base culture per city: 1/turn. Monument +1, Library +2, Temple +3. Max with all buildings: 7/turn.

---

## Phase 1: Culture Model & Border Expansion

**User stories**: 1, 2, 3, 4, 5, 6, 7, 8, 14, 29

### What to build

Add culture accumulation and territorial border expansion to cities. Each city tracks its own `culture` points and `border_radius`. At the end of each turn, cities generate culture (1 base + building bonuses) and check whether they've crossed an expansion threshold (10 → radius 1, 30 → radius 2, 60 → radius 3). When a threshold is crossed, all tiles within the new Manhattan distance radius are claimed for that city's owner — unless already claimed by another city (first-to-reach rule). Water and mountain tiles cannot be owned.

Add Monument, Library, and Temple to `BuildingType`. Implement `execute_build_building()` in the rules engine so that players can construct cultural buildings in their cities. All three stack in a single city.

Wire culture accumulation and border expansion into `resolve_turn()` as a new step after action processing but before resource collection. Update `get_game_state` MCP tool responses to include city culture, border radius, and tile ownership in the returned state.

Write tests covering: culture accumulation with and without buildings, border expansion at each threshold, first-to-reach conflict resolution, water/mountain tiles excluded from borders, newly founded cities start at radius 0.

### Acceptance criteria

- [ ] `City` model has `culture: int` and `border_radius: int` fields (default 0)
- [ ] `BuildingType` enum includes `MONUMENT`, `LIBRARY`, `TEMPLE`
- [ ] `execute_build_building()` implemented: validates ownership, resource cost, adds building to city
- [ ] Building costs enforced: Monument (20 wood), Library (30 wood + 10 ore), Temple (30 wood + 20 ore + 10 crystal)
- [ ] Culture accumulation runs each turn: 1 base + 1 (Monument) + 2 (Library) + 3 (Temple)
- [ ] Border expansion triggers at thresholds 10, 30, 60 — claiming tiles at Manhattan distance 1, 2, 3
- [ ] First-to-reach conflict: tiles already owned by another city are not claimed
- [ ] Water and mountain tiles are never claimed
- [ ] Newly founded cities start with `culture=0`, `border_radius=0` (only city tile owned)
- [ ] Each tile belongs to at most one city
- [ ] Game state returned by MCP tools includes culture, border_radius, and tile ownership
- [ ] Tests cover: culture accumulation rates, all three expansion thresholds, building stacking, border conflict, terrain exclusion
- [ ] All existing tests still pass

---

## Phase 2: City Tile Yields

**User stories**: 9, 10, 11, 12, 30

### What to build

Extend `collect_resources()` so that cities harvest resources from all tiles within their cultural borders, not just a flat 1 food/turn. Unimproved resource tiles yield +1 of their resource type per turn. All forest tiles (with or without a wood resource) yield +1 wood/turn. Improvements boost yields: farms to +3 food, mines to +3 ore, lumber mills to +3 wood, crystal extractors to +2 crystal. The existing flat +1 food/turn base city production remains on top of tile yields.

The yield calculation should be clear and auditable: for each tile owned by a city, compute base yield (from resource/terrain) + improvement bonus, and add to the city owner's stockpile. Non-resource plains tiles yield nothing.

Write tests covering: base yields from each resource type, forest passive wood yield, improved tile yields, multiple cities collecting independently, tiles outside borders not yielding.

### Acceptance criteria

- [ ] Cities collect resources from all owned tiles each turn during `collect_resources()`
- [ ] Unimproved food tiles yield +1 food, ore tiles +1 ore, wood tiles +1 wood, crystal tiles +1 crystal
- [ ] All forest tiles within borders yield +1 wood/turn (regardless of wood resource)
- [ ] Improved tile yields: farm +3 food, mine +3 ore, lumber mill +3 wood, crystal extractor +2 crystal (total including base)
- [ ] Base city food production (+1/turn, boosted by Granary) still applies on top of tile yields
- [ ] Plains tiles without resources yield nothing
- [ ] Tiles outside city borders do not generate yields
- [ ] Tests cover: each resource type unimproved, each improvement type, forest passive yield, multi-city collection, border boundary enforcement
- [ ] All existing tests still pass

---

## Phase 3: Improvements & Lumber Mill

**User stories**: 13

### What to build

Add `LUMBER_MILL` to the `ImprovementType` enum. Implement `execute_build_improvement()` in the rules engine: validate the worker is owned by the player, is on the target tile, the tile is within the player's territory, and the terrain/resource combination supports the improvement type. Deduct the resource cost, place the improvement on the tile, and consume the worker.

Terrain/improvement rules: Farm requires a food resource tile. Mine requires an ore resource tile. Lumber mill requires any forest tile. Crystal extractor requires a crystal resource tile. All require the tile to be owned by the building player.

Improvement costs: Farm (10 wood), Mine (10 wood), Lumber mill (10 ore), Crystal extractor (10 ore + 5 crystal).

Update the `validate_actions` MCP tool to support `BUILD_IMPROVEMENT` and `BUILD_BUILDING` action types (building was implemented in Phase 1 but validation may need updating).

Write tests covering: each improvement type on valid terrain, wrong terrain rejection, tile not owned rejection, insufficient resources, worker consumed on build, lumber mill on forest with and without wood resource.

### Acceptance criteria

- [ ] `LUMBER_MILL` added to `ImprovementType` enum
- [ ] `execute_build_improvement()` implemented: validates ownership, territory, terrain, resources; places improvement; consumes worker
- [ ] Improvement costs enforced: Farm (10 wood), Mine (10 wood), Lumber mill (10 ore), Crystal extractor (10 ore + 5 crystal)
- [ ] Terrain validation: Farm on food tile, Mine on ore tile, Lumber mill on any forest tile, Crystal extractor on crystal tile
- [ ] Tile must be within the player's territory (owned) to build an improvement
- [ ] Worker is consumed after building an improvement
- [ ] `validate_actions` MCP tool accepts and validates BUILD_IMPROVEMENT and BUILD_BUILDING
- [ ] Tests cover: valid build for each type, wrong terrain, unowned tile, insufficient resources, worker consumption, lumber mill on forest without wood resource
- [ ] All existing tests still pass

---

## Phase 4: Victory Conditions & Elimination

**User stories**: 15, 16, 17, 18, 19, 20, 21, 22, 26, 27, 28

### What to build

Implement four configurable victory conditions: domination, economic, elimination, and score. Add `victory_conditions: list[str]` to `GameState` (default: all four enabled). Add a `victory_conditions` parameter to the `create_game` MCP tool.

**Domination**: Last player with at least one city wins. Checked after all actions resolve each turn. Takes priority over all other victory conditions when multiple trigger simultaneously.

**Economic**: A player wins when their current stockpile totals >= 1000 (food + wood + ore + crystal). Checked after resource collection each turn.

**Elimination**: A player is eliminated when they lose their last city. If a player has not yet founded a city, they are eliminated when their last unit is killed. When eliminated: all their tiles become unowned, all their improvements are destroyed, their cities are removed, and they are marked as eliminated (but remain in the players list for history). If elimination reduces the game to one remaining player, that triggers domination victory.

**Score at turn limit**: When `max_turns` is reached, calculate scores: cities (weighted highest), territory (tile count), units, and resources. Highest score wins.

Consolidate victory checking into a pure function in `rules.py` that runs at the end of `resolve_turn()`, replacing the existing `_check_victory` in the persistent game controller. Update `get_game_info` MCP tool to include enabled victory conditions and elimination status.

Write tests covering: each victory condition triggering, domination priority over economic, elimination cascading to domination, economic threshold boundary, score calculation, worker-only elimination, eliminated player cleanup.

### Acceptance criteria

- [ ] `GameState` has `victory_conditions: list[str]` field, defaulting to all four
- [ ] `create_game` MCP tool accepts a `victory_conditions` parameter
- [ ] Domination victory: last player with a city wins
- [ ] Domination takes priority when multiple conditions trigger on the same turn
- [ ] Economic victory: player with >= 1000 total stockpile wins (checked after resource collection)
- [ ] Elimination: player loses last city → eliminated; player with no city loses last unit → eliminated
- [ ] Eliminated player cleanup: tiles become unowned, improvements destroyed, cities removed
- [ ] Elimination reducing to one player triggers domination victory
- [ ] Score victory at turn limit: weighted sum of cities, territory, units, resources
- [ ] Victory checking is a pure function in `rules.py`, called at end of `resolve_turn()`
- [ ] Existing `_check_victory` in persistent game controller delegates to the rules function
- [ ] `get_game_info` includes enabled victory conditions
- [ ] Tests cover: each condition triggering independently, domination priority, elimination cascade, economic boundary, score calculation, worker-only elimination, cleanup of eliminated player state
- [ ] All existing tests still pass

---

## Phase 5: Unit Healing

**User stories**: 23, 24, 25

### What to build

Add passive healing for units that are stationary in friendly territory. At the end of each turn (after actions resolve, during the healing step), any unit that did not move this turn and is on a tile owned by its player heals +1 HP, up to its maximum HP. Scouts are excluded from passive healing.

"Did not move" is determined by comparing the unit's `moves_left` to its full movement allowance — if `moves_left` equals the unit's base `moves` stat, the unit did not move this turn. Healing does not consume resources.

Wire healing into `resolve_turn()` after action processing and border expansion, but before resource collection.

Write tests covering: soldier heals in friendly territory, scout does not heal, unit that moved does not heal, unit outside friendly territory does not heal, unit does not exceed max HP, healing with no resource cost.

### Acceptance criteria

- [ ] Units heal +1 HP/turn when stationary and on a tile owned by their player
- [ ] Scouts are excluded from healing
- [ ] "Stationary" means the unit did not use any movement this turn
- [ ] Units cannot heal above their max HP (from `UNIT_STATS`)
- [ ] Healing does not consume any resources
- [ ] Healing runs in `resolve_turn()` after actions and border expansion, before resource collection
- [ ] Tests cover: healing in friendly territory, scout exclusion, moved unit exclusion, non-owned tile exclusion, max HP cap, zero resource cost
- [ ] All existing tests still pass
