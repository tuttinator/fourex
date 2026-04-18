# Diplomacy

## Problem Statement

The 4X engine today models inter-player interaction almost entirely through combat: any player can attack any other, the `DiplomaticState` enum (PEACE/ALLIANCE/WAR) exists but is only consulted to prevent allies from attacking each other, and there is no way for players to *communicate*, *commit*, *trade*, or *coordinate* short of sending military units at each other. This is a poor sandbox for AI agent research, because the richest behaviours we want to study — negotiation, coalition-building, deception, reciprocity, reputation, punishment cycles, treaty-breaking — all live in the social layer that the game has no vocabulary for. Human players on the frontend face the same flattening: there is no UI to do anything diplomatic, so even co-op scenarios degrade to parallel solo games.

We also lack the means for agents (or humans) to use *information* as a strategic resource: sharing or withholding vision of the map, committing to tribute streams, exchanging resources for favourable positioning. Without these, the game's strategy surface is narrower than it should be.

## Solution

Introduce a full diplomacy system with five layered capabilities available to both LLM agents (via new MCP tools) and human players (via a new frontend diplomacy page):

1. **Relations** — every pair of players has a diplomatic state (PEACE / ALLIANCE / WAR) that defaults to PEACE, can flip to WAR by explicit declaration or by a treacherous first strike, and returns to PEACE only through a mutually accepted peace treaty. An ALLIANCE state is established only through a ratified alliance clause.
2. **Messages** — players can send free-form text messages (≤2000 chars) to any *discovered* player on their own turn, capped at 5 messages/turn total, delivered at turn resolution, visible only to sender and recipient, and persisted in the replay/history.
3. **Treaties** — bilateral, multi-clause, bundled contracts spanning peace, alliance, one-off resource swaps, recurring tribute, mutual vision sharing, open borders, and free-text (unenforced) clauses. Treaties are **public** — all players see that two players have ratified a treaty and its terms. Treaties are **non-binding**: any party may cancel at any time; violations are first-class events logged publicly.
4. **Alliances** (a state reached through a ratified alliance clause) grant: no attacks between allies, mutual shared vision, unit co-stacking, free movement through each other's territory, automatic war-drag when an ally is attacked, and shared victory when allied players *jointly* satisfy a victory condition.
5. **Frontend** — a dedicated diplomacy page per game with a relations matrix, per-player message threads, treaty inbox/outbox, active treaty list, historical treaty log, and a world-events feed showing public diplomatic signals (declarations, ratifications, violations).

Agents gain new MCP tools that mirror every frontend capability, plus two new personality axes to bias their diplomatic behaviour. The engine records diplomatic events with enough fidelity that agent reputation can be reconstructed entirely by consumers — the engine itself is neutral on reputation.

## User Stories

### Discovery & relations

1. As a player, I want my diplomatic relationship with every other player I have discovered to be visible at a glance, so I know who I can attack, ally with, or negotiate with.
2. As a player, I want undiscovered players to be hidden from my diplomacy view, so that fog-of-war is preserved in the diplomatic layer.
3. As a player, I want players I have *ever* discovered to remain permanently discoverable even if I lose all sight of them, so that once-established diplomatic channels persist.
4. As a player, I want to declare war on any discovered player on my turn, so I can legitimise military action.
5. As a player, I want my declaration of war to take effect immediately (same turn), so I can attack on the same turn I declare.
6. As a player, I want declaring war to automatically cancel every active treaty between me and the target, so the state is consistent without manual cleanup.
7. As a player, I want to propose peace to a player I am at war with, so that wars can end diplomatically rather than only via elimination.
8. As a player, I want to be able to attack a player I am at peace with, so that treachery is a tactical option.
9. As a player, I want a treacherous first strike to automatically flip the relationship to WAR and log a public "treacherous attack" event, so the breach of peace is surfaced to other players.

### Messaging

