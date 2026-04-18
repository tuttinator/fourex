"""
Game rules and turn resolution logic.
"""

import random
from copy import deepcopy

from .models import (
    BUILDING_STATS,
    IMPROVEMENT_STATS,
    UNIT_STATS,
    Action,
    ActionResult,
    AttackAction,
    BuildBuildingAction,
    BuildImprovementAction,
    City,
    Coord,
    DeclareWarAction,
    DiplomaticEvent,
    DiplomaticEventType,
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
    VictoryResult,
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
    """Create a copy of game state with fog-of-war applied for the given player.

    Also filters diplomatic state: the viewer sees only their own discovered
    set, only diplomacy entries involving the viewer or two discovered-by-viewer
    players, and only diplomatic events where the viewer is the actor, the
    counterparty, or has discovered both parties.
    """
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

    # Redact diplomatic state
    discovered_set = set(state.discovered.get(player_id, [])) | {player_id}
    redacted.discovered = {player_id: list(state.discovered.get(player_id, []))}

    redacted.diplomacy = {
        key: value
        for key, value in state.diplomacy.items()
        if player_id in key or (key[0] in discovered_set and key[1] in discovered_set)
    }

    redacted.diplomatic_events = [
        event
        for event in state.diplomatic_events
        if event.actor == player_id
        or event.counterparty == player_id
        or (
            event.actor in discovered_set
            and (event.counterparty is None or event.counterparty in discovered_set)
        )
    ]

    return redacted


def _diplomacy_key(a: PlayerId, b: PlayerId) -> tuple[PlayerId, PlayerId]:
    """Return a canonical sorted-pair key for the ``GameState.diplomacy`` dict."""
    return (a, b) if a <= b else (b, a)


def set_relation(
    state: GameState, a: PlayerId, b: PlayerId, value: DiplomaticState
) -> None:
    """Canonicalise relation storage so ``get_diplomatic_state`` stays symmetric.

    Clears both ordered keys before writing the sorted-pair key, so callers that
    previously stored ``(a, b)`` don't leave the inverse entry behind.
    """
    state.diplomacy.pop((a, b), None)
    state.diplomacy.pop((b, a), None)
    state.diplomacy[_diplomacy_key(a, b)] = value


def emit_diplomatic_event(
    state: GameState,
    event_type: DiplomaticEventType,
    actor: PlayerId,
    counterparty: PlayerId | None = None,
    payload: dict[str, str] | None = None,
) -> DiplomaticEvent:
    """Append a public diplomatic event with a deterministic id."""
    event = DiplomaticEvent(
        id=state.next_event_id,
        type=event_type,
        actor=actor,
        counterparty=counterparty,
        turn=state.turn,
        payload=payload or {},
    )
    state.diplomatic_events.append(event)
    state.next_event_id += 1
    return event


def record_discovery(state: GameState, viewer: PlayerId, target: PlayerId) -> None:
    """Record that ``viewer`` has now observed ``target``. Idempotent.

    Discovery is permanent: once added, entries are never removed.
    """
    if viewer == target:
        return
    bucket = state.discovered.setdefault(viewer, [])
    if target not in bucket:
        bucket.append(target)


def has_discovered(state: GameState, viewer: PlayerId, target: PlayerId) -> bool:
    """Return True if ``viewer`` has ever observed ``target``."""
    if viewer == target:
        return True
    return target in state.discovered.get(viewer, [])


def update_discovery(state: GameState) -> None:
    """Update each player's discovered set based on currently-visible owners.

    Called once per turn during resolution. Discovery flows both ways: if
    player A can see an object owned by B, A discovers B. B does not
    automatically discover A from that observation.
    """
    for viewer in state.players:
        if viewer in state.eliminated_players:
            continue
        visible = get_visible_tiles(state, viewer)
        for unit in state.units.values():
            if unit.loc in visible and unit.owner != viewer:
                record_discovery(state, viewer, unit.owner)
        for city in state.cities.values():
            if city.loc in visible and city.owner != viewer:
                record_discovery(state, viewer, city.owner)


def execute_declare_war(
    state: GameState, actor: PlayerId, action: DeclareWarAction
) -> ActionResult:
    """Declare war on ``action.target_player``. Takes effect immediately.

    Rejected if the target is not in ``actor``'s discovered set, if the target
    is ``actor`` themselves, if the target is not a game participant, or if
    the pair is already at war.
    """
    target = action.target_player
    if target == actor:
        return ActionResult(
            success=False,
            message="Cannot declare war on yourself.",
            action=action,
        )
    if target not in state.players:
        return ActionResult(
            success=False,
            message=f"Player {target} is not in this game.",
            action=action,
        )
    if not has_discovered(state, actor, target):
        return ActionResult(
            success=False,
            message=f"Cannot declare war on undiscovered player {target}.",
            action=action,
        )
    current = state.get_diplomatic_state(actor, target)
    if current == DiplomaticState.WAR:
        return ActionResult(
            success=False,
            message=f"Already at war with {target}.",
            action=action,
        )

    set_relation(state, actor, target, DiplomaticState.WAR)
    emit_diplomatic_event(
        state,
        DiplomaticEventType.WAR_DECLARED,
        actor=actor,
        counterparty=target,
        payload={"cause": "declaration"},
    )
    return ActionResult(
        success=True,
        message=f"{actor} declared war on {target}.",
        action=action,
    )


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

        # Treacherous first strike: attacking at PEACE flips to WAR and logs
        # a public TREACHEROUS_ATTACK event in addition to the combat outcome.
        if diplomatic_state == DiplomaticState.PEACE and attacker.owner != target.owner:
            set_relation(state, attacker.owner, target.owner, DiplomaticState.WAR)
            emit_diplomatic_event(
                state,
                DiplomaticEventType.TREACHEROUS_ATTACK,
                actor=attacker.owner,
                counterparty=target.owner,
                payload={"target_type": "unit", "target_id": str(target.id)},
            )
            emit_diplomatic_event(
                state,
                DiplomaticEventType.WAR_DECLARED,
                actor=attacker.owner,
                counterparty=target.owner,
                payload={"cause": "treacherous_attack"},
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

        # Treacherous first strike against an at-peace city.
        if (
            diplomatic_state == DiplomaticState.PEACE
            and attacker.owner != target_city.owner
        ):
            set_relation(state, attacker.owner, target_city.owner, DiplomaticState.WAR)
            emit_diplomatic_event(
                state,
                DiplomaticEventType.TREACHEROUS_ATTACK,
                actor=attacker.owner,
                counterparty=target_city.owner,
                payload={"target_type": "city", "target_id": str(target_city.id)},
            )
            emit_diplomatic_event(
                state,
                DiplomaticEventType.WAR_DECLARED,
                actor=attacker.owner,
                counterparty=target_city.owner,
                payload={"cause": "treacherous_attack"},
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
    cost = ResourceBag(food=15)
    player_resources = state.stockpiles.get(worker.owner, ResourceBag())
    if not player_resources.can_afford(cost):
        return ActionResult(
            success=False,
            message=f"Player {worker.owner} cannot afford city (need 15 food)",
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

    # Claim adjacent tiles immediately — cities start at border radius 1.
    city.border_radius = 1
    _expand_borders(state, city)

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


def execute_build_improvement(
    state: GameState, action: BuildImprovementAction
) -> ActionResult:
    """Execute building a tile improvement using a worker."""
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

    # Check if improvement type is valid
    if action.improvement not in IMPROVEMENT_STATS:
        return ActionResult(
            success=False,
            message=f"Invalid improvement type: {action.improvement}",
            action=action,
        )

    improvement_stats = IMPROVEMENT_STATS[action.improvement]

    # Check the tile the worker is on
    tile = state.get_tile(worker.loc)
    if not tile:
        return ActionResult(
            success=False,
            message="Invalid location for improvement",
            action=action,
        )

    # Check if tile already has an improvement
    if tile.improvement is not None:
        return ActionResult(
            success=False,
            message=f"Tile at {worker.loc} already has improvement {tile.improvement}",
            action=action,
        )

    # Validate terrain
    if tile.terrain not in improvement_stats.valid_terrain:
        return ActionResult(
            success=False,
            message=(
                f"Cannot build {action.improvement} on {tile.terrain}; "
                f"requires {[t.value for t in improvement_stats.valid_terrain]}"
            ),
            action=action,
        )

    # Validate required resource on tile
    if improvement_stats.required_resource is not None:
        if tile.resource != improvement_stats.required_resource:
            return ActionResult(
                success=False,
                message=(
                    f"Cannot build {action.improvement} here; "
                    f"requires {improvement_stats.required_resource} resource on tile"
                ),
                action=action,
            )

    # Check if player can afford the improvement
    player_resources = state.stockpiles.get(worker.owner, ResourceBag())
    if not player_resources.can_afford(improvement_stats.cost):
        return ActionResult(
            success=False,
            message=f"Player {worker.owner} cannot afford {action.improvement}",
            action=action,
        )

    # Deduct resources
    state.stockpiles[worker.owner] = player_resources - improvement_stats.cost

    # Place improvement. Worker is not consumed — only FOUND_CITY consumes workers.
    tile.improvement = action.improvement

    return ActionResult(
        success=True,
        message=f"Improvement {action.improvement} built at {worker.loc}",
        action=action,
    )


def execute_build_building(
    state: GameState, action: BuildBuildingAction
) -> ActionResult:
    """Execute building construction in a city."""
    city = state.get_city(action.city_id)
    if not city:
        return ActionResult(
            success=False,
            message=f"City {action.city_id} not found",
            action=action,
        )

    # Check ownership
    player_id = city.owner
    for player in state.players:
        if player == player_id:
            break
    else:
        return ActionResult(
            success=False,
            message=f"City {action.city_id} owner not found in players",
            action=action,
        )

    # Check if building type is valid
    if action.building_type not in BUILDING_STATS:
        return ActionResult(
            success=False,
            message=f"Invalid building type: {action.building_type}",
            action=action,
        )

    # Check if building already exists in city
    if action.building_type in city.buildings:
        return ActionResult(
            success=False,
            message=f"City {city.id} already has {action.building_type}",
            action=action,
        )

    # Check resource cost
    building_stats = BUILDING_STATS[action.building_type]
    player_resources = state.stockpiles.get(player_id, ResourceBag())
    if not player_resources.can_afford(building_stats.cost):
        return ActionResult(
            success=False,
            message=f"Player {player_id} cannot afford {action.building_type}",
            action=action,
        )

    # Deduct resources and add building
    state.stockpiles[player_id] = player_resources - building_stats.cost
    city.buildings.add(action.building_type)

    return ActionResult(
        success=True,
        message=f"Building {action.building_type} constructed in city {city.id}",
        action=action,
    )


# Culture thresholds: cumulative culture required for each border radius.
# Radius 1 is claimed immediately on founding (threshold 0); radius 2 at 15
# culture and radius 3 at 40 culture.
CULTURE_THRESHOLDS = {1: 0, 2: 15, 3: 40}


def accumulate_culture(state: GameState) -> None:
    """Accumulate culture for all cities and expand borders if thresholds are crossed."""
    for city in state.cities.values():
        city.culture += city.culture_per_turn()

        # Check for border expansion
        for radius in (1, 2, 3):
            if (
                city.border_radius < radius
                and city.culture >= CULTURE_THRESHOLDS[radius]
            ):
                city.border_radius = radius
                _expand_borders(state, city)


def _expand_borders(state: GameState, city: City) -> None:
    """Claim tiles within the city's border radius that aren't already owned.

    Water and mountain tiles can be owned — they contribute whatever resource
    they carry (e.g. ore on a mountain) but still cannot host cities or
    non-mine improvements.
    """
    for tile in state.tiles:
        distance = city.loc.distance_to(tile.loc)
        if distance > city.border_radius:
            continue
        if distance == 0:
            continue  # City tile already owned at founding
        if tile.owner is not None:
            continue  # First-to-reach: already claimed
        tile.owner = city.owner
        tile.city_id = city.id


def _calculate_tile_yield(tile: Tile) -> ResourceBag:
    """Calculate the resource yield for an owned tile.

    Base yields (from terrain/resource):
    - Food resource tile: +1 food
    - Wood resource tile: +1 wood
    - Ore resource tile: +1 ore
    - Crystal resource tile: +1 crystal
    - Forest tile (no wood resource): +1 wood
    - Plains without resource: +0

    Improved tile yields (total, replacing base):
    - Farm on food tile: +3 food
    - Mine on ore tile: +3 ore
    - Lumber mill on forest: +3 wood
    - Crystal extractor on crystal tile: +2 crystal
    """
    resources = ResourceBag()

    # Base yield from resource
    if tile.resource == Resource.FOOD:
        resources.food += 1
    elif tile.resource == Resource.WOOD:
        resources.wood += 1
    elif tile.resource == Resource.ORE:
        resources.ore += 1
    elif tile.resource == Resource.CRYSTAL:
        resources.crystal += 1
    elif tile.terrain == Terrain.FOREST:
        # Forest tiles without a resource still yield +1 wood
        resources.wood += 1

    # Improvement bonus (on top of base yield)
    if tile.improvement:
        if tile.improvement == ImprovementType.FARM and tile.resource == Resource.FOOD:
            resources.food += 2  # +2 bonus → total +3 food
        elif tile.improvement == ImprovementType.MINE and tile.resource == Resource.ORE:
            resources.ore += 2  # +2 bonus → total +3 ore
        elif tile.improvement == ImprovementType.LUMBER_MILL:
            resources.wood += 2  # +2 bonus → total +3 wood
        elif (
            tile.improvement == ImprovementType.CRYSTAL_EXTRACTOR
            and tile.resource == Resource.CRYSTAL
        ):
            resources.crystal += 1  # +1 bonus → total +2 crystal

    return resources


def collect_resources(state: GameState) -> None:
    """Collect resources from cities and tile yields at turn end.

    Each city produces base food (+1, boosted by Granary). Additionally,
    all tiles within city borders generate yields based on their terrain,
    resource, and improvement.
    """
    # Base city food production (independent of territory)
    for city in state.cities.values():
        base_food = 2
        food_production = int(base_food * city.food_multiplier())

        current_resources = state.stockpiles.get(city.owner, ResourceBag())
        current_resources.food += food_production
        state.stockpiles[city.owner] = current_resources

    # Collect yields from all owned tiles (within city borders)
    for tile in state.tiles:
        if tile.owner is None:
            continue
        if tile.city_id is not None and tile.city_id in state.cities:
            # Skip the city tile itself — it contributes base food above
            city = state.cities[tile.city_id]
            if city.loc == tile.loc:
                continue

        tile_yield = _calculate_tile_yield(tile)
        if tile_yield != ResourceBag():
            current_resources = state.stockpiles.get(tile.owner, ResourceBag())
            state.stockpiles[tile.owner] = current_resources + tile_yield


def eliminate_player(state: GameState, player_id: PlayerId) -> None:
    """Eliminate a player: remove cities, clear tile ownership, destroy improvements.

    The player remains in state.players for history but is added to eliminated_players.
    """
    if player_id in state.eliminated_players:
        return

    state.eliminated_players.append(player_id)

    # Remove all cities owned by the player
    city_ids_to_remove = [
        cid for cid, city in state.cities.items() if city.owner == player_id
    ]
    for cid in city_ids_to_remove:
        city = state.cities[cid]
        city_tile = state.get_tile(city.loc)
        if city_tile:
            city_tile.city_id = None
        del state.cities[cid]

    # Remove all units owned by the player
    unit_ids_to_remove = [
        uid for uid, unit in state.units.items() if unit.owner == player_id
    ]
    for uid in unit_ids_to_remove:
        unit = state.units[uid]
        tile = state.get_tile(unit.loc)
        if tile:
            tile.unit_id = None
        del state.units[uid]

    # Clear tile ownership and destroy improvements
    for tile in state.tiles:
        if tile.owner == player_id:
            tile.owner = None
            tile.city_id = None
            tile.improvement = None


def calculate_scores(state: GameState) -> dict[PlayerId, int]:
    """Calculate scores for all active players.

    Weights: cities (50), territory tiles (2), units (10), resources (1 per 10).
    """
    scores: dict[PlayerId, int] = {}
    active_players = [p for p in state.players if p not in state.eliminated_players]
    for player in active_players:
        score = 0
        # Cities: 50 points each
        score += sum(50 for city in state.cities.values() if city.owner == player)
        # Territory: 2 points per owned tile
        score += sum(2 for tile in state.tiles if tile.owner == player)
        # Units: 10 points each
        score += sum(10 for unit in state.units.values() if unit.owner == player)
        # Resources: 1 point per 10 resources
        resources = state.stockpiles.get(player, ResourceBag())
        total_resources = (
            resources.food + resources.wood + resources.ore + resources.crystal
        )
        score += total_resources // 10
        scores[player] = score
    return scores


def check_elimination(state: GameState) -> list[PlayerId]:
    """Check for players that should be eliminated this turn.

    A player is eliminated when:
    - They lose their last city (if they ever had one)
    - They lose their last unit without ever having founded a city
    """
    if "elimination" not in state.victory_conditions:
        return []

    newly_eliminated: list[PlayerId] = []
    for player in state.players:
        if player in state.eliminated_players:
            continue

        has_city = any(city.owner == player for city in state.cities.values())
        has_unit = any(unit.owner == player for unit in state.units.values())

        if not has_city and not has_unit:
            # Player has nothing — eliminate
            newly_eliminated.append(player)

    return newly_eliminated


def check_victory(state: GameState) -> VictoryResult:
    """Check all enabled victory conditions. Returns VictoryResult.

    Priority order when multiple conditions trigger on the same turn:
    1. Domination (highest priority)
    2. Economic
    3. Score (only at turn limit)
    """
    active_players = [p for p in state.players if p not in state.eliminated_players]

    # Domination: last player with at least one city
    if "domination" in state.victory_conditions:
        players_with_cities = {city.owner for city in state.cities.values()}
        # Filter to active players only
        players_with_cities = players_with_cities & set(active_players)
        if len(players_with_cities) == 1 and len(active_players) >= 2:
            winner = next(iter(players_with_cities))
            return VictoryResult(winner=winner, victory_type="domination")
        if len(active_players) == 1:
            return VictoryResult(winner=active_players[0], victory_type="domination")

    # Economic: stockpile totals >= 1000
    if "economic" in state.victory_conditions:
        for player in active_players:
            resources = state.stockpiles.get(player, ResourceBag())
            total = resources.food + resources.wood + resources.ore + resources.crystal
            if total >= 1000:
                return VictoryResult(winner=player, victory_type="economic")

    # Score at turn limit
    if "score" in state.victory_conditions and state.turn >= state.max_turns:
        scores = calculate_scores(state)
        if scores:
            winner = max(scores, key=lambda k: scores[k])
            return VictoryResult(winner=winner, victory_type="score", scores=scores)

    return VictoryResult()


def get_valid_moves(
    state: GameState,
    unit_id: int,
    visible_coords: set[Coord] | None = None,
) -> list[dict]:
    """Compute all tiles a unit can legally move to this turn.

    A tile is a valid destination if:
    - Manhattan distance from the unit <= ``unit.moves_left``
    - The tile exists and terrain is passable (not water/mountain)
    - The tile is not occupied by another unit
    - The tile is in ``visible_coords`` (when supplied — for fog-of-war)

    ``visible_coords`` of ``None`` disables the visibility filter (used by
    tests and any server-side caller that holds raw state).

    Each result tile includes ``x``, ``y``, ``terrain``, ``has_resource``,
    ``resource_type``, ``has_improvement``, ``owner``, and ``distance``.
    """
    unit = state.get_unit(unit_id)
    if unit is None or unit.moves_left <= 0:
        return []

    results: list[dict] = []
    for tile in state.tiles:
        distance = unit.loc.distance_to(tile.loc)
        if distance == 0 or distance > unit.moves_left:
            continue
        if tile.terrain in (Terrain.WATER, Terrain.MOUNTAIN):
            continue
        if tile.unit_id is not None and tile.unit_id != unit.id:
            continue
        if visible_coords is not None and tile.loc not in visible_coords:
            continue
        results.append(
            {
                "x": tile.loc.x,
                "y": tile.loc.y,
                "terrain": tile.terrain.value,
                "has_resource": tile.resource is not None,
                "resource_type": tile.resource.value if tile.resource else None,
                "has_improvement": tile.improvement is not None,
                "owner": tile.owner,
                "distance": distance,
            }
        )

    results.sort(key=lambda r: (r["distance"], r["x"], r["y"]))
    return results


STARTING_STOCKPILE = ResourceBag(food=50, wood=20, ore=10)
STARTING_WORKER_HP = 100
_PASSABLE_TERRAIN = (Terrain.PLAINS, Terrain.FOREST)


def _find_scout_placement(state: GameState, worker_loc: Coord) -> Coord | None:
    """Find a passable tile for scout placement, preferring cardinal neighbours.

    Tries cardinal directions (N, E, S, W) first. If all four are impassable
    or occupied, falls back to a wider ring-by-ring search out to radius 4.
    Returns None if nothing suitable is found.
    """
    # Cardinals in N, E, S, W order.
    cardinals = [(0, -1), (1, 0), (0, 1), (-1, 0)]
    for dx, dy in cardinals:
        coord = Coord(
            x=(worker_loc.x + dx) % state.map_width,
            y=(worker_loc.y + dy) % state.map_height,
        )
        tile = state.get_tile(coord)
        if tile and tile.terrain in _PASSABLE_TERRAIN and not tile.unit_id:
            return coord

    for radius in range(2, 5):
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                if abs(dx) + abs(dy) != radius:
                    continue
                coord = Coord(
                    x=(worker_loc.x + dx) % state.map_width,
                    y=(worker_loc.y + dy) % state.map_height,
                )
                tile = state.get_tile(coord)
                if tile and tile.terrain in _PASSABLE_TERRAIN and not tile.unit_id:
                    return coord

    return None


def place_starting_units(
    state: GameState,
    player_id: PlayerId,
    rng: random.Random,
    min_distance: int = 5,
) -> None:
    """Place a starting worker and scout for ``player_id``.

    The worker is placed on a plains/forest tile inside a margin-trimmed inner
    region, at least ``min_distance`` away from any existing unit. If no such
    spot is found after 100 attempts, falls back to the first suitable tile.
    The scout is placed on an adjacent passable tile via ``_find_scout_placement``.

    Both units are registered on ``state.units`` and on their tile's ``unit_id``,
    and ``state.next_unit_id`` is advanced.
    """
    map_w = state.map_width
    map_h = state.map_height
    margin = min(2, map_w // 5, map_h // 5)

    worker_loc: Coord | None = None
    for _ in range(100):
        x = rng.randint(margin, map_w - margin - 1)
        y = rng.randint(margin, map_h - margin - 1)
        coord = Coord(x=x, y=y)
        tile = state.get_tile(coord)
        if tile and tile.terrain in _PASSABLE_TERRAIN and not tile.unit_id:
            too_close = any(
                coord.distance_to(u.loc) < min_distance for u in state.units.values()
            )
            if not too_close:
                worker_loc = coord
                break

    if worker_loc is None:
        for tile in state.tiles:
            if tile.terrain in _PASSABLE_TERRAIN and not tile.unit_id:
                worker_loc = tile.loc
                break

    if worker_loc is None:
        raise ValueError(f"No suitable starting tile found for {player_id}")

    worker_id = state.next_unit_id
    worker = Unit(
        id=worker_id,
        owner=player_id,
        type=UnitType.WORKER,
        hp=STARTING_WORKER_HP,
        moves_left=UNIT_STATS[UnitType.WORKER].moves,
        loc=worker_loc,
    )
    state.units[worker_id] = worker
    worker_tile = state.get_tile(worker_loc)
    if worker_tile is not None:
        worker_tile.unit_id = worker_id
    state.next_unit_id = worker_id + 1

    scout_loc = _find_scout_placement(state, worker_loc)
    if scout_loc is None:
        return

    scout_stats = UNIT_STATS[UnitType.SCOUT]
    scout_id = state.next_unit_id
    scout = Unit(
        id=scout_id,
        owner=player_id,
        type=UnitType.SCOUT,
        hp=scout_stats.hp,
        moves_left=scout_stats.moves,
        loc=scout_loc,
    )
    state.units[scout_id] = scout
    scout_tile = state.get_tile(scout_loc)
    if scout_tile is not None:
        scout_tile.unit_id = scout_id
    state.next_unit_id = scout_id + 1


def reset_unit_moves(state: GameState) -> None:
    """Reset movement points for all units at turn start."""
    for unit in state.units.values():
        unit.moves_left = unit.stats.moves


def heal_units(state: GameState) -> None:
    """Heal units that are stationary in friendly territory.

    A unit heals +1 HP if:
    - It did not move this turn (moves_left equals its base moves)
    - It is on a tile owned by its player (friendly territory)
    - It is not a Scout (scouts are disposable reconnaissance units)

    Healing is capped at the unit's max HP (from UNIT_STATS).
    No resources are consumed.
    """
    for unit in state.units.values():
        if unit.type == UnitType.SCOUT:
            continue
        if unit.moves_left != unit.stats.moves:
            # Unit used movement this turn
            continue
        tile = state.get_tile(unit.loc)
        if tile is None or tile.owner != unit.owner:
            continue
        max_hp = unit.stats.hp
        if unit.hp < max_hp:
            unit.hp = min(unit.hp + 1, max_hp)


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
            if isinstance(action, MoveAction):
                result = execute_move(state, action)
            elif isinstance(action, AttackAction):
                result = execute_attack(state, action)
            elif isinstance(action, FoundCityAction):
                result = execute_found_city(state, action)
            elif isinstance(action, TrainUnitAction):
                result = execute_train_unit(state, action)
            elif isinstance(action, BuildImprovementAction):
                result = execute_build_improvement(state, action)
            elif isinstance(action, BuildBuildingAction):
                result = execute_build_building(state, action)
            elif isinstance(action, DeclareWarAction):
                result = execute_declare_war(state, player_id, action)
            else:
                result = ActionResult(
                    success=False,
                    message=f"Unknown action type: {action.type}",
                    action=action,
                )

            player_results.append(result)

        results[player_id] = player_results

    # Check for eliminations after actions resolve
    newly_eliminated = check_elimination(state)
    for player_id in newly_eliminated:
        eliminate_player(state, player_id)

    # Expand borders (culture accumulation + border expansion)
    accumulate_culture(state)

    # Heal stationary units in friendly territory
    heal_units(state)

    # Collect resources at end of turn
    collect_resources(state)

    # Update each player's discovered-players set based on end-of-turn visibility.
    # Discovery is permanent; this only adds entries, never removes them.
    update_discovery(state)

    # Check for eliminations again (in case actions during this phase caused them)
    newly_eliminated = check_elimination(state)
    for player_id in newly_eliminated:
        eliminate_player(state, player_id)

    # Check victory conditions
    victory = check_victory(state)

    # Store current turn number before incrementing
    current_turn = state.turn

    # Advance turn counter
    state.turn += 1

    return TurnResult(
        turn=current_turn,
        player_actions=results,
        state_hash=state.hash_state(),
        victory=victory if victory.victory_type != "none" else None,
    )
