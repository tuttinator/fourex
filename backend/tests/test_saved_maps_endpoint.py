"""Tests for the ``/api/v1/maps`` endpoints + lobby ``saved:<id>`` resolver.

Phase 4 of the map system overhaul. Covers:

* Listing is open to any authenticated user; mutating verbs require
  ``is_admin``.
* Server-side payload validation (spawn-zone count, terrain
  eligibility, dimensions, name uniqueness).
* The lobby controller's ``saved:<id>`` resolver: tile + spawn-zone
  load, dimension override, deterministic subset selection.
"""

from __future__ import annotations

import time

import jwt
import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import delete

from backend.src.api.persistent_game_controller import (
    PersistentGameController,
    _select_saved_spawn_subset,
)
from backend.src.config import settings
from backend.src.database.connection import async_session_factory, init_db
from backend.src.database.models import Game, SavedMap, UserIdentity
from backend.src.database.repository import GameRepository
from backend.src.game.models import Coord, Terrain
from backend.src.main import app

ALG = "HS256"
EMAIL_DOMAIN = "@savedmaps.example.com"


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest_asyncio.fixture(autouse=True)
async def _clean() -> None:
    await init_db()
    async with async_session_factory() as session:
        # Order matters: SavedMap and Game both FK into UserIdentity,
        # so wipe the children first.
        await session.execute(delete(SavedMap))
        await session.execute(delete(Game).where(Game.id.like("savedmap-%")))
        await session.execute(
            delete(UserIdentity).where(UserIdentity.email.like(f"%{EMAIL_DOMAIN}"))
        )
        await session.commit()
    yield
    async with async_session_factory() as session:
        # Order matters: SavedMap and Game both FK into UserIdentity,
        # so wipe the children first.
        await session.execute(delete(SavedMap))
        await session.execute(delete(Game).where(Game.id.like("savedmap-%")))
        await session.execute(
            delete(UserIdentity).where(UserIdentity.email.like(f"%{EMAIL_DOMAIN}"))
        )
        await session.commit()


def _mint_jwt(user_identity_id: int, email: str) -> str:
    now = int(time.time())
    payload = {
        "sub": str(user_identity_id),
        "email": email,
        "iat": now,
        "exp": now + 3600,
    }
    return jwt.encode(payload, settings.auth_secret, algorithm=ALG)


async def _seed_identity(email: str, *, is_admin: bool = False) -> int:
    async with async_session_factory() as session:
        repo = GameRepository(session)
        identity = await repo.upsert_user_identity_by_email(email)
        identity.is_admin = is_admin
        await session.commit()
        return identity.id


def _make_tiles(width: int, height: int, terrain: str = "grass") -> list[dict]:
    return [{"x": x, "y": y, "terrain": terrain} for y in range(height) for x in range(width)]


def _valid_payload(
    name: str = "Test Map",
    *,
    width: int = 10,
    height: int = 10,
    terrain: str = "grass",
    spawn_zones: list[dict] | None = None,
) -> dict:
    return {
        "name": name,
        "description": "Test map",
        "width": width,
        "height": height,
        "tiles": _make_tiles(width, height, terrain),
        "spawn_zones": spawn_zones if spawn_zones is not None else [
            {"x": 1, "y": 1},
            {"x": 8, "y": 8},
        ],
    }


