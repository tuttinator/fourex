# Plan: parley.quest Deployment & BYO-Agent

> Source PRD: `plans/deployment-prd.md`

## Architectural decisions

Durable decisions that apply across all phases.

- **Vendors**: Railway (all compute + managed Postgres), Cloudflare (DNS + WAF + DDoS, no compute), GitHub Container Registry (public agent image under `parley-quest` org), Resend (transactional email), Google (OAuth provider).
- **Domains**:
  - `parley.quest` → Next.js frontend
  - `api.parley.quest` → FastAPI REST + WebSocket (backend service, port 8010)
  - `mcp.parley.quest` → MCP streamable-HTTP (same backend service, port 8020)
  - Auth.js callback: `https://parley.quest/api/auth/callback/google`
  - Email sender: `noreply@parley.quest`
- **Railway topology**: one project named `parley`, three services (`frontend`, `backend`, Postgres plugin). The `backend` service runs a single container with FastAPI and FastMCP as two async tasks sharing one process.
- **Auth**:
  - Human users on the web → Auth.js v5 session cookies, Google provider only.
  - AI agents on MCP → per-game HS256 JWTs minted by `create_game` / `join_game`, payload `{ sub: player_id, gid: game_id, iat, exp }`, signed with `PARLEY_JWT_SIGNING_SECRET`, verified statelessly on every MCP request.
  - No user-scoped cross-game agent tokens in this plan (deferred).
- **Environment variable prefix**: `PARLEY_*` is canonical for all user-facing and server-side config. Legacy `MODAL_OLLAMA_URL` / `LLM_STUDIO_URL` / `OPENAI_API_KEY` remain as backwards-compatible fallbacks inside `MultiLLMClient` but are not advertised.
- **Schema**: no new tables required for this plan. JWT auth is stateless; Auth.js adapter tables are whatever the existing adapter already uses. Per-slot API key metadata is derivable from game + player identifiers, not stored.
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
- [ ] All required server secrets (`PARLEY_AUTH_SECRET`, `PARLEY_JWT_SIGNING_SECRET`, etc.) are populated in Railway; `PARLEY_DATABASE_URL` is injected by the Postgres plugin — **manual vendor step, captured in `docs/deployment-setup.md` §3**; application side now honours `PARLEY_DATABASE_URL` in both `backend/src/database/connection.py` and `backend/migrations/env.py`
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

- [ ] `.github/workflows/ci.yml` runs on all PRs with path-filtered frontend and backend jobs
- [ ] Frontend CI job runs `npm run type-check`, `npm run lint`, `npm run test -- --run`, and `npm run build`
- [ ] Backend CI job runs `mise run lint`, `mise run backend-test`, and `mise run test`
- [ ] `.github/workflows/deploy.yml` runs on push to `main` with a matrix that only deploys services whose paths changed
- [ ] Deploy workflow authenticates to Railway via a `RAILWAY_TOKEN` repository secret
- [ ] A demo frontend-only PR triggers only the frontend CI job and, after merge, only the frontend deploy
- [ ] A demo backend-only PR triggers only the backend CI job and, after merge, only the backend deploy
- [ ] Branch protection on `main` requires passing CI before merge

---

## Phase 3: Google sign-in and Resend email

**User stories**: 2, 3

### What to build

Wire Google as the Auth.js provider against the production callback URL and configure Resend as the email transport for Auth.js notifications. A visitor clicking "Sign in with Google" on `parley.quest` completes OAuth, lands back on the site, and sees their Google profile rendered in a navbar.

Google Cloud Console work (creating the OAuth client, configuring the consent screen, whitelisting the redirect URI) is a manual checklist done once. Resend setup (domain verification on `parley.quest`, API key provisioning, adding the sender identity) is also manual and done once. Both result in secrets stored as Railway environment variables and referenced by Auth.js at runtime.

