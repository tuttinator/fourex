# Map System Overhaul — PRD

## Problem Statement

Maps in the current game are unsatisfying for both players and AI agents. Three concrete pain points:

1. **Logic bug — unreachable resources.** Mountains are flagged impassable for land units, yet `MINE` improvements are restricted to `MOUNTAIN` and ore spawns there at 50%. Workers cannot enter mountains, so the ore on most mountain tiles is permanently unreachable. Mines are effectively impossible to build under the current generator.

2. **Aesthetics & gameplay variety — pure noise generation.** `generate_map()` rolls each tile independently from a flat probability table (40% plains / 20% forest / 20% mountain / 20% water, with resources sprinkled on top). The result is a featureless static-noise mess: no continents, no rivers, no biomes, no readable shape. Every game looks the same kind of unstructured. There are also four new tile sprites already shipped (`tile-grass.png`, `tile-desert.png`, `tile-hills.png`, `tile-swamp.png`) that the engine cannot represent because the `Terrain` enum only has four values.

3. **No authoring path.** There is no way to design a curated map (balanced, symmetric, scenario, tutorial, etc.) — every game is a fresh procedural roll, and starting positions are random within an inset rectangle. There is no concept of a "map" as a saved, reusable artefact.

These limitations make the game feel arbitrary, undermine strategic agency (every map is equivalent in expectation), prevent us from running designed scenarios, and leak through to the agent harness — the planner cannot rely on terrain shape because there is none.

## Solution

A three-part overhaul, shipped together:

1. **Expanded terrain set + corrected resource rules.** Replace the four-terrain enum with seven biome-aware tile types (`GRASS`, `FOREST`, `HILLS`, `MOUNTAIN`, `DESERT`, `SWAMP`, `WATER`), each with its own movement cost, yield, city-eligibility, and resource-spawn rules. Ore moves to `HILLS` (passable, cost 2). Mountains become resource-free strict obstacles. Mine improvement moves to hills. Existing PNG sprites are wired in.

2. **Parametric map templates.** Replace the single noise-roll generator with a registry of named templates: `random` (legacy), `continent`, `islands`, `river`, `lakes`, `archipelago`. Each template is a deterministic, seed-driven generator that produces both tiles **and** a list of candidate spawn zones tuned to its shape. The lobby UI surfaces the template choice as a drop-down. Starting-unit placement consumes spawn zones rather than rolling random tiles.

3. **Admin-authored saved maps.** A new admin role gains access to a map builder web page where they can paint terrain on a grid, place spawn-zone markers, name the map, and save it. Saved maps live in the database and appear in the same lobby drop-down alongside parametric templates. When a saved map has more spawn zones than the lobby has players, the engine picks a random subset.

Existing games are abandoned (database wipe) — no data migration. The change is shipped as a single PR.

## User Stories

### Players & game creators

1. As a game creator, I want to pick from a drop-down of map templates (e.g. "Continent", "Islands", "River") when I create a lobby, so that I can choose a map shape that fits the kind of game I want.
2. As a game creator, I want a "Random" option in the template list, so that I retain the legacy unstructured-noise behaviour for quick-start games.
3. As a game creator, I want the seed input to keep working with templates, so that I can replay a specific map by sharing the seed + template name.
4. As a game creator, I want each template to scale to my chosen player count (2–8) and map dimensions, so that I do not have to learn which template fits which lobby size.
5. As a game creator, I want to see admin-authored saved maps in the same drop-down as parametric templates, so that I do not have to learn two separate UIs to find a map.
6. As a game creator selecting a saved map, I want the map dimensions to lock to the values baked into that map, so that I cannot accidentally generate a misshaped grid.
7. As a player joining a game on an islands map, I want my starting units placed on a coherent island rather than randomly, so that my opening turns feel like I am exploring a place rather than wandering noise.
8. As a player, I want mountains to look and behave like genuine obstacles (no resources, no improvements, blocking movement), so that the strategic value of avoiding/flanking them matches their visual weight.
9. As a player, I want hills to be the natural home for ore and mines, so that there is a reachable, plannable industrial economy.
10. As a player, I want desert and swamp tiles to feel mechanically distinct (penalised yields, slower swamp movement, etc.), so that biome variety matters strategically rather than just visually.
11. As a player, I want the in-game map renderer to use the new tile sprites (desert, hills, swamp, grass), so that the map is legible at a glance.
12. As a player loading a multi-spawn saved map with fewer players than spawn zones, I want unused spawn zones to remain unowned and explorable, so that the map stays tactically interesting.

