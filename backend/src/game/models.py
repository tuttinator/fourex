"""
Core Pydantic models for the 4X game.
"""

from __future__ import annotations

import hashlib
import json
from enum import Enum

from pydantic import BaseModel, Field


class Terrain(str, Enum):
    """Terrain types on the map."""

    PLAINS = "plains"
    FOREST = "forest"
    MOUNTAIN = "mountain"
    WATER = "water"


class Resource(str, Enum):
    """Resource types that can be found on tiles."""

    FOOD = "food"
    WOOD = "wood"
    ORE = "ore"
    CRYSTAL = "crystal"


class UnitType(str, Enum):
    """Unit types that can be built."""

    SCOUT = "scout"
    WORKER = "worker"
    SOLDIER = "soldier"
    ARCHER = "archer"


class BuildingType(str, Enum):
    """Building types that can be constructed in cities."""

    GRANARY = "granary"
    BARRACKS = "barracks"
    WALLS = "walls"


class ImprovementType(str, Enum):
    """Tile improvements that can be built."""

    FARM = "farm"
    MINE = "mine"
    CRYSTAL_EXTRACTOR = "crystal_extractor"


class DiplomaticState(str, Enum):
    """Diplomatic relationships between players."""

    PEACE = "peace"
    ALLIANCE = "alliance"
    WAR = "war"


PlayerId = str


class CreateGameRequest(BaseModel):
    """Request to create a new game."""

    players: list[PlayerId]
    seed: int = 42


class Coord(BaseModel):
    """Map coordinate."""

    x: int
    y: int

    def __hash__(self) -> int:
        return hash((self.x, self.y))

    def distance_to(self, other: Coord) -> int:
        """Calculate orthogonal distance to another coordinate."""
        return abs(self.x - other.x) + abs(self.y - other.y)


class ResourceBag(BaseModel):
    """Collection of resources."""

    food: int = 0
    wood: int = 0
    ore: int = 0
    crystal: int = 0

    def __add__(self, other: ResourceBag) -> ResourceBag:
        return ResourceBag(
            food=self.food + other.food,
            wood=self.wood + other.wood,
            ore=self.ore + other.ore,
            crystal=self.crystal + other.crystal,
        )

    def __sub__(self, other: ResourceBag) -> ResourceBag:
        return ResourceBag(
            food=self.food - other.food,
            wood=self.wood - other.wood,
            ore=self.ore - other.ore,
            crystal=self.crystal - other.crystal,
        )

    def can_afford(self, cost: ResourceBag) -> bool:
        """Check if this bag has enough resources to pay the cost."""
        return (
            self.food >= cost.food
            and self.wood >= cost.wood
            and self.ore >= cost.ore
            and self.crystal >= cost.crystal
        )


class UnitStats(BaseModel):
    """Base stats for unit types."""

    cost: ResourceBag
    moves: int
    hp: int
    sight: int
    attack: int
    attack_range: int
    special: str = ""


UNIT_STATS = {
    UnitType.SCOUT: UnitStats(
        cost=ResourceBag(food=20),
        moves=3,
        hp=2,
        sight=3,
        attack=1,
        attack_range=1,
        special="Ignores forest movement penalty",
    ),
    UnitType.WORKER: UnitStats(
        cost=ResourceBag(food=30),
        moves=2,
        hp=2,
        sight=2,
        attack=0,
        attack_range=0,
        special="Builds improvements, cities",
    ),
    UnitType.SOLDIER: UnitStats(
        cost=ResourceBag(food=30, ore=10),
        moves=2,
        hp=4,
        sight=2,
        attack=2,
        attack_range=1,
        special="+25% vs cities",
    ),
    UnitType.ARCHER: UnitStats(
        cost=ResourceBag(food=30, wood=10),
        moves=2,
        hp=3,
        sight=3,
        attack=2,
        attack_range=2,
        special="Ranged; no counter-attack",
    ),
}


class BuildingStats(BaseModel):
    """Base stats for building types."""

    cost: ResourceBag
    hp: int
    effect: str


BUILDING_STATS = {
    BuildingType.GRANARY: BuildingStats(
        cost=ResourceBag(wood=40), hp=10, effect="+50% food output"
    ),
    BuildingType.BARRACKS: BuildingStats(
        cost=ResourceBag(wood=50), hp=10, effect="-25% unit training cost"
    ),
    BuildingType.WALLS: BuildingStats(
        cost=ResourceBag(ore=40), hp=15, effect="City gains +5 HP & ranged counter-fire"
    ),
}


class Tile(BaseModel):
    """Map tile with terrain, resources, and occupants."""

    id: int
    loc: Coord
    terrain: Terrain
    resource: Resource | None = None
    owner: PlayerId | None = None
    city_id: int | None = None
    unit_id: int | None = None
    improvement: ImprovementType | None = None


