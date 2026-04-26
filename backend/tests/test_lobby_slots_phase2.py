"""Phase 2 (lobby + skill split): ``lobby_slots`` consistency tests.

The new ``lobby_slots`` JSON column on ``games`` mirrors the
existing ``players`` roster — every Phase 2 slot is ``type:
"human"``, with ``name`` carrying the seated player's display name
and ``player_api_key_id`` pointing at the slot's active
``PlayerApiKey``. These tests lock in:

* the create / join / leave round-trip keeps ``lobby_slots`` and
  ``players`` in lock-step,
* the legacy fallback (``lobby_slots IS NULL``) still renders as an
  all-Human slot array on ``GET /games/{id}`` so older rows do not
  break the new UI.
"""

from __future__ import annotations

import time

import jwt
import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import delete, update

from backend.src.api.lobby_slots import (
    coerce_slots,
    derive_slots_from_players,
    fill_slot,
    first_empty_slot_index,
)
from backend.src.config import settings
from backend.src.database.connection import async_session_factory, init_db
from backend.src.database.models import (
    Game,
    GameSnapshot,
    GameTurn,
    PlayerApiKey,
    TurnAction,
    TurnSnapshot,
    UserIdentity,
)
from backend.src.database.repository import GameRepository
from backend.src.main import app

ALG = "HS256"


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


async def _purge() -> None:
    async with async_session_factory() as session:
        await session.execute(
            delete(PlayerApiKey).where(PlayerApiKey.game_id.like("slotsp2_%"))
        )
        await session.execute(
            delete(TurnSnapshot).where(TurnSnapshot.game_id.like("slotsp2_%"))
        )
        await session.execute(
            delete(TurnAction).where(TurnAction.game_id.like("slotsp2_%"))
        )
        await session.execute(
            delete(GameSnapshot).where(GameSnapshot.game_id.like("slotsp2_%"))
        )
        await session.execute(
            delete(GameTurn).where(GameTurn.game_id.like("slotsp2_%"))
        )
        await session.execute(delete(Game).where(Game.id.like("slotsp2_%")))
        await session.execute(
            delete(UserIdentity).where(UserIdentity.email.like("%@slotsp2.example.com"))
        )
        await session.commit()


@pytest_asyncio.fixture
async def _clean() -> None:
    await init_db()
    await _purge()
    yield
    await _purge()


def _mint_jwt(user_identity_id: int) -> str:
    now = int(time.time())
    payload = {"sub": str(user_identity_id), "iat": now, "exp": now + 3600}
    return jwt.encode(payload, settings.auth_secret, algorithm=ALG)


async def _seed_identity(email: str) -> int:
    async with async_session_factory() as session:
        repo = GameRepository(session)
        identity = await repo.upsert_user_identity_by_email(email)
        await session.commit()
        return identity.id


def _game_id(suffix: str) -> str:
    return f"slotsp2_{suffix}_{int(time.time() * 1000000)}"


# --- Pure helpers -----------------------------------------------------------


class TestSlotHelpers:
    def test_derive_from_empty_players(self) -> None:
        slots = derive_slots_from_players([], 3)
        assert len(slots) == 3
        assert all(s["type"] == "human" for s in slots)
        assert all(s["name"] is None for s in slots)
        assert [s["slot_index"] for s in slots] == [0, 1, 2]

    def test_derive_partial_roster(self) -> None:
        slots = derive_slots_from_players(["alice"], 3)
        assert slots[0]["name"] == "alice"
        assert slots[1]["name"] is None
        assert slots[2]["name"] is None

    def test_coerce_legacy_null(self) -> None:
        slots = coerce_slots(None, ["alice", "bob"], 3)
        assert [s["name"] for s in slots] == ["alice", "bob", None]
        assert all(s["type"] == "human" for s in slots)

    def test_coerce_existing_passes_through(self) -> None:
        raw = [
            {
                "slot_index": 1,
                "type": "human",
                "name": "bob",
                "reserved_email": None,
                "player_api_key_id": 7,
            },
            {
                "slot_index": 0,
                "type": "human",
                "name": "alice",
                "reserved_email": None,
                "player_api_key_id": 6,
            },
        ]
        slots = coerce_slots(raw, ["alice", "bob"], 2)
        # Sorted by slot_index, full keys filled in.
        assert [s["slot_index"] for s in slots] == [0, 1]
        assert slots[0]["player_api_key_id"] == 6
        assert slots[1]["name"] == "bob"

    def test_first_empty_slot(self) -> None:
        slots = derive_slots_from_players(["alice"], 3)
        assert first_empty_slot_index(slots) == 1
        # Filling 1 leaves 2.
        next_slot = fill_slot(slots, 1, name="bob", player_api_key_id=None)
        assert first_empty_slot_index(next_slot) == 2


