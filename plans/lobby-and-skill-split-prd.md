# Lobby redesign + agent key surfacing + skill split

## Problem Statement

I want to invite AI agents to play games on the live parley.quest server, but
today there's no way to do this without running my own copy of the backend
locally:

1. **The web UI never shows API keys.** The REST endpoints already mint a
   plaintext per-game API key on lobby create / join, but the frontend
   silently writes it to `localStorage` and the human never sees it. With no
   way to copy the key out, I can't paste it into an agent. Today the only
   working agent path is "run `fourex-mcp` locally and let it call
   `join_game` itself" — which doesn't help anyone using the live server.

2. **All-agent games are impossible.** The lobby implicitly seats the
   creator in slot 0, so I can't set up a game where I'm the owner /
   spectator and every actual seat is held by an agent. The only way to
   approximate it today is to call `create_game` from a local MCP and have
   the local agent loop play out, which bypasses the live UI entirely.

3. **The Claude skill assumes local stdio MCP.** `play-4x` only knows about
   `mise run serve` and the in-process `fourex-mcp` tools. There's no
   guidance for using the deployed `mcp.parley.quest` endpoint, and there's
   nowhere it tells the user "paste the API key the lobby gave you". The
   default play experience for someone discovering Claude + Parley should
   be against the live server, not a local sandbox.

4. **Inviting other humans is also fiddly.** Today the only way to invite
   another human is to share a URL and ask them to sign in and join — there
   is no per-slot reservation, so anyone with the URL can take any open
   slot. For a deliberately-set-up table this is awkward.

## Solution

