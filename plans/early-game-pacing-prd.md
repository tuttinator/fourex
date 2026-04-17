# Early Game Pacing & Economy Rebalance PRD

## Problem Statement

The 4X game suffers from a severe early-game pacing problem. After founding a city on turn 0, players enter a ~10-20 turn "dead zone" where they have no meaningful decisions to make. Cities start at border radius 0 (owning only the city tile), generating just 1 food/turn base income. Workers are consumed when building tile improvements, making them prohibitively expensive for one-time-use. Unit and building costs are too high relative to income, meaning players wait 20-30 turns to afford basic units like soldiers or workers.

This problem is acute for both human players and AI agents. Human players find the early game boring with no choices. AI agents waste API calls and tokens observing turns where nothing happens. The game is designed as an AI agent research sandbox, so pacing must support fast, decision-rich gameplay from turn 1.

During a test game, the following timeline was observed:
- Turn 0: Found city, remaining resources nearly depleted
- Turns 1-6: No affordable actions, slowly accumulating food at 1/turn
- Turn 7: Borders finally expand to radius 1, income starts trickling
- Turn 17: Borders reach radius 2, income meaningfully improves
- Turn 19-20: First soldier trained (~20 turns after city founding)

A 100-turn game should not have 20% of its duration be effectively idle.

## Solution

Rebalance the early game economy through five coordinated changes:

1. **Immediate border radius 1** — cities claim adjacent tiles the moment they are founded, providing tile yields from turn 1.
2. **Workers survive improvements** — workers are only consumed when founding cities, not when building tile improvements. This makes workers a lasting investment that can improve multiple tiles.
3. **Two starting units** — each player begins with a worker and a scout on adjacent tiles, enabling simultaneous city founding and exploration from turn 0.
4. **Halved costs** — unit costs, building costs, and improvement costs are all reduced by approximately 50%, bringing the time-to-first-unit down from ~20 turns to ~5-10 turns.
5. **Increased base income** — base city food production increases from 1 to 2 per turn, and mountains/water tiles within borders can now be owned (providing ore/crystal yields from mountains).
6. **Reduced culture thresholds** — border expansion occurs sooner, with radius 1 immediate, radius 2 at 15 culture, and radius 3 at 40 culture.

Together, these changes compress the "build-up" phase from ~20 turns to ~5 turns and increase the number of meaningful decisions per turn throughout the game.

## User Stories

1. As a player, I want my city to own adjacent tiles immediately when founded, so that I start earning resource yields from turn 1 instead of waiting for culture to accumulate.
2. As a player, I want my worker to survive after building a tile improvement, so that I can improve multiple tiles with a single worker investment.
3. As a player, I want my worker to be consumed only when founding a new city, so that city founding feels like a meaningful strategic sacrifice.
4. As a player, I want to start the game with both a worker and a scout, so that I can found my city and explore the map simultaneously on turn 0.
5. As a player, I want my starting scout to spawn on an adjacent tile to my worker, so that both units can act independently from the first turn.
6. As a player, I want unit training costs to be roughly half the current values, so that I can build my first military unit within 5-10 turns rather than 20-30.
7. As a player, I want building construction costs to be roughly half the current values, so that early buildings like Monuments and Libraries are affordable in the first few turns.
8. As a player, I want tile improvement costs to be roughly half the current values, so that improving my territory is a viable early-game strategy.
9. As a player, I want my city to produce 2 base food per turn instead of 1, so that early resource accumulation is faster and I have more frequent decision points.
10. As a player, I want mountain tiles within my borders to be owned by my city, so that ore and crystal resources on mountains contribute to my income.
11. As a player, I want water tiles within my borders to be owned by my city, so that border shapes feel natural and contiguous rather than having holes.
12. As a player, I want border radius 2 to be achievable around turn 7-8 with a Monument, so that mid-game territorial expansion happens in the first quarter of the game.
13. As a player, I want border radius 3 to be achievable around turn 20 with culture buildings, so that full territorial control is a late-first-half achievement rather than a late-game one.
14. As a player, I want my worker to retain remaining movement points after building an improvement, so that a worker can build and reposition in the same turn.
15. As an AI agent, I want meaningful action choices available on most turns, so that my reasoning and planning capabilities are exercised rather than wasted on idle turns.
16. As an AI agent, I want the early game to offer genuine strategic trade-offs (e.g. improve tiles vs. train units vs. build culture), so that different strategic personalities lead to divergent early games.
17. As a game observer, I want the early game to have visible progress each turn (units moving, tiles being improved, buildings constructed), so that spectating is engaging from the start.
18. As a player, I want the Granary's +50% food bonus to be meaningful on the higher base food, so that building a Granary is an impactful economic decision.
19. As a player, I want the Barracks' -25% cost reduction to apply to the new halved unit costs, so that military-focused strategies are further rewarded.

