# PRD: Gameplay Dynamics — Economy, Territory, Victory & Healing

## Problem Statement

The 4X game engine has the structural bones of a strategy game but the gameplay dynamics are shallow and broken in practice. Playing a test game revealed several critical gaps:

- **The economy is glacially slow.** Cities produce a flat 1 food/turn with no way to scale production. Training a single worker costs 30 food — 30 turns of waiting with one city. There is no passive resource collection from the map, making city placement strategically irrelevant.
- **There is no territorial control.** Cities only own the tile they sit on. There are no borders, no cultural expansion, and no way to claim land. Improvements require tile ownership to generate resources, but there is no mechanism to acquire ownership beyond founding a city.
- **There are no victory conditions.** Games run to `max_turns` and stop. There is no domination, economic, or score-based win state. Players cannot be eliminated. The game has no end goal.
- **Wood is a dead resource.** Starting stockpiles of wood are the only source. There is no wood-producing improvement and no passive wood generation. Once spent, wood is gone forever.
- **Units never heal.** Damaged units remain damaged permanently. Combat is pure attrition with no recovery, making military engagements a one-way ratchet toward mutual destruction.

These gaps make the game unsuitable as a meaningful testbed for AI agent decision-making — agents have nothing to optimise for, no economy to manage, and no strategic territory to contest.

## Solution

Introduce five interconnected gameplay systems that transform the engine from a movement-and-combat prototype into a functional 4X game with strategic depth:

1. **Cultural borders and territorial expansion** — Cities accumulate culture points and expand their borders over time. Cultural buildings (Monument, Library, Temple) accelerate expansion. Territory is the foundation for the economy.
2. **City tile yields** — Cities passively collect resources from all tiles within their borders. Resource tiles yield their resource type; improvements boost yields. City placement and border expansion become the primary strategic levers.
3. **Victory conditions** — Four configurable win conditions: domination (last player with a city), economic (1000 total resources in stockpile), elimination (lose last city/unit), and score-based (highest score at turn limit). Domination takes priority when multiple conditions trigger simultaneously.
4. **Lumber mill improvement** — A new improvement type for forest tiles that produces wood, completing the resource improvement cycle (farm/mine/lumber mill/crystal extractor).
5. **Unit healing** — Units heal passively when stationary in friendly territory. Scouts are excluded (disposable reconnaissance units).

## User Stories

1. As a player, I want my city to automatically claim nearby tiles as its borders expand, so that I can build improvements and collect resources from the surrounding land.
2. As a player, I want to build a Monument in my city to generate culture, so that my borders expand faster in the early game.
3. As a player, I want to build a Library in my city to generate more culture, so that I can accelerate mid-game territorial expansion.
4. As a player, I want to build a Temple in my city to generate the most culture, so that I can push my borders to maximum range in the late game.
5. As a player, I want my cultural buildings to stack (Monument + Library + Temple), so that investing in all three gives a meaningful culture advantage.
6. As a player, I want my city's borders to expand at culture thresholds (10, 30, 60), so that expansion feels like a progression with clear milestones.
7. As a player, I want border conflicts resolved by first-to-reach, so that early expansion and city placement are rewarded.
8. As a player, I want a newly founded city to start with radius 0 (only the city tile), so that border expansion is a earned progression, not a freebie.
9. As a player, I want my city to collect resources from all tiles within its borders, so that territorial expansion directly strengthens my economy.
10. As a player, I want unimproved resource tiles within my borders to yield +1 of their resource per turn, so that city placement near resources matters from the start.
11. As a player, I want forest tiles within my borders to passively yield +1 wood per turn, so that forests are valuable territory.
12. As a player, I want improvements to boost tile yields (e.g. farm on food tile = +3 food/turn total), so that investing in improvements has a clear economic payoff.
13. As a player, I want to build a lumber mill on any forest tile I own, so that I can produce wood to fund further construction.
14. As a player, I want each tile to belong to exactly one city (no overlapping borders), so that territory is clearly delineated.
15. As a player, I want to win by domination (being the last player with at least one city), so that military conquest is a viable strategy.
16. As a player, I want to win by economic victory (reaching 1000 total resources in my current stockpile), so that peaceful economic play is a viable strategy.
17. As a player, I want players to be eliminated when they lose their last city, so that conquest has permanent consequences.
18. As a player, I want players who haven't founded a city yet to be eliminated if their worker is killed, so that early aggression can knock out opponents.
19. As a player, I want the game to calculate scores at the turn limit (based on cities, units, resources, territory), so that games that reach the time limit have a clear winner.
20. As a player, I want to select which victory conditions are enabled when creating a game, so that I can tailor the game mode to my preference.
21. As a player, I want all four victory conditions enabled by default, so that games are rich and multi-dimensional out of the box.
22. As a player, I want domination to take priority when multiple victory conditions trigger on the same turn, so that there is no ambiguity.
23. As a player, I want my units to heal +1 HP per turn when stationary in friendly territory, so that I can recover from combat without training replacement units.
24. As a player, I want scouts to not heal passively, so that they remain disposable fast-moving reconnaissance units.
25. As a player, I want healing to not consume resources, so that recovery is a function of strategic positioning, not economic capacity.
26. As a player, I want eliminated players' improvements to be destroyed, so that conquered territory requires reinvestment to exploit.
27. As a player, I want eliminated players' tiles to become unowned, so that surviving players can claim the land through cultural expansion.
28. As an AI agent, I want victory conditions to be queryable via MCP tools, so that I can evaluate progress toward different win states.
29. As an AI agent, I want territorial information included in game state, so that I can reason about border expansion and contested regions.
30. As an AI agent, I want resource yield projections available, so that I can evaluate the economic value of different expansion paths.