10. As a player, I want to send a free-form text message to any discovered player, so I can negotiate, threaten, or coordinate.
11. As a player, I want my message length limited to 2000 characters, so the UI and storage remain bounded.
12. As a player, I want a per-turn send limit of 5 messages total, so spam is prevented.
13. As a player, I want messages to be sendable only during my own turn, so timing matches the turn-based pacing of the rest of the game.
14. As a player, I want messages delivered to recipients at turn resolution (not the moment I send), so the turn remains the atomic unit of game progress.
15. As a player, I want my messages visible only to me and the recipient, so private diplomacy is actually private.
16. As a player, I want all messages I have sent or received to be persisted in the turn history and replay, so I can review the diplomatic arc of the game.
17. As an agent, I want to read my inbox and outbox via an MCP tool, so I can incorporate recent messages into my planning.
18. As an agent, I want the option to store important messages in my scratchpad, so I can retain them beyond any automatic context window.
19. As a player on the frontend, I want a threaded message view per counterpart, so I can follow a bilateral conversation.

### Treaties: proposing, responding, lifecycle

20. As a player, I want to propose a treaty to any discovered player, so I can attempt to commit us both to a contract.
21. As a player, I want to bundle multiple clauses (e.g. peace + tribute + vision) into a single treaty, so complex deals can be ratified atomically.
22. As a player, I want the available clause types to cover: peace for N turns, alliance for N turns, one-off resource swap, recurring tribute for N turns, mutual vision sharing for N turns, open borders for N turns, and a free-text (unenforced) clause.
23. As a player, I want a pending proposal to be seen by the recipient at the next turn resolution, so proposing and responding are both turn-gated.
24. As a player, I want the recipient to respond on their next turn by accepting or declining, so responses don't create out-of-band state changes.
25. As a player, I want a pending proposal to auto-expire after 3 turns if not answered, so stale proposals don't clog the inbox indefinitely.
26. As a player, I want to withdraw a proposal I have made before it is answered, so I can revise my offer.
27. As a player, I want proposals, withdrawals, acceptances, declines, and expirations all logged in the public event feed, so other players can observe diplomatic tempo.
28. As a player, I want accepted treaties to be public — all players see that two players have ratified a treaty and its full terms — so treaties act as credible signals to third parties.

### Trade atomicity & resource validation

29. As a player proposing a treaty to an **ally**, I want the one-off swap and tribute clauses pre-validated against my and the ally's current resource stockpiles at proposal time, so I can't propose an unfundable deal (because allies already share resource visibility).
30. As a player proposing a treaty to a **non-ally**, I want no pre-validation at proposal time — the proposal may be a bluff — so resource stockpiles are not leaked via proposal probing.
31. As a player, I want one-off resource swaps to execute simultaneously on both sides at acceptance, so neither party can front-run the other.
32. As a player, I want a treaty whose one-off swap is unfundable at acceptance time to fail ratification, log a public "proposal failed — unfundable" event, and the recipient's acceptance decision to be nullified, so bluffing has a visible cost but isn't silently swallowed.

### Active treaties: enforcement and violation

33. As a player, I want active treaties to be visible at a glance, with their remaining duration and pending obligations.
34. As a player, I want recurring tribute to be paid automatically at turn resolution for the duration of the treaty.
35. As a player, I want a recurring tribute payment I cannot afford to auto-cancel the treaty and log a public violation event, so promise-failures are unambiguous.
36. As a player, I want to unilaterally cancel any active treaty on my turn, so I can break deals.
37. As a player, I want unilateral cancellation of a treaty with active obligations (tribute, vision, borders, alliance, peace) to be recorded as a **violation**, and cancellation of a treaty with no remaining obligations to be recorded as a plain **cancellation**, so third parties can distinguish betrayal from routine wind-down.
38. As a player, I want all violation events to be visible to every player in the game, so reputation is a public artefact.
39. As a player, I want the engine to hold no opinion on reputation — no numeric score, no penalty, no flag — so agents and humans are free to invent their own reputation models from the public event log.

### Alliance semantics

