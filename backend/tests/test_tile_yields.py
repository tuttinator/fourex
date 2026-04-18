"""
Tests for Phase 2: City tile yields.

Cities collect resources from all tiles within their cultural borders.
Base yields come from terrain/resource type; improvements boost yields.
"""

from backend.src.game.models import (
    BuildingType,
    City,
    Coord,
    GameState,
    ImprovementType,
    Resource,
    ResourceBag,
    Terrain,
    Tile,
)
from backend.src.game.rules import (
    _calculate_tile_yield,
    collect_resources,
    resolve_turn,
)


def _make_state(width: int = 10, height: int = 10) -> GameState:
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


def _add_city(state: GameState, owner: str, x: int, y: int) -> City:
    """Add a city at the given location, claiming the city tile."""
    city = City(id=state.next_city_id, owner=owner, loc=Coord(x=x, y=y))
    state.cities[city.id] = city
    state.next_city_id += 1

    tile = state.get_tile(Coord(x=x, y=y))
    assert tile is not None
    tile.city_id = city.id
    tile.owner = owner

    if owner not in state.players:
        state.players.append(owner)
    if owner not in state.stockpiles:
        state.stockpiles[owner] = ResourceBag()

    return city


def _set_tile(
    state: GameState,
    x: int,
    y: int,
    terrain: Terrain = Terrain.PLAINS,
    resource: Resource | None = None,
    owner: str | None = None,
    city_id: int | None = None,
    improvement: ImprovementType | None = None,
) -> Tile:
    """Modify an existing tile's properties."""
    tile = state.get_tile(Coord(x=x, y=y))
    assert tile is not None
    tile.terrain = terrain
    tile.resource = resource
    tile.owner = owner
    tile.city_id = city_id
    tile.improvement = improvement
    return tile


# ── _calculate_tile_yield unit tests ──


class TestTileYieldCalculation:
    """Test the per-tile yield calculation function."""

    def test_food_resource_tile(self):
        tile = Tile(
            id=0, loc=Coord(x=0, y=0), terrain=Terrain.PLAINS, resource=Resource.FOOD
        )
        assert _calculate_tile_yield(tile) == ResourceBag(food=1)

    def test_wood_resource_tile(self):
        tile = Tile(
            id=0, loc=Coord(x=0, y=0), terrain=Terrain.FOREST, resource=Resource.WOOD
        )
        assert _calculate_tile_yield(tile) == ResourceBag(wood=1)

    def test_ore_resource_tile(self):
        tile = Tile(
            id=0,
            loc=Coord(x=0, y=0),
            terrain=Terrain.MOUNTAIN,
            resource=Resource.ORE,
        )
        assert _calculate_tile_yield(tile) == ResourceBag(ore=1)

    def test_crystal_resource_tile(self):
        tile = Tile(
            id=0,
            loc=Coord(x=0, y=0),
            terrain=Terrain.PLAINS,
            resource=Resource.CRYSTAL,
        )
        assert _calculate_tile_yield(tile) == ResourceBag(crystal=1)

    def test_forest_without_resource_yields_wood(self):
        """Forest tiles without a resource yield +1 wood."""
        tile = Tile(id=0, loc=Coord(x=0, y=0), terrain=Terrain.FOREST)
        assert _calculate_tile_yield(tile) == ResourceBag(wood=1)

    def test_plains_without_resource_yields_nothing(self):
        tile = Tile(id=0, loc=Coord(x=0, y=0), terrain=Terrain.PLAINS)
        assert _calculate_tile_yield(tile) == ResourceBag()

    def test_farm_on_food_tile(self):
        """Farm on food tile: +1 base + +2 improvement = +3 food total."""
        tile = Tile(
            id=0,
            loc=Coord(x=0, y=0),
            terrain=Terrain.PLAINS,
            resource=Resource.FOOD,
            improvement=ImprovementType.FARM,
        )
        assert _calculate_tile_yield(tile) == ResourceBag(food=3)

    def test_mine_on_ore_tile(self):
        """Mine on ore tile: +1 base + +2 improvement = +3 ore total."""
        tile = Tile(
            id=0,
            loc=Coord(x=0, y=0),
            terrain=Terrain.MOUNTAIN,
            resource=Resource.ORE,
            improvement=ImprovementType.MINE,
        )
        assert _calculate_tile_yield(tile) == ResourceBag(ore=3)

    def test_lumber_mill_on_forest(self):
        """Lumber mill on forest: +1 base (forest) + +2 improvement = +3 wood total."""
        tile = Tile(
            id=0,
            loc=Coord(x=0, y=0),
            terrain=Terrain.FOREST,
            improvement=ImprovementType.LUMBER_MILL,
        )
        assert _calculate_tile_yield(tile) == ResourceBag(wood=3)

    def test_lumber_mill_on_forest_with_wood_resource(self):
        """Lumber mill on forest with wood resource: +1 base (resource) + +2 = +3."""
        tile = Tile(
            id=0,
            loc=Coord(x=0, y=0),
            terrain=Terrain.FOREST,
            resource=Resource.WOOD,
            improvement=ImprovementType.LUMBER_MILL,
        )
        assert _calculate_tile_yield(tile) == ResourceBag(wood=3)

    def test_crystal_extractor_on_crystal_tile(self):
        """Crystal extractor on crystal tile: +1 base + +1 improvement = +2 crystal."""
        tile = Tile(
            id=0,
            loc=Coord(x=0, y=0),
            terrain=Terrain.PLAINS,
            resource=Resource.CRYSTAL,
            improvement=ImprovementType.CRYSTAL_EXTRACTOR,
        )
        assert _calculate_tile_yield(tile) == ResourceBag(crystal=2)