### Admins / map authors

13. As an admin, I want a dedicated `/maps` page in the web UI where I can browse and create maps, so that I have a single home for authoring.
14. As an admin, I want a paintable grid where I click/drag to apply a selected terrain to tiles, so that authoring a map feels like using a basic image editor.
15. As an admin, I want a palette of all seven terrain types with their sprites, so that I can pick a brush by visual recognition.
16. As an admin, I want to drop spawn-zone markers on tiles, so that I control where players start on this map.
17. As an admin, I want to set map width and height before painting (or resize an existing draft), so that I can author both small skirmish maps and large epic maps.
18. As an admin, I want to give the map a name and optional description, so that game creators in the lobby drop-down can recognise what they're picking.
19. As an admin, I want my saved maps to be available globally to all game creators, so that I do not have to share them manually.
20. As an admin, I want to edit and delete maps I previously saved, so that I can iterate on a design after playtesting.
21. As an admin, I want validation feedback when I save (e.g. "needs at least 2 spawn zones", "spawn zone is on impassable terrain"), so that I do not publish broken maps.
22. As an admin, I want a starter template (e.g. an empty grass grid, or seeded from a parametric template) when I create a new map, so that I am not always painting from a blank canvas.
23. As an admin, I want spawn zones to be visually distinct from terrain (e.g. coloured pin overlay), so that I can see them while I edit terrain underneath.
24. As an admin, I want a non-admin user attempting to reach the map builder page to be cleanly redirected away, so that the authoring surface stays restricted.

### AI agents (MCP harness)

25. As an AI agent, I want `get_game_state` to return tile terrain values from the expanded enum, so that my planner can reason about the new biomes.
26. As an AI agent, I want `get_rules_reference` to expose the current per-terrain movement costs, yields, city-eligibility, and resource-spawn rules, so that I do not have to hard-code constants that may have changed.
27. As an AI agent, I want the planner profiles to keep working on the new terrain set without code changes (mines auto-target hills instead of mountains, etc.), so that profile-driven self-play still produces valid games.

### Operators

28. As an operator deploying the change, I want existing in-flight games to be wiped during the migration, so that no game persists with the legacy four-terrain shape and confuses the engine.
29. As an operator, I want the admin role to be assignable via a clear mechanism (env var allowlist or a single DB flag), so that I can grant/revoke access without redeploying code.

## Implementation Decisions

### Terrain model

- The `Terrain` enum gains three values and renames one: `GRASS` (replaces `PLAINS`), `FOREST`, `HILLS` (new), `MOUNTAIN`, `DESERT` (new), `SWAMP` (new), `WATER`. All references to `PLAINS` in code, tests, planner profiles, sprites, MCP tool outputs, rules-reference, and improvement-validity tables migrate to `GRASS`.
- Per-terrain mechanics:
  - `GRASS`: passable, entry cost 1, can host cities, food resource spawns here.
  - `FOREST`: passable, entry cost 2 (scout ignores), can host cities, wood resource spawns here, defensive bonus retained.
  - `HILLS`: passable, entry cost 2, can host cities, ore resource spawns here, mines build here.
  - `MOUNTAIN`: impassable, no resources, no improvements, no city placement.
  - `DESERT`: passable, entry cost 1, can host cities, no food yield, crystal resource may spawn (rare).
  - `SWAMP`: passable, entry cost 3, cannot host cities, no yield bonus.
  - `WATER`: impassable to land units (current behaviour preserved).
- The bug fix is structural: `MOUNTAIN` is removed from `MINE.valid_terrain`, replaced by `HILLS`. Resource-spawn rules in the generator never place ore on mountains. Mountains are guaranteed resource-free.
- City-placement validity is updated to gate on the new terrain set in both the rules layer and the queueable-tiles helper.

### Map generation

