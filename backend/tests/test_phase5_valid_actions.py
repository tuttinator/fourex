"""Tests for Phase 5 (backend) valid-action helpers and REST endpoints.

Covers the five new surfaces the Phase 5 frontend action queue will
consume:

- ``get_valid_attacks`` / ``GET .../valid-attacks``
- ``can_found_city_here`` / ``GET .../can-found-city``
- ``get_valid_improvements`` / ``GET .../valid-improvements``
- ``get_trainable_units`` / ``GET .../trainable-units``
- ``get_buildable_buildings`` / ``GET .../buildable-buildings``

The pure-function tests verify the helper contracts against a
hand-constructed ``GameState``. The REST tests mirror the Phase 4
``test_gameplay_tracer.py`` pattern: missing/wrong-game key reject
with 401/403, enemy units/cities 404 (not 403) so IDs can't be
enumerated through the oracle, and fog-of-war filtering is enforced.
"""

from __future__ import annotations

import time

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import delete

from backend.src.api.persistent_game_controller import (
    get_persistent_game_controller,
)
from backend.src.api.websocket import manager
from backend.src.auth import create_player_key
from backend.src.database.connection import async_session_factory, init_db
from backend.src.database.models import (
    Game,
    GameSnapshot,
    GameTurn,
    PlayerAction,
    PlayerApiKey,
    TurnAction,
    TurnSnapshot,
)
from backend.src.game.models import (
    BUILDING_STATS,
    UNIT_STATS,
    BuildingType,
    City,
    Coord,
    DiplomaticState,
    GameState,
    ImprovementType,
    Resource,
    ResourceBag,
    Terrain,
    Tile,
    Unit,
    UnitType,
)
from backend.src.game.rules import (
    can_found_city_here,
    get_buildable_buildings,
    get_trainable_units,
    get_valid_attacks,
    get_valid_improvements,
)
from backend.src.main import app

_GAME_PREFIX = "phase5"


# ---------------------------------------------------------------------------
# Helpers for pure-function tests (hand-built GameState)
# ---------------------------------------------------------------------------


def _make_state(width: int = 5, height: int = 5, *, players: tuple[str, ...] = ("p1",)) -> GameState:
    state = GameState(map_width=width, map_height=height)
    tile_id = 0
    for y in range(height):
        for x in range(width):
            state.tiles.append(
                Tile(id=tile_id, loc=Coord(x=x, y=y), terrain=Terrain.PLAINS)
            )
            tile_id += 1
    for p in players:
        state.players.append(p)
        state.stockpiles[p] = ResourceBag(food=100, wood=100, ore=100, crystal=100)
    return state


def _set_tile(
    state: GameState,
    x: int,
    y: int,
    *,
    terrain: Terrain | None = None,
    resource: Resource | None = None,
    improvement: ImprovementType | None = None,
) -> None:
    tile = state.get_tile(Coord(x=x, y=y))
    assert tile is not None
    if terrain is not None:
        tile.terrain = terrain
    if resource is not None:
        tile.resource = resource
    if improvement is not None:
        tile.improvement = improvement


def _add_unit(
    state: GameState,
    unit_type: UnitType,
    x: int,
    y: int,
    owner: str = "p1",
) -> Unit:
    stats = UNIT_STATS[unit_type]
    unit = Unit(
        id=state.next_unit_id,
        owner=owner,
        type=unit_type,
        hp=stats.hp,
        moves_left=stats.moves,
        loc=Coord(x=x, y=y),
    )
    state.units[unit.id] = unit
    state.next_unit_id += 1
    tile = state.get_tile(Coord(x=x, y=y))
    assert tile is not None
    tile.unit_id = unit.id
    return unit


def _add_city(state: GameState, x: int, y: int, owner: str = "p1") -> City:
    city = City(id=state.next_city_id, owner=owner, loc=Coord(x=x, y=y))
    state.cities[city.id] = city
    state.next_city_id += 1
    tile = state.get_tile(Coord(x=x, y=y))
    assert tile is not None
    tile.city_id = city.id
    tile.owner = owner
    return city


# ---------------------------------------------------------------------------
# Pure-function tests
# ---------------------------------------------------------------------------