# ── collect_resources integration tests ──


class TestCollectResources:
    """Test the full collect_resources flow with cities and tile yields."""

    def test_base_city_food_still_applies(self):
        """Cities produce +2 base food independent of territory."""
        state = _make_state()
        _add_city(state, "p1", 5, 5)

        collect_resources(state)
        assert state.stockpiles["p1"].food == 2

    def test_base_city_food_with_granary(self):
        """Granary boosts base city food to +3 (int(2 * 1.5) = 3)."""
        state = _make_state()
        city = _add_city(state, "p1", 5, 5)
        city.buildings.add(BuildingType.GRANARY)

        collect_resources(state)
        # int(2 * 1.5) = 3
        assert state.stockpiles["p1"].food == 3

    def test_owned_food_tile_yields(self):
        """Food resource tile within borders yields +1 food on top of base city food."""
        state = _make_state()
        city = _add_city(state, "p1", 5, 5)
        _set_tile(state, 5, 6, resource=Resource.FOOD, owner="p1", city_id=city.id)

        collect_resources(state)
        # 2 (base city) + 1 (food tile) = 3
        assert state.stockpiles["p1"].food == 3

    def test_owned_ore_tile_yields(self):
        state = _make_state()
        city = _add_city(state, "p1", 5, 5)
        _set_tile(state, 5, 6, resource=Resource.ORE, owner="p1", city_id=city.id)

        collect_resources(state)
        assert state.stockpiles["p1"].ore == 1

    def test_owned_crystal_tile_yields(self):
        state = _make_state()
        city = _add_city(state, "p1", 5, 5)
        _set_tile(state, 5, 6, resource=Resource.CRYSTAL, owner="p1", city_id=city.id)

        collect_resources(state)
        assert state.stockpiles["p1"].crystal == 1

    def test_forest_tile_yields_wood(self):
        """Forest tile within borders yields +1 wood."""
        state = _make_state()
        city = _add_city(state, "p1", 5, 5)
        _set_tile(
            state,
            5,
            6,
            terrain=Terrain.FOREST,
            owner="p1",
            city_id=city.id,
        )

        collect_resources(state)
        assert state.stockpiles["p1"].wood == 1

    def test_unowned_tile_yields_nothing(self):
        """Tiles outside borders (no owner) do not generate yields."""
        state = _make_state()
        _add_city(state, "p1", 5, 5)
        # Set a food tile nearby but don't assign owner
        _set_tile(state, 5, 6, resource=Resource.FOOD)

        collect_resources(state)
        # Only base city food, no tile yield
        assert state.stockpiles["p1"].food == 2

    def test_plains_without_resource_yields_nothing(self):
        """Owned plains tiles without a resource contribute nothing."""
        state = _make_state()
        city = _add_city(state, "p1", 5, 5)
        _set_tile(state, 5, 6, owner="p1", city_id=city.id)

        collect_resources(state)
        assert state.stockpiles["p1"] == ResourceBag(food=2)

    def test_improved_farm_yields_3_food(self):
        """Farm on a food tile within borders yields +3 food total."""
        state = _make_state()
        city = _add_city(state, "p1", 5, 5)
        _set_tile(
            state,
            5,
            6,
            resource=Resource.FOOD,
            owner="p1",
            city_id=city.id,
            improvement=ImprovementType.FARM,
        )

        collect_resources(state)
        # 2 (base city) + 3 (farm tile) = 5
        assert state.stockpiles["p1"].food == 5

    def test_improved_mine_yields_3_ore(self):
        """Mine on an ore tile within borders yields +3 ore total."""
        state = _make_state()
        city = _add_city(state, "p1", 5, 5)
        _set_tile(
            state,
            5,
            6,
            resource=Resource.ORE,
            owner="p1",
            city_id=city.id,
            improvement=ImprovementType.MINE,
        )

        collect_resources(state)
        assert state.stockpiles["p1"].ore == 3

    def test_improved_lumber_mill_yields_3_wood(self):
        """Lumber mill on a forest tile within borders yields +3 wood total."""
        state = _make_state()
        city = _add_city(state, "p1", 5, 5)
        _set_tile(
            state,
            5,
            6,
            terrain=Terrain.FOREST,
            owner="p1",
            city_id=city.id,
            improvement=ImprovementType.LUMBER_MILL,
        )

        collect_resources(state)
        assert state.stockpiles["p1"].wood == 3

    def test_improved_crystal_extractor_yields_2_crystal(self):
        """Crystal extractor on a crystal tile within borders yields +2 crystal."""
        state = _make_state()
        city = _add_city(state, "p1", 5, 5)
        _set_tile(
            state,
            5,
            6,
            resource=Resource.CRYSTAL,
            owner="p1",
            city_id=city.id,
            improvement=ImprovementType.CRYSTAL_EXTRACTOR,
        )

        collect_resources(state)
        assert state.stockpiles["p1"].crystal == 2

    def test_multiple_cities_collect_independently(self):
        """Two cities owned by different players collect from their own tiles."""
        state = _make_state()
        city1 = _add_city(state, "p1", 3, 3)
        city2 = _add_city(state, "p2", 7, 7)

        _set_tile(state, 3, 4, resource=Resource.FOOD, owner="p1", city_id=city1.id)
        _set_tile(state, 7, 8, resource=Resource.ORE, owner="p2", city_id=city2.id)

        collect_resources(state)

        assert state.stockpiles["p1"].food == 3  # 2 base + 1 tile
        assert state.stockpiles["p1"].ore == 0
        assert state.stockpiles["p2"].food == 2  # 2 base only
        assert state.stockpiles["p2"].ore == 1

    def test_same_player_two_cities(self):
        """Same player with two cities gets base food from both."""
        state = _make_state()
        _add_city(state, "p1", 3, 3)
        _add_city(state, "p1", 7, 7)

        collect_resources(state)
        # 2 + 2 base food from two cities
        assert state.stockpiles["p1"].food == 4

    def test_multiple_resource_tiles_accumulate(self):
        """Multiple owned tiles contribute their yields cumulatively."""
        state = _make_state()
        city = _add_city(state, "p1", 5, 5)

        _set_tile(state, 5, 6, resource=Resource.FOOD, owner="p1", city_id=city.id)
        _set_tile(state, 5, 4, resource=Resource.FOOD, owner="p1", city_id=city.id)
        _set_tile(state, 6, 5, resource=Resource.ORE, owner="p1", city_id=city.id)

        collect_resources(state)
        assert state.stockpiles["p1"].food == 4  # 2 base + 2 food tiles
        assert state.stockpiles["p1"].ore == 1

    def test_city_tile_itself_does_not_double_count(self):
        """The tile the city sits on should not generate tile yields (only base food)."""
        state = _make_state()
        city = _add_city(state, "p1", 5, 5)
        # Put a food resource on the city tile
        tile = state.get_tile(Coord(x=5, y=5))
        tile.resource = Resource.FOOD

        collect_resources(state)
        # Only base city food, not base + tile yield
        assert state.stockpiles["p1"].food == 2


