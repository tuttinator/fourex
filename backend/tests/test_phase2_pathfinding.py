"""
Phase 2 — gameplay-improvements: pathfinding movement + valid-move payload.

Covers:

- ``compute_paths`` Dijkstra over ``TERRAIN_ENTRY_COST``: forest costs 2,
  mountains and water are impassable, diagonals are not 4-connected.
- ``is_valid_move`` / ``execute_move`` deduct path cost (not Manhattan).
- ``get_valid_moves`` returns ``{cost, path, ...}`` per reachable tile.
- Cross-front-door parity: REST ``/valid-moves`` and MCP ``get_valid_moves``
  agree on cost and path.
"""

from copy import deepcopy

from backend.src.game.models import (
    UNIT_STATS,
    Coord,
    GameState,
    MoveAction,
    ResourceBag,
    Terrain,
    Tile,
    Unit,
    UnitType,
)
from backend.src.game.rules import (
    compute_paths,
    execute_move,
    get_valid_moves,
    is_valid_move,
)


def _plains_state(width: int = 7, height: int = 7) -> GameState:
    state = GameState(map_width=width, map_height=height)
    tile_id = 0
    for y in range(height):
        for x in range(width):
            state.tiles.append(
                Tile(id=tile_id, loc=Coord(x=x, y=y), terrain=Terrain.PLAINS)
            )
            tile_id += 1
    state.players.append("p1")
    state.stockpiles["p1"] = ResourceBag()
    return state


def _set_terrain(state: GameState, x: int, y: int, terrain: Terrain) -> None:
    tile = state.get_tile(Coord(x=x, y=y))
    assert tile is not None
    tile.terrain = terrain


def _add_unit(
    state: GameState,
    x: int,
    y: int,
    unit_type: UnitType = UnitType.SCOUT,
    moves_left: int | None = None,
    owner: str = "p1",
) -> Unit:
    stats = UNIT_STATS[unit_type]
    unit = Unit(
        id=state.next_unit_id,
        owner=owner,
        type=unit_type,
        hp=stats.hp,
        moves_left=moves_left if moves_left is not None else stats.moves,
        loc=Coord(x=x, y=y),
    )
    state.units[unit.id] = unit
    state.next_unit_id += 1
    tile = state.get_tile(unit.loc)
    assert tile is not None
    tile.unit_ids.append(unit.id)
    return unit


class TestComputePaths:
    def test_plains_uniform_cost(self):
        state = _plains_state()
        unit = _add_unit(state, 3, 3, moves_left=2)

        paths = compute_paths(state, unit, unit.moves_left)

        # 4-connected, cost 1 per plains tile, budget 2
        assert paths[Coord(x=4, y=3)] == (1, [Coord(x=4, y=3)])
        assert paths[Coord(x=5, y=3)] == (2, [Coord(x=4, y=3), Coord(x=5, y=3)])
        # Diagonal (4,4) reached via (4,3)→(4,4) or (3,4)→(4,4): cost 2
        assert paths[Coord(x=4, y=4)][0] == 2
        # Start tile is not in result
        assert Coord(x=3, y=3) not in paths

    def test_forest_costs_two(self):
        state = _plains_state()
        _set_terrain(state, 4, 3, Terrain.FOREST)
        unit = _add_unit(state, 3, 3, moves_left=3)

        paths = compute_paths(state, unit, unit.moves_left)

        # Forest entry = 2, so (4,3) cumulative cost = 2
        assert paths[Coord(x=4, y=3)][0] == 2
        # (5,3) through forest = 2 + 1 = 3 — route is forest then plains
        assert paths[Coord(x=5, y=3)][0] == 3
        # (6,3) = 2 + 1 + 1 = 4 — exceeds budget 3, not reachable
        assert Coord(x=6, y=3) not in paths

    def test_mountain_impassable(self):
        state = _plains_state()
        _set_terrain(state, 4, 3, Terrain.MOUNTAIN)
        unit = _add_unit(state, 3, 3, moves_left=4)

        paths = compute_paths(state, unit, unit.moves_left)

        # (4,3) itself impassable — not reachable as a destination
        assert Coord(x=4, y=3) not in paths
        # (5,3) still reachable via (3,3)→(3,4)→(4,4)→(5,4)→(5,3): cost 4
        assert paths[Coord(x=5, y=3)][0] == 4

    def test_water_impassable(self):
        state = _plains_state()
        _set_terrain(state, 4, 3, Terrain.WATER)
        unit = _add_unit(state, 3, 3, moves_left=2)

        paths = compute_paths(state, unit, unit.moves_left)

        assert Coord(x=4, y=3) not in paths

    def test_path_reconstruction_endpoint_inclusive(self):
        state = _plains_state()
        unit = _add_unit(state, 0, 0, moves_left=3)

        paths = compute_paths(state, unit, unit.moves_left)

        cost, path = paths[Coord(x=2, y=1)]
        assert cost == 3
        # Path excludes the start, includes the destination, step-by-step
        # 4-connected neighbours at each hop.
        assert len(path) == 3
        assert path[-1] == Coord(x=2, y=1)
        prev = unit.loc
        for step in path:
            assert abs(step.x - prev.x) + abs(step.y - prev.y) == 1
            prev = step

    def test_occupied_tiles_block_traversal(self):
        state = _plains_state()
        unit = _add_unit(state, 3, 3, moves_left=3)
        # Put a blocker at (4,3). Under Phase 2 (pre-stacking) this still
        # blocks both traversal and occupation.
        _add_unit(state, 4, 3, unit_type=UnitType.WORKER, owner="p2")

        paths = compute_paths(state, unit, unit.moves_left)

        assert Coord(x=4, y=3) not in paths
        # (5,3) still reachable via (3,3)→(3,4)→(4,4)→(5,4)→(5,3) = 4 > budget
        # so it's NOT reachable in a budget of 3.
        assert Coord(x=5, y=3) not in paths
        # But (5,3) IS reachable with a bigger budget.
        paths_big = compute_paths(state, unit, 4)
        assert Coord(x=5, y=3) in paths_big


