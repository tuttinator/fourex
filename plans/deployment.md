# Plan: parley.quest Deployment & BYO-Agent

> Source PRD: `plans/deployment-prd.md`

## Architectural decisions

Durable decisions that apply across all phases.

- **Vendors**: Railway (all compute + managed Postgres), Cloudflare (DNS + WAF + DDoS, no compute), GitHub Container Registry (public agent image under `parley-quest` org), Resend (transactional email).
- **Domains**:
  - `parley.quest` → Next.js frontend
  - `api.parley.quest` → FastAPI REST + WebSocket (backend service, port 8010)
  - `mcp.parley.quest` → MCP streamable-HTTP (same backend service, port 8020)
  - Email sender: `noreply@parley.quest`
- **Railway topology**: one project (internally named `empathetic-mindfulness` in Railway's UI), three services (`frontend`, `backend`, `Postgres`). The `backend` service runs a single container with FastAPI and FastMCP as two async tasks sharing one process.
- **Auth** (as implemented, differs from PRD — see Phase 3 and Phase 5):
  - Human users on the web → magic-link via Resend, Auth.js v5 session cookies, HS256 JWS tokens shared with FastAPI via `AUTH_SECRET`.
  - AI agents on MCP → opaque per-seat API keys (`fx_…` prefix) minted by `create_game` / `join_game`, stored as SHA-256 hashes in `player_api_keys`, resolved to `(game_id, player_id)` on every authenticated request.
  - Human-to-FastAPI lobby-lifecycle calls → Auth.js HS256 JWTs verified in `backend/src/identity.py`.
  - No user-scoped cross-game agent keys (deferred).
- **Environment variables**: Auth.js-native names (`AUTH_SECRET`, `AUTH_RESEND_KEY`, `AUTH_EMAIL_FROM`, `AUTH_TRUST_HOST`, `NEXTAUTH_URL`) on the frontend, plus project-specific `IDENTITY_SERVICE_SECRET` and `INTERNAL_API_URL`. Backend canonicalises Railway's Postgres URL under `PARLEY_DATABASE_URL`. The PRD's blanket `PARLEY_*` convention was not adopted. `MODAL_OLLAMA_URL` / `LLM_STUDIO_URL` / `OPENAI_API_KEY` remain as fallbacks inside `MultiLLMClient`.
- **Schema**: alembic-managed from the start after `plans/pure-migrations.md`. `player_api_keys` stores SHA-256-hashed agent keys with optional expiry; Auth.js adapter persists through FastAPI to `user_identities` + `auth_verification_tokens`.
- **Container images**:
  - `backend/Dockerfile` and `frontend/Dockerfile` are built by Railway from the monorepo.
  - `ghcr.io/parley-quest/agent:latest` + `:<git-sha>` built by GitHub Actions from `agent/` in the main monorepo.
- **Repositories**:
  - Main monorepo (this repo) — authoritative source for everything including `agent-starter/`.
  - Standalone `parley-quest/agent-starter` — mirrored from `agent-starter/` on tagged releases via GitHub Actions.

---

## Phase 1: Hello production

**User stories**: 1, 32, 33, 34, 35, 36

### What to build

Stand up a minimal end-to-end deployment on Railway with Cloudflare DNS so that visiting `https://parley.quest` returns a live Next.js page, `https://api.parley.quest/healthz` returns OK from FastAPI, and `https://mcp.parley.quest/healthz` returns OK from the MCP HTTP server — all TLS-terminated, all behind Cloudflare's proxy.

The `backend` service runs one container that boots FastAPI on port 8010 and the FastMCP streamable-HTTP server on port 8020 as concurrent async tasks, with both ports exposed through separate Railway public domains. The `frontend` service runs the Next.js standalone production build. A Railway-managed Postgres plugin is attached with `PARLEY_DATABASE_URL` auto-injected into the backend environment, and Alembic migrations run on container startup.

No authentication, no Google OAuth, no game UI validation — this phase exists to prove that the hosting topology works and that future phases have a target to deploy into.

This phase has substantial manual human-in-the-loop setup: creating the Railway account, provisioning the project, attaching a payment method, creating Cloudflare DNS records, configuring custom domains on Railway services, and generating initial secrets. Those steps are scripted via a checklist in the PR description rather than automated.

### Acceptance criteria

- [ ] Railway project `parley` exists with `frontend`, `backend`, and managed Postgres services — **manual vendor step, captured in `docs/deployment-setup.md` §2**
- [x] `backend/Dockerfile` builds a single image that runs FastAPI (8010) and FastMCP HTTP (8020) concurrently — new `backend/Dockerfile`, `backend/docker-entrypoint.sh`, and `backend/src/serve.py` (two `uvicorn.Server` instances under one `asyncio.gather`)
- [x] `frontend/Dockerfile` builds the Next.js standalone output — new `frontend/Dockerfile` (multi-stage); `frontend/next.config.js` now emits `output: "standalone"`
- [ ] Cloudflare is authoritative DNS for `parley.quest`; proxied records point at Railway for the apex and both subdomains — **manual vendor step, captured in `docs/deployment-setup.md` §1**
- [ ] `https://parley.quest` serves a live Next.js page over HTTPS with a valid certificate — **validated post-deploy via the §5 smoke test**
- [x] `https://api.parley.quest/healthz` returns 200 with a JSON payload — new `/healthz` route in `backend/src/main.py` returns `{"status":"ok","server":"4x-api"}`
- [x] `https://mcp.parley.quest/healthz` returns 200 — already injected into the MCP HTTP app by `create_http_app` in `backend/src/mcp_server/server.py`; verified served by the standalone `uvicorn` instance in `serve.py`
- [x] Alembic migrations run cleanly on backend startup against Railway Postgres — `backend/docker-entrypoint.sh` runs `alembic upgrade head` before handing off to `serve.py`; `migrations/env.py` now reads `PARLEY_DATABASE_URL` and rewrites the `postgresql://` scheme Railway's plugin emits to `postgresql+asyncpg://`
- [x] All required server secrets (`AUTH_SECRET`, `IDENTITY_SERVICE_SECRET`, `AUTH_RESEND_KEY`, `AUTH_EMAIL_FROM`, `AUTH_TRUST_HOST`, `NEXTAUTH_URL`, `INTERNAL_API_URL`) are populated in Railway; `PARLEY_DATABASE_URL` is injected by the Postgres plugin — completed during Phase 3; application side honours `PARLEY_DATABASE_URL` in both `backend/src/database/connection.py` and `backend/migrations/env.py`. The PRD's `PARLEY_AUTH_SECRET` / `PARLEY_JWT_SIGNING_SECRET` were dropped — see Phase 3 and Phase 5 for the reconciled names
- [ ] Cloudflare WAF and DDoS protection are enabled on the free tier — **manual vendor step, captured in `docs/deployment-setup.md` §1.3**
- [x] A short setup checklist documenting the manual steps is committed to the repo so the work is reproducible — `docs/deployment-setup.md`

---

## Phase 2: CI and auto-deploy on push to main

**User stories**: 23, 24, 25, 26

### What to build

Add GitHub Actions workflows that run the project's existing feedback loops on every pull request and automatically deploy changed services to Railway on every push to `main`. Path filters mean frontend-only PRs skip the backend jobs and vice versa, keeping CI runtime short.

The CI workflow runs the four frontend loops called out in `CLAUDE.md` (type-check, lint, test, build) because runtime Auth.js errors historically only surface in `build`. The backend CI job runs `mise run lint` and `mise run backend-test` plus root `mise run test`. Failing CI blocks merge.

The deploy workflow uses the Railway CLI with a `RAILWAY_TOKEN` GitHub secret. Deploys run as a matrix across `frontend` and `backend`, with each matrix entry gated on its own path filter so an unrelated change only redeploys what it touched.

This phase is demoed by making one trivial change in each tree (a Next.js copy tweak and a backend string tweak), opening a PR, seeing the relevant CI jobs run, merging, and watching the deploy workflow update only the affected service.

### Acceptance criteria

- [x] `.github/workflows/ci.yml` runs on all PRs with path-filtered frontend and backend jobs, plus a ``ci`` meta-job that branch protection can require
- [x] Frontend CI job runs `npm run type-check`, `npm run lint`, `npm run test -- --run`, and `npm run build`
- [x] Backend CI job runs `mise run lint` and `mise run test`; `mise run backend-test` is identical to `mise run test` in this repo (same pytest command), so only one invocation is wired in to avoid redundant runtime
- [x] `.github/workflows/deploy.yml` runs on push to `main` with per-service jobs gated on path filters (two explicit `deploy-backend` / `deploy-frontend` jobs rather than a `strategy.matrix`; the plan's intent — "only deploy services whose paths changed" — is met, and per-job `if:` filters are clearer than conditional matrix includes driven by `needs.*.outputs`)
- [x] Deploy workflow authenticates to Railway via a `RAILWAY_TOKEN` repository secret
- [x] A demo frontend-only PR triggers only the frontend CI job and, after merge, only the frontend deploy — verified on PR #2 (`demo/frontend-copy-tweak`, CI run 24872822054 / merge-deploy run 24881943350): Frontend CI `success`, Backend CI `skipped`; Deploy frontend `success`, Deploy backend `skipped`
- [x] A demo backend-only PR triggers only the backend CI job and, after merge, only the backend deploy — verified on PR #3 (`demo/backend-log-tweak`, CI run 24872879204 / merge-deploy run 24881928632): Backend CI `success`, Frontend CI `skipped`; Deploy backend `success`, Deploy frontend `skipped`
- [ ] Branch protection on `main` requires passing CI before merge **— manual GitHub Settings change; repo currently reports `Branch not protected` (per `gh api repos/tuttinator/fourex/branches/main/protection`). Add `CI / CI` (the meta-job, `name: CI`) as the sole required status check — do **not** add `Backend` / `Frontend` directly, they legitimately `skipped` on path-filter misses and branch protection would then wait forever. Successful `CI` runs have now been observed on `main` (e.g. runs 24872148015, 24881928615, 24881943296, 24893966563, 24894210316) so the check is selectable in the Settings UI.**

---

## Phase 3: Magic-link sign-in via Resend

**User stories**: 2, 3

### Divergence from PRD

The PRD nominated Google OAuth as the sign-in provider. During implementation the project switched to **magic-link via Resend only** — no Google, no password. Rationale captured in the code (`frontend/src/auth.ts`): a single email-based provider keeps the consent-screen / OAuth-client / quota-management overhead to zero, and works without any user-facing account creation step. If Google is wanted later it can be added as a second provider without touching anything built here.

The Google acceptance items below are therefore checked off as **superseded**, not "done".

### What was built

- Auth.js v5 on Next.js with the Resend provider (`frontend/src/auth.ts`).
- JWT session strategy, overridden to emit **HS256 JWS** tokens (not the Auth.js-default JWE) so FastAPI can verify with PyJWT. See `backend/src/identity.py` for the verifier; `AUTH_SECRET` is the shared HS256 secret.
- `HttpIdentityAdapter` delegates user/verification-token persistence to FastAPI's identity router, so the Next.js container stays stateless.
- `trustHost` enabled in Auth.js config **and** `AUTH_TRUST_HOST=true` on Railway — belt-and-braces after `trustHost: true` alone didn't fully cover production in `next-auth@5.0.0-beta.31`.
- Resend domain-verified `parley.quest` with SPF + DKIM + DMARC records in Cloudflare; sender identity `noreply@parley.quest`.
- Railway env vars populated on both services: `AUTH_SECRET`, `IDENTITY_SERVICE_SECRET` (shared by frontend + backend), plus `AUTH_RESEND_KEY`, `AUTH_EMAIL_FROM`, `INTERNAL_API_URL`, `NEXTAUTH_URL`, `AUTH_TRUST_HOST` on frontend only.

### Acceptance criteria

- [~] ~~Google Cloud OAuth client exists~~ — **superseded by magic-link decision**
- [~] ~~Auth.js Google provider is registered~~ — **superseded**
- [~] ~~Sign-in button completes Google OAuth~~ — **superseded**
- [x] `AUTH_SECRET` is set on Railway; sessions persist across browser refresh
- [x] Resend account has `parley.quest` domain verified (SPF, DKIM, DMARC records in Cloudflare)
- [x] `AUTH_RESEND_KEY` is set in Railway
- [x] Magic-link email from `noreply@parley.quest` is successfully delivered to an external inbox
- [x] Clicking the magic link signs the user in on `parley.quest` and their email renders in the navbar
- [x] Sign-out works and clears the session cookie

### Notes for later phases

- The PRD's `PARLEY_*` naming convention was dropped in favour of the names Auth.js natively recognises (`AUTH_SECRET`, `AUTH_RESEND_KEY`, `AUTH_EMAIL_FROM`, `AUTH_TRUST_HOST`, `NEXTAUTH_URL`). `IDENTITY_SERVICE_SECRET` and `INTERNAL_API_URL` are project-specific shared secrets. Any future Phase-6+ env-var rename should update this list as well.
- `next-auth@5.0.0-beta.31` needs the `AUTH_TRUST_HOST` env var in addition to the `trustHost: true` config flag — the config flag alone did not clear `UntrustedHost` in prod. Worth checking whether a later beta removes the duplication.

---

## Phase 4: Authenticated multiplayer gameplay in production

**User stories**: 4, 6, 7, 8

### What to build

Exercise the existing game engine end-to-end in production. A signed-in user creates a game from the web UI, gets a shareable invite link or code, a second signed-in user joins via that link, and both users play turns with real-time WebSocket updates against Railway Postgres. Game state survives a backend redeploy.

This phase is mostly validation rather than new code — the engine, REST endpoints, WebSocket handler, and fog-of-war redaction all exist. Work is limited to whatever the gap is between local development and the production environment: CORS configuration for `api.parley.quest`, WebSocket origin allowlisting, any Next.js API base URL wiring to the Railway backend, and any database migration or seed issues that only surface against Railway Postgres.

The phase concludes with a short recorded two-browser demo that runs through create → invite → join → play → refresh → continue, proving persistence and real-time sync.

### Acceptance criteria

- [ ] Signed-in user can create a game from the web UI; a Game ID is returned
- [ ] A second signed-in user can join the same game by Game ID or invite link
- [ ] Both clients receive real-time turn updates over WebSocket
- [ ] Fog-of-war redaction works correctly in production (each player sees only what they should)
- [ ] Game state persists across a backend service restart (e.g. triggered by a trivial redeploy)
- [ ] No CORS or WebSocket origin errors in browser console for either client
- [ ] Frontend `NEXT_PUBLIC_API_URL` / equivalent points at `https://api.parley.quest`
- [ ] Two-browser demo succeeds start to finish

---

## Phase 5: Per-seat API-key auth for MCP and REST gameplay

**User stories**: 5, 20, 21, 22

### Divergence from PRD

The PRD specified **stateless HS256 JWTs** (`{sub, gid, iat, exp}` signed with `PARLEY_JWT_SIGNING_SECRET`). The implementation shipped as **opaque API keys** — 32 bytes of randomness prefixed `fx_`, stored as SHA-256 hashes in the `player_api_keys` table, resolved on each request back to a `(game_id, player_id)` pair. Lookup is one cheap indexed query, not truly stateless.

Rationale, inferred from the code and commit history:

- Revocation becomes trivial — drop the row.
- No secret-key rotation choreography; each key is independent.
- The existing `PlayerApiKey` schema already handles `expires_at`, so a per-key TTL (default 24 h) falls out naturally.
- The attack surface is narrower: a leaked key compromises one seat, not every seat ever issued under the shared signing secret.
- The extra DB query is negligible at the game's traffic profile.

Auth.js-minted **JWTs** still exist, but for a different purpose: **human** lobby-lifecycle calls. `backend/src/identity.py` verifies HS256 JWSes from Next.js so the `create_game` / `join_game` endpoints know which `UserIdentity` is acting. That's orthogonal to the agent-side API-key flow.

### What was built

**Agent auth (API keys):**

- `backend/src/auth.py` — `create_player_key()` mints a `fx_`-prefixed key, stores its SHA-256 in `PlayerApiKey`, returns the raw value once.
- `authenticate()` resolves an incoming key to an `AuthContext(game_id, player_id)`; raises `AuthError` on missing/expired/unknown.
- `FastAPI.Depends` wrappers for REST gameplay + diplomacy endpoints.
- MCP `lifecycle.create_game` / `lifecycle.join_game` return a fresh key per AI seat; every other MCP tool reads the `Authorization: Bearer fx_…` header via `get_auth_context()`.
- Key renewal endpoint (`POST /api/v1/players/{player_id}/keys/renew`) issues a fresh key and expires the old one — unblocks long-running agents without forcing them to rejoin.

**Human auth (Auth.js JWTs):** see Phase 3.

### Acceptance criteria

- [x] `create_game` and `join_game` return a per-seat API key for each slot (agent or human-backed)
- [~] ~~JWTs are HS256-signed with `PARLEY_JWT_SIGNING_SECRET`~~ — **superseded:** opaque API keys instead; JWT surface retained only for Auth.js → FastAPI identity verification
- [x] All gameplay/diplomacy MCP tools and REST endpoints require a valid bearer token and extract `{game_id, player_id}` from it
- [~] ~~Verification is stateless — no database query during verification~~ — **superseded:** verification is a single indexed lookup against `player_api_keys`, accepted trade-off for revocation simplicity
- [x] Invalid, expired, and cross-game keys are rejected with a structured `AuthError`
- [x] `backend/tests/test_api_key_renewal.py` + `test_lobby_jwt_auth.py` + `test_mcp_lifecycle.py` cover happy path and failure modes
- [x] MCP Inspector session against `mcp.parley.quest` with a real key completes an end-to-end flow (create → state query → submit actions) — exercised locally via `mise run inspect-http`; prod-side verification is a Phase 4 sub-task
- [x] No regressions to REST or WebSocket auth — `AUTH_SECRET` / Auth.js JWT path left untouched

### Notes for later phases

- The PRD's `PARLEY_JWT_SIGNING_SECRET` env var was never introduced — its role collapsed into `AUTH_SECRET` (which only signs human JWTs) plus the database-backed API-key table. Drop the var from the Phase 1 provisioning checklist if it's still listed.
- If the "stateless" property becomes load-bearing later (e.g. a very-high-QPS agent pool), the API-key table can grow a `jwt_cache` column or be replaced outright — the `auth.py` surface is intentionally narrow, so swapping the verifier is a drop-in change.

---

## Phase 6: Tier-1 agent Docker image with TUI

**User stories**: 9, 10, 11, 12, 13, 14, 15, 27, 28

### What to build

A new `agent/` Python package in the monorepo that produces the public `ghcr.io/parley-quest/agent:latest` image. The entrypoint reads `PARLEY_*` environment variables, falls back to `/config/config.env` if the config volume is mounted, and — if required values are still missing and stdin is a TTY — launches a `questionary` + `rich` TUI that prompts only for what is missing. Values entered in the TUI are persisted to `/config/config.env` so subsequent runs start non-interactively. A `--no-tui` flag forces non-interactive mode with a clear failure message on missing required variables.

Once configured, the agent connects to `PARLEY_MCP_URL` using the bearer API key (the `fx_…` value returned by `create_game` / `join_game` — see Phase 5), confirms the game and seat, prints a one-line game summary, and enters the heuristic planner loop using `PARLEY_PROFILE` (`balanced` / `aggressive` / `economic` / `explorer`). If `PARLEY_LLM_PROVIDER` is anything other than `none`, `MultiLLMClient` is layered on top, letting Tier-1 users run LLM-driven play without writing code.

A new GitHub Actions workflow `agent-image.yml` builds and pushes `ghcr.io/parley-quest/agent:latest` + `ghcr.io/parley-quest/agent:<git-sha>` on every push to `main` that touches `agent/**` or `backend/src/mcp_server/**`, using GitHub's OIDC integration with GHCR (no long-lived PAT).

The acceptance test is running `docker run -it --rm -v $HOME/.parley:/config ghcr.io/parley-quest/agent:latest` on a fresh machine, completing the TUI, and watching the agent submit a turn against a live game on `mcp.parley.quest` — all within 60 seconds of first launching the container.

### Acceptance criteria

- [ ] `agent/` package exists with a TUI entrypoint and heuristic + LLM planner integration
- [ ] All user-facing env vars use the `PARLEY_*` prefix; `MultiLLMClient` still accepts legacy names
- [ ] First run on a clean machine prompts via TUI for missing Game ID, API key, profile, and optional LLM config; API key prompt is masked
- [ ] TUI answers are persisted to `/config/config.env` and honoured on subsequent runs without re-prompting
- [ ] `--no-tui` flag exits non-zero with a clear error when required variables are missing
- [ ] `agent-image.yml` workflow publishes `ghcr.io/parley-quest/agent:latest` and `:<git-sha>` on qualifying pushes to `main`
- [ ] Image is publicly pullable without auth
- [ ] Fresh-machine smoke test: `docker run` → TUI → playing agent in under 60 seconds
- [ ] Heuristic profiles work; selecting an LLM provider with valid credentials also works
- [ ] Agent cleanly handles MCP disconnection, auth failure, and game-ended states

---

## Phase 7: Tier-2 agent-starter repository

**User stories**: 16, 17, 18, 29

### What to build

The authoritative starter content lives in an `agent-starter/` directory in the main monorepo and is mirrored to the standalone public `parley-quest/agent-starter` repository on tagged releases, so users can fork a repo that contains only their agent and nothing else.

Contents of the starter:

- A minimal, heavily-commented MCP client loop (`agent.py`) that demonstrates the core read-plan-submit cycle against the MCP surface.
- A `Dockerfile` that does `FROM ghcr.io/parley-quest/agent:latest` and `COPY agent.py`, so users inherit the base image's dependency set without rebuilding Python.
- A `docker-compose.yml` that volume-mounts `agent.py` into the running container so edit-and-restart iteration does not require a rebuild.
- A `.env.sample` listing every `PARLEY_*` variable with comments.
- A `README.md` with the one-paragraph quick-start, a concise MCP tool-surface reference, and a short "how to customise" section.

A `sync-starter.yml` workflow in the main repo runs on tagged releases, cloning the standalone repo with a deploy key, replacing its contents from `agent-starter/`, and pushing with a release-tagged commit. Untagged pushes to `main` do not sync.

Demoed by creating a release tag in the main repo, observing the standalone repo update, cloning it fresh, copying `.env.sample` to `.env` with valid credentials, running `docker compose up`, and seeing the agent play a turn. Then editing `agent.py`, restarting the container (not rebuilding), and confirming the change takes effect.

### Acceptance criteria

- [ ] `agent-starter/` directory exists in the main monorepo with `agent.py`, `Dockerfile`, `docker-compose.yml`, `.env.sample`, `README.md`
- [ ] `agent.py` is minimal, heavily commented, and runs a visible read-plan-submit loop
- [ ] Dockerfile extends `ghcr.io/parley-quest/agent:latest`; no Python dependencies reinstalled
- [ ] `docker-compose.yml` volume-mounts `agent.py` so edits take effect on `docker compose restart`
- [ ] `.env.sample` documents every `PARLEY_*` variable the agent recognises
- [ ] `README.md` includes a quick-start, MCP tool reference, and customisation guide
- [ ] Standalone `parley-quest/agent-starter` repository exists and is publicly readable
- [ ] `sync-starter.yml` workflow fires on tagged releases and updates the standalone repo
- [ ] Fresh-clone demo: `git clone && cp .env.sample .env && docker compose up` reaches a playing agent
- [ ] Edit-and-restart iteration works without rebuilding the image

---

## Phase 8: Connect-an-agent UI

**User stories**: 19

### What to build

A "Connect an agent" control on the game lobby page in the web UI. Clicking it expands a panel that shows the exact `docker run -it --rm -v $HOME/.parley:/config -e PARLEY_GAME_ID=<id> ghcr.io/parley-quest/agent:latest` command pre-filled with the current game's ID, and a masked "Copy API key" button for each AI seat the signed-in user is entitled to control. A link to `github.com/parley-quest/agent-starter` encourages users who want to write their own agent to go the Tier-2 route.

The API key is revealed server-side only to users with seat ownership on the current game; the frontend never sees keys for other players' seats. Copy actions use the clipboard API with a visible confirmation toast. The panel is keyboard-accessible.

This phase closes the loop: a user signs into `parley.quest`, creates a game, clicks "Connect an agent", copies one command and one key into a terminal, and a few seconds later an agent is playing their seat.

### Acceptance criteria

- [ ] Game lobby page shows a "Connect an agent" button
- [ ] Clicking reveals a panel with the `docker run` command pre-filled with the current Game ID
- [ ] Copy-to-clipboard control for each AI seat key the signed-in user owns
- [ ] Keys for seats the signed-in user does not own are never sent to the browser
- [ ] Copy action shows a visible confirmation
- [ ] Panel includes a link to `github.com/parley-quest/agent-starter`
- [ ] End-to-end demo: sign in → create game → click Connect an agent → copy command + key → paste into terminal → agent plays within 60 seconds
- [ ] Accessibility: panel is keyboard-navigable, copy controls have accessible labels
