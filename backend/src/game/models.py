"""
Core Pydantic models for the 4X game.
"""

from __future__ import annotations

import hashlib
import json
from enum import Enum
from typing import Annotated, Literal

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
    MONUMENT = "monument"
    LIBRARY = "library"
    TEMPLE = "temple"


class ImprovementType(str, Enum):
    """Tile improvements that can be built."""

    FARM = "farm"
    MINE = "mine"
    CRYSTAL_EXTRACTOR = "crystal_extractor"
    LUMBER_MILL = "lumber_mill"


class DiplomaticState(str, Enum):
    """Diplomatic relationships between players."""

    PEACE = "peace"
    ALLIANCE = "alliance"
    WAR = "war"


class DiplomaticEventType(str, Enum):
    """Types of public diplomatic events emitted by the engine."""

    WAR_DECLARED = "war_declared"
    TREACHEROUS_ATTACK = "treacherous_attack"
    TREATY_PROPOSED = "treaty_proposed"
    PROPOSAL_WITHDRAWN = "proposal_withdrawn"
    PROPOSAL_EXPIRED = "proposal_expired"
    PROPOSAL_ACCEPTED = "proposal_accepted"
    PROPOSAL_DECLINED = "proposal_declined"
    PROPOSAL_FAILED_UNFUNDABLE = "proposal_failed_unfundable"
    TREATY_CANCELLED = "treaty_cancelled"
    TREATY_VIOLATED = "treaty_violated"
    TREATY_EXPIRED = "treaty_expired"
    TRIBUTE_PAID = "tribute_paid"
    TRIBUTE_FAILED = "tribute_failed"
    MESSAGE_SENT = "message_sent"


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
        cost=ResourceBag(food=10),
        moves=3,
        hp=2,
        sight=3,
        attack=1,
        attack_range=1,
        special="Ignores forest movement penalty",
    ),
    UnitType.WORKER: UnitStats(
        cost=ResourceBag(food=15),
        moves=2,
        hp=2,
        sight=2,
        attack=0,
        attack_range=0,
        special="Builds improvements, cities",
    ),
    UnitType.SOLDIER: UnitStats(
        cost=ResourceBag(food=15, ore=5),
        moves=2,
        hp=4,
        sight=2,
        attack=2,
        attack_range=1,
        special="+25% vs cities",
    ),
    UnitType.ARCHER: UnitStats(
        cost=ResourceBag(food=15, wood=5),
        moves=2,
        hp=3,
        sight=3,
        attack=2,
        attack_range=2,
        special="Ranged; no counter-attack",
    ),
}


class ImprovementStats(BaseModel):
    """Base stats for tile improvement types."""

    cost: ResourceBag
    valid_terrain: list[Terrain]
    required_resource: Resource | None = None
    effect: str


IMPROVEMENT_STATS = {
    ImprovementType.FARM: ImprovementStats(
        cost=ResourceBag(wood=10),
        valid_terrain=[Terrain.PLAINS],
        required_resource=Resource.FOOD,
        effect="+2 food bonus (total +3 food on food tile)",
    ),
    ImprovementType.MINE: ImprovementStats(
        cost=ResourceBag(wood=10),
        valid_terrain=[Terrain.MOUNTAIN],
        required_resource=Resource.ORE,
        effect="+2 ore bonus (total +3 ore on ore tile)",
    ),
    ImprovementType.LUMBER_MILL: ImprovementStats(
        cost=ResourceBag(wood=5),
        valid_terrain=[Terrain.FOREST],
        required_resource=None,
        effect="+2 wood bonus (total +3 wood on forest tile)",
    ),
    ImprovementType.CRYSTAL_EXTRACTOR: ImprovementStats(
        cost=ResourceBag(wood=10, ore=5),
        valid_terrain=[Terrain.PLAINS, Terrain.FOREST, Terrain.MOUNTAIN],
        required_resource=Resource.CRYSTAL,
        effect="+1 crystal bonus (total +2 crystal on crystal tile)",
    ),
}


