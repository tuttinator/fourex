"""
Tests for Phase 1: Culture model and border expansion.
"""

from backend.src.game.models import (
    BuildBuildingAction,
    BuildingType,
    City,
    Coord,
    GameState,
    ResourceBag,
    Terrain,
    Tile,
    Unit,
    UnitType,
)
from backend.src.game.rules import (
    accumulate_culture,
    execute_build_building,
    resolve_turn,
)


def _make_state_with_grid(width: int = 10, height: int = 10) -> GameState:
    """Create a game state with a full grid of plains tiles."""
    state = GameState(map_width=width, map_height=height)
    tile_id = 0
    for y in range(height):
        for x in range(width):
            state.tiles.append(
                Tile(
                    id=tile_id,
                    loc=Coord(x=x, y=y),
                    terrain=Terrain.PLAINS,
                )
            )
            tile_id += 1
    return state


class TestCityModel:
    """Test City model culture extensions."""

    def test_city_defaults(self):
        """New cities start with culture=0 and border_radius=0."""
        city = City(id=1, owner="p1", loc=Coord(x=5, y=5))
        assert city.culture == 0
        assert city.border_radius == 0

    def test_culture_per_turn_base(self):
        """Base culture per turn is 1."""
        city = City(id=1, owner="p1", loc=Coord(x=5, y=5))
        assert city.culture_per_turn() == 1

    def test_culture_per_turn_monument(self):
        city = City(
            id=1,
            owner="p1",
            loc=Coord(x=5, y=5),
            buildings={BuildingType.MONUMENT},
        )
        assert city.culture_per_turn() == 2

    def test_culture_per_turn_library(self):
        city = City(
            id=1,
            owner="p1",
            loc=Coord(x=5, y=5),
            buildings={BuildingType.LIBRARY},
        )
        assert city.culture_per_turn() == 3

    def test_culture_per_turn_temple(self):
        city = City(
            id=1,
            owner="p1",
            loc=Coord(x=5, y=5),
            buildings={BuildingType.TEMPLE},
        )
        assert city.culture_per_turn() == 4

    def test_culture_per_turn_all_buildings(self):
        """All three cultural buildings stack to 7 culture/turn."""
        city = City(
            id=1,
            owner="p1",
            loc=Coord(x=5, y=5),
            buildings={
                BuildingType.MONUMENT,
                BuildingType.LIBRARY,
                BuildingType.TEMPLE,
            },
        )
        assert city.culture_per_turn() == 7