class TestGetValidAttacks:
    def test_adjacent_enemy_unit_listed(self) -> None:
        state = _make_state(players=("p1", "p2"))
        attacker = _add_unit(state, UnitType.SOLDIER, 2, 2, owner="p1")
        enemy = _add_unit(state, UnitType.SOLDIER, 2, 3, owner="p2")

        results = get_valid_attacks(state, attacker.id)

        assert len(results) == 1
        r = results[0]
        assert r["target_type"] == "unit"
        assert r["target_id"] == enemy.id
        assert r["owner"] == "p2"
        assert r["distance"] == 1
        assert r["diplomatic_state"] == DiplomaticState.PEACE.value

    def test_out_of_range_unit_excluded(self) -> None:
        state = _make_state(players=("p1", "p2"))
        # SOLDIER has attack_range=1; target at distance 2 is excluded.
        attacker = _add_unit(state, UnitType.SOLDIER, 0, 0, owner="p1")
        _add_unit(state, UnitType.SOLDIER, 2, 0, owner="p2")

        results = get_valid_attacks(state, attacker.id)
        assert results == []

    def test_archer_range_two_includes_distance_two(self) -> None:
        state = _make_state(players=("p1", "p2"))
        attacker = _add_unit(state, UnitType.ARCHER, 0, 0, owner="p1")  # range=2
        _add_unit(state, UnitType.SOLDIER, 2, 0, owner="p2")

        results = get_valid_attacks(state, attacker.id)
        assert len(results) == 1
        assert results[0]["distance"] == 2

    def test_worker_zero_attack_returns_empty(self) -> None:
        state = _make_state(players=("p1", "p2"))
        worker = _add_unit(state, UnitType.WORKER, 2, 2, owner="p1")
        _add_unit(state, UnitType.SOLDIER, 2, 3, owner="p2")

        assert get_valid_attacks(state, worker.id) == []

    def test_ally_excluded(self) -> None:
        state = _make_state(players=("p1", "p2"))
        state.diplomacy[("p1", "p2")] = DiplomaticState.ALLIANCE
        attacker = _add_unit(state, UnitType.SOLDIER, 2, 2, owner="p1")
        _add_unit(state, UnitType.SOLDIER, 2, 3, owner="p2")

        assert get_valid_attacks(state, attacker.id) == []

    def test_own_unit_excluded(self) -> None:
        state = _make_state(players=("p1",))
        attacker = _add_unit(state, UnitType.SOLDIER, 2, 2, owner="p1")
        _add_unit(state, UnitType.SCOUT, 2, 3, owner="p1")

        assert get_valid_attacks(state, attacker.id) == []

    def test_enemy_city_listed(self) -> None:
        state = _make_state(players=("p1", "p2"))
        attacker = _add_unit(state, UnitType.SOLDIER, 2, 2, owner="p1")
        enemy_city = _add_city(state, 2, 3, owner="p2")

        results = get_valid_attacks(state, attacker.id)
        assert len(results) == 1
        assert results[0]["target_type"] == "city"
        assert results[0]["target_id"] == enemy_city.id

    def test_visibility_mask_filters_targets(self) -> None:
        """Targets on tiles outside the visible set are excluded."""
        state = _make_state(players=("p1", "p2"))
        attacker = _add_unit(state, UnitType.ARCHER, 0, 0, owner="p1")  # range=2
        _add_unit(state, UnitType.SOLDIER, 2, 0, owner="p2")
        # Visibility mask does not include (2, 0) even though it's in range.
        visible = {Coord(x=0, y=0), Coord(x=1, y=0)}

        assert get_valid_attacks(state, attacker.id, visible_coords=visible) == []


