# PRD: Parley — Human Frontend Experience & MCP Parity

> **Project branding:** the game ships publicly as **Parley**, at **parley.quest**. The name signals the core hook — humans and AI agents meeting at the same table to negotiate, ally, and wage war. All new user-facing surfaces (sign-in page, email sender, lobby chrome) should adopt the Parley name; the internal `fourex` codename stays in the repo and engine code.

## Problem Statement

I want to play 4X games against AI agents and other humans entirely from the web frontend, but today I cannot. When I open the lobby and click **Create Lobby**, the backend immediately rejects me with **"Not authenticated"**. The frontend expects a bearer token in `localStorage` that nothing in the UI ever sets, and there is no sign-in flow to obtain one. Even if I hack a token into `localStorage` and get past the create screen, the lobby view only polls every five seconds, so other humans joining the lobby do not appear in real time. Worse, once a game starts there is no UI at all for moving units, founding cities, training, attacking, building, conducting diplomacy, or ending a turn — the frontend can only *watch* games; it cannot *play* them.

Meanwhile, AI agents connecting through the MCP server can do all of this and more. They receive a proper, game-scoped, cryptographically hashed API key when they create or join a game, and they have a full toolbelt of lifecycle, gameplay, and diplomacy tools. This asymmetry means the "human experience" is effectively vestigial — the game is only playable by agents — and the two authentication models (an insecure string-prefix check for humans versus real hashed API keys for MCP) cannot interoperate, so a human and an agent cannot sit at the same table.

I want one game, two front doors: the browser for humans, MCP for agents, both sharing a single auth story and a common capability surface.

## Solution

Unify authentication behind the existing API-key model, replace the `player_*` string-prefix hack with a real identity flow (**magic link by email**), and build the missing gameplay UI so that every core action an MCP agent can take is also available to a human in the browser.

From the player's perspective:

1. **I sign in with my email.** I enter my address, receive a magic-link email, click it, and I am now a known identity in the browser. No passwords, no account setup.
2. **I create or join a lobby.** I create a lobby from the dashboard or open a shared link. On join, the backend mints an API key bound to (my identity, this game) and the frontend stores it silently.
3. **The lobby updates live.** When another human clicks the join link, I see them appear in the lobby roster without refreshing.
4. **I play turns in the browser.** I select units, queue moves, train and build, open a diplomacy panel to message or propose treaties, then press **End Turn** to submit my queued actions. The map updates when the turn resolves.
5. **An MCP agent can join my game** by using the same `join_game` MCP tool that already exists — we're seated at the same table with equivalent capabilities.

The initiative ships in three phases so each phase is independently shippable:

- **Phase 1 — Identity, Auth, Lobby, Realtime.** Magic-link sign-in, unified API-key auth, real-time lobby via WebSocket, working **Create Lobby** and **Join** flows.
- **Phase 2 — Human Gameplay.** Action queueing UI (move, attack, found city, train, build), **End Turn** submission, state-refresh on turn resolution.
- **Phase 3 — Diplomacy.** Human-facing UI over the existing diplomacy REST endpoints: messaging, treaty proposals, responses, withdrawals, war declarations.

## User Stories

**Identity & session**
1. As a new visitor, I want to enter my email address and receive a magic-link, so that I can sign in without creating a password.
2. As a returning visitor, I want my browser to remember my identity, so that I don't need to re-verify on every visit until my session expires.
3. As a signed-in user, I want a visible indicator of who I'm signed in as and a way to sign out, so that I can switch identities or end my session.
4. As a user whose magic-link has expired, I want a clear error and a way to request a new link, so that I'm not stranded.

**Lobby creation and joining**
5. As a signed-in user, I want the **Create Lobby** button to actually create a lobby, so that I can start a game.
6. As a lobby creator, I want to configure map size, seed, and player slot count at creation time, so that I can tailor the game.
7. As a lobby creator, I want a shareable URL for my lobby, so that I can invite other humans or publish it for an MCP agent to join.
8. As a signed-in user visiting a lobby link, I want to see the lobby details and a **Join** button if a slot is open, so that I can take a seat.
9. As a joined player, I want the backend to return me an API key bound to this game and store it for me automatically, so that subsequent authenticated calls succeed.
10. As a lobby participant, I want to see the roster of joined players update in real time when someone else joins or leaves, so that I know who I'm playing.
11. As the lobby creator, I want a **Start Game** control that is only enabled when all slots are filled, so that I can't start prematurely.
12. As a non-creator participant, I want to see that only the creator can start the game, so that I'm not confused by a missing button.
13. As a player, I want to be told when the game transitions from **waiting** to **active** without needing to refresh, so that I enter the game at the moment play begins.

