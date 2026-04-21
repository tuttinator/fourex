"""
Phase 3: Friendly unit stacking.

Covers PRD acceptance criteria:
- Tile.unit_ids replaces Tile.unit_id in models and redaction.
- Up to 5 units may occupy a single tile; the 6th move is rejected.
- validate_actions accepts moves onto friendly-occupied tiles under the cap.
- AttackAction.target_tile picks a random defender via seeded RNG; same seed +
  actions produces identical defender choice across replays.
- AttackAction.target_id still resolves against a specific stacked unit.
- Units on a friendly city tile take 25% less damage when attacked.
- Redacted state exposes only visible stacked units.
"""

from __future__ import annotations

import pytest

from backend.src.game.models import (
    FORTIFICATION_CITY_DEFENCE_BONUS,
    STACK_CAP,
    UNIT_STATS,
    AttackAction,
    City,
    Coord,
    GameState,
    MoveAction,
    ResourceBag,
    Terrain,
    Tile,
    Unit,
    UnitStats,
    UnitType,
)
from backend.src.game.rules import (
    execute_attack,
    is_valid_move,
    redact_state,
    resolve_turn,
)


def _make_state(width: int = 7, height: int = 7) -> GameState:
    state = GameState(map_width=width, map_height=height)
    tile_id = 0
    for y in range(height):
        for x in range(width):
            state.tiles.append(
                Tile(id=tile_id, loc=Coord(x=x, y=y), terrain=Terrain.PLAINS)
            )
            tile_id += 1
    for player in ("p1", "p2"):
        state.players.append(player)
        state.stockpiles[player] = ResourceBag()
    return state


def _add_unit(
    state: GameState,
    unit_type: UnitType,
    x: int,
    y: int,
    owner: str = "p1",
    hp: int | None = None,
) -> Unit:
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
    tile.unit_ids.append(unit.id)
    return unit


def _place_city(
    state: GameState, x: int, y: int, owner: str = "p1", name: str = "cap"
) -> City:
    tile = state.get_tile(Coord(x=x, y=y))
    assert tile is not None
    city = City(
        id=state.next_city_id,
        owner=owner,
        name=name,
        loc=Coord(x=x, y=y),
    )
    state.cities[city.id] = city
    state.next_city_id += 1
    tile.city_id = city.id
    tile.owner = owner
    return city


class TestStackCap:
    def test_move_onto_friendly_tile_under_cap_accepted(self):
        state = _make_state()
        # Four existing friendlies on destination (3,3): below cap.
        for _ in range(4):
            _add_unit(state, UnitType.WORKER, 3, 3)
        mover = _add_unit(state, UnitType.SOLDIER, 3, 2)

        ok, _msg = is_valid_move(state, mover, Coord(x=3, y=3))
        assert ok

    def test_move_rejected_when_destination_at_cap(self):
        state = _make_state()
        for _ in range(STACK_CAP):
            _add_unit(state, UnitType.WORKER, 3, 3)
        mover = _add_unit(state, UnitType.SOLDIER, 3, 2)

        ok, msg = is_valid_move(state, mover, Coord(x=3, y=3))
        assert not ok
        assert "stack cap" in msg.lower()

    def test_enemy_occupied_tile_still_blocks(self):
        state = _make_state()
        _add_unit(state, UnitType.SOLDIER, 3, 3, owner="p2")
        mover = _add_unit(state, UnitType.SOLDIER, 3, 2, owner="p1")

        ok, msg = is_valid_move(state, mover, Coord(x=3, y=3))
        assert not ok
        assert "enemy" in msg.lower()

    def test_resolve_turn_rejects_move_exceeding_cap(self):
        state = _make_state()
        for _ in range(STACK_CAP):
            _add_unit(state, UnitType.WORKER, 3, 3)
        mover = _add_unit(state, UnitType.SOLDIER, 3, 2)

        resolve_turn(state, {"p1": [MoveAction(unit_id=mover.id, to=Coord(x=3, y=3))]})

        # Mover must remain on its origin tile; cap on destination unchanged.
        assert mover.loc == Coord(x=3, y=2)
        dest = state.get_tile(Coord(x=3, y=3))
        assert dest is not None
        assert len(dest.unit_ids) == STACK_CAP