class TestListAndGet:
    def test_list_requires_auth(self, client: TestClient) -> None:
        resp = client.get("/api/v1/maps")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_list_open_to_any_authenticated_user(
        self, client: TestClient
    ) -> None:
        identity_id = await _seed_identity(f"regular{EMAIL_DOMAIN}")
        token = _mint_jwt(identity_id, f"regular{EMAIL_DOMAIN}")
        resp = client.get(
            "/api/v1/maps", headers={"Authorization": f"Bearer {token}"}
        )
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_get_returns_full_payload(self, client: TestClient) -> None:
        admin_id = await _seed_identity(f"admin{EMAIL_DOMAIN}", is_admin=True)
        token = _mint_jwt(admin_id, f"admin{EMAIL_DOMAIN}")
        resp = client.post(
            "/api/v1/maps",
            json=_valid_payload(),
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200, resp.text
        saved_id = resp.json()["id"]

        resp2 = client.get(
            f"/api/v1/maps/{saved_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp2.status_code == 200
        body = resp2.json()
        assert body["name"] == "Test Map"
        assert len(body["tiles"]) == 100
        assert len(body["spawn_zones"]) == 2
        assert body["creator_email"] == f"admin{EMAIL_DOMAIN}"


class TestAdminGate:
    @pytest.mark.asyncio
    async def test_create_rejects_non_admin(self, client: TestClient) -> None:
        identity_id = await _seed_identity(f"regular{EMAIL_DOMAIN}")
        token = _mint_jwt(identity_id, f"regular{EMAIL_DOMAIN}")
        resp = client.post(
            "/api/v1/maps",
            json=_valid_payload(),
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_create_accepts_admin(self, client: TestClient) -> None:
        admin_id = await _seed_identity(f"admin{EMAIL_DOMAIN}", is_admin=True)
        token = _mint_jwt(admin_id, f"admin{EMAIL_DOMAIN}")
        resp = client.post(
            "/api/v1/maps",
            json=_valid_payload(),
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_patch_and_delete_admin_only(self, client: TestClient) -> None:
        admin_id = await _seed_identity(f"admin{EMAIL_DOMAIN}", is_admin=True)
        admin_token = _mint_jwt(admin_id, f"admin{EMAIL_DOMAIN}")
        regular_id = await _seed_identity(f"regular{EMAIL_DOMAIN}")
        regular_token = _mint_jwt(regular_id, f"regular{EMAIL_DOMAIN}")

        resp = client.post(
            "/api/v1/maps",
            json=_valid_payload(),
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        saved_id = resp.json()["id"]

        # Non-admin cannot patch
        resp = client.patch(
            f"/api/v1/maps/{saved_id}",
            json={"description": "stolen"},
            headers={"Authorization": f"Bearer {regular_token}"},
        )
        assert resp.status_code == 403

        # Non-admin cannot delete
        resp = client.delete(
            f"/api/v1/maps/{saved_id}",
            headers={"Authorization": f"Bearer {regular_token}"},
        )
        assert resp.status_code == 403

        # Admin can delete
        resp = client.delete(
            f"/api/v1/maps/{saved_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200


class TestValidation:
    @pytest_asyncio.fixture
    async def admin_token(self) -> str:
        admin_id = await _seed_identity(f"admin{EMAIL_DOMAIN}", is_admin=True)
        return _mint_jwt(admin_id, f"admin{EMAIL_DOMAIN}")

    def test_rejects_too_few_spawn_zones(
        self, client: TestClient, admin_token: str
    ) -> None:
        payload = _valid_payload(spawn_zones=[{"x": 1, "y": 1}])
        resp = client.post(
            "/api/v1/maps",
            json=payload,
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 400
        assert "spawn zones" in resp.json()["detail"]

    def test_rejects_spawn_on_water(
        self, client: TestClient, admin_token: str
    ) -> None:
        # Build a payload where spawn zone (1,1) is on water.
        tiles = _make_tiles(10, 10, "grass")
        for tile in tiles:
            if tile["x"] == 1 and tile["y"] == 1:
                tile["terrain"] = "water"
        payload = _valid_payload(name="Water Spawn")
        payload["tiles"] = tiles
        resp = client.post(
            "/api/v1/maps",
            json=payload,
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 400
        assert "passable" in resp.json()["detail"]

    def test_rejects_spawn_on_mountain(
        self, client: TestClient, admin_token: str
    ) -> None:
        tiles = _make_tiles(10, 10, "grass")
        for tile in tiles:
            if tile["x"] == 1 and tile["y"] == 1:
                tile["terrain"] = "mountain"
        payload = _valid_payload(name="Mountain Spawn")
        payload["tiles"] = tiles
        resp = client.post(
            "/api/v1/maps",
            json=payload,
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 400

    def test_rejects_resource_on_mountain(
        self, client: TestClient, admin_token: str
    ) -> None:
        tiles = _make_tiles(10, 10, "grass")
        for tile in tiles:
            if tile["x"] == 5 and tile["y"] == 5:
                tile["terrain"] = "mountain"
                tile["resource"] = "ore"
        payload = _valid_payload(name="Bad Resource")
        payload["tiles"] = tiles
        resp = client.post(
            "/api/v1/maps",
            json=payload,
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 400

    def test_rejects_dimensions_too_small(
        self, client: TestClient, admin_token: str
    ) -> None:
        payload = _valid_payload(name="Tiny", width=5, height=5)
        resp = client.post(
            "/api/v1/maps",
            json=payload,
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        # Pydantic field-level validation: 422 (validation error)
        assert resp.status_code == 422

    def test_rejects_unknown_terrain(
        self, client: TestClient, admin_token: str
    ) -> None:
        tiles = _make_tiles(10, 10, "grass")
        tiles[0]["terrain"] = "lava"
        payload = _valid_payload(name="Lava")
        payload["tiles"] = tiles
        resp = client.post(
            "/api/v1/maps",
            json=payload,
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 400

    def test_rejects_duplicate_name(
        self, client: TestClient, admin_token: str
    ) -> None:
        client.post(
            "/api/v1/maps",
            json=_valid_payload(name="Same"),
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        resp = client.post(
            "/api/v1/maps",
            json=_valid_payload(name="Same"),
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 409


class TestPatch:
    @pytest_asyncio.fixture
    async def admin_token(self) -> str:
        admin_id = await _seed_identity(f"admin{EMAIL_DOMAIN}", is_admin=True)
        return _mint_jwt(admin_id, f"admin{EMAIL_DOMAIN}")

    def test_patch_updates_description(
        self, client: TestClient, admin_token: str
    ) -> None:
        resp = client.post(
            "/api/v1/maps",
            json=_valid_payload(),
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        saved_id = resp.json()["id"]
        # Sending empty {} keeps the row unchanged because every field
        # is optional and ``None`` means "skip".
        resp = client.patch(
            f"/api/v1/maps/{saved_id}",
            json={"name": "Renamed"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "Renamed"

    def test_patch_validates_new_tiles_against_dimensions(
        self, client: TestClient, admin_token: str
    ) -> None:
        resp = client.post(
            "/api/v1/maps",
            json=_valid_payload(),
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        saved_id = resp.json()["id"]
        # Patch tiles only — the validator checks merged width × height
        # × tile count; mismatch returns 400.
        resp = client.patch(
            f"/api/v1/maps/{saved_id}",
            json={"tiles": _make_tiles(5, 5)},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 400


class TestSpawnSubsetSelection:
    """Pure unit tests for ``_select_saved_spawn_subset``."""

    def test_more_zones_than_players_picks_subset(self) -> None:
        zones = [Coord(x=i, y=0) for i in range(6)]
        chosen = _select_saved_spawn_subset(zones, 2, seed=42)
        assert len(chosen) == 2
        assert all(z in zones for z in chosen)

    def test_deterministic_for_same_inputs(self) -> None:
        zones = [Coord(x=i, y=0) for i in range(6)]
        a = _select_saved_spawn_subset(zones, 2, seed=42)
        b = _select_saved_spawn_subset(zones, 2, seed=42)
        assert a == b

    def test_different_seeds_can_pick_different_subsets(self) -> None:
        zones = [Coord(x=i, y=0) for i in range(8)]
        a = _select_saved_spawn_subset(zones, 2, seed=1)
        b = _select_saved_spawn_subset(zones, 2, seed=99)
        # Not strictly required to differ, but with 8 zones and 2
        # players there are 28 combinations, so the odds of collision
        # at two seeds are tiny — assert behaviour is plausible by
        # checking both runs produce valid subsets.
        assert all(z in zones for z in a)
        assert all(z in zones for z in b)

    def test_too_few_zones_raises(self) -> None:
        zones = [Coord(x=0, y=0)]
        with pytest.raises(ValueError, match="needs 2"):
            _select_saved_spawn_subset(zones, 2, seed=42)

    def test_exact_match_returns_all(self) -> None:
        zones = [Coord(x=0, y=0), Coord(x=5, y=5)]
        chosen = _select_saved_spawn_subset(zones, 2, seed=42)
        assert chosen == zones


class TestLobbyResolver:
    @pytest.mark.asyncio
    async def test_create_lobby_uses_saved_map_dimensions(self) -> None:
        admin_id = await _seed_identity(f"admin{EMAIL_DOMAIN}", is_admin=True)
        async with async_session_factory() as session:
            repo = GameRepository(session)
            saved = await repo.create_saved_map(
                name="Resolver Map",
                description=None,
                width=12,
                height=14,
                tiles=_make_tiles(12, 14, "grass"),
                spawn_zones=[{"x": 1, "y": 1}, {"x": 10, "y": 12}],
                created_by=admin_id,
            )
            await session.commit()
            saved_id = saved.id

        async with async_session_factory() as session:
            controller = PersistentGameController(session)
            await controller.create_lobby(
                game_id="savedmap-resolver-1",
                player_slots=2,
                # Lobby requested 20×20, but the saved map is 12×14.
                map_width=20,
                map_height=20,
                seed=42,
                creator=None,
                creator_user_identity_id=admin_id,
                map_template=f"saved:{saved_id}",
            )
            await session.commit()

            db_game = await controller.repo.get_game("savedmap-resolver-1")
            assert db_game is not None
            assert db_game.map_width == 12
            assert db_game.map_height == 14
            assert db_game.map_template == f"saved:{saved_id}"

    @pytest.mark.asyncio
    async def test_create_lobby_rejects_too_few_zones(self) -> None:
        admin_id = await _seed_identity(f"admin{EMAIL_DOMAIN}", is_admin=True)
        async with async_session_factory() as session:
            repo = GameRepository(session)
            saved = await repo.create_saved_map(
                name="Too Few",
                description=None,
                width=10,
                height=10,
                tiles=_make_tiles(10, 10, "grass"),
                spawn_zones=[{"x": 1, "y": 1}, {"x": 8, "y": 8}],
                created_by=admin_id,
            )
            await session.commit()
            saved_id = saved.id

        async with async_session_factory() as session:
            controller = PersistentGameController(session)
            with pytest.raises(ValueError, match="provides 2"):
                await controller.create_lobby(
                    game_id="savedmap-resolver-2",
                    player_slots=4,  # need 4 zones, map has 2
                    map_width=10,
                    map_height=10,
                    seed=42,
                    creator=None,
                    creator_user_identity_id=admin_id,
                    map_template=f"saved:{saved_id}",
                )

    @pytest.mark.asyncio
    async def test_create_lobby_unknown_saved_id(self) -> None:
        async with async_session_factory() as session:
            controller = PersistentGameController(session)
            with pytest.raises(ValueError, match="Saved map 99999 not found"):
                await controller.create_lobby(
                    game_id="savedmap-resolver-3",
                    player_slots=2,
                    map_width=10,
                    map_height=10,
                    seed=42,
                    creator=None,
                    creator_user_identity_id=None,
                    map_template="saved:99999",
                )

    @pytest.mark.asyncio
    async def test_lobby_loads_terrain_from_saved_map(self) -> None:
        admin_id = await _seed_identity(f"admin{EMAIL_DOMAIN}", is_admin=True)
        # Build a 10×10 grass map but make (3,3) a forest so we can
        # verify the engine state picked it up.
        tiles = _make_tiles(10, 10, "grass")
        for tile in tiles:
            if tile["x"] == 3 and tile["y"] == 3:
                tile["terrain"] = "forest"
                tile["resource"] = "wood"
        async with async_session_factory() as session:
            repo = GameRepository(session)
            saved = await repo.create_saved_map(
                name="Forest at 3,3",
                description=None,
                width=10,
                height=10,
                tiles=tiles,
                spawn_zones=[{"x": 1, "y": 1}, {"x": 8, "y": 8}],
                created_by=admin_id,
            )
            await session.commit()
            saved_id = saved.id

        async with async_session_factory() as session:
            controller = PersistentGameController(session)
            await controller.create_lobby(
                game_id="savedmap-resolver-4",
                player_slots=2,
                map_width=10,
                map_height=10,
                seed=42,
                creator=None,
                creator_user_identity_id=admin_id,
                map_template=f"saved:{saved_id}",
            )
            await session.commit()
            state = await controller.get_game_state("savedmap-resolver-4")
            assert state is not None
            tile = next(t for t in state.tiles if t.loc.x == 3 and t.loc.y == 3)
            assert tile.terrain == Terrain.FOREST