class BuildingStats(BaseModel):
    """Base stats for building types."""

    cost: ResourceBag
    hp: int
    effect: str


BUILDING_STATS = {
    BuildingType.GRANARY: BuildingStats(
        cost=ResourceBag(wood=20), hp=10, effect="+50% food output"
    ),
    BuildingType.BARRACKS: BuildingStats(
        cost=ResourceBag(wood=25), hp=10, effect="-25% unit training cost"
    ),
    BuildingType.WALLS: BuildingStats(
        cost=ResourceBag(ore=20), hp=15, effect="City gains +5 HP & ranged counter-fire"
    ),
    BuildingType.MONUMENT: BuildingStats(
        cost=ResourceBag(wood=10), hp=5, effect="+1 culture/turn"
    ),
    BuildingType.LIBRARY: BuildingStats(
        cost=ResourceBag(wood=15, ore=5), hp=5, effect="+2 culture/turn"
    ),
    BuildingType.TEMPLE: BuildingStats(
        cost=ResourceBag(wood=15, ore=10, crystal=5),
        hp=5,
        effect="+3 culture/turn",
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
    culture: int = 0
    border_radius: int = 0

    def has_walls(self) -> bool:
        """Check if city has defensive walls."""
        return BuildingType.WALLS in self.buildings

    def food_multiplier(self) -> float:
        """Get food production multiplier from buildings."""
        return 1.5 if BuildingType.GRANARY in self.buildings else 1.0

    def unit_cost_multiplier(self) -> float:
        """Get unit training cost multiplier from buildings."""
        return 0.75 if BuildingType.BARRACKS in self.buildings else 1.0

    def culture_per_turn(self) -> int:
        """Get culture output per turn from base + buildings."""
        culture = 1  # base
        if BuildingType.MONUMENT in self.buildings:
            culture += 1
        if BuildingType.LIBRARY in self.buildings:
            culture += 2
        if BuildingType.TEMPLE in self.buildings:
            culture += 3
        return culture


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


class VictoryResult(BaseModel):
    """Result of a victory check."""

    winner: PlayerId | None = None
    victory_type: str = "none"
    scores: dict[PlayerId, int] = Field(default_factory=dict)


class DiplomaticEvent(BaseModel):
    """A public (or visibility-gated) diplomatic event logged to the game feed.

    Event ids are drawn from ``GameState.next_event_id`` — a deterministic
    monotonic counter — so replays produce identical ids.
    """

    id: int
    type: DiplomaticEventType
    actor: PlayerId
    counterparty: PlayerId | None = None
    turn: int
    payload: dict[str, str] = Field(default_factory=dict)


MESSAGE_BODY_MAX_LENGTH = 2000
MESSAGES_PER_TURN_LIMIT = 5

TREATY_PROPOSAL_EXPIRY_TURNS = 3
FREE_TEXT_CLAUSE_MAX_LENGTH = 500
PEACE_CLAUSE_MAX_DURATION = 100


class PeaceClause(BaseModel):
    """Sets the pair's ``DiplomaticState`` to PEACE for ``duration_turns`` turns.

    ``turns_remaining`` is decremented at the end of each turn during the
    diplomacy-resolution phase; when it reaches zero the clause expires.
    """

    clause_type: Literal["peace"] = "peace"
    duration_turns: int = Field(gt=0, le=PEACE_CLAUSE_MAX_DURATION)
    turns_remaining: int = Field(ge=0)


class FreeTextClause(BaseModel):
    """Unenforced free-form clause text. Purely informational."""

    clause_type: Literal["free_text"] = "free_text"
    text: str = Field(min_length=1, max_length=FREE_TEXT_CLAUSE_MAX_LENGTH)


TreatyClause = Annotated[
    PeaceClause | FreeTextClause,
    Field(discriminator="clause_type"),
]


class Treaty(BaseModel):
    """A ratified bilateral treaty with one or more clauses.

    Treaties are *public* — visible to all players in the game regardless of
    discovery. Ids are drawn from ``GameState.next_treaty_id`` for determinism.
    """

    id: int
    parties: tuple[PlayerId, PlayerId]
    clauses: list[TreatyClause]
    turn_ratified: int


class TreatyProposal(BaseModel):
    """A pending proposal awaiting a response from ``recipient``.

    Proposals are *private* to ``proposer`` and ``recipient`` — third parties
    cannot see them via any read endpoint. Auto-expires on
    ``expires_on_turn`` if still unanswered.
    """

    id: int
    proposer: PlayerId
    recipient: PlayerId
    clauses: list[TreatyClause]
    turn_proposed: int
    expires_on_turn: int


class Message(BaseModel):
    """A private bilateral message between two players.

    Ids are drawn from ``GameState.next_message_id`` — a deterministic monotonic
    counter — so replays produce identical ids. Only the sender and recipient
    ever see the message content or existence; ``redact_state`` enforces this.
    """

    id: int
    sender: PlayerId
    recipient: PlayerId
    body: str
    turn_sent: int


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
    next_event_id: int = 1
    next_message_id: int = 1
    next_proposal_id: int = 1
    next_treaty_id: int = 1
    max_turns: int = 100
    victory_conditions: list[str] = Field(
        default_factory=lambda: ["domination", "economic", "elimination", "score"]
    )
    eliminated_players: list[PlayerId] = Field(default_factory=list)
    discovered: dict[PlayerId, list[PlayerId]] = Field(default_factory=dict)
    diplomatic_events: list[DiplomaticEvent] = Field(default_factory=list)
    messages: list[Message] = Field(default_factory=list)
    pending_proposals: list[TreatyProposal] = Field(default_factory=list)
    active_treaties: list[Treaty] = Field(default_factory=list)

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


class DeclareWarAction(BaseModel):
    """Declare war on another (discovered) player. Effect is immediate."""

    type: str = "DECLARE_WAR"
    target_player: PlayerId


class SendMessageAction(BaseModel):
    """Send a private bilateral message to a discovered player.

    Capped at ``MESSAGE_BODY_MAX_LENGTH`` characters per message and
    ``MESSAGES_PER_TURN_LIMIT`` messages per sender per turn. Only the sender
    and recipient ever see the message.
    """

    type: str = "SEND_MESSAGE"
    recipient: PlayerId
    body: str


class ProposeTreatyAction(BaseModel):
    """Propose a treaty with one or more clauses to a discovered player."""

    type: str = "PROPOSE_TREATY"
    recipient: PlayerId
    clauses: list[TreatyClause]


class RespondToTreatyAction(BaseModel):
    """Accept or decline a pending treaty proposal addressed to you."""

    type: str = "RESPOND_TO_TREATY"
    proposal_id: int
    accept: bool


class WithdrawTreatyAction(BaseModel):
    """Withdraw a pending proposal you previously made, before a response."""

    type: str = "WITHDRAW_TREATY"
    proposal_id: int


class CancelTreatyAction(BaseModel):
    """Unilaterally cancel a ratified treaty you are a party to.

    If the treaty has active obligations (e.g. an unexpired peace clause) the
    cancellation is recorded as ``TREATY_VIOLATED``; otherwise ``TREATY_CANCELLED``.
    """

    type: str = "CANCEL_TREATY"
    treaty_id: int


Action = (
    MoveAction
    | AttackAction
    | BuildImprovementAction
    | FoundCityAction
    | TrainUnitAction
    | BuildBuildingAction
    | DeclareWarAction
    | SendMessageAction
    | ProposeTreatyAction
    | RespondToTreatyAction
    | WithdrawTreatyAction
    | CancelTreatyAction
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
    victory: VictoryResult | None = None
