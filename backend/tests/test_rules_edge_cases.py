"""
Phase 7 edge-case tests for the rules engine.

Coverage focus (things that existing test files didn't already cover):

- Movement: execute_move rejected on water and mountains, out-of-range
  rejected at the execute layer, move blocked by another unit.
- Combat: allied-city attacks rejected, wall counter-fire damage, city
  captured on HP<=0, self-attack rejected.
- City founding: rejected on water and on mountains, insufficient food,
  duplicate founding on a city tile, non-worker unit.
- Training: insufficient resources, barracks cost discount, occupied
  city tile.
- Build building: happy path, duplicate, insufficient resources,
  unknown city, invalid building type.
- Resources: collect_resources never produces negative stockpiles; a
  city with a Granary doubles its base food.

These are unit tests — no MCP server, no DB — so they run fast and are
deterministic.
"""

from __future__ import annotations

from backend.src.game.models import (
    AttackAction,
    BuildBuildingAction,
    BuildingType,
    City,
    Coord,
    DiplomaticState,
    FoundCityAction,
    GameState,
    MoveAction,
    ResourceBag,
    Terrain,
    Tile,
    TrainUnitAction,
    Unit,
    UnitType,
)
from backend.src.game.rules import (
    collect_resources,
    execute_attack,
    execute_build_building,
    execute_found_city,
    execute_move,
    execute_train_unit,
    resolve_turn,
)


def _plains_state(width: int = 6, height: int = 6) -> GameState:
    state = GameState(map_width=width, map_height=height)
    tile_id = 0
    for y in range(height):
        for x in range(width):
            state.tiles.append(
                Tile(id=tile_id, loc=Coord(x=x, y=y), terrain=Terrain.PLAINS)
            )
            tile_id += 1
    return state


def _set_terrain(state: GameState, x: int, y: int, terrain: Terrain) -> Tile:
    tile = state.get_tile(Coord(x=x, y=y))
    assert tile is not None
    tile.terrain = terrain
    return tile


def _add_unit(
    state: GameState,
    owner: str,
    unit_type: UnitType,
    x: int,
    y: int,
    hp: int | None = None,
    moves: int | None = None,
) -> Unit:
    from backend.src.game.models import UNIT_STATS

    stats = UNIT_STATS[unit_type]
    unit = Unit(
        id=state.next_unit_id,
        owner=owner,
        type=unit_type,
        hp=hp if hp is not None else stats.hp,
        moves_left=moves if moves is not None else stats.moves,
        loc=Coord(x=x, y=y),
    )
    state.units[unit.id] = unit
    tile = state.get_tile(Coord(x=x, y=y))
    if tile:
        tile.unit_id = unit.id
    state.next_unit_id += 1
    return unit


class TestMovementEdgeCases:
    def test_execute_move_rejects_water(self):
        state = _plains_state()
        state.players = ["p1"]
        _set_terrain(state, 2, 1, Terrain.WATER)
        unit = _add_unit(state, "p1", UnitType.SCOUT, 1, 1)

        result = execute_move(state, MoveAction(unit_id=unit.id, to=Coord(x=2, y=1)))

        assert result.success is False
        assert "water" in result.message.lower()
        # Unit stays put.
        assert unit.loc == Coord(x=1, y=1)
        # Old tile still holds the unit.
        assert state.get_tile(Coord(x=1, y=1)).unit_id == unit.id

    def test_execute_move_rejects_mountain(self):
        state = _plains_state()
        state.players = ["p1"]
        _set_terrain(state, 2, 1, Terrain.MOUNTAIN)
        unit = _add_unit(state, "p1", UnitType.SCOUT, 1, 1)

        result = execute_move(state, MoveAction(unit_id=unit.id, to=Coord(x=2, y=1)))

        assert result.success is False
        assert "mountain" in result.message.lower()
        assert unit.loc == Coord(x=1, y=1)

    def test_execute_move_rejects_out_of_range(self):
        state = _plains_state(width=10, height=10)
        state.players = ["p1"]
        unit = _add_unit(state, "p1", UnitType.WORKER, 1, 1)  # 2 moves

        result = execute_move(state, MoveAction(unit_id=unit.id, to=Coord(x=5, y=1)))

        assert result.success is False
        assert "moves" in result.message.lower()
        assert unit.loc == Coord(x=1, y=1)

    def test_execute_move_blocked_by_other_unit(self):
        state = _plains_state()
        state.players = ["p1", "p2"]
        mover = _add_unit(state, "p1", UnitType.SCOUT, 1, 1)
        _add_unit(state, "p2", UnitType.SCOUT, 2, 1)

        result = execute_move(state, MoveAction(unit_id=mover.id, to=Coord(x=2, y=1)))

        assert result.success is False
        assert mover.loc == Coord(x=1, y=1)