class TestTileYieldsInResolveTurn:
    """Test that tile yields are collected as part of resolve_turn."""

    def test_yields_collected_during_turn(self):
        """resolve_turn collects tile yields from owned tiles."""
        state = _make_state()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag()
        city = _add_city(state, "p1", 5, 5)
        _set_tile(
            state,
            5,
            6,
            terrain=Terrain.FOREST,
            owner="p1",
            city_id=city.id,
            improvement=ImprovementType.LUMBER_MILL,
        )

        resolve_turn(state, {"p1": []})

        # 2 base food + 3 wood from lumber mill
        assert state.stockpiles["p1"].food == 2
        assert state.stockpiles["p1"].wood == 3

    def test_culture_expansion_then_yield_collection(self):
        """Tiles claimed by border expansion in the same turn should yield resources."""
        state = _make_state()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag()
        city = _add_city(state, "p1", 5, 5)
        # Set culture to just below threshold so this turn's accumulation crosses it
        city.culture = 9  # +1 base → 10, triggers radius 1

        # Place a food resource at distance 1
        _set_tile(state, 5, 6, resource=Resource.FOOD)

        resolve_turn(state, {"p1": []})

        # Border should have expanded to radius 1, claiming (5,6)
        tile = state.get_tile(Coord(x=5, y=6))
        assert tile.owner == "p1"
        # Yields: 2 base food + 1 food from newly claimed tile = 3
        assert state.stockpiles["p1"].food == 3
