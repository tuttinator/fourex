"""
Tests for Phase 6: get_valid_moves pure function.

Returns all legal move destinations for a unit, filtered by Manhattan
distance <= moves_left, passable terrain, unoccupied tiles, and (when
supplied) a visibility mask for fog-of-war.
"""

from backend.src.game.models import (
    UNIT_STATS,
    Coord,
    GameState,
    ImprovementType,
    Resource,
    ResourceBag,
    Terrain,
    Tile,
    Unit,
    UnitType,
)
from backend.src.game.rules import get_valid_moves


def _make_state(width: int = 5, height: int = 5) -> GameState:
    """Plains grid with one player."""
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
    unit_type: UnitType,
    x: int,
    y: int,
    owner: str = "p1",
    moves_left: int | None = None,
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
    tile = state.get_tile(Coord(x=x, y=y))
    assert tile is not None
    tile.unit_id = unit.id
    return unit


def _all_coords(state: GameState) -> set[Coord]:
    return {tile.loc for tile in state.tiles}


class TestGetValidMoves:
    def test_open_plains_returns_all_in_range(self):
        state = _make_state()
        unit = _add_unit(state, UnitType.SOLDIER, 2, 2)  # moves=2

        results = get_valid_moves(state, unit.id, _all_coords(state))

        # Soldier at (2,2) with 2 moves: every tile with Manhattan <= 2
        # on a 5x5 plains grid, excluding the unit's own tile.
        expected = {
            (x, y)
            for x in range(5)
            for y in range(5)
            if 0 < abs(x - 2) + abs(y - 2) <= 2
        }
        assert {(r["x"], r["y"]) for r in results} == expected
        for r in results:
            assert r["terrain"] == "plains"
            assert r["has_resource"] is False
            assert r["resource_type"] is None
            assert r["has_improvement"] is False
            assert r["owner"] is None
            assert 1 <= r["distance"] <= 2

    def test_mountains_and_water_excluded(self):
        state = _make_state()
        _set_terrain(state, 3, 2, Terrain.MOUNTAIN)
        _set_terrain(state, 2, 3, Terrain.WATER)
        unit = _add_unit(state, UnitType.SOLDIER, 2, 2)

        results = get_valid_moves(state, unit.id, _all_coords(state))
        coords = {(r["x"], r["y"]) for r in results}

        assert (3, 2) not in coords
        assert (2, 3) not in coords
        assert (1, 2) in coords
        assert (2, 1) in coords

    def test_occupied_tiles_excluded(self):
        state = _make_state()
        unit = _add_unit(state, UnitType.SOLDIER, 2, 2)
        _add_unit(state, UnitType.WORKER, 3, 2)

        results = get_valid_moves(state, unit.id, _all_coords(state))
        coords = {(r["x"], r["y"]) for r in results}

        assert (3, 2) not in coords
        assert (1, 2) in coords

    def test_fog_of_war_filters_invisible_tiles(self):
        state = _make_state()
        unit = _add_unit(state, UnitType.SOLDIER, 2, 2)
        visible = {Coord(x=2, y=2), Coord(x=3, y=2), Coord(x=2, y=3)}

        results = get_valid_moves(state, unit.id, visible)
        coords = {(r["x"], r["y"]) for r in results}

        assert coords == {(3, 2), (2, 3)}

    def test_zero_moves_left_returns_empty(self):
        state = _make_state()
        unit = _add_unit(state, UnitType.SOLDIER, 2, 2, moves_left=0)

        results = get_valid_moves(state, unit.id, _all_coords(state))
        assert results == []

    def test_unknown_unit_returns_empty(self):
        state = _make_state()
        results = get_valid_moves(state, 999, _all_coords(state))
        assert results == []

    def test_none_visible_coords_disables_filter(self):
        state = _make_state()
        unit = _add_unit(state, UnitType.SOLDIER, 2, 2)

        results_all = get_valid_moves(state, unit.id, None)
        results_full = get_valid_moves(state, unit.id, _all_coords(state))

        assert {(r["x"], r["y"]) for r in results_all} == {
            (r["x"], r["y"]) for r in results_full
        }

    def test_results_include_tile_metadata(self):
        state = _make_state()
        # Give (3, 2) a wood resource and a lumber mill; (1, 2) has an owner.
        wood_tile = state.get_tile(Coord(x=3, y=2))
        assert wood_tile is not None
        wood_tile.terrain = Terrain.FOREST
        wood_tile.resource = Resource.WOOD
        wood_tile.improvement = ImprovementType.LUMBER_MILL
        owned_tile = state.get_tile(Coord(x=1, y=2))
        assert owned_tile is not None
        owned_tile.owner = "p1"
        unit = _add_unit(state, UnitType.SOLDIER, 2, 2)

        results = {(r["x"], r["y"]): r for r in get_valid_moves(
            state, unit.id, _all_coords(state)
        )}

        forest = results[(3, 2)]
        assert forest["terrain"] == "forest"
        assert forest["has_resource"] is True
        assert forest["resource_type"] == "wood"
        assert forest["has_improvement"] is True
        # Forest entry cost is 2 (TERRAIN_ENTRY_COST) — one step into the
        # forest from plains costs 2 movement, not Manhattan distance 1.
        assert forest["cost"] == 2
        assert forest["distance"] == 2
        assert forest["path"] == [{"x": 3, "y": 2}]

        owned = results[(1, 2)]
        assert owned["owner"] == "p1"

    def test_scout_has_three_moves(self):
        state = _make_state(width=7, height=7)
        unit = _add_unit(state, UnitType.SCOUT, 3, 3)  # moves=3

        results = get_valid_moves(state, unit.id, _all_coords(state))
        max_distance = max(r["distance"] for r in results)
        assert max_distance == 3

    def test_results_sorted_by_distance(self):
        state = _make_state()
        unit = _add_unit(state, UnitType.SOLDIER, 2, 2)

        results = get_valid_moves(state, unit.id, _all_coords(state))
        distances = [r["distance"] for r in results]
        assert distances == sorted(distances)