class TestBuildBuilding:
    """Test execute_build_building()."""

    def test_build_monument(self):
        """Queueing a building deducts resources immediately but does not
        construct the building this turn — that's ``advance_production``'s
        job once the ``BuildJob`` accrues enough production."""
        state = _make_state_with_grid()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag(wood=20)
        city = City(id=1, owner="p1", loc=Coord(x=5, y=5))
        state.cities[1] = city
        tile = state.get_tile(Coord(x=5, y=5))
        tile.city_id = 1
        tile.owner = "p1"

        action = BuildBuildingAction(city_id=1, building_type=BuildingType.MONUMENT)
        result = execute_build_building(state, action)

        assert result.success is True
        assert BuildingType.MONUMENT not in city.buildings
        assert len(city.build_queue) == 1
        assert city.build_queue[0].target == BuildingType.MONUMENT.value
        assert state.stockpiles["p1"].wood == 10

    def test_build_library(self):
        state = _make_state_with_grid()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag(wood=30, ore=10)
        city = City(id=1, owner="p1", loc=Coord(x=5, y=5))
        state.cities[1] = city

        action = BuildBuildingAction(city_id=1, building_type=BuildingType.LIBRARY)
        result = execute_build_building(state, action)

        assert result.success is True
        assert len(city.build_queue) == 1
        assert city.build_queue[0].target == BuildingType.LIBRARY.value
        assert state.stockpiles["p1"] == ResourceBag(wood=15, ore=5)

    def test_build_temple(self):
        state = _make_state_with_grid()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag(wood=30, ore=20, crystal=10)
        city = City(id=1, owner="p1", loc=Coord(x=5, y=5))
        state.cities[1] = city

        action = BuildBuildingAction(city_id=1, building_type=BuildingType.TEMPLE)
        result = execute_build_building(state, action)

        assert result.success is True
        assert len(city.build_queue) == 1
        assert city.build_queue[0].target == BuildingType.TEMPLE.value

    def test_cannot_afford(self):
        state = _make_state_with_grid()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag(wood=5)
        city = City(id=1, owner="p1", loc=Coord(x=5, y=5))
        state.cities[1] = city

        action = BuildBuildingAction(city_id=1, building_type=BuildingType.MONUMENT)
        result = execute_build_building(state, action)

        assert result.success is False
        assert "cannot afford" in result.message.lower()

    def test_duplicate_building(self):
        state = _make_state_with_grid()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag(wood=40)
        city = City(
            id=1,
            owner="p1",
            loc=Coord(x=5, y=5),
            buildings={BuildingType.MONUMENT},
        )
        state.cities[1] = city

        action = BuildBuildingAction(city_id=1, building_type=BuildingType.MONUMENT)
        result = execute_build_building(state, action)

        assert result.success is False
        assert "already has" in result.message.lower()

    def test_city_not_found(self):
        state = _make_state_with_grid()
        state.players = ["p1"]

        action = BuildBuildingAction(city_id=99, building_type=BuildingType.MONUMENT)
        result = execute_build_building(state, action)

        assert result.success is False
        assert "not found" in result.message.lower()

    def test_stacking_buildings(self):
        """All three cultural buildings can coexist in a single city, but
        only one can be under construction at a time — each job must
        complete before the next enqueues."""
        from backend.src.game.rules import advance_production

        state = _make_state_with_grid()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag(wood=100, ore=50, crystal=20)
        city = City(id=1, owner="p1", loc=Coord(x=5, y=5))
        state.cities[1] = city

        for bt in (BuildingType.MONUMENT, BuildingType.LIBRARY, BuildingType.TEMPLE):
            result = execute_build_building(
                state, BuildBuildingAction(city_id=1, building_type=bt)
            )
            assert result.success is True
            # Drive the active job to completion before enqueueing the
            # next: base rate is 2/turn and all three cultural buildings
            # cost at most 12 production points.
            while city.build_queue:
                advance_production(state)

        assert city.buildings == {
            BuildingType.MONUMENT,
            BuildingType.LIBRARY,
            BuildingType.TEMPLE,
        }


class TestCultureAccumulation:
    """Test culture accumulation logic."""

    def test_base_culture_accumulation(self):
        state = _make_state_with_grid()
        state.players = ["p1"]
        # Cities founded via execute_found_city start at border_radius=1; use
        # that canonical state here so the test focuses on culture counting.
        city = City(id=1, owner="p1", loc=Coord(x=5, y=5), border_radius=1)
        state.cities[1] = city
        tile = state.get_tile(Coord(x=5, y=5))
        tile.city_id = 1
        tile.owner = "p1"

        accumulate_culture(state)
        assert city.culture == 1
        assert city.border_radius == 1

    def test_culture_with_monument(self):
        state = _make_state_with_grid()
        state.players = ["p1"]
        city = City(
            id=1,
            owner="p1",
            loc=Coord(x=5, y=5),
            border_radius=1,
            buildings={BuildingType.MONUMENT},
        )
        state.cities[1] = city
        tile = state.get_tile(Coord(x=5, y=5))
        tile.city_id = 1
        tile.owner = "p1"

        accumulate_culture(state)
        assert city.culture == 2

    def test_culture_with_all_buildings(self):
        state = _make_state_with_grid()
        state.players = ["p1"]
        city = City(
            id=1,
            owner="p1",
            loc=Coord(x=5, y=5),
            border_radius=1,
            buildings={
                BuildingType.MONUMENT,
                BuildingType.LIBRARY,
                BuildingType.TEMPLE,
            },
        )
        state.cities[1] = city
        tile = state.get_tile(Coord(x=5, y=5))
        tile.city_id = 1
        tile.owner = "p1"

        accumulate_culture(state)
        assert city.culture == 7