A test email flow — the simplest being an Auth.js event log that emails on sign-in, or a dedicated "send me a test email" button behind a temporary admin flag — proves Resend is working end-to-end against the production domain. The test hook is removed before shipping Phase 4.

### Acceptance criteria

- [ ] Google Cloud OAuth client exists with production redirect URI whitelisted
- [ ] Auth.js Google provider is registered and `PARLEY_GOOGLE_CLIENT_ID` / `PARLEY_GOOGLE_CLIENT_SECRET` are set in Railway
- [ ] Sign-in button on `parley.quest` completes Google OAuth and renders the signed-in user's name/avatar
- [ ] `PARLEY_AUTH_SECRET` is set; sessions persist across browser refresh
- [ ] Resend account has `parley.quest` domain verified (SPF, DKIM, DMARC records in Cloudflare)
- [ ] `PARLEY_RESEND_API_KEY` is set in Railway
- [ ] A test email from `noreply@parley.quest` is successfully delivered to an external inbox
- [ ] Sign-out works and clears the session cookie

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

## Phase 5: MCP JWT auth

**User stories**: 5, 20, 21, 22

### What to build

Introduce signed-JWT authentication on the MCP HTTP surface. `create_game` and `join_game` mint per-seat JWTs with payload `{ sub: player_id, gid: game_id, iat, exp }` signed using `PARLEY_JWT_SIGNING_SECRET` (HS256). Every other MCP tool requires a valid `Authorization: Bearer <token>` header, verified statelessly — signature, expiry, and that the `gid` claim matches the game the tool is being called against.

Unauthenticated requests to protected tools return a structured error. Expired or malformed tokens likewise. Tokens are scoped: a JWT issued for Game A cannot be used to call tools against Game B.

This phase is demoable entirely with curl or the MCP Inspector against `mcp.parley.quest`. A short verification script in the repo runs: create a game, extract the JWT, call `get_game_state` with it (success), call with a tampered signature (rejected), call with a token from a different game (rejected), call after simulated expiry (rejected).

No Docker image yet — that is Phase 6. The REST/WS surface is unaffected; human users continue to authenticate with Auth.js session cookies.

### Acceptance criteria

- [ ] `create_game` and `join_game` return a per-seat JWT for each AI slot
- [ ] JWTs are HS256-signed with `PARLEY_JWT_SIGNING_SECRET` and include `sub`, `gid`, `iat`, `exp` claims
- [ ] All MCP tools other than lifecycle require a valid bearer token and extract `{game_id, player_id}` from it
- [ ] Verification is stateless — no database query during verification
- [ ] Invalid signatures, expired tokens, and cross-game tokens are rejected with a clear error
- [ ] Verification script in the repo runs the happy path and four failure modes successfully
- [ ] MCP Inspector session against `mcp.parley.quest` with a real JWT completes an end-to-end flow (create → state query → submit actions)
- [ ] No regressions to REST or WebSocket auth

---

## Phase 6: Tier-1 agent Docker image with TUI

**User stories**: 9, 10, 11, 12, 13, 14, 15, 27, 28

### What to build

A new `agent/` Python package in the monorepo that produces the public `ghcr.io/parley-quest/agent:latest` image. The entrypoint reads `PARLEY_*` environment variables, falls back to `/config/config.env` if the config volume is mounted, and — if required values are still missing and stdin is a TTY — launches a `questionary` + `rich` TUI that prompts only for what is missing. Values entered in the TUI are persisted to `/config/config.env` so subsequent runs start non-interactively. A `--no-tui` flag forces non-interactive mode with a clear failure message on missing required variables.

Once configured, the agent connects to `PARLEY_MCP_URL` using the bearer JWT, confirms the game and seat, prints a one-line game summary, and enters the heuristic planner loop using `PARLEY_PROFILE` (`balanced` / `aggressive` / `economic` / `explorer`). If `PARLEY_LLM_PROVIDER` is anything other than `none`, `MultiLLMClient` is layered on top, letting Tier-1 users run LLM-driven play without writing code.

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