## Implementation Decisions

### Culture and Territory System

- Culture is accumulated **per city**, not globally per player. Each city tracks its own culture points and expands its own borders independently.
- Cities produce a small amount of base culture passively (1/turn) and cultural buildings boost this:
  - **Monument**: +1 culture/turn (total 2 with base). Cost: 20 wood.
  - **Library**: +2 culture/turn (total 3 with base, or 5 with Monument). Cost: 30 wood + 10 ore.
  - **Temple**: +3 culture/turn (total 4 with base, or 8 with all buildings). Cost: 30 wood + 20 ore + 10 crystal.
- All three cultural buildings can coexist in a city (they stack). Maximum culture output with all three: 1 (base) + 1 + 2 + 3 = **7 culture/turn**.
- Border expansion thresholds (cumulative culture required):
  - **Radius 0** (city tile only): starting state.
  - **Radius 1** (Manhattan distance 1, up to 4 tiles): 10 culture.
  - **Radius 2** (Manhattan distance 2, up to 12 tiles): 30 culture.
  - **Radius 3** (Manhattan distance 3, up to 24 tiles): 60 culture.
- Newly founded cities start at radius 0.
- Border conflicts are resolved **first-to-reach** — the first city whose culture threshold claims a tile owns it permanently. No tile can belong to two cities.
- When a player is eliminated, all their tiles become unowned, all improvements on those tiles are destroyed, and all their cities are removed.

### City Tile Yields

- Cities collect resources from **all tiles within their cultural borders** at end of turn, during `collect_resources()`.
- Base yields for unimproved tiles within borders:
  - Food resource tile: +1 food/turn
  - Wood resource tile: +1 wood/turn
  - Ore resource tile: +1 ore/turn
  - Crystal resource tile: +1 crystal/turn
  - Forest tile (no wood resource): +1 wood/turn
  - Plains tile (no resource): +0
  - Water/mountain tiles: cannot be owned, +0
- Improved tile yields (base + improvement bonus, stacked):
  - Farm on food tile: +3 food/turn
  - Mine on ore tile: +3 ore/turn
  - Lumber mill on forest tile: +3 wood/turn
  - Crystal extractor on crystal tile: +2 crystal/turn (crystal is rarer, lower bonus)
