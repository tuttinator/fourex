# Plan: Diplomacy

> Source PRD: `plans/diplomacy.md`

## Architectural decisions

Durable decisions that apply across all phases:

- **Persistence**: all diplomacy state lives inside the `GameState` JSON blob on the existing `Game.state` column — no DB schema migration.
- **Determinism**: event ids, treaty ids, and proposal ids are generated from a seeded monotonic counter stored inside `GameState`, never from UUIDs or wall-clock time. Replays must be bit-identical.
- **Relations dict**: the canonical per-pair diplomatic state remains the existing `GameState.diplomacy` dict keyed by sorted `(player_a, player_b)` tuples with values in the existing `DiplomaticState` enum (PEACE / ALLIANCE / WAR). Treaty ratification, expiration, cancellation, and war declaration all update this dict; other subsystems read it.
- **Action discrimination**: all new diplomatic actions join the existing `Action` discriminated union and execute inside `resolve_turn()` in submission order.
- **Turn ordering**: within `resolve_turn()`, diplomatic actions execute in the existing per-player action loop; a new *diplomacy-resolution phase* runs after action execution and before resource collection, handling recurring tribute, clause expiry, proposal expiry, and alliance-derived-state recomputation.
- **Public vs private visibility**: messages and pending proposals are private to sender/recipient; ratified treaties, declarations of war, violations, and all `DiplomaticEvent`s are public. Redaction is enforced in `redact_state()`.
- **Hybrid resource validation**: treaty proposals between allied parties pre-validate fundability at proposal time; between non-allied parties, validation happens only at acceptance (bluffing allowed).
- **Non-binding treaties**: engine emits events for violation; engine holds no numeric reputation or penalty state — reputation is a consumer concern.
- **Discovery**: a per-player "discovered players" set lives in `GameState`. Entries are added by the same visibility logic that drives fog-of-war but are never removed (permanent discovery).
- **Routes**:
  - Frontend page: `/games/[id]/diplomacy`
  - REST: `/api/v1/games/{game_id}/diplomacy/...` (declare-war, treaties/proposals [+ respond, withdraw], treaties [+ cancel], messages, get)
  - MCP: new `tools/diplomacy.py` module exposing `declare_war`, `propose_treaty`, `respond_to_treaty`, `withdraw_treaty`, `cancel_treaty`, `send_message`, `get_messages`, `get_diplomacy_state`.
- **Frontend–MCP parity**: every frontend capability has an equivalent MCP tool and vice versa. Hard invariant.
- **Bilateral only**: every treaty has exactly two parties. Coalitions are modelled as meshes of bilateral alliances.

---

## Phase 1: Relations foundation — declare war, treacherous attack, public event feed

**User stories**: 1, 2, 3, 4, 5, 6, 8, 9, 38, 39, 53, 54, 55, 61, 62, 66, 67, 68

### What to build

Lay the foundations for the whole feature. Extend `GameState` with a deterministic id counter, a per-player discovered-players set, and a public diplomatic-events log. Add an explicit war-declaration action with immediate effect. Detect and log treacherous first strikes (attacking a player you are at peace with) and auto-flip that pair to WAR. Ship a minimal diplomacy page on the frontend showing the relations matrix for discovered players and a live world-events feed, plus the underlying REST + MCP surface for these two write actions and a read endpoint for diplomacy state.

### Acceptance criteria

- [ ] `GameState` carries a diplomatic-events list, a deterministic id counter, and a per-player discovered-players set; redacted reads respect per-viewer visibility of relations and events.
- [ ] A player can declare war on any discovered player on their turn; war takes effect immediately and is recorded as a public `WAR_DECLARED` event.
- [ ] A player attacking another player at PEACE succeeds, auto-flips the pair to WAR, and emits a public `TREACHEROUS_ATTACK` event in addition to the usual combat events.
- [ ] Declaring war against a player you cannot see (undiscovered) is rejected at action validation.
- [ ] A new frontend route `/games/[id]/diplomacy` renders a relations matrix for discovered players and a world-events feed with distinct styling for declarations vs treacherous attacks.
- [ ] The MCP `get_diplomacy_state` tool returns relations, discovered players, and recent events filtered per the viewer's visibility rules.
- [ ] Replay of a recorded game reproduces identical event ids and state.

