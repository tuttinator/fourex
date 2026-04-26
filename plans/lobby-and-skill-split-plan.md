# Plan: Lobby redesign + agent key surfacing + skill split

> Source PRD: `plans/lobby-and-skill-split-prd.md`

## Architectural decisions

Durable decisions that apply across all phases:

- **Routes** (all under `/api/v1`):
  - `POST /games` — extended with `creator_seated: bool` and optional
    `slots: list[SlotConfig]`. Legacy body still accepted.
  - `GET /games/{game_id}` — response gains a `slots` array; per-slot
    plaintext API keys included only for the creator and only while
    status is `waiting`.
  - `PUT /games/{game_id}/slots` — replace slot configuration in
    `waiting` status. Creator-only (per-game API key).
  - `POST /games/{game_id}/slots/{slot_index}/regenerate-key` —
    rotate an Agent slot's key. Creator-only, `waiting` only.
  - `POST /games/{game_id}/slots/{slot_index}/invite` — (re)send
    Resend invite for a reserved Human slot. Idempotent.
  - `POST /games/{game_id}/slots/{slot_index}/invite/clear` —
    drop the reservation, invalidate any outstanding token.
  - `POST /games/{game_id}/join` — extended with optional
    `invite_token` for reserved-slot redemption.
- **Schema**:
  - `Game.lobby_slots` — JSON column. Each entry: `{slot_index: int,
    type: "human" | "agent", name: str | null, reserved_email: str |
    null, player_api_key_id: int | null}`. Null on legacy rows.
  - New `LobbyInvite` table — `(id, game_id, slot_index, email,
    token_hash, expires_at, redeemed_at, created_at)`. Token hash is
    SHA-256 of a 32-byte random hex string; only the hash is stored.
  - `Game.players: list[str]` — retained; kept in sync with the
    filled slot names so existing fog-of-war / engine code works
    unchanged.
  - `PlayerApiKey` — reused as-is. Slot ↔ key ownership is now
    explicit via `lobby_slots[i].player_api_key_id`.
- **MCP**:
  - Live streamable-http endpoint: `https://mcp.parley.quest/`
    (root path, no `/mcp` suffix). Reachable as of the Phase 0
    deployment fix already shipped.
  - New tool `whoami(api_key) → {game_id, player_id, slot_index}`,
    read-only, available on stdio + http. Surfaced in both skills.
- **Auth**:
  - Per-game API key (creator's own) authorises slot-config and
    regenerate endpoints. Same model as today's `leave_game` /
    `start_game`.
  - Invite redemption requires Auth.js JWT identity whose email
    matches the slot's `reserved_email`, plus a valid (unredeemed,
    unexpired) token. Single-use.
- **Email**:
  - Resend, via the existing verified `parley.quest` sender domain.
    Distinct template from Auth.js magic links — invite emails
    embed the lobby URL with `?invite=<token>` query param.
- **Skills**:
  - `.claude/skills/play-parley-local/skill.md` — renamed from
    `play-4x`. Local stdio MCP, `create_game` from agent, self-play.
  - `.claude/skills/play-parley/skill.md` — new. Live MCP at
    `https://mcp.parley.quest/`. Join + play only; no `create_game`,
    no `join_game` (slots pre-exist).
- **Visibility window**:
  - Plaintext API keys for agent slots are returned by `GET
    /games/{id}` only while `status == "waiting"`, and only to the
    creator. The instant the game flips to `active`, the field is
    gone.

---

## Phase 1: Live agent path works end-to-end (tracer)

**User stories**: 8, 9, 13, 14, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40

### What to build

The thinnest possible slice that proves an agent can play on the live
server. No schema work, no slot redesign — just expose the API key
the creator already has, ship the MCP tool an agent needs to identify
itself, and replace the local-only skill with a live + local pair.

After this phase, a human creates a game using the existing
create-lobby flow, sees their per-game API key in the lobby UI with a
copy button, pastes it (with the game URL) into Claude Code running
the new `play-parley` skill, and the agent connects to
`https://mcp.parley.quest/`, calls `whoami` to confirm identity, and
plays the game end-to-end.

### Acceptance criteria

- [ ] `whoami` MCP tool exists, registered in the lifecycle module,
      returns `{game_id, player_id, slot_index}` for a valid key and
      an `error` payload for an invalid one.
- [ ] `GET /games/{game_id}` response includes the creator's own
      plaintext API key while `status == "waiting"`, only when the
      request is authenticated as the creator.
- [ ] Lobby page renders the creator's API key with a copy-to-
      clipboard button and a one-line warning that the key disappears
      when the game starts.
- [ ] Key field is absent from the response (and the UI) once the
      game flips to `active`.
- [ ] `.claude/skills/play-4x/skill.md` is renamed to
      `.claude/skills/play-parley-local/skill.md`; `name` and
      `description` frontmatter updated. Body otherwise unchanged.
