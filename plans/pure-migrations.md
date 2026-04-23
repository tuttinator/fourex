# Plan: pure Alembic migrations from the start

> Follow-up to the Phase 1 deployment work in `plans/deployment.md`.

## Problem

Schema creation lives in two places:

- `Base.metadata.create_all` inside `init_db()` (FastAPI lifespan and
  local dev) creates the baseline tables (`games`, `game_turns`,
  `player_actions`, `prompt_logs`).
- Alembic migrations starting at `20260415_000001` add incremental
  deltas and assume the baseline already exists — revision 1 declares
  `down_revision = None` but references `games.id` as a foreign key.

On a fresh Railway Postgres, `alembic upgrade head` crashes on the
first FK reference because nothing ever creates `games`. The Phase 1
deploy-blocker workaround was `backend/src/db_bootstrap.py`, which
detects an empty database and runs `create_all` + `alembic stamp head`
before subsequent boots hit the normal `upgrade head` path.

That workaround is fine operationally but leaves three warts:

1. Two sources of truth for "what is the baseline schema".
2. A bootstrap script that exists purely to reconcile them.
3. Local-dev databases whose provenance is `create_all`, not alembic
   — so their state is only nominally tracked.

The fix is to make Alembic the sole schema owner: a real baseline
migration that creates every baseline table, with `20260415_000001`
re-parented to it. After that, `alembic upgrade head` on a fresh
database produces the full schema unaided, `db_bootstrap.py` can be
deleted, and `init_db()` can be retired (or at most kept as a thin
pass-through for local test setup).

## Non-goals

- Renaming or restructuring any existing table. This work only
  captures the current schema accurately in a migration; any cleanup
  of historical naming or data belongs to a separate plan.
- Consolidating the seven individually-shipped migrations into one.
  Each carries its own commit history and context; collapsing them
  into a "squashed baseline" would lose that.
- Touching production data. The work targets greenfield behaviour
  for future fresh deployments and a clear migration path for the
  one live database (Railway) we already have.

## Phase 1: write the baseline migration

### What to build

Author a new Alembic revision `20260414_000001_baseline_schema`
(date stamped one day before the existing `20260415_000001`) that
creates every baseline table the current `20260415_000001` assumes
exists. Set `down_revision = None` on the new baseline and update
`20260415_000001`'s `down_revision` to point at it.

The baseline migration's body is produced by running Alembic's
autogenerate against an empty database, filtered down to only the
tables that are NOT created by any subsequent revision. In practice
that is:

- `games`
- `game_turns`
- `player_actions`
- `prompt_logs`

(All other tables — `agent_memory`, `turn_snapshots`, `turn_actions`,
`player_api_keys`, `user_identities`, `auth_verification_tokens`,
`game_snapshots`, `player_stats` — are already created by later
migrations; the baseline must not duplicate them.)

The simplest authoring flow: `docker compose up postgres`, run
`alembic upgrade head` against it (using the existing
`db_bootstrap.py` hack one last time to populate it), then
`alembic revision --autogenerate -m baseline_schema` against an empty
*second* database to get the full schema in one file, and hand-prune
the generated revision down to just the four baseline tables. Review
the diff against the SQLAlchemy models in
`backend/src/database/models.py` column-by-column — autogenerate is
not perfect for defaults and enum types.

### Acceptance criteria

- [ ] `backend/migrations/versions/20260414_000001_baseline_schema.py`
  exists with `down_revision = None` and creates exactly the four
  baseline tables plus their indices.
- [ ] `backend/migrations/versions/20260415_000001_*.py` has
  `down_revision = "20260414_000001"`.
- [ ] `alembic upgrade head` on a fresh empty database produces a
  schema byte-identical (modulo constraint naming) to
  `Base.metadata.create_all`, verified by a pytest that diffs
  `sqlalchemy.MetaData` reflected from each path.
- [ ] `alembic downgrade base` on the fresh database drops everything
  cleanly.
- [ ] All 812 existing backend tests pass unchanged.

---

## Phase 2: delete the bootstrap hack

### What to build