- `generate_map(width, height, seed)` is replaced by a registry-driven entry point: a `generate_map(template, width, height, seed, player_count)` function dispatches to a per-template generator. Each generator returns `(tiles, spawn_zones)` where `spawn_zones` is a list of `Coord` candidates.
- Templates implemented in v1: `random` (current independent-roll behaviour, retained as escape hatch), `continent` (one big landmass, water margins), `islands` (N landmasses sized to player count), `river` (continent split by a vertical or horizontal water strip), `lakes` (mostly land with scattered water bodies), `archipelago` (mostly water with small island clusters).
- All templates remain deterministic: same `(template, width, height, seed, player_count)` produces identical tiles and identical spawn-zone ordering.
- Biome distribution within a template uses noise (e.g. value-noise / Perlin-ish from seeded RNG) so that grass/forest/hills/desert/swamp form coherent regions, not pixel static.
- Per-template guarantees: at least `player_count` valid spawn zones, each spawn zone on passable, city-eligible terrain, with a configurable minimum inter-zone distance.

### Starting-unit placement

- `place_starting_units` is refactored to accept a list of pre-computed spawn coords (one per player) rather than rolling its own random tile. The existing margin/min-distance/random-fallback logic moves into the per-template spawn-zone generators.
- For saved maps with more spawn zones than players, a seeded random subset of the requested size is selected. The selection is deterministic given `(seed, player_count)`.
- For saved maps with fewer spawn zones than players, the lobby creation request fails with a clear error.

### Saved maps (DB-backed)

- New `saved_maps` table with: `id`, `name` (unique), `description`, `width`, `height`, `tiles` (JSON array of `{x, y, terrain, resource}`), `spawn_zones` (JSON array of `{x, y}`), `created_by` (FK to `user_identities`), `created_at`, `updated_at`.
- Saved-map identifiers in the lobby flow are namespaced (e.g. `saved:<id>`) so that the existing "template name" string can carry both parametric and saved-map selections without a schema split.
- When a saved map is selected, the lobby request's `map_width`/`map_height` are ignored (server overrides them with the saved-map dimensions). `seed` still controls spawn-subset randomness and any post-load randomisation hooks (e.g. resource jitter, if added later).

### Admin role

- `UserIdentity` gains an `is_admin: bool` column (default `false`).
- Admin assignment is bootstrapped via an env-var allowlist: a comma-separated list of admin emails. On Auth.js verify, the server stamps `is_admin = true` for any identity whose email is in the allowlist, and `false` otherwise. This is idempotent — the flag re-syncs on every login, so removing an email from the allowlist demotes the user on their next sign-in.
- A new `/api/v1/me` endpoint (or an `is_admin` field on the existing identity endpoint) exposes the flag to the frontend so the navbar can show/hide the `Maps` link.
- All map-builder endpoints (`POST /api/v1/maps`, `PATCH /api/v1/maps/{id}`, `DELETE /api/v1/maps/{id}`) require `is_admin = true`. `GET /api/v1/maps` (list) is open to any authenticated user so the lobby drop-down can populate.

### Map builder UI

- New page at `/maps` (list) and `/maps/new`, `/maps/[id]/edit` (editor), restricted to admins via an `is_admin` guard on the layout/route.
- Editor uses a Pixi.js or canvas-based grid (consistent with the in-game map renderer) showing terrain sprites at editor-appropriate zoom.
- Tools palette: terrain-brush (one button per terrain type), spawn-zone marker, eraser. Click and click-drag both paint.
- Sidebar form: name, description, width/height (resize is destructive — clamps existing tile data), spawn-zone list with click-to-focus.
- Save validates server-side: at least 2 spawn zones, all spawn zones on passable + city-eligible terrain, dimensions within global limits (10–100 each).
- The list page shows all saved maps with a thumbnail, name, dimensions, spawn count, author email, and edit/delete actions.

### Lobby integration

- `CreateLobbyRequest` gains a `map_template: str` field (default `"random"`). Values are: parametric template names or `"saved:<id>"`.
- `GameDetailResponse` echoes the chosen `map_template` so the lobby UI can display it.
- The lobby front-end's create-game form replaces the seed-only flow with a template drop-down (parametric templates listed first, then a separator, then saved maps by name). Width/height inputs disable when a saved map is selected.

