# Plan: Parley — Human Frontend Experience & MCP Parity

> Source PRD: `plans/human-frontend-parity-prd.md`

## Branding

The public-facing product is **Parley**, deployed at **parley.quest**. The repo codename (`fourex`) and internal module names stay as-is; only user-visible surfaces adopt the Parley brand: the Next.js site header and metadata, the sign-in page copy, the magic-link sender address and email body, and the lobby/game chrome. Favicon, page title, and OpenGraph metadata should be updated as part of Phase 1.

## Architectural decisions

Durable decisions that apply across all phases:

- **Routes** (all in Next.js)
  - `/api/auth/*` — Auth.js-managed routes (sign-in, email callback, sign-out, session). Configured with the Resend email provider and JWT session strategy.
  - `/signin` — Auth.js-rendered or custom sign-in page (email entry).
  - `/` — dashboard / game list (existing, now gated behind an Auth.js session).
  - `/games/:gameId` — lobby + in-game view (existing, expanded).
  - `/games/:gameId/diplomacy` — diplomacy sub-view (new; may render as a panel within the game view rather than a separate page, but the route is reserved).
- **Schema**
  - New `UserIdentity(id, email UNIQUE, created_at)` — the verified human behind a browser session. Row is upserted by a Next.js server route the first time an Auth.js verify succeeds for a given email.
  - No `MagicLinkToken` or `UserSession` tables. Magic-link verification tokens are handled by the Auth.js Resend provider's own adapter storage; browser sessions are JWTs and therefore stateless.
  - Existing `PlayerApiKey` retained, extended with a nullable `user_identity_id` column so human-created keys can be attributed to a `UserIdentity`. MCP-created keys leave it null.
  - Existing `Game`, `GameState` unchanged.
- **Key models**
  - `UserIdentity` is the browser-side identity; `PlayerApiKey` is the game-scoped capability.
  - The Auth.js JWT authorises lobby lifecycle only (create, join, list own games). Every gameplay or diplomacy call requires an API key.
  - API keys remain 24h-expiry. A renewal path off the JWT is added but its UI can ship later.
- **Auth**
  - **Identity layer:** Auth.js in Next.js with the Resend email provider. Session strategy = JWT. The signing secret is shared via environment variable between Next.js and FastAPI; rotating it requires coordinated redeploy of both services.
  - **Email sender:** magic-link emails send from a Parley-branded address on the verified **parley.quest** domain (e.g. `hello@parley.quest`). SPF, DKIM, and DMARC records on parley.quest must be configured in Resend before real sign-ups are opened.
  - **FastAPI JWT verifier:** a single dependency validates the Auth.js JWT (signature, expiry) on each lobby-lifecycle request and extracts the `user_identity_id` claim.
  - **FastAPI API-key dependency:** one shared REST dependency resolves `(game_id, player_id, expires_at)` from a hashed API-key lookup. All gameplay/diplomacy endpoints adopt it.
  - The JWT verifier and the API-key verifier are orthogonal: lobby-lifecycle endpoints use the JWT, gameplay/diplomacy endpoints use the API key, neither is ever used for both.
  - The `player_*` string-prefix check is deleted as part of Phase 2; there is no coexistence window.
- **WebSocket**
  - One connection per `(player, game)` pair.
  - Connect-time auth: API key passed via subprotocol header (preferred) or query parameter. Handler validates against `PlayerApiKey` before subscribing.
  - Events are filtered server-side against the connected player's fog-of-war.
  - Event names are namespaced:
    - `lobby.player_joined`, `lobby.player_left`, `lobby.started`
    - `turn.submitted`, `turn.resolved`
    - `diplomacy.message_received`, `diplomacy.proposal_received`, `diplomacy.proposal_responded`, `diplomacy.treaty_cancelled`, `diplomacy.war_declared`
  - Frontend falls back to polling on connect failure or repeated drops.
- **Action queue model**
  - Gameplay and diplomacy actions accumulate client-side.
  - `End Turn` is the only submission trigger; the full queue posts to `/actions` as one atomic batch.
  - Diplomacy actions use the same queue so players cannot short-circuit turn resolution.