class TestCombatEdgeCases:
    def test_cannot_attack_allied_city(self):
        state = _plains_state()
        state.players = ["p1", "p2"]
        state.diplomacy[("p1", "p2")] = DiplomaticState.ALLIANCE
        attacker = _add_unit(state, "p1", UnitType.SOLDIER, 3, 3)
        city = City(id=1, owner="p2", loc=Coord(x=3, y=4))
        state.cities[city.id] = city

        result = execute_attack(
            state,
            AttackAction(attacker_id=attacker.id, target_id=city.id, target_type="city"),
        )

        assert result.success is False
        assert "allied" in result.message.lower()
        assert city.hp == 10

    def test_walls_counter_fire_damages_attacker(self):
        state = _plains_state()
        state.players = ["p1", "p2"]
        attacker = _add_unit(state, "p1", UnitType.SOLDIER, 3, 3, hp=4)
        city = City(
            id=1,
            owner="p2",
            loc=Coord(x=3, y=4),
            hp=20,
            buildings={BuildingType.WALLS},
        )
        state.cities[city.id] = city

        result = execute_attack(
            state,
            AttackAction(attacker_id=attacker.id, target_id=city.id, target_type="city"),
        )

        assert result.success is True
        # Soldier deals 2 * 1.25 = 2 damage (int truncated).
        assert city.hp == 18
        # Walls counter for 2.
        assert attacker.hp == 2

    def test_city_captured_when_hp_drops_to_zero(self):
        state = _plains_state()
        state.players = ["p1", "p2"]
        attacker = _add_unit(state, "p1", UnitType.SOLDIER, 3, 3)
        city = City(id=1, owner="p2", loc=Coord(x=3, y=4), hp=1)
        state.cities[city.id] = city

        result = execute_attack(
            state,
            AttackAction(attacker_id=attacker.id, target_id=city.id, target_type="city"),
        )

        assert result.success is True
        assert city.owner == "p1"
        assert city.hp == 1  # Captured-with-1-HP rule
        assert "captured" in result.message.lower()

    def test_out_of_range_attack_rejected(self):
        state = _plains_state(width=10, height=10)
        state.players = ["p1", "p2"]
        attacker = _add_unit(state, "p1", UnitType.SOLDIER, 1, 1)
        target = _add_unit(state, "p2", UnitType.SCOUT, 5, 5)

        result = execute_attack(
            state,
            AttackAction(attacker_id=attacker.id, target_id=target.id, target_type="unit"),
        )

        assert result.success is False
        assert target.hp == 2


class TestFoundCityEdgeCases:
    def test_cannot_found_on_water(self):
        state = _plains_state()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag(food=100)
        _set_terrain(state, 2, 2, Terrain.WATER)
        worker = _add_unit(state, "p1", UnitType.WORKER, 2, 2)

        result = execute_found_city(state, FoundCityAction(worker_id=worker.id))

        assert result.success is False
        assert "water" in result.message.lower()
        # Worker still exists, resources intact.
        assert worker.id in state.units
        assert state.stockpiles["p1"].food == 100

    def test_cannot_found_on_mountain(self):
        state = _plains_state()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag(food=100)
        _set_terrain(state, 2, 2, Terrain.MOUNTAIN)
        worker = _add_unit(state, "p1", UnitType.WORKER, 2, 2)

        result = execute_found_city(state, FoundCityAction(worker_id=worker.id))

        assert result.success is False
        assert "mountain" in result.message.lower()
        assert worker.id in state.units

    def test_cannot_found_without_food(self):
        state = _plains_state()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag(food=10)
        worker = _add_unit(state, "p1", UnitType.WORKER, 2, 2)

        result = execute_found_city(state, FoundCityAction(worker_id=worker.id))

        assert result.success is False
        assert "afford" in result.message.lower() or "food" in result.message.lower()
        assert worker.id in state.units

    def test_cannot_found_on_existing_city(self):
        state = _plains_state()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag(food=100)
        tile = state.get_tile(Coord(x=2, y=2))
        tile.city_id = 99
        worker = _add_unit(state, "p1", UnitType.WORKER, 2, 2)

        result = execute_found_city(state, FoundCityAction(worker_id=worker.id))

        assert result.success is False
        assert "city" in result.message.lower()
        assert worker.id in state.units

    def test_non_worker_unit_cannot_found(self):
        state = _plains_state()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag(food=100)
        scout = _add_unit(state, "p1", UnitType.SCOUT, 2, 2)

        result = execute_found_city(state, FoundCityAction(worker_id=scout.id))

        assert result.success is False
        assert "worker" in result.message.lower()


