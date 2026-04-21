"""Phase 3/4: multi-turn production via BuildJob.

Covers the engine-level invariants the PRD promises: resources deduct at
queue time, production advances deterministically, the unit/building
materialises only when ``progress >= total_cost``, Barracks boosts unit
jobs only, ``redact_state`` hides other players' queues, and completion
events surface on ``TurnResult.production_completed``.

Phase 4 turned ``City.build_queue`` from a single-slot ``BuildJob | None``
into an ordered ``list[BuildJob]``. These tests assert head-slot
semantics (``build_queue[0]`` is active; empty list means idle) as well
as the Phase 3 invariants above.
"""

from backend.src.game.models import (
    BUILDING_PRODUCTION_COST,
    UNIT_PRODUCTION_COST,
    BuildBuildingAction,
    BuildingType,
    City,
    Coord,
    GameState,
    ResourceBag,
    Terrain,
    Tile,
    TrainUnitAction,
    Unit,
    UnitType,
)
from backend.src.game.rules import (
    advance_production,
    execute_train_unit,
    redact_state,
    resolve_turn,
)


def _plains_grid(width: int = 10, height: int = 10) -> GameState:
    state = GameState(map_width=width, map_height=height)
    tile_id = 0
    for y in range(height):
        for x in range(width):
            state.tiles.append(
                Tile(id=tile_id, loc=Coord(x=x, y=y), terrain=Terrain.PLAINS)
            )
            tile_id += 1
    return state


def _seed_city(state: GameState, player: str, x: int, y: int, city_id: int = 1) -> City:
    city = City(id=city_id, owner=player, loc=Coord(x=x, y=y))
    state.cities[city_id] = city
    tile = state.get_tile(Coord(x=x, y=y))
    assert tile is not None
    tile.city_id = city_id
    tile.owner = player
    return city


class TestQueueSemantics:
    def test_queue_deducts_resources_immediately(self):
        state = _plains_grid()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag(food=100, ore=100)
        city = _seed_city(state, "p1", 5, 5)

        result = execute_train_unit(
            state, TrainUnitAction(city_id=city.id, unit_type=UnitType.SOLDIER)
        )

        assert result.success is True
        assert len(city.build_queue) == 1
        # Soldier costs food=15, ore=5; deducted at queue time.
        assert state.stockpiles["p1"].food == 85
        assert state.stockpiles["p1"].ore == 95

    def test_queue_without_ore_rejected(self):
        state = _plains_grid()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag(food=100)
        city = _seed_city(state, "p1", 5, 5)

        result = execute_train_unit(
            state, TrainUnitAction(city_id=city.id, unit_type=UnitType.SOLDIER)
        )

        # Soldier wants ore=5; we have none.
        assert result.success is False
        assert city.build_queue == []
        assert state.stockpiles["p1"].food == 100

    def test_total_cost_from_static_table(self):
        state = _plains_grid()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag(food=100)
        city = _seed_city(state, "p1", 5, 5)

        execute_train_unit(
            state, TrainUnitAction(city_id=city.id, unit_type=UnitType.SCOUT)
        )
        assert len(city.build_queue) == 1
        assert city.build_queue[0].total_cost == UNIT_PRODUCTION_COST[UnitType.SCOUT]