- **MCP compatibility invariant**
  - Every phase must leave the MCP `create_game` / `join_game` / gameplay / diplomacy tools fully functional. A human and an agent sharing one game is a continuous acceptance criterion, not a per-phase one.

---

## Phase 1: Auth.js sign-in with Resend + Parley branding

**User stories**: 1, 2, 3, 4, 16

### What to build

Auth.js is installed in the Next.js frontend and configured with the Resend email provider and the JWT session strategy. The user lands on `/signin`, enters their email, and Auth.js issues a Parley-branded magic-link email via Resend, sent from a verified address on **parley.quest**. Clicking the link hits Auth.js's email-callback route, which verifies the token and sets the Auth.js session JWT cookie. The dashboard now shows a "signed in as [email]" indicator and a sign-out control wired to Auth.js's sign-out endpoint. Expired or already-used tokens produce Auth.js's default error screen (customised for copy) with a "request a new link" action.

Alongside the auth work, this phase lands the Parley brand on every user-visible surface: site title and OpenGraph metadata, favicon, sign-in page copy ("Sign in to Parley"), the magic-link email subject and body, and the lobby page header. The internal `fourex` codename stays in the repo and engine; this is cosmetic only.

The parley.quest domain is set up in Resend with verified SPF, DKIM, and DMARC records as part of this phase so the first magic link actually delivers.

On first successful verify for a given email, a small Next.js server route upserts a row into the shared `UserIdentity(id, email, created_at)` Postgres table so FastAPI has something to reference later when minting `PlayerApiKey`s. The JWT carries the `UserIdentity.id` as a claim.

The JWT signing secret (`AUTH_SECRET` / matching env on FastAPI) is added to both services' environments. FastAPI gains its JWT verifier dependency in this phase, but no FastAPI endpoint uses it yet — Phase 2 introduces the first caller. Adding the verifier here lets us unit-test it against real Auth.js-issued tokens before depending on it.

This phase does not touch any game logic, any MCP code, or the existing `player_*` auth path. The dashboard is gated behind an Auth.js session; unauthenticated visitors are redirected to `/signin`.

### Acceptance criteria

- [ ] Auth.js is installed in the Next.js app with the Resend email provider and JWT session strategy.
- [ ] parley.quest is verified in Resend with SPF, DKIM, and DMARC records in place.
- [ ] A new visitor can enter an email at `/signin` and receive a Parley-branded magic-link email from a parley.quest sender.
- [ ] Site title, OpenGraph metadata, favicon, sign-in copy, magic-link email subject/body, and lobby header all use the Parley brand.
- [ ] Clicking the link signs them in and redirects to the Parley dashboard.
- [ ] The dashboard displays the signed-in email and a sign-out button; sign-out clears the session cookie.
- [ ] Expired or previously-used magic-link tokens produce a clear error and a re-request affordance.
- [ ] On first successful verify, a `UserIdentity` row is upserted by email; subsequent verifies reuse the existing row.
- [ ] The Auth.js JWT includes the `UserIdentity.id` as a claim.
- [ ] The `AUTH_SECRET` env var is set in both Next.js and FastAPI environments.
- [ ] FastAPI has a JWT verifier dependency with unit tests proving it accepts real Auth.js tokens and rejects tampered/expired ones.
- [ ] `UserIdentity` table exists with an Alembic migration; `PlayerApiKey` has a nullable `user_identity_id` column added.
- [ ] MCP `create_game` / `join_game` continue to function with no code changes.

---

## Phase 2: Create & Join lobby with unified API-key auth

**User stories**: 5, 6, 7, 8, 9, 14, 15, 17, 18

### What to build

Create Lobby and Join actually work from the frontend, and the legacy `player_*` string-prefix auth is removed in the same phase because Create Lobby cannot succeed without the new auth path.

