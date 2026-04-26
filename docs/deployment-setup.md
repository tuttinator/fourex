# parley.quest deployment checklist

This document captures the manual vendor-side setup that provisions the
production topology described in `plans/deployment.md`. Everything here
is expected to be performed once, by hand, through the relevant vendor
dashboards; the GitHub Actions workflows added in Phase 2 take over
from there.

The Phase 1 goal was reachable URLs:

- `https://parley.quest` serves a Next.js page.
- `https://api.parley.quest/healthz` returns `{"status":"ok","server":"4x-api"}`.
- `https://mcp.parley.quest/healthz` returns `{"status":"ok","server":"4x-mcp"}`.

Phases 3 and 5 added authentication on top. See the "Divergence from
PRD" sections in `plans/deployment.md` for the full reconciliation
between the PRD's original intent and what actually shipped; the
short version is that sign-in is magic-link via Resend (no Google
OAuth) and agent auth is opaque per-seat API keys (no standalone
JWT signing secret).

## 1. Domain + Cloudflare DNS

1. Confirm `parley.quest` is registered and the registrar points
   nameservers at Cloudflare. Cloudflare is the authoritative DNS.
2. In Cloudflare → `parley.quest` → SSL/TLS, set the mode to **Full
   (strict)**. Railway terminates TLS with a valid certificate, so
   Full-strict is safe and rejects downgraded origins.
3. Enable the free-tier **WAF** managed rules and the automatic
   **DDoS** mitigation. No custom rules are needed.
4. DNS records (all proxied — the orange-cloud toggle must be on):
   | Type    | Name  | Content                                           |
   | ------- | ----- | ------------------------------------------------- |
   | `CNAME` | `@`   | Railway hostname for the `frontend` service       |
   | `CNAME` | `api` | Railway hostname for the `backend` service (8010) |
   | `CNAME` | `mcp` | Railway hostname for the `backend` service (8020) |

   The exact Railway hostnames are printed in step 2 below; copy them
   verbatim.
5. Phase 3 adds three more records for Resend's outbound sender
   domain (`parley.quest`): one `TXT` for SPF, one `CNAME`/`TXT` pair
   for DKIM, and one `TXT` for DMARC. Resend's dashboard prints the
   exact values after you add the domain.

## 2. Create the Railway project