40. As a player in an ALLIANCE, I want to be unable to attack my ally (hard rule in the engine), so the alliance is meaningful.
41. As a player in an ALLIANCE, I want my visible tiles to be the union of mine and my ally's visible tiles, so intelligence is genuinely shared.
42. As a player in an ALLIANCE, I want my units and my ally's units to be able to occupy the same tile, so we can defend in depth jointly.
43. As a player in an ALLIANCE, I want my units to be able to move through my ally's territory without penalty, so joint operations are practical.
44. As a player in an ALLIANCE, I want to be automatically dragged into wars: if a third party declares war on my ally, I am at war with that third party effective immediately.
45. As a player dragged into a war by alliance obligation, I want to be able to negotiate my own separate settlement (peace treaty) on my turn, so I have agency to exit a war my ally started.
46. As a player, I want an alliance to end cleanly when either party cancels it (logged as cancellation or violation per rule 37), so alliances are not permanent.
47. As an allied pair, I want to win the game jointly if and only if our combined territory/score/etc. jointly satisfy a victory condition — an ally solo-satisfying a condition does **not** share victory — so allying the leader is not a free win.
48. As an allied pair that jointly wins, I want the game to end with both of us recorded as victors, so shared victory is a real outcome.

### Agent integration

49. As an agent, I want MCP tools for every diplomatic action a human can perform, so I am not disadvantaged relative to human players.
50. As an agent, I want a `get_diplomacy_state` tool that returns my current relations, active treaties, pending proposals (both directions), recent messages, and the public event feed, filtered by visibility rules, so I can plan diplomatically.
51. As an agent, I want two new personality axes — an "honour" axis (how readily I break promises) and an "openness" axis (how readily I initiate contact and alliances) — to bias my default behaviour, so diverse agent rosters produce diverse diplomatic dynamics.
52. As an agent, I want the ability to make contradictory promises to different players (e.g. promise alliance to A and to B even if A and B are at war), so deception is a first-class strategy.
53. As a researcher, I want the public event feed to contain enough structured data (actor, counterparty, event type, turn, references to prior proposals/treaties) to reconstruct any agent's diplomatic history post-hoc, so reputation research is tractable.

### Frontend

54. As a human player, I want a dedicated Diplomacy page per game, accessible from the main game view, so diplomatic actions don't crowd the map UI.
55. As a human player, I want a relations matrix showing every player I have discovered and my current state with them (peace/alliance/war), so I see the diplomatic map at a glance.
56. As a human player, I want per-counterpart message threads with an input box, so I can converse with each other player separately.
57. As a human player, I want a treaty proposal builder where I can select a counterpart, add one or more clauses (with type-specific inputs — duration, resource amounts, etc.), and submit, so I can assemble complex deals.
58. As a human player, I want an inbox of pending proposals addressed to me with accept/decline actions, and an outbox of proposals I have made with withdraw actions, so both sides of the proposal lifecycle are visible.
59. As a human player, I want a list of my active treaties with counterparty, remaining duration, clauses, and a cancel button, so I can manage and break commitments.
60. As a human player, I want a treaty history log per game (all ratified, expired, cancelled, violated treaties) accessible for review, so I can see the game's diplomatic arc.
61. As a human player, I want a public world-events feed (declarations of war, treaty ratifications, violations, treacherous attacks) visible to me, so I can observe the global diplomatic state.
62. As a human player, I want visual emphasis (colour, iconography) distinguishing violations from routine cancellations in the events feed, so betrayal is legible at a glance.
63. As a human player or spectator, I want to replay the game and see the diplomatic events in sync with turn progression, so diplomacy is legible in replays as well as live.
64. As a human player, I want clear affordances that I can only send messages / propose treaties on my own turn, so the turn-gating is not confusing.

### Redaction & visibility edge cases

65. As a player, I want my inbox to show only messages sent to me, so third-party messages remain confidential.
66. As a player, I want active treaties and their clauses to be visible to me even if I am not a party to them, so the public-treaty rule is honoured.
67. As a player, I want pending proposals where I am neither sender nor recipient to be hidden from me, so private negotiations can happen before public ratification.
68. As a player, I want violation and declaration events to be visible to me regardless of whether I was a party, so the public event log is truly public.