A signed-in user on the dashboard can click **Create Lobby**, configure map size, seed, and slot count, and submit. The frontend attaches the Auth.js JWT (forwarded from the server session) to the request; FastAPI's JWT verifier validates it and extracts `user_identity_id`, creates the game with the creator seated in slot 0, mints a `PlayerApiKey` bound to `(game_id, creator_player_id, user_identity_id)`, and returns the lobby detail plus the API key. The browser stores the API key keyed by game ID and redirects to `/games/:gameId`.

Any signed-in user with the lobby URL can open it and see the lobby detail with a **Join** button if a slot is open. Joining validates the JWT, appends the player to the game, mints an API key for them, and returns it in the response. The frontend stores it silently.

The shared REST auth dependency is introduced and every gameplay/diplomacy endpoint is migrated to it. The legacy string-prefix check is deleted; any tests or scripts depending on it are migrated to mint real API keys. MCP `create_game` and `join_game` are audited to confirm their API-key payload shape is unchanged — the frontend and MCP now produce identical keys from the same table, so a human and an agent can sit in the same lobby.

Lobby roster still polls at the existing cadence in this phase; realtime arrives in Phase 3.

Shareable URL is just the `/games/:gameId` path — nothing fancy. The lobby detail surfaces a "copy link" button.

### Acceptance criteria

- [ ] A signed-in user can create a lobby end-to-end and land on the lobby page with state persisted.
- [ ] `POST /games` and `POST /games/:id/join` accept the Auth.js JWT and reject requests without one or with an invalid one (401).
- [ ] The `POST /games` response includes a new API key; the browser stores it keyed by `gameId`.
- [ ] A second signed-in user can open the lobby URL and join an open slot; their join response also returns an API key.
- [ ] Newly minted `PlayerApiKey` rows for human callers have `user_identity_id` populated; MCP-minted keys leave it null.
- [ ] The "copy link" control copies the lobby URL to the clipboard.
- [ ] All REST endpoints requiring a per-game player identity use the shared API-key auth dependency.
- [ ] The `player_*` string-prefix auth check is removed from the codebase; grep confirms zero references.
- [ ] MCP `create_game` returns API keys in the same shape as before.
- [ ] Cross-front-door test: a human creates a lobby and an MCP agent calls `join_game` with the same `game_id`, receives a valid API key, and both seats appear in the roster.
- [ ] Backend tests cover: create-lobby happy path, join happy path, join when full, JWT rejection paths (missing/expired/tampered), unified API-key auth on a representative gameplay endpoint.

---

## Phase 3: Real-time lobby via authenticated WebSocket

**User stories**: 10, 11, 12, 13, 42, 43

### What to build

Lobby updates become realtime and the Start Game flow lights up.

The WebSocket endpoint gains connect-time authentication: the client passes its game-scoped API key (subprotocol or query parameter) and the server validates it against `PlayerApiKey`, binding the connection to `(player, game)`. Connections without a valid key are rejected.

The persistent game controller emits `lobby.player_joined`, `lobby.player_left`, and `lobby.started` at the corresponding state transitions. The frontend opens one WebSocket per open game page, subscribes, and invalidates the React Query cache for the lobby detail on each event — the roster now updates live.

The **Start Game** button appears only for the lobby creator and is enabled only when all slots are filled. Clicking it transitions the game to `active` and emits `lobby.started`. All connected clients receive the event and transition their UI into the in-game view (map is rendered read-only for now; gameplay controls come in Phase 4).

Polling remains as a fallback: if the WebSocket fails to connect or drops repeatedly within a short window, the client reverts to the existing polling cadence and surfaces a subtle "reconnecting" indicator.

### Acceptance criteria

- [ ] WebSocket connections require a valid API key; connections without one are rejected with a close code.
- [ ] Events are scoped to the connected `(player, game)`; a client cannot subscribe to a game it has no key for.
- [ ] Joining a lobby in browser A causes the roster in browser B to update without a manual refresh.
- [ ] Leaving a lobby emits `lobby.player_left` and updates observers live.
- [ ] The Start Game button is visible only to the creator and disabled until all slots are filled.
- [ ] Clicking Start transitions the game to active and all connected clients move into the in-game view.
- [ ] WebSocket drop forces a polling fallback within a bounded retry window.
- [ ] MCP agents in the same lobby are represented in the live roster identically to humans.
- [ ] Backend tests cover: WS auth rejection, event emission on join/leave/start, fog-of-war scoping.