## Implementation Decisions

### Border Expansion

- Culture thresholds change from `{1: 10, 2: 30, 3: 60}` to `{1: 0, 2: 15, 3: 40}`.
- When a city is founded, `_expand_borders` is called immediately to claim radius 1 tiles.
- The terrain filter in `_expand_borders` is removed — water and mountain tiles can now be owned. They still cannot have cities or tile improvements built on them (mountains can still have mines on ore tiles as currently designed).
- Water tiles with no resource yield nothing; mountain tiles without resources yield nothing. Mountain tiles with ore/crystal yield their resource as normal through `_calculate_tile_yield`.

### Worker Lifecycle

- Workers are no longer consumed when executing `BUILD_IMPROVEMENT`. The worker remains on the tile after building. The lines that delete the worker and clear the tile's `unit_id` are removed from `execute_build_improvement`.
- Workers are still consumed when executing `FOUND_CITY` (unchanged).
- Building an improvement does not consume the worker's remaining moves — they can continue moving after building. This means `BUILD_IMPROVEMENT` should not cost any movement points (the resource cost is sufficient).

### Starting Units

- Each player spawns with two units: a worker and a scout.
- The worker spawns on the designated starting tile (as currently).
- The scout spawns on an adjacent passable tile (not water, not mountain). The placement logic should try cardinal directions in order (N, E, S, W) and pick the first valid tile.
- This applies to all game creation paths: MCP server lifecycle, game controller, persistent game controller, and the CLI `__main__` entry point.

### Cost Rebalancing

**Unit costs (approximately halved):**
- Scout: 20 food → 10 food
- Worker: 30 food → 15 food
- Soldier: 30 food + 10 ore → 15 food + 5 ore
- Archer: 30 food + 10 wood → 15 food + 5 wood

**Building costs (approximately halved):**
- Granary: 40 wood → 20 wood
- Barracks: 50 wood → 25 wood
- Walls: 40 ore → 20 ore
- Monument: 20 wood → 10 wood
- Library: 30 wood + 10 ore → 15 wood + 5 ore
- Temple: 30 wood + 20 ore + 10 crystal → 15 wood + 10 ore + 5 crystal

**Improvement costs (approximately halved):**
- Farm: 20 wood → 10 wood
- Mine: 20 wood → 10 wood
- Lumber Mill: 10 wood → 5 wood
- Crystal Extractor: 20 wood + 10 ore → 10 wood + 5 ore

**City founding cost (halved):**
- Found City: 30 food → 15 food

**Starting stockpile (unchanged):**
- 50 food, 20 wood, 10 ore, 0 crystal

### Base Income

- Base city food production increases from 1 to 2 per turn (before Granary multiplier).
- Tile yields are unchanged — food tiles still yield +1, improved food tiles +3, etc.

### Existing Tests

- All existing tests that assert on specific resource values, culture thresholds, unit costs, or border expansion timing will need to be updated to reflect the new values.
- Tests that verify worker consumption on improvement building will need to be updated to verify worker survival instead.

## Out of Scope

- **Diplomacy mechanics** (alliances, resource trading, shared vision) — will be a separate PRD.
- **New unit types or building types** — this PRD only rebalances existing ones.
- **Map generation changes** — terrain distribution, resource density, and map size are not addressed.
- **Victory condition rebalancing** — the economic victory threshold (1000 total resources) may need adjustment after these changes, but that is deferred.
- **AI agent personality tuning** — agent strategies may need rebalancing for the new economy, but that is outside this scope.
- **Frontend/UI changes** — no visual changes are required; the frontend already renders whatever state the backend provides.

## Further Notes

- The economic victory threshold of 1000 total resources will likely be too easy with faster income. A follow-up tuning pass should evaluate whether this needs increasing.
- The Granary's +50% food bonus now applies to 2 base food (yielding 3) rather than 1 (yielding 1, since `int(1 * 1.5) = 1`). This is an intentional improvement — the Granary was effectively useless before due to integer truncation.
- These changes are intentionally aggressive. The philosophy is that a 100-turn game should have meaningful decisions on nearly every turn. If the game feels too fast after these changes, individual values can be tuned upward — but the structural changes (immediate borders, worker survival, two starting units) should remain.
- All four game creation paths (MCP lifecycle, game controller, persistent game controller, CLI `__main__`) must be updated consistently. Consider extracting shared constants for starting stockpiles and starting unit placement to avoid future drift.