---

## Phase 2: Messaging

**User stories**: 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 64, 65

### What to build

Free-form bilateral messaging. A player can send up to 5 messages per turn to any discovered player; each message is ≤2000 characters, submitted on the sender's turn, and delivered at turn resolution. Messages are private to sender and recipient and persisted in the game state and replay. A `MESSAGE_SENT` event is NOT added to the public feed — only the two parties ever see the content. The diplomacy page gains per-counterpart message threads with turn-gated send controls.

### Acceptance criteria

- [ ] Sending a message to an undiscovered player, messages over 2000 chars, or the 6th message in a turn are all rejected at validation.
- [ ] Messages sent on turn N appear in the recipient's inbox at the start of turn N+1.
- [ ] A third player cannot see message content or even existence in any read endpoint.
- [ ] The MCP `send_message` and `get_messages` tools mirror the frontend capability exactly.
- [ ] Frontend send controls are disabled with an explanatory tooltip when it is not the viewer's turn.
- [ ] Messages appear in the recorded turn history for replay and agent scratchpad inspection.

---

## Phase 3: Treaty lifecycle skeleton (peace + free-text clauses)

**User stories**: 7, 20, 21, 23, 24, 25, 26, 27, 28, 33, 36, 37, 60 (plus wiring for "war cancels treaties" from story 6)

### What to build

The full treaty proposal/response/withdraw/cancel lifecycle, restricted to two clause types for this phase: `PeaceClause` (set pair to PEACE for N turns) and `FreeTextClause` (no mechanical effect). A treaty may bundle both. Ratified treaties are public (all players see parties + clauses); pending proposals are private to the two parties. Proposals made on turn N are visible to the recipient at turn N+1; the recipient responds on their next turn; proposals auto-expire after 3 turns if not answered. Proposers may withdraw before a response. Either party may unilaterally cancel a ratified treaty on their turn — the engine distinguishes `TREATY_CANCELLED` (no active obligations) from `TREATY_VIOLATED` (active obligations present). Declaring war (Phase 1) now also cancels every active treaty between the two parties, emitting `TREATY_CANCELLED` events (not violations, because the war is the antecedent signal). Frontend gains a proposal builder (peace + free-text only for now), inbox/outbox, active-treaties list, and treaty history log.

### Acceptance criteria

- [ ] A peace treaty ratified on turn N sets the pair's `DiplomaticState` to PEACE and persists it for the declared duration, with the existing `diplomacy` dict as the source of truth.
- [ ] Proposal lifecycle events (`TREATY_PROPOSED`, `PROPOSAL_WITHDRAWN`, `PROPOSAL_DECLINED`, `PROPOSAL_ACCEPTED`, `PROPOSAL_EXPIRED`) emit on the public event feed; the content of the proposal is visible in the feed only once it is ratified or declined publicly (ratifications are public; declines emit the event but not the clauses — decide in implementation).
- [ ] Pending proposals are visible only to proposer and recipient; third parties cannot see them in any read endpoint.
- [ ] Active treaties (ratified but not yet expired/cancelled) are visible to all players with full clause content.
- [ ] A proposal with no response 3 turns after being proposed is auto-expired and removed from the inbox.
- [ ] Unilateral cancellation of a ratified peace treaty emits `TREATY_VIOLATED` (peace is an active obligation); cancellation of a pure free-text treaty emits `TREATY_CANCELLED`.
- [ ] Declaring war cancels every active treaty between the two parties with `TREATY_CANCELLED` events.
- [ ] Frontend proposal builder supports adding one or more clauses of the two supported types, with duration input for peace, and renders inbox/outbox/active/history views.
- [ ] MCP `propose_treaty`, `respond_to_treaty`, `withdraw_treaty`, `cancel_treaty` accept and emit the same shapes the REST endpoints do.

---