---

## Phase 4: Gameplay tracer — move and end turn

**User stories**: 19, 20, 26, 27, 29, 31, 41

### What to build

A single action type is wired from UI click to post-resolution state refresh, proving the full gameplay loop. Move is chosen because it exercises selection, valid-move computation, queue management, submission, turn resolution, and state refresh — every layer the remaining actions will share.

On an active game, clicking a friendly unit selects it and highlights its valid move tiles using the existing valid-moves logic. Clicking a highlighted tile queues a move order. A sidebar shows the queued-action list with a remove control per item. **End Turn** posts the queue to `/actions` as a single atomic batch.

After submission, the client shows a minimal "waiting" state and listens for `turn.resolved` over WebSocket. On the event, the client invalidates the game-state query, the map and event log refresh, and the queue clears. State is rendered with fog-of-war redaction as returned by the existing `/state` endpoint.

`turn.resolved` is emitted by the controller at the end of `resolve_turn()`.

Non-move action types are out of scope for this phase; the queue data structure is generic enough to accept them but the UI affordances wait for Phase 5.

### Acceptance criteria

- [ ] Clicking a friendly unit on the map selects it and highlights valid move tiles.
- [ ] Clicking a highlighted tile adds a move order to the queue sidebar.
- [ ] Queued orders can be removed individually before submission.
- [ ] End Turn posts the queue to `/actions` atomically.
- [ ] The client receives `turn.resolved` over WebSocket and the map/state refresh automatically.
- [ ] Server-side validation rejects illegal moves and the client surfaces the error.
- [ ] Rendered state respects fog-of-war.
- [ ] An MCP agent in the same game can submit its own actions independently and both players' turns resolve together.
- [ ] Backend tests cover: `turn.resolved` emission, batch `/actions` atomicity.

---

## Phase 5: Remaining gameplay action types

**User stories**: 21, 22, 23, 24, 25, 28

### What to build

The action queue gains UI affordances for attack, found city, train unit, build building, and build improvement. Each hooks into the same queue → End Turn → `turn.resolved` pipeline from Phase 4.

- **Attack**: with a unit selected, hostile units and cities within attack range are highlighted; clicking one queues the attack.
- **Found City**: selecting a settler-type unit on a valid tile surfaces a Found City control; clicking queues the action.
- **Train Unit**: clicking a friendly city opens a city panel listing unit types trainable given current buildings and resources; selecting one queues a train order.
- **Build Building**: the city panel also lists buildable buildings given prerequisites; selecting one queues a build order.
- **Build Improvement**: worker-type units surface improvement options on eligible tiles.

Client-side validation blocks obviously-invalid actions (insufficient resources, wrong unit type, wrong terrain) where the information is already available locally. Server-side validation remains authoritative; rejections surface per-item in the queue sidebar with a readable message.

### Acceptance criteria

- [ ] Every action type in the PRD (move, attack, found city, train, build building, build improvement) is queueable from the UI.
- [ ] Client-side validation flags obviously-invalid actions before submission.
- [ ] Server-side rejections produce per-item error messages in the queue sidebar.
- [ ] All queued action types submit together atomically on End Turn and resolve together.
- [ ] City panel correctly filters unit and building options by prerequisites and resources.
- [ ] Backend tests cover representative rejection paths for each action type.
- [ ] MCP agents and humans can play a full game to a meaningful state (cities founded, units trained, combat exchanged) against each other.

---

## Phase 6: Turn-submission status

**User stories**: 30

### What to build

After End Turn, the human needs to know why nothing is moving: is the server slow, is another player still deciding, or did something break?

The controller emits `turn.submitted` whenever any player submits their batch, including which player. The frontend tracks per-player submission state for the current turn and renders it in a sidebar: each opponent shows as "deciding" or "submitted". A banner shows "waiting for N player(s)" while any are outstanding. On `turn.resolved`, the banner clears and the indicators reset for the new turn.

