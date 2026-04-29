# Plan: Map System Overhaul

> Source PRD: `plans/map-system-overhaul-prd.md`

## Architectural decisions

Durable decisions that apply across all phases:

- **Terrain enum**: `GRASS, FOREST, HILLS, MOUNTAIN, DESERT, SWAMP, WATER` (7 values; `PLAINS` is renamed to `GRASS`).
- **Per-terrain mechanics** (load-bearing across phases):
  - `GRASS`: passable cost 1, city-eligible, food spawns.
  - `FOREST`: passable cost 2 (scout ignores), city-eligible, wood spawns.
  - `HILLS`: passable cost 2, city-eligible, ore spawns, mines build here.
  - `MOUNTAIN`: impassable, no resources, no improvements, no cities.
  - `DESERT`: passable cost 1, city-eligible, no food yield, rare crystal.
  - `SWAMP`: passable cost 3, no city, no yield bonus.
  - `WATER`: impassable to land units.
- **Map generation API**: `generate_map(template, width, height, seed, player_count) -> (tiles, spawn_zones)`. Registry-driven dispatch. Always deterministic on its inputs.
- **Spawn zones**: a list of `Coord` candidates returned alongside tiles. Starting-unit placement consumes spawn zones (one per player) rather than rolling its own random tile.
- **Lobby template field**: `CreateLobbyRequest.map_template: str` (default `"random"`). Parametric templates use bare names (`continent`, `islands`, ...). Saved maps use `saved:<id>` namespace. Field stays a string so future namespaces (`scenario:<id>`) are additive.
- **Saved-map dimensions**: when `map_template` starts with `saved:`, the server overrides `map_width` / `map_height` with the saved map's dimensions; the lobby UI disables those inputs.
- **Spawn subset rule**: if `len(spawn_zones) > player_count`, the engine picks a deterministic random subset seeded by `(seed, player_count)`. If `len(spawn_zones) < player_count`, lobby creation fails with a clear error.
- **Routes (frontend)**:
  - `/maps` — admin-only list of saved maps.
  - `/maps/new` — admin-only blank-canvas editor.
  - `/maps/[id]/edit` — admin-only edit existing map.
- **Routes (REST)**:
  - `GET /api/v1/maps` — list saved maps (any authenticated user).
  - `POST /api/v1/maps` — create (admin only).
  - `PATCH /api/v1/maps/{id}` — update (admin only).
  - `DELETE /api/v1/maps/{id}` — delete (admin only).
  - `GET /api/v1/me` — current identity, includes `is_admin` flag.
- **Schema additions**:
  - `user_identities.is_admin: bool` (default `false`).
  - New `saved_maps` table: `id, name (unique), description, width, height, tiles (jsonb), spawn_zones (jsonb), created_by (fk → user_identities.id), created_at, updated_at`.
- **Admin assignment**: env-var allowlist (comma-separated emails). Auth.js verify re-syncs `is_admin` on every login — adding/removing emails takes effect on the user's next sign-in.
- **Determinism invariant**: `(template, width, height, seed, player_count)` and saved-map-plus-seed must reproduce identical games end-to-end. No randomisation outside the seeded RNG.
- **Migration policy**: existing games and snapshots are wiped in a single Alembic migration. No backfill of legacy `PLAINS` terrain.

---

## Phase 1: Terrain expansion + ore-on-mountain fix + sprites + DB wipe

**User stories**: 8, 9, 10, 11, 25, 26, 27, 28

### What to build

