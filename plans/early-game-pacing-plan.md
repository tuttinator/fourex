# Plan: Early Game Pacing & Economy Rebalance

> Source PRD: `plans/early-game-pacing-prd.md`

## Architectural decisions

Durable decisions that apply across all phases:

- **Game state model**: No new models or fields are introduced. All changes operate on existing `GameState`, `City`, `Unit`, `Tile`, `ResourceBag`, and the `UNIT_STATS` / `BUILDING_STATS` / `IMPROVEMENT_STATS` / `CULTURE_THRESHOLDS` constants.
- **Four creation paths**: Game initialisation exists in four places — MCP server lifecycle, game controller, persistent game controller, and CLI `__main__`. All must stay consistent. Consider extracting shared constants to reduce drift.
- **Canonical worker HP**: Controllers and MCP server use `hp=100`; legacy CLI and some tests use `hp=2`. The canonical value is `100`. All paths and tests will be normalised to this.
- **Starting stockpile unchanged**: 50 food, 20 wood, 10 ore, 0 crystal across all non-CLI paths. The CLI `__main__.py` will be normalised to match.
- **Determinism preserved**: All changes must maintain the deterministic property — same seed + same actions = identical outcomes.

---

## Phase 1: Immediate Borders & Ownable Terrain

**User stories**: 1, 10, 11

### What to build

When a city is founded, it immediately starts at border radius 1, claiming all tiles within Manhattan distance 1. The border expansion logic is updated to allow water and mountain tiles to be owned — they still cannot have cities or non-mine improvements built on them, but they contribute resource yields if they have a resource (e.g. ore on a mountain, crystal on a mountain).

The culture threshold for radius 1 changes from 10 to 0. Radius 2 changes from 30 to 15. Radius 3 changes from 60 to 40. When `execute_found_city` creates a city, it triggers `_expand_borders` immediately so the founding player owns adjacent tiles from turn 0.

The `_expand_borders` function removes its terrain filter that currently skips water and mountain tiles. The `_calculate_tile_yield` function already handles these tiles correctly (mountains with ore yield ore, water with no resource yields nothing), so no yield logic changes are needed.

### Acceptance criteria

- [ ] A newly founded city has `border_radius` of 1 and owns adjacent passable tiles immediately
- [ ] Water tiles within a city's border radius are owned by that city
- [ ] Mountain tiles within a city's border radius are owned by that city
- [ ] Mountain tiles with ore/crystal resources yield their resource when owned
- [ ] Water tiles with no resource yield nothing (no error, just zero yield)
- [ ] Culture threshold for radius 1 is 0, radius 2 is 15, radius 3 is 40
- [ ] Border radius 2 expansion triggers at culture 15 (claiming tiles at distance 2)
- [ ] Border radius 3 expansion triggers at culture 40 (claiming tiles at distance 3)
- [ ] First-to-reach ownership rule still applies — tiles already owned by another player are not overwritten
- [ ] All existing culture/border tests updated and passing
- [ ] A test verifies that mountain and water tiles are now claimable within borders

---

## Phase 2: Cost Rebalance & Base Income

**User stories**: 6, 7, 8, 9, 12, 13, 18, 19

### What to build

All unit, building, improvement, and city founding costs are halved. Base city food production increases from 1 to 2 per turn.

**Unit costs:**
- Scout: 10 food
- Worker: 15 food
- Soldier: 15 food + 5 ore
- Archer: 15 food + 5 wood

**Building costs:**
- Granary: 20 wood
- Barracks: 25 wood
- Walls: 20 ore
- Monument: 10 wood
- Library: 15 wood + 5 ore
- Temple: 15 wood + 10 ore + 5 crystal

**Improvement costs:**
- Farm: 10 wood
- Mine: 10 wood
- Lumber Mill: 5 wood
- Crystal Extractor: 10 wood + 5 ore

**City founding cost:** 15 food (down from 30)

**Base city food:** 2 per turn (before Granary multiplier). With Granary (+50%), this becomes `int(2 * 1.5) = 3` — a meaningful boost compared to the old `int(1 * 1.5) = 1`.

### Acceptance criteria

- [ ] All unit costs in `UNIT_STATS` reflect the halved values
- [ ] All building costs in `BUILDING_STATS` reflect the halved values
- [ ] All improvement costs in `IMPROVEMENT_STATS` reflect the halved values
- [ ] City founding cost is 15 food
- [ ] Base city food production is 2 per turn
- [ ] Granary multiplier on base food produces 3 (not 1 as before)
- [ ] A player starting with 50 food can found a city (15 food) and train a scout (10 food) on turn 0 with food to spare
- [ ] All existing tests that assert on cost values or income are updated and passing

---

## Phase 3: Worker Survival

**User stories**: 2, 3, 14, 16

### What to build

Workers are no longer consumed when building tile improvements. The worker remains on the tile after the improvement is placed and retains any remaining movement points — building an improvement does not cost movement. Workers are still consumed when founding cities (unchanged).

This changes `execute_build_improvement` to skip the worker deletion step. The resource cost for the improvement is still deducted. The tile's improvement is still set. The worker's `unit_id` remains on the tile.

### Acceptance criteria

- [ ] A worker that builds a farm remains alive in `state.units` after the action resolves
- [ ] The worker remains on the tile (tile's `unit_id` still references the worker)
- [ ] The worker retains its remaining movement points after building
- [ ] A worker can build an improvement and then move in the same turn
- [ ] A worker can build multiple improvements across multiple turns
- [ ] A worker founding a city is still consumed (unchanged behaviour)
- [ ] Improvement resource costs are still deducted from the player's stockpile
- [ ] The tile's improvement field is still set correctly
- [ ] All existing improvement tests updated — assertions that the worker is consumed are changed to assert survival
- [ ] A new test verifies a worker can build, then move, in the same turn

---

## Phase 4: Two Starting Units & Consistency Cleanup

**User stories**: 4, 5, 15, 17

### What to build

Each player starts the game with two units: a worker and a scout. The worker spawns on the designated starting tile (as currently). The scout spawns on an adjacent passable tile — the placement logic tries cardinal directions (N, E, S, W) and picks the first tile that is not water or mountain.

This change applies to all four game creation paths (MCP server lifecycle, game controller, persistent game controller, CLI `__main__`) and the `join_game` flow.

As a consistency cleanup in this phase:
- The CLI `__main__.py` starting stockpile is normalised from `(food=100, wood=50, ore=30, crystal=5)` to `(food=50, wood=20, ore=10)` to match all other paths.
- Worker HP across all creation paths and tests is normalised to 100 (the canonical value from controllers/MCP server). Legacy tests using `hp=2` are updated.

### Acceptance criteria

- [ ] A new game creates both a worker and a scout for each player
- [ ] The worker spawns on the player's starting tile
- [ ] The scout spawns on an adjacent tile (not water, not mountain)
- [ ] If all four cardinal-adjacent tiles are impassable, the scout placement falls back to a wider search
- [ ] The `join_game` flow also places both a worker and a scout for the joining player
- [ ] All four creation paths (MCP lifecycle, game controller, persistent game controller, CLI) produce consistent starting state
- [ ] CLI `__main__.py` uses the same starting stockpile as all other paths (50 food, 20 wood, 10 ore)
- [ ] Worker HP is 100 across all creation paths and tests
- [ ] All existing tests updated and passing
- [ ] A test verifies both starting units are placed with correct types and positions
