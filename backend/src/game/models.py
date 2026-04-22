"""
Core Pydantic models for the 4X game.
"""

from __future__ import annotations

import hashlib
import json
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator


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
    SCIENCE = "science"


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
    science: int = 0

    def __add__(self, other: ResourceBag) -> ResourceBag:
        return ResourceBag(
            food=self.food + other.food,
            wood=self.wood + other.wood,
            ore=self.ore + other.ore,
            crystal=self.crystal + other.crystal,
            science=self.science + other.science,
        )

    def __sub__(self, other: ResourceBag) -> ResourceBag:
        return ResourceBag(
            food=self.food - other.food,
            wood=self.wood - other.wood,
            ore=self.ore - other.ore,
            crystal=self.crystal - other.crystal,
            science=self.science - other.science,
        )

    def can_afford(self, cost: ResourceBag) -> bool:
        """Check if this bag has enough resources to pay the cost."""
        return (
            self.food >= cost.food
            and self.wood >= cost.wood
            and self.ore >= cost.ore
            and self.crystal >= cost.crystal
            and self.science >= cost.science
        )


TechId = str


class UnitStats(BaseModel):
    """Base stats for unit types.

    ``required_tech`` (Phase 6) names the tech that must be in the player's
    ``ResearchState.completed`` set before a city may queue this unit. A
    ``None`` value means the unit is always available. Starter-tier techs
    (``bronze_working`` etc.) are pre-completed at game creation so they
    function as "unlocked from turn 1" for the purposes of this gate.
    """

    cost: ResourceBag
    moves: int
    hp: int
    sight: int
    attack: int
    attack_range: int
    special: str = ""
    required_tech: TechId | None = None