class TestAdvanceProduction:
    def test_scout_takes_three_turns(self):
        """Scout total_cost=5, base rate=2 → 3 turns to materialise."""
        state = _plains_grid()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag(food=100)
        city = _seed_city(state, "p1", 5, 5)

        execute_train_unit(
            state, TrainUnitAction(city_id=city.id, unit_type=UnitType.SCOUT)
        )

        # Turn 1: 0 + 2 = 2
        advance_production(state)
        assert len(city.build_queue) == 1
        assert city.build_queue[0].progress == 2
        assert len(state.units) == 0

        # Turn 2: 2 + 2 = 4
        advance_production(state)
        assert len(city.build_queue) == 1
        assert city.build_queue[0].progress == 4
        assert len(state.units) == 0

        # Turn 3: 4 + 2 = 6 ≥ 5 → materialises
        completions = advance_production(state)
        assert city.build_queue == []
        assert len(state.units) == 1
        unit = next(iter(state.units.values()))
        assert unit.type == UnitType.SCOUT
        assert unit.owner == "p1"
        assert unit.loc == city.loc
        assert len(completions) == 1
        assert completions[0].city_id == city.id
        assert completions[0].type == "unit"
        assert completions[0].target == UnitType.SCOUT.value

    def test_barracks_boosts_unit_jobs_only(self):
        """Barracks adds +1/turn to unit jobs but not building jobs."""
        state = _plains_grid()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag(food=100, ore=100, wood=100, crystal=50)
        city = _seed_city(state, "p1", 5, 5)
        city.buildings.add(BuildingType.BARRACKS)

        # Barracks+unit rate is 3/turn; Scout is 5 → 2 turns to complete.
        execute_train_unit(
            state, TrainUnitAction(city_id=city.id, unit_type=UnitType.SCOUT)
        )
        advance_production(state)
        assert len(city.build_queue) == 1
        assert city.build_queue[0].progress == 3
        advance_production(state)
        assert city.build_queue == []
        assert len(state.units) == 1

        # Building job uses the base rate 2/turn despite Barracks.
        from backend.src.game.rules import execute_build_building

        execute_build_building(
            state,
            BuildBuildingAction(city_id=city.id, building_type=BuildingType.MONUMENT),
        )
        assert len(city.build_queue) == 1
        advance_production(state)
        assert len(city.build_queue) == 1
        assert city.build_queue[0].progress == 2  # base rate only

    def test_building_materialises_into_buildings_set(self):
        state = _plains_grid()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag(wood=100)
        city = _seed_city(state, "p1", 5, 5)

        from backend.src.game.rules import execute_build_building

        execute_build_building(
            state,
            BuildBuildingAction(city_id=city.id, building_type=BuildingType.MONUMENT),
        )
        # Monument is 6 production, 2/turn → 3 turns.
        for _ in range(3):
            advance_production(state)
        assert BuildingType.MONUMENT in city.buildings
        assert city.build_queue == []

    def test_unit_stalls_on_occupied_city_tile(self):
        """If the city tile is occupied when a unit job completes, progress
        clamps at total_cost and the unit emerges the turn the tile frees."""
        state = _plains_grid()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag(food=100)
        city = _seed_city(state, "p1", 5, 5)

        # Park a worker on the city tile.
        worker = Unit(
            id=50,
            owner="p1",
            type=UnitType.WORKER,
            hp=2,
            moves_left=2,
            loc=city.loc,
        )
        state.units[50] = worker
        state.next_unit_id = 51
        tile = state.get_tile(city.loc)
        assert tile is not None
        tile.unit_id = worker.id

        execute_train_unit(
            state, TrainUnitAction(city_id=city.id, unit_type=UnitType.SCOUT)
        )

        # Three turns — normally enough for Scout (cost 5, rate 2).
        for _ in range(3):
            completions = advance_production(state)
            assert completions == []
        # Job is still present, clamped at total_cost.
        assert len(city.build_queue) == 1
        assert city.build_queue[0].progress == city.build_queue[0].total_cost
        assert len(state.units) == 1  # still only the worker

        # Free the tile.
        tile.unit_id = None
        # Next turn: job completes.
        completions = advance_production(state)
        assert len(completions) == 1
        assert city.build_queue == []
        assert len(state.units) == 2


class TestInstantResolutionDeleted:
    """Grep confirms no instant-materialisation branch remains; these
    tests encode the invariant at the resolve_turn level."""

    def test_train_unit_does_not_materialise_same_turn(self):
        state = _plains_grid()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag(food=100)
        city = _seed_city(state, "p1", 5, 5)

        resolve_turn(
            state,
            {"p1": [TrainUnitAction(city_id=city.id, unit_type=UnitType.SCOUT)]},
        )
        # Scout cost is 5, rate 2 → 3 turns, so not present after turn 1.
        assert len(state.units) == 0

    def test_soldier_multi_turn_completion(self):
        """Soldier total=8, rate=2 → 4 turns. Asserts "appears after N
        turns" rather than the legacy "appears this turn" invariant."""
        state = _plains_grid()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag(food=100, ore=100)
        city = _seed_city(state, "p1", 5, 5)

        resolve_turn(
            state,
            {"p1": [TrainUnitAction(city_id=city.id, unit_type=UnitType.SOLDIER)]},
        )
        for _ in range(3):
            result = resolve_turn(state, {"p1": []})
            if result.production_completed:
                break
        # After four total resolve_turn calls the Soldier should exist.
        assert len(state.units) == 1
        soldier = next(iter(state.units.values()))
        assert soldier.type == UnitType.SOLDIER

    def test_resolve_turn_reports_completion_event(self):
        state = _plains_grid()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag(food=100)
        city = _seed_city(state, "p1", 5, 5)

        resolve_turn(
            state,
            {"p1": [TrainUnitAction(city_id=city.id, unit_type=UnitType.SCOUT)]},
        )
        resolve_turn(state, {"p1": []})
        final = resolve_turn(state, {"p1": []})
        assert len(final.production_completed) == 1
        event = final.production_completed[0]
        assert event.city_id == city.id
        assert event.owner == "p1"
        assert event.type == "unit"
        assert event.target == UnitType.SCOUT.value