class TestAttackTargeting:
    def test_target_id_selects_specific_stacked_unit(self):
        state = _make_state()
        # Two defenders stacked at (3,3).
        d1 = _add_unit(state, UnitType.SOLDIER, 3, 3, owner="p2", hp=3)
        d2 = _add_unit(state, UnitType.WORKER, 3, 3, owner="p2", hp=2)
        attacker = _add_unit(state, UnitType.SOLDIER, 3, 2, owner="p1")

        execute_attack(
            state,
            AttackAction(
                attacker_id=attacker.id,
                target_id=d2.id,
                target_type="unit",
            ),
        )

        # d2 was specifically targeted — d1 untouched.
        assert state.units[d1.id].hp == 3
        assert d2.id not in state.units or state.units[d2.id].hp < 2

    def test_target_tile_picks_hostile_defender_deterministically(self):
        """Same seed + identical actions => identical defender chosen."""

        def run() -> int:
            state = _make_state()
            state.rng_state = 12345
            state.turn = 7
            for _ in range(3):
                _add_unit(state, UnitType.WORKER, 3, 3, owner="p2", hp=2)
            attacker = _add_unit(state, UnitType.SOLDIER, 3, 2, owner="p1")
            # Snapshot tile occupants before attack.
            tile = state.get_tile(Coord(x=3, y=3))
            assert tile is not None
            before = set(tile.unit_ids)
            execute_attack(
                state,
                AttackAction(
                    attacker_id=attacker.id,
                    target_tile=Coord(x=3, y=3),
                    target_type="unit",
                ),
            )
            # Whichever defender was chosen will have hp < 2 (or be dead).
            for uid in before:
                unit = state.units.get(uid)
                if unit is None or unit.hp < 2:
                    return uid
            raise AssertionError("No defender was damaged")

        choice_a = run()
        choice_b = run()
        assert choice_a == choice_b

    def test_target_tile_without_hostile_defender_errors(self):
        state = _make_state()
        _add_unit(state, UnitType.WORKER, 3, 3, owner="p1")
        attacker = _add_unit(state, UnitType.SOLDIER, 3, 2, owner="p1")

        result = execute_attack(
            state,
            AttackAction(
                attacker_id=attacker.id,
                target_tile=Coord(x=3, y=3),
                target_type="unit",
            ),
        )
        assert not result.success

    def test_attack_action_requires_exactly_one_target(self):
        with pytest.raises(ValueError):
            AttackAction(attacker_id=1, target_type="unit")
        with pytest.raises(ValueError):
            AttackAction(
                attacker_id=1,
                target_id=2,
                target_tile=Coord(x=0, y=0),
                target_type="unit",
            )


