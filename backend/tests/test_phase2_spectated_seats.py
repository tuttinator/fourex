"""
Phase 2 spectated-agents: verify /games exposes per-seat identity metadata.

The frontend games list needs to tell Resume (viewer is seated) from
Observe (viewer is signed in but a spectator) and flag agent-only games.
Both signals hinge on the ``user_identity_id`` attached to each
``PlayerApiKey`` row — MCP-minted keys leave it null, human-minted keys
carry the id. These tests pin the wire format that the frontend depends
on so a future refactor of the listing endpoint can't silently drop it.
"""

from __future__ import annotations

import time

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

from backend.src.auth import create_player_key
from backend.src.database.connection import async_session_factory, init_db
from backend.src.database.models import UserIdentity
from backend.src.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest_asyncio.fixture
async def _init_db() -> None:
    await init_db()


def _game_id(prefix: str) -> str:
    return f"{prefix}_{int(time.time() * 1000000)}"


async def _seed_user(email: str) -> int:
    async with async_session_factory() as session:
        identity = UserIdentity(email=email)
        session.add(identity)
        await session.flush()
        await session.commit()
        return identity.id


@pytest.mark.asyncio
async def test_games_list_returns_empty_seats_before_join(
    client: TestClient, _init_db: None
) -> None:
    game_id = _game_id("seats_empty")
    client.post(
        f"/api/v1/games/{game_id}/start",
        json={"players": ["alice", "bob"], "seed": 42},
    )

    response = client.get("/api/v1/games")
    assert response.status_code == 200
    summary = next(g for g in response.json()["games"] if g["game_id"] == game_id)
    # The legacy ``/start`` flow doesn't mint keys — so no seats.
    assert summary["seats"] == []
    assert summary["players"] == ["alice", "bob"]


@pytest.mark.asyncio
async def test_games_list_exposes_seat_user_identity_ids(
    client: TestClient, _init_db: None
) -> None:
    game_id = _game_id("seats_human")
    client.post(
        f"/api/v1/games/{game_id}/start",
        json={"players": ["alice", "bob"], "seed": 42},
    )

    user_id = await _seed_user(f"{game_id}@example.test")
    async with async_session_factory() as session:
        await create_player_key(session, game_id, "alice", user_identity_id=user_id)
        # Bob's seat is left unminted so we can assert that partial rosters
        # don't poison the response — only claimed seats appear.
        await session.commit()

    response = client.get("/api/v1/games")
    assert response.status_code == 200
    summary = next(g for g in response.json()["games"] if g["game_id"] == game_id)
    assert summary["seats"] == [
        {"player_id": "alice", "user_identity_id": user_id},
    ]


@pytest.mark.asyncio
async def test_games_list_marks_mcp_seats_null(
    client: TestClient, _init_db: None
) -> None:
    game_id = _game_id("seats_agents")
    client.post(
        f"/api/v1/games/{game_id}/start",
        json={"players": ["agent_a", "agent_b"], "seed": 42},
    )

    async with async_session_factory() as session:
        await create_player_key(session, game_id, "agent_a")
        await create_player_key(session, game_id, "agent_b")
        await session.commit()

    response = client.get("/api/v1/games")
    assert response.status_code == 200
    summary = next(g for g in response.json()["games"] if g["game_id"] == game_id)
    # Both seats come from MCP-minted keys — the "Agent vs Agent" signal.
    assert len(summary["seats"]) == 2
    for seat in summary["seats"]:
        assert seat["user_identity_id"] is None
    assert {s["player_id"] for s in summary["seats"]} == {"agent_a", "agent_b"}