The foundational engine and rendering change. Expand the `Terrain` enum to seven values, fix the resource-on-impassable-terrain bug (move ore to `HILLS`, move the `MINE` improvement's valid-terrain to `HILLS`, guarantee mountains are resource-free), and update every layer that names terrain by string: rules tables (entry cost, valid improvements, city eligibility), the legacy `random` generator (so it emits the new tiles), the deterministic planner's improvement-targeting logic, the rules-reference output consumed by `get_rules_reference`, the frontend sprite atlas (wire in the new PNGs for all 7 terrains), and any TypeScript types / CSS fallbacks. Ship a single Alembic migration that drops all existing game and snapshot data so no record of legacy terrain survives. The lobby flow is untouched in this phase — games still create with the legacy entry point and produce noise maps, but on the new tile set with correctly-placed ore.

### Acceptance criteria

- [ ] `Terrain` enum has exactly the seven canonical values; no code path references `PLAINS`.
- [ ] No tile with `terrain == MOUNTAIN` ever has a `resource` set, in any generated map.
- [ ] `MINE` improvement's valid-terrain list is `[HILLS]` (not `[MOUNTAIN]`).
- [ ] Per-terrain entry cost, city eligibility, and resource-spawn rules match the table in the PRD's per-terrain mechanics list.
- [ ] The deterministic planner builds mines on hills (not mountains) in profile-driven self-play, with no regression in profile win/loss counts vs. baseline random opponents.
- [ ] The frontend renderer displays the correct sprite for each of the seven terrains in a freshly-created game.
- [ ] `get_rules_reference` publishes the new per-terrain table.
- [ ] The Alembic migration applies cleanly on a non-empty DB and leaves the games / snapshots / lobby tables empty.
- [ ] Existing test suites (backend, frontend type-check + lint + vitest + build) pass.

---

## Phase 2: Map template registry + parametric templates + lobby drop-down + spawn-zone-aware placement

**User stories**: 1, 2, 3, 4, 7

### What to build

Replace the single noise-roll generator with a registry-driven `generate_map(template, width, height, seed, player_count)` entry point that dispatches to per-template generators and returns `(tiles, spawn_zones)`. Ship all six parametric templates in v1: `random` (legacy noise behaviour, retained), `continent`, `islands`, `river`, `lakes`, `archipelago`. Each generator must produce coherent biome regions (not pixel static), guarantee at least `player_count` valid spawn zones on passable + city-eligible terrain at a minimum inter-zone distance, and remain deterministic on its inputs. Refactor `place_starting_units` to accept pre-computed spawn coords (one per player) rather than rolling its own random tile; the per-player scout fan-out logic is preserved. Plumb a `map_template: str` field through `CreateLobbyRequest` (default `"random"`) and through `GameDetailResponse`. Update the lobby create-game form to render a template drop-down listing the six parametric options.

### Acceptance criteria

- [ ] `generate_map` accepts a template name and player count, dispatches via the registry, and returns `(tiles, spawn_zones)`.
- [ ] Each of `random`, `continent`, `islands`, `river`, `lakes`, `archipelago` is implemented and registered.
- [ ] For every template, every spawn zone returned is on passable + city-eligible terrain.
- [ ] For every template, the same `(template, width, height, seed, player_count)` produces identical tile data and identical spawn-zone ordering across runs.
- [ ] `place_starting_units` consumes spawn zones; no random fallback path is exercised on a healthy template.
- [ ] `CreateLobbyRequest.map_template` is honoured by the controller; `GameDetailResponse` echoes it.
- [ ] The lobby UI's create-game form renders a template drop-down with all six options and submits the selection correctly.
- [ ] Profile-driven self-play completes a full game on each of the six templates without deadlock or invalid-action errors.

---

## Phase 3: Admin role

**User stories**: 24, 29

### What to build

Introduce the admin concept end-to-end. Add `is_admin: bool` (default `false`) to `user_identities` via Alembic migration. Add an env-var allowlist of admin emails that the Auth.js verify path consults on every login: matching identities have `is_admin` set to `true`, non-matching identities are reset to `false` (so removing an email demotes the user on next sign-in). Expose `is_admin` on a `GET /api/v1/me` endpoint. Add an admin-only `Maps` link to the navbar that renders only when the current identity is admin. Add a route guard on `/maps` (the page itself can be a placeholder this phase) that redirects non-admins. End-to-end: an admin signs in and sees the link; a non-admin signs in and does not.

### Acceptance criteria

- [ ] `user_identities.is_admin` column exists and defaults to `false`.
- [ ] On Auth.js verify, the column is set to `true` iff the email is in the configured allowlist; otherwise set to `false`.
- [ ] `GET /api/v1/me` returns `is_admin` for the authenticated caller.
- [ ] The frontend navbar shows the `Maps` link iff `is_admin` is true.
- [ ] Visiting `/maps` as a non-admin redirects them away (e.g. to home).
- [ ] Visiting `/maps` as an admin renders a placeholder page (to be filled in Phase 4/5).
- [ ] Removing an email from the allowlist demotes that user on their next sign-in (verified by integration test or manual check).

---

## Phase 4: Saved maps backend + lobby integration

**User stories**: 5, 6, 12, 19, 20, 21

### What to build

Make saved maps a first-class lobby option, with no UI yet. Create the `saved_maps` table per the schema decision. Implement REST endpoints: `GET /api/v1/maps` (list, open to any authenticated user), `POST /api/v1/maps` (create, admin only), `PATCH /api/v1/maps/{id}` (update, admin only), `DELETE /api/v1/maps/{id}` (admin only). Server-side validation on create/update: at least 2 spawn zones, every spawn zone on passable + city-eligible terrain, dimensions in 10–100 range, name unique. Extend the lobby's `map_template` resolver to recognise the `saved:<id>` namespace and load tiles + spawn zones from the DB. When the lobby request specifies a saved map, the server overrides `map_width` / `map_height` with the saved-map dimensions. Implement the random-subset spawn selection rule (deterministic on `(seed, player_count)`) for cases where `len(spawn_zones) > player_count`. The lobby create-form drop-down is extended to list saved maps under a separator below the parametric templates; selecting one disables the dimensions inputs. Also expose the `Maps` placeholder page at `/maps` as a list view of saved maps (read-only — full editor lands in Phase 5).

### Acceptance criteria

- [ ] `saved_maps` table exists with the schema in the architectural-decisions section.
- [ ] All four REST endpoints behave per the route table; non-admin POST/PATCH/DELETE returns 403.
- [ ] Server-side validation rejects maps with <2 spawn zones, spawn zones on impassable / non-city-eligible terrain, or out-of-range dimensions, with field-specific error messages.
- [ ] Creating a game with `map_template = "saved:<id>"` loads tile data and spawn zones from the DB and uses the saved-map dimensions regardless of the dimensions sent in the request.
- [ ] When a saved map has more spawn zones than players, the engine picks a deterministic random subset; the same `(seed, player_count, saved_map_id)` always selects the same subset.
- [ ] When a saved map has fewer spawn zones than players, lobby creation returns a clear validation error.
- [ ] The lobby create-form drop-down lists parametric templates first, then a separator, then saved maps by name; selecting a saved map disables width/height inputs.
- [ ] The `/maps` page lists saved maps with name, dimensions, spawn count, and author email (no editor yet).

---

## Phase 5: Map builder UI

**User stories**: 13, 14, 15, 16, 17, 18, 22, 23

### What to build

The admin-facing authoring experience. Add `/maps/new` and `/maps/[id]/edit` pages, both admin-guarded. The editor renders a paintable grid (canvas/Pixi-based, consistent with the in-game renderer) showing tiles at editor zoom. A tools palette offers a brush per terrain type, a spawn-zone marker tool, and an eraser; click and click-drag both apply the selected tool. A sidebar form holds name, description, width/height (resize is destructive — clamps existing tile data), and a click-to-focus list of spawn zones. Spawn zones render as a coloured pin overlay so they remain visible while painting underneath. The new-map page seeds the canvas from a template option (e.g. blank grass, or one of the parametric templates as a starting point). Save calls the existing Phase 4 endpoints, surfaces validation errors inline near the offending field. Editing an existing map loads its tiles / spawns / metadata into the same UI. The list page from Phase 4 grows edit and delete actions per row.

### Acceptance criteria

- [ ] `/maps/new` and `/maps/[id]/edit` are reachable by admins and redirect non-admins.
- [ ] All seven terrain brushes are present in the palette and visually identifiable by sprite.
- [ ] Click and click-drag both paint terrain; the spawn-zone tool drops/removes pins; the eraser clears resource overlays where applicable.
- [ ] Spawn-zone pins render above terrain sprites and remain visible while painting.
- [ ] The new-map page offers at least one starter option (e.g. blank grass or a parametric template seed).
- [ ] Saving a valid map persists it via the Phase 4 endpoints; it appears immediately in the list and in the lobby drop-down.
- [ ] Saving an invalid map shows inline error messages adjacent to the offending field (e.g. on a spawn pin placed on water).
- [ ] Editing an existing map round-trips: load → tweak → save produces the expected diff in the DB.
- [ ] The list page has working edit and delete actions; delete prompts for confirmation.
- [ ] Frontend feedback loops (type-check, lint, vitest, build) all pass.

---

## Phase 6: MCP rules-reference polish + per-template self-play coverage

**User stories**: 25, 26, 27 (verification & hardening)

### What to build

Close out the agent-facing surface and lock in regression coverage. Audit `get_rules_reference` to ensure the full new per-terrain table (movement cost, yield, city-eligible, resource spawn) is published in a shape useful to LLM-driven agents. Audit the MCP rendering tools (`render_map_ascii`, `render_map_svg`, `render_map_image`) to ensure all seven terrains have legible output (ASCII glyph, SVG fill, PNG sprite). Add per-template self-play smoke tests: one game per parametric template completed without invalid-action errors, deadlocks, or starved profiles. Add at least one self-play smoke test on a saved map (fixture loaded from a JSON file in the test suite) to exercise the `saved:<id>` resolver path. Ensure the existing `mise run self-play` and showcase commands run cleanly on the new generators.

### Acceptance criteria

- [ ] `get_rules_reference` output includes movement cost, city eligibility, and primary resource for all seven terrains.
- [ ] `render_map_ascii` has a unique glyph for each of the seven terrains.
- [ ] `render_map_svg` and `render_map_image` produce visibly distinct output for each of the seven terrains.
- [ ] One self-play smoke test exists per parametric template (`random`, `continent`, `islands`, `river`, `lakes`, `archipelago`); each runs to completion in CI.
- [ ] At least one self-play smoke test runs against a fixture saved map and exercises the `saved:<id>` resolver.
- [ ] `mise run self-play`, `mise run quick`, `mise run classic`, and `mise run showcase` all succeed on the new generators.
