"""
Game rules and turn resolution logic.
"""

import random
from copy import deepcopy

from .models import (
    UNIT_STATS,
    Action,
    ActionResult,
    AttackAction,
    City,
    Coord,
    DiplomaticState,
    FoundCityAction,
    GameState,
    ImprovementType,
    MoveAction,
    PlayerId,
    Resource,
    ResourceBag,
    Terrain,
    Tile,
    TrainUnitAction,
    TurnResult,
    Unit,
    UnitType,
)


def generate_map(width: int, height: int, seed: int) -> list[Tile]:
    """Generate a random map with the given dimensions and seed."""
    rng = random.Random(seed)
    tiles = []
    tile_id = 0

    for y in range(height):
        for x in range(width):
            # Randomly choose terrain
            terrain_roll = rng.random()
            if terrain_roll < 0.4:
                terrain = Terrain.PLAINS
            elif terrain_roll < 0.6:
                terrain = Terrain.FOREST
            elif terrain_roll < 0.8:
                terrain = Terrain.MOUNTAIN
            else:
                terrain = Terrain.WATER

            # Add resources based on terrain
            resource = None
            if terrain == Terrain.PLAINS and rng.random() < 0.3:
                resource = Resource.FOOD
            elif terrain == Terrain.FOREST and rng.random() < 0.4:
                resource = Resource.WOOD
            elif terrain == Terrain.MOUNTAIN and rng.random() < 0.5:
                resource = Resource.ORE
            elif rng.random() < 0.05:  # Rare crystal nodes
                resource = Resource.CRYSTAL

            tiles.append(
                Tile(
                    id=tile_id,
                    loc=Coord(x=x, y=y),
                    terrain=terrain,
                    resource=resource,
                )
            )
            tile_id += 1

    return tiles


def get_neighbors(loc: Coord, width: int, height: int) -> list[Coord]:
    """Get orthogonal neighbors of a coordinate."""
    neighbors = []
    for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
        new_x = (loc.x + dx) % width
        new_y = (loc.y + dy) % height
        neighbors.append(Coord(x=new_x, y=new_y))
    return neighbors


def get_visible_tiles(
    state: GameState, player_id: PlayerId, sight_range: int = 2
) -> set[Coord]:
    """Get all tiles visible to a player."""
    visible = set()

    # Units provide visibility
    for unit in state.units.values():
        if unit.owner == player_id:
            visible.update(
                get_tiles_in_range(
                    unit.loc, unit.stats.sight, state.map_width, state.map_height
                )
            )

    # Cities provide visibility (range 3)
    for city in state.cities.values():
        if city.owner == player_id:
            visible.update(
                get_tiles_in_range(city.loc, 3, state.map_width, state.map_height)
            )

    # Allied units and cities also provide visibility
    for other_player in state.players:
        if (
            other_player != player_id
            and state.get_diplomatic_state(player_id, other_player)
            == DiplomaticState.ALLIANCE
        ):
            for unit in state.units.values():
                if unit.owner == other_player:
                    visible.update(
                        get_tiles_in_range(
                            unit.loc,
                            unit.stats.sight,
                            state.map_width,
                            state.map_height,
                        )
                    )
            for city in state.cities.values():
                if city.owner == other_player:
                    visible.update(
                        get_tiles_in_range(
                            city.loc, 3, state.map_width, state.map_height
                        )
                    )

    return visible


def get_tiles_in_range(
    center: Coord, range_val: int, width: int, height: int
) -> set[Coord]:
    """Get all tiles within orthogonal range of center."""
    tiles = set()
    for dx in range(-range_val, range_val + 1):
        for dy in range(-range_val, range_val + 1):
            if abs(dx) + abs(dy) <= range_val:
                x = (center.x + dx) % width
                y = (center.y + dy) % height
                tiles.add(Coord(x=x, y=y))
    return tiles


def redact_state(state: GameState, player_id: PlayerId) -> GameState:
    """Create a copy of game state with fog-of-war applied for the given player."""
    visible_tiles = get_visible_tiles(state, player_id)
    redacted = deepcopy(state)

    # Filter tiles to only visible ones
    redacted.tiles = [tile for tile in redacted.tiles if tile.loc in visible_tiles]

    # Filter units to only visible ones
    visible_units = {}
    for unit_id, unit in redacted.units.items():
        if unit.loc in visible_tiles:
            visible_units[unit_id] = unit
    redacted.units = visible_units

    # Filter cities to only visible ones
    visible_cities = {}
    for city_id, city in redacted.cities.items():
        if city.loc in visible_tiles:
            visible_cities[city_id] = city
    redacted.cities = visible_cities

    return redacted