## Implementation Decisions

### Data model (backend/src/game/models.py)

- Extend `GameState` with new fields: `pending_proposals`, `active_treaties`, `messages`, `diplomatic_events`. All keyed by unique ids assigned at creation.
- Reuse the existing `DiplomaticState` enum and the existing `diplomacy` dict keyed by sorted `(player_a, player_b)` tuples as the canonical relation state; the new treaty system writes to this dict when alliance or peace clauses ratify/expire/cancel.
- New Pydantic models: `Treaty` (id, parties, clauses, turn_ratified, clauses-have-per-clause-duration), `TreatyClause` (discriminated union: `PeaceClause`, `AllianceClause`, `ResourceSwapClause`, `RecurringTributeClause`, `VisionSharingClause`, `OpenBordersClause`, `FreeTextClause`), `TreatyProposal` (id, proposer, recipient, clauses, turn_proposed, expires_on_turn, status), `Message` (id, sender, recipient, body, turn_sent), `DiplomaticEvent` (id, type, actor, counterparty, turn, payload).
- `DiplomaticEvent.type` covers: `WAR_DECLARED`, `TREACHEROUS_ATTACK`, `TREATY_PROPOSED`, `PROPOSAL_WITHDRAWN`, `PROPOSAL_EXPIRED`, `PROPOSAL_ACCEPTED`, `PROPOSAL_DECLINED`, `PROPOSAL_FAILED_UNFUNDABLE`, `TREATY_CANCELLED`, `TREATY_VIOLATED`, `TREATY_EXPIRED`, `TRIBUTE_PAID`, `TRIBUTE_FAILED`, `MESSAGE_SENT`.
- Add `DiscoveredBy` tracking to `GameState` — a per-player set of other players ever observed. Updated whenever `redact_state` would have revealed a unit/city owner; once added, entries are never removed.

### Actions (discriminated union)

- Extend the `Action` union with: `DeclareWarAction`, `ProposeTreatyAction`, `RespondToTreatyAction` (accept/decline), `WithdrawTreatyAction`, `CancelTreatyAction`, `SendMessageAction`.
- Per-turn rate limit: engine rejects `SendMessageAction` beyond 5 per player per turn at action validation time.
- Diplomatic actions are executed during `resolve_turn()` in the same per-player loop as other actions. Ordering inside a turn is the submission order (deterministic).

### Turn resolution (backend/src/game/rules.py)

Within `resolve_turn()`, after existing action execution and before resource collection, add a diplomacy-resolution phase that:
1. Applies each diplomatic action in submission order, emitting events.
2. At turn end, evaluates recurring tribute obligations on every active treaty in a fixed order (by treaty id) and either debits/credits resources or auto-cancels the treaty with a violation event.
3. Advances the `turns_remaining` counter on each durational clause; clauses reaching zero expire and emit a `TREATY_EXPIRED` event (not a violation).
4. Expires pending proposals whose `expires_on_turn` has been reached.
5. Recomputes alliance-derived state (e.g. the pair-level `DiplomaticState` in the `diplomacy` dict) based on currently-active clauses.

The `execute_attack()` function is extended: if attacker and defender are at PEACE, the attack proceeds, the pair is set to WAR, and a `TREACHEROUS_ATTACK` event is emitted in addition to the usual combat events. If at ALLIANCE, the attack is rejected at validation (unchanged).

`declare_war` additionally iterates all active treaties between the two parties and cancels them with `TREATY_CANCELLED` events (not violations — the war declaration is the antecedent signal).

Alliance war-drag: when `WAR_DECLARED` is emitted for pair (A, C), the engine inspects all active alliance clauses involving A or C and auto-declares war between each ally and the opposing side, emitting further `WAR_DECLARED` events (marked with `cause: "alliance_drag"` in the payload).

### Resource validation (hybrid policy)

