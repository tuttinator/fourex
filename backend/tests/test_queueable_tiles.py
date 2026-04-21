"""
Tests for Phase 5 ``get_queueable_tiles`` helper.

Mirrors ``get_valid_moves`` but with no movement budget — the client
uses this to offer multi-turn destinations.
"""

from backend.src.game.models import (
    UNIT_STATS,
    Coord,
    GameState,
    ResourceBag,
    Terrain,
    Tile,
    Unit,
    UnitType,
)
from backend.src.game.rules import get_queueable_tiles


def _make_state(width: int = 7, height: int = 3) -> GameState:
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


def _add_unit(state: GameState, x: int, y: int, owner: str = "p1") -> Unit:
    stats = UNIT_STATS[UnitType.SCOUT]
    unit = Unit(
        id=state.next_unit_id,
        owner=owner,
        type=UnitType.SCOUT,
        hp=stats.hp,
        moves_left=stats.moves,
        loc=Coord(x=x, y=y),
    )
    state.units[unit.id] = unit
    state.next_unit_id += 1
    tile = state.get_tile(Coord(x=x, y=y))
    assert tile is not None
    tile.unit_ids.append(unit.id)
    return unit


def _all_coords(state: GameState) -> set[Coord]:
    return {tile.loc for tile in state.tiles}


def test_queueable_exceeds_moves_left():
    state = _make_state(width=7)
    unit = _add_unit(state, 0, 1)

    tiles = get_queueable_tiles(state, unit.id, _all_coords(state))

    # Every reachable tile except the unit's own should be present,
    # including tiles beyond the scout's movement budget.
    coords = {(t["x"], t["y"]) for t in tiles}
    assert (6, 1) in coords  # cost 6, unreachable this turn (moves=3)
    assert (0, 0) in coords


def test_queueable_includes_path_and_turns_required():
    state = _make_state(width=7)
    unit = _add_unit(state, 0, 1)

    tiles = get_queueable_tiles(state, unit.id, _all_coords(state))
    by_coord = {(t["x"], t["y"]): t for t in tiles}

    far = by_coord[(6, 1)]
    assert far["cost"] == 6
    assert far["turns_required"] >= 2
    assert far["path"][-1] == {"x": 6, "y": 1}


def test_queueable_respects_visibility():
    state = _make_state(width=7)
    unit = _add_unit(state, 0, 1)

    visible = {Coord(x=x, y=1) for x in range(7)}
    tiles = get_queueable_tiles(state, unit.id, visible)
    coords = {(t["x"], t["y"]) for t in tiles}

    # Only the row-1 strip should be returned.
    assert all(y == 1 for _, y in coords)


def test_queueable_blocks_on_impassable():
    state = _make_state(width=7)
    # Build a mountain wall at x=3 along y=0..2 so (4..6) are unreachable.
    for y in range(3):
        wall = state.get_tile(Coord(x=3, y=y))
        assert wall is not None
        wall.terrain = Terrain.MOUNTAIN

    unit = _add_unit(state, 0, 1)
    tiles = get_queueable_tiles(state, unit.id, _all_coords(state))
    coords = {(t["x"], t["y"]) for t in tiles}

    assert (2, 1) in coords
    assert (4, 1) not in coords
    assert (6, 1) not in coords