1. Sign in to Railway and create a project (internal Railway name
   `empathetic-mindfulness`; "parley" is fine too — the identifier
   isn't user-visible).
2. Attach a **Postgres** plugin. Railway auto-exports
   `DATABASE_URL`; add a variable alias named `PARLEY_DATABASE_URL`
   pointing at `${{Postgres.DATABASE_URL}}` so both the application
   (`backend/src/database/connection.py`) and Alembic
   (`backend/migrations/env.py`) pick it up via the canonical name.
3. Create the `backend` service:
   - Source: this repo.
   - Root directory: `.` (repo root — the Dockerfile references
     `pyproject.toml` and `uv.lock` at the root).
   - Dockerfile path: `backend/Dockerfile`.
   - Ports: expose **8010** and **8020**. Attach a custom domain
     `api.parley.quest` to port 8010 and `mcp.parley.quest` to
     port 8020. Railway will surface the target CNAME hostnames to
     copy into Cloudflare.
4. Create the `frontend` service:
   - Source: this repo.
   - Root directory: `frontend`.
   - Dockerfile path: `frontend/Dockerfile`.
   - Attach the apex custom domain `parley.quest`.
   - `NEXT_PUBLIC_API_URL` must be wired as a **build argument** on
     this service — not just a runtime env var — because Next.js
     inlines `NEXT_PUBLIC_*` values into the client bundle at build
     time (see `frontend/Dockerfile` `ARG NEXT_PUBLIC_API_URL`). In
     Railway this means adding it under the service's variables with
     the "Available at build" toggle, or wiring it through the
     Nixpacks / Dockerfile build-args config.

## 3. Secrets

Populate these variables on Railway (service-level, not project-level,
unless noted). Generate secrets with `openssl rand -hex 32`; do not
commit them.

### Backend service

| Variable                   | Notes                                                                                             |
| -------------------------- | ------------------------------------------------------------------------------------------------- |
| `PARLEY_DATABASE_URL`      | Reference-variable alias for `${{Postgres.DATABASE_URL}}`.                                        |
| `AUTH_SECRET`              | 32+ random bytes. **Must match the frontend `AUTH_SECRET`** — this is how FastAPI verifies the HS256 JWTs issued by Auth.js (`backend/src/identity.py`). |
| `IDENTITY_SERVICE_SECRET`  | 32+ random bytes. Shared with the frontend; gates the `/api/v1/identities/upsert` endpoint the Next.js server route calls on first magic-link verify. |
| `CORS_ORIGINS`             | JSON list of allowed browser origins. Production value: `["https://parley.quest"]`. Without this, the default list (`localhost`) will cause the browser to reject real requests in Phase 4. |

### Frontend service

| Variable                   | Notes                                                                                             |
| -------------------------- | ------------------------------------------------------------------------------------------------- |
| `AUTH_SECRET`              | Same value as the backend `AUTH_SECRET`. Signs Auth.js session JWTs that FastAPI verifies.        |
| `AUTH_RESEND_KEY`          | Resend API key. Auth.js's Resend provider picks this up automatically.                             |
| `AUTH_EMAIL_FROM`          | Verified sender on `parley.quest` (production value: `noreply@parley.quest`).                     |
| `AUTH_TRUST_HOST`          | `true`. Required alongside the `trustHost: true` config flag in `frontend/src/auth.ts` — on `next-auth@5.0.0-beta.31` the config flag alone does not clear `UntrustedHost` in prod. |
| `NEXTAUTH_URL`             | `https://parley.quest`.                                                                           |
| `INTERNAL_API_URL`         | Server-to-server base URL the Auth.js adapter uses when calling FastAPI. In Railway this should be the backend's internal URL (e.g. `http://backend.railway.internal:8010`) to avoid routing through Cloudflare; `https://api.parley.quest` also works but pays an extra hop. |
| `IDENTITY_SERVICE_SECRET`  | Same value as the backend `IDENTITY_SERVICE_SECRET`.                                              |
| `NEXT_PUBLIC_API_URL`      | `https://api.parley.quest/api/v1`. **Build-time only** — see §2 step 4 for the build-arg wiring. Used by the browser for REST + WebSocket (`frontend/src/lib/api.ts`, `frontend/src/hooks/use-lobby-events.ts`). |

### What's deliberately absent

The following were named in the PRD but **were not adopted**; do not
create them on Railway. See `plans/deployment.md` Phase 3 and Phase 5
for the rationale.

- `PARLEY_AUTH_SECRET` — superseded by `AUTH_SECRET` (Auth.js's
  native name, shared between the two services).
- `PARLEY_JWT_SIGNING_SECRET` — no separate agent-JWT secret. Agent
  auth ships as opaque API keys hashed in `player_api_keys`; the
  only JWT surface is human → FastAPI, signed with `AUTH_SECRET`.
- `PARLEY_GOOGLE_CLIENT_ID` / `PARLEY_GOOGLE_CLIENT_SECRET` —
  superseded by magic-link-only sign-in.
- `PARLEY_RESEND_API_KEY` — superseded by `AUTH_RESEND_KEY`, the
  name Auth.js's Resend provider auto-picks.

## 4. Deploy

1. Push `main`. Railway auto-builds both services from their
   Dockerfiles. The backend entrypoint runs `alembic upgrade head`
   before booting the two async servers (FastAPI on 8010, MCP HTTP
   on 8020). Confirm logs show a clean migration run.
2. Visit each URL and confirm the Phase 1 acceptance criteria:
   - `https://parley.quest` serves the Next.js landing page.
   - `https://api.parley.quest/healthz` returns JSON.
   - `https://mcp.parley.quest/healthz` returns JSON.

## 5. Smoke test

From a clean terminal:

```bash
curl -sf https://api.parley.quest/healthz | jq
curl -sf https://mcp.parley.quest/healthz | jq
curl -sfI https://parley.quest
```

All three must succeed.

## 6. Migration history runbook

The live Postgres was originally bootstrapped by commit `e02bfc1`
using `Base.metadata.create_all` followed by `alembic stamp head`
— at the time, the earliest Alembic revision assumed baseline
tables like `games` already existed. The `plans/pure-migrations.md`
work closed that gap: commit `0925756` added a real baseline
migration (`20260414_000001_baseline_schema`), commits `a187253`
and `a9e25f9` retired the bootstrap script and routed `init_db()`
through Alembic.

Net effect on the production database:

- `alembic_version` already points at the latest revision (it was
  stamped there by the original bootstrap).
- The baseline migration was inserted *behind* the existing chain;
  head did not move, so `alembic upgrade head` on the next deploy
  is a no-op.
- Downgrades now walk one revision further back to the new
  baseline before reaching empty — useful for a full-reset clone,
  not normally run against production.

Post-deploy verification (run once, after the first boot that
includes the baseline migration):

```bash
# From a Railway service shell or psql session against production.
psql "$PARLEY_DATABASE_URL" -c "SELECT version_num FROM alembic_version;"
# Expected: the current head (see backend/migrations/versions/).
```

If the value is missing, the bootstrap never ran and the next
deploy should recreate it via `alembic upgrade head`. If the
value points at an unknown revision, someone has deployed a
branch ahead of main — do not stamp blindly; reconcile first.

For a full chain-integrity check, clone the production database
into a throwaway target and run `alembic downgrade base` there.
The chain should unwind cleanly and leave only `alembic_version`
behind. Never run this against production.

## 7. Branch protection status runbook

`gh api repos/tuttinator/fourex/branches/main/protection` returns
`404 Branch not protected` — this is expected. That endpoint only
surfaces *classic* branch protection; this repo uses Rulesets. The
active ruleset is `15504879` ("Default branches", `enforcement:
active`), enforcing `deletion`, `non_fast_forward`, `pull_request`,
and `required_status_checks` pinned to context `CI`. Query it with:

```bash
gh api repos/tuttinator/fourex/rulesets/15504879
```

## Notes on later phases

- **Phase 2** (CI/CD) — complete. Adds `.github/workflows/ci.yml`
  and `.github/workflows/deploy.yml`. Only Railway-side action
  required was creating the `RAILWAY_TOKEN` repo secret.
- **Phase 3** (magic-link sign-in) — complete. Requires the
  Resend account with `parley.quest` domain verified (SPF, DKIM,
  DMARC in Cloudflare per §1.5) and the `AUTH_*` frontend vars
  populated per §3.
- **Phase 4** (multiplayer in prod) — in progress. Primarily
  validation rather than new code. The two config prerequisites
  are `NEXT_PUBLIC_API_URL` (§3 frontend table) and `CORS_ORIGINS`
  (§3 backend table); both are covered above.
- **Phase 5** (per-seat API keys) — complete. No new Railway
  secrets were introduced; keys are minted on demand by
  `create_game` / `join_game` and stored hashed in the
  `player_api_keys` table.