**Lifecycle across both front doors**
14. As an MCP agent, I want to join a lobby that was created by a human and receive the same shape of API-key payload I receive today, so that I don't need a separate code path.
15. As a human player, I want to join a lobby that was created by an MCP agent and receive an API key the same way I would from a human-created lobby, so that the two front doors interoperate.

**Auth unification**
16. As the engineer, I want a single authentication dependency used by every REST endpoint and MCP tool that requires a player identity, so that auth bugs only need to be fixed in one place.
17. As an operator, I want API keys to expire after a bounded window and support revocation on demand, so that stale keys cannot be replayed indefinitely.
18. As a developer, I want the insecure `player_*` string-prefix auth check fully removed from the codebase, so that nobody accidentally relies on it.

**Gameplay — action submission**
19. As a human player on an active turn, I want to click a unit on the map and see its valid moves highlighted, so that I can decide where to send it.
20. As a human player, I want to queue a move order for a selected unit, so that it executes when I end my turn.
21. As a human player, I want to queue an attack order against an adjacent hostile unit or city, so that I can engage in combat.
22. As a human player, I want to queue **Found City** for a settler unit on a valid tile, so that I can expand.
23. As a human player, I want to queue **Train Unit** from a city, with a selector of unit types available given the city's buildings and my resources, so that I can grow my army.
24. As a human player, I want to queue **Build Building** in a city, with a selector of eligible buildings, so that I can develop my economy.
25. As a human player, I want to queue improvement-building orders on worker-type units, so that I can exploit terrain.
26. As a human player, I want to see my queued actions as a list with the ability to reorder or cancel any of them before I end the turn, so that I can correct mistakes.
27. As a human player, I want to click **End Turn** to submit all queued actions atomically, so that the turn resolves.
28. As a human player, I want invalid queued actions to be flagged client-side where possible and rejected with a clear message server-side otherwise, so that I understand why an action failed.
29. As a human player, I want the map, resources, and event log to refresh immediately after a turn resolves, so that I can plan my next turn.
30. As a human player in a multi-player game, I want to see which other players have submitted their turn and which are still deciding, so that I know whether to wait or nudge.
31. As a human player, I want fog-of-war redaction applied to what I see, so that I cannot cheat by reading opponents' state.

**Gameplay — diplomacy (parity)**
32. As a human player, I want to open a diplomacy panel listing every other player, their relation status (peace, war, allied) and our treaty history, so that I can make informed decisions.
33. As a human player, I want to send a private free-text message to another player, so that I can negotiate.
34. As a human player, I want to receive messages addressed to me and see them in a threaded inbox, so that I don't miss communications.
35. As a human player, I want to propose a treaty (peace, resource swap, recurring tribute, or free-text) with specific clauses, so that I can formalise an agreement.
36. As a human player, I want to see treaty proposals directed at me and accept, reject, or counter each one, so that I can engage in negotiation.
37. As a human player, I want to withdraw a treaty proposal I've made before it is accepted, so that I can back out of an offer.
38. As a human player, I want to cancel an active treaty, so that I can end agreements that no longer suit me.
39. As a human player, I want to declare war on another player with a confirmation prompt, so that I don't trigger war accidentally.
40. As a human player, I want diplomacy actions to follow the same queued-until-End-Turn model as gameplay actions, so that the mental model is consistent.

**Real-time updates beyond the lobby**
41. As a human player in an active game, I want the WebSocket to push lightweight events (turn resolved, diplomatic message received, treaty proposal arrived) to my browser, so that I don't need to poll.
42. As a human player, I want the WebSocket to authenticate using my existing API key, so that the event stream respects fog-of-war and doesn't leak opponent information.
43. As a human player, I want a graceful fallback to polling if my WebSocket connection drops, so that a flaky network doesn't silently freeze my client.

**Boundaries between human and agent experiences**
44. As the engineer, I want analysis tools (`analyze_territory`, `evaluate_military_position`, `find_resource_opportunities`, `calculate_distances`) to remain MCP-only, so that humans reason about the board themselves and the UI stays uncluttered.
45. As the engineer, I want agent-memory tools (`write_scratchpad`, `read_scratchpad`, strategic goals, opponent models, turn notes) to remain MCP-only, so that agent cognition aids don't leak into the human UI.
46. As the engineer, I want history tools (`get_turn_history`, `get_turn_snapshot`) and MCP map renderers (`render_map_ascii`, `render_map_svg`, `render_map_image`) to remain MCP-only for this PRD, so that scope stays bounded; a human-facing history viewer may come in a later initiative.

## Implementation Decisions

### Authentication and identity