class TestFortificationBonus:
    def test_defender_on_friendly_city_takes_reduced_damage(self, monkeypatch):
        # Patch archer attack to 4 so raw damage is 4 on plain terrain and
        # round(3.0)=3 with fortification — without a patch, every base unit's
        # attack is 2 and rounding would erase the difference.
        monkeypatch.setitem(
            UNIT_STATS,
            UnitType.ARCHER,
            UnitStats(
                cost=ResourceBag(food=15, wood=5),
                moves=2,
                hp=3,
                sight=3,
                attack=4,
                attack_range=2,
                special="Ranged; no counter-attack",
                required_tech="archery",
            ),
        )
        state_plain = _make_state()
        defender_plain = _add_unit(
            state_plain, UnitType.WORKER, 3, 3, owner="p1", hp=10
        )
        attacker_plain = _add_unit(
            state_plain, UnitType.ARCHER, 3, 2, owner="p2", hp=10
        )

        state_city = _make_state()
        _place_city(state_city, 3, 3, owner="p1")
        defender_city = _add_unit(
            state_city, UnitType.WORKER, 3, 3, owner="p1", hp=10
        )
        attacker_city = _add_unit(
            state_city, UnitType.ARCHER, 3, 2, owner="p2", hp=10
        )

        execute_attack(
            state_plain,
            AttackAction(
                attacker_id=attacker_plain.id,
                target_id=defender_plain.id,
                target_type="unit",
            ),
        )
        execute_attack(
            state_city,
            AttackAction(
                attacker_id=attacker_city.id,
                target_id=defender_city.id,
                target_type="unit",
            ),
        )

        dmg_plain = 10 - defender_plain.hp
        dmg_city = 10 - defender_city.hp
        assert dmg_city < dmg_plain
        expected = max(
            1, int(round(dmg_plain * (1 - FORTIFICATION_CITY_DEFENCE_BONUS)))
        )
        assert dmg_city == expected

    def test_no_bonus_on_enemy_city_tile(self):
        state = _make_state()
        _place_city(state, 3, 3, owner="p1")
        # Defender belongs to p2 even though standing on p1's city tile.
        defender = _add_unit(state, UnitType.WORKER, 3, 3, owner="p2", hp=10)
        attacker = _add_unit(state, UnitType.ARCHER, 3, 2, owner="p1", hp=10)

        execute_attack(
            state,
            AttackAction(
                attacker_id=attacker.id,
                target_id=defender.id,
                target_type="unit",
            ),
        )

        # Full damage should have landed (no fortification for enemy city).
        attacker_strength = UNIT_STATS[UnitType.ARCHER].attack
        defender_strength = UNIT_STATS[UnitType.WORKER].attack
        expected = max(1, attacker_strength - defender_strength // 2)
        assert 10 - defender.hp == expected


class TestRedactedStackedUnits:
    def test_redacted_state_hides_stack_on_unseen_tile(self):
        # Map is toroidal, so a 7x7 would let (0,0) see (6,6) via wrap.
        # Use a larger map to place the enemy stack truly out of sight.
        state = _make_state(width=20, height=20)
        _add_unit(state, UnitType.SCOUT, 0, 0, owner="p1")
        for _ in range(3):
            _add_unit(state, UnitType.SOLDIER, 10, 10, owner="p2")

        redacted = redact_state(state, "p1")

        assert redacted.get_tile(Coord(x=10, y=10)) is None
        assert all(u.owner != "p2" for u in redacted.units.values())

    def test_redacted_state_exposes_visible_stack(self):
        state = _make_state()
        # p1 scout adjacent to stacked enemies so they enter visibility.
        _add_unit(state, UnitType.SCOUT, 3, 2, owner="p1")
        enemy_ids = [
            _add_unit(state, UnitType.SOLDIER, 3, 3, owner="p2").id for _ in range(2)
        ]

        redacted = redact_state(state, "p1")
        tile = redacted.get_tile(Coord(x=3, y=3))
        assert tile is not None
        assert set(tile.unit_ids) == set(enemy_ids)
        for uid in enemy_ids:
            assert uid in redacted.units


class TestLegacyTileDeserialisation:
    def test_legacy_unit_id_field_is_normalised_to_unit_ids(self):
        legacy = {
            "id": 0,
            "loc": {"x": 0, "y": 0},
            "terrain": "plains",
            "unit_id": 42,
        }
        tile = Tile.model_validate(legacy)
        assert tile.unit_ids == [42]

    def test_legacy_unit_id_none_becomes_empty_list(self):
        legacy = {
            "id": 0,
            "loc": {"x": 0, "y": 0},
            "terrain": "plains",
            "unit_id": None,
        }
        tile = Tile.model_validate(legacy)
        assert tile.unit_ids == []