class TestDeterminism:
    def test_sorted_city_order(self):
        """Two cities completing on the same turn both fire in
        sorted city_id order, regardless of dict insertion order."""
        state = _plains_grid(15, 15)
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag(food=100)
        # Insert city 2 before city 1 to verify iteration order.
        _seed_city(state, "p1", 10, 10, city_id=2)
        _seed_city(state, "p1", 5, 5, city_id=1)

        from backend.src.game.models import BuildJob

        for cid in (1, 2):
            state.cities[cid].build_queue = [
                BuildJob(
                    type="unit",
                    target=UnitType.SCOUT.value,
                    progress=4,
                    total_cost=UNIT_PRODUCTION_COST[UnitType.SCOUT],
                )
            ]

        completions = advance_production(state)
        assert [c.city_id for c in completions] == [1, 2]

    def test_replay_identical_hash(self):
        """Same seed + same actions → identical state hash under the new
        multi-turn resolver."""
        state_a = _plains_grid()
        state_a.players = ["p1"]
        state_a.stockpiles["p1"] = ResourceBag(food=100)
        _seed_city(state_a, "p1", 5, 5)

        state_b = _plains_grid()
        state_b.players = ["p1"]
        state_b.stockpiles["p1"] = ResourceBag(food=100)
        _seed_city(state_b, "p1", 5, 5)

        actions_sequence: list[dict] = [
            {"p1": [TrainUnitAction(city_id=1, unit_type=UnitType.SCOUT)]},
            {"p1": []},
            {"p1": []},
        ]
        hashes_a = []
        hashes_b = []
        for actions in actions_sequence:
            resolve_turn(state_a, actions)
            resolve_turn(state_b, actions)
            hashes_a.append(state_a.hash_state())
            hashes_b.append(state_b.hash_state())
        assert hashes_a == hashes_b


class TestFogOfWar:
    def test_redact_elides_foreign_build_queue(self):
        state = _plains_grid()
        state.players = ["p1", "p2"]
        state.stockpiles["p1"] = ResourceBag(food=100)
        state.stockpiles["p2"] = ResourceBag(food=100)
        city_p2 = _seed_city(state, "p2", 5, 5, city_id=1)
        # Give p1 line of sight to p2's city via a scout on the neighbouring tile.
        scout = Unit(
            id=100,
            owner="p1",
            type=UnitType.SCOUT,
            hp=2,
            moves_left=3,
            loc=Coord(x=4, y=5),
        )
        state.units[100] = scout
        state.next_unit_id = 101
        state.tiles[0].unit_id = None  # no-op; keep linter happy

        execute_train_unit(
            state, TrainUnitAction(city_id=city_p2.id, unit_type=UnitType.SCOUT)
        )
        assert len(city_p2.build_queue) == 1

        redacted = redact_state(state, "p1")
        # p1 can see the city via the scout…
        assert city_p2.id in redacted.cities
        # …but the build_queue is hidden (empty list) from them.
        assert redacted.cities[city_p2.id].build_queue == []

        # Owner still sees their own queue.
        redacted_owner = redact_state(state, "p2")
        assert len(redacted_owner.cities[city_p2.id].build_queue) == 1


class TestBuildingProductionCostTable:
    def test_all_buildings_have_a_cost(self):
        # Guard against enum drift — adding a BuildingType without a cost
        # would silently KeyError inside execute_build_building.
        for bt in BuildingType:
            assert bt in BUILDING_PRODUCTION_COST
