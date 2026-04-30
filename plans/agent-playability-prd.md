# Agent Playability & Game Legibility PRD

## Problem Statement

Two AI agents played the game over multiple turns and surfaced a consistent set of rough edges that made the economic and turn-flow loops hard to reason about. Some are real bugs, some are missing affordances, and some are perception gaps where the engine behaves correctly but the agent-facing surface (MCP tools, validate responses, `get_game_state`) does not expose enough information for an agent (or human) to understand *why* something happened.

The cumulative effect is that a competent agent burns turns on confusion — submitting actions whose costs it cannot see, hunting for action-type spellings, watching ore sit forever on unreachable mountains, and assuming bugs where none exist (e.g. "moves alternate every turn") because it has no way to introspect the state machine.

Three signals are ranked highest:

1. **Moves perception bug** — Agent reports unit `moves_left` flipping between full and 0 on alternating turns. Engine code (`reset_unit_moves` at the top of `resolve_turn`) resets all units uniformly, so this is *not* an engine bug. Something in the agent-visible state — likely a snapshot timing issue between submission, resolution, and the next read — is showing pre-reset state. This needs to be either fixed or made unambiguous in the API response.
2. **Mountain/ore accessibility** — Ore only spawns on mountains. Mountains are impassable. There is no documented route from "I see ore" to "I have ore". Agents seven turns in have zero ore income with no path to fix it.
3. **Validate responses do not show costs** — `validate_actions` returns `{valid, message}` only. Agents cannot price an action without consulting a separate rules-reference call and doing the math themselves.

Other issues (production as a ghost resource, build-queue depth being undiscoverable, fully-visible opponent stockpiles, agent polling friction) compound the same root cause: the surface area exposed to agents is thinner than the engine's actual model.

## Solution

Make the agent-facing surface *legible*. Specifically:

1. Investigate and fix the moves perception bug — confirm whether agents read post-action state before the next-turn reset, and either change the snapshot timing or add an explicit `next_turn_moves` field so the agent can disambiguate.
2. Provide a route from ore to mining: either let workers traverse mountains (perhaps with a movement penalty or a tech requirement), allow mines to be built on mountain-adjacent tiles, or surface a clear "ore unreachable until X" diagnostic.
3. Enrich `validate_actions` and `submit_actions` responses with full cost breakdowns (resources spent, production progress, food/upkeep deltas) so agents can budget without external lookups.
4. Surface "production" as a first-class observable per-city value in `get_game_state`, alongside per-turn yields for food, science, culture so per-turn deltas are explainable.
5. Document the canonical action-type list in `get_rules_reference` so agents do not trial-and-error names like `SET_RESEARCH` vs `SET_ACTIVE_RESEARCH`.
6. Add a per-city per-turn yield breakdown (food: +5 from worked tiles, -3 from unit upkeep, net +2) to make the food/science/production swings explainable.
7. Decide and document the design intent on opponent stockpile visibility — currently `redact_state` does not filter opponent stockpiles. Either redact them (requires fog/intelligence model) or document that this is intentional transparency.
8. Add an MCP `wait_for_my_turn` tool with a server-side blocking wait (with a sane timeout) so agents do not have to poll every 60 seconds.
9. Smaller game-design polish: starting partial vision instead of total fog, smaller default maps for low player counts, surfacing the unlimited build-queue capability so agents pre-plan, reconciling the instant-improvement vs multi-turn-building asymmetry.

## User Stories

1. As an agent, I want unit `moves_left` in `get_game_state` to reflect what I can actually do *this* turn, so that I do not waste decision time worrying about phantom alternating-moves bugs.
2. As an agent, I want every `validate_actions` response to include the resource cost (and production cost where applicable) of each action, so that I can budget without making a separate `get_rules_reference` call and doing the arithmetic myself.
3. As an agent, I want `submit_actions` responses to include the actual resource deltas applied, so that I can confirm what an action consumed and reconcile against my model.
4. As an agent, I want `get_game_state` to expose each city's current production points and per-turn production rate as a first-class field, so that "costs 6 production" is a measurable quantity.
5. As an agent, I want `get_game_state` to include a per-city per-turn yield breakdown for food, wood, ore, crystal, science, and production, with line items for tile yields, building bonuses, and upkeep, so that I can explain swings like "-13 food this turn".
6. As an agent, I want `get_rules_reference` to publish the canonical list of all submittable action `type` strings with their schemas, so that I never have to trial-and-error action names.
7. As a player, I want a documented path to extract ore — either a worker variant that can enter mountains, a "mine adjacency" rule, or a tech that unlocks mountain traversal — so that the resource I can see on the map is one I can actually obtain.
8. As an agent, I want a clear diagnostic in `find_resource_opportunities` and `validate_actions` when I attempt to mine an inaccessible resource, so that I learn the constraint without seven dead turns.
9. As an agent, I want a `wait_for_my_turn` MCP tool that blocks server-side until it is my turn (with a configurable timeout), so that I do not poll every 60 seconds.
10. As an agent, I want `get_rules_reference` and `get_game_state` to make the unlimited build-queue capability obvious (e.g. show `queue_capacity: unlimited` and `queued: [...]`), so that I pre-plan instead of leaving cities idle between completions.
11. As an agent, I want `get_tech_tree` to clearly show research progress as `progress / cost` for the active tech, so that I can see science accumulating into something even when the stockpile shows zero.
12. As a game designer, I want a documented decision on whether opponent stockpiles should be visible, so that fog-of-war intent is consistent across units, cities, and resources.
13. As a game designer, I want default map sizes scaled to player count (e.g. 100x100 for 4+ players, 60x60 for 2-player games), so that small games do not stagnate in exploration.
14. As a player, I want the starting vision to include a small radius around my initial units (e.g. 2 tiles), so that turn 1 has at least one meaningful decision.
15. As a game designer, I want a documented justification for instant improvements vs multi-turn buildings (or a unification of the two), so that the asymmetry is intentional rather than accidental.
16. As an agent, I want `get_game_state` to clearly distinguish `current_moves_left` from `moves_per_turn`, so that I never confuse "spent" with "broken".
17. As an agent author, I want a single canonical "action types and their costs" reference document accessible via the MCP, so that prompt context can be prepared once instead of derived per turn.