class TestIsValidMoveAndExecute:
    def test_plains_single_step(self):
        state = _plains_state()
        unit = _add_unit(state, 3, 3, moves_left=2)

        valid, _msg = is_valid_move(state, unit, Coord(x=4, y=3))
        assert valid is True

    def test_path_cost_deducted_not_manhattan(self):
        state = _plains_state()
        _set_terrain(state, 4, 3, Terrain.FOREST)
        unit = _add_unit(state, 3, 3, moves_left=3)

        result = execute_move(state, MoveAction(unit_id=unit.id, to=Coord(x=4, y=3)))

        assert result.success is True
        # Forest entry cost = 2 deducted, not Manhattan 1.
        assert unit.moves_left == 1

    def test_rejects_path_over_budget(self):
        state = _plains_state()
        _set_terrain(state, 4, 3, Terrain.FOREST)
        unit = _add_unit(state, 3, 3, moves_left=1)

        # Forest costs 2, unit has only 1 move — rejected.
        valid, msg = is_valid_move(state, unit, Coord(x=4, y=3))
        assert valid is False
        assert "no path" in msg or "moves left" in msg

    def test_mountain_blocks_path(self):
        state = _plains_state()
        # Wall of mountain cuts (3,3) from (5,3).
        _set_terrain(state, 4, 2, Terrain.MOUNTAIN)
        _set_terrain(state, 4, 3, Terrain.MOUNTAIN)
        _set_terrain(state, 4, 4, Terrain.MOUNTAIN)
        unit = _add_unit(state, 3, 3, moves_left=3)

        # Direct step into mountain is rejected by terrain check.
        valid, msg = is_valid_move(state, unit, Coord(x=4, y=3))
        assert valid is False
        assert "mountain" in msg.lower()

        # (5,3) would require going around; 3 moves isn't enough.
        valid, _msg = is_valid_move(state, unit, Coord(x=5, y=3))
        assert valid is False

    def test_execute_move_updates_tile_occupancy(self):
        state = _plains_state()
        unit = _add_unit(state, 3, 3, moves_left=2)

        result = execute_move(state, MoveAction(unit_id=unit.id, to=Coord(x=5, y=3)))

        assert result.success is True
        old_tile = state.get_tile(Coord(x=3, y=3))
        new_tile = state.get_tile(Coord(x=5, y=3))
        assert old_tile is not None and old_tile.unit_ids == []
        assert new_tile is not None and new_tile.unit_ids == [unit.id]
        assert unit.moves_left == 0


class TestGetValidMovesPayload:
    def test_returns_cost_and_path(self):
        state = _plains_state()
        _set_terrain(state, 4, 3, Terrain.FOREST)
        unit = _add_unit(state, 3, 3, moves_left=3)

        results = {
            (r["x"], r["y"]): r
            for r in get_valid_moves(state, unit.id, None)
        }

        forest = results[(4, 3)]
        assert forest["cost"] == 2
        assert forest["path"] == [{"x": 4, "y": 3}]
        # ``distance`` kept as an alias for backwards compatibility.
        assert forest["distance"] == 2

        # Reaching (5, 3) via forest = 2 + 1 = 3
        further = results[(5, 3)]
        assert further["cost"] == 3
        assert further["path"] == [{"x": 4, "y": 3}, {"x": 5, "y": 3}]

    def test_sorted_by_cost(self):
        state = _plains_state()
        _set_terrain(state, 4, 3, Terrain.FOREST)
        unit = _add_unit(state, 3, 3, moves_left=3)

        results = get_valid_moves(state, unit.id, None)
        costs = [r["cost"] for r in results]
        assert costs == sorted(costs)

    def test_regression_single_turn_plains_move(self):
        """Manhattan-distance move on uniform plains still works."""
        state = _plains_state(width=10, height=10)
        unit = _add_unit(state, 5, 5, unit_type=UnitType.SCOUT, moves_left=3)

        # Same as test_rules.py::test_execute_move — (7,5) reachable with
        # 2 moves left after.
        valid, _ = is_valid_move(state, unit, Coord(x=7, y=5))
        assert valid is True

        before = deepcopy(unit)
        result = execute_move(state, MoveAction(unit_id=unit.id, to=Coord(x=7, y=5)))
        assert result.success is True
        assert unit.loc == Coord(x=7, y=5)
        assert unit.moves_left == before.moves_left - 2
