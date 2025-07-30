"""
Tests for Pydantic models.
"""

import pytest
from pydantic import ValidationError

from backend.src.game.models import (
    UNIT_STATS,
    AttackAction,
    Coord,
    GameState,
    MoveAction,
    ResourceBag,
    Terrain,
    Tile,
    Unit,
    UnitType,
)


class TestCoord:
    """Test coordinate model."""

    def test_coord_creation(self):
        coord = Coord(x=5, y=10)
        assert coord.x == 5
        assert coord.y == 10

    def test_coord_distance(self):
        coord1 = Coord(x=0, y=0)
        coord2 = Coord(x=3, y=4)
        assert coord1.distance_to(coord2) == 7  # Manhattan distance

    def test_coord_hash(self):
        coord1 = Coord(x=5, y=10)
        coord2 = Coord(x=5, y=10)
        coord3 = Coord(x=10, y=5)

        assert hash(coord1) == hash(coord2)
        assert hash(coord1) != hash(coord3)


class TestResourceBag:
    """Test resource bag model."""

    def test_resource_bag_creation(self):
        bag = ResourceBag(food=10, wood=5)
        assert bag.food == 10
        assert bag.wood == 5
        assert bag.ore == 0  # Default value
        assert bag.crystal == 0

    def test_resource_bag_addition(self):
        bag1 = ResourceBag(food=10, wood=5)
        bag2 = ResourceBag(food=5, ore=3)
        result = bag1 + bag2

        assert result.food == 15
        assert result.wood == 5
        assert result.ore == 3
        assert result.crystal == 0

    def test_resource_bag_subtraction(self):
        bag1 = ResourceBag(food=10, wood=5, ore=3)
        bag2 = ResourceBag(food=5, wood=2)
        result = bag1 - bag2

        assert result.food == 5
        assert result.wood == 3
        assert result.ore == 3
        assert result.crystal == 0

    def test_can_afford(self):
        bag = ResourceBag(food=10, wood=5, ore=3)
        cost1 = ResourceBag(food=5, wood=2)
        cost2 = ResourceBag(food=15, wood=2)
        cost3 = ResourceBag(food=5, wood=2, crystal=1)

        assert bag.can_afford(cost1) is True
        assert bag.can_afford(cost2) is False  # Not enough food
        assert bag.can_afford(cost3) is False  # No crystal


class TestUnit:
    """Test unit model."""

    def test_unit_creation(self):
        unit = Unit(
            id=1,
            owner="player1",
            type=UnitType.SCOUT,
            hp=2,
            moves_left=3,
            loc=Coord(x=5, y=5),
        )

        assert unit.id == 1
        assert unit.owner == "player1"
        assert unit.type == UnitType.SCOUT
        assert unit.hp == 2
        assert unit.moves_left == 3

    def test_unit_stats(self):
        unit = Unit(
            id=1,
            owner="player1",
            type=UnitType.SCOUT,
            hp=2,
            moves_left=3,
            loc=Coord(x=5, y=5),
        )

        stats = unit.stats
        assert stats == UNIT_STATS[UnitType.SCOUT]
        assert stats.moves == 3
        assert stats.sight == 3

    def test_unit_can_attack(self):
        archer = Unit(
            id=1,
            owner="player1",
            type=UnitType.ARCHER,
            hp=3,
            moves_left=2,
            loc=Coord(x=5, y=5),
        )

        # Archer has range 2
        assert archer.can_attack(Coord(x=5, y=7)) is True  # Distance 2
        assert archer.can_attack(Coord(x=7, y=5)) is True  # Distance 2
        assert archer.can_attack(Coord(x=8, y=5)) is False  # Distance 3

        worker = Unit(
            id=2,
            owner="player1",
            type=UnitType.WORKER,
            hp=2,
            moves_left=2,
            loc=Coord(x=5, y=5),
        )

        # Worker cannot attack (attack = 0)
        assert worker.can_attack(Coord(x=5, y=6)) is False


class TestGameState:
    """Test game state model."""

    def test_game_state_creation(self):
        state = GameState()
        assert state.turn == 0
        assert state.map_width == 20
        assert state.map_height == 20
        assert len(state.tiles) == 0
        assert len(state.units) == 0
        assert len(state.cities) == 0

    def test_get_tile(self):
        state = GameState()
        tile = Tile(
            id=1,
            loc=Coord(x=5, y=5),
            terrain=Terrain.PLAINS,
        )
        state.tiles.append(tile)

        found_tile = state.get_tile(Coord(x=5, y=5))
        assert found_tile == tile

        not_found = state.get_tile(Coord(x=10, y=10))
        assert not_found is None

    def test_diplomatic_state(self):
        state = GameState()
        state.players = ["player1", "player2", "player3"]

        # Same player should be alliance
        assert state.get_diplomatic_state("player1", "player1") == "alliance"

        # Default should be peace
        assert state.get_diplomatic_state("player1", "player2") == "peace"

        # Set war
        state.diplomacy[("player1", "player2")] = "war"
        assert state.get_diplomatic_state("player1", "player2") == "war"
        assert state.get_diplomatic_state("player2", "player1") == "war"  # Symmetric

    def test_state_hash_deterministic(self):
        state1 = GameState(turn=5, rng_state=42)
        state2 = GameState(turn=5, rng_state=42)

        # Same state should produce same hash
        assert state1.hash_state() == state2.hash_state()

        # Different state should produce different hash
        state3 = GameState(turn=6, rng_state=42)
        assert state1.hash_state() != state3.hash_state()


class TestActions:
    """Test action models."""

    def test_move_action(self):
        action = MoveAction(unit_id=1, to=Coord(x=5, y=5))
        assert action.type == "MOVE"
        assert action.unit_id == 1
        assert action.to == Coord(x=5, y=5)

    def test_attack_action(self):
        action = AttackAction(
            attacker_id=1,
            target_id=2,
            target_type="unit",
        )
        assert action.type == "ATTACK"
        assert action.attacker_id == 1
        assert action.target_id == 2
        assert action.target_type == "unit"

    def test_action_validation(self):
        # Valid action
        action = MoveAction(unit_id=1, to=Coord(x=5, y=5))
        assert action.unit_id == 1

        # Invalid action should raise validation error
        with pytest.raises(ValidationError):
            MoveAction(unit_id="invalid", to=Coord(x=5, y=5))