class TestBorderExpansion:
    """Test border expansion at culture thresholds."""

    def test_radius_1_immediate(self):
        """Radius 1 expands immediately (threshold 0) — the first
        ``accumulate_culture`` call after founding claims adjacent tiles."""
        state = _make_state_with_grid()
        state.players = ["p1"]
        city = City(id=1, owner="p1", loc=Coord(x=5, y=5))
        state.cities[1] = city
        tile = state.get_tile(Coord(x=5, y=5))
        tile.city_id = 1
        tile.owner = "p1"

        accumulate_culture(state)
        assert city.border_radius == 1

        # Check that Manhattan distance 1 tiles are claimed
        for coord in [
            Coord(x=5, y=4),
            Coord(x=5, y=6),
            Coord(x=4, y=5),
            Coord(x=6, y=5),
        ]:
            claimed_tile = state.get_tile(coord)
            assert claimed_tile.owner == "p1", f"Tile at {coord} should be owned by p1"
            assert claimed_tile.city_id == 1

    def test_radius_2_at_15_culture(self):
        """Border expands to radius 2 when culture reaches 15."""
        state = _make_state_with_grid()
        state.players = ["p1"]
        city = City(id=1, owner="p1", loc=Coord(x=5, y=5), culture=14, border_radius=1)
        state.cities[1] = city
        tile = state.get_tile(Coord(x=5, y=5))
        tile.city_id = 1
        tile.owner = "p1"
        # Pre-claim radius 1 tiles
        for t in state.tiles:
            if city.loc.distance_to(t.loc) <= 1:
                t.owner = "p1"
                t.city_id = 1

        accumulate_culture(state)
        assert city.border_radius == 2

        # Check a radius 2 tile
        tile_r2 = state.get_tile(Coord(x=5, y=3))
        assert tile_r2.owner == "p1"

    def test_radius_3_at_40_culture(self):
        """Border expands to radius 3 when culture reaches 40."""
        state = _make_state_with_grid()
        state.players = ["p1"]
        city = City(id=1, owner="p1", loc=Coord(x=5, y=5), culture=39, border_radius=2)
        state.cities[1] = city
        tile = state.get_tile(Coord(x=5, y=5))
        tile.city_id = 1
        tile.owner = "p1"
        # Pre-claim radius 2 tiles
        for t in state.tiles:
            if city.loc.distance_to(t.loc) <= 2:
                t.owner = "p1"
                t.city_id = 1

        accumulate_culture(state)
        assert city.border_radius == 3

        # Check a radius 3 tile
        tile_r3 = state.get_tile(Coord(x=5, y=2))
        assert tile_r3.owner == "p1"

    def test_first_to_reach_conflict(self):
        """Tiles already owned by another city are not claimed."""
        state = _make_state_with_grid()
        state.players = ["p1", "p2"]

        # Two cities close enough that their borders would overlap at (4,5).
        city1 = City(id=1, owner="p1", loc=Coord(x=3, y=5))
        city2 = City(id=2, owner="p2", loc=Coord(x=5, y=5), border_radius=1)
        state.cities[1] = city1
        state.cities[2] = city2

        # Set up city tiles
        t1 = state.get_tile(Coord(x=3, y=5))
        t1.city_id = 1
        t1.owner = "p1"
        t2 = state.get_tile(Coord(x=5, y=5))
        t2.city_id = 2
        t2.owner = "p2"

        # p2 already owns (4,5) from border_radius=1
        contested = state.get_tile(Coord(x=4, y=5))
        contested.owner = "p2"
        contested.city_id = 2

        # p1 expands to radius 1 — must NOT claim (4,5) because p2 owns it
        accumulate_culture(state)
        assert city1.border_radius == 1
        assert contested.owner == "p2"
        assert contested.city_id == 2

    def test_water_tiles_claimed(self):
        """Water tiles within borders are owned (they yield whatever resource
        they carry, and contribute nothing if bare)."""
        state = _make_state_with_grid()
        state.players = ["p1"]
        water_tile = state.get_tile(Coord(x=5, y=6))
        water_tile.terrain = Terrain.WATER

        city = City(id=1, owner="p1", loc=Coord(x=5, y=5))
        state.cities[1] = city
        tile = state.get_tile(Coord(x=5, y=5))
        tile.city_id = 1
        tile.owner = "p1"

        accumulate_culture(state)
        assert city.border_radius == 1
        assert water_tile.owner == "p1"
        assert water_tile.city_id == 1

    def test_mountain_tiles_claimed(self):
        """Mountain tiles within borders are owned — ore/crystal on mountains
        contributes to income via _calculate_tile_yield."""
        state = _make_state_with_grid()
        state.players = ["p1"]
        mountain_tile = state.get_tile(Coord(x=5, y=4))
        mountain_tile.terrain = Terrain.MOUNTAIN

        city = City(id=1, owner="p1", loc=Coord(x=5, y=5))
        state.cities[1] = city
        tile = state.get_tile(Coord(x=5, y=5))
        tile.city_id = 1
        tile.owner = "p1"

        accumulate_culture(state)
        assert mountain_tile.owner == "p1"
        assert mountain_tile.city_id == 1

    def test_newly_founded_city_radius_1(self):
        """Newly founded cities start at radius 1, owning adjacent tiles
        immediately so they have tile yields from turn 1."""
        state = _make_state_with_grid()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag(food=50)

        worker = Unit(
            id=1,
            owner="p1",
            type=UnitType.WORKER,
            hp=100,
            moves_left=2,
            loc=Coord(x=5, y=5),
        )
        state.units[1] = worker
        tile = state.get_tile(Coord(x=5, y=5))
        tile.unit_id = 1

        from backend.src.game.models import FoundCityAction
        from backend.src.game.rules import execute_found_city

        result = execute_found_city(state, FoundCityAction(worker_id=1))
        assert result.success is True

        city = list(state.cities.values())[0]
        assert city.culture == 0
        assert city.border_radius == 1

        # City tile and all Manhattan-distance-1 tiles should be owned.
        for coord in [
            Coord(x=5, y=5),
            Coord(x=5, y=4),
            Coord(x=5, y=6),
            Coord(x=4, y=5),
            Coord(x=6, y=5),
        ]:
            t = state.get_tile(coord)
            assert t.owner == "p1", f"Tile at {coord} should be owned by p1"
            assert t.city_id == city.id

        # Tiles at distance 2 should remain unowned.
        far = state.get_tile(Coord(x=5, y=3))
        assert far.owner is None

    def test_tile_belongs_to_at_most_one_city(self):
        """Each tile belongs to at most one city after expansion."""
        state = _make_state_with_grid()
        state.players = ["p1"]

        city1 = City(id=1, owner="p1", loc=Coord(x=3, y=5))
        city2 = City(id=2, owner="p1", loc=Coord(x=7, y=5))
        state.cities[1] = city1
        state.cities[2] = city2

        t1 = state.get_tile(Coord(x=3, y=5))
        t1.city_id = 1
        t1.owner = "p1"
        t2 = state.get_tile(Coord(x=7, y=5))
        t2.city_id = 2
        t2.owner = "p1"

        accumulate_culture(state)

        # Verify no tile has conflicting city_ids
        for t in state.tiles:
            if t.city_id is not None:
                assert t.city_id in (1, 2)


