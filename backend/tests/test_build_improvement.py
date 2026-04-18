"""
Tests for execute_build_improvement(): validates ownership, terrain,
resources; places improvement; worker survives and retains moves.

Covers: valid builds for each improvement type, wrong terrain, wrong
resource, insufficient resources, duplicate improvement, non-worker unit,
missing unit, and resolve_turn integration.
"""

from backend.src.game.models import (
    IMPROVEMENT_STATS,
    BuildImprovementAction,
    Coord,
    GameState,
    ImprovementType,
    MoveAction,
    Resource,
    ResourceBag,
    Terrain,
    Tile,
    Unit,
    UnitType,
)
from backend.src.game.rules import execute_build_improvement, resolve_turn


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


def _add_worker(state: GameState, owner: str, x: int, y: int) -> Unit:
    """Add a worker at the given location."""
    unit = Unit(
        id=state.next_unit_id,
        owner=owner,
        type=UnitType.WORKER,
        hp=100,
        moves_left=2,
        loc=Coord(x=x, y=y),
    )
    state.units[unit.id] = unit
    state.next_unit_id += 1
    tile = state.get_tile(Coord(x=x, y=y))
    if tile:
        tile.unit_id = unit.id
    return unit


def _set_tile(
    state: GameState, x: int, y: int, terrain: Terrain, resource: Resource | None = None
) -> Tile:
    """Set a tile's terrain and resource."""
    tile = state.get_tile(Coord(x=x, y=y))
    assert tile is not None
    tile.terrain = terrain
    tile.resource = resource
    return tile


class TestBuildFarm:
    """FARM requires plains terrain + food resource."""

    def test_valid_farm(self):
        state = _make_state()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag(wood=100)
        _set_tile(state, 3, 3, Terrain.PLAINS, Resource.FOOD)
        worker = _add_worker(state, "p1", 3, 3)

        action = BuildImprovementAction(
            worker_id=worker.id, improvement=ImprovementType.FARM
        )
        result = execute_build_improvement(state, action)

        assert result.success
        tile = state.get_tile(Coord(x=3, y=3))
        assert tile.improvement == ImprovementType.FARM
        assert worker.id in state.units  # worker survives
        assert tile.unit_id == worker.id
        assert worker.moves_left == 2  # moves retained
        cost = IMPROVEMENT_STATS[ImprovementType.FARM].cost
        assert state.stockpiles["p1"].wood == 100 - cost.wood

    def test_farm_wrong_terrain_forest(self):
        state = _make_state()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag(wood=100)
        _set_tile(state, 3, 3, Terrain.FOREST, Resource.FOOD)
        worker = _add_worker(state, "p1", 3, 3)

        action = BuildImprovementAction(
            worker_id=worker.id, improvement=ImprovementType.FARM
        )
        result = execute_build_improvement(state, action)

        assert not result.success
        assert "plains" in result.message.lower()

    def test_farm_no_food_resource(self):
        state = _make_state()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag(wood=100)
        _set_tile(state, 3, 3, Terrain.PLAINS, None)  # no resource
        worker = _add_worker(state, "p1", 3, 3)

        action = BuildImprovementAction(
            worker_id=worker.id, improvement=ImprovementType.FARM
        )
        result = execute_build_improvement(state, action)

        assert not result.success
        assert "food" in result.message.lower()