- **Identity provider: Auth.js in Next.js with the Resend email provider.** Magic-link issuance, token signing, verification, and the browser session all live in the Next.js frontend. FastAPI does not own sign-in.
- **Session strategy: JWT.** Auth.js is configured with the JWT session strategy. The session JWT is signed with a secret shared between Next.js and FastAPI (environment variable on both sides). No session table is needed on either service.
- **FastAPI trust relationship:** FastAPI gains a dependency that verifies the Auth.js JWT (signature, expiry, issuer) on every lobby-lifecycle request and extracts the user identity claim. FastAPI does not issue, store, or mutate sessions.
- **UserIdentity storage:** A minimal `UserIdentity(id, email UNIQUE, created_at)` row exists in the shared Postgres database, written by a Next.js server route on first successful verify and referenced by `PlayerApiKey`. Auth.js itself does not need a DB adapter for sessions because JWT is stateless; email-verification token storage is handled by the Auth.js Resend provider's built-in mechanism.
- **Per-game API key unchanged:** The existing `PlayerApiKey` model remains the authority for game-scoped operations. It is minted at `create_game` / `join_game` and returned to the caller. Its `user_identity_id` column is populated from the Auth.js JWT claim when the caller is human; left null for MCP-originated keys.
- **Browser API-key storage:** API keys are returned on create/join and stored in the browser (keyed by game ID). They are sent as `Authorization: Bearer` for REST and as a WebSocket subprotocol or query parameter for the event stream.
- **Single auth dependency for gameplay:** All REST endpoints and MCP tools that require a player share one verification path that looks up `PlayerApiKey` by hashed key and returns the bound `(game_id, player_id, expires_at)`. This is orthogonal to the Auth.js JWT check — the JWT authorises lobby lifecycle, the API key authorises gameplay/diplomacy.
- **Deprecation:** The string-prefix `player_*` check is removed from the REST auth dependency entirely. Any tests or scripts depending on it are migrated.

### Lobby, slots, and game start

- **Slot policy:** Open slots, first-come-first-served. The creator sets total slot count; any signed-in user with the lobby URL can claim an open slot.
- **AI seating:** Out of this PRD. AI agents must join externally via MCP using the existing `join_game` tool. The lobby does not attempt to spawn or configure AI seats.
- **Lobby state model:** Unchanged backend-side (`waiting` → `active`). A new "who joined" broadcast is added over WebSocket.
- **Start authority:** Only the lobby creator can start, and only when all slots are filled.
- **Unified join path across front doors.** Both the MCP `join_game` tool and the REST lobby-join endpoint must delegate to a single controller method (`persistent_game_controller.join_game`) and accept any lobby in a pre-start status (today: `waiting`). The current MCP tool hard-codes `status == "created"` and runs a bespoke DB path, so lobbies created by the browser are unreachable from MCP — this is the user-story-14/15 parity defect and it blocks the hybrid human+agent table. The lobby UI must also surface an "Invite an MCP agent" affordance with the exact `join_game(game_id=..., player_name=...)` snippet a user can paste into their agent, since there is otherwise no discoverable path from a browser lobby to an MCP-hosted seat.

### Real-time: WebSocket contract

- **Authentication:** WebSocket clients pass their game-scoped API key on connect (query parameter or subprotocol header). The handler validates against `PlayerApiKey` before subscribing the connection.
- **Subscription scope:** One connection is scoped to one `(player, game)` pair. Events are filtered server-side to respect fog-of-war for that player.
- **Event types (minimum):** `lobby.player_joined`, `lobby.player_left`, `lobby.started`, `turn.resolved`, `diplomacy.message_received`, `diplomacy.proposal_received`, `diplomacy.proposal_responded`, `diplomacy.treaty_cancelled`, `diplomacy.war_declared`.
- **Broadcast integration:** The game controller emits events at state transitions (join, leave, start, turn resolve) and diplomacy endpoints emit events on each diplomacy mutation.
- **Fallback:** Frontend falls back to polling at current cadence if the WebSocket connection cannot be established or drops repeatedly.

### Frontend structure

- **New routes/screens:** sign-in (email entry), magic-link callback, lobby detail (real-time roster), in-game view with map + action queue + turn controls, diplomacy panel.
- **API client layer:** Extend the existing API client with methods for every new endpoint (`requestMagicLink`, `verifyMagicLink`, `submitActions`, the diplomacy suite).
- **Action queue:** Client-side queue of action objects matching backend schemas. `End Turn` posts the queue to `/actions` as a single batch.
- **Map interactions:** Click to select; highlight valid moves/attacks; right-click or context menu for orders; keyboard shortcuts optional.
- **Diplomacy panel:** Per-opponent subview with relation state, message thread, treaty proposals (outbound and inbound), and active treaties.
- **Realtime hook:** A React hook wraps the WebSocket, reconnects with backoff, and invalidates the relevant React Query caches on each event type.