### Frontend rendering

- `sprite-atlas.ts` extends `TERRAIN_SPRITE_URLS` with entries for grass, hills, desert, swamp (PNG), and re-points the existing forest/mountain/water entries to match (PNG vs SVG to be aligned across the set).
- The `Terrain` TypeScript type adds the three new values and renames `plains` → `grass`. Anywhere the renderer keys off terrain (tinting, hover tooltip, side-panel info) is updated.
- `globals.css` terrain colour helpers expand to cover the new values (used as fallback while sprites load).

### MCP / agents

- The `get_rules_reference` tool publishes the new per-terrain table (movement cost, yield, city-eligible, resource spawn). Agents reading it gain awareness of the new biomes for free.
- The deterministic planner in `backend/src/agents/planner.py` is updated so that improvement targeting (mines, farms, lumber mills, crystal extractors) keys off the new `valid_terrain` lists.
- Profile-driven self-play smoke tests are extended to cover at least one game per template to catch regressions where a template starves a profile of viable resource tiles.

### Database migration

- A single Alembic migration adds the `saved_maps` table, adds `is_admin` to `user_identities`, and **drops all existing game and snapshot data** (truncate `games`, `game_snapshots`, `lobby_*` tables, and any FK-dependent rows). This is acceptable per product decision: there is no production user load to preserve.

## Out of Scope

- Hex grids, true 3D terrain elevation, line-of-sight changes — square grid + Manhattan distance + flat fog stays.
- Per-user (non-admin) saved maps. Authoring is admin-only in v1.
- Map sharing/import/export (e.g. JSON file upload, public gallery, ratings, comments).
- Tournament-grade balance verification tooling (mirroring, fairness metrics, automated symmetry checks).
- Procedural rivers as flowing water that splits tiles or runs along edges. The `river` template uses straight tile-aligned water strips.
- Editing live game state ("god mode"). The map builder edits map definitions, not in-flight games.
- Migrating existing games to the new terrain set. Old games are wiped.
- New resource types or new improvement types. Resources and improvements stay as-is — only their terrain-validity tables change.
- Civ-style continents-with-coastlines smoothing, beaches, or shore tiles. Land/water is a binary boundary at tile granularity.
- A separate "scenario" concept (preset starting units/cities/research). Saved maps define terrain + spawn zones only.
- Admin role escalation beyond the env-var allowlist (no UI for granting admin, no per-resource ACLs).

## Further Notes

- **Determinism remains the load-bearing property.** Every change preserves the invariant that `(template, width, height, seed, player_count)` and saved-map-plus-seed inputs reproduce identical games. This is what keeps replay, self-play smoke tests, and agent debugging viable. Reviewers should resist any "small randomisation" sprinkled outside the seeded RNG.
- **Sprite consistency.** The new tiles ship as PNGs; the existing terrain sprites are SVGs. We should pick one format per renderer (likely PNG across the board for tile art) and align in the same PR — having two render paths invites bugs.
- **Spawn-zone semantics.** A spawn zone is a single tile that the engine treats as a candidate worker placement. The accompanying scout placement still uses the existing cardinal-search logic anchored at the worker tile, so spawn zones do not need to encode scout positions.
- **Movement cost = 3 for swamp** is a noticeable nerf; agents that path-find through swamp will be punished heavily. The planner's pathing already respects per-terrain cost via `TERRAIN_ENTRY_COST`, so no new logic is needed, but self-play tests should sanity-check that swamp-heavy templates do not deadlock economic profiles.
- **Admin allowlist via env.** Encoding admin membership in an env var (not the DB as a source of truth) means the app deployment is the single place admin status is granted. The DB column is a cache/mirror that's refreshed on login. This keeps "who is admin" auditable in deployment config.
- **Future hooks worth designing for, but not implementing now.** A `tags: string[]` column on `saved_maps` (for filters like "1v1", "ffa", "tutorial") would be cheap to add later. The `map_template` string field on the lobby is intentionally a string, not an enum, so adding new parametric templates or namespaces (`scenario:<id>`, `community:<id>`) later does not require a schema change.
