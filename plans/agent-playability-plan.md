# Plan: Agent Playability & Game Legibility

> Source PRD: `plans/agent-playability-prd.md`

## Dependencies

- **`plans/map-system-overhaul-plan.md` is assumed complete before this plan starts.** It owns the ore-on-mountain gameplay fix (adds `HILLS` terrain, moves ore + `MINE` improvement to `HILLS`, mountains become genuinely impassable + resource-free) and the per-terrain table in `get_rules_reference`. This plan does not duplicate that work.
- Phase 7's default-map-sizing and starting-fog tweaks are layered on top of the `generate_map(template, width, height, seed, player_count)` entry point introduced in map-system-overhaul Phase 2.

## Architectural decisions

Durable decisions that apply across all phases:

- **Surface convention**: legibility lives in the existing MCP / REST tool responses. No new transports, no new persisted entities, no push channel.
- **`Unit` projection**: gains an explicit pair of fields — `moves_left` (what the agent can spend *this* turn) and `moves_per_turn` (the unit's base allowance). The pair is the canonical disambiguation of "spent" vs "broken".
- **Snapshot timing**: `get_game_state` always returns post-resolution state for the most recently completed turn boundary. If the moves-perception investigation finds the agent reads pre-reset state, the fix is at the snapshot boundary, not in `reset_unit_moves`.
- **`validate_actions` response shape**: each per-action entry grows a `cost` object summarising resources, production, and upkeep deltas the action would apply. Existing `{valid, message}` keys are preserved.
- **`submit_actions` response shape**: each per-action entry grows a `delta` (or equivalent) object reporting the realised resource / production / upkeep changes the engine actually applied. Existing keys are preserved.
- **`City` projection**: gains `production_points`, `production_per_turn`, and a per-resource `yield_breakdown` block with line items (tile yields, building bonuses, upkeep). Build-queue depth is exposed as `queue_capacity: "unlimited"` plus the current `queued: [...]` list.
- **`get_rules_reference`**: becomes the canonical home for the action-type catalogue (every submittable `type` string, its JSON schema, and its cost model). The per-terrain table delivered by map-system-overhaul is left in place; this plan extends the response, never overwrites it.
- **`get_tech_tree`**: active research surfaces `progress / cost` directly so non-zero accumulation is visible even before a tech completes.
- **`is_my_turn` evolution**: returns `{is_my_turn, current_turn, turn_deadline_at}` so agents can self-pace polling. No blocking long-poll tool is added in this plan; that decision is deferred until the cheap signal proves insufficient.
- **Mining diagnostics**: `find_resource_opportunities` and `validate_actions` surface a structured reason when a resource target is unreachable / unmineable, on top of the gameplay fix delivered by map-system-overhaul.
- **Determinism invariant**: every change is observational. The engine's resolution order, RNG seeding, and action semantics are unchanged unless explicitly noted (Phase 7 fog-radius and default-sizing are the only behavioural tweaks).

---

## Phase 1: Moves perception fix

**User stories**: 1, 16

### What to build

Investigate exactly when `get_game_state` is called relative to `resolve_turn` and `reset_unit_moves`, and confirm whether agents are observing pre-reset state on the turn boundary. Land whichever of (a) snapshot-ordering fix or (b) explicit `moves_left` vs `moves_per_turn` field pair makes the agent's view unambiguous. The end state: an agent that has just submitted a turn and reads `get_game_state` immediately sees moves values that match what it can actually spend on its next turn, and never sees a phantom flip between full and zero.

### Acceptance criteria

- [ ] A short investigation note (in the PR description or this plan) documents the actual root cause — snapshot timing, redaction artefact, or projection bug.
- [ ] `Unit` projection in `get_game_state` exposes both `moves_left` and `moves_per_turn` as distinct fields with documented semantics.
- [ ] Replaying a multi-turn self-play game shows `moves_left` values that are monotonically consistent with the actions the agent submitted that turn (no alternating-zero artefact).
- [ ] A regression test exercises the exact sequence (submit → resolve → next get_game_state) the agents reported, asserting `moves_left` matches expectations.
- [ ] `get_rules_reference` (or tool docstring) documents the `moves_left` / `moves_per_turn` pair so agents do not have to infer it.

---

## Phase 2: Action cost visibility

**User stories**: 2, 3

### What to build

Enrich `validate_actions` so every per-action result carries a `cost` object describing what the action would consume (resources, production cost, food / upkeep delta where applicable). Enrich `submit_actions` so every per-action result carries the realised delta — what the engine actually applied — so agents can reconcile their model against ground truth. End-to-end through engine → REST → MCP; tool docstrings updated; tests cover at least one action of each cost-bearing kind (train unit, queue building, found city, research, improvement order).

### Acceptance criteria

- [ ] `validate_actions` returns `cost` per action entry alongside `valid` / `message`. `cost` is well-typed and documented in `get_rules_reference`.
- [ ] `submit_actions` returns the realised delta per action entry. For invalid / failed actions the delta is empty or explicitly null.
- [ ] An agent that calls `validate_actions` followed by `submit_actions` can reconcile expected vs realised cost for every action without consulting `get_rules_reference`.
- [ ] Backend tests assert `cost` and `delta` shapes for at least one action per cost-bearing kind, including the no-op / invalid case.
- [ ] Existing callers (REST + MCP + planner + frontend) keep working — additive, not replacing.

---

## Phase 3: City production & per-turn yield breakdown

**User stories**: 4, 5

### What to build

Make per-city economic state legible in `get_game_state`. Each `City` projection grows `production_points` (current accumulation), `production_per_turn` (next-turn rate), and a per-resource `yield_breakdown` mapping each resource to a list of line items (tile yields, building bonuses, upkeep) plus a net total. The breakdown should let an agent explain "-13 food this turn" by reading a single field. Engine reuses existing `production_per_turn` / yield helpers; the breakdown is composed at projection time, not stored.

### Acceptance criteria

- [ ] Every city in `get_game_state` exposes `production_points` and `production_per_turn` as integers.
- [ ] Every city exposes `yield_breakdown` keyed by resource (food, wood, ore, crystal, science, production) with line items and a net total per resource.
- [ ] The line-item totals reconcile to the actual per-turn delta applied by `resolve_turn` for at least one fixture game (asserted by test).
- [ ] An agent reading `yield_breakdown` for a city can identify the dominant contributor to a swing (e.g. the line item attributable to unit upkeep) without consulting `get_rules_reference`.
- [ ] Tool docstrings and `get_rules_reference` document the breakdown shape.

---

## Phase 4: Rules reference, tech progress & build-queue surface

**User stories**: 6, 10, 11, 17

### What to build

Make `get_rules_reference` the single canonical home for action-type discovery: publish every submittable `type` string with its JSON schema and cost model alongside the per-terrain table that already exists from map-system-overhaul. Expose `progress / cost` for the active research in `get_tech_tree` (or the active-research projection) so non-zero accumulation is visible. Surface `queue_capacity: "unlimited"` and the current `queued: [...]` list per city in `get_game_state` so agents pre-plan instead of leaving cities idle. No new endpoints — every change is a field added to existing tool responses.

### Acceptance criteria

- [ ] `get_rules_reference` includes a top-level `action_types` block listing every submittable action `type`, with JSON schema and cost model. The block sits alongside the existing per-terrain table without disturbing it.
- [ ] `get_tech_tree` (or the active-research projection) exposes `progress` and `cost` for the active tech as integers, along with `progress_per_turn`.
- [ ] Every city in `get_game_state` exposes `queue_capacity: "unlimited"` and a `queued` list reflecting the current build queue in submission order.
- [ ] An agent that has only ever read tool docstrings + `get_rules_reference` can construct a valid action of each type without trial-and-error on the `type` string.
- [ ] Tests assert the action-type catalogue is generated from the same source the engine validates against (no duplicated source of truth).

---

## Phase 5: Mining diagnostic

**User stories**: 8

### What to build

Lean phase. The gameplay fix for ore extraction (HILLS terrain, mine-on-hills) is owned by map-system-overhaul. This phase adds the *diagnostic* half: when an agent targets a tile that cannot host a mine, or asks `find_resource_opportunities` for ore, the response carries a structured reason (e.g. `"reason": "tile_terrain_invalid_for_improvement"`, with the tile coord and terrain) instead of a silent rejection or generic `valid: false`. Story 7 is intentionally not addressed here because map-system-overhaul handles it.

### Acceptance criteria

- [ ] `validate_actions` returns a structured `reason` (machine-readable code + human message) for any action rejected on terrain / resource grounds, including mine-on-non-hills.
- [ ] `find_resource_opportunities` annotates each opportunity with reachability / mineability flags so agents see "ore visible but no path" without seven turns of trial.
- [ ] Tool docstrings document the reason-code vocabulary.
- [ ] Tests cover: mine on grass (rejected with reason), mine on hills (accepted), mine on water (rejected with reason), `find_resource_opportunities` returning a ore tile annotated with mineable status.

---

## Phase 6: Cheap turn-pacing signals

**User stories**: 9 (reworked)

### What to build

Extend `is_my_turn` to return `{is_my_turn, current_turn, turn_deadline_at}` so agents can self-pace polling without burning 60-second loops. Update the `is_my_turn` docstring (and `get_rules_reference`) to recommend a polling cadence and explain the deadline semantics. No new MCP tool is added — the blocking long-poll variant is deferred until evidence shows the cheap signal is insufficient.

### Acceptance criteria

- [ ] `is_my_turn` response includes `current_turn` (int) and `turn_deadline_at` (ISO timestamp or null when no deadline is configured) in addition to the existing `is_my_turn` boolean.
- [ ] Tool docstring documents recommended polling cadence and deadline semantics.
- [ ] An agent using only `is_my_turn` can compute a sensible next-poll delay without external state.
- [ ] Tests cover: my turn / not my turn / deadline-present / deadline-absent.

---

## Phase 7: Game-design polish

**User stories**: 12, 13, 14, 15

### What to build

A grouped polish phase, gated on designer sign-off but tracked together because each item is small and cross-cutting:

- **Opponent stockpile visibility**: implement the chosen decision — either redact opponent stockpiles in `redact_state` or document the current full visibility as intentional in `get_rules_reference`. No partial / fog-gated middle ground in this phase.
- **Default map sizing**: scale `map_width` / `map_height` defaults with player count (e.g. 100×100 for 4+ players, 60×60 for 2-player). Layered on top of map-system-overhaul's `generate_map(... player_count)` entry point.
- **Starting fog radius**: give starting units a small initial vision radius (≈2 tiles) so turn 1 has at least one meaningful decision.
- **Improvement vs building asymmetry**: either document the design intent in `get_rules_reference` or convert improvements to a short queued job. Whichever lands, the rationale is captured in the rules reference so agents and humans can reason about it.

### Acceptance criteria

- [ ] Designer decisions on all four items are documented (in this plan or a linked doc) before code lands.
- [ ] `redact_state` behaviour for opponent stockpiles matches the documented decision; `get_rules_reference` records the choice.
- [ ] Default `map_width` / `map_height` scale with player count per the agreed table; documented in `get_rules_reference`.
- [ ] On a freshly-created game, every starting unit reveals a vision footprint of the agreed radius around it on turn 1.
- [ ] Improvement timing matches the documented decision (instant or queued); `get_rules_reference` documents it.
- [ ] Profile-driven self-play (`mise run quick` / `classic` / `showcase`) completes cleanly under the new defaults with no invalid-action errors.