class TestCanFoundCityHere:
    def test_worker_on_plains_can_found(self) -> None:
        state = _make_state()
        worker = _add_unit(state, UnitType.WORKER, 2, 2)

        result = can_found_city_here(state, worker.id)
        assert result["can_found"] is True
        assert result["reason"] is None
        assert result["cost"] == {"food": 15}

    def test_non_worker_cannot_found(self) -> None:
        state = _make_state()
        soldier = _add_unit(state, UnitType.SOLDIER, 2, 2)

        result = can_found_city_here(state, soldier.id)
        assert result["can_found"] is False
        assert "not a worker" in result["reason"]

    def test_mountain_tile_rejected(self) -> None:
        state = _make_state()
        _set_tile(state, 2, 2, terrain=Terrain.MOUNTAIN)
        worker = _add_unit(state, UnitType.WORKER, 2, 2)

        result = can_found_city_here(state, worker.id)
        assert result["can_found"] is False
        assert "mountain" in result["reason"].lower()

    def test_insufficient_food_rejected(self) -> None:
        state = _make_state()
        state.stockpiles["p1"] = ResourceBag(food=5)
        worker = _add_unit(state, UnitType.WORKER, 2, 2)

        result = can_found_city_here(state, worker.id)
        assert result["can_found"] is False
        assert "afford" in result["reason"].lower()

    def test_existing_city_rejected(self) -> None:
        state = _make_state()
        worker = _add_unit(state, UnitType.WORKER, 2, 2)
        _add_city(state, 2, 2)

        result = can_found_city_here(state, worker.id)
        assert result["can_found"] is False


class TestGetValidImprovements:
    def test_lumber_mill_on_forest_listed(self) -> None:
        state = _make_state()
        _set_tile(state, 2, 2, terrain=Terrain.FOREST)
        worker = _add_unit(state, UnitType.WORKER, 2, 2)

        results = get_valid_improvements(state, worker.id)
        improvement_types = {r["improvement"] for r in results}
        assert ImprovementType.LUMBER_MILL.value in improvement_types

    def test_farm_requires_food_resource(self) -> None:
        state = _make_state()
        # Plain plains with no food resource — FARM requires FOOD on tile.
        worker = _add_unit(state, UnitType.WORKER, 2, 2)
        results = get_valid_improvements(state, worker.id)
        assert ImprovementType.FARM.value not in {r["improvement"] for r in results}

        # Add FOOD resource; FARM now listed.
        _set_tile(state, 2, 2, resource=Resource.FOOD)
        results = get_valid_improvements(state, worker.id)
        assert ImprovementType.FARM.value in {r["improvement"] for r in results}

    def test_existing_improvement_blocks_all(self) -> None:
        state = _make_state()
        _set_tile(state, 2, 2, terrain=Terrain.FOREST, improvement=ImprovementType.LUMBER_MILL)
        worker = _add_unit(state, UnitType.WORKER, 2, 2)

        assert get_valid_improvements(state, worker.id) == []

    def test_non_worker_returns_empty(self) -> None:
        state = _make_state()
        _set_tile(state, 2, 2, terrain=Terrain.FOREST)
        soldier = _add_unit(state, UnitType.SOLDIER, 2, 2)

        assert get_valid_improvements(state, soldier.id) == []

    def test_affordable_flag_reflects_stockpile(self) -> None:
        state = _make_state()
        _set_tile(state, 2, 2, terrain=Terrain.FOREST)
        state.stockpiles["p1"] = ResourceBag()  # empty
        worker = _add_unit(state, UnitType.WORKER, 2, 2)

        results = get_valid_improvements(state, worker.id)
        # LUMBER_MILL costs 5 wood; with empty stockpile, affordable=False but listed.
        lumber = next(r for r in results if r["improvement"] == ImprovementType.LUMBER_MILL.value)
        assert lumber["affordable"] is False


class TestGetTrainableUnits:
    def test_lists_all_unit_types(self) -> None:
        state = _make_state()
        city = _add_city(state, 2, 2)

        results = get_trainable_units(state, city.id)
        types = {r["unit_type"] for r in results}
        assert types == {u.value for u in UNIT_STATS.keys()}

    def test_barracks_discount_applied(self) -> None:
        state = _make_state()
        city = _add_city(state, 2, 2)

        baseline = get_trainable_units(state, city.id)
        baseline_soldier = next(
            r for r in baseline if r["unit_type"] == UnitType.SOLDIER.value
        )

        city.buildings.add(BuildingType.BARRACKS)
        discounted = get_trainable_units(state, city.id)
        discounted_soldier = next(
            r for r in discounted if r["unit_type"] == UnitType.SOLDIER.value
        )
        # 15 food * 0.75 = 11, 5 ore * 0.75 = 3
        assert discounted_soldier["cost"]["food"] < baseline_soldier["cost"]["food"]

    def test_affordable_flag_reflects_stockpile(self) -> None:
        state = _make_state()
        state.stockpiles["p1"] = ResourceBag(food=5)
        city = _add_city(state, 2, 2)

        results = get_trainable_units(state, city.id)
        soldier = next(r for r in results if r["unit_type"] == UnitType.SOLDIER.value)
        assert soldier["affordable"] is False

    def test_unknown_city_returns_empty(self) -> None:
        state = _make_state()
        assert get_trainable_units(state, 9999) == []