class Unit(BaseModel):
    """Game unit with stats and current state."""

    id: int
    owner: PlayerId
    type: UnitType
    hp: int
    moves_left: int
    loc: Coord

    @property
    def stats(self) -> UnitStats:
        """Get the base stats for this unit type."""
        return UNIT_STATS[self.type]

    def can_attack(self, target_loc: Coord) -> bool:
        """Check if this unit can attack the target location."""
        distance = self.loc.distance_to(target_loc)
        return distance <= self.stats.attack_range and self.stats.attack > 0


class BuildJob(BaseModel):
    """Building/unit construction job."""

    type: str  # "unit" or "building"
    target: str  # UnitType or BuildingType
    progress: int = 0
    total_cost: int = 1


class City(BaseModel):
    """Player city with buildings and production."""

    id: int
    owner: PlayerId
    loc: Coord
    hp: int = 10
    build_queue: BuildJob | None = None
    buildings: set[BuildingType] = Field(default_factory=set)

    def has_walls(self) -> bool:
        """Check if city has defensive walls."""
        return BuildingType.WALLS in self.buildings

    def food_multiplier(self) -> float:
        """Get food production multiplier from buildings."""
        return 1.5 if BuildingType.GRANARY in self.buildings else 1.0

    def unit_cost_multiplier(self) -> float:
        """Get unit training cost multiplier from buildings."""
        return 0.75 if BuildingType.BARRACKS in self.buildings else 1.0


class DiplomacyRequest(BaseModel):
    """Diplomatic proposal between players."""

    from_player: PlayerId
    to_player: PlayerId
    type: DiplomaticState


class TradeRequest(BaseModel):
    """Trade proposal between players."""

    from_player: PlayerId
    to_player: PlayerId
    give: ResourceBag
    want: ResourceBag


class PromptLog(BaseModel):
    """Log entry for LLM prompt and response."""

    player: PlayerId
    prompt: str
    response: str
    tokens_in: int
    tokens_out: int
    latency_ms: int


class GameState(BaseModel):
    """Complete game state."""

    turn: int = 0
    rng_state: int = 42
    map_width: int = 20
    map_height: int = 20
    tiles: list[Tile] = Field(default_factory=list)
    units: dict[int, Unit] = Field(default_factory=dict)
    cities: dict[int, City] = Field(default_factory=dict)
    players: list[PlayerId] = Field(default_factory=list)
    diplomacy: dict[tuple[PlayerId, PlayerId], DiplomaticState] = Field(
        default_factory=dict
    )
    stockpiles: dict[PlayerId, ResourceBag] = Field(default_factory=dict)
    next_unit_id: int = 1
    next_city_id: int = 1
    max_turns: int = 100

    def get_tile(self, loc: Coord) -> Tile | None:
        """Get tile at the given location."""
        for tile in self.tiles:
            if tile.loc == loc:
                return tile
        return None

    def get_unit(self, unit_id: int) -> Unit | None:
        """Get unit by ID."""
        return self.units.get(unit_id)

    def get_city(self, city_id: int) -> City | None:
        """Get city by ID."""
        return self.cities.get(city_id)

    def get_diplomatic_state(
        self, player1: PlayerId, player2: PlayerId
    ) -> DiplomaticState:
        """Get diplomatic relationship between two players."""
        if player1 == player2:
            return DiplomaticState.ALLIANCE
        key1 = (player1, player2)
        key2 = (player2, player1)
        return self.diplomacy.get(key1, self.diplomacy.get(key2, DiplomaticState.PEACE))

    def hash_state(self) -> str:
        """Generate deterministic hash of game state for testing."""
        state_dict = self.model_dump(mode="json")
        # Sort dictionaries for deterministic hashing
        state_str = json.dumps(state_dict, sort_keys=True, default=str)
        return hashlib.sha256(state_str.encode()).hexdigest()[:16]


# Action types using discriminated union
class MoveAction(BaseModel):
    """Move a unit to a new location."""

    type: str = "MOVE"
    unit_id: int
    to: Coord


class AttackAction(BaseModel):
    """Attack another unit or city."""

    type: str = "ATTACK"
    attacker_id: int
    target_id: int
    target_type: str  # "unit" or "city"


class BuildImprovementAction(BaseModel):
    """Build a tile improvement."""

    type: str = "BUILD_IMPROVEMENT"
    worker_id: int
    improvement: ImprovementType


class FoundCityAction(BaseModel):
    """Found a new city."""

    type: str = "FOUND_CITY"
    worker_id: int


class TrainUnitAction(BaseModel):
    """Train a new unit in a city."""

    type: str = "TRAIN_UNIT"
    city_id: int
    unit_type: UnitType


class BuildBuildingAction(BaseModel):
    """Build a building in a city."""

    type: str = "BUILD_BUILDING"
    city_id: int
    building_type: BuildingType


Action = (
    MoveAction
    | AttackAction
    | BuildImprovementAction
    | FoundCityAction
    | TrainUnitAction
    | BuildBuildingAction
)


class ActionResult(BaseModel):
    """Result of attempting to execute an action."""

    success: bool
    message: str
    action: Action


class TurnResult(BaseModel):
    """Result of processing a complete turn."""

    turn: int
    player_actions: dict[PlayerId, list[ActionResult]]
    state_hash: str