## Phase 4: Resource clauses — one-off swap and recurring tribute

**User stories**: 22 (swap + tribute), 29, 30, 31, 32, 34, 35

### What to build

Add two new clause types. `ResourceSwapClause` specifies amounts each party pays at ratification; payment is atomic and simultaneous. `RecurringTributeClause` specifies amounts one party pays the other every turn for N turns. Introduce hybrid validation: if the two parties are in ALLIANCE state at proposal time, the engine pre-validates that both can fund every clause now; otherwise no pre-validation (bluffing allowed). At acceptance, every immediate obligation (swap) is re-validated — if unfundable, emit `PROPOSAL_FAILED_UNFUNDABLE`, discard the treaty, charge nothing. Recurring tribute runs in the diplomacy-resolution phase at turn end; a payment the payer cannot afford auto-cancels the treaty with `TREATY_VIOLATED` and `TRIBUTE_FAILED` events. Proposal builder gains clause-type-specific inputs.

### Acceptance criteria

- [ ] A one-off swap where both parties can pay ratifies atomically: both stockpiles update in the same resolution step; no interim state where only one has paid.
- [ ] A one-off swap where the proposer cannot pay at acceptance (non-ally route) emits `PROPOSAL_FAILED_UNFUNDABLE`; neither party is charged; the proposal is discarded.
- [ ] A one-off swap proposed between allies where either party lacks resources is rejected at proposal-action validation (not at acceptance).
- [ ] A recurring-tribute treaty transfers resources each turn for its declared duration.
- [ ] A tribute payment the payer cannot afford emits `TRIBUTE_FAILED` and `TREATY_VIOLATED`, cancels the treaty, and does not partially pay.
- [ ] Frontend proposal builder renders amount inputs for swap/tribute clauses and enforces basic client-side constraints (positive integers, resource types from the existing enum).
- [ ] Active-treaty list shows the next tribute amount due and remaining tribute turns.

---

## Phase 5: Alliance core — ratification and passive benefits

**User stories**: 22 (alliance/vision/open-borders), 40, 41, 42, 43, 46

### What to build

Add three clause types: `AllianceClause`, `VisionSharingClause`, and `OpenBordersClause`. Ratifying an alliance clause sets the pair's `DiplomaticState` to ALLIANCE in the `diplomacy` dict for the declared duration. An ALLIANCE state mechanically grants: no attacks between allies (existing rule, reaffirmed), mutual shared vision (the union of both players' visible tiles appears to each), unit co-stacking on the same tile, and free movement through each other's territory. Standalone `VisionSharingClause` and `OpenBordersClause` grant only the corresponding benefit without the other alliance effects. Alliance cancellation by either party clears the ALLIANCE state and emits `TREATY_VIOLATED` (alliance is an active obligation). Expiration by reaching duration zero emits `TREATY_EXPIRED`. Frontend relations matrix renders alliances distinctly; the game map surfaces tiles visible via ally sharing with a marker so the viewer knows they are seeing ally intel.

### Acceptance criteria

- [ ] Ratifying an alliance clause sets the `diplomacy` dict pair entry to ALLIANCE and the existing attack-validation check blocks combat between the two players.
- [ ] `redact_state()` returns the union of the viewer's and every current ally's visible tiles to the viewer; tiles visible only via ally sharing are distinguishable to the frontend.
- [ ] Units of allied players can occupy the same tile; movement into a tile already occupied by an ally's unit is permitted.
- [ ] A unit may move through a tile owned by an ally (terrain/territorial-owner permitting) without penalty that does not apply to own-territory movement.
- [ ] A standalone `VisionSharingClause` grants mutual vision without granting no-attack, stacking, or passage.
- [ ] A standalone `OpenBordersClause` grants passage without granting vision or no-attack.
- [ ] Unilateral cancellation of a ratified alliance clause emits `TREATY_VIOLATED`; expiry emits `TREATY_EXPIRED`; in both cases the `diplomacy` dict pair entry reverts to PEACE.
- [ ] Frontend map shows ally-shared tiles distinguishably; relations matrix shows ALLIANCE distinctly from PEACE and WAR.