class TestBuildMine:
    """MINE requires mountain terrain + ore resource."""

    def test_valid_mine(self):
        state = _make_state()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag(wood=100)
        _set_tile(state, 4, 4, Terrain.MOUNTAIN, Resource.ORE)
        worker = _add_worker(state, "p1", 4, 4)

        action = BuildImprovementAction(
            worker_id=worker.id, improvement=ImprovementType.MINE
        )
        result = execute_build_improvement(state, action)

        assert result.success
        tile = state.get_tile(Coord(x=4, y=4))
        assert tile.improvement == ImprovementType.MINE
        assert worker.id in state.units

    def test_mine_wrong_terrain(self):
        state = _make_state()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag(wood=100)
        _set_tile(state, 4, 4, Terrain.PLAINS, Resource.ORE)
        worker = _add_worker(state, "p1", 4, 4)

        action = BuildImprovementAction(
            worker_id=worker.id, improvement=ImprovementType.MINE
        )
        result = execute_build_improvement(state, action)

        assert not result.success
        assert "mountain" in result.message.lower()

    def test_mine_no_ore_resource(self):
        state = _make_state()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag(wood=100)
        _set_tile(state, 4, 4, Terrain.MOUNTAIN, None)
        worker = _add_worker(state, "p1", 4, 4)

        action = BuildImprovementAction(
            worker_id=worker.id, improvement=ImprovementType.MINE
        )
        result = execute_build_improvement(state, action)

        assert not result.success
        assert "ore" in result.message.lower()


class TestBuildLumberMill:
    """LUMBER_MILL requires forest terrain, no specific resource."""

    def test_valid_lumber_mill(self):
        state = _make_state()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag(wood=100)
        _set_tile(state, 5, 5, Terrain.FOREST)
        worker = _add_worker(state, "p1", 5, 5)

        action = BuildImprovementAction(
            worker_id=worker.id, improvement=ImprovementType.LUMBER_MILL
        )
        result = execute_build_improvement(state, action)

        assert result.success
        tile = state.get_tile(Coord(x=5, y=5))
        assert tile.improvement == ImprovementType.LUMBER_MILL
        assert worker.id in state.units

    def test_lumber_mill_on_forest_with_wood_resource(self):
        """Lumber mill should work on forest with wood resource too."""
        state = _make_state()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag(wood=100)
        _set_tile(state, 5, 5, Terrain.FOREST, Resource.WOOD)
        worker = _add_worker(state, "p1", 5, 5)

        action = BuildImprovementAction(
            worker_id=worker.id, improvement=ImprovementType.LUMBER_MILL
        )
        result = execute_build_improvement(state, action)

        assert result.success

    def test_lumber_mill_wrong_terrain(self):
        state = _make_state()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag(wood=100)
        _set_tile(state, 5, 5, Terrain.PLAINS)
        worker = _add_worker(state, "p1", 5, 5)

        action = BuildImprovementAction(
            worker_id=worker.id, improvement=ImprovementType.LUMBER_MILL
        )
        result = execute_build_improvement(state, action)

        assert not result.success
        assert "forest" in result.message.lower()


class TestBuildCrystalExtractor:
    """CRYSTAL_EXTRACTOR requires crystal resource on any non-water terrain."""

    def test_valid_crystal_extractor_plains(self):
        state = _make_state()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag(wood=100, ore=100)
        _set_tile(state, 6, 6, Terrain.PLAINS, Resource.CRYSTAL)
        worker = _add_worker(state, "p1", 6, 6)

        action = BuildImprovementAction(
            worker_id=worker.id, improvement=ImprovementType.CRYSTAL_EXTRACTOR
        )
        result = execute_build_improvement(state, action)

        assert result.success
        tile = state.get_tile(Coord(x=6, y=6))
        assert tile.improvement == ImprovementType.CRYSTAL_EXTRACTOR

    def test_valid_crystal_extractor_mountain(self):
        state = _make_state()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag(wood=100, ore=100)
        _set_tile(state, 6, 6, Terrain.MOUNTAIN, Resource.CRYSTAL)
        worker = _add_worker(state, "p1", 6, 6)

        action = BuildImprovementAction(
            worker_id=worker.id, improvement=ImprovementType.CRYSTAL_EXTRACTOR
        )
        result = execute_build_improvement(state, action)

        assert result.success

    def test_crystal_extractor_no_crystal_resource(self):
        state = _make_state()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag(wood=100, ore=100)
        _set_tile(state, 6, 6, Terrain.PLAINS, Resource.FOOD)
        worker = _add_worker(state, "p1", 6, 6)

        action = BuildImprovementAction(
            worker_id=worker.id, improvement=ImprovementType.CRYSTAL_EXTRACTOR
        )
        result = execute_build_improvement(state, action)

        assert not result.success
        assert "crystal" in result.message.lower()

    def test_crystal_extractor_on_water(self):
        state = _make_state()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag(wood=100, ore=100)
        _set_tile(state, 6, 6, Terrain.WATER, Resource.CRYSTAL)
        worker = _add_worker(state, "p1", 6, 6)

        action = BuildImprovementAction(
            worker_id=worker.id, improvement=ImprovementType.CRYSTAL_EXTRACTOR
        )
        result = execute_build_improvement(state, action)

        assert not result.success


