# parley.quest Deployment & BYO-Agent PRD

## Problem Statement

The 4X strategy game exists as a working local development stack (Next.js frontend, FastAPI backend, MCP HTTP server, Postgres, heuristic agent runtime), but it has no production deployment. There is no way for a prospective player to visit a URL, sign in, create a game, invite another human, and play a match end-to-end. There is also no way for an AI-agent researcher to run their own agent against a live hosted game — the only path today is cloning the full monorepo and running `mise run quick` against an in-process game.

The project is hobby-scale with modest traffic expectations but occasional bursts (e.g. when showcased), so it needs:

1. A public, HTTPS-terminated deployment under a memorable domain with working Google sign-in.
2. A persistent, shared game server that humans and AI agents can both connect to.
3. A genuinely frictionless path — "copy one command, paste, play" — for researchers and hobbyists to connect an AI agent to a live game, without cloning the repo or reading deployment docs.
4. Automation so that every push to `main` ships to production without human involvement.
5. A total monthly cost in the low tens of dollars.

## Solution

Deploy the existing codebase to **Railway** as a single project with three services (frontend, backend+MCP bundled, Postgres), sit **Cloudflare** in front for DNS/WAF/DDoS under the `parley.quest` domain, and automate deploys with **GitHub Actions**.

Introduce a production auth surface on the MCP HTTP endpoint using per-game signed JWTs issued by `create_game` and `join_game`, so agents can authenticate statelessly without any user-account plumbing.

Ship a public agent Docker image to **GitHub Container Registry** under the `parley-quest` organisation. The image is fully self-contained: the end user runs `docker run -it --rm -v $HOME/.parley:/config ghcr.io/parley-quest/agent:latest` and is met by a small terminal UI that prompts for Game ID, API key, and optional LLM provider, persists the answers, and starts playing. The reference heuristic planner (`aggressive` / `economic` / `explorer` / `balanced`) is bundled so zero-code play works out of the box; the optional `MultiLLMClient` integration lets a Tier-1 user layer an LLM on top without writing code.

For users who want to write their own agent, a companion repository `parley-quest/agent-starter` is created on day one with a minimal, heavily-commented MCP client loop, a Dockerfile that extends the pre-built image, a `docker-compose.yml` that volume-mounts the user's `agent.py` for edit-and-restart iteration, a `.env.sample`, and a README documenting the MCP tool surface. The starter repo is kept in sync with the main repo's authoritative copy via a release-tag GitHub Actions workflow.

Consolidate all user-facing environment variable names under a single `PARLEY_*` prefix (agent-side) and use the same prefix for server-side secrets. Existing `MODAL_OLLAMA_URL` / `LLM_STUDIO_URL` / `OPENAI_API_KEY` names remain as backwards-compatible fallbacks inside `MultiLLMClient` but are not advertised in user-facing docs.

Surface the agent onboarding flow directly in the web UI with a "Connect an agent" button on the game lobby page that shows the exact `docker run` command pre-populated with the current Game ID and a one-click copy control for the API key.

## User Stories