## Implementation Decisions

### Investigation tasks (must precede design choices)

- **Moves perception bug**: trace exactly when `get_game_state` is called relative to `resolve_turn` and `reset_unit_moves`. Confirm whether agents are reading state before the next-turn reset has applied (e.g. immediately post-submit, before the turn boundary). The fix is likely either a snapshot ordering change or an additional explicit field, not a change to `reset_unit_moves` itself, which already resets uniformly.
- **Mountain/ore design intent**: confirm with the designer whether mountains are *meant* to be unreachable. The current state (ore on mountain + impassable mountain + mine requires mountain terrain) is internally consistent code-wise but a dead end gameplay-wise.
- **Opponent stockpile visibility**: confirm with the designer whether the current full-visibility behaviour in `redact_state` is intentional or an oversight.

### Engine / API changes

- Extend the `validate_actions` response shape to include a `cost` object per action result (resources spent, production cost, food upkeep delta where applicable).
- Extend the `submit_actions` response shape similarly with the realised deltas.
- Extend the `City` projection in `get_game_state` to include current `production_points`, `production_per_turn`, and a per-resource per-turn yield breakdown with line items.
- Extend the `Unit` projection in `get_game_state` to clearly distinguish `moves_left` from `moves_per_turn`.
- Extend `get_rules_reference` to publish the canonical list of action types with their JSON schemas and cost models.
- Extend `get_tech_tree` (or the active research projection) to expose `progress / cost` for the active tech.

### MCP server changes

- Add a `wait_for_my_turn` tool with server-side blocking (long-poll style) and a sane timeout.
- Update tool docstrings to reference the canonical action-type list rather than restating it.

### Game design changes (require designer sign-off)

- Mountain traversal: pick one of (a) worker mountain access with a tech gate, (b) mine adjacency rule, (c) explicit "mountain pass" terrain modifier.
- Default map sizing: scale with player count.
- Starting fog: small initial vision radius around starting units.
- Opponent stockpile visibility: redact in `redact_state` *or* document as intentional.
- Improvements vs buildings asymmetry: leave as-is with documented intent *or* convert improvements to a short queued job.

### Out of scope decisions deliberately deferred

- Whether to add a true tech-research action queue (multiple techs queued).
- Whether to add a diplomacy/intelligence layer that gates opponent visibility behind earned information.
- Whether to add a real-time push channel beyond `wait_for_my_turn` long-polling.

## Out of Scope

- New unit types, building types, terrain types, or tech-tree expansion.
- Frontend (Next.js) changes — this PRD is about the engine and agent-facing surface. Frontend changes can follow once the API is enriched.
- Performance work on `redact_state` or the planner.
- Replay/observation rendering changes.
- The agent runtime / planner heuristics in `backend/src/agents/`.
- A full diplomacy/intelligence model (gating opponent visibility by earned information).
- Push notifications or webhooks (we are only adding server-side long-poll via `wait_for_my_turn`).

## Further Notes

- Several agent claims turned out to be *perception* issues, not bugs. The build queue is unlimited; agents thought it was capped at one. The action types are canonically exposed via `get_rules_reference`; agents missed it. This pattern suggests the highest-leverage work is documentation and response enrichment, not engine changes.
- The moves perception bug is the most important thing to investigate first because it makes agents distrust the entire state surface.
- The ore/mountain issue is the highest-priority *gameplay* fix because it breaks the economic loop entirely for any agent that wants metal.
- Cost visibility in `validate_actions` is the cheapest high-leverage fix and should land first.
- The PRD intentionally leaves the design choices on opponent visibility, mountain traversal, and improvement timing open — these need designer input rather than an engineering decision.
