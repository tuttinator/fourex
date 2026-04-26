"""Phase 3 (lobby + skill split): Agent slots + per-slot keys.

Phase 3 introduces Agent slots at create time, the per-slot
plaintext-key visibility window, the regenerate-key endpoint, the
all-Agent (owner-only) creator path, and the start-game guard that
treats every slot uniformly. These tests exercise:

* create with mixed Human / Agent slots, including key plaintexts on
  the response,
* the all-Agent (creator unticks "I'll take a slot") create + start
  flow via the JWT-authenticated owner endpoint,
* validation on the slot config (count mismatch, missing Agent name,
  duplicate Agent names, creator name colliding with an Agent name,
  creator_seated=true but no Human slot bears the creator's name),
* regenerate-key — minted key visible, previous key invalidated,
  creator-only / waiting-only / Agent-only,
* the visibility window — per-slot ``plaintext_key`` is gone for
  non-creators and the moment the game flips to ``active``,
* the start guard rejects half-empty / un-keyed lobbies.
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
            delete(PlayerApiKey).where(PlayerApiKey.game_id.like("slotsp3_%"))
        )
        await session.execute(
            delete(TurnSnapshot).where(TurnSnapshot.game_id.like("slotsp3_%"))
        )
        await session.execute(
            delete(TurnAction).where(TurnAction.game_id.like("slotsp3_%"))
        )
        await session.execute(
            delete(GameSnapshot).where(GameSnapshot.game_id.like("slotsp3_%"))
        )
        await session.execute(
            delete(GameTurn).where(GameTurn.game_id.like("slotsp3_%"))
        )
        await session.execute(delete(Game).where(Game.id.like("slotsp3_%")))
        await session.execute(
            delete(UserIdentity).where(
                UserIdentity.email.like("%@slotsp3.example.com")
            )
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
    return f"slotsp3_{suffix}_{int(time.time() * 1000000)}"


class TestCreateMixedSlots:
    """End-to-end: create a lobby with a mix of Human and Agent slots."""

    @pytest.mark.asyncio
    async def test_create_seated_creator_with_one_agent(
        self, client: TestClient, _clean: None
    ) -> None:
        uid = await _seed_identity("mixed@slotsp3.example.com")
        token = _mint_jwt(uid)
        game_id = _game_id("mixed_seated")

        resp = client.post(
            f"/api/v1/games?game_id={game_id}",
            json={
                "player_id": "alice",
                "player_slots": 2,
                "creator_seated": True,
                "slots": [
                    {"type": "human", "name": "alice"},
                    {"type": "agent", "name": "bot1"},
                ],
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["api_key"] is not None and body["api_key"].startswith("fx_")

        slots = body["game"]["slots"]
        assert len(slots) == 2
        assert slots[0]["type"] == "human"
        assert slots[0]["name"] == "alice"
        assert slots[0]["plaintext_key"] is None
        assert slots[1]["type"] == "agent"
        assert slots[1]["name"] == "bot1"
        assert slots[1]["plaintext_key"] is not None
        assert slots[1]["plaintext_key"].startswith("fx_")
        assert slots[1]["player_api_key_id"] is not None

        # Bot1 is in the players roster so the engine treats it as a real seat.
        assert "alice" in body["game"]["players"]
        assert "bot1" in body["game"]["players"]


class TestAllAgentFlow:
    """The owner unticks 'I'll take a slot' and runs an all-Agent table."""

    @pytest.mark.asyncio
    async def test_create_all_agent_returns_no_creator_key(
        self, client: TestClient, _clean: None
    ) -> None:
        uid = await _seed_identity("owner@slotsp3.example.com")
        token = _mint_jwt(uid)
        game_id = _game_id("all_agent")

        resp = client.post(
            f"/api/v1/games?game_id={game_id}",
            json={
                "player_id": "owner",
                "player_slots": 2,
                "creator_seated": False,
                "slots": [
                    {"type": "agent", "name": "bot_a"},
                    {"type": "agent", "name": "bot_b"},
                ],
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        # No per-game key for the creator — they aren't in players.
        assert body["api_key"] is None
        assert body["game"]["creator"] is None
        assert sorted(body["game"]["players"]) == ["bot_a", "bot_b"]
        slots = body["game"]["slots"]
        assert all(s["type"] == "agent" for s in slots)
        assert all(s["plaintext_key"] for s in slots)

    @pytest.mark.asyncio
    async def test_owner_starts_via_jwt(
        self, client: TestClient, _clean: None
    ) -> None:
        uid = await _seed_identity("owner-start@slotsp3.example.com")
        token = _mint_jwt(uid)
        game_id = _game_id("owner_start")

        client.post(
            f"/api/v1/games?game_id={game_id}",
            json={
                "player_id": "owner",
                "player_slots": 2,
                "creator_seated": False,
                "slots": [
                    {"type": "agent", "name": "alpha"},
                    {"type": "agent", "name": "beta"},
                ],
            },
            headers={"Authorization": f"Bearer {token}"},
        )

        # The JWT-authenticated owner endpoint accepts the start.
        resp = client.post(
            f"/api/v1/games/{game_id}/start-as-owner",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "game_started"

        # Game flipped to active and the per-slot keys are gone.
        detail = client.get(f"/api/v1/games/{game_id}").json()
        assert detail["status"] == "active"
        for slot in detail["slots"]:
            assert slot["plaintext_key"] is None

    @pytest.mark.asyncio
    async def test_non_owner_cannot_start_as_owner(
        self, client: TestClient, _clean: None
    ) -> None:
        owner_uid = await _seed_identity("owner-x@slotsp3.example.com")
        owner_token = _mint_jwt(owner_uid)
        game_id = _game_id("owner_x")

        client.post(
            f"/api/v1/games?game_id={game_id}",
            json={
                "player_id": "owner",
                "player_slots": 2,
                "creator_seated": False,
                "slots": [
                    {"type": "agent", "name": "alpha"},
                    {"type": "agent", "name": "beta"},
                ],
            },
            headers={"Authorization": f"Bearer {owner_token}"},
        )

        intruder_uid = await _seed_identity("intruder@slotsp3.example.com")
        intruder_token = _mint_jwt(intruder_uid)
        resp = client.post(
            f"/api/v1/games/{game_id}/start-as-owner",
            headers={"Authorization": f"Bearer {intruder_token}"},
        )
        assert resp.status_code == 403


class TestSlotValidation:
    @pytest.mark.asyncio
    async def test_count_mismatch_rejected(
        self, client: TestClient, _clean: None
    ) -> None:
        uid = await _seed_identity("v1@slotsp3.example.com")
        resp = client.post(
            f"/api/v1/games?game_id={_game_id('count')}",
            json={
                "player_id": "alice",
                "player_slots": 3,
                "creator_seated": True,
                "slots": [
                    {"type": "human", "name": "alice"},
                    {"type": "agent", "name": "bot"},
                ],
            },
            headers={"Authorization": f"Bearer {_mint_jwt(uid)}"},
        )
        assert resp.status_code == 400
        assert "player_slots" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_agent_name_missing_rejected(
        self, client: TestClient, _clean: None
    ) -> None:
        uid = await _seed_identity("v2@slotsp3.example.com")
        resp = client.post(
            f"/api/v1/games?game_id={_game_id('noname')}",
            json={
                "player_id": "alice",
                "player_slots": 2,
                "creator_seated": True,
                "slots": [
                    {"type": "human", "name": "alice"},
                    {"type": "agent"},
                ],
            },
            headers={"Authorization": f"Bearer {_mint_jwt(uid)}"},
        )
        assert resp.status_code == 400
        assert "Agent slot" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_duplicate_agent_names_rejected(
        self, client: TestClient, _clean: None
    ) -> None:
        uid = await _seed_identity("v3@slotsp3.example.com")
        resp = client.post(
            f"/api/v1/games?game_id={_game_id('dup')}",
            json={
                "player_id": "alice",
                "player_slots": 2,
                "creator_seated": False,
                "slots": [
                    {"type": "agent", "name": "twin"},
                    {"type": "agent", "name": "twin"},
                ],
            },
            headers={"Authorization": f"Bearer {_mint_jwt(uid)}"},
        )
        assert resp.status_code == 400
        assert "duplicated" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_creator_seated_but_no_matching_human_slot_rejected(
        self, client: TestClient, _clean: None
    ) -> None:
        uid = await _seed_identity("v4@slotsp3.example.com")
        resp = client.post(
            f"/api/v1/games?game_id={_game_id('nocreator')}",
            json={
                "player_id": "alice",
                "player_slots": 2,
                "creator_seated": True,
                "slots": [
                    {"type": "human"},  # no name
                    {"type": "agent", "name": "bot"},
                ],
            },
            headers={"Authorization": f"Bearer {_mint_jwt(uid)}"},
        )
        assert resp.status_code == 400
        assert "alice" in resp.json()["detail"]


class TestRegenerateKey:
    @pytest.mark.asyncio
    async def test_regenerate_invalidates_previous(
        self, client: TestClient, _clean: None
    ) -> None:
        uid = await _seed_identity("regen@slotsp3.example.com")
        token = _mint_jwt(uid)
        game_id = _game_id("regen")

        create = client.post(
            f"/api/v1/games?game_id={game_id}",
            json={
                "player_id": "alice",
                "player_slots": 2,
                "creator_seated": True,
                "slots": [
                    {"type": "human", "name": "alice"},
                    {"type": "agent", "name": "bot"},
                ],
            },
            headers={"Authorization": f"Bearer {token}"},
        ).json()
        old_key = create["game"]["slots"][1]["plaintext_key"]

        # Old key authenticates the gameplay endpoint. ``/turn-submissions``
        # uses ``require_api_key`` so it strictly enforces the key (unlike
        # ``/state`` which falls back to god-mode for unauthenticated
        # callers).
        ok = client.get(
            f"/api/v1/games/{game_id}/turn-submissions",
            headers={"Authorization": f"Bearer {old_key}"},
        )
        assert ok.status_code == 200

        # Regenerate via the creator's seated per-game key.
        creator_key = create["api_key"]
        regen = client.post(
            f"/api/v1/games/{game_id}/slots/1/regenerate-key",
            headers={"Authorization": f"Bearer {creator_key}"},
        )
        assert regen.status_code == 200
        new_key = regen.json()["plaintext_key"]
        assert new_key.startswith("fx_")
        assert new_key != old_key

        # Old key no longer works.
        gone = client.get(
            f"/api/v1/games/{game_id}/turn-submissions",
            headers={"Authorization": f"Bearer {old_key}"},
        )
        assert gone.status_code == 401

        # New key works.
        ok2 = client.get(
            f"/api/v1/games/{game_id}/turn-submissions",
            headers={"Authorization": f"Bearer {new_key}"},
        )
        assert ok2.status_code == 200

    @pytest.mark.asyncio
    async def test_regenerate_human_slot_rejected(
        self, client: TestClient, _clean: None
    ) -> None:
        uid = await _seed_identity("regen-h@slotsp3.example.com")
        token = _mint_jwt(uid)
        game_id = _game_id("regen_human")

        create = client.post(
            f"/api/v1/games?game_id={game_id}",
            json={
                "player_id": "alice",
                "player_slots": 2,
                "creator_seated": True,
                "slots": [
                    {"type": "human", "name": "alice"},
                    {"type": "agent", "name": "bot"},
                ],
            },
            headers={"Authorization": f"Bearer {token}"},
        ).json()
        creator_key = create["api_key"]

        resp = client.post(
            f"/api/v1/games/{game_id}/slots/0/regenerate-key",
            headers={"Authorization": f"Bearer {creator_key}"},
        )
        assert resp.status_code == 400
        assert "Agent" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_regenerate_non_creator_rejected(
        self, client: TestClient, _clean: None
    ) -> None:
        creator_uid = await _seed_identity("regen-c@slotsp3.example.com")
        creator_token = _mint_jwt(creator_uid)
        game_id = _game_id("regen_perms")

        client.post(
            f"/api/v1/games?game_id={game_id}",
            json={
                "player_id": "alice",
                "player_slots": 2,
                "creator_seated": True,
                "slots": [
                    {"type": "human", "name": "alice"},
                    {"type": "agent", "name": "bot"},
                ],
            },
            headers={"Authorization": f"Bearer {creator_token}"},
        )

        intruder_uid = await _seed_identity("intruder2@slotsp3.example.com")
        intruder_token = _mint_jwt(intruder_uid)
        resp = client.post(
            f"/api/v1/games/{game_id}/slots/1/regenerate-key",
            headers={"Authorization": f"Bearer {intruder_token}"},
        )
        assert resp.status_code == 403


class TestKeyVisibility:
    @pytest.mark.asyncio
    async def test_creator_sees_per_slot_keys_while_waiting(
        self, client: TestClient, _clean: None
    ) -> None:
        uid = await _seed_identity("vis-c@slotsp3.example.com")
        token = _mint_jwt(uid)
        game_id = _game_id("vis_creator")

        create = client.post(
            f"/api/v1/games?game_id={game_id}",
            json={
                "player_id": "alice",
                "player_slots": 2,
                "creator_seated": True,
                "slots": [
                    {"type": "human", "name": "alice"},
                    {"type": "agent", "name": "bot"},
                ],
            },
            headers={"Authorization": f"Bearer {token}"},
        ).json()
        creator_key = create["api_key"]

        # Creator (per-game key) sees the agent slot's plaintext.
        resp = client.get(
            f"/api/v1/games/{game_id}",
            headers={"Authorization": f"Bearer {creator_key}"},
        )
        assert resp.status_code == 200
        assert resp.json()["slots"][1]["plaintext_key"] is not None

        # Creator (JWT, no per-game key) ALSO sees the plaintext —
        # this is the all-Agent owner path, but here we just verify
        # the JWT branch works for any creator.
        resp_jwt = client.get(
            f"/api/v1/games/{game_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp_jwt.status_code == 200
        assert resp_jwt.json()["slots"][1]["plaintext_key"] is not None

    @pytest.mark.asyncio
    async def test_non_creator_does_not_see_per_slot_keys(
        self, client: TestClient, _clean: None
    ) -> None:
        creator_uid = await _seed_identity("vis-nc@slotsp3.example.com")
        creator_token = _mint_jwt(creator_uid)
        game_id = _game_id("vis_nc")

        client.post(
            f"/api/v1/games?game_id={game_id}",
            json={
                "player_id": "alice",
                "player_slots": 2,
                "creator_seated": True,
                "slots": [
                    {"type": "human", "name": "alice"},
                    {"type": "agent", "name": "bot"},
                ],
            },
            headers={"Authorization": f"Bearer {creator_token}"},
        )

        # Anonymous viewer.
        resp = client.get(f"/api/v1/games/{game_id}")
        assert resp.status_code == 200
        for slot in resp.json()["slots"]:
            assert slot["plaintext_key"] is None

        # Different signed-in user.
        other_uid = await _seed_identity("other@slotsp3.example.com")
        other_token = _mint_jwt(other_uid)
        resp_other = client.get(
            f"/api/v1/games/{game_id}",
            headers={"Authorization": f"Bearer {other_token}"},
        )
        assert resp_other.status_code == 200
        for slot in resp_other.json()["slots"]:
            assert slot["plaintext_key"] is None

    @pytest.mark.asyncio
    async def test_keys_disappear_when_active(
        self, client: TestClient, _clean: None
    ) -> None:
        uid = await _seed_identity("vis-active@slotsp3.example.com")
        token = _mint_jwt(uid)
        game_id = _game_id("vis_active")

        create = client.post(
            f"/api/v1/games?game_id={game_id}",
            json={
                "player_id": "alice",
                "player_slots": 2,
                "creator_seated": True,
                "slots": [
                    {"type": "human", "name": "alice"},
                    {"type": "agent", "name": "bot"},
                ],
            },
            headers={"Authorization": f"Bearer {token}"},
        ).json()
        creator_key = create["api_key"]

        client.post(
            f"/api/v1/games/{game_id}/start",
            headers={"Authorization": f"Bearer {creator_key}"},
        )

        resp = client.get(
            f"/api/v1/games/{game_id}",
            headers={"Authorization": f"Bearer {creator_key}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "active"
        for slot in body["slots"]:
            assert slot["plaintext_key"] is None


class TestStartGuard:
    @pytest.mark.asyncio
    async def test_start_blocked_with_open_human_slot(
        self, client: TestClient, _clean: None
    ) -> None:
        uid = await _seed_identity("guard@slotsp3.example.com")
        token = _mint_jwt(uid)
        game_id = _game_id("guard_human")

        create = client.post(
            f"/api/v1/games?game_id={game_id}",
            json={
                "player_id": "alice",
                "player_slots": 3,
                "creator_seated": True,
                "slots": [
                    {"type": "human", "name": "alice"},
                    {"type": "agent", "name": "bot"},
                    {"type": "human"},  # open
                ],
            },
            headers={"Authorization": f"Bearer {token}"},
        ).json()
        creator_key = create["api_key"]

        resp = client.post(
            f"/api/v1/games/{game_id}/start",
            headers={"Authorization": f"Bearer {creator_key}"},
        )
        assert resp.status_code == 400
        assert "All slots" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_start_succeeds_when_all_slots_filled(
        self, client: TestClient, _clean: None
    ) -> None:
        uid = await _seed_identity("guard-ok@slotsp3.example.com")
        token = _mint_jwt(uid)
        game_id = _game_id("guard_ok")

        create = client.post(
            f"/api/v1/games?game_id={game_id}",
            json={
                "player_id": "alice",
                "player_slots": 2,
                "creator_seated": True,
                "slots": [
                    {"type": "human", "name": "alice"},
                    {"type": "agent", "name": "bot"},
                ],
            },
            headers={"Authorization": f"Bearer {token}"},
        ).json()
        creator_key = create["api_key"]

        resp = client.post(
            f"/api/v1/games/{game_id}/start",
            headers={"Authorization": f"Bearer {creator_key}"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "game_started"