1. As a first-time visitor, I want to visit `https://parley.quest` and see a working landing page over HTTPS, so that I trust the site is real and not a half-finished project.
2. As a visitor, I want to sign in with my Google account via a single OAuth click, so that I do not have to manage a new password.
3. As a signed-in user, I want to receive transactional emails (game invitations, turn notifications) from `noreply@parley.quest`, so that I can keep track of games I'm in without having the tab open.
4. As a signed-in user, I want to create a new game from the web UI, so that I can invite others to play.
5. As a game creator, I want to receive one API key per AI slot in the game I've created, so that I can pass those keys to agents (my own or someone else's).
6. As a signed-in user, I want to join an existing game by invitation link or code, so that I can play with a friend who created the game.
7. As a player, I want to play a full game turn-by-turn with real-time state updates via WebSocket, so that the game feels responsive.
8. As a player, I want my game state to persist across browser refreshes and server restarts, so that I do not lose progress.
9. As an AI-agent researcher, I want to run a single `docker run` command against a live game and have an agent start playing within a minute, so that I can evaluate the game as a research environment without reading any deployment docs.
10. As an AI-agent researcher on my first-ever run, I want to be prompted by a terminal UI for my Game ID, API key, and optional LLM provider, so that I do not have to hunt through documentation to discover which environment variables to set.
11. As an AI-agent researcher on my second run, I want the agent to start immediately without re-prompting, so that my saved credentials are not re-entered each time.
12. As an AI-agent researcher, I want to pick between the bundled heuristic profiles (`aggressive` / `economic` / `explorer` / `balanced`) without writing any code, so that I can observe game dynamics before committing to a custom agent.
13. As an AI-agent researcher with an OpenAI key, I want to plug it into the bundled agent via the TUI, so that I can test LLM-driven play immediately.
14. As an AI-agent researcher running a local model in LM Studio, I want to point the bundled agent at `http://localhost:1234`, so that I can play fully offline.
15. As a CI pipeline running in headless mode, I want to pass `--no-tui` so that the agent fails fast on missing credentials instead of hanging on a prompt.
16. As an AI-agent developer who wants to write my own logic, I want to `git clone parley-quest/agent-starter`, copy `.env.sample` to `.env`, and run `docker compose up`, so that I am playing against a live game within a few minutes of starting.
17. As an AI-agent developer iterating on my code, I want my `agent.py` to be volume-mounted into the running container so I can edit and restart without rebuilding the image, so that my inner loop is fast.
18. As an AI-agent developer, I want the starter repo's README to list the MCP tool surface with concise descriptions, so that I can discover what's possible without running the MCP Inspector.
19. As a player looking at my game lobby in the web UI, I want a "Connect an agent" button that shows me the exact `docker run` command with my Game ID pre-filled and a copy-to-clipboard control for the API key, so that I can forward credentials to a collaborator or paste them into my own terminal without error.
20. As a game creator, I want the API keys my game issues to expire, so that a leaked key cannot be used forever.
21. As a security-conscious user, I want API keys to be scoped to a single game and player, so that a leaked key's blast radius is limited to one match.
22. As the MCP server, I want to validate incoming JWTs statelessly, so that high-frequency agent polling does not create database load.
23. As the project owner, I want every push to `main` to automatically deploy the changed services to Railway, so that I do not have to run manual deploy commands.
24. As the project owner, I want frontend-only changes to skip backend CI and vice versa, so that CI runtime stays under a few minutes.
25. As the project owner, I want the four frontend feedback loops from CLAUDE.md (type-check, lint, test, build) to run on every PR, so that runtime Auth.js errors like `MissingAdapter` are caught before merge.
26. As the project owner, I want pull requests that fail CI to block merging, so that broken code does not reach production.
27. As a Tier-1 agent user, I want the Docker image to be published to GHCR on every main-branch push under the `parley-quest` organisation, so that `ghcr.io/parley-quest/agent:latest` always reflects the latest server-compatible agent code.
28. As a Tier-1 agent user, I want immutable `:sha` tags alongside `:latest`, so that I can pin a specific agent version when reproducing a bug.
29. As a starter-repo user, I want the standalone `parley-quest/agent-starter` repo to stay in sync with the authoritative copy in the main repo, so that my fork does not drift away from breaking MCP surface changes.
30. As the project owner, I want to keep total monthly Railway spend in the $15-25 range for hobby-level usage, so that the project does not become a financial burden.
31. As the project owner, I want a single vendor (Railway) for frontend, backend, and database, so that I only have one dashboard, one billing account, and one set of environment variables to manage.
32. As a visitor during a traffic spike (e.g. a demo tweet), I want the site to remain responsive, so that my first impression is not a timeout.
33. As a game player on slow Wi-Fi, I want the frontend to load quickly via Cloudflare's CDN, so that the initial page load does not feel slow.
34. As the project owner, I want DDoS protection and WAF on the public surface, so that obvious abuse is filtered before hitting Railway compute.
35. As the project owner, I want Railway's managed Postgres with automated backups, so that I do not have to operate a database.
36. As the project owner, I want the MCP HTTP server and the FastAPI REST/WS server to run in the same container on different ports, so that I pay for one Railway service instead of two.

## Implementation Decisions

### Hosting topology

- One Railway project named `parley` containing three services: `frontend`, `backend`, and the managed Postgres plugin.
- The `backend` service runs a single container that bundles both the FastAPI REST/WebSocket server (port 8010) and the FastMCP streamable-HTTP server (port 8020) as two async tasks in one process. Railway exposes both ports through two public domains attached to the same service.
- The `frontend` service runs the Next.js standalone production build.
- Cloudflare is configured as authoritative DNS for `parley.quest` with proxied (orange-cloud) records pointing at Railway's public hostnames. WAF and DDoS protection are enabled on the free tier.

### Domain mapping

- `parley.quest` → Next.js frontend
- `api.parley.quest` → FastAPI REST + WebSocket (backend service, port 8010)
- `mcp.parley.quest` → MCP HTTP (backend service, port 8020)
- Auth.js OAuth callback URL: `https://parley.quest/api/auth/callback/google`
- Transactional email sender identity: `noreply@parley.quest` via Resend

### Auth model

