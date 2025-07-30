"""
Tests for game rules and turn resolution.
"""

from backend.src.game.models import (
    AttackAction,
    City,
    Coord,
    DiplomaticState,
    FoundCityAction,
    GameState,
    MoveAction,
    ResourceBag,
    Terrain,
    Tile,
    TrainUnitAction,
    Unit,
    UnitType,
)
from backend.src.game.rules import (
    collect_resources,
    execute_attack,
    execute_found_city,
    execute_move,
    execute_train_unit,
    generate_map,
    get_neighbors,
    get_visible_tiles,
    is_valid_move,
    redact_state,
    reset_unit_moves,
    resolve_turn,
)


class TestMapGeneration:
    """Test map generation functions."""

    def test_generate_map_deterministic(self):
        """Same seed should produce same map."""
        map1 = generate_map(10, 10, seed=42)
        map2 = generate_map(10, 10, seed=42)

        assert len(map1) == len(map2) == 100

        for tile1, tile2 in zip(map1, map2):
            assert tile1.loc == tile2.loc
            assert tile1.terrain == tile2.terrain
            assert tile1.resource == tile2.resource

    def test_generate_map_different_seeds(self):
        """Different seeds should produce different maps."""
        map1 = generate_map(10, 10, seed=42)
        map2 = generate_map(10, 10, seed=43)

        # Maps should be different (very unlikely to be identical)
        terrain_differences = sum(
            1 for t1, t2 in zip(map1, map2) if t1.terrain != t2.terrain
        )
        assert terrain_differences > 0

    def test_generate_map_size(self):
        """Map should have correct size."""
        width, height = 15, 12
        tiles = generate_map(width, height, seed=42)

        assert len(tiles) == width * height

        # Check all coordinates are covered
        coords = {(tile.loc.x, tile.loc.y) for tile in tiles}
        expected_coords = {(x, y) for x in range(width) for y in range(height)}
        assert coords == expected_coords

    def test_get_neighbors(self):
        """Test neighbor calculation with wrapping."""
        neighbors = get_neighbors(Coord(x=5, y=5), width=20, height=20)
        expected = [
            Coord(x=5, y=6),  # North
            Coord(x=5, y=4),  # South
            Coord(x=6, y=5),  # East
            Coord(x=4, y=5),  # West
        ]
        assert set(neighbors) == set(expected)

        # Test wrapping at edges
        neighbors = get_neighbors(Coord(x=0, y=0), width=10, height=10)
        expected = [
            Coord(x=0, y=1),  # North
            Coord(x=0, y=9),  # South (wrapped)
            Coord(x=1, y=0),  # East
            Coord(x=9, y=0),  # West (wrapped)
        ]
        assert set(neighbors) == set(expected)


class TestVisibility:
    """Test fog-of-war and visibility rules."""

    def test_get_visible_tiles(self):
        """Test visibility calculation."""
        state = GameState(map_width=10, map_height=10)
        state.players = ["player1", "player2"]

        # Add a unit for player1
        unit = Unit(
            id=1,
            owner="player1",
            type=UnitType.SCOUT,  # Sight range 3
            hp=2,
            moves_left=3,
            loc=Coord(x=5, y=5),
        )
        state.units[1] = unit

        visible = get_visible_tiles(state, "player1")

        # Should see tiles within range 3
        assert Coord(x=5, y=5) in visible  # Unit location
        assert Coord(x=5, y=8) in visible  # Distance 3
        assert Coord(x=8, y=5) in visible  # Distance 3
        assert Coord(x=5, y=9) not in visible  # Distance 4

    def test_redact_state(self):
        """Test fog-of-war redaction."""
        state = GameState(map_width=5, map_height=5)
        state.players = ["player1", "player2"]

        # Add tiles
        for x in range(5):
            for y in range(5):
                tile = Tile(
                    id=x * 5 + y,
                    loc=Coord(x=x, y=y),
                    terrain=Terrain.PLAINS,
                )
                state.tiles.append(tile)

        # Add units
        unit1 = Unit(
            id=1,
            owner="player1",
            type=UnitType.SCOUT,
            hp=2,
            moves_left=3,
            loc=Coord(x=1, y=1),
        )
        unit2 = Unit(
            id=2,
            owner="player2",
            type=UnitType.SCOUT,
            hp=2,
            moves_left=3,
            loc=Coord(x=4, y=4),
        )
        state.units[1] = unit1
        state.units[2] = unit2

        # Redact for player1
        redacted = redact_state(state, "player1")

        # Should see own unit but not enemy unit (if not in sight range)
        assert 1 in redacted.units
        assert 2 not in redacted.units  # Too far away

        # Should only see visible tiles
        visible_coords = {tile.loc for tile in redacted.tiles}
        expected_visible = {
            Coord(x=x, y=y)
            for x in range(5)
            for y in range(5)
            if abs(x - 1) + abs(y - 1) <= 3  # Scout sight range
        }
        assert visible_coords == expected_visible