def is_valid_move(state: GameState, unit: Unit, target: Coord) -> tuple[bool, str]:
    """Check if a unit can move to the target location."""
    # Check distance
    distance = unit.loc.distance_to(target)
    if distance > unit.moves_left:
        return (
            False,
            f"Unit {unit.id} has {unit.moves_left} moves left, need {distance}",
        )

    # Check if target tile exists and is passable
    target_tile = state.get_tile(target)
    if not target_tile:
        return False, f"Target location {target} is invalid"

    if target_tile.terrain == Terrain.WATER:
        return False, "Cannot move into water"

    if target_tile.terrain == Terrain.MOUNTAIN:
        return False, "Cannot move into mountains"

    # Check if another unit is on the tile
    if target_tile.unit_id and target_tile.unit_id != unit.id:
        return False, f"Another unit {target_tile.unit_id} is on target tile"

    return True, "Valid move"


def execute_move(state: GameState, action: MoveAction) -> ActionResult:
    """Execute a unit move action."""
    unit = state.get_unit(action.unit_id)
    if not unit:
        return ActionResult(
            success=False,
            message=f"Unit {action.unit_id} not found",
            action=action,
        )

    valid, message = is_valid_move(state, unit, action.to)
    if not valid:
        return ActionResult(success=False, message=message, action=action)

    # Update old tile
    old_tile = state.get_tile(unit.loc)
    if old_tile:
        old_tile.unit_id = None

    # Update new tile
    new_tile = state.get_tile(action.to)
    if new_tile:
        new_tile.unit_id = unit.id

    # Update unit
    distance = unit.loc.distance_to(action.to)
    unit.loc = action.to
    unit.moves_left -= distance

    return ActionResult(
        success=True,
        message=f"Unit {unit.id} moved to {action.to}",
        action=action,
    )