This phase is pure UX: no new gameplay capability, just visibility into existing state.

### Acceptance criteria

- [ ] Submitting End Turn emits `turn.submitted` visible to all connected players for that game.
- [ ] Each opponent is shown as "deciding" or "submitted" for the current turn.
- [ ] A waiting banner appears while any player is outstanding and disappears on `turn.resolved`.
- [ ] Indicators reset at the start of each new turn.
- [ ] MCP agents' submissions are reflected in the human's UI the same way human submissions are.

---

## Phase 7: Diplomacy — relations panel and messaging

**User stories**: 32, 33, 34, 40

### What to build

A diplomacy panel opens alongside the in-game view. It lists every other player (human or agent) with their current relation state (peace, war, allied) and any active treaties.

Selecting an opponent opens a threaded message view. The player can compose a private free-text message; sending it queues a message action via the existing `/diplomacy/messages` endpoint — following the same End-Turn queue model as gameplay. Inbound messages arrive via `diplomacy.message_received` WebSocket events and appear in the thread live.

The panel surfaces an unread badge on opponents with new inbound messages since the last view.

### Acceptance criteria

- [ ] The diplomacy panel lists every other player with relation state and active treaties.
- [ ] Selecting an opponent opens a threaded inbox of messages between that player and the viewer.
- [ ] Composing and sending a message queues a diplomacy action that posts on End Turn.
- [ ] Inbound messages appear live via `diplomacy.message_received`.
- [ ] Unread badges appear for opponents with new messages and clear when the thread is viewed.
- [ ] A human can exchange a full round of messages with an MCP agent and vice versa.

---

## Phase 8: Treaty lifecycle UI

**User stories**: 35, 36, 37, 38

### What to build

Treaty operations are wired through the diplomacy panel.

- **Propose**: a "Propose Treaty" control opens a form supporting the four treaty kinds (peace, resource swap, recurring tribute, free-text) with the clause shape each kind needs. Submitting queues a proposal action.
- **Respond**: inbound proposals appear in a distinct inbox section with accept and reject controls. Selecting either queues the response action.
- **Withdraw**: the proposer can see their own outstanding outbound proposals and withdraw any before it is accepted; withdrawing queues the action.
- **Cancel**: active treaties list a cancel control that queues a cancellation.

All four operations use the existing diplomacy REST endpoints. `diplomacy.proposal_received`, `diplomacy.proposal_responded`, and `diplomacy.treaty_cancelled` WebSocket events drive live updates to both sides of every transaction.

### Acceptance criteria

- [ ] A player can compose and propose all four treaty kinds with the appropriate clause shape for each.
- [ ] Inbound proposals appear live via `diplomacy.proposal_received` and can be accepted or rejected.
- [ ] The proposer can withdraw their own outstanding proposals; the counterparty sees the withdrawal live.
- [ ] Active treaties can be cancelled; both parties see the cancellation live via `diplomacy.treaty_cancelled`.
- [ ] All treaty actions use the End-Turn queue model.
- [ ] A human and an MCP agent can negotiate a full proposal-and-acceptance cycle end-to-end in either direction.

---

## Phase 9: Declare war

**User stories**: 39

### What to build

A "Declare War" control appears for any opponent currently at peace. Clicking it opens a confirmation dialog that spells out the consequences (treaties cancelled, relation set to war). Confirming queues a war-declaration action on the existing endpoint; cancelling dismisses with no effect.

On resolution, `diplomacy.war_declared` fires and both parties' diplomacy panels update live.

### Acceptance criteria

- [ ] The Declare War control is visible only for opponents currently at peace.
- [ ] Clicking it opens a confirmation dialog; confirming queues the action, cancelling is a no-op.
- [ ] On resolution, the relation flips to war and any treaties implicated by the declaration are cancelled.
- [ ] Both parties see the war declaration live via `diplomacy.war_declared`.
- [ ] The feature works identically whether the declarer is human or an MCP agent and whether the target is human or an MCP agent.