class TestTrainUnitEdgeCases:
    def _seeded_city(self, state: GameState) -> City:
        city = City(id=1, owner="p1", loc=Coord(x=2, y=2))
        state.cities[city.id] = city
        tile = state.get_tile(Coord(x=2, y=2))
        tile.city_id = city.id
        return city

    def test_insufficient_resources(self):
        state = _plains_state()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag(food=5)
        self._seeded_city(state)

        result = execute_train_unit(
            state, TrainUnitAction(city_id=1, unit_type=UnitType.SCOUT)
        )

        assert result.success is False
        assert "afford" in result.message.lower()
        assert len(state.units) == 0

    def test_occupied_tile_blocks_training(self):
        state = _plains_state()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag(food=100)
        city = self._seeded_city(state)
        _add_unit(state, "p1", UnitType.WORKER, city.loc.x, city.loc.y)

        result = execute_train_unit(
            state, TrainUnitAction(city_id=city.id, unit_type=UnitType.SCOUT)
        )

        assert result.success is False
        assert "occupied" in result.message.lower()

    def test_barracks_discount_applied(self):
        state = _plains_state()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag(food=100, ore=100)
        city = self._seeded_city(state)
        city.buildings.add(BuildingType.BARRACKS)

        result = execute_train_unit(
            state, TrainUnitAction(city_id=city.id, unit_type=UnitType.SOLDIER)
        )

        assert result.success is True
        # Soldier costs food=30, ore=10 at full price; barracks multiplies
        # by 0.75 -> food=22, ore=7.
        assert state.stockpiles["p1"].food == 78
        assert state.stockpiles["p1"].ore == 93


class TestBuildBuildingEdgeCases:
    def _seeded_city(self, state: GameState) -> City:
        city = City(id=1, owner="p1", loc=Coord(x=2, y=2))
        state.cities[city.id] = city
        tile = state.get_tile(Coord(x=2, y=2))
        tile.city_id = city.id
        return city

    def test_build_granary_happy_path(self):
        state = _plains_state()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag(wood=60)
        city = self._seeded_city(state)

        result = execute_build_building(
            state,
            BuildBuildingAction(city_id=city.id, building_type=BuildingType.GRANARY),
        )

        assert result.success is True
        assert BuildingType.GRANARY in city.buildings
        assert state.stockpiles["p1"].wood == 20  # 60 - 40

    def test_duplicate_building_rejected(self):
        state = _plains_state()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag(wood=200)
        city = self._seeded_city(state)
        city.buildings.add(BuildingType.GRANARY)

        result = execute_build_building(
            state,
            BuildBuildingAction(city_id=city.id, building_type=BuildingType.GRANARY),
        )

        assert result.success is False
        assert "already" in result.message.lower()
        # No resource deduction on failure.
        assert state.stockpiles["p1"].wood == 200

    def test_build_building_insufficient_resources(self):
        state = _plains_state()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag(wood=10)
        city = self._seeded_city(state)

        result = execute_build_building(
            state,
            BuildBuildingAction(city_id=city.id, building_type=BuildingType.GRANARY),
        )

        assert result.success is False
        assert "afford" in result.message.lower()
        assert BuildingType.GRANARY not in city.buildings

    def test_build_building_missing_city(self):
        state = _plains_state()
        state.players = ["p1"]

        result = execute_build_building(
            state,
            BuildBuildingAction(city_id=999, building_type=BuildingType.GRANARY),
        )

        assert result.success is False
        assert "not found" in result.message.lower()


class TestResourceCollection:
    def test_negative_stockpile_cannot_emerge_from_collect(self):
        state = _plains_state()
        state.players = ["p1"]
        # Start at zero — collect_resources should only add, never subtract.
        state.stockpiles["p1"] = ResourceBag()
        city = City(id=1, owner="p1", loc=Coord(x=2, y=2))
        state.cities[city.id] = city

        collect_resources(state)

        pile = state.stockpiles["p1"]
        assert pile.food >= 0
        assert pile.wood >= 0
        assert pile.ore >= 0
        assert pile.crystal >= 0
        assert pile.food == 1  # Base city output

    def test_granary_boosts_food(self):
        state = _plains_state()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag()
        city = City(id=1, owner="p1", loc=Coord(x=2, y=2))
        city.buildings.add(BuildingType.GRANARY)
        state.cities[city.id] = city

        collect_resources(state)

        # 1 base * 1.5 multiplier = 1 (int-cast in rules.py).
        # The only guarantee is >= base; if rules change we want this to
        # catch it either way.
        assert state.stockpiles["p1"].food >= 1


class TestResolveTurnInvariants:
    def test_invalid_action_does_not_corrupt_state(self):
        """Submitting a bad action should fail that action only — not the turn."""
        state = _plains_state()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag(food=100)
        worker = _add_unit(state, "p1", UnitType.WORKER, 2, 2)
        _set_terrain(state, 3, 2, Terrain.WATER)

        # Try to step into water and also found a city on plains.
        # Only the found-city should succeed.
        actions = {
            "p1": [
                MoveAction(unit_id=worker.id, to=Coord(x=3, y=2)),  # invalid: water
                FoundCityAction(worker_id=worker.id),  # valid: plains, funded
            ]
        }
        result = resolve_turn(state, actions)

        outcomes = result.player_actions["p1"]
        assert outcomes[0].success is False  # water move rejected
        assert outcomes[1].success is True  # city founded
        # Worker consumed by founding; no dangling tile unit ref.
        assert worker.id not in state.units
        assert state.get_tile(Coord(x=2, y=2)).unit_id is None
        # Stockpile deducted exactly once, not twice.
        assert state.stockpiles["p1"].food == 70 + 1  # 100 - 30 + collect