- [ ] New `.claude/skills/play-parley/skill.md` exists. Body covers:
      one-time MCP client config snippet pointing at
      `https://mcp.parley.quest/`, the "paste game URL + key"
      handshake, `whoami` + `get_game_info` confirmation, the
      standard play loop, and an etiquette section for human-mixed
      games.
- [ ] Manual end-to-end demo passes: human creates game on
      `parley.quest`, copies key from lobby, runs `/play-parley` in
      Claude Code, agent reports identity via `whoami` and plays at
      least one full turn.
- [ ] Existing self-play and create_game-from-agent flows in
      `play-parley-local` still work (no regression on the local
      sandbox loop).

---

## Phase 2: Slot-model plumbing

**User stories**: foundational for 1–7, 10, 24–26 (no user-visible behaviour change yet)

### What to build

Introduce the `lobby_slots` data structure without changing any
behaviour. The column is added, the existing create / join code
populates it as it writes `players`, and the GET response exposes
it. The lobby UI starts reading from it (rendering a "Human" type
badge per slot) but every slot stays Human and the create dialog is
unchanged.

This phase is intentionally thin so the column shape and
serialisation can be validated against real Postgres before the
larger Phase 3 / 4 work piles on top.

### Acceptance criteria

- [ ] Alembic migration adds `Game.lobby_slots` (nullable JSON
      column).
- [ ] On `POST /games`, the controller writes a `lobby_slots` array
      whose entries match `players` (all `type: "human"`,
      `name = player_id`, `reserved_email = null`,
      `player_api_key_id` populated for the creator).
- [ ] On `POST /games/{id}/join`, the joining player's slot is
      filled in `lobby_slots` (name + key reference) alongside the
      existing `players` append.
- [ ] On `POST /games/{id}/leave`, the slot's name and
      `player_api_key_id` are cleared in `lobby_slots`; the entry
      itself remains (slot index is preserved).
- [ ] `GET /games/{game_id}` response includes `slots: [...]`.
- [ ] Lobby page reads from `slots`, rendering each slot's index,
      colour, type badge ("Human"), and current occupant. Visual
      output is equivalent to today's player list.
- [ ] Backend tests cover create / join / leave maintaining
      `lobby_slots` ↔ `players` consistency.
- [ ] Legacy rows (no `lobby_slots`) render as all-Human slots; this
      branch is exercised by a unit test even though production has
      no legacy data.

---

## Phase 3: Agent slots at create time + per-slot keys

**User stories**: 1, 2, 3, 6, 7, 10, 11, 12, 28, 29, 30

### What to build

The first user-visible redesign. The create-lobby dialog asks for
slot count, then per-slot type (Human / Agent) and name (required
for Agent). Creator can opt out of taking any slot. On submit, the
backend mints one `PlayerApiKey` per Agent slot, stores its id on
the slot record, and returns the slot array (with plaintext keys for
the creator) in the response.

The lobby page renders each Agent slot's key with a copy button and
a regenerate button (with confirmation modal). All-agent games can
be created and started without the creator being seated. Once Start
is pressed and status flips to `active`, the keys vanish from the
response and the UI.

### Acceptance criteria

- [ ] `POST /games` accepts `creator_seated: bool` (default `true`)
      and optional `slots: [{type, name?, reserved_email?}]`. When
      `slots` is omitted, legacy behaviour (creator in slot 0, all
      Human, count = `player_slots`) applies.
- [ ] Backend rejects creates where Agent slots have no name, or
      where any two Agent names collide.
- [ ] Each Agent slot gets a fresh `PlayerApiKey` minted at create,
      attributed to the creator's `UserIdentity`. Slot's
      `player_api_key_id` is populated.
- [ ] `POST /games/{game_id}/slots/{slot_index}/regenerate-key`
      mints a new key, invalidates the previous, returns plaintext.
      Creator-only, `waiting`-only, Agent-slot-only.
- [ ] Create-lobby dialog redesigned: slot count → "I'll take a
      slot" toggle → per-slot rows with type selector and name
      field. Validates Agent name uniqueness client-side.
- [ ] Lobby page renders per-slot key + copy button + regenerate
      button (with confirmation) for Agent slots, only to the
      creator, only while `waiting`.
- [ ] All-agent flow works: creator unticks "I'll take a slot",
      configures N Agent slots, starts the game, never enters a
      `players` slot themselves.
- [ ] Start button enables only when every slot is filled (Agent
      slots have keys, Human slots are joined or open with someone
      seated).
- [ ] After `Start`, `GET /games/{id}` no longer returns plaintext
      keys; the lobby UI key panel is empty / hidden.
- [ ] One-line warning text in the lobby reminds the creator to
      copy keys before starting.
- [ ] Backend tests cover: create with mixed slots, create
      all-agent, regenerate flow, key visibility window, name
      uniqueness rejection, Start guard.

---

## Phase 4: Slot reconfiguration in the lobby

**User stories**: 4, 24, 25, 26, 27

### What to build