class TestGetBuildableBuildings:
    def test_lists_all_building_types(self) -> None:
        state = _make_state()
        city = _add_city(state, 2, 2)

        results = get_buildable_buildings(state, city.id)
        types = {r["building_type"] for r in results}
        assert types == {b.value for b in BUILDING_STATS.keys()}

    def test_already_built_flag_set(self) -> None:
        state = _make_state()
        city = _add_city(state, 2, 2)
        city.buildings.add(BuildingType.GRANARY)

        results = get_buildable_buildings(state, city.id)
        granary = next(
            r for r in results if r["building_type"] == BuildingType.GRANARY.value
        )
        assert granary["already_built"] is True

        walls = next(
            r for r in results if r["building_type"] == BuildingType.WALLS.value
        )
        assert walls["already_built"] is False

    def test_affordable_flag_reflects_stockpile(self) -> None:
        state = _make_state()
        state.stockpiles["p1"] = ResourceBag()
        city = _add_city(state, 2, 2)

        results = get_buildable_buildings(state, city.id)
        granary = next(
            r for r in results if r["building_type"] == BuildingType.GRANARY.value
        )
        assert granary["affordable"] is False


# ---------------------------------------------------------------------------
# REST endpoint tests
# ---------------------------------------------------------------------------


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest_asyncio.fixture
async def _clean_phase5_rows() -> None:
    await init_db()
    async with async_session_factory() as session:
        for table in (
            PlayerApiKey,
            GameSnapshot,
            TurnSnapshot,
            TurnAction,
            PlayerAction,
            GameTurn,
        ):
            await session.execute(
                delete(table).where(table.game_id.like(f"{_GAME_PREFIX}_%"))
            )
        await session.execute(delete(Game).where(Game.id.like(f"{_GAME_PREFIX}_%")))
        await session.commit()
    manager._by_game.clear()
    yield
    async with async_session_factory() as session:
        for table in (
            PlayerApiKey,
            GameSnapshot,
            TurnSnapshot,
            TurnAction,
            PlayerAction,
            GameTurn,
        ):
            await session.execute(
                delete(table).where(table.game_id.like(f"{_GAME_PREFIX}_%"))
            )
        await session.execute(delete(Game).where(Game.id.like(f"{_GAME_PREFIX}_%")))
        await session.commit()
    manager._by_game.clear()


def _game_id(suffix: str) -> str:
    return f"{_GAME_PREFIX}_{suffix}_{int(time.time() * 1000000)}"


async def _mint_key(game_id: str, player_id: str) -> str:
    async with async_session_factory() as session:
        key = await create_player_key(session, game_id, player_id)
        await session.commit()
        return key