def execute_attack(state: GameState, action: AttackAction) -> ActionResult:
    """Execute an attack action."""
    attacker = state.get_unit(action.attacker_id)
    if not attacker:
        return ActionResult(
            success=False,
            message=f"Attacker {action.attacker_id} not found",
            action=action,
        )

    if action.target_type == "unit":
        target = state.get_unit(action.target_id)
        if not target:
            return ActionResult(
                success=False,
                message=f"Target unit {action.target_id} not found",
                action=action,
            )

        # Check if attacker can attack target
        if not attacker.can_attack(target.loc):
            return ActionResult(
                success=False,
                message=f"Unit {attacker.id} cannot attack unit {target.id} at range",
                action=action,
            )

        # Check diplomatic state
        diplomatic_state = state.get_diplomatic_state(attacker.owner, target.owner)
        if diplomatic_state == DiplomaticState.ALLIANCE:
            return ActionResult(
                success=False,
                message=f"Cannot attack allied unit {target.id}",
                action=action,
            )

        # Calculate damage
        attacker_strength = attacker.stats.attack
        defender_strength = target.stats.attack
        damage = max(1, attacker_strength - defender_strength // 2)

        target.hp -= damage
        message = f"Unit {attacker.id} attacks unit {target.id} for {damage} damage"

        # Counter-attack if target survives and can counter
        if target.hp > 0 and target.can_attack(attacker.loc):
            counter_damage = max(1, defender_strength - attacker_strength // 2)
            attacker.hp -= counter_damage
            message += f", unit {target.id} counters for {counter_damage} damage"

        # Remove destroyed units
        if target.hp <= 0:
            target_tile = state.get_tile(target.loc)
            if target_tile:
                target_tile.unit_id = None
            del state.units[target.id]
            message += f", unit {target.id} destroyed"

        if attacker.hp <= 0:
            attacker_tile = state.get_tile(attacker.loc)
            if attacker_tile:
                attacker_tile.unit_id = None
            del state.units[attacker.id]
            message += f", unit {attacker.id} destroyed"

        return ActionResult(success=True, message=message, action=action)

    elif action.target_type == "city":
        target_city = state.get_city(action.target_id)
        if not target_city:
            return ActionResult(
                success=False,
                message=f"Target city {action.target_id} not found",
                action=action,
            )

        # Check if attacker can attack city
        if not attacker.can_attack(target_city.loc):
            return ActionResult(
                success=False,
                message=(
                    f"Unit {attacker.id} cannot attack city {target_city.id} at range"
                ),
                action=action,
            )

        # Check diplomatic state
        diplomatic_state = state.get_diplomatic_state(attacker.owner, target_city.owner)
        if diplomatic_state == DiplomaticState.ALLIANCE:
            return ActionResult(
                success=False,
                message=f"Cannot attack allied city {target_city.id}",
                action=action,
            )

        # Calculate damage (soldiers get +25% vs cities)
        attacker_strength = attacker.stats.attack
        if attacker.type == UnitType.SOLDIER:
            attacker_strength = int(attacker_strength * 1.25)

        damage = max(1, attacker_strength)
        target_city.hp -= damage
        message = (
            f"Unit {attacker.id} attacks city {target_city.id} for {damage} damage"
        )

        # City counter-attack if it has walls
        if target_city.has_walls() and target_city.hp > 0:
            counter_damage = 2  # Wall counter-fire
            attacker.hp -= counter_damage
            message += f", city {target_city.id} counters for {counter_damage} damage"

        # Remove destroyed units
        if attacker.hp <= 0:
            attacker_tile = state.get_tile(attacker.loc)
            if attacker_tile:
                attacker_tile.unit_id = None
            del state.units[attacker.id]
            message += f", unit {attacker.id} destroyed"

        # Capture city if destroyed
        if target_city.hp <= 0:
            target_city.owner = attacker.owner
            target_city.hp = 1  # Cities survive with 1 HP when captured
            message += f", city {target_city.id} captured by {attacker.owner}"

        return ActionResult(success=True, message=message, action=action)

    return ActionResult(
        success=False,
        message=f"Invalid target type: {action.target_type}",
        action=action,
    )


def execute_found_city(state: GameState, action: FoundCityAction) -> ActionResult:
    """Execute founding a new city."""
    worker = state.get_unit(action.worker_id)
    if not worker:
        return ActionResult(
            success=False,
            message=f"Worker {action.worker_id} not found",
            action=action,
        )

    if worker.type != UnitType.WORKER:
        return ActionResult(
            success=False,
            message=f"Unit {worker.id} is not a worker",
            action=action,
        )

    # Check if player can afford city
    cost = ResourceBag(food=30)
    player_resources = state.stockpiles.get(worker.owner, ResourceBag())
    if not player_resources.can_afford(cost):
        return ActionResult(
            success=False,
            message=f"Player {worker.owner} cannot afford city (need 30 food)",
            action=action,
        )

    # Check if tile is suitable for city
    tile = state.get_tile(worker.loc)
    if not tile:
        return ActionResult(
            success=False,
            message="Invalid location for city",
            action=action,
        )

    if tile.city_id:
        return ActionResult(
            success=False,
            message=f"City already exists at {worker.loc}",
            action=action,
        )

    if tile.terrain == Terrain.WATER or tile.terrain == Terrain.MOUNTAIN:
        return ActionResult(
            success=False,
            message=f"Cannot found city on {tile.terrain}",
            action=action,
        )

    # Create city
    city = City(
        id=state.next_city_id,
        owner=worker.owner,
        loc=worker.loc,
    )
    state.cities[city.id] = city
    state.next_city_id += 1

    # Update tile
    tile.city_id = city.id
    tile.owner = worker.owner

    # Consume resources
    state.stockpiles[worker.owner] = player_resources - cost

    # Remove worker
    tile.unit_id = None
    del state.units[worker.id]

    return ActionResult(
        success=True,
        message=f"City {city.id} founded at {worker.loc}",
        action=action,
    )


def execute_train_unit(state: GameState, action: TrainUnitAction) -> ActionResult:
    """Execute training a new unit."""
    city = state.get_city(action.city_id)
    if not city:
        return ActionResult(
            success=False,
            message=f"City {action.city_id} not found",
            action=action,
        )

    # Check if unit type is valid
    if action.unit_type not in UNIT_STATS:
        return ActionResult(
            success=False,
            message=f"Invalid unit type: {action.unit_type}",
            action=action,
        )

    # Calculate cost with city modifiers
    base_cost = UNIT_STATS[action.unit_type].cost
    cost_multiplier = city.unit_cost_multiplier()
    actual_cost = ResourceBag(
        food=int(base_cost.food * cost_multiplier),
        wood=int(base_cost.wood * cost_multiplier),
        ore=int(base_cost.ore * cost_multiplier),
        crystal=int(base_cost.crystal * cost_multiplier),
    )

    # Check if player can afford unit
    player_resources = state.stockpiles.get(city.owner, ResourceBag())
    if not player_resources.can_afford(actual_cost):
        return ActionResult(
            success=False,
            message=f"Player {city.owner} cannot afford {action.unit_type}",
            action=action,
        )

    # Check if city tile is free
    city_tile = state.get_tile(city.loc)
    if city_tile and city_tile.unit_id:
        return ActionResult(
            success=False,
            message=f"City {city.id} tile is occupied",
            action=action,
        )

    # Create unit
    unit_stats = UNIT_STATS[action.unit_type]
    unit = Unit(
        id=state.next_unit_id,
        owner=city.owner,
        type=action.unit_type,
        hp=unit_stats.hp,
        moves_left=unit_stats.moves,
        loc=city.loc,
    )
    state.units[unit.id] = unit
    state.next_unit_id += 1

    # Update tile
    if city_tile:
        city_tile.unit_id = unit.id

    # Consume resources
    state.stockpiles[city.owner] = player_resources - actual_cost

    return ActionResult(
        success=True,
        message=f"Unit {unit.id} ({action.unit_type}) trained in city {city.id}",
        action=action,
    )


def collect_resources(state: GameState) -> None:
    """Collect resources from cities and improvements at turn end."""
    for city in state.cities.values():
        base_food = 1
        food_production = int(base_food * city.food_multiplier())

        current_resources = state.stockpiles.get(city.owner, ResourceBag())
        current_resources.food += food_production
        state.stockpiles[city.owner] = current_resources

    # Collect from tile improvements
    for tile in state.tiles:
        if tile.improvement and tile.owner:
            resources_generated = ResourceBag()

            if (
                tile.improvement == ImprovementType.FARM
                and tile.resource == Resource.FOOD
            ):
                resources_generated.food += 2
            elif (
                tile.improvement == ImprovementType.MINE
                and tile.resource == Resource.ORE
            ):
                resources_generated.ore += 2
            elif (
                tile.improvement == ImprovementType.CRYSTAL_EXTRACTOR
                and tile.resource == Resource.CRYSTAL
            ):
                resources_generated.crystal += 1

            if resources_generated != ResourceBag():
                current_resources = state.stockpiles.get(tile.owner, ResourceBag())
                state.stockpiles[tile.owner] = current_resources + resources_generated


def reset_unit_moves(state: GameState) -> None:
    """Reset movement points for all units at turn start."""
    for unit in state.units.values():
        unit.moves_left = unit.stats.moves


def resolve_turn(
    state: GameState, player_actions: dict[PlayerId, list[Action]]
) -> TurnResult:
    """
    Resolve a complete turn deterministically.

    Args:
        state: Current game state
        player_actions: Dictionary mapping player IDs to their actions

    Returns:
        TurnResult with action outcomes and updated state hash
    """
    # Reset unit movement at start of turn
    reset_unit_moves(state)

    # Process all actions
    results: dict[PlayerId, list[ActionResult]] = {}

    for player_id in state.players:
        player_results = []
        actions = player_actions.get(player_id, [])

        for action in actions:
            if action.type == "MOVE":
                result = execute_move(state, action)
            elif action.type == "ATTACK":
                result = execute_attack(state, action)
            elif action.type == "FOUND_CITY":
                result = execute_found_city(state, action)
            elif action.type == "TRAIN_UNIT":
                result = execute_train_unit(state, action)
            elif action.type == "BUILD_IMPROVEMENT":
                # TODO: Implement improvement building
                result = ActionResult(
                    success=False,
                    message="Improvement building not implemented yet",
                    action=action,
                )
            elif action.type == "BUILD_BUILDING":
                # TODO: Implement building construction
                result = ActionResult(
                    success=False,
                    message="Building construction not implemented yet",
                    action=action,
                )
            else:
                result = ActionResult(
                    success=False,
                    message=f"Unknown action type: {action.type}",
                    action=action,
                )

            player_results.append(result)

        results[player_id] = player_results

    # Collect resources at end of turn
    collect_resources(state)

    # Store current turn number before incrementing
    current_turn = state.turn

    # Advance turn counter
    state.turn += 1

    return TurnResult(
        turn=current_turn,
        player_actions=results,
        state_hash=state.hash_state(),
    )
