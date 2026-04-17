"""
Tests for Phase 5: Unit healing.

Units heal +1 HP per turn when stationary (did not move this turn) and on
a tile owned by their player. Scouts are excluded. Healing is capped at
the unit's max HP and consumes no resources.
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
from backend.src.game.rules import heal_units, resolve_turn


def _make_state(width: int = 5, height: int = 5) -> GameState:
    """Create a game state with a plains grid and one player."""
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
    state.players.append("p1")
    state.stockpiles["p1"] = ResourceBag()
    return state


def _add_unit(
    state: GameState,
    unit_type: UnitType,
    x: int,
    y: int,
    owner: str = "p1",
    hp: int | None = None,
) -> Unit:
    """Add a unit at the given coord. Defaults to max HP."""
    stats = UNIT_STATS[unit_type]
    unit = Unit(
        id=state.next_unit_id,
        owner=owner,
        type=unit_type,
        hp=hp if hp is not None else stats.hp,
        moves_left=stats.moves,
        loc=Coord(x=x, y=y),
    )
    state.units[unit.id] = unit
    state.next_unit_id += 1
    tile = state.get_tile(Coord(x=x, y=y))
    assert tile is not None
    tile.unit_id = unit.id
    return unit


def _claim_tile(state: GameState, x: int, y: int, owner: str = "p1") -> Tile:
    tile = state.get_tile(Coord(x=x, y=y))
    assert tile is not None
    tile.owner = owner
    return tile


class TestHealUnits:
    """Direct tests for heal_units() behaviour."""

    def test_soldier_heals_in_friendly_territory(self):
        state = _make_state()
        _claim_tile(state, 2, 2)
        soldier = _add_unit(state, UnitType.SOLDIER, 2, 2, hp=1)

        heal_units(state)

        assert soldier.hp == 2

    def test_healing_caps_at_max_hp(self):
        state = _make_state()
        _claim_tile(state, 2, 2)
        soldier = _add_unit(state, UnitType.SOLDIER, 2, 2, hp=4)

        heal_units(state)

        assert soldier.hp == UNIT_STATS[UnitType.SOLDIER].hp

    def test_healing_stops_at_max_hp(self):
        state = _make_state()
        _claim_tile(state, 2, 2)
        archer = _add_unit(state, UnitType.ARCHER, 2, 2, hp=2)

        heal_units(state)
        heal_units(state)
        heal_units(state)

        assert archer.hp == UNIT_STATS[UnitType.ARCHER].hp

    def test_scout_does_not_heal(self):
        state = _make_state()
        _claim_tile(state, 2, 2)
        scout = _add_unit(state, UnitType.SCOUT, 2, 2, hp=1)

        heal_units(state)

        assert scout.hp == 1

    def test_worker_heals(self):
        state = _make_state()
        _claim_tile(state, 2, 2)
        worker = _add_unit(state, UnitType.WORKER, 2, 2, hp=1)

        heal_units(state)

        assert worker.hp == 2

    def test_archer_heals(self):
        state = _make_state()
        _claim_tile(state, 2, 2)
        archer = _add_unit(state, UnitType.ARCHER, 2, 2, hp=1)

        heal_units(state)

        assert archer.hp == 2

    def test_unit_that_moved_does_not_heal(self):
        state = _make_state()
        _claim_tile(state, 2, 2)
        soldier = _add_unit(state, UnitType.SOLDIER, 2, 2, hp=1)
        soldier.moves_left = 0

        heal_units(state)

        assert soldier.hp == 1

    def test_unit_on_unowned_tile_does_not_heal(self):
        state = _make_state()
        soldier = _add_unit(state, UnitType.SOLDIER, 2, 2, hp=1)

        heal_units(state)

        assert soldier.hp == 1

    def test_unit_on_enemy_tile_does_not_heal(self):
        state = _make_state()
        state.players.append("p2")
        _claim_tile(state, 2, 2, owner="p2")
        soldier = _add_unit(state, UnitType.SOLDIER, 2, 2, hp=1)

        heal_units(state)

        assert soldier.hp == 1

    def test_healing_does_not_consume_resources(self):
        state = _make_state()
        _claim_tile(state, 2, 2)
        _add_unit(state, UnitType.SOLDIER, 2, 2, hp=1)
        state.stockpiles["p1"] = ResourceBag(food=5, wood=5, ore=5, crystal=5)

        heal_units(state)

        assert state.stockpiles["p1"] == ResourceBag(
            food=5, wood=5, ore=5, crystal=5
        )

    def test_full_hp_unit_unchanged(self):
        state = _make_state()
        _claim_tile(state, 2, 2)
        soldier = _add_unit(state, UnitType.SOLDIER, 2, 2)
        max_hp = UNIT_STATS[UnitType.SOLDIER].hp

        heal_units(state)

        assert soldier.hp == max_hp

    def test_only_stationary_units_heal(self):
        state = _make_state()
        _claim_tile(state, 1, 1)
        _claim_tile(state, 2, 2)
        stationary = _add_unit(state, UnitType.SOLDIER, 1, 1, hp=1)
        moved = _add_unit(state, UnitType.SOLDIER, 2, 2, hp=1)
        moved.moves_left = 1

        heal_units(state)

        assert stationary.hp == 2
        assert moved.hp == 1


class TestHealingInResolveTurn:
    """Integration tests: healing runs as part of resolve_turn()."""

    def test_healing_runs_during_turn_resolution(self):
        state = _make_state()
        _claim_tile(state, 2, 2)
        soldier = _add_unit(state, UnitType.SOLDIER, 2, 2, hp=1)

        resolve_turn(state, {"p1": []})

        assert soldier.hp == 2

    def test_moving_unit_does_not_heal_same_turn(self):
        from backend.src.game.models import MoveAction

        state = _make_state()
        _claim_tile(state, 2, 2)
        _claim_tile(state, 2, 3)
        soldier = _add_unit(state, UnitType.SOLDIER, 2, 2, hp=1)

        resolve_turn(
            state,
            {"p1": [MoveAction(unit_id=soldier.id, to=Coord(x=2, y=3))]},
        )

        assert soldier.hp == 1