- `ProposeTreatyAction` validation: if proposer and recipient are currently in ALLIANCE, pre-validate that both parties can fund every clause at proposal time and reject the action if not. Otherwise, accept any proposal regardless of current stockpiles.
- `RespondToTreatyAction` with accept: at execution time, re-validate funding for immediate swap clauses. If either party cannot pay, emit `PROPOSAL_FAILED_UNFUNDABLE`, discard the treaty, do not charge anyone.

### Vision & redaction (backend/src/game/rules.py)

- `redact_state()` is extended: a player's visible tiles become the union of their own visible tiles plus those of every current ally (via active alliance clause or alliance-dropping vision-sharing clause).
- Redaction of diplomatic state per player:
  - Messages: only those where the player is sender or recipient.
  - Pending proposals: only those where the player is proposer or recipient.
  - Active treaties: all of them (public by design).
  - Diplomatic events: all of them (public by design).
  - Relations (`diplomacy` dict): only entries involving the player *or* involving two other players the viewer has discovered (so third-party wars are visible, but wars between two undiscovered players are not).

### MCP server (backend/src/mcp_server/tools/diplomacy.py)

New tool module registering:
- `declare_war(target_player)`
- `propose_treaty(recipient, clauses)`
- `respond_to_treaty(proposal_id, accept: bool)`
- `withdraw_treaty(proposal_id)`
- `cancel_treaty(treaty_id)`
- `send_message(recipient, body)`
- `get_diplomacy_state()` — returns relations, active treaties, pending proposals (in/out), recent messages, and recent diplomatic events, filtered per the viewer's visibility rules.
- `get_messages(counterparty?, since_turn?)` — inbox/outbox query.

All diplomacy tools are write-ish (no `readOnlyHint: true`) except the two getters. All are tagged `diplomacy` for discoverability.

### REST API (backend/src/api/rest.py)

Mirror the MCP surface as REST endpoints under `/api/v1/games/{game_id}/diplomacy/...`:
- `POST /declare-war`, `POST /treaties/proposals`, `POST /treaties/proposals/{id}/respond`, `DELETE /treaties/proposals/{id}` (withdraw), `DELETE /treaties/{id}` (cancel), `POST /messages`.
- `GET /diplomacy` returns the same shape as the `get_diplomacy_state` MCP tool.
- All responses use the redacted view for the authenticated player.

### WebSocket (backend/src/api/websocket.py)

Broadcast a diplomatic-events slice on turn resolution so the frontend updates the world-events feed live without polling.

### Frontend

- New route `frontend/src/app/games/[id]/diplomacy/page.tsx` as the diplomacy hub. Link from the main game page's side panel.
- Components (new): `RelationsMatrix`, `MessageThread`, `MessageInbox`, `ProposalBuilder` (clause-type-specific inputs), `ProposalInbox`, `ProposalOutbox`, `ActiveTreatiesList`, `TreatyHistoryLog`, `WorldEventsFeed`.
- Server state via React Query using a new `useDiplomacy(gameId)` hook.
- Update `frontend/src/types/game.ts` with the new Treaty/Clause/Proposal/Message/Event TypeScript types.
- Visual: violations and treacherous attacks use a distinct accent colour and icon in the events feed; cancellations use a muted style; ratifications use a positive accent.
- Turn-gating: disable send/propose controls when it is not the viewer's turn, with a tooltip explaining why.

### Agent system (agents/ + prompting)

- Add new MCP tool bindings to the agent's toolkit.
- Extend `FourXAgent` planning prompt with a concise description of diplomatic actions and the public event feed.
- Add two new personality axes to `agents/src/personalities.py`:
  - **honour** (how readily the agent breaks its promises — low honour increases propensity to violate active treaties and attack peace partners)
  - **openness** (how readily the agent initiates messages, proposals, and alliances — low openness biases toward isolation)
- Existing personalities get reasonable defaults; add at least one new personality that exercises the axes (e.g. a "treacherous diplomat").

### Persistence

- Diplomacy state lives inside the `GameState` JSON blob in the existing `Game.state` column. No schema migration. Determinism is preserved because all diplomatic state transitions happen inside `resolve_turn()`.