The lobby becomes a real configuration surface. The creator picks slot count
once, then for each slot picks a type (Human or Agent) and either reserves
it (Agent name, or invited human's email) or leaves it open. The creator
can opt out of any slot themselves — they're allowed to be a pure owner /
spectator. Slot types can be edited in the lobby up until the game starts.

For agent slots, the lobby shows the per-slot API key with a copy button
and a regenerate button. The key disappears the instant the game flips
from "waiting" to "active". For human slots with a reservation, the lobby
sends a Resend-delivered magic invite link with a single-use token; the
invitee signs in (or is already signed in) and the token redeems them
straight into that slot. The creator can resend or change the reservation
while the slot is unoccupied.

For the agent itself, there's a new `whoami` MCP tool so an agent given
just a key + game URL can confirm which player_id it owns and which game
it's in. The existing `play-4x` skill is renamed to `play-parley-local`
and stays as the local-sandbox / self-play experience. A new
`play-parley` skill ships as the default — it points at the live MCP
endpoint, walks the user through the one-time client config, and asks
for the game URL + key from the lobby UI.

The deployment-side fix (FastMCP `transport_security` allow-list) has
already shipped as a Phase 0 prerequisite — `mcp.parley.quest/` is now
reachable as a streamable-http MCP endpoint.

## User Stories

### Lobby creation and slot configuration

1. As a human creator, I want to choose how many slots my game has at
   creation time, so the table size is set before anyone joins.
2. As a human creator, I want to choose whether I take one of the slots
   myself, so I can run all-agent games as a pure owner / spectator.
3. As a human creator, I want to mark each slot as Human or Agent, so I
   can set up mixed tables (e.g. me + two bots, or four bots, or two
   humans + two bots).
4. As a human creator, I want to redefine slot types in the lobby after
   creation, so I can change my mind without tearing the lobby down.
5. As a human creator, I want the slot count to be fixed once the lobby
   exists, so I don't have to deal with edge cases around resizing
   (e.g. losing reserved slots).
6. As a human creator, I want to give each agent slot a unique display
   name at slot configuration time, so the agent has an identity bound
   to its API key.
7. As a human creator, I want the lobby to enforce that agent names are
   unique within the game, so I can't accidentally create two slots
   that collide on player_id.

### API key visibility for agent slots

8. As a human creator, I want to see the plaintext API key for each
   agent slot displayed in the lobby, so I can copy it and hand it to
   the agent.
9. As a human creator, I want a one-click "copy key" button per agent
   slot, so I don't have to manually select text.
10. As a human creator, I want each agent slot to have its own unique
    key, so revoking one agent doesn't affect any others.
11. As a human creator, I want to regenerate an agent slot's key with
    one click (with a confirmation step), so I can recover if a key is
    leaked or lost — invalidating the previous key in place.
12. As a human creator, I want regeneration to be available *only* on
    agent slots and *only* while the game is in waiting status, so the
    affordance matches the only situation where it's useful.
13. As a human creator, I want the keys to disappear from the lobby
    view the instant the game starts, so the lobby UI doesn't double
    as a long-lived secret store.
14. As a human player, I do *not* want my own slot's bearer key shown
    in the UI by default, since I drive my slot via the browser session
    and the key noise isn't useful.

### Human invitations

15. As a human creator, I want to reserve a Human slot for a specific
    person by typing their email address, so only they can claim that
    slot.
16. As a human creator, I want the system to email the invited person
    a link to the game via Resend, so they get notified without me
    having to ferry the URL by hand.
17. As a human creator, I want the invite link to carry a single-use
    token, so the same recipient can be invited to multiple games
    without one invite redeeming another.
18. As a human creator, I want to resend the invite email, so I can
    nudge an invitee who lost the original.
19. As a human creator, I want to change the reserved email for a slot
    while it's unoccupied, so I can correct typos or switch invitees.
20. As a human creator, I want to clear the reservation back to "open"
    while the slot is unoccupied, so I can fall back to a public-join
    flow if the invitee can't make it.
21. As an invited human, I want to click the link in the email and
    land on the game lobby already authenticated to claim my reserved
    slot (or be sent through the standard Auth.js sign-in first), so
    the path from invitation to seated takes a single click after
    sign-in.
22. As an invited human, I want the invite token to be invalidated
    after I redeem it, so the same link can't be used twice.
23. As a human creator, I want to leave any Human slot unreserved
    (open), so I preserve the existing "share the URL, anyone signed
    in can join" workflow when I want it.

### Slot mutability and safety

24. As a human creator, I want to flip a slot from Agent → Human (and
    vice versa) while it's unoccupied, so I can reconfigure the table
    without recreating it.
25. As a human creator, I want to be blocked from flipping a Human slot
    to Agent while a human player has already joined it, so I don't
    accidentally kick someone mid-setup.
26. As a human creator, I want flipping an Agent slot to Human to
    immediately invalidate the previous agent key, so the abandoned
    agent can no longer act under that slot.
27. As a human player, I want to leave a slot I joined and free it up
    again, so I'm not locked in.

### Starting and finishing the lobby

28. As a human creator, I want a Start button that becomes enabled only
    when every slot is filled (every Agent slot has a key, every
    Human slot has a player or is open and joined), so I can't start a
    half-empty game.
29. As a human creator running an all-agent game, I want to start the
    game even though I'm not in a slot myself, so owner-only games
    work end-to-end.
30. As a human creator, I want the lobby UI to clearly indicate "the
    keys you've copied need to be in your agents *now* — once I press
    Start they're not visible here anymore", so I'm never surprised by
    losing access to them.

### Agent identity and live-server play

31. As an agent given just a game URL and an API key, I want to call a
    `whoami` MCP tool and learn which game I'm in and which player_id I
    own, so I don't have to be told my identity out-of-band.
32. As an agent connecting to the live server, I want a clearly
    documented MCP endpoint URL (`https://mcp.parley.quest/`) so I can
    register it in my MCP client without trial and error.
33. As an agent, I want my API key to be the only thing tying me to
    a game — no email, no Auth.js — so I can run headlessly without an
    account.

### Skill split

34. As a Claude user discovering Parley, I want the default skill
    (`play-parley`) to play against the live server out of the box, so
    I don't need to clone the repo to try the game.
35. As a developer iterating on the engine, I want a separate skill
    (`play-parley-local`) that talks to a local stdio MCP, runs
    self-play, and supports `create_game` from the agent side, so my
    development loop is unaffected.
36. As a Claude user invoking `play-parley` for the first time, I want
    the skill to walk me through the one-time MCP client configuration
    (the JSON snippet to add to `.mcp.json`), so I'm not guessing.
37. As a Claude user with `play-parley` configured, I want to paste the
    game URL and API key from the lobby UI and have the agent call
    `whoami` + `get_game_info` to confirm the connection, so I see
    confirmation before any moves are made.
38. As a Claude user playing in a human-mixed game via `play-parley`, I
    want the skill to include short etiquette guidance for diplomacy
    (don't spam, be polite, respect cease-fires), so the agent doesn't
    behave badly toward human opponents.
39. As a Claude user, I want `play-parley` to never call `create_game`
    or `join_game` (slots pre-exist; the human created them in the UI
    and handed me a key), so the skill matches the live workflow.
40. As an existing user of `play-4x`, I want the renamed
    `play-parley-local` skill to behave identically to today, so my
    existing workflows (self-play, create_game from MCP, full local
    flow) are not regressed.

### Removed / deferred surface

41. As a human creator, I no longer need the existing "Invite an MCP
    agent" snippet panel in the lobby (the one that emits a
    `join_game(...)` snippet), because the new per-slot key flow
    replaces it.

## Implementation Decisions

### Schema

- `Game` gains a `lobby_slots` JSON column. Each entry is a record with
  fields: slot index (int), slot type (`human` | `agent`), display name
  (string, optional for unfilled human slots), reserved email (string,
  human slots only), and the foreign-key id of the active
  `PlayerApiKey` for that slot (so the slot ↔ key relationship is
  explicit and survives regeneration).
- `Game.players: list[str]` is retained for backward compatibility with
  the existing fog-of-war and game-state code that already references
  it; it stays in sync with the filled slot names.
- A new `LobbyInvite` table holds single-use invitation tokens, one row
  per (game, slot, email, token), with `redeemed_at` and `expires_at`.
  Tokens are 32-byte random hex; only the hash is stored.
- No data migration is needed — production is empty. The new column
  defaults to null on legacy rows; null is treated as "all current
  players are human, no agent slots, no reservations" for safety, but
  that branch is not expected to fire in production.

### REST API

- `POST /games` (create lobby) gains a body field `creator_seated:
  bool` (default `true` to preserve current behaviour) and an optional
  `slots: list[SlotConfig]` array. If `slots` is omitted, the legacy
  behaviour (creator in slot 0, all human, count = `player_slots`)
  applies.
- `PUT /games/{game_id}/slots` lets the creator redefine slot
  configuration while the game is in `waiting` status. Validates that
  no Human → Agent flip is attempted on an occupied slot. Mints /
  invalidates `PlayerApiKey` rows as needed. Authenticated by the
  creator's per-game API key.
- `POST /games/{game_id}/slots/{slot_index}/regenerate-key` mints a new
  key for an Agent slot and invalidates the previous one. Restricted
  to the creator and to `waiting` status.
- `POST /games/{game_id}/slots/{slot_index}/invite` (re)sends the
  invitation email for a reserved Human slot via Resend. Idempotent —
  if a live token already exists it's reused; otherwise a new one is
  minted.
- `POST /games/{game_id}/slots/{slot_index}/invite/clear` removes the
  reservation, invalidating any outstanding tokens.
- `POST /games/{game_id}/join` accepts an optional `invite_token`.
  When present, the endpoint redeems the token (must match the slot's
  live token, must not be expired or already redeemed, recipient
  must be the same email as the reservation) and seats the user in
  the reserved slot. When absent, the legacy behaviour (open join
  into the next free Human slot) applies — this is what an unreserved
  open slot uses.
- `LobbyKeyResponse` shape is unchanged for create/join. The new
  per-slot keys for agent slots are exposed on the `GET /games/{id}`
  detail response, only while the game is in `waiting` status, only
  to the creator.

### MCP

- New `whoami` tool, accepts `api_key`, returns `{game_id, player_id,
  slot_index}`. Read-only, no side effects. Available on both stdio
  and streamable-http transports — the live skill uses it; the local
  skill may also surface it for symmetry.
- No other MCP tool changes. `create_game` and `join_game` keep
  working as today (used by `play-parley-local` and any existing
  callers).

### Frontend

- The create-lobby dialog gains a slot-configuration step: pick count,
  pick whether the creator takes a slot, then per-slot type (with name
  field for agent slots, optional email reservation for human slots).
- The lobby page shows each slot as a card with: type badge, name (or
  "Empty / Reserved / Open"), per-slot actions (regenerate / resend
  invite / change reservation / clear reservation), and — for agent
  slots only, while waiting — the plaintext key and copy button.
- Keys are visible to the creator only. The visibility guard is
  enforced server-side (the detail endpoint redacts the keys for
  non-creators) and the UI just renders what it gets.
- The existing "Invite an MCP agent" collapsible snippet section on
  the game detail page is removed.
- A small "configure your MCP client" hint replaces it with a copy
  button for the streamable-http endpoint URL and a one-line example
  of the JSON snippet to add to `.mcp.json`.
- Invite emails (Resend) include the lobby URL with a `?invite=<token>`
  query parameter. The lobby page reads the token from the URL on
  mount and, if the visitor is signed in, automatically calls join
  with the token; otherwise it surfaces a "Sign in to claim your slot"
  CTA that preserves the token across the Auth.js round-trip.

### Slot-type change semantics

- Agent → Human: invalidate the agent key (delete the `PlayerApiKey`
  row); clear the slot's name; slot is now unreserved-open.
- Human → Agent: blocked while a human is seated. Once empty, the
  flip mints a new key bound to the new name.
- Human (open) → Human (reserved): mint an invite token, send the
  email; existing seated player (if any) is unaffected.
- Human (reserved) → Human (open): clear the token; recipient who has
  not yet redeemed loses access.

### Skill files

- `.claude/skills/play-4x/skill.md` is renamed to
  `.claude/skills/play-parley-local/skill.md`. Frontmatter `name`
  changes to `play-parley-local`; description rewritten to clarify
  it's the local sandbox / self-play / `create_game`-from-agent
  experience. Body is otherwise preserved.
- A new `.claude/skills/play-parley/skill.md` ships, with frontmatter
  `name: play-parley`, description framed as "play on the live
  parley.quest server", and body covering: one-time MCP client
  config (the JSON snippet pointing at `https://mcp.parley.quest/`),
  the "paste game URL + API key" handshake, `whoami` →
  `get_game_info` confirmation, the standard play loop (mostly reused
  from the local skill), and a short etiquette section for diplomacy
  in human-mixed games.
- The local skill description is reworded so the live skill reads as
  the default ("for live play see `play-parley`; this is the local
  sandbox").

### Deployment

- Phase 0 (already done as part of this PRD's interview): FastMCP
  `transport_security` is now wired to `MCP_ALLOWED_HOSTS` /
  `CORS_ORIGINS`, and the deployment doc lists the new env var. The
  live MCP endpoint at `https://mcp.parley.quest/` is reachable via
  JSON-RPC.
- No new deployment work expected for this PRD beyond the standard
  Railway redeploy and the Resend domain (already verified for
  Auth.js magic links — same sender domain reused for invites).

## Out of Scope

- Any change to the agent runtime, planner, or profile system in
  `backend/src/agents/`. Agents continue to be driven by whatever
  client connects — Claude Code via the new skill, the in-process
  `selfplay` runner, or anything else.
- Any change to MCP tools other than the addition of `whoami`.
- Any change to the Auth.js sign-in flow itself; magic-link auth
  stays as-is. The invite emails reuse Resend but are a separate
  template, not Auth.js-issued.
- Any backfill migration for existing games. Production is empty;
  the schema change applies forward only.
- Any rework of spectator behaviour. Anyone signed in can still view
  any game, as today.
- Any global "browse open lobbies" / matchmaking surface. Lobby
  discovery stays at the existing games-list page.
- Renaming or restructuring the existing MCP tool inventory.
- Per-slot human pseudonyms decoupled from Auth.js identity (e.g.
  letting one human take two human slots in the same game). One
  human, one slot per game, per current invariants.
- Any change to the WebSocket / lobby-events transport beyond
  whatever new events are needed to broadcast slot reconfiguration.

## Further Notes

- **Default skill positioning.** When both `play-parley` and
  `play-parley-local` are installed, the live one is the entry point.
  This is conveyed via the description text in the skill frontmatter
  and via the order/wording in any "getting started" docs — Claude's
  skill picker doesn't have a true "default" mechanism, so the
  positioning is editorial rather than enforced.
- **Key UX warning.** The lobby UI should make it obvious that copying
  the key is a one-shot affordance — the wording on the regenerate
  button and the visible-only-while-waiting behaviour both hint at
  this, but a small explanatory line ("Copy the key now — you won't
  be able to see it after the game starts. Use Regenerate if you lose
  it.") is worth including.
- **Invite token TTL.** Tokens expire on the same timeline as the
  lobby itself (default 24h, matching the existing `PlayerApiKey`
  TTL). Resending refreshes the expiry on the existing token rather
  than minting a new one, so a single recipient sees a stable link
  even across resends.
- **Resend abuse guard.** Capping resends at e.g. 5 per slot per hour
  is a reasonable cheap guard against accidentally spamming an
  invitee; not strictly required for correctness, worth a one-liner
  in the implementation.
- **`whoami` for the local skill.** The local skill currently relies
  on the agent remembering the `api_keys` map returned by
  `create_game`. `whoami` makes the local flow more robust too (no
  state to remember between turns) — worth surfacing it in
  `play-parley-local`'s tool inventory even though it's not strictly
  needed there.
- **Agent slot ordering.** Slot index in the schema is the canonical
  ordering and matches the existing `getPlayerColor(i)` mapping in
  the frontend — colour assignment is already index-driven, so all
  slots stay visually consistent regardless of type.
- **Test coverage focus.** The risky surface is (a) slot
  reconfiguration's interaction with the `PlayerApiKey` lifecycle
  and (b) invite-token redemption (single-use, expiry, identity
  match). Both deserve direct integration tests against a real
  Postgres rather than mocks.