class TestEdgeCases:
    """Edge cases for build improvement."""

    def test_unit_not_found(self):
        state = _make_state()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag(wood=100)

        action = BuildImprovementAction(worker_id=999, improvement=ImprovementType.FARM)
        result = execute_build_improvement(state, action)

        assert not result.success
        assert "not found" in result.message.lower()

    def test_non_worker_unit(self):
        state = _make_state()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag(wood=100)
        _set_tile(state, 3, 3, Terrain.PLAINS, Resource.FOOD)

        # Add a soldier instead of worker
        soldier = Unit(
            id=state.next_unit_id,
            owner="p1",
            type=UnitType.SOLDIER,
            hp=4,
            moves_left=2,
            loc=Coord(x=3, y=3),
        )
        state.units[soldier.id] = soldier
        state.next_unit_id += 1

        action = BuildImprovementAction(
            worker_id=soldier.id, improvement=ImprovementType.FARM
        )
        result = execute_build_improvement(state, action)

        assert not result.success
        assert "not a worker" in result.message.lower()

    def test_insufficient_resources(self):
        state = _make_state()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag(wood=0)  # no wood
        _set_tile(state, 3, 3, Terrain.PLAINS, Resource.FOOD)
        worker = _add_worker(state, "p1", 3, 3)

        action = BuildImprovementAction(
            worker_id=worker.id, improvement=ImprovementType.FARM
        )
        result = execute_build_improvement(state, action)

        assert not result.success
        assert "cannot afford" in result.message.lower()
        # Worker should still exist
        assert worker.id in state.units

    def test_duplicate_improvement(self):
        state = _make_state()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag(wood=200)
        tile = _set_tile(state, 3, 3, Terrain.PLAINS, Resource.FOOD)
        tile.improvement = ImprovementType.FARM  # already improved
        worker = _add_worker(state, "p1", 3, 3)

        action = BuildImprovementAction(
            worker_id=worker.id, improvement=ImprovementType.FARM
        )
        result = execute_build_improvement(state, action)

        assert not result.success
        assert "already has improvement" in result.message.lower()

    def test_resource_deduction_crystal_extractor(self):
        """Crystal extractor costs wood + ore; verify both deducted."""
        state = _make_state()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag(wood=50, ore=50)
        _set_tile(state, 6, 6, Terrain.PLAINS, Resource.CRYSTAL)
        worker = _add_worker(state, "p1", 6, 6)

        action = BuildImprovementAction(
            worker_id=worker.id, improvement=ImprovementType.CRYSTAL_EXTRACTOR
        )
        result = execute_build_improvement(state, action)

        assert result.success
        cost = IMPROVEMENT_STATS[ImprovementType.CRYSTAL_EXTRACTOR].cost
        assert state.stockpiles["p1"].wood == 50 - cost.wood
        assert state.stockpiles["p1"].ore == 50 - cost.ore