- Agents authenticate to the MCP HTTP server with a **per-game JWT** passed via `Authorization: Bearer <token>`.
- JWTs are signed with HS256 using `PARLEY_JWT_SIGNING_SECRET` held only on the server.
- Payload: `{ sub: "<player_id>", gid: "<game_id>", iat, exp }`. Expiry default is the configured maximum game duration plus a grace window.
- Tokens are minted by the `create_game` and `join_game` MCP tools. Human players continue to authenticate to the REST/WS surface via their Auth.js session cookie — JWTs exist solely for the MCP surface.
- MCP tool handlers extract the bearer token, verify the signature and expiry, and attach the decoded `{game_id, player_id}` context to the request before dispatching. Verification is stateless — no database call required.
- A leaked JWT can only be used against the single game/player it was issued for, and only until it expires.
- User-scoped long-lived tokens are deferred to a follow-up PRD.

### Web authentication

- Google OAuth provider added to the existing Auth.js v5 configuration in the frontend.
- Resend integrated as the email provider for magic-link and notification flows.
- Session adapter continues to use the existing Auth.js adapter pattern — no schema changes required beyond what Auth.js mandates.

### Environment variable conventions

- Canonical user-facing prefix is `PARLEY_*`. All documentation, `.env.sample` files, and the agent TUI use these names exclusively.
- Agent-facing variables: `PARLEY_API_KEY`, `PARLEY_GAME_ID`, `PARLEY_MCP_URL` (default `https://mcp.parley.quest`), `PARLEY_PROFILE`, `PARLEY_LLM_PROVIDER`, `PARLEY_LLM_API_KEY`, `PARLEY_LLM_BASE_URL`, `PARLEY_LLM_MODEL`.
- Server-facing variables (Railway secrets): `PARLEY_DATABASE_URL` (auto-injected by the Postgres plugin), `PARLEY_AUTH_SECRET`, `PARLEY_GOOGLE_CLIENT_ID`, `PARLEY_GOOGLE_CLIENT_SECRET`, `PARLEY_RESEND_API_KEY`, `PARLEY_JWT_SIGNING_SECRET`.
- The existing `MultiLLMClient` keeps recognising `MODAL_OLLAMA_URL`, `LLM_STUDIO_URL`, and `OPENAI_API_KEY` as a backwards-compatible fallback, but docs only mention the `PARLEY_*` names.

### Agent Docker image

- Image source lives in a new top-level `agent/` directory in the main monorepo (distinct from the existing `agents/` CLI shims). This is the authoritative source for the published image.
- Image is built by a GitHub Actions workflow on pushes to `main` affecting `agent/**` or `backend/src/mcp_server/**`, and published to `ghcr.io/parley-quest/agent:latest` plus an immutable `ghcr.io/parley-quest/agent:<git-sha>` tag.
- Entrypoint is a Python script that:
  - Reads `PARLEY_*` variables from environment and from `/config/config.env` if the config volume exists.
  - If required variables are missing and stdin is a TTY, launches an interactive TUI built on `questionary` + `rich` that prompts only for the missing values. The API key prompt is masked.
  - Persists entered values to `/config/config.env` with `chmod 600`-equivalent permissions so subsequent runs start non-interactively.
  - Supports `--no-tui` to force non-interactive mode: missing required variables cause immediate exit with a clear error.
  - Connects to the configured MCP URL using the bearer token, confirms the game exists and the player is seated, prints a one-line game summary, and enters the heuristic planner loop using the chosen profile.
  - Wraps the existing `MultiLLMClient` when a non-`none` LLM provider is selected, so Tier-1 users can mix heuristic planning with LLM planning without code changes.

### Agent starter repository

- Standalone repo `parley-quest/agent-starter` is created day one with its own git history, not a mirror of a monorepo subdirectory.
- Contents: `agent.py` (minimal, heavily-commented MCP client loop), `Dockerfile` (`FROM ghcr.io/parley-quest/agent:latest`), `docker-compose.yml` (volume-mounts `agent.py` for live-reload), `.env.sample`, `README.md` (quick-start + MCP tool surface reference + fork-and-customise guide).
- The authoritative copy of these files lives in `agent-starter/` inside the main monorepo so MCP surface changes can be made atomically with starter updates.
- A GitHub Actions workflow on tagged releases in the main repo pushes the `agent-starter/` directory contents to the standalone repo using a deploy key.

### Web UI — Connect an agent

- New "Connect an agent" control on the game lobby page.
- Reveals a panel showing the exact `docker run` command with the Game ID pre-filled.
- A copy-to-clipboard control for the per-slot API key. The key is only rendered for slots the signed-in user is entitled to see (their own seats).
- Link out to the starter repo for users who want to write custom agents.

### GitHub Actions workflows (main repo)