### Turn-flow UX

- **Queue-then-submit model.** All actions accumulate client-side until `End Turn`. On submit, the full queue posts to `/actions`. Client-side validation flags obvious errors before submission; server-side validation is authoritative.
- **Waiting state.** After submission, the client shows a "waiting for other players" indicator and listens for `turn.resolved` over WebSocket (with polling fallback).

### API contracts (shape, not paths)

- **Sign-in / verify:** handled entirely by Auth.js routes in Next.js. No FastAPI contract.
- **Create lobby:** requires a valid Auth.js JWT; response includes lobby detail and an API key bound to the creator as the first-seated player.
- **Join lobby:** requires a valid Auth.js JWT; response includes lobby detail and the new API key for the joining player.
- **Submit actions:** requires API key; accepts a list of `Action` objects (existing discriminated union); atomic — either all accepted or all rejected with per-item errors.
- **WebSocket connect:** requires API key; subscribes the connection to events for `(player, game)`.

### Out of scope for analysis and agent-memory parity

Per the boundaries above, the following MCP tools intentionally have no human UI equivalent in this initiative: `analyze_territory`, `evaluate_military_position`, `find_resource_opportunities`, `calculate_distances`, `write_scratchpad`, `read_scratchpad`, `write_strategic_goals`, `read_strategic_goals`, `write_opponent_models`, `read_opponent_models`, `write_turn_notes`, `read_turn_notes`, `get_turn_history`, `get_turn_snapshot`, `render_map_ascii`, `render_map_svg`, `render_map_image`.

### Phase ordering

- **Phase 1 — Identity, Auth, Lobby, Realtime.** Magic-link sign-in and session cookie; unified API-key auth; remove `player_*` hack; working Create Lobby; working Join; WebSocket authenticated; real-time lobby roster; Start Game transition.
- **Phase 2 — Human Gameplay.** Map interaction; action queue UI for move/attack/found-city/train/build/improvement; End Turn submission; post-resolution state refresh via WebSocket and query invalidation.
- **Phase 3 — Diplomacy.** Diplomacy panel wired to existing REST endpoints; inbox and outbound messaging; treaty proposal/response/withdrawal/cancellation; war declaration with confirmation.

## Out of Scope

- Rewriting the deterministic game engine or altering the `resolve_turn()` semantics.
- Persistent user profiles beyond what magic-link identity provides (no display-name history, avatars, achievements, friends, ELO).
- Password, OAuth, or SSO sign-in.
- AI seat configuration from within the lobby UI; AI agents continue to join via MCP out-of-band.
- Spectator/unauthenticated public viewing of games.
- Multi-device session sync beyond a single browser; if a user signs in on another device they get a fresh session.
- Human-facing analysis helpers, agent memory surfaces, turn-history viewers, and alternate map renderers (all remain MCP-only for this initiative).
- Mobile-responsive or touch-first gameplay UI.
- Replay, undo, or rewind of submitted actions once a turn is resolved.
- Email deliverability infrastructure beyond a single sender and plain-text magic-link template.

## Further Notes

- Email transport is **Resend**, integrated through the Auth.js Resend provider. The API key lives in the Next.js environment only; FastAPI never sees it.
- The verified sending domain is **parley.quest**. Magic-link emails send from a Parley-branded address (e.g. `hello@parley.quest` or `noreply@parley.quest`). DNS records for SPF, DKIM, and DMARC must be configured on parley.quest before the first batch of real sign-ups; the domain should be warmed by sending a small number of messages to known-good inboxes before opening sign-ups broadly. For local development, the Resend onboarding sender is fine.
- The Auth.js JWT signing secret is shared via environment variable between Next.js and FastAPI. Rotating it requires a coordinated redeploy of both services — acceptable at this scale; if it becomes painful, move to a JWKS endpoint later.
- The existing diplomacy REST endpoints (`/diplomacy/*` in `backend/src/api/rest.py`) already cover the capabilities Phase 3 needs; Phase 3 is predominantly frontend work plus WebSocket event emission at each diplomacy mutation point.
- The existing WebSocket endpoint at `backend/src/api/websocket.py` has no authentication and is not emitted to from the game controller; both gaps must be closed in Phase 1.
- API-key expiry is currently 24 hours. Keep that default; if a game lasts longer, renewal can be handled by re-authenticating the session and re-minting on demand — design the renewal endpoint in Phase 1 even if UI for it waits.
- The prior diplomacy rollout (Phases 1–4 in the git log) is the model for how to phase this work: each phase ships an independently useful increment, with tests and commits per phase.
- Follow-up: after the PRD is approved, run `/prd-to-plan` to generate tracer-bullet implementation phases, then iterate implementation via the usual loop.