UNIT_STATS = {
    UnitType.SCOUT: UnitStats(
        cost=ResourceBag(food=10),
        moves=3,
        hp=2,
        sight=3,
        attack=1,
        attack_range=1,
        special="Ignores forest movement penalty",
        required_tech=None,
    ),
    UnitType.WORKER: UnitStats(
        cost=ResourceBag(food=15),
        moves=2,
        hp=2,
        sight=2,
        attack=0,
        attack_range=0,
        special="Builds improvements, cities",
        required_tech=None,
    ),
    UnitType.SOLDIER: UnitStats(
        cost=ResourceBag(food=15, ore=5),
        moves=2,
        hp=4,
        sight=2,
        attack=2,
        attack_range=1,
        special="+25% vs cities",
        required_tech="bronze_working",
    ),
    UnitType.ARCHER: UnitStats(
        cost=ResourceBag(food=15, wood=5),
        moves=2,
        hp=3,
        sight=3,
        attack=2,
        attack_range=2,
        special="Ranged; no counter-attack",
        required_tech="archery",
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
    """Base stats for building types.

    ``required_tech`` (Phase 6) gates the building behind a tech in the
    player's ``ResearchState.completed`` set. Starter-tier techs are
    pre-completed at game creation, so buildings gated on ``pottery`` or
    ``bronze_working`` are available from turn 1 and the gate is purely
    shaping the later game.
    """

    cost: ResourceBag
    hp: int
    effect: str
    required_tech: TechId | None = None


BUILDING_STATS = {
    BuildingType.GRANARY: BuildingStats(
        cost=ResourceBag(wood=20),
        hp=10,
        effect="+50% food output",
        required_tech="pottery",
    ),
    BuildingType.BARRACKS: BuildingStats(
        cost=ResourceBag(wood=25),
        hp=10,
        effect="-25% unit training cost",
        required_tech="bronze_working",
    ),
    BuildingType.WALLS: BuildingStats(
        cost=ResourceBag(ore=20),
        hp=15,
        effect="City gains +5 HP & ranged counter-fire",
        required_tech="masonry",
    ),
    BuildingType.MONUMENT: BuildingStats(
        cost=ResourceBag(wood=10),
        hp=5,
        effect="+1 culture/turn",
        required_tech="writing",
    ),
    BuildingType.LIBRARY: BuildingStats(
        cost=ResourceBag(wood=15, ore=5),
        hp=5,
        effect="+2 culture/turn",
        required_tech="writing",
    ),
    BuildingType.TEMPLE: BuildingStats(
        cost=ResourceBag(wood=15, ore=10, crystal=5),
        hp=5,
        effect="+3 culture/turn",
        required_tech="mysticism",
    ),
}


class Tech(BaseModel):
    """Static record describing a single tech in the tech tree.

    ``requires`` lists the prerequisite tech ids; a tech is researchable
    once every prereq is in the player's ``completed`` set. Starter techs
    have an empty ``requires`` list and are pre-populated into every
    player's ``completed`` set at game creation so turn 1 is playable.
    """

    id: TechId
    name: str
    cost_science: int
    requires: list[TechId] = Field(default_factory=list)
    unlocks_units: list[UnitType] = Field(default_factory=list)
    unlocks_buildings: list[BuildingType] = Field(default_factory=list)


# Static tech-tree graph. Phase 5 establishes the resource flow + research
# loop without gating any gameplay yet (``required_tech`` on units and
# buildings lands in Phase 6). The starter tier (empty ``requires``) is
# seeded into every player's ``completed`` set at game creation.
TECH_TREE: dict[TechId, Tech] = {
    "pottery": Tech(
        id="pottery",
        name="Pottery",
        cost_science=0,
        requires=[],
        unlocks_buildings=[BuildingType.GRANARY],
    ),
    "bronze_working": Tech(
        id="bronze_working",
        name="Bronze Working",
        cost_science=0,
        requires=[],
        unlocks_units=[UnitType.SOLDIER],
        unlocks_buildings=[BuildingType.BARRACKS],
    ),
    "masonry": Tech(
        id="masonry",
        name="Masonry",
        cost_science=10,
        requires=["bronze_working"],
        unlocks_buildings=[BuildingType.WALLS],
    ),
    "archery": Tech(
        id="archery",
        name="Archery",
        cost_science=10,
        requires=["bronze_working"],
        unlocks_units=[UnitType.ARCHER],
    ),
    "writing": Tech(
        id="writing",
        name="Writing",
        cost_science=15,
        requires=["pottery"],
        unlocks_buildings=[BuildingType.LIBRARY, BuildingType.MONUMENT],
    ),
    "mysticism": Tech(
        id="mysticism",
        name="Mysticism",
        cost_science=20,
        requires=["writing"],
        unlocks_buildings=[BuildingType.TEMPLE],
    ),
}


STARTER_TECHS: list[TechId] = [
    tech.id for tech in TECH_TREE.values() if not tech.requires
]


class ResearchState(BaseModel):
    """Per-player research state.

    ``completed`` tracks every tech the player has finished (starter techs
    are seeded here at game creation). ``active`` is the currently-chosen
    tech — ``None`` means no research is accruing. ``progress`` is the
    science points accumulated toward the active tech; on completion it
    resets to 0 and ``active`` clears. Switching ``active`` mid-research
    preserves ``progress`` (it applies to whichever tech is active next,
    clamped to that tech's cost).
    """

    completed: list[TechId] = Field(default_factory=list)
    active: TechId | None = None
    progress: int = 0


class Tile(BaseModel):
    """Map tile with terrain, resources, and occupants.

    ``unit_ids`` (Phase 3) is the ordered list of units currently on the
    tile. Stacking allows multiple friendly units to share a tile up to
    :data:`STACK_CAP`; the cap is enforced at move validation, not here.
    A legacy ``unit_id`` field is accepted on input and normalised to a
    one-element (or empty) list so pre-Phase-3 persisted states still
    deserialise.
    """

    id: int
    loc: Coord
    terrain: Terrain
    resource: Resource | None = None
    owner: PlayerId | None = None
    city_id: int | None = None
    unit_ids: list[int] = Field(default_factory=list)
    improvement: ImprovementType | None = None

    @model_validator(mode="before")
    @classmethod
    def _legacy_unit_id_to_unit_ids(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        if "unit_id" in data and "unit_ids" not in data:
            legacy = data.pop("unit_id")
            data["unit_ids"] = [legacy] if legacy is not None else []
        return data


class QueuedMoveOrder(BaseModel):
    """A persisted multi-turn move order (Phase 5).

    The engine resumes the head of each unit's ``orders_queue`` at the
    start of every turn, walking it along the shortest path to
    ``destination`` until the turn's movement budget is exhausted or the
    destination is reached. ``known_enemy_ids`` tracks the enemy unit ids
    already within the moving unit's sight; a new id appearing in sight
    triggers a newly-visible-enemy cancellation so the player isn't
    walked into an ambush they didn't know about when the order was
    issued. The list updates as the unit moves so seeing the *same*
    enemy again on later steps does not re-cancel.
    """

    type: Literal["move"] = "move"
    destination: Coord
    known_enemy_ids: list[int] = Field(default_factory=list)


QueuedOrder = Annotated[QueuedMoveOrder, Field(discriminator="type")]


class OrderCancellationReason(str, Enum):
    """Why a queued order was cancelled during turn resolution."""

    ENEMY_SIGHTED = "enemy_sighted"
    OBSTRUCTED = "obstructed"
    ATTACKED = "attacked"
    COMPLETED = "completed"


class UnitAutomation(str, Enum):
    """Persistent automation mode a unit can be placed into (Phase 6).

    Initial member: ``AUTO_IMPROVE`` — the engine selects the nearest
    unimproved own-territory tile, routes the worker there over multiple
    turns using the Phase 5 queue machinery, and on arrival issues the
    terrain-appropriate improvement build. Clears automatically when an
    enemy unit enters Chebyshev-distance-1 or the player submits a
    manual action for the worker.
    """

    AUTO_IMPROVE = "auto_improve"


class AutomationCancellationReason(str, Enum):
    """Why a unit's ``automation`` slot was cleared during turn resolution."""

    ENEMY_ADJACENT = "enemy_adjacent"
    MANUAL_OVERRIDE = "manual_override"
    NO_TARGET = "no_target"


class AutomationCancelledEvent(BaseModel):
    """A unit's automation was cleared during turn resolution.

    Scoped to the owning player via ``redact_state`` — other players
    never see automation events for units that aren't theirs.
    """

    id: int
    turn: int
    unit_id: int
    owner: PlayerId
    mode: UnitAutomation
    reason: AutomationCancellationReason


class OrderCancelledEvent(BaseModel):
    """A unit's queued order was cancelled (or completed) during turn resolution.

    Scoped to the owning player via ``redact_state`` — other players
    never see order events for units that aren't theirs.
    """

    id: int
    turn: int
    unit_id: int
    owner: PlayerId
    reason: OrderCancellationReason
    destination: Coord | None = None


class Unit(BaseModel):
    """Game unit with stats and current state.

    ``orders_queue`` (Phase 5) holds multi-turn orders the engine
    resumes at turn start. ``took_damage_last_turn`` is set by
    ``execute_attack`` when this unit's HP drops from an incoming attack
    or a counter-attack; on the next turn's resume phase it cancels any
    active queued order ("don't keep marching, you just got hit") and is
    then cleared before the new turn's actions are processed.
    """

    id: int
    owner: PlayerId
    type: UnitType
    hp: int
    moves_left: int
    loc: Coord
    orders_queue: list[QueuedOrder] = Field(default_factory=list)
    took_damage_last_turn: bool = False
    automation: UnitAutomation | None = None

    @property
    def stats(self) -> UnitStats:
        """Get the base stats for this unit type."""
        return UNIT_STATS[self.type]

    def can_attack(self, target_loc: Coord) -> bool:
        """Check if this unit can attack the target location."""
        distance = self.loc.distance_to(target_loc)
        return distance <= self.stats.attack_range and self.stats.attack > 0


UNIT_PRODUCTION_COST: dict[UnitType, int] = {
    UnitType.SCOUT: 5,
    UnitType.WORKER: 6,
    UnitType.SOLDIER: 8,
    UnitType.ARCHER: 7,
}


BUILDING_PRODUCTION_COST: dict[BuildingType, int] = {
    BuildingType.MONUMENT: 6,
    BuildingType.GRANARY: 8,
    BuildingType.BARRACKS: 10,
    BuildingType.WALLS: 10,
    BuildingType.LIBRARY: 10,
    BuildingType.TEMPLE: 12,
}


# Base per-turn production points for a city. Barracks boosts unit jobs.
CITY_BASE_PRODUCTION_RATE = 2
BARRACKS_UNIT_PRODUCTION_BONUS = 1


# Per-turn science income from a city. Library and Temple add on top of
# the base trickle — see ``City.science_per_turn``.
CITY_BASE_SCIENCE_PER_TURN = 1
LIBRARY_SCIENCE_BONUS = 2
TEMPLE_SCIENCE_BONUS = 1


# Phase 1 rules-reference constants. These live with the other engine
# constants so the REST/MCP rules reference has one canonical source.
# Phase 2+ will wire TERRAIN_ENTRY_COST into pathfinding; Phase 3 will
# wire STACK_CAP and FORTIFICATION_CITY_DEFENCE_BONUS into the movement
# validator and combat resolver. Publishing them here now means agents
# can plan against the target ruleset before the engine catches up.
RULES_SCHEMA_VERSION = 1

# Per-tile entry cost for land units. ``None`` means impassable.
# Future terrain types (e.g. hills, rivers) slot in here without touching
# engine code.
TERRAIN_ENTRY_COST: dict[Terrain, int | None] = {
    Terrain.PLAINS: 1,
    Terrain.FOREST: 2,
    Terrain.MOUNTAIN: None,
    Terrain.WATER: None,
}

# Max units that may co-occupy a single tile, friendly or enemy.
STACK_CAP = 5

# Multiplicative damage reduction for units defending on a friendly city
# tile. 0.25 means a defender on a city tile takes 25% less damage.
FORTIFICATION_CITY_DEFENCE_BONUS = 0.25


class BuildJob(BaseModel):
    """Building/unit construction job.

    ``type`` is ``"unit"`` or ``"building"``. ``target`` is a ``UnitType`` or
    ``BuildingType`` enum value (e.g. ``"scout"`` / ``"granary"``).
    ``progress`` accrues each turn at the city's production rate until it
    reaches ``total_cost``, at which point the item materialises and the
    job clears.
    """

    type: str
    target: str
    progress: int = 0
    total_cost: int = 1


class City(BaseModel):
    """Player city with buildings and production."""

    id: int
    owner: PlayerId
    loc: Coord
    hp: int = 10
    build_queue: list[BuildJob] = Field(default_factory=list)
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

    def science_per_turn(self) -> int:
        """Science output per turn from base + culture-building bonuses.

        Phase 5 wires science as a first-class resource. Every city
        contributes a base trickle so a player without Library or Temple
        still makes progress on research; Library and Temple add on top
        of that — the same buildings that boost culture also fuel
        research, reinforcing the "invest in culture" lever.
        """
        science = CITY_BASE_SCIENCE_PER_TURN
        if BuildingType.LIBRARY in self.buildings:
            science += LIBRARY_SCIENCE_BONUS
        if BuildingType.TEMPLE in self.buildings:
            science += TEMPLE_SCIENCE_BONUS
        return science

    def production_per_turn(self, job_kind: str = "unit") -> int:
        """Production points this city accrues per turn for ``job_kind``.

        Base rate is :data:`CITY_BASE_PRODUCTION_RATE`. Barracks adds
        :data:`BARRACKS_UNIT_PRODUCTION_BONUS` to unit jobs only.
        """
        rate = CITY_BASE_PRODUCTION_RATE
        if job_kind == "unit" and BuildingType.BARRACKS in self.buildings:
            rate += BARRACKS_UNIT_PRODUCTION_BONUS
        return rate


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


class ResourceSwapClause(BaseModel):
    """One-off simultaneous resource exchange ratified atomically.

    At acceptance time, the proposer transfers ``proposer_gives`` to the
    recipient and the recipient transfers ``recipient_gives`` to the proposer
    in a single atomic step. If either party cannot fund their side, the
    proposal fails (``PROPOSAL_FAILED_UNFUNDABLE``) and nobody is charged.
    ``Treaty.parties[0]`` is the proposer and ``parties[1]`` the recipient —
    this ordering is load-bearing for interpreting the two sides.
    """

    clause_type: Literal["resource_swap"] = "resource_swap"
    proposer_gives: ResourceBag = Field(default_factory=ResourceBag)
    recipient_gives: ResourceBag = Field(default_factory=ResourceBag)


class RecurringTributeClause(BaseModel):
    """Per-turn transfer from ``payer`` to the other party for a fixed span.

    ``turns_remaining`` decrements each diplomacy phase after a successful
    payment. If the payer cannot fund a payment, ``TRIBUTE_FAILED`` +
    ``TREATY_VIOLATED`` are emitted, the treaty is cancelled, and no partial
    payment is made.
    """

    clause_type: Literal["recurring_tribute"] = "recurring_tribute"
    payer: PlayerId
    amount: ResourceBag
    duration_turns: int = Field(gt=0, le=PEACE_CLAUSE_MAX_DURATION)
    turns_remaining: int = Field(ge=0)


TreatyClause = Annotated[
    PeaceClause | FreeTextClause | ResourceSwapClause | RecurringTributeClause,
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

    @model_validator(mode="before")
    @classmethod
    def _coerce_diplomacy_keys(cls, data: object) -> object:
        # Pydantic serialises tuple-keyed dicts to JSON as comma-joined
        # strings (e.g. ``("agent","caleb")`` → ``"agent,caleb"``) but
        # does not parse them back on load. Reconstruct the tuple here so
        # round-tripping through JSON storage works.
        if not isinstance(data, dict):
            return data
        diplomacy = data.get("diplomacy")
        if not isinstance(diplomacy, dict):
            return data
        fixed: dict[object, object] = {}
        for key, value in diplomacy.items():
            if isinstance(key, str) and "," in key:
                a, b = key.split(",", 1)
                fixed[(a, b)] = value
            else:
                fixed[key] = value
        data["diplomacy"] = fixed
        return data

    stockpiles: dict[PlayerId, ResourceBag] = Field(default_factory=dict)
    next_unit_id: int = 1
    next_city_id: int = 1
    next_event_id: int = 1
    next_message_id: int = 1
    next_proposal_id: int = 1
    next_treaty_id: int = 1
    next_order_event_id: int = 1
    next_automation_event_id: int = 1
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
    research: dict[PlayerId, ResearchState] = Field(default_factory=dict)
    order_events: list[OrderCancelledEvent] = Field(default_factory=list)
    automation_events: list[AutomationCancelledEvent] = Field(default_factory=list)

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
    """Attack another unit or city.

    Exactly one of ``target_id`` or ``target_tile`` must be supplied.
    ``target_id`` names a specific unit or city for deterministic
    targeting. ``target_tile`` (Phase 3) points at a tile and lets the
    engine pick a defender — useful when the defender is part of an
    enemy stack. With a stacked enemy tile the engine selects one
    defender uniformly at random via a RNG seeded off the game's
    ``rng_state`` + turn + attacker + tile, so replays stay deterministic.
    ``target_type`` remains ``"unit"`` or ``"city"``.
    """

    type: str = "ATTACK"
    attacker_id: int
    target_id: int | None = None
    target_tile: Coord | None = None
    target_type: str  # "unit" or "city"

    @model_validator(mode="after")
    def _exactly_one_target(self) -> AttackAction:
        if (self.target_id is None) == (self.target_tile is None):
            raise ValueError(
                "AttackAction requires exactly one of target_id or target_tile"
            )
        return self


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


class SetCityProductionAction(BaseModel):
    """Append an item (unit or building) to a city's ordered build queue.

    Exactly one of ``unit_type`` / ``building_type`` must be set. Resources
    are deducted at queue time, matching the Phase 3 semantics for the
    legacy ``TRAIN_UNIT`` / ``BUILD_BUILDING`` wrappers.
    """

    type: str = "SET_CITY_PRODUCTION"
    city_id: int
    unit_type: UnitType | None = None
    building_type: BuildingType | None = None


class CancelCityProductionAction(BaseModel):
    """Remove one entry from a city's build queue by index.

    Index 0 is the active job; cancelling it forfeits accumulated progress
    and does not refund the resources spent at queue time. Cancelling a
    waiting entry (index >= 1) refunds the resources since the job never
    started, matching player expectations that a mistake made but not yet
    acted on costs nothing.
    """

    type: str = "CANCEL_CITY_PRODUCTION"
    city_id: int
    queue_index: int


class ReorderCityQueueAction(BaseModel):
    """Permute a city's build queue.

    ``new_order`` must be a permutation of the current queue indices
    (``[0, 1, ..., len(queue)-1]``). The progress on the current active
    job carries with it: if the new order places a different job at index
    0, the previous active job's accumulated progress still sits on that
    job, and the new index-0 job advances next turn from its own
    (possibly zero) progress.
    """

    type: str = "REORDER_CITY_QUEUE"
    city_id: int
    new_order: list[int]


class QueueOrderAction(BaseModel):
    """Queue a multi-turn move order on a unit (Phase 5).

    The engine advances the unit along the shortest path to
    ``destination`` at the start of every turn, consuming that turn's
    movement budget until the destination is reached or a cancellation
    condition fires. Validation rejects unreachable destinations
    (impassable terrain, no path) at submission time.
    """

    type: str = "QUEUE_ORDER"
    unit_id: int
    destination: Coord


class CancelOrderAction(BaseModel):
    """Clear a unit's queued orders (Phase 5)."""

    type: str = "CANCEL_ORDER"
    unit_id: int


class SetAutomationAction(BaseModel):
    """Enable an automation mode on a unit (Phase 6).

    Currently supports ``UnitAutomation.AUTO_IMPROVE`` on workers. At
    turn resume the engine routes the worker to the nearest unimproved
    own-territory tile and issues the terrain-appropriate improvement
    build on arrival, repeating until the automation is cleared.
    """

    type: str = "SET_AUTOMATION"
    unit_id: int
    mode: UnitAutomation


class ClearAutomationAction(BaseModel):
    """Clear a unit's automation slot (Phase 6).

    Equivalent to the cancel half of the "one-click toggle" UX. Also
    clears any queued order the automation installed on the unit's
    behalf so the worker actually stops moving, not just stops picking
    fresh targets.
    """

    type: str = "CLEAR_AUTOMATION"
    unit_id: int


class ResignAction(BaseModel):
    """Concede the current game.

    Takes effect immediately at submission time — not deferred to turn
    resolution. The resigner's cities, units, and tile ownership are
    destroyed via the standard elimination path. In a 2-player game the
    remaining seat is declared winner and the game ends with
    ``end_reason='resignation'``. In a 3+ player game play continues and
    victory resolves when only one player has cities.

    ``type`` is a ``Literal`` (unlike the other action classes in this
    file) because ResignAction has no other required fields. Without a
    literal discriminator the Pydantic smart-union coercion on
    ``list[Action]`` would classify a bare ``{"type": "RESIGN"}``
    payload as whichever sibling type has the loosest fields. A literal
    makes RESIGN unambiguous.
    """

    type: Literal["RESIGN"] = "RESIGN"


class SetActiveResearchAction(BaseModel):
    """Set the player's active research tech.

    ``tech_id`` must be a real tech in ``TECH_TREE``, not already in the
    player's ``completed`` set, and must have all its prerequisites
    completed. Passing ``None`` clears the active slot without
    forfeiting accumulated ``progress`` — progress sits with the player
    and re-applies to whatever tech is active next (clamped to its cost).
    """

    type: str = "SET_ACTIVE_RESEARCH"
    tech_id: TechId | None = None


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
    | SetCityProductionAction
    | CancelCityProductionAction
    | ReorderCityQueueAction
    | SetActiveResearchAction
    | QueueOrderAction
    | CancelOrderAction
    | SetAutomationAction
    | ClearAutomationAction
    | ResignAction
)


class ActionResult(BaseModel):
    """Result of attempting to execute an action."""

    success: bool
    message: str
    action: Action


class ProductionCompletedEvent(BaseModel):
    """A city finished building an item during this turn's resolution."""

    city_id: int
    owner: PlayerId
    type: str  # "unit" or "building"
    target: str  # UnitType or BuildingType value
    turn: int


class ResearchCompletedEvent(BaseModel):
    """A player completed a tech during this turn's resolution.

    Scoped to the researching player's WebSocket connection only —
    research state is private per ``redact_state``. Carries the flat
    unlock lists so the client can surface "X is now buildable" without
    re-fetching ``TECH_TREE``.
    """

    player_id: PlayerId
    tech_id: TechId
    turn: int
    unlocks_units: list[UnitType] = Field(default_factory=list)
    unlocks_buildings: list[BuildingType] = Field(default_factory=list)


class TurnResult(BaseModel):
    """Result of processing a complete turn."""

    turn: int
    player_actions: dict[PlayerId, list[ActionResult]]
    state_hash: str
    victory: VictoryResult | None = None
    production_completed: list[ProductionCompletedEvent] = Field(default_factory=list)
    research_completed: list[ResearchCompletedEvent] = Field(default_factory=list)