# --- End-to-end via REST ---------------------------------------------------


class TestSlotConsistency:
    @pytest.mark.asyncio
    async def test_create_lobby_writes_slot_array(
        self, client: TestClient, _clean: None
    ) -> None:
        uid = await _seed_identity("creator@slotsp2.example.com")
        token = _mint_jwt(uid)
        game_id = _game_id("create")

        resp = client.post(
            f"/api/v1/games?game_id={game_id}",
            json={"player_id": "alice", "player_slots": 3},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        body = resp.json()["game"]

        assert body["players"] == ["alice"]
        slots = body["slots"]
        assert len(slots) == 3
        assert slots[0]["name"] == "alice"
        assert slots[0]["type"] == "human"
        assert slots[0]["player_api_key_id"] is not None
        assert slots[1]["name"] is None
        assert slots[1]["player_api_key_id"] is None
        assert slots[2]["name"] is None

    @pytest.mark.asyncio
    async def test_join_fills_next_open_slot(
        self, client: TestClient, _clean: None
    ) -> None:
        creator_uid = await _seed_identity("c1@slotsp2.example.com")
        creator_token = _mint_jwt(creator_uid)
        game_id = _game_id("join")

        client.post(
            f"/api/v1/games?game_id={game_id}",
            json={"player_id": "alice", "player_slots": 3},
            headers={"Authorization": f"Bearer {creator_token}"},
        )

        bob_uid = await _seed_identity("bob@slotsp2.example.com")
        resp = client.post(
            f"/api/v1/games/{game_id}/join",
            json={"player_id": "bob"},
            headers={"Authorization": f"Bearer {_mint_jwt(bob_uid)}"},
        )
        assert resp.status_code == 200
        slots = resp.json()["game"]["slots"]

        assert slots[0]["name"] == "alice"
        assert slots[1]["name"] == "bob"
        assert slots[1]["player_api_key_id"] is not None
        assert slots[2]["name"] is None

    @pytest.mark.asyncio
    async def test_leave_clears_slot_and_preserves_index(
        self, client: TestClient, _clean: None
    ) -> None:
        creator_uid = await _seed_identity("c2@slotsp2.example.com")
        creator_token = _mint_jwt(creator_uid)
        game_id = _game_id("leave")

        client.post(
            f"/api/v1/games?game_id={game_id}",
            json={"player_id": "alice", "player_slots": 3},
            headers={"Authorization": f"Bearer {creator_token}"},
        )

        bob_uid = await _seed_identity("bob2@slotsp2.example.com")
        join_resp = client.post(
            f"/api/v1/games/{game_id}/join",
            json={"player_id": "bob"},
            headers={"Authorization": f"Bearer {_mint_jwt(bob_uid)}"},
        )
        bob_key = join_resp.json()["api_key"]

        # Bob leaves using his per-game API key.
        leave_resp = client.post(
            f"/api/v1/games/{game_id}/leave",
            headers={"Authorization": f"Bearer {bob_key}"},
        )
        assert leave_resp.status_code == 200
        slots = leave_resp.json()["slots"]

        # Slot 1 still exists but is empty; alice still in slot 0.
        assert len(slots) == 3
        assert slots[0]["name"] == "alice"
        assert slots[1]["name"] is None
        assert slots[1]["player_api_key_id"] is None
        assert slots[1]["slot_index"] == 1

    @pytest.mark.asyncio
    async def test_legacy_null_lobby_slots_renders_as_human_array(
        self, client: TestClient, _clean: None
    ) -> None:
        """Rows that predate Phase 2 (``lobby_slots IS NULL``) should
        still render a slot array — the GET handler synthesises one
        from ``players`` so the frontend never sees a missing field.
        """
        uid = await _seed_identity("legacy@slotsp2.example.com")
        token = _mint_jwt(uid)
        game_id = _game_id("legacy")

        client.post(
            f"/api/v1/games?game_id={game_id}",
            json={"player_id": "alice", "player_slots": 2},
            headers={"Authorization": f"Bearer {token}"},
        )

        # Simulate a pre-Phase-2 row by clearing the column.
        async with async_session_factory() as session:
            await session.execute(
                update(Game).where(Game.id == game_id).values(lobby_slots=None)
            )
            await session.commit()

        resp = client.get(f"/api/v1/games/{game_id}")
        assert resp.status_code == 200
        slots = resp.json()["slots"]
        assert len(slots) == 2
        assert slots[0]["type"] == "human"
        assert slots[0]["name"] == "alice"
        assert slots[1]["name"] is None