### Determinism & replay

- Event ids and treaty ids are generated from a seeded counter inside `GameState`, not via UUIDs or wall clock, so replays are bit-identical.
- Turn history snapshots (existing system) already capture full `GameState` post-turn; no changes needed to serve diplomacy-aware replays.

## Out of Scope

- **Numeric reputation or trust scores** computed by the engine. The engine only emits structured events; any reputation model is a consumer concern.
- **Multi-party treaties** (three or more signatories on one treaty). All treaties are strictly bilateral. A multi-way coalition is modelled as a mesh of bilateral alliances.
- **Diplomatic victory conditions** (e.g. "win by being elected world leader"). Shared victory is possible only via joint satisfaction of existing victory conditions by an allied pair.
- **Per-clause cancellation** of individual clauses inside a multi-clause treaty. Cancellation is always whole-treaty.
- **Treaty amendment/renegotiation**. To change terms, cancel the existing treaty and propose a new one.
- **Message attachments, embedded game-state references, or structured message payloads**. Messages are free-form UTF-8 text only (≤2000 chars).
- **Anonymous or pseudonymous messaging**. Every message carries its sender's player id.
- **Player-wide mutes / blocks**. Discovery is the only gate on inbound messaging.
- **Treaty templates or auto-suggest.** Proposers construct each treaty from scratch.
- **Undiscovered-player notifications** for treaties between two other undiscovered players. You don't hear about wars between players you've never met, even though those wars are "public" to those who have met both parties.
- **LLM-moderated message content filtering.** Messages are transmitted verbatim.
- **Agent-to-engine reputation feedback loops.** The engine does not read agent-held reputation state.

## Further Notes

**Game-theoretic target behaviours.** The design is deliberately biased toward emergent punishment cycles, reputation-driven cooperation, and deception. Key affordances that support this: non-binding treaties + public violation events (so tit-for-tat is possible), contradictory-promise allowance (so deception has a mechanical home), public treaty ratifications (so third parties can react to bilateral deals), and turn-gated messaging (so negotiation rhythms match the game's tempo).

**Information asymmetry as a strategic resource.** The hybrid resource-validation policy (pre-validate between allies, bluff-allowed between non-allies) is a deliberate design choice: allies already share fog-of-war vision, so proposal-time validation leaks nothing new; between non-allies, accepting the bluff option keeps stockpile privacy intact and turns "can they actually pay?" into a judgement call rather than a query.

**Alliance cascade risk.** Auto-drag into wars via alliances can produce large diplomatic chain reactions. This is intentional — it mirrors pre-1914 European geopolitics and creates interesting emergent outcomes — but the ability to negotiate a separate peace on your next turn (user story 45) is the safety valve that prevents any single alliance from locking the game into total war.

**Treacherous first strike.** The choice to *allow* attacks under peace (with an auto-flip to war and a public event) rather than requiring a prior declaration is the single biggest driver of agent strategic richness: it makes peace genuinely risky, declarations genuinely meaningful, and reputation genuinely load-bearing. If playtesting shows it's too destabilising we can revisit with a "declaration required" flag.

**Public treaties as signalling.** Making ratified treaties fully public is unusual — real diplomacy is much more opaque — but it's the right call for this sandbox because it gives third-party agents unambiguous observations to condition on, which is what most multi-agent-reasoning research needs.

**Agent personality axes.** The new honour/openness axes are the minimum viable set. They will likely need tuning after observing agent behaviour; we may later add axes like "forgivingness" (propensity to re-accept proposals from past violators) or "opportunism" (propensity to exploit weakened players).

**Frontend-MCP parity.** Every frontend capability has an MCP tool equivalent and vice versa. This is a hard invariant: humans and agents are first-class peers in this sandbox.

**Observability.** Consider emitting logfire spans for each diplomatic event type so we can run analytical queries over whole-game corpora (e.g. "proportion of proposals that are accepted, grouped by personality pair"). Not a blocker for shipping but strongly recommended early.
