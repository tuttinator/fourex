"""
Game rules and turn resolution logic.
"""

import random
from copy import deepcopy

from .models import (
    BUILDING_PRODUCTION_COST,
    BUILDING_STATS,
    IMPROVEMENT_STATS,
    MESSAGE_BODY_MAX_LENGTH,
    MESSAGES_PER_TURN_LIMIT,
    TREATY_PROPOSAL_EXPIRY_TURNS,
    UNIT_PRODUCTION_COST,
    UNIT_STATS,
    Action,
    ActionResult,
    AttackAction,
    BuildBuildingAction,
    BuildImprovementAction,
    BuildingType,
    BuildJob,
    CancelTreatyAction,
    City,
    Coord,
    DeclareWarAction,
    DiplomaticEvent,
    DiplomaticEventType,
    DiplomaticState,
    FoundCityAction,
    FreeTextClause,
    GameState,
    ImprovementType,
    Message,
    MoveAction,
    PeaceClause,
    PlayerId,
    ProductionCompletedEvent,
    ProposeTreatyAction,
    RecurringTributeClause,
    Resource,
    ResourceBag,
    ResourceSwapClause,
    RespondToTreatyAction,
    SendMessageAction,
    Terrain,
    Tile,
    TrainUnitAction,
    Treaty,
    TreatyProposal,
    TurnResult,
    Unit,
    UnitType,
    VictoryResult,
    WithdrawTreatyAction,
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

    # Filter cities to only visible ones. Non-owners never see the active
    # ``build_queue`` even for cities they can otherwise see — production
    # plans are private.
    visible_cities = {}
    for city_id, city in redacted.cities.items():
        if city.loc not in visible_tiles:
            continue
        if city.owner != player_id:
            city.build_queue = None
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

    # Messages are strictly private to sender and recipient — third parties
    # cannot see content or existence regardless of discovery.
    redacted.messages = [
        msg
        for msg in state.messages
        if msg.sender == player_id or msg.recipient == player_id
    ]

    # Pending treaty proposals are private to proposer and recipient; third
    # parties see neither content nor existence. Ratified treaties in
    # ``active_treaties`` are public by design — no redaction applied.
    redacted.pending_proposals = [
        p
        for p in state.pending_proposals
        if p.proposer == player_id or p.recipient == player_id
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
    # Declaring war cancels every active treaty between the two parties.
    # The war is the antecedent signal, so these are routine cancellations,
    # not violations (per user story 6 + Phase 3 acceptance criteria).
    _cancel_treaties_between(state, actor, target, actor=actor, cause="war_declared")
    return ActionResult(
        success=True,
        message=f"{actor} declared war on {target}.",
        action=action,
    )


def _count_messages_sent_this_turn(state: GameState, sender: PlayerId) -> int:
    """Count messages ``sender`` has already sent during the current turn.

    Counts directly from ``state.messages`` (rather than a transient counter)
    so the limit is robust to replay and resubmission.
    """
    return sum(
        1
        for msg in state.messages
        if msg.sender == sender and msg.turn_sent == state.turn
    )


def execute_send_message(
    state: GameState, sender: PlayerId, action: SendMessageAction
) -> ActionResult:
    """Queue a private message from ``sender`` to ``action.recipient``.

    Validation:
    - Recipient cannot be the sender.
    - Recipient must be a player in the game and must have been discovered.
    - Body length must be between 1 and ``MESSAGE_BODY_MAX_LENGTH`` characters.
    - Sender cannot exceed ``MESSAGES_PER_TURN_LIMIT`` messages this turn.
    """
    recipient = action.recipient
    if recipient == sender:
        return ActionResult(
            success=False,
            message="Cannot send a message to yourself.",
            action=action,
        )
    if recipient not in state.players:
        return ActionResult(
            success=False,
            message=f"Player {recipient} is not in this game.",
            action=action,
        )
    if not has_discovered(state, sender, recipient):
        return ActionResult(
            success=False,
            message=f"Cannot message undiscovered player {recipient}.",
            action=action,
        )
    body_length = len(action.body)
    if body_length == 0:
        return ActionResult(
            success=False,
            message="Message body cannot be empty.",
            action=action,
        )
    if body_length > MESSAGE_BODY_MAX_LENGTH:
        return ActionResult(
            success=False,
            message=(
                f"Message body is {body_length} chars; limit is "
                f"{MESSAGE_BODY_MAX_LENGTH}."
            ),
            action=action,
        )
    if _count_messages_sent_this_turn(state, sender) >= MESSAGES_PER_TURN_LIMIT:
        return ActionResult(
            success=False,
            message=(
                f"Per-turn message limit reached ({MESSAGES_PER_TURN_LIMIT} "
                f"messages/turn)."
            ),
            action=action,
        )

    message = Message(
        id=state.next_message_id,
        sender=sender,
        recipient=recipient,
        body=action.body,
        turn_sent=state.turn,
    )
    state.messages.append(message)
    state.next_message_id += 1

    return ActionResult(
        success=True,
        message=f"{sender} sent a message to {recipient}.",
        action=action,
    )


def _treaty_involves(treaty: Treaty, player: PlayerId) -> bool:
    """Return True if ``player`` is one of the two treaty parties."""
    return player in treaty.parties


def _treaty_has_active_obligation(treaty: Treaty) -> bool:
    """Return True if cancellation of ``treaty`` should count as a violation.

    Durational obligations: unexpired ``PeaceClause`` or
    ``RecurringTributeClause``. Free-text clauses are purely informational,
    and one-off ``ResourceSwapClause`` is fully discharged at ratification —
    neither counts as an ongoing obligation.
    """
    for clause in treaty.clauses:
        if isinstance(clause, PeaceClause) and clause.turns_remaining > 0:
            return True
        if isinstance(clause, RecurringTributeClause) and clause.turns_remaining > 0:
            return True
    return False


def _cancel_treaties_between(
    state: GameState,
    a: PlayerId,
    b: PlayerId,
    actor: PlayerId,
    cause: str,
    violate_on_obligation: bool = False,
) -> None:
    """Cancel every active treaty between ``a`` and ``b`` with a given cause.

    Used by ``execute_declare_war`` (``violate_on_obligation=False``: the war
    declaration is the antecedent signal, so cancellations are not violations)
    and by the treacherous-attack branch (``violate_on_obligation=True``:
    attacking while a peace clause is still active is a violation).
    """
    key = _diplomacy_key(a, b)
    remaining: list[Treaty] = []
    for treaty in state.active_treaties:
        parties_key = _diplomacy_key(treaty.parties[0], treaty.parties[1])
        if parties_key == key:
            violated = violate_on_obligation and _treaty_has_active_obligation(treaty)
            event_type = (
                DiplomaticEventType.TREATY_VIOLATED
                if violated
                else DiplomaticEventType.TREATY_CANCELLED
            )
            emit_diplomatic_event(
                state,
                event_type,
                actor=actor,
                counterparty=b if actor == a else a,
                payload={"treaty_id": str(treaty.id), "cause": cause},
            )
        else:
            remaining.append(treaty)
    state.active_treaties = remaining


def _bag_has_negative(bag: ResourceBag) -> bool:
    """Return True if any resource field is below zero."""
    return bag.food < 0 or bag.wood < 0 or bag.ore < 0 or bag.crystal < 0


def _bag_is_zero(bag: ResourceBag) -> bool:
    """Return True if every resource field is exactly zero."""
    return bag.food == 0 and bag.wood == 0 and bag.ore == 0 and bag.crystal == 0


def _validate_resource_clauses(
    clauses: list, proposer: PlayerId, recipient: PlayerId
) -> str | None:
    """Shape-validate Phase 4 clauses. Returns an error string or None.

    Pydantic already enforces duration bounds; this covers the semantic
    rules (no negatives, at least one resource on each clause, tribute payer
    is one of the two parties).
    """
    for clause in clauses:
        if isinstance(clause, ResourceSwapClause):
            if _bag_has_negative(clause.proposer_gives) or _bag_has_negative(
                clause.recipient_gives
            ):
                return "Resource swap amounts cannot be negative."
            if _bag_is_zero(clause.proposer_gives) and _bag_is_zero(
                clause.recipient_gives
            ):
                return "Resource swap must transfer at least one resource."
        elif isinstance(clause, RecurringTributeClause):
            if clause.payer not in (proposer, recipient):
                return f"Tribute payer {clause.payer} must be one of the two parties."
            if _bag_has_negative(clause.amount):
                return "Recurring tribute amount cannot be negative."
            if _bag_is_zero(clause.amount):
                return "Recurring tribute amount must be positive."
    return None


def _aggregate_swap_totals(clauses: list) -> tuple[ResourceBag, ResourceBag]:
    """Sum all ResourceSwapClause sides into (proposer_total, recipient_total).

    Multi-clause proposals are ratified atomically, so the cumulative totals
    are what must be fundable — not any single clause in isolation.
    """
    proposer_total = ResourceBag()
    recipient_total = ResourceBag()
    for clause in clauses:
        if isinstance(clause, ResourceSwapClause):
            proposer_total = proposer_total + clause.proposer_gives
            recipient_total = recipient_total + clause.recipient_gives
    return proposer_total, recipient_total


def _precheck_ally_funding(
    state: GameState,
    clauses: list,
    proposer: PlayerId,
    recipient: PlayerId,
) -> str | None:
    """If proposer and recipient are allies, pre-check swap + tribute funding.

    Hybrid policy: allies see each other's treasuries, so unfundable deals are
    rejected up-front. Non-allies can still bluff — unfundable proposals pass
    here and fail at acceptance (swap) or tribute step (recurring).
    """
    if state.get_diplomatic_state(proposer, recipient) != DiplomaticState.ALLIANCE:
        return None
    proposer_bag = state.stockpiles.get(proposer, ResourceBag())
    recipient_bag = state.stockpiles.get(recipient, ResourceBag())

    p_total, r_total = _aggregate_swap_totals(clauses)
    if not proposer_bag.can_afford(p_total):
        return f"Proposer {proposer} cannot afford their swap side."
    if not recipient_bag.can_afford(r_total):
        return f"Recipient {recipient} cannot afford their swap side."

    for clause in clauses:
        if isinstance(clause, RecurringTributeClause):
            payer_bag = proposer_bag if clause.payer == proposer else recipient_bag
            if not payer_bag.can_afford(clause.amount):
                return f"Payer {clause.payer} cannot afford tribute amount."
    return None


def execute_propose_treaty(
    state: GameState, proposer: PlayerId, action: ProposeTreatyAction
) -> ActionResult:
    """Queue a treaty proposal awaiting the recipient's response.

    Validation:
    - Recipient must be a player, not the proposer, and discovered by proposer.
    - Proposal must have at least one clause.
    - Peace clauses must have positive duration; free-text must be non-empty
      (Pydantic-enforced).
    - Swap/tribute clauses must have non-negative amounts, at least one
      resource, and tribute payer must be a party.
    - If proposer and recipient are allies, swap + tribute clauses are
      pre-checked for fundability (hybrid policy: allies see treasuries,
      non-allies may bluff).
    """
    recipient = action.recipient
    if recipient == proposer:
        return ActionResult(
            success=False,
            message="Cannot propose a treaty to yourself.",
            action=action,
        )
    if recipient not in state.players:
        return ActionResult(
            success=False,
            message=f"Player {recipient} is not in this game.",
            action=action,
        )
    if not has_discovered(state, proposer, recipient):
        return ActionResult(
            success=False,
            message=f"Cannot propose to undiscovered player {recipient}.",
            action=action,
        )
    if not action.clauses:
        return ActionResult(
            success=False,
            message="Treaty must have at least one clause.",
            action=action,
        )

    shape_error = _validate_resource_clauses(action.clauses, proposer, recipient)
    if shape_error is not None:
        return ActionResult(success=False, message=shape_error, action=action)

    ally_funding_error = _precheck_ally_funding(
        state, action.clauses, proposer, recipient
    )
    if ally_funding_error is not None:
        return ActionResult(
            success=False,
            message=ally_funding_error,
            action=action,
        )

    # Normalise: for durational clauses, ensure turns_remaining matches
    # duration_turns at proposal time so the recipient sees exactly the
    # offered span rather than any client-supplied transient value.
    normalised_clauses: list = []
    for clause in action.clauses:
        if isinstance(clause, PeaceClause):
            normalised_clauses.append(
                PeaceClause(
                    duration_turns=clause.duration_turns,
                    turns_remaining=clause.duration_turns,
                )
            )
        elif isinstance(clause, RecurringTributeClause):
            normalised_clauses.append(
                RecurringTributeClause(
                    payer=clause.payer,
                    amount=clause.amount,
                    duration_turns=clause.duration_turns,
                    turns_remaining=clause.duration_turns,
                )
            )
        else:
            normalised_clauses.append(clause)

    proposal = TreatyProposal(
        id=state.next_proposal_id,
        proposer=proposer,
        recipient=recipient,
        clauses=normalised_clauses,
        turn_proposed=state.turn,
        expires_on_turn=state.turn + TREATY_PROPOSAL_EXPIRY_TURNS,
    )
    state.pending_proposals.append(proposal)
    state.next_proposal_id += 1

    emit_diplomatic_event(
        state,
        DiplomaticEventType.TREATY_PROPOSED,
        actor=proposer,
        counterparty=recipient,
        payload={
            "proposal_id": str(proposal.id),
            "clause_count": str(len(proposal.clauses)),
        },
    )

    return ActionResult(
        success=True,
        message=f"Proposal {proposal.id} sent to {recipient}.",
        action=action,
    )


def _apply_ratified_clauses(state: GameState, treaty: Treaty) -> None:
    """Apply the immediate effects of each clause in a newly-ratified treaty.

    - ``PeaceClause``: if the pair is currently at WAR, flip to PEACE. The
      per-clause ``turns_remaining`` tracks the active duration.
    - ``ResourceSwapClause``: both parties transfer their side simultaneously.
      Fundability has already been verified by the caller.
    - ``RecurringTributeClause``: no immediate effect — the first payment is
      made at end-of-turn in ``resolve_diplomacy_phase``.
    - ``FreeTextClause``: no mechanical effect.
    """
    proposer, recipient = treaty.parties
    for clause in treaty.clauses:
        if isinstance(clause, PeaceClause):
            current = state.get_diplomatic_state(proposer, recipient)
            if current == DiplomaticState.WAR:
                set_relation(state, proposer, recipient, DiplomaticState.PEACE)
        elif isinstance(clause, ResourceSwapClause):
            proposer_bag = state.stockpiles.get(proposer, ResourceBag())
            recipient_bag = state.stockpiles.get(recipient, ResourceBag())
            state.stockpiles[proposer] = (
                proposer_bag - clause.proposer_gives + clause.recipient_gives
            )
            state.stockpiles[recipient] = (
                recipient_bag - clause.recipient_gives + clause.proposer_gives
            )


def execute_respond_to_treaty(
    state: GameState, actor: PlayerId, action: RespondToTreatyAction
) -> ActionResult:
    """Accept or decline a pending proposal addressed to ``actor``."""
    proposal = next(
        (p for p in state.pending_proposals if p.id == action.proposal_id),
        None,
    )
    if proposal is None:
        return ActionResult(
            success=False,
            message=f"Proposal {action.proposal_id} not found.",
            action=action,
        )
    if proposal.recipient != actor:
        return ActionResult(
            success=False,
            message=(
                f"Proposal {proposal.id} is addressed to {proposal.recipient}; "
                f"only they can respond."
            ),
            action=action,
        )

    state.pending_proposals = [
        p for p in state.pending_proposals if p.id != proposal.id
    ]

    if not action.accept:
        emit_diplomatic_event(
            state,
            DiplomaticEventType.PROPOSAL_DECLINED,
            actor=actor,
            counterparty=proposal.proposer,
            payload={"proposal_id": str(proposal.id)},
        )
        return ActionResult(
            success=True,
            message=f"Proposal {proposal.id} declined.",
            action=action,
        )

    # Atomic fundability re-check for any resource-swap clauses. Evaluated
    # on the cumulative total per side, not per clause — the ratification is
    # simultaneous, so partial success isn't a thing.
    proposer_total, recipient_total = _aggregate_swap_totals(proposal.clauses)
    proposer_bag = state.stockpiles.get(proposal.proposer, ResourceBag())
    recipient_bag = state.stockpiles.get(proposal.recipient, ResourceBag())
    if not proposer_bag.can_afford(proposer_total) or not recipient_bag.can_afford(
        recipient_total
    ):
        # Discard the proposal with a public failure event; no treaty, no
        # partial transfers, nobody charged. Proposal is already removed from
        # pending_proposals above.
        emit_diplomatic_event(
            state,
            DiplomaticEventType.PROPOSAL_FAILED_UNFUNDABLE,
            actor=actor,
            counterparty=proposal.proposer,
            payload={"proposal_id": str(proposal.id)},
        )
        return ActionResult(
            success=True,
            message=(f"Proposal {proposal.id} failed: resource swap unfundable."),
            action=action,
        )

    treaty = Treaty(
        id=state.next_treaty_id,
        parties=(proposal.proposer, proposal.recipient),
        clauses=proposal.clauses,
        turn_ratified=state.turn,
    )
    state.next_treaty_id += 1
    state.active_treaties.append(treaty)
    _apply_ratified_clauses(state, treaty)

    emit_diplomatic_event(
        state,
        DiplomaticEventType.PROPOSAL_ACCEPTED,
        actor=actor,
        counterparty=proposal.proposer,
        payload={
            "proposal_id": str(proposal.id),
            "treaty_id": str(treaty.id),
        },
    )
    return ActionResult(
        success=True,
        message=f"Proposal {proposal.id} accepted; treaty {treaty.id} active.",
        action=action,
    )


def execute_withdraw_treaty(
    state: GameState, actor: PlayerId, action: WithdrawTreatyAction
) -> ActionResult:
    """Withdraw a pending proposal the caller previously made."""
    proposal = next(
        (p for p in state.pending_proposals if p.id == action.proposal_id),
        None,
    )
    if proposal is None:
        return ActionResult(
            success=False,
            message=f"Proposal {action.proposal_id} not found.",
            action=action,
        )
    if proposal.proposer != actor:
        return ActionResult(
            success=False,
            message=(
                f"Only the original proposer ({proposal.proposer}) may "
                f"withdraw proposal {proposal.id}."
            ),
            action=action,
        )

    state.pending_proposals = [
        p for p in state.pending_proposals if p.id != proposal.id
    ]
    emit_diplomatic_event(
        state,
        DiplomaticEventType.PROPOSAL_WITHDRAWN,
        actor=actor,
        counterparty=proposal.recipient,
        payload={"proposal_id": str(proposal.id)},
    )
    return ActionResult(
        success=True,
        message=f"Proposal {proposal.id} withdrawn.",
        action=action,
    )


def execute_cancel_treaty(
    state: GameState, actor: PlayerId, action: CancelTreatyAction
) -> ActionResult:
    """Unilaterally cancel an active treaty the caller is a party to.

    If the treaty has active obligations (e.g. unexpired peace clause), the
    cancellation is recorded as ``TREATY_VIOLATED``; otherwise as
    ``TREATY_CANCELLED``.
    """
    treaty = next(
        (t for t in state.active_treaties if t.id == action.treaty_id),
        None,
    )
    if treaty is None:
        return ActionResult(
            success=False,
            message=f"Treaty {action.treaty_id} not found.",
            action=action,
        )
    if not _treaty_involves(treaty, actor):
        return ActionResult(
            success=False,
            message=f"You are not a party to treaty {treaty.id}.",
            action=action,
        )

    counterparty = (
        treaty.parties[1] if treaty.parties[0] == actor else treaty.parties[0]
    )
    state.active_treaties = [t for t in state.active_treaties if t.id != treaty.id]

    violated = _treaty_has_active_obligation(treaty)
    event_type = (
        DiplomaticEventType.TREATY_VIOLATED
        if violated
        else DiplomaticEventType.TREATY_CANCELLED
    )
    emit_diplomatic_event(
        state,
        event_type,
        actor=actor,
        counterparty=counterparty,
        payload={"treaty_id": str(treaty.id), "cause": "unilateral_cancellation"},
    )
    return ActionResult(
        success=True,
        message=(f"Treaty {treaty.id} " f"{'violated' if violated else 'cancelled'}."),
        action=action,
    )


def resolve_diplomacy_phase(state: GameState) -> None:
    """Process tribute payments, decrement durations, expire finished treaties,
    and expire pending proposals past their deadline.

    Runs once per turn after action execution. Iteration order is fixed
    (sorted by treaty id / proposal id) so replays are bit-identical.

    Auto-expiry rule: a treaty expires at end-of-turn when it has no active
    durational clauses (peace or tribute) AND no free-text clauses. Free-text
    clauses keep the treaty alive indefinitely (cancellable only manually);
    a swap-only treaty therefore expires immediately after its ratification
    turn — the swap is a one-off with no ongoing obligation.
    """
    cancelled_treaty_ids: set[int] = set()
    expired_treaty_ids: list[int] = []

    for treaty in sorted(state.active_treaties, key=lambda t: t.id):
        # (1) Recurring tribute payments. Iterate clauses in index order for
        # determinism. If any tribute payment is unaffordable, emit
        # TRIBUTE_FAILED + TREATY_VIOLATED and cancel — no partial payment for
        # the failing clause; any already-successful payments earlier in this
        # loop stand.
        tribute_failed = False
        failed_clause: RecurringTributeClause | None = None
        for clause in treaty.clauses:
            if not isinstance(clause, RecurringTributeClause):
                continue
            if clause.turns_remaining <= 0:
                continue
            payer = clause.payer
            payee = (
                treaty.parties[1] if payer == treaty.parties[0] else treaty.parties[0]
            )
            payer_bag = state.stockpiles.get(payer, ResourceBag())
            if not payer_bag.can_afford(clause.amount):
                tribute_failed = True
                failed_clause = clause
                break
            state.stockpiles[payer] = payer_bag - clause.amount
            state.stockpiles[payee] = (
                state.stockpiles.get(payee, ResourceBag()) + clause.amount
            )
            emit_diplomatic_event(
                state,
                DiplomaticEventType.TRIBUTE_PAID,
                actor=payer,
                counterparty=payee,
                payload={
                    "treaty_id": str(treaty.id),
                    "food": str(clause.amount.food),
                    "wood": str(clause.amount.wood),
                    "ore": str(clause.amount.ore),
                    "crystal": str(clause.amount.crystal),
                },
            )
            clause.turns_remaining -= 1

        if tribute_failed and failed_clause is not None:
            payer = failed_clause.payer
            payee = (
                treaty.parties[1] if payer == treaty.parties[0] else treaty.parties[0]
            )
            emit_diplomatic_event(
                state,
                DiplomaticEventType.TRIBUTE_FAILED,
                actor=payer,
                counterparty=payee,
                payload={"treaty_id": str(treaty.id)},
            )
            emit_diplomatic_event(
                state,
                DiplomaticEventType.TREATY_VIOLATED,
                actor=payer,
                counterparty=payee,
                payload={"treaty_id": str(treaty.id), "cause": "tribute_failed"},
            )
            cancelled_treaty_ids.add(treaty.id)
            continue

        # (2) Decrement peace-clause durations.
        for clause in treaty.clauses:
            if isinstance(clause, PeaceClause) and clause.turns_remaining > 0:
                clause.turns_remaining -= 1

        # (3) Auto-expiry check.
        any_active_durational = any(
            (isinstance(c, PeaceClause) and c.turns_remaining > 0)
            or (isinstance(c, RecurringTributeClause) and c.turns_remaining > 0)
            for c in treaty.clauses
        )
        any_free_text = any(isinstance(c, FreeTextClause) for c in treaty.clauses)
        if not any_active_durational and not any_free_text:
            expired_treaty_ids.append(treaty.id)

    for treaty_id in expired_treaty_ids:
        treaty = next(t for t in state.active_treaties if t.id == treaty_id)
        emit_diplomatic_event(
            state,
            DiplomaticEventType.TREATY_EXPIRED,
            actor=treaty.parties[0],
            counterparty=treaty.parties[1],
            payload={"treaty_id": str(treaty.id)},
        )
    state.active_treaties = [
        t
        for t in state.active_treaties
        if t.id not in cancelled_treaty_ids and t.id not in expired_treaty_ids
    ]

    # Expire pending proposals whose deadline has been reached.
    expired_proposals: list[TreatyProposal] = [
        p
        for p in sorted(state.pending_proposals, key=lambda p: p.id)
        if state.turn >= p.expires_on_turn
    ]
    for proposal in expired_proposals:
        emit_diplomatic_event(
            state,
            DiplomaticEventType.PROPOSAL_EXPIRED,
            actor=proposal.proposer,
            counterparty=proposal.recipient,
            payload={"proposal_id": str(proposal.id)},
        )
    expired_ids = {p.id for p in expired_proposals}
    state.pending_proposals = [
        p for p in state.pending_proposals if p.id not in expired_ids
    ]


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
            # Active peace treaties between the parties are violated by the
            # treacherous strike; pure free-text treaties are cancelled.
            _cancel_treaties_between(
                state,
                attacker.owner,
                target.owner,
                actor=attacker.owner,
                cause="treacherous_attack",
                violate_on_obligation=True,
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
            _cancel_treaties_between(
                state,
                attacker.owner,
                target_city.owner,
                actor=attacker.owner,
                cause="treacherous_attack",
                violate_on_obligation=True,
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
    """Queue a unit for training in a city.

    Resources are deducted at queue time. The unit materialises only after
    the city's ``BuildJob`` accrues enough progress (see
    :func:`advance_production`). Phase 3 holds at most one active job per
    city: queuing while a job is already active is rejected.
    """
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

    if city.build_queue is not None:
        active = city.build_queue
        return ActionResult(
            success=False,
            message=(
                f"City {city.id} is already producing {active.target} "
                f"({active.progress}/{active.total_cost})"
            ),
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

    # Consume resources at queue time
    state.stockpiles[city.owner] = player_resources - actual_cost

    # Enqueue the job. total_cost is production points, derived from the
    # static UNIT_PRODUCTION_COST table (not the resource cost).
    city.build_queue = BuildJob(
        type="unit",
        target=action.unit_type.value,
        progress=0,
        total_cost=UNIT_PRODUCTION_COST[action.unit_type],
    )

    return ActionResult(
        success=True,
        message=(
            f"City {city.id} queued {action.unit_type.value} "
            f"(cost {city.build_queue.total_cost} production)"
        ),
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
    """Queue a building for construction in a city.

    Resources are deducted at queue time. The building materialises only
    after the city's ``BuildJob`` accrues enough progress (see
    :func:`advance_production`). Phase 3 holds at most one active job per
    city: queuing while a job is already active is rejected.
    """
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

    if city.build_queue is not None:
        active = city.build_queue
        return ActionResult(
            success=False,
            message=(
                f"City {city.id} is already producing {active.target} "
                f"({active.progress}/{active.total_cost})"
            ),
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

    # Consume resources at queue time
    state.stockpiles[player_id] = player_resources - building_stats.cost

    # Enqueue the job. total_cost is production points, derived from the
    # static BUILDING_PRODUCTION_COST table (not the resource cost).
    city.build_queue = BuildJob(
        type="building",
        target=action.building_type.value,
        progress=0,
        total_cost=BUILDING_PRODUCTION_COST[action.building_type],
    )

    return ActionResult(
        success=True,
        message=(
            f"City {city.id} queued {action.building_type.value} "
            f"(cost {city.build_queue.total_cost} production)"
        ),
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


def get_valid_attacks(
    state: GameState,
    unit_id: int,
    visible_coords: set[Coord] | None = None,
) -> list[dict]:
    """Compute all hostile targets a unit can legally attack this turn.

    A target (unit or city) is valid if:
    - Manhattan distance from the attacker <= ``unit.stats.attack_range``
    - The attacker has nonzero attack
    - The target is not allied with the attacker (ALLIANCE is forbidden;
      PEACE is allowed — it flips to WAR via the treacherous-attack path)
    - The target is not owned by the attacker
    - The target tile is in ``visible_coords`` (when supplied) so the
      list cannot leak positions of unexplored enemy units

    Each result dict carries ``target_type`` ("unit" | "city"),
    ``target_id``, ``x``, ``y``, ``distance``, ``owner``, ``hp``, and
    ``diplomatic_state`` (the relation between attacker and target
    before any treacherous-attack transition). The frontend uses this
    to render the attack highlight layer and to decide whether to warn
    about breaking peace.
    """
    attacker = state.get_unit(unit_id)
    if attacker is None:
        return []
    if attacker.stats.attack <= 0 or attacker.stats.attack_range <= 0:
        return []

    results: list[dict] = []
    for target in state.units.values():
        if target.id == attacker.id or target.owner == attacker.owner:
            continue
        distance = attacker.loc.distance_to(target.loc)
        if distance > attacker.stats.attack_range:
            continue
        if visible_coords is not None and target.loc not in visible_coords:
            continue
        rel = state.get_diplomatic_state(attacker.owner, target.owner)
        if rel == DiplomaticState.ALLIANCE:
            continue
        results.append(
            {
                "target_type": "unit",
                "target_id": target.id,
                "x": target.loc.x,
                "y": target.loc.y,
                "distance": distance,
                "owner": target.owner,
                "hp": target.hp,
                "diplomatic_state": rel.value,
            }
        )

    for city in state.cities.values():
        if city.owner == attacker.owner:
            continue
        distance = attacker.loc.distance_to(city.loc)
        if distance > attacker.stats.attack_range:
            continue
        if visible_coords is not None and city.loc not in visible_coords:
            continue
        rel = state.get_diplomatic_state(attacker.owner, city.owner)
        if rel == DiplomaticState.ALLIANCE:
            continue
        results.append(
            {
                "target_type": "city",
                "target_id": city.id,
                "x": city.loc.x,
                "y": city.loc.y,
                "distance": distance,
                "owner": city.owner,
                "hp": city.hp,
                "diplomatic_state": rel.value,
            }
        )

    results.sort(key=lambda r: (r["distance"], r["target_type"], r["target_id"]))
    return results


FOUND_CITY_COST = ResourceBag(food=15)


def can_found_city_here(state: GameState, worker_id: int) -> dict:
    """Report whether a worker can Found City on its current tile.

    Returns ``{"can_found": bool, "reason": str | None, "cost": dict}``.
    ``reason`` is a human-readable explanation when ``can_found`` is
    False; ``cost`` is the flat FOUND_CITY cost (15 food today) so the
    frontend can render an affordance without duplicating the constant.
    """
    cost_dict = {"food": FOUND_CITY_COST.food}
    worker = state.get_unit(worker_id)
    if worker is None:
        return {"can_found": False, "reason": "Worker not found", "cost": cost_dict}
    if worker.type != UnitType.WORKER:
        return {
            "can_found": False,
            "reason": f"Unit {worker.id} is not a worker",
            "cost": cost_dict,
        }
    tile = state.get_tile(worker.loc)
    if tile is None:
        return {
            "can_found": False,
            "reason": "Invalid location for city",
            "cost": cost_dict,
        }
    if tile.city_id is not None:
        return {
            "can_found": False,
            "reason": f"City already exists at {worker.loc}",
            "cost": cost_dict,
        }
    if tile.terrain in (Terrain.WATER, Terrain.MOUNTAIN):
        return {
            "can_found": False,
            "reason": f"Cannot found city on {tile.terrain.value}",
            "cost": cost_dict,
        }
    player_resources = state.stockpiles.get(worker.owner, ResourceBag())
    if not player_resources.can_afford(FOUND_CITY_COST):
        return {
            "can_found": False,
            "reason": (
                f"Cannot afford city (need {FOUND_CITY_COST.food} food, "
                f"have {player_resources.food})"
            ),
            "cost": cost_dict,
        }
    return {"can_found": True, "reason": None, "cost": cost_dict}


def get_valid_improvements(state: GameState, worker_id: int) -> list[dict]:
    """List improvement types a worker can legally build on its current tile.

    Workers build on the tile they're standing on (see ``execute_build_improvement``).
    Each returned entry carries ``improvement`` (enum value), ``cost``
    (ResourceBag as a dict), ``affordable`` (bool given the player's
    current stockpile), and ``valid`` (always True — a variant is only
    listed if it passes the terrain/resource/tile-free checks). The
    frontend uses ``affordable`` to grey out entries the player cannot
    yet buy without hiding them entirely.
    """
    worker = state.get_unit(worker_id)
    if worker is None or worker.type != UnitType.WORKER:
        return []
    tile = state.get_tile(worker.loc)
    if tile is None or tile.improvement is not None:
        return []
    player_resources = state.stockpiles.get(worker.owner, ResourceBag())

    results: list[dict] = []
    for imp_type, stats in IMPROVEMENT_STATS.items():
        if tile.terrain not in stats.valid_terrain:
            continue
        if (
            stats.required_resource is not None
            and tile.resource != stats.required_resource
        ):
            continue
        results.append(
            {
                "improvement": imp_type.value,
                "cost": {
                    "food": stats.cost.food,
                    "wood": stats.cost.wood,
                    "ore": stats.cost.ore,
                    "crystal": stats.cost.crystal,
                },
                "affordable": player_resources.can_afford(stats.cost),
                "terrain": tile.terrain.value,
                "resource": tile.resource.value if tile.resource else None,
            }
        )
    results.sort(key=lambda r: r["improvement"])
    return results


def get_trainable_units(state: GameState, city_id: int) -> list[dict]:
    """List unit types a city can train, with per-item costs and affordability.

    Costs reflect the city's ``unit_cost_multiplier`` (BARRACKS discount).
    The list is exhaustive over ``UNIT_STATS`` so the UI can render every
    variant and grey the unaffordable ones; ``affordable`` reflects the
    city owner's current stockpile.
    """
    city = state.get_city(city_id)
    if city is None:
        return []
    player_resources = state.stockpiles.get(city.owner, ResourceBag())
    cost_multiplier = city.unit_cost_multiplier()

    results: list[dict] = []
    for unit_type, stats in UNIT_STATS.items():
        actual_cost = ResourceBag(
            food=int(stats.cost.food * cost_multiplier),
            wood=int(stats.cost.wood * cost_multiplier),
            ore=int(stats.cost.ore * cost_multiplier),
            crystal=int(stats.cost.crystal * cost_multiplier),
        )
        results.append(
            {
                "unit_type": unit_type.value,
                "cost": {
                    "food": actual_cost.food,
                    "wood": actual_cost.wood,
                    "ore": actual_cost.ore,
                    "crystal": actual_cost.crystal,
                },
                "affordable": player_resources.can_afford(actual_cost),
                "stats": {
                    "hp": stats.hp,
                    "moves": stats.moves,
                    "sight": stats.sight,
                    "attack": stats.attack,
                    "attack_range": stats.attack_range,
                },
            }
        )
    results.sort(key=lambda r: r["unit_type"])
    return results


def get_buildable_buildings(state: GameState, city_id: int) -> list[dict]:
    """List building types a city can construct, with per-item costs and status.

    Exhaustive over ``BUILDING_STATS``. ``already_built`` flags buildings
    the city has; the UI hides/greys those. ``affordable`` reflects the
    city owner's current stockpile against the flat cost (no multipliers
    apply to buildings today).
    """
    city = state.get_city(city_id)
    if city is None:
        return []
    player_resources = state.stockpiles.get(city.owner, ResourceBag())

    results: list[dict] = []
    for building_type, stats in BUILDING_STATS.items():
        already = building_type in city.buildings
        results.append(
            {
                "building_type": building_type.value,
                "cost": {
                    "food": stats.cost.food,
                    "wood": stats.cost.wood,
                    "ore": stats.cost.ore,
                    "crystal": stats.cost.crystal,
                },
                "affordable": player_resources.can_afford(stats.cost),
                "already_built": already,
                "effect": stats.effect,
            }
        )
    results.sort(key=lambda r: r["building_type"])
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


def advance_production(state: GameState) -> list[ProductionCompletedEvent]:
    """Advance each city's active ``BuildJob`` by its production rate.

    Iterates cities in sorted ``city_id`` order so replays are deterministic.
    When a job's ``progress`` reaches ``total_cost`` the item materialises:
    units spawn on the city tile (or stall while the tile is occupied),
    buildings are added to ``city.buildings``. Completions are returned as
    events so the caller can broadcast them; the in-game effect has
    already been applied to ``state``.
    """
    completions: list[ProductionCompletedEvent] = []
    for city_id in sorted(state.cities.keys()):
        city = state.cities[city_id]
        job = city.build_queue
        if job is None:
            continue

        rate = city.production_per_turn(job.type)
        new_progress = job.progress + rate
        if new_progress < job.total_cost:
            job.progress = new_progress
            continue

        # Job has enough production to complete this turn.
        if job.type == "unit":
            try:
                unit_type = UnitType(job.target)
            except ValueError:
                # Corrupt target — drop the job to avoid a permanent stall.
                city.build_queue = None
                continue

            # Stall if the city tile is occupied: hold progress at total_cost
            # so the unit emerges the turn the tile frees up. Keeps the
            # single-slot invariant simple — no overflow bookkeeping.
            city_tile = state.get_tile(city.loc)
            if city_tile is not None and city_tile.unit_id is not None:
                job.progress = job.total_cost
                continue

            unit_stats = UNIT_STATS[unit_type]
            unit = Unit(
                id=state.next_unit_id,
                owner=city.owner,
                type=unit_type,
                hp=unit_stats.hp,
                moves_left=unit_stats.moves,
                loc=city.loc,
            )
            state.units[unit.id] = unit
            state.next_unit_id += 1
            if city_tile is not None:
                city_tile.unit_id = unit.id

        elif job.type == "building":
            try:
                building_type = BuildingType(job.target)
            except ValueError:
                city.build_queue = None
                continue
            city.buildings.add(building_type)

        else:
            # Unknown job type — drop it rather than stall forever.
            city.build_queue = None
            continue

        completions.append(
            ProductionCompletedEvent(
                city_id=city.id,
                owner=city.owner,
                type=job.type,
                target=job.target,
                turn=state.turn,
            )
        )
        city.build_queue = None

    return completions


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
            elif isinstance(action, SendMessageAction):
                result = execute_send_message(state, player_id, action)
            elif isinstance(action, ProposeTreatyAction):
                result = execute_propose_treaty(state, player_id, action)
            elif isinstance(action, RespondToTreatyAction):
                result = execute_respond_to_treaty(state, player_id, action)
            elif isinstance(action, WithdrawTreatyAction):
                result = execute_withdraw_treaty(state, player_id, action)
            elif isinstance(action, CancelTreatyAction):
                result = execute_cancel_treaty(state, player_id, action)
            else:
                result = ActionResult(
                    success=False,
                    message=f"Unknown action type: {action.type}",
                    action=action,
                )

            player_results.append(result)

        results[player_id] = player_results

    # Diplomacy-resolution phase: decrement clause durations, expire treaties,
    # expire pending proposals. Runs once after all player actions have been
    # processed so everyone sees the same turn-boundary state.
    resolve_diplomacy_phase(state)

    # Check for eliminations after actions resolve
    newly_eliminated = check_elimination(state)
    for player_id in newly_eliminated:
        eliminate_player(state, player_id)

    # Expand borders (culture accumulation + border expansion)
    accumulate_culture(state)

    # Heal stationary units in friendly territory
    heal_units(state)

    # Advance any active build jobs and collect completion events so the
    # caller can fan them out over the WebSocket. Runs before
    # collect_resources so a brand-new building (e.g. Granary) does not
    # affect the same turn's resource collection — it takes effect next
    # turn, matching the "commitment is immediate but payoff is delayed"
    # framing of multi-turn production.
    production_completed = advance_production(state)

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
        production_completed=production_completed,
    )
