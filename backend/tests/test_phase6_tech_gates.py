"""Phase 6: tech gates on unit/building production.

Engine-level invariants the PRD promises:

* ``UNIT_STATS`` and ``BUILDING_STATS`` carry a ``required_tech`` field.
* Queueing an item whose required tech is not in the player's
  ``ResearchState.completed`` fails with a per-item message naming the
  missing tech.
* The three wrapper actions — ``TRAIN_UNIT`` (Phase 3),
  ``BUILD_BUILDING`` (Phase 3), ``SET_CITY_PRODUCTION`` (Phase 4) — all
  share the same gate (they all land on the ``_enqueue_*`` helpers).
* ``get_trainable_units`` / ``get_buildable_buildings`` surface a
  ``locked`` flag and ``required_tech`` / ``required_tech_name`` so the
  UI can grey locked entries rather than hide them.
* Starter-tier techs are pre-completed at game creation, so gated-but-
  starter items (e.g. SOLDIER on bronze_working) stay buildable from
  turn 1.
"""

from backend.src.game.models import (
    BUILDING_STATS,
    TECH_TREE,
    UNIT_STATS,
    BuildBuildingAction,
    BuildingType,
    City,
    Coord,
    GameState,
    ResearchState,
    ResourceBag,
    SetCityProductionAction,
    Terrain,
    Tile,
    TrainUnitAction,
    UnitType,
)
from backend.src.game.rules import (
    execute_build_building,
    execute_set_city_production,
    execute_train_unit,
    get_buildable_buildings,
    get_trainable_units,
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


def _seed_city(state: GameState, player: str, x: int, y: int) -> City:
    city = City(id=1, owner=player, loc=Coord(x=x, y=y))
    state.cities[1] = city
    tile = state.get_tile(Coord(x=x, y=y))
    assert tile is not None
    tile.city_id = 1
    tile.owner = player
    return city


class TestRequiredTechMetadata:
    """The stats tables expose ``required_tech`` with the expected gates."""

    def test_unit_gates(self):
        assert UNIT_STATS[UnitType.SCOUT].required_tech is None
        assert UNIT_STATS[UnitType.WORKER].required_tech is None
        assert UNIT_STATS[UnitType.SOLDIER].required_tech == "bronze_working"
        assert UNIT_STATS[UnitType.ARCHER].required_tech == "archery"

    def test_building_gates(self):
        assert BUILDING_STATS[BuildingType.GRANARY].required_tech == "pottery"
        assert BUILDING_STATS[BuildingType.BARRACKS].required_tech == "bronze_working"
        assert BUILDING_STATS[BuildingType.WALLS].required_tech == "masonry"
        assert BUILDING_STATS[BuildingType.MONUMENT].required_tech == "writing"
        assert BUILDING_STATS[BuildingType.LIBRARY].required_tech == "writing"
        assert BUILDING_STATS[BuildingType.TEMPLE].required_tech == "mysticism"


class TestUnitTechGate:
    def test_archer_rejected_without_archery(self):
        """ARCHER requires archery — not in STARTER_TECHS, so a fresh
        game rejects the queueing with a message that names the gate."""
        state = _plains_grid()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag(food=100, wood=100)
        city = _seed_city(state, "p1", 5, 5)

        result = execute_train_unit(
            state, TrainUnitAction(city_id=city.id, unit_type=UnitType.ARCHER)
        )
        assert result.success is False
        assert "archer" in result.message.lower()
        # Per-item message names the missing tech — both the display
        # name and the id so the UI / agent can surface either.
        assert "archery" in result.message.lower()
        assert "archery" in result.message  # id
        # No queue side effect on rejection.
        assert city.build_queue == []
        # Stockpile unchanged — the affordability check runs after the
        # gate, so rejection must leave resources intact.
        assert state.stockpiles["p1"].food == 100
        assert state.stockpiles["p1"].wood == 100

    def test_soldier_allowed_because_bronze_working_is_starter(self):
        """SOLDIER is gated on bronze_working which is a starter tech.
        The resolver auto-seeds starters, so a freshly constructed state
        queues SOLDIER fine on turn 1."""
        state = _plains_grid()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag(food=100, ore=100)
        city = _seed_city(state, "p1", 5, 5)

        result = execute_train_unit(
            state, TrainUnitAction(city_id=city.id, unit_type=UnitType.SOLDIER)
        )
        assert result.success is True
        assert len(city.build_queue) == 1
        assert city.build_queue[0].target == UnitType.SOLDIER.value

    def test_archer_allowed_after_archery_researched(self):
        state = _plains_grid()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag(food=100, wood=100)
        state.research["p1"] = ResearchState(
            completed=["pottery", "bronze_working", "archery"]
        )
        city = _seed_city(state, "p1", 5, 5)

        result = execute_train_unit(
            state, TrainUnitAction(city_id=city.id, unit_type=UnitType.ARCHER)
        )
        assert result.success is True
        assert city.build_queue[0].target == UnitType.ARCHER.value


class TestBuildingTechGate:
    def test_library_rejected_without_writing(self):
        state = _plains_grid()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag(wood=100, ore=100)
        city = _seed_city(state, "p1", 5, 5)

        result = execute_build_building(
            state,
            BuildBuildingAction(
                city_id=city.id, building_type=BuildingType.LIBRARY
            ),
        )
        assert result.success is False
        assert "library" in result.message.lower()
        assert "writing" in result.message.lower()
        assert "writing" in result.message  # id
        assert city.build_queue == []
        assert state.stockpiles["p1"].wood == 100

    def test_granary_allowed_because_pottery_is_starter(self):
        state = _plains_grid()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag(wood=100)
        city = _seed_city(state, "p1", 5, 5)

        result = execute_build_building(
            state,
            BuildBuildingAction(
                city_id=city.id, building_type=BuildingType.GRANARY
            ),
        )
        assert result.success is True
        assert city.build_queue[0].target == BuildingType.GRANARY.value

    def test_walls_allowed_after_masonry_researched(self):
        state = _plains_grid()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag(ore=100)
        state.research["p1"] = ResearchState(
            completed=["pottery", "bronze_working", "masonry"]
        )
        city = _seed_city(state, "p1", 5, 5)

        result = execute_build_building(
            state,
            BuildBuildingAction(city_id=city.id, building_type=BuildingType.WALLS),
        )
        assert result.success is True
        assert city.build_queue[0].target == BuildingType.WALLS.value


class TestWrapperParity:
    """All three wrappers (``TRAIN_UNIT``, ``BUILD_BUILDING``,
    ``SET_CITY_PRODUCTION``) land on the same ``_enqueue_*`` helpers, so
    the gate must fire identically through each."""

    def test_set_city_production_unit_rejects_same_as_train_unit(self):
        state = _plains_grid()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag(food=100, wood=100)
        city = _seed_city(state, "p1", 5, 5)

        train_result = execute_train_unit(
            state, TrainUnitAction(city_id=city.id, unit_type=UnitType.ARCHER)
        )
        set_result = execute_set_city_production(
            state,
            "p1",
            SetCityProductionAction(city_id=city.id, unit_type=UnitType.ARCHER),
        )
        assert train_result.success is False
        assert set_result.success is False
        assert train_result.message == set_result.message

    def test_set_city_production_building_rejects_same_as_build_building(self):
        state = _plains_grid()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag(wood=100, ore=100)
        city = _seed_city(state, "p1", 5, 5)

        build_result = execute_build_building(
            state,
            BuildBuildingAction(
                city_id=city.id, building_type=BuildingType.LIBRARY
            ),
        )
        set_result = execute_set_city_production(
            state,
            "p1",
            SetCityProductionAction(
                city_id=city.id, building_type=BuildingType.LIBRARY
            ),
        )
        assert build_result.success is False
        assert set_result.success is False
        assert build_result.message == set_result.message


class TestTrainableListingExposesLock:
    def test_locked_and_required_tech_fields_present(self):
        state = _plains_grid()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag(food=100, wood=100, ore=100)
        _seed_city(state, "p1", 5, 5)

        rows = {r["unit_type"]: r for r in get_trainable_units(state, 1)}

        # Scout has no gate.
        assert rows[UnitType.SCOUT.value]["locked"] is False
        assert rows[UnitType.SCOUT.value]["required_tech"] is None
        assert rows[UnitType.SCOUT.value]["required_tech_name"] is None

        # Soldier is gated on bronze_working (starter → unlocked).
        assert rows[UnitType.SOLDIER.value]["locked"] is False
        assert rows[UnitType.SOLDIER.value]["required_tech"] == "bronze_working"
        assert (
            rows[UnitType.SOLDIER.value]["required_tech_name"]
            == TECH_TREE["bronze_working"].name
        )

        # Archer is gated on archery (non-starter → locked).
        assert rows[UnitType.ARCHER.value]["locked"] is True
        assert rows[UnitType.ARCHER.value]["required_tech"] == "archery"
        assert (
            rows[UnitType.ARCHER.value]["required_tech_name"]
            == TECH_TREE["archery"].name
        )

    def test_locked_clears_after_research(self):
        state = _plains_grid()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag(food=100, wood=100)
        state.research["p1"] = ResearchState(
            completed=["pottery", "bronze_working", "archery"]
        )
        _seed_city(state, "p1", 5, 5)

        rows = {r["unit_type"]: r for r in get_trainable_units(state, 1)}
        assert rows[UnitType.ARCHER.value]["locked"] is False


class TestBuildableListingExposesLock:
    def test_locked_and_required_tech_fields_present(self):
        state = _plains_grid()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag(wood=100, ore=100, crystal=100)
        _seed_city(state, "p1", 5, 5)

        rows = {r["building_type"]: r for r in get_buildable_buildings(state, 1)}

        # Granary gated on starter pottery → unlocked.
        assert rows[BuildingType.GRANARY.value]["locked"] is False
        assert rows[BuildingType.GRANARY.value]["required_tech"] == "pottery"

        # Monument gated on writing → locked pre-research.
        monument = rows[BuildingType.MONUMENT.value]
        assert monument["locked"] is True
        assert monument["required_tech"] == "writing"
        assert monument["required_tech_name"] == TECH_TREE["writing"].name

        # Temple gated on mysticism → locked.
        temple = rows[BuildingType.TEMPLE.value]
        assert temple["locked"] is True
        assert temple["required_tech"] == "mysticism"

    def test_locked_clears_after_research(self):
        state = _plains_grid()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag(wood=100)
        state.research["p1"] = ResearchState(
            completed=["pottery", "bronze_working", "writing"]
        )
        _seed_city(state, "p1", 5, 5)

        rows = {r["building_type"]: r for r in get_buildable_buildings(state, 1)}
        assert rows[BuildingType.MONUMENT.value]["locked"] is False
        assert rows[BuildingType.LIBRARY.value]["locked"] is False
        # Temple still locked — it needs mysticism, which requires writing.
        assert rows[BuildingType.TEMPLE.value]["locked"] is True