class TestMovement:
    """Test unit movement rules."""

    def test_is_valid_move(self):
        """Test movement validation."""
        state = GameState(map_width=10, map_height=10)

        # Add tiles
        for x in range(10):
            for y in range(10):
                terrain = Terrain.WATER if x == 0 else Terrain.PLAINS
                tile = Tile(
                    id=x * 10 + y,
                    loc=Coord(x=x, y=y),
                    terrain=terrain,
                )
                state.tiles.append(tile)

        # Add unit
        unit = Unit(
            id=1,
            owner="player1",
            type=UnitType.SCOUT,
            hp=2,
            moves_left=3,
            loc=Coord(x=5, y=5),
        )

        # Valid move within range
        valid, msg = is_valid_move(state, unit, Coord(x=7, y=5))
        assert valid is True

        # Invalid move - too far
        valid, msg = is_valid_move(state, unit, Coord(x=9, y=5))
        assert valid is False
        assert "moves left" in msg

        # Invalid move - into water
        valid, msg = is_valid_move(state, unit, Coord(x=0, y=5))
        assert valid is False
        assert "water" in msg.lower()

    def test_execute_move(self):
        """Test move execution."""
        state = GameState(map_width=10, map_height=10)

        # Add tiles
        for x in range(10):
            for y in range(10):
                tile = Tile(
                    id=x * 10 + y,
                    loc=Coord(x=x, y=y),
                    terrain=Terrain.PLAINS,
                )
                state.tiles.append(tile)

        # Add unit
        unit = Unit(
            id=1,
            owner="player1",
            type=UnitType.SCOUT,
            hp=2,
            moves_left=3,
            loc=Coord(x=5, y=5),
        )
        state.units[1] = unit

        # Set initial tile
        old_tile = state.get_tile(Coord(x=5, y=5))
        old_tile.unit_id = 1

        # Execute move
        action = MoveAction(unit_id=1, to=Coord(x=7, y=5))
        result = execute_move(state, action)

        assert result.success is True
        assert unit.loc == Coord(x=7, y=5)
        assert unit.moves_left == 1  # 3 - 2 (distance)

        # Check tiles updated
        assert old_tile.unit_id is None
        new_tile = state.get_tile(Coord(x=7, y=5))
        assert new_tile.unit_id == 1


class TestCombat:
    """Test combat mechanics."""

    def test_execute_attack_unit(self):
        """Test unit vs unit combat."""
        state = GameState()
        state.players = ["player1", "player2"]

        # Add attacker
        attacker = Unit(
            id=1,
            owner="player1",
            type=UnitType.SOLDIER,  # Attack 2
            hp=4,
            moves_left=2,
            loc=Coord(x=5, y=5),
        )

        # Add target
        target = Unit(
            id=2,
            owner="player2",
            type=UnitType.SCOUT,  # Attack 1
            hp=2,
            moves_left=3,
            loc=Coord(x=5, y=6),  # Adjacent
        )

        state.units[1] = attacker
        state.units[2] = target

        # Execute attack
        action = AttackAction(attacker_id=1, target_id=2, target_type="unit")
        result = execute_attack(state, action)

        assert result.success is True

        # Check damage calculation: attacker_strength - defender_strength/2
        # Attacker does 2 - 1/2 = 1.5 -> 1 damage (floored, min 1)
        # Target does 1 - 2/2 = 0 -> 1 damage (min 1)
        assert target.hp == 1  # 2 - 1
        assert attacker.hp == 3  # 4 - 1

    def test_execute_attack_city(self):
        """Test unit vs city combat."""
        state = GameState()
        state.players = ["player1", "player2"]

        # Add attacker
        attacker = Unit(
            id=1,
            owner="player1",
            type=UnitType.SOLDIER,  # +25% vs cities
            hp=4,
            moves_left=2,
            loc=Coord(x=5, y=5),
        )

        # Add target city
        city = City(
            id=1,
            owner="player2",
            loc=Coord(x=5, y=6),
            hp=10,
        )

        state.units[1] = attacker
        state.cities[1] = city

        # Execute attack
        action = AttackAction(attacker_id=1, target_id=1, target_type="city")
        result = execute_attack(state, action)

        assert result.success is True

        # Soldier gets +25% vs cities: 2 * 1.25 = 2.5 -> 2 damage
        assert city.hp == 8  # 10 - 2

    def test_cannot_attack_allies(self):
        """Test that allied units cannot attack each other."""
        state = GameState()
        state.players = ["player1", "player2"]
        state.diplomacy[("player1", "player2")] = DiplomaticState.ALLIANCE

        # Add units
        attacker = Unit(
            id=1,
            owner="player1",
            type=UnitType.SOLDIER,
            hp=4,
            moves_left=2,
            loc=Coord(x=5, y=5),
        )

        target = Unit(
            id=2,
            owner="player2",
            type=UnitType.SCOUT,
            hp=2,
            moves_left=3,
            loc=Coord(x=5, y=6),
        )

        state.units[1] = attacker
        state.units[2] = target

        # Try to attack ally
        action = AttackAction(attacker_id=1, target_id=2, target_type="unit")
        result = execute_attack(state, action)

        assert result.success is False
        assert "allied" in result.message.lower()