def _auth(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


def _start_game(client: TestClient, game_id: str, players: list[str]) -> None:
    resp = client.post(
        f"/api/v1/games/{game_id}/start",
        json={"players": players, "seed": 42},
    )
    assert resp.status_code == 200


async def _first_unit_id_for(game_id: str, player_id: str) -> int:
    async with async_session_factory() as session:
        controller = get_persistent_game_controller(session)
        state = await controller.get_game_state(game_id)
        assert state is not None
        for unit in state.units.values():
            if unit.owner == player_id:
                return unit.id
        raise AssertionError(f"no units for {player_id} in {game_id}")


async def _first_worker_id_for(game_id: str, player_id: str) -> int:
    async with async_session_factory() as session:
        controller = get_persistent_game_controller(session)
        state = await controller.get_game_state(game_id)
        assert state is not None
        for unit in state.units.values():
            if unit.owner == player_id and unit.type == UnitType.WORKER:
                return unit.id
        raise AssertionError(f"no worker for {player_id} in {game_id}")


class TestValidAttacksEndpoint:
    def test_missing_key_rejected(self, client: TestClient) -> None:
        resp = client.get("/api/v1/games/x/units/1/valid-attacks")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_wrong_game_key_rejected(
        self, client: TestClient, _clean_phase5_rows: None
    ) -> None:
        game_a = _game_id("att_a")
        game_b = _game_id("att_b")
        _start_game(client, game_a, ["alice", "bob"])
        _start_game(client, game_b, ["alice", "bob"])
        key_a = await _mint_key(game_a, "alice")

        resp = client.get(
            f"/api/v1/games/{game_b}/units/1/valid-attacks",
            headers=_auth(key_a),
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_enemy_unit_returns_404(
        self, client: TestClient, _clean_phase5_rows: None
    ) -> None:
        """Querying an enemy unit 404s so IDs cannot be enumerated."""
        game_id = _game_id("att_enemy")
        _start_game(client, game_id, ["alice", "bob"])
        alice_key = await _mint_key(game_id, "alice")
        bob_unit = await _first_unit_id_for(game_id, "bob")

        resp = client.get(
            f"/api/v1/games/{game_id}/units/{bob_unit}/valid-attacks",
            headers=_auth(alice_key),
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_happy_path_shape(
        self, client: TestClient, _clean_phase5_rows: None
    ) -> None:
        game_id = _game_id("att_happy")
        _start_game(client, game_id, ["alice", "bob"])
        key = await _mint_key(game_id, "alice")
        unit_id = await _first_unit_id_for(game_id, "alice")

        resp = client.get(
            f"/api/v1/games/{game_id}/units/{unit_id}/valid-attacks",
            headers=_auth(key),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["game_id"] == game_id
        assert data["unit_id"] == unit_id
        assert "attack_range" in data
        assert isinstance(data["targets"], list)


class TestCanFoundCityEndpoint:
    def test_missing_key_rejected(self, client: TestClient) -> None:
        resp = client.get("/api/v1/games/x/units/1/can-found-city")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_worker_happy_path(
        self, client: TestClient, _clean_phase5_rows: None
    ) -> None:
        """Starting worker is placed on passable terrain; can_found reflects the state."""
        game_id = _game_id("fc_happy")
        _start_game(client, game_id, ["alice", "bob"])
        key = await _mint_key(game_id, "alice")
        worker_id = await _first_worker_id_for(game_id, "alice")

        resp = client.get(
            f"/api/v1/games/{game_id}/units/{worker_id}/can-found-city",
            headers=_auth(key),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["unit_id"] == worker_id
        assert "can_found" in data
        assert "cost" in data
        assert data["cost"]["food"] == 15

    @pytest.mark.asyncio
    async def test_enemy_worker_returns_404(
        self, client: TestClient, _clean_phase5_rows: None
    ) -> None:
        game_id = _game_id("fc_enemy")
        _start_game(client, game_id, ["alice", "bob"])
        alice_key = await _mint_key(game_id, "alice")
        bob_worker = await _first_worker_id_for(game_id, "bob")

        resp = client.get(
            f"/api/v1/games/{game_id}/units/{bob_worker}/can-found-city",
            headers=_auth(alice_key),
        )
        assert resp.status_code == 404


class TestValidImprovementsEndpoint:
    @pytest.mark.asyncio
    async def test_worker_on_starting_tile(
        self, client: TestClient, _clean_phase5_rows: None
    ) -> None:
        game_id = _game_id("imp_happy")
        _start_game(client, game_id, ["alice", "bob"])
        key = await _mint_key(game_id, "alice")
        worker_id = await _first_worker_id_for(game_id, "alice")

        resp = client.get(
            f"/api/v1/games/{game_id}/units/{worker_id}/valid-improvements",
            headers=_auth(key),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["unit_id"] == worker_id
        assert isinstance(data["improvements"], list)
        # tile key present (starting tile is always passable)
        assert data["tile"] is not None

    @pytest.mark.asyncio
    async def test_enemy_worker_returns_404(
        self, client: TestClient, _clean_phase5_rows: None
    ) -> None:
        game_id = _game_id("imp_enemy")
        _start_game(client, game_id, ["alice", "bob"])
        alice_key = await _mint_key(game_id, "alice")
        bob_worker = await _first_worker_id_for(game_id, "bob")

        resp = client.get(
            f"/api/v1/games/{game_id}/units/{bob_worker}/valid-improvements",
            headers=_auth(alice_key),
        )
        assert resp.status_code == 404


class TestTrainableUnitsEndpoint:
    def test_missing_key_rejected(self, client: TestClient) -> None:
        resp = client.get("/api/v1/games/x/cities/1/trainable-units")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_unknown_city_returns_404(
        self, client: TestClient, _clean_phase5_rows: None
    ) -> None:
        game_id = _game_id("tu_unknown")
        _start_game(client, game_id, ["alice", "bob"])
        key = await _mint_key(game_id, "alice")

        resp = client.get(
            f"/api/v1/games/{game_id}/cities/9999/trainable-units",
            headers=_auth(key),
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_owned_city_happy_path(
        self, client: TestClient, _clean_phase5_rows: None
    ) -> None:
        """Found a city, then query it for trainable-units."""
        game_id = _game_id("tu_happy")
        _start_game(client, game_id, ["alice", "bob"])
        key = await _mint_key(game_id, "alice")

        # Seed a city directly via the controller.
        async with async_session_factory() as session:
            controller = get_persistent_game_controller(session)
            state = await controller.get_game_state(game_id)
            assert state is not None
            city = City(id=state.next_city_id, owner="alice", loc=Coord(x=0, y=0))
            state.cities[city.id] = city
            state.next_city_id += 1
            tile = state.get_tile(city.loc)
            assert tile is not None
            tile.city_id = city.id
            tile.owner = "alice"
            await controller.repo.update_game_state(game_id, state)
            await session.commit()
            city_id = city.id

        resp = client.get(
            f"/api/v1/games/{game_id}/cities/{city_id}/trainable-units",
            headers=_auth(key),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["city_id"] == city_id
        assert isinstance(data["units"], list)
        assert len(data["units"]) == len(UNIT_STATS)
        sample = data["units"][0]
        for field in ("unit_type", "cost", "affordable", "stats"):
            assert field in sample


class TestBuildableBuildingsEndpoint:
    def test_missing_key_rejected(self, client: TestClient) -> None:
        resp = client.get("/api/v1/games/x/cities/1/buildable-buildings")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_owned_city_happy_path(
        self, client: TestClient, _clean_phase5_rows: None
    ) -> None:
        game_id = _game_id("bb_happy")
        _start_game(client, game_id, ["alice", "bob"])
        key = await _mint_key(game_id, "alice")

        async with async_session_factory() as session:
            controller = get_persistent_game_controller(session)
            state = await controller.get_game_state(game_id)
            assert state is not None
            city = City(id=state.next_city_id, owner="alice", loc=Coord(x=0, y=0))
            state.cities[city.id] = city
            state.next_city_id += 1
            tile = state.get_tile(city.loc)
            assert tile is not None
            tile.city_id = city.id
            tile.owner = "alice"
            await controller.repo.update_game_state(game_id, state)
            await session.commit()
            city_id = city.id

        resp = client.get(
            f"/api/v1/games/{game_id}/cities/{city_id}/buildable-buildings",
            headers=_auth(key),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["city_id"] == city_id
        assert len(data["buildings"]) == len(BUILDING_STATS)
        sample = data["buildings"][0]
        for field in ("building_type", "cost", "affordable", "already_built", "effect"):
            assert field in sample

    @pytest.mark.asyncio
    async def test_enemy_city_returns_404(
        self, client: TestClient, _clean_phase5_rows: None
    ) -> None:
        """Enemy city queried with your key 404s (oracle prevention)."""
        game_id = _game_id("bb_enemy")
        _start_game(client, game_id, ["alice", "bob"])
        alice_key = await _mint_key(game_id, "alice")

        async with async_session_factory() as session:
            controller = get_persistent_game_controller(session)
            state = await controller.get_game_state(game_id)
            assert state is not None
            bob_city = City(id=state.next_city_id, owner="bob", loc=Coord(x=0, y=0))
            state.cities[bob_city.id] = bob_city
            state.next_city_id += 1
            tile = state.get_tile(bob_city.loc)
            assert tile is not None
            tile.city_id = bob_city.id
            tile.owner = "bob"
            await controller.repo.update_game_state(game_id, state)
            await session.commit()
            bob_city_id = bob_city.id

        resp = client.get(
            f"/api/v1/games/{game_id}/cities/{bob_city_id}/buildable-buildings",
            headers=_auth(alice_key),
        )
        assert resp.status_code == 404