class TestResolveTurnIntegration:
    """BUILD_IMPROVEMENT actions through resolve_turn()."""

    def test_resolve_turn_builds_improvement(self):
        state = _make_state()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag(wood=100)
        _set_tile(state, 3, 3, Terrain.PLAINS, Resource.FOOD)
        worker = _add_worker(state, "p1", 3, 3)

        actions = {
            "p1": [
                BuildImprovementAction(
                    worker_id=worker.id, improvement=ImprovementType.FARM
                )
            ]
        }
        turn_result = resolve_turn(state, actions)

        assert turn_result.player_actions["p1"][0].success
        tile = state.get_tile(Coord(x=3, y=3))
        assert tile.improvement == ImprovementType.FARM

    def test_worker_survives_and_can_move_same_turn(self):
        """Worker builds a farm, then moves to an adjacent tile in the same turn."""
        state = _make_state()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag(wood=100)
        _set_tile(state, 3, 3, Terrain.PLAINS, Resource.FOOD)
        worker = _add_worker(state, "p1", 3, 3)

        actions = {
            "p1": [
                BuildImprovementAction(
                    worker_id=worker.id, improvement=ImprovementType.FARM
                ),
                MoveAction(unit_id=worker.id, to=Coord(x=4, y=3)),
            ]
        }
        turn_result = resolve_turn(state, actions)

        outcomes = turn_result.player_actions["p1"]
        assert outcomes[0].success
        assert outcomes[1].success
        assert worker.id in state.units
        assert state.units[worker.id].loc == Coord(x=4, y=3)
        assert state.get_tile(Coord(x=3, y=3)).improvement == ImprovementType.FARM
        assert state.get_tile(Coord(x=3, y=3)).unit_id is None
        assert state.get_tile(Coord(x=4, y=3)).unit_id == worker.id

    def test_worker_builds_multiple_improvements_across_turns(self):
        """A single worker builds a farm on turn 1, moves, then builds a lumber mill on turn 2."""
        state = _make_state()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag(wood=100)
        _set_tile(state, 3, 3, Terrain.PLAINS, Resource.FOOD)
        _set_tile(state, 4, 3, Terrain.FOREST)
        worker = _add_worker(state, "p1", 3, 3)

        turn1 = resolve_turn(
            state,
            {
                "p1": [
                    BuildImprovementAction(
                        worker_id=worker.id, improvement=ImprovementType.FARM
                    ),
                    MoveAction(unit_id=worker.id, to=Coord(x=4, y=3)),
                ]
            },
        )
        assert all(r.success for r in turn1.player_actions["p1"])

        turn2 = resolve_turn(
            state,
            {
                "p1": [
                    BuildImprovementAction(
                        worker_id=worker.id, improvement=ImprovementType.LUMBER_MILL
                    ),
                ]
            },
        )
        assert turn2.player_actions["p1"][0].success
        assert worker.id in state.units
        assert state.get_tile(Coord(x=3, y=3)).improvement == ImprovementType.FARM
        assert state.get_tile(Coord(x=4, y=3)).improvement == ImprovementType.LUMBER_MILL

    def test_resolve_turn_rejects_invalid_improvement(self):
        state = _make_state()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag(wood=100)
        _set_tile(state, 3, 3, Terrain.WATER, Resource.FOOD)  # water tile
        worker = _add_worker(state, "p1", 3, 3)

        actions = {
            "p1": [
                BuildImprovementAction(
                    worker_id=worker.id, improvement=ImprovementType.FARM
                )
            ]
        }
        turn_result = resolve_turn(state, actions)

        assert not turn_result.player_actions["p1"][0].success
        # Worker should still exist on failure
        assert worker.id in state.units


class TestImprovementStats:
    """Verify IMPROVEMENT_STATS are defined for all improvement types."""

    def test_all_improvement_types_have_stats(self):
        for imp_type in ImprovementType:
            assert imp_type in IMPROVEMENT_STATS, f"Missing stats for {imp_type}"

    def test_all_stats_have_positive_cost(self):
        for imp_type, stats in IMPROVEMENT_STATS.items():
            total_cost = (
                stats.cost.food + stats.cost.wood + stats.cost.ore + stats.cost.crystal
            )
            assert total_cost > 0, f"{imp_type} has zero total cost"

    def test_all_stats_have_valid_terrain(self):
        for imp_type, stats in IMPROVEMENT_STATS.items():
            assert len(stats.valid_terrain) > 0, f"{imp_type} has no valid terrain"