---

## Phase 6: Alliance dynamics — war-drag cascade, separate peace, shared victory

**User stories**: 44, 45, 47, 48

### What to build

When a `WAR_DECLARED` event fires for pair (A, C), the engine inspects all active alliance clauses and auto-declares war between each ally of A and C (and vice versa), emitting further `WAR_DECLARED` events tagged with `cause: "alliance_drag"`. A player dragged into a war they did not initiate can, on their subsequent turn, propose a separate peace treaty to the third party, following the normal treaty flow — acceptance restores PEACE for that pair without affecting the original belligerents. Shared victory: at the point where victory is evaluated, the engine checks each active alliance pair and, if the pair *jointly* satisfies the condition (combined territory/score/whatever the condition measures), records both players as victors and ends the game with multiple winners. An ally solo-satisfying a condition does not share victory.

### Acceptance criteria

- [ ] Declaring war on a player who has one or more allies triggers additional `WAR_DECLARED` events with `cause: "alliance_drag"` for each ally on the defender's side (and symmetrically for attacker's allies).
- [ ] A player dragged into a war can, on their next turn, propose a peace treaty to the third party; acceptance restores PEACE for that pair only.
- [ ] A separate peace negotiated by a dragged ally does not end the war between the original belligerents.
- [ ] Victory evaluation returns multiple victors when an allied pair jointly satisfies a condition; the game ends with both recorded as winners.
- [ ] An allied pair where only one player solo-satisfies a condition does NOT both win — only the solo-satisfying player is the victor, and the ally is not dragged into victory.
- [ ] The world-events feed renders alliance-drag declarations distinguishably from direct declarations.

---

## Phase 7: Agent integration and personality axes

**User stories**: 17, 18, 49, 50, 51, 52

### What to build

Bind the full MCP diplomacy toolkit into the agent system so agents can declare war, send messages, propose/respond to/withdraw/cancel treaties, and query diplomacy state. Extend the agent planning prompt to describe diplomatic actions and the public event feed so the LLM can reason about them. Add two new personality axes — `honour` (propensity to keep promises; low values increase violation and treacherous-attack frequency) and `openness` (propensity to initiate contact, proposals, and alliances; low values bias toward isolation). Seed at least one new personality (e.g. "treacherous diplomat") that exercises the axes. Confirm that agents can and do store salient messages in their existing scratchpad memory without any special engine support.

### Acceptance criteria

- [ ] Agents can successfully invoke every diplomacy MCP tool in an end-to-end AI-vs-AI game.
- [ ] The planning prompt references diplomatic actions, the public event feed, and the new personality axes.
- [ ] Two new personality axes (`honour`, `openness`) exist in the personality definitions with sensible defaults for existing personalities.
- [ ] At least one new personality variant is defined and measurably exhibits distinct diplomatic behaviour (higher violation rate or higher proposal rate) in a showcase game.
- [ ] A showcase game of 3+ agents produces observable diplomatic events (proposals, ratifications, at least one violation or declaration) without any human intervention.
- [ ] Agents can save messages they consider important into the scratchpad via existing memory tools; no new memory tool is required.

---

## Phase 8: Replay sync and observability

**User stories**: 63

### What to build

Ensure the frontend replay UI renders diplomatic events in sync with turn progression — stepping through turns surfaces the events feed, message inbox, and treaty state as they were at that turn. Add logfire spans for each diplomatic event type with structured attributes (actor, counterparty, event type, clause types, game id, turn) so whole-corpus analytical queries are practical. Sweep any straggling acceptance criteria from prior phases.

### Acceptance criteria

- [ ] Stepping through a recorded game's turns in the frontend replay shows the events feed, active treaties, and message inbox as they existed at each turn.
- [ ] A logfire span is emitted for each diplomatic event with structured attributes usable for grouping and aggregation.
- [ ] Running the existing test suites + new diplomacy tests passes on main.
- [ ] A manual end-to-end smoke test (create game, declare war, negotiate alliance, violate, win jointly) passes against the frontend and MCP in parallel.
