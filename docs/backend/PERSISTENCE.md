# Backend Persistence

This backend stores game state in PostgreSQL using SQLAlchemy async models and a persistent game controller.

## What It Persists

- `games`
- `game_turns`
- `player_actions`
- `prompt_logs`
- `game_snapshots`
- `player_stats`

The backend also keeps an in-memory cache for active games, but the source of record is the database.

## Current Workflow

### Install dependencies

```bash
mise run install
```

### Configure the backend

```bash
cp backend/.env.example backend/.env
```

Common settings:

```env
DATABASE_URL=postgresql+asyncpg://fourex:fourex@localhost:5432/fourex
SQL_DEBUG=false
API_HOST=0.0.0.0
API_PORT=8010
DEBUG=true
```

### Database commands

From the repo root:

```bash
mise run db-create
mise run db-reset
mise run db-check
mise run db-list
mise run db-info GAME=<game_id>
```

### Run the backend

```bash
mise run run-dev
```

The backend listens on:

```text
http://localhost:8010
```

## Persistence Behavior

- A game is created through the persistent game controller.
- Current game state is written to the `games` table.
- Submitted actions are written to `player_actions`.
- Turn results are written to `game_turns`.
- Snapshots are created initially and then periodically.
- Prompt logs can be written through the REST API and are stored in `prompt_logs`.

## Useful Endpoints

- `GET /api/v1/games/{game_id}/info`
- `POST /api/v1/games/{game_id}/restore`
- `GET /api/v1/state`
- `POST /api/v1/actions`
- `POST /api/v1/prompts`
- `GET /health`

## Tests

```bash
mise run backend-test
mise run test
```

`mise run test` starts a temporary backend locally before running the root integration tests.

## Notes

- The backend currently initializes tables on startup.
- The persistence layer is real, but it is still fairly development-oriented: there are debug prints, a global controller instance, and startup-driven table creation.
- If you change connection settings, keep `backend/.env.example` and `mise.toml` aligned.