Remove `backend/src/db_bootstrap.py` and have `docker-entrypoint.sh`
go back to `alembic upgrade head`. Retire `init_db()` from the
FastAPI lifespan entirely — alembic is now the one true path to a
valid schema, and keeping `create_all` around invites drift where a
forgotten model is silently created in dev but missing in prod.

Local dev workflow changes:

- `mise run db-reset` currently uses `manage_db.py` with
  `create_all`/`drop_all`. Update it to `alembic downgrade base` +
  `alembic upgrade head` so a reset leaves the DB in the same
  alembic-tracked state as production.
- New `mise run db-migrate` task wrapping `alembic upgrade head` for
  day-to-day forward migration.
- `manage_db.py` can keep its inspection commands (`check`,
  `list-games`, `game-info`) but its `create` / `drop` / `reset` verbs
  should delegate to alembic rather than raw metadata operations.

Tests that use `init_db()` directly (there are a handful in the
pytest suite) move to a small fixture that runs
`alembic upgrade head` once per test session. SQLite in-memory tests
that can't run alembic migrations migrate to a throwaway Postgres
container via pytest-postgresql.

### Acceptance criteria

- [ ] `backend/src/db_bootstrap.py` deleted.
- [ ] `backend/docker-entrypoint.sh` runs `alembic upgrade head`
  directly, from `/app/backend`, with no bootstrap detour.
- [ ] `init_db()` removed from `backend/src/database/connection.py`
  and the FastAPI lifespan in `backend/src/main.py`.
- [ ] `manage_db.py` create/drop/reset verbs route through alembic.
- [ ] `mise run db-reset` and new `mise run db-migrate` tasks
  documented in `CLAUDE.md`.
- [ ] Test suite migrated onto alembic-backed fixtures; all 812
  existing tests still pass.
- [ ] `docs/deployment-setup.md` §4 simplified to reflect that
  migrations are just migrations.

---

## Phase 3: production cutover

### What to build

The live Railway database was bootstrapped via `create_all` + `stamp
head`, so its `alembic_version` row already points at the latest
revision. After Phase 1 introduces the baseline migration, that row
would be wrong — it would skip the new baseline revision during a
future `downgrade base`.

Cutover steps, run once against the production database:

1. Confirm current `alembic_version` value matches the pre-Phase-1
   `head`.
2. Manually update the row to sit between the old head and the new
   baseline so that a future downgrade chain unrolls cleanly. In
   practice the simplest approach is a single `alembic stamp head`
   after deploy, because the baseline revision is added behind the
   existing migrations — the head value doesn't change; only the
   chain walks further back on downgrade.
3. Run `alembic downgrade base` against a throwaway clone of the
   production database to confirm the chain unwinds without error.

This phase is entirely operational and guarded behind a one-time
runbook entry rather than code.

### Acceptance criteria

- [ ] Production `alembic_version` matches `head` after deploy,
  verified with `psql`.
- [ ] `alembic history` on the production database shows the new
  baseline as the first revision.
- [ ] A throwaway clone of production can `alembic downgrade base`
  cleanly, proving the chain is sound end-to-end.
- [ ] Runbook entry in `docs/deployment-setup.md` captures the
  cutover so it's obvious what happened for anyone auditing the
  schema history later.

---

## Risks and rollback

- If autogenerate misses a column default or a constraint, the new
  baseline diverges from the current `create_all` schema. Mitigation
  is the Phase 1 byte-comparison test — any discrepancy fails loudly
  before merge.
- If the cutover `stamp` is run against a database that has drifted
  (e.g. someone added a column manually), future migrations will
  conflict. Mitigation is a schema-drift check via
  `alembic check` before running the cutover stamp.
- Rollback from Phase 2 is straightforward: re-add
  `db_bootstrap.py`, re-wire the entrypoint, re-add `init_db` to the
  lifespan. No data changes involved.

## Sequencing with other work

This plan is independent of the deployment-phase roadmap and can
land between Phase 2 (CI) and Phase 5 (JWT auth) without blocking
any user-facing feature. Phase 4 (multiplayer in production)
specifically benefits because it adds no new tables and gives the
cleanest window to prove `alembic downgrade base` works end-to-end
on a production clone.