class TestCityManagement:
    """Test city founding and management."""

    def test_execute_found_city(self):
        """Test city founding."""
        state = GameState()
        state.players = ["player1"]
        state.stockpiles["player1"] = ResourceBag(food=50)

        # Add tile
        tile = Tile(
            id=1,
            loc=Coord(x=5, y=5),
            terrain=Terrain.PLAINS,
        )
        state.tiles.append(tile)

        # Add worker
        worker = Unit(
            id=1,
            owner="player1",
            type=UnitType.WORKER,
            hp=2,
            moves_left=2,
            loc=Coord(x=5, y=5),
        )
        state.units[1] = worker
        tile.unit_id = 1

        # Found city
        action = FoundCityAction(worker_id=1)
        result = execute_found_city(state, action)

        assert result.success is True
        assert len(state.cities) == 1

        city = list(state.cities.values())[0]
        assert city.owner == "player1"
        assert city.loc == Coord(x=5, y=5)

        # Worker should be consumed
        assert 1 not in state.units
        assert tile.unit_id is None
        assert tile.city_id == city.id

        # Resources consumed
        remaining = state.stockpiles["player1"]
        assert remaining.food == 20  # 50 - 30

    def test_execute_train_unit(self):
        """Test unit training in cities."""
        state = GameState()
        state.players = ["player1"]
        state.stockpiles["player1"] = ResourceBag(food=50)

        # Add tile
        tile = Tile(
            id=1,
            loc=Coord(x=5, y=5),
            terrain=Terrain.PLAINS,
        )
        state.tiles.append(tile)

        # Add city
        city = City(
            id=1,
            owner="player1",
            loc=Coord(x=5, y=5),
        )
        state.cities[1] = city
        tile.city_id = 1

        # Train unit
        action = TrainUnitAction(city_id=1, unit_type=UnitType.SCOUT)
        result = execute_train_unit(state, action)

        assert result.success is True
        assert len(state.units) == 1

        unit = list(state.units.values())[0]
        assert unit.owner == "player1"
        assert unit.type == UnitType.SCOUT
        assert unit.loc == Coord(x=5, y=5)

        # Resources consumed (scout costs 20 food)
        remaining = state.stockpiles["player1"]
        assert remaining.food == 30  # 50 - 20


class TestTurnResolution:
    """Test complete turn resolution."""

    def test_resolve_turn_deterministic(self):
        """Test that turn resolution is deterministic."""
        # Create identical initial states
        state1 = GameState(rng_state=42)
        state1.players = ["player1", "player2"]
        state1.stockpiles["player1"] = ResourceBag(food=50)
        state1.stockpiles["player2"] = ResourceBag(food=50)

        state2 = GameState(rng_state=42)
        state2.players = ["player1", "player2"]
        state2.stockpiles["player1"] = ResourceBag(food=50)
        state2.stockpiles["player2"] = ResourceBag(food=50)

        # Add identical units
        for state in [state1, state2]:
            unit = Unit(
                id=1,
                owner="player1",
                type=UnitType.SCOUT,
                hp=2,
                moves_left=3,
                loc=Coord(x=5, y=5),
            )
            state.units[1] = unit

        # Same actions
        actions = {"player1": [], "player2": []}

        # Resolve turns
        result1 = resolve_turn(state1, actions)
        result2 = resolve_turn(state2, actions)

        # Results should be identical
        assert result1.state_hash == result2.state_hash
        assert state1.hash_state() == state2.hash_state()

    def test_reset_unit_moves(self):
        """Test that unit moves are reset at turn start."""
        state = GameState()

        # Add unit with depleted moves
        unit = Unit(
            id=1,
            owner="player1",
            type=UnitType.SCOUT,
            hp=2,
            moves_left=0,  # No moves left
            loc=Coord(x=5, y=5),
        )
        state.units[1] = unit

        # Reset moves
        reset_unit_moves(state)

        # Moves should be restored
        assert unit.moves_left == 3  # Scout has 3 moves

    def test_collect_resources(self):
        """Test resource collection from cities."""
        state = GameState()
        state.players = ["player1"]
        state.stockpiles["player1"] = ResourceBag()

        # Add city
        city = City(
            id=1,
            owner="player1",
            loc=Coord(x=5, y=5),
        )
        state.cities[1] = city

        # Collect resources
        collect_resources(state)

        # Should get 1 food per city per turn
        resources = state.stockpiles["player1"]
        assert resources.food == 1
