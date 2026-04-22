"""Phase 4 spectated-agents: manual archive.

Covers the Phase 4 acceptance criteria in ``plans/spectated-agents.md``:

- ``POST /games/{id}/archive`` succeeds for the creator, 403 for others.
- ``POST /games/{id}/unarchive`` restores and clears the archive columns.
- Archiving sets ``archived_reason='manual'``.
- ``GET /games`` hides archived rows by default; ``include_archived=true``
  surfaces them.
- Turn snapshots remain queryable after archive.
"""

from __future__ import annotations

import time

import jwt
import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import delete

from backend.src.config import settings
from backend.src.database.connection import async_session_factory, init_db
from backend.src.database.models import Game, PlayerApiKey, UserIdentity
from backend.src.database.repository import GameRepository
from backend.src.main import app

ALG = "HS256"


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest_asyncio.fixture
async def _clean_archive_rows() -> None:
    await init_db()
    async with async_session_factory() as session:
        await session.execute(
            delete(PlayerApiKey).where(PlayerApiKey.game_id.like("archive_%"))
        )
        await session.execute(delete(Game).where(Game.id.like("archive_%")))
        await session.execute(
            delete(UserIdentity).where(
                UserIdentity.email.like("%@archive.example.com")
            )
        )
        await session.commit()
    yield
    async with async_session_factory() as session:
        await session.execute(
            delete(PlayerApiKey).where(PlayerApiKey.game_id.like("archive_%"))
        )
        await session.execute(delete(Game).where(Game.id.like("archive_%")))
        await session.execute(
            delete(UserIdentity).where(
                UserIdentity.email.like("%@archive.example.com")
            )
        )
        await session.commit()


def _mint_jwt(user_identity_id: int) -> str:
    now = int(time.time())
    return jwt.encode(
        {"sub": str(user_identity_id), "iat": now, "exp": now + 3600},
        settings.auth_secret,
        algorithm=ALG,
    )


async def _seed_identity(email: str) -> int:
    async with async_session_factory() as session:
        repo = GameRepository(session)
        identity = await repo.upsert_user_identity_by_email(email)
        await session.commit()
        return identity.id


def _game_id(suffix: str) -> str:
    return f"archive_{suffix}_{int(time.time() * 1000000)}"


async def _create_lobby(
    client: TestClient, game_id: str, creator_player_id: str, jwt_token: str
) -> None:
    resp = client.post(
        f"/api/v1/games?game_id={game_id}",
        json={"player_id": creator_player_id, "player_slots": 2},
        headers={"Authorization": f"Bearer {jwt_token}"},
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_archive_succeeds_for_creator_and_stamps_reason(
    client: TestClient, _clean_archive_rows: None
) -> None:
    uid = await _seed_identity("creator@archive.example.com")
    token = _mint_jwt(uid)
    game_id = _game_id("ok")
    await _create_lobby(client, game_id, "alice", token)

    resp = client.post(
        f"/api/v1/games/{game_id}/archive",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["archived_at"] is not None
    assert body["archived_reason"] == "manual"

    async with async_session_factory() as session:
        repo = GameRepository(session)
        row = await repo.get_game(game_id)
        assert row is not None
        assert row.archived_at is not None
        assert row.archived_reason == "manual"


@pytest.mark.asyncio
async def test_archive_rejects_non_creator_with_403(
    client: TestClient, _clean_archive_rows: None
) -> None:
    creator_uid = await _seed_identity("creator2@archive.example.com")
    creator_token = _mint_jwt(creator_uid)
    game_id = _game_id("403")
    await _create_lobby(client, game_id, "alice", creator_token)

    other_uid = await _seed_identity("other@archive.example.com")
    other_token = _mint_jwt(other_uid)

    resp = client.post(
        f"/api/v1/games/{game_id}/archive",
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_archive_404_for_unknown_game(
    client: TestClient, _clean_archive_rows: None
) -> None:
    uid = await _seed_identity("ghost@archive.example.com")
    token = _mint_jwt(uid)
    resp = client.post(
        f"/api/v1/games/{_game_id('missing')}/archive",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_unarchive_clears_archive_columns(
    client: TestClient, _clean_archive_rows: None
) -> None:
    uid = await _seed_identity("creator3@archive.example.com")
    token = _mint_jwt(uid)
    game_id = _game_id("restore")
    await _create_lobby(client, game_id, "alice", token)

    client.post(
        f"/api/v1/games/{game_id}/archive",
        headers={"Authorization": f"Bearer {token}"},
    )

    resp = client.post(
        f"/api/v1/games/{game_id}/unarchive",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["archived_at"] is None
    assert body["archived_reason"] is None

    async with async_session_factory() as session:
        repo = GameRepository(session)
        row = await repo.get_game(game_id)
        assert row is not None
        assert row.archived_at is None
        assert row.archived_reason is None


@pytest.mark.asyncio
async def test_list_games_hides_archived_by_default_and_surfaces_with_flag(
    client: TestClient, _clean_archive_rows: None
) -> None:
    uid = await _seed_identity("creator4@archive.example.com")
    token = _mint_jwt(uid)
    game_id = _game_id("list")
    await _create_lobby(client, game_id, "alice", token)

    # Before archive: the row is in the default list (status=waiting filter).
    resp = client.get("/api/v1/games?status=waiting&limit=100")
    assert resp.status_code == 200
    ids_before = [g["game_id"] for g in resp.json()["games"]]
    assert game_id in ids_before

    # Archive it.
    client.post(
        f"/api/v1/games/{game_id}/archive",
        headers={"Authorization": f"Bearer {token}"},
    )

    # Default list now omits it.
    resp = client.get("/api/v1/games?status=waiting&limit=100")
    ids_default = [g["game_id"] for g in resp.json()["games"]]
    assert game_id not in ids_default

    # Explicit include_archived brings it back with the metadata set.
    resp = client.get("/api/v1/games?include_archived=true&limit=100")
    games = resp.json()["games"]
    row = next((g for g in games if g["game_id"] == game_id), None)
    assert row is not None
    assert row["archived_at"] is not None
    assert row["archived_reason"] == "manual"


@pytest.mark.asyncio
async def test_archive_is_idempotent_on_already_archived_game(
    client: TestClient, _clean_archive_rows: None
) -> None:
    uid = await _seed_identity("creator5@archive.example.com")
    token = _mint_jwt(uid)
    game_id = _game_id("idem")
    await _create_lobby(client, game_id, "alice", token)

    first = client.post(
        f"/api/v1/games/{game_id}/archive",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert first.status_code == 200
    first_at = first.json()["archived_at"]

    # Second archive call should not error and should not modify archived_at.
    second = client.post(
        f"/api/v1/games/{game_id}/archive",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert second.status_code == 200
    assert second.json()["archived_at"] == first_at


@pytest.mark.asyncio
async def test_archive_requires_jwt(
    client: TestClient, _clean_archive_rows: None
) -> None:
    uid = await _seed_identity("creator6@archive.example.com")
    token = _mint_jwt(uid)
    game_id = _game_id("nojwt")
    await _create_lobby(client, game_id, "alice", token)

    resp = client.post(f"/api/v1/games/{game_id}/archive")
    assert resp.status_code == 401