The creator can edit slot types and names in the lobby (while
`waiting`). Agent → Human invalidates the agent's key and clears the
slot. Human → Agent is rejected if a human is currently seated;
once empty, the flip mints a new key. Slot count is fixed at
creation — no add/remove of slots themselves.

### Acceptance criteria

- [ ] `PUT /games/{game_id}/slots` accepts a full slot array,
      validates against the safety rules, and applies the diff
      atomically (mint / invalidate keys as required).
- [ ] Endpoint returns 400 on Human → Agent flip while a human is
      seated, with a message explaining the player must leave first.
- [ ] Endpoint returns 400 on slot count change.
- [ ] Endpoint returns 400 on Agent name collision.
- [ ] Lobby page exposes per-slot edit affordance: type toggle,
      name field, save / cancel.
- [ ] Editing an Agent slot's name re-binds the existing key (or
      mints a new one if none exists yet) — name change alone does
      not invalidate the key, but flipping type does.
- [ ] Backend tests cover each transition: human-occupied →
      blocked, human-empty → agent (key minted), agent → human
      (key revoked), name change in place.
- [ ] Lobby page tests cover the UI guard (disable type toggle on
      occupied human slots; show explanation).

---

## Phase 5: Human email invitations

**User stories**: 15, 16, 17, 18, 19, 20, 21, 22, 23

### What to build

Human slots can be reserved for a specific email. Reservation
generates a `LobbyInvite` row with a single-use token; the system
sends an email via Resend containing the lobby URL with
`?invite=<token>`. The invitee clicks, signs in via Auth.js if
needed (token preserved across the round-trip), and is redeemed
straight into the reserved slot.

### Acceptance criteria

- [ ] Alembic migration adds `LobbyInvite` table per the schema in
      the architectural decisions.
- [ ] `POST /games/{game_id}/slots/{slot_index}/invite` accepts
      `email`, mints (or reuses) a token, persists the row, sends
      the Resend email, returns 200. Idempotent — repeat calls with
      the same email refresh the existing token's expiry rather
      than minting a new one.
- [ ] `POST /games/{game_id}/slots/{slot_index}/invite/clear`
      removes the reservation and invalidates outstanding tokens.
- [ ] `POST /games/{game_id}/join` accepts an optional
      `invite_token`. When present: token must match the slot's
      live record, must not be expired or redeemed, JWT email must
      match `reserved_email`. On success, marks `redeemed_at` and
      seats the user in the reserved slot. On failure, returns 400
      with a specific reason.
- [ ] Open Human slots (no `reserved_email`) keep the existing
      "any signed-in user can join the next free slot" behaviour
      when `invite_token` is absent.
- [ ] Reserved Human slots reject open joins (must use the token).
- [ ] Lobby create dialog and edit affordance let the creator
      enter an email per Human slot (optional).
- [ ] Lobby page shows reservation status per slot ("Reserved for
      alice@example.com — invite sent / resend / clear").
- [ ] Lobby page reads `?invite=<token>` from the URL on mount.
      If signed in, auto-calls join with the token. If not, surfaces
      a "Sign in to claim your slot" CTA that preserves the token
      across the Auth.js round-trip and resumes redemption on
      return.
- [ ] Resend integration uses the existing verified
      `parley.quest` sender domain; email template includes game
      name, inviter's name, and the redemption link.
- [ ] Resend rate guard: cap `invite` calls at e.g. 5 per slot per
      hour with a 429 response.
- [ ] Integration tests against real Postgres cover: mint, redeem,
      single-use enforcement, expiry, identity mismatch, clear,
      re-mint after clear.

---

## Phase 6: Cleanup and polish

**User stories**: 38, 41

### What to build

Remove the deprecated "Invite an MCP agent" snippet panel — the
per-slot key flow has fully replaced it. Add a small "configure
your MCP client" hint near the slot panel with a copy-paste JSON
snippet pointing at `https://mcp.parley.quest/`. Round out the
`play-parley` skill's etiquette section based on what surfaced
during Phase 5 testing.

### Acceptance criteria

- [ ] "Invite an MCP agent" collapsible section and its `join_game`
      snippet are removed from the game detail page.
- [ ] New "Configure your MCP client" panel renders a copy-pasteable
      snippet (`{"fourex-mcp": {"url": "https://mcp.parley.quest/",
      "transport": "streamable-http"}}` or equivalent) with a copy
      button.
- [ ] `play-parley` skill body has a short, opinionated etiquette
      section (≤ 10 lines) covering: don't spam treaty proposals,
      keep messages terse and topical, respect declared cease-fires,
      don't impersonate other players.
- [ ] Skill description frontmatter for both skills positions
      `play-parley` as the default ("for live play") and
      `play-parley-local` as the opt-in ("local sandbox /
      development").
- [ ] Manual smoke: a fresh user can discover `play-parley`,
      configure their MCP client from the snippet, and join a
      reserved slot — all without consulting external docs.