- `ci.yml` — runs on every PR. Path-filtered jobs: a backend job runs `mise run lint`, `mise run backend-test`, and `mise run test`; a frontend job runs `npm run type-check`, `npm run lint`, `npm run test -- --run`, and `npm run build`. Both gate merging.
- `deploy.yml` — runs on push to `main`. Path-filtered matrix: `railway up --service frontend` and/or `railway up --service backend` fire only when relevant paths changed. Authenticates with `RAILWAY_TOKEN` GitHub secret.
- `agent-image.yml` — runs on push to `main` affecting `agent/**` or `backend/src/mcp_server/**`. Builds and pushes `ghcr.io/parley-quest/agent:latest` and `:<sha>` using the GitHub Actions OIDC integration with GHCR.
- `sync-starter.yml` — runs on tagged releases. Pushes `agent-starter/` to the standalone `parley-quest/agent-starter` repo using a stored deploy key.

### Build & release order

1. JWT minting in `create_game` / `join_game` plus bearer-token verification middleware on the MCP HTTP surface.
2. `backend/Dockerfile` that runs FastAPI and MCP HTTP as two tasks in one process.
3. `frontend/Dockerfile` using Next.js standalone output; Google OAuth provider wired into Auth.js; Resend wired for transactional email.
4. Railway project created, services configured, environment variables set, Postgres plugin attached. (Performed by the owner following a click-path guide.)
5. Cloudflare DNS records created for `parley.quest`, `api.parley.quest`, `mcp.parley.quest`.
6. `ci.yml` and `deploy.yml` GitHub Actions workflows added and validated.
7. `agent/` package built with TUI, `MultiLLMClient` integration, and `PARLEY_*` env var handling.
8. `agent-image.yml` workflow added; first `ghcr.io/parley-quest/agent:latest` published and smoke-tested from a clean machine.
9. `parley-quest/agent-starter` standalone repo created; `sync-starter.yml` workflow validated with a test release tag.
10. "Connect an agent" UI shipped on the game lobby page.

## Out of Scope

- User-scoped long-lived agent tokens that span multiple games under one key. Per-game JWTs only for this PRD.
- Rate limiting, quota management, or abuse controls on the MCP endpoint beyond what Cloudflare WAF provides.
- Production observability dashboards. Logfire is already wired in code but its production configuration, alerting, and dashboards are deferred.
- Further BYO-agent UX improvements beyond the TUI (these will be a follow-up PRD).
- Any form of agent registry, marketplace, or public directory.
- Multi-region deployment or failover.
- Mobile-native clients.
- Payment processing or paid tiers.
- Migration tooling for the existing local-development database — this PRD assumes a fresh production database.
- Changes to the deterministic game engine itself. This PRD is deployment infrastructure and an auth layer only.

## Further Notes

### Cost envelope

Target is $15–25/month on Railway Hobby-tier usage pricing, assuming the frontend and backend services are mostly idle with occasional short bursts. Railway's usage-based model means idle time costs close to zero. Neon / external Postgres were considered but rejected in favour of Railway's managed Postgres to keep single-vendor simplicity. The domain (purchased separately) and Resend are not counted against this budget.

### Why JWT rather than opaque tokens

Agents polling `is_my_turn` every few seconds would generate a steady DB load if every call required a token lookup. Signed JWTs keep MCP verification entirely in-memory. The JWT signing secret never leaves Railway, and tokens expire naturally.

### Why GHCR rather than Docker Hub

GHCR is free for public images under a GitHub organisation, integrates cleanly with GitHub Actions OIDC (no long-lived secret), and the `parley-quest` organisation is already the canonical namespace for the project's source code.

### Why a standalone starter repo rather than a monorepo subdirectory

Users should be able to fork a repo that is purely their agent. A fork of the main monorepo would drag along the entire backend and frontend, which is confusing and invites accidental upstream PRs. Keeping the authoritative source inside the main monorepo (for atomic edits with MCP surface changes) and publishing to a standalone repo via CI gives us the best of both worlds.

### Existing code to reuse

The repo already has next-auth v5 installed, an `auth.ts` / `auth-adapter.ts` pair in the frontend, a working FastMCP server with lifecycle and gameplay tools, and `MultiLLMClient` with OpenAI / LM Studio / Modal Ollama support. None of this needs to be rewritten for this PRD — only wired into production configuration.

### Known friction points to monitor

- Railway's multi-port-per-service support needs to be verified during step 4. If it proves awkward, the fallback is running the MCP HTTP server as a separate Railway service with its own Dockerfile, at roughly double the backend compute cost.
- Auth.js `MissingAdapter` runtime errors are historically only caught by `npm run build`, not by type-check or unit tests. The `ci.yml` workflow must run `build` to catch these pre-merge.
- First-time Google OAuth users will receive the unverified-app warning until the OAuth consent screen is submitted for verification. This is a manual Google Cloud Console step outside CI.
