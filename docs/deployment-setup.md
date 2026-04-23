# parley.quest Phase 1 deployment checklist

This document captures the manual one-time setup that provisions the
production topology described in `plans/deployment-prd.md`. Everything
here is expected to be performed once, by hand, through the relevant
vendor dashboards. Subsequent phases add automated CI/CD, auth, and
application wiring on top of this foundation.

The Phase 1 goal is reachable URLs — nothing more, nothing less:

- `https://parley.quest` serves a Next.js page.
- `https://api.parley.quest/healthz` returns `{"status":"ok","server":"4x-api"}`.
- `https://mcp.parley.quest/healthz` returns `{"status":"ok","server":"4x-mcp"}`.

## 1. Domain + Cloudflare DNS

1. Confirm `parley.quest` is registered and the registrar points
   nameservers at Cloudflare. Cloudflare is the authoritative DNS.
2. In Cloudflare → `parley.quest` → SSL/TLS, set the mode to **Full
   (strict)**. Railway terminates TLS with a valid certificate, so
   Full-strict is safe and rejects downgraded origins.
3. Enable the free-tier **WAF** managed rules and the automatic
   **DDoS** mitigation. No custom rules are needed for Phase 1.
4. DNS records (all proxied — the orange-cloud toggle must be on):
   | Type    | Name  | Content                                           |
   | ------- | ----- | ------------------------------------------------- |
   | `CNAME` | `@`   | Railway hostname for the `frontend` service       |
   | `CNAME` | `api` | Railway hostname for the `backend` service (8010) |
   | `CNAME` | `mcp` | Railway hostname for the `backend` service (8020) |

   The exact Railway hostnames are printed in step 3 below; copy them
   verbatim.

## 2. Create the Railway project

1. Sign in to Railway and create a project named `parley`.
2. Attach a **Postgres** plugin. Railway auto-exports
   `DATABASE_URL`; add a variable alias named `PARLEY_DATABASE_URL`
   pointing at `${{Postgres.DATABASE_URL}}` so both the application
   and Alembic pick it up via the canonical name.
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

## 3. Secrets

Populate these variables on Railway (service-level, not project-level,
unless noted):

| Variable                       | Service    | Notes                                                                           |
| ------------------------------ | ---------- | ------------------------------------------------------------------------------- |
| `PARLEY_DATABASE_URL`          | `backend`  | Reference-variable alias for `${{Postgres.DATABASE_URL}}`.                      |
| `PARLEY_AUTH_SECRET`           | `backend`  | 32+ random bytes. Must match the frontend `AUTH_SECRET`. Generate once.         |
| `PARLEY_JWT_SIGNING_SECRET`    | `backend`  | 32+ random bytes. Used by Phase 5 MCP auth; set now so later rollouts are free. |
| `PARLEY_GOOGLE_CLIENT_ID`      | `backend`  | Populated in Phase 3. Leave unset for Phase 1.                                  |
| `PARLEY_GOOGLE_CLIENT_SECRET`  | `backend`  | Populated in Phase 3.                                                           |
| `PARLEY_RESEND_API_KEY`        | `backend`  | Populated in Phase 3.                                                           |
| `AUTH_SECRET`                  | `frontend` | Same value as `PARLEY_AUTH_SECRET`.                                             |
| `NEXTAUTH_URL`                 | `frontend` | `https://parley.quest`.                                                         |

Generate secrets with `openssl rand -hex 32`. Do not commit them.

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

All three must succeed before closing the Phase 1 PR.

## Notes for later phases

- Phase 2 adds GitHub Actions CI/CD — no Railway dashboard work required
  beyond creating the `RAILWAY_TOKEN` repo secret.
- Phase 3 requires creating the Google OAuth client and verifying the
  Resend sender domain. Both are manual console clicks; keep this doc
  updated as the source of truth for repeatable setup.
- Phase 5 introduces JWT auth; `PARLEY_JWT_SIGNING_SECRET` is already
  set in this phase so no new Railway work is needed.