class TestBuildBuildingInResolveTurn:
    """Test that BUILD_BUILDING works through resolve_turn()."""

    def test_build_building_via_resolve_turn(self):
        """BUILD_BUILDING submitted through resolve_turn enqueues a job;
        the building materialises after enough turns for production to
        accrue (Monument costs 6 production, base rate 2/turn → 3 turns)."""
        state = _make_state_with_grid()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag(wood=20)
        city = City(id=1, owner="p1", loc=Coord(x=5, y=5))
        state.cities[1] = city
        tile = state.get_tile(Coord(x=5, y=5))
        tile.city_id = 1
        tile.owner = "p1"

        actions = {
            "p1": [BuildBuildingAction(city_id=1, building_type=BuildingType.MONUMENT)]
        }
        result = resolve_turn(state, actions)

        assert result.player_actions["p1"][0].success is True
        # First turn resolves: job enqueued + advanced by 2 (Monument is
        # 6 production, so 4 still to go).
        assert BuildingType.MONUMENT not in city.buildings
        assert len(city.build_queue) == 1
        assert city.build_queue[0].progress == 2

        # Two more empty turns drive the job to completion on the third.
        resolve_turn(state, {"p1": []})
        assert BuildingType.MONUMENT not in city.buildings
        final = resolve_turn(state, {"p1": []})
        assert BuildingType.MONUMENT in city.buildings
        assert city.build_queue == []
        assert len(final.production_completed) == 1
        assert final.production_completed[0].target == BuildingType.MONUMENT.value

    def test_culture_accumulates_in_resolve_turn(self):
        """Culture accumulates during resolve_turn after actions."""
        state = _make_state_with_grid()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag()
        city = City(id=1, owner="p1", loc=Coord(x=5, y=5))
        state.cities[1] = city
        tile = state.get_tile(Coord(x=5, y=5))
        tile.city_id = 1
        tile.owner = "p1"

        resolve_turn(state, {"p1": []})
        assert city.culture == 1  # 1 base culture after 1 turn