- Each tile belongs to exactly one city. No overlapping borders, no double-collection.
- The existing flat +1 food/turn base city production remains (representing the city's own food production independent of territory).

### Improvement Costs

- **Farm**: 10 wood. Built by worker on a food resource tile within owned territory.
- **Mine**: 10 wood. Built by worker on an ore resource tile within owned territory.
- **Lumber mill**: 10 ore. Built by worker on any forest tile within owned territory. (Ore cost avoids circular wood-for-wood.)
- **Crystal extractor**: 10 ore + 5 crystal. Built by worker on a crystal resource tile within owned territory.

### Victory Conditions

- Four victory conditions, all enabled by default. Selectable at game creation via a list of enabled conditions.
- **Domination**: Last player with at least one city wins. Takes priority over all other conditions when multiple trigger on the same turn.
- **Economic**: A player wins when their current stockpile totals >= 1000 across all resource types (food + wood + ore + crystal). Spending resources delays victory — this creates tension between investing and winning.
- **Elimination**: A player is eliminated when they lose their last city. If a player has not yet founded a city, they are eliminated when their last unit is killed. Eliminated players' territory becomes unowned and their improvements are destroyed.
- **Score at turn limit**: When `max_turns` is reached, the player with the highest score wins. Score is a weighted sum of cities, units, resources, and territory (exact weights to be determined during implementation, but cities and territory should be weighted highest).
- Victory is checked at the end of each turn, after all actions resolve and resources are collected.

### Unit Healing

- Units heal **+1 HP per turn** when stationary (did not move this turn) and located on a tile owned by their player (friendly territory).
- **Scouts do not heal passively.** They are disposable reconnaissance units with 2 HP.
- Healing does not consume any resources.
- Healing is applied during turn resolution, after actions resolve but before (or alongside) resource collection.
- Units cannot heal above their maximum HP.

### Lumber Mill

- New improvement type: `LUMBER_MILL`.
- Can be built on **any forest tile** (with or without a wood resource), as long as the tile is within the building player's territory.
- Produces +2 wood/turn as improvement bonus (total +3 on a forest tile with the +1 base yield from the forest).
- Cost: 10 ore.
- Follows the same worker-consumed-on-build pattern as other improvements.

### Sequential Turn Resolution

- The existing sequential player-order action resolution is retained as a deliberate design choice. Player 1's actions resolve before Player 2's. This is a core feature, not a bug.

## Out of Scope

- **Diplomacy system changes**: The existing diplomacy model (alliance states) is unchanged. No new diplomatic actions (trade, war declarations, treaties).
- **New unit types**: No new military or civilian units. The existing scout/worker/soldier/archer roster is sufficient.
- **Tech tree or research**: No technology system. Culture is not a tech tree — it only drives border expansion.
- **Trade routes or inter-city connections**: Cities are independent economic units.
- **Map generation changes**: Terrain distribution and resource placement are unchanged.
- **Fog-of-war changes**: Visibility rules are unchanged.
- **Agent AI changes**: Agent profiles, memory, and decision-making are not modified. Agents will interact with new mechanics through existing MCP tools (updated to expose new state).
- **Frontend changes**: The Next.js UI is not updated as part of this work.

## Further Notes

- These five features are tightly coupled. Culture/territory must be implemented first, as tile yields and improvement building both depend on tile ownership. The suggested implementation order is: (1) culture & borders, (2) tile yields, (3) lumber mill & improvement costs, (4) victory conditions, (5) healing.
- The economic victory threshold of 1000 may need tuning after playtesting. With a well-developed economy (3 cities, improved tiles), a player might generate 20-30 resources/turn, making economic victory achievable around turn 40-50 — roughly aligned with the default 50-turn game length.
- The culture thresholds (10, 30, 60) assume 1-7 culture/turn per city. A city with only base culture reaches radius 1 at turn 10, radius 2 at turn 30, radius 3 at turn 60. With all three cultural buildings, those milestones drop to roughly turns 2, 5, and 9. This creates a strong incentive to invest in cultural buildings early.
- Worker consumption on improvement building means workers are a recurring cost. At 30 food per worker, players must balance unit production between workers (economic) and military units (defensive/offensive). This is intentional tension.
- The "first-to-reach" border conflict rule means that early city placement and cultural investment create permanent territorial advantages. This rewards proactive expansion over turtling.
