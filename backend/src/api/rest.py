"""
REST API endpoints for game state and actions.
"""

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import (
    AuthContext,
    AuthError,
    create_player_key,
    require_api_key,
    require_api_key_optional,
)
from ..database.connection import get_database_session
from ..database.repository import GameRepository
from ..game.models import (
    FREE_TEXT_CLAUSE_MAX_LENGTH,
    MESSAGE_BODY_MAX_LENGTH,
    MESSAGES_PER_TURN_LIMIT,
    PEACE_CLAUSE_MAX_DURATION,
    TECH_TREE,
    Action,
    CancelTreatyAction,
    CreateGameRequest,
    DeclareWarAction,
    FreeTextClause,
    GameState,
    PeaceClause,
    PlayerId,
    PromptLog,
    ProposeTreatyAction,
    RecurringTributeClause,
    ResearchState,
    ResourceBag,
    ResourceSwapClause,
    RespondToTreatyAction,
    SendMessageAction,
    WithdrawTreatyAction,
)
from ..game.rules import (
    can_found_city_here,
    get_buildable_buildings,
    get_queueable_tiles,
    get_trainable_units,
    get_valid_attacks,
    get_valid_improvements,
    get_valid_moves,
    get_visible_tiles,
    redact_state,
)
from ..game.rules_reference import build_rules_reference
from ..identity import UserIdentityContext, require_user_identity
from .persistent_game_controller import get_persistent_game_controller

router = APIRouter()


def get_current_player(
    auth: AuthContext = Depends(require_api_key),
) -> PlayerId:
    """Resolve the caller's ``player_id`` from their per-game API key.

    Thin wrapper preserved so existing handlers can keep their
    ``current_player: PlayerId = Depends(get_current_player)`` signatures;
    the underlying dependency enforces both key validity and that the key
    matches the game_id on the request (path or query).
    """
    return auth.player_id


def get_current_player_optional(
    auth: AuthContext | None = Depends(require_api_key_optional),
) -> PlayerId | None:
    """Optional variant: returns ``None`` when the caller is unauthenticated.

    Used by ``GET /state`` and ``POST /games/{id}/start``'s legacy path to
    allow unauthenticated god-mode observation / test-only create-and-start
    flow respectively.
    """
    return auth.player_id if auth is not None else None


@router.get("/rules", tags=["rules"])
async def get_rules_reference() -> dict[str, Any]:
    """Return the canonical rules reference payload.

    Single source of truth for unit stats, building costs, improvement
    effects, terrain entry costs, combat formulas, stacking rules,
    queued-order cancellation conditions, and the tech tree. Static —
    no game context, no authentication — so agents and UI consumers can
    fetch it once per version and cache. Breaking shape changes bump
    ``schema_version``.
    """
    return build_rules_reference()


@router.get("/state", tags=["state"])
async def get_game_state(
    game_id: str = "default",
    current_player: PlayerId | None = Depends(get_current_player_optional),
    session: AsyncSession = Depends(get_database_session),
) -> GameState:
    """
    Get the current game state with optional fog-of-war applied for the requesting player.
    If no authentication token is provided, returns the full game state without fog-of-war.
    """
    try:
        controller = get_persistent_game_controller(session)
        state = await controller.get_game_state(game_id)
        if not state:
            raise HTTPException(status_code=404, detail="Game not found")

        # Apply fog-of-war only if player is authenticated
        if current_player:
            redacted_state = redact_state(state, current_player)
            return redacted_state
        else:
            # Return full state for observation/admin purposes
            return state

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/actions", tags=["state"])
async def submit_actions(
    actions: list[Action],
    game_id: str = "default",
    current_player: PlayerId = Depends(get_current_player),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, str]:
    """
    Submit actions for the current turn.
    """
    try:
        controller = get_persistent_game_controller(session)
        await controller.submit_player_actions(game_id, current_player, actions)
        return {"status": "actions_submitted", "count": str(len(actions))}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/games/{game_id}/my-submission", tags=["state"])
async def get_my_submission(
    game_id: str,
    current_player: PlayerId = Depends(get_current_player),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """Return the caller's submitted actions for the current turn.

    Lets the frontend restore the queued-orders UI after a page refresh:
    if the player has already submitted, the stored actions come back here
    so the view can repopulate the queue and show "waiting for turn to
    resolve". Returns ``submitted: false`` when nothing is on file.
    """
    controller = get_persistent_game_controller(session)
    state = await controller.get_game_state(game_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Game not found")

    existing = await controller.repo.get_turn_action(
        game_id, current_player, state.turn
    )
    if existing is None:
        return {
            "game_id": game_id,
            "player": current_player,
            "turn": state.turn,
            "submitted": False,
            "actions": [],
        }

    raw_list = existing.actions_json if isinstance(existing.actions_json, list) else []
    return {
        "game_id": game_id,
        "player": current_player,
        "turn": state.turn,
        "submitted": True,
        "actions": raw_list,
        "submitted_at": (
            existing.submitted_at.isoformat() if existing.submitted_at else None
        ),
    }


@router.get("/games/{game_id}/turn-submissions", tags=["state"])
async def get_turn_submissions(
    game_id: str,
    current_player: PlayerId = Depends(get_current_player),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """Return the roster of players who have submitted for the current turn.

    Phase 6 hydration surface: lets the gameplay view repopulate its
    per-opponent "deciding" vs "submitted" indicators on mount (and on
    every ``turn.resolved``) so a page refresh doesn't lose visibility
    into who the game is still waiting on. Live updates arrive via the
    ``turn.submitted`` WebSocket event, which carries the same roster.

    Auth: per-game bearer, same as every other gameplay endpoint. The
    response lists public ``player_id``s only — this is already surfaced
    via ``GameDetailResponse.players``, so it leaks no fog-of-war.
    """
    controller = get_persistent_game_controller(session)
    state = await controller.get_game_state(game_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Game not found")

    submitted = await controller.repo.get_all_turn_actions(game_id, state.turn)
    submitted_players = [ta.player_id for ta in submitted]
    return {
        "game_id": game_id,
        "turn": state.turn,
        "players": list(state.players),
        "submitted_players": submitted_players,
    }


@router.get("/games/{game_id}/units/{unit_id}/valid-moves", tags=["state"])
async def get_unit_valid_moves(
    game_id: str,
    unit_id: int,
    current_player: PlayerId = Depends(get_current_player),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """List the tiles a friendly unit can legally move to this turn.

    Backs the Phase 4 frontend gameplay tracer's "click a unit, see its
    moves" highlight. Re-uses the canonical ``rules.get_valid_moves``
    helper so client-side highlighting and server-side validation share
    one source of truth — the queue submission to ``POST /actions`` is
    still authoritative on rejection.

    Visibility: results are filtered by the caller's fog-of-war so the
    list cannot leak occupancy of unexplored tiles. Ownership: callers
    can only query their own units (404 otherwise — same shape as
    "unit not found" so we don't accidentally confirm an enemy unit's
    existence).
    """
    controller = get_persistent_game_controller(session)
    state = await controller.get_game_state(game_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Game not found")

    unit = state.get_unit(unit_id)
    if unit is None or unit.owner != current_player:
        raise HTTPException(status_code=404, detail="Unit not found")

    visible = get_visible_tiles(state, current_player)
    moves = get_valid_moves(state, unit_id, visible_coords=visible)
    return {
        "game_id": game_id,
        "unit_id": unit_id,
        "moves_left": unit.moves_left,
        "moves": moves,
    }


@router.get("/games/{game_id}/units/{unit_id}/queueable-tiles", tags=["state"])
async def get_unit_queueable_tiles(
    game_id: str,
    unit_id: int,
    current_player: PlayerId = Depends(get_current_player),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """List every tile the unit can reach (Phase 5 multi-turn queueing).

    Ignores ``moves_left`` so the client can offer destinations beyond
    the current turn's budget. Each tile includes the server-computed
    path and a ``turns_required`` estimate. The path may change each
    resume cycle if the map state evolves — this endpoint is a UX
    convenience, not a commitment.
    """
    controller = get_persistent_game_controller(session)
    state = await controller.get_game_state(game_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Game not found")

    unit = state.get_unit(unit_id)
    if unit is None or unit.owner != current_player:
        raise HTTPException(status_code=404, detail="Unit not found")

    visible = get_visible_tiles(state, current_player)
    tiles = get_queueable_tiles(state, unit_id, visible_coords=visible)
    return {
        "game_id": game_id,
        "unit_id": unit_id,
        "tiles": tiles,
    }


@router.get("/games/{game_id}/units/{unit_id}/valid-attacks", tags=["state"])
async def get_unit_valid_attacks(
    game_id: str,
    unit_id: int,
    current_player: PlayerId = Depends(get_current_player),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """List hostile targets a friendly unit can legally attack this turn.

    Backs the Phase 5 frontend attack-highlight layer. Re-uses
    ``rules.get_valid_attacks`` so highlighting and the server-side
    validator in ``execute_attack`` share one source of truth.

    Visibility: filtered by the caller's fog-of-war — targets on
    unexplored tiles are suppressed. Ownership: only the owner of
    ``unit_id`` may query (404 otherwise, matching the valid-moves
    oracle-prevention pattern).
    """
    controller = get_persistent_game_controller(session)
    state = await controller.get_game_state(game_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Game not found")

    unit = state.get_unit(unit_id)
    if unit is None or unit.owner != current_player:
        raise HTTPException(status_code=404, detail="Unit not found")

    visible = get_visible_tiles(state, current_player)
    attacks = get_valid_attacks(state, unit_id, visible_coords=visible)
    return {
        "game_id": game_id,
        "unit_id": unit_id,
        "attack_range": unit.stats.attack_range,
        "attack": unit.stats.attack,
        "targets": attacks,
    }


@router.get("/games/{game_id}/units/{unit_id}/can-found-city", tags=["state"])
async def get_unit_can_found_city(
    game_id: str,
    unit_id: int,
    current_player: PlayerId = Depends(get_current_player),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """Report whether a friendly worker can Found City on its current tile.

    Frontend surfaces a Found City control when ``can_found`` is true;
    when false, ``reason`` explains why so the UI can tooltip the
    greyed-out control. Only the owner of ``unit_id`` may query.
    """
    controller = get_persistent_game_controller(session)
    state = await controller.get_game_state(game_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Game not found")

    unit = state.get_unit(unit_id)
    if unit is None or unit.owner != current_player:
        raise HTTPException(status_code=404, detail="Unit not found")

    result = can_found_city_here(state, unit_id)
    return {
        "game_id": game_id,
        "unit_id": unit_id,
        **result,
    }


@router.get("/games/{game_id}/units/{unit_id}/valid-improvements", tags=["state"])
async def get_unit_valid_improvements(
    game_id: str,
    unit_id: int,
    current_player: PlayerId = Depends(get_current_player),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """List improvement types a friendly worker can build on its current tile.

    Workers build on the tile they occupy; results are exhaustive over
    the improvement types that pass terrain and tile-resource checks.
    ``affordable`` per entry reflects the caller's current stockpile so
    the UI can render all options and grey unaffordable ones.
    """
    controller = get_persistent_game_controller(session)
    state = await controller.get_game_state(game_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Game not found")

    unit = state.get_unit(unit_id)
    if unit is None or unit.owner != current_player:
        raise HTTPException(status_code=404, detail="Unit not found")

    improvements = get_valid_improvements(state, unit_id)
    tile = state.get_tile(unit.loc)
    return {
        "game_id": game_id,
        "unit_id": unit_id,
        "tile": {"x": unit.loc.x, "y": unit.loc.y} if tile else None,
        "improvements": improvements,
    }


@router.get("/games/{game_id}/cities/{city_id}/trainable-units", tags=["state"])
async def get_city_trainable_units(
    game_id: str,
    city_id: int,
    current_player: PlayerId = Depends(get_current_player),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """List unit types the caller's city can train, with cost and affordability.

    Costs reflect the city's BARRACKS discount where applicable. Callers
    can only query their own cities (404 otherwise — matches the unit-
    owned oracle-prevention pattern so enemy city IDs cannot be probed
    through this surface).
    """
    controller = get_persistent_game_controller(session)
    state = await controller.get_game_state(game_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Game not found")

    city = state.get_city(city_id)
    if city is None or city.owner != current_player:
        raise HTTPException(status_code=404, detail="City not found")

    units = get_trainable_units(state, city_id)
    return {
        "game_id": game_id,
        "city_id": city_id,
        "units": units,
    }


@router.get("/games/{game_id}/tech-tree", tags=["state"])
async def get_game_tech_tree(
    game_id: str,
    current_player: PlayerId = Depends(get_current_player),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """Return the full static tech graph plus the caller's research state.

    Phase 6 tech-tree panel — lists every tech with prerequisites and
    unlocks so the UI can render node states (researched/in-progress/
    available/locked). ``research`` is the caller's per-player block;
    other players' research is not exposed here.
    """
    controller = get_persistent_game_controller(session)
    state = await controller.get_game_state(game_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Game not found")
    if current_player not in state.players:
        raise HTTPException(status_code=404, detail="Player not in game")

    research = state.research.get(current_player) or ResearchState()
    tech_tree_dump = {
        tech_id: {
            "id": tech.id,
            "name": tech.name,
            "cost_science": tech.cost_science,
            "requires": list(tech.requires),
            "unlocks_units": [u.value for u in tech.unlocks_units],
            "unlocks_buildings": [b.value for b in tech.unlocks_buildings],
        }
        for tech_id, tech in TECH_TREE.items()
    }
    return {
        "game_id": game_id,
        "player": current_player,
        "tech_tree": tech_tree_dump,
        "research": {
            "completed": list(research.completed),
            "active": research.active,
            "progress": research.progress,
        },
    }


@router.get("/games/{game_id}/cities/{city_id}/buildable-buildings", tags=["state"])
async def get_city_buildable_buildings(
    game_id: str,
    city_id: int,
    current_player: PlayerId = Depends(get_current_player),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """List buildings the caller's city can construct, with cost and status.

    Exhaustive over building types. ``already_built`` flags the ones the
    city owns so the UI can hide/grey them; ``affordable`` reflects the
    caller's current stockpile.
    """
    controller = get_persistent_game_controller(session)
    state = await controller.get_game_state(game_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Game not found")

    city = state.get_city(city_id)
    if city is None or city.owner != current_player:
        raise HTTPException(status_code=404, detail="City not found")

    buildings = get_buildable_buildings(state, city_id)
    return {
        "game_id": game_id,
        "city_id": city_id,
        "buildings": buildings,
    }


@router.post("/prompts", tags=["state"])
async def submit_prompt_log(
    prompt_log: PromptLog,
    game_id: str = "default",
    current_player: PlayerId = Depends(get_current_player),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, str]:
    """
    Submit LLM prompt and response log for research purposes.
    """
    try:
        # Validate that the player matches the log
        if prompt_log.player != current_player:
            raise HTTPException(
                status_code=400,
                detail="Prompt log player must match authenticated player",
            )

        controller = get_persistent_game_controller(session)
        await controller.log_prompt(game_id, prompt_log)
        return {"status": "prompt_logged"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


class ScratchpadWriteRequest(BaseModel):
    content: str = Field(
        max_length=4000, description="Scratchpad text (max 4000 chars)"
    )
    turn_number: int | None = Field(
        default=None, description="Turn number (defaults to current turn)"
    )


@router.post("/scratchpad", tags=["memory"])
async def write_scratchpad(
    request: ScratchpadWriteRequest,
    game_id: str = "default",
    current_player: PlayerId = Depends(get_current_player),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, str]:
    """Write agent scratchpad entry for the current (or specified) turn."""
    try:
        controller = get_persistent_game_controller(session)
        state = await controller.get_game_state(game_id)
        if not state:
            raise HTTPException(status_code=404, detail="Game not found")

        turn = request.turn_number if request.turn_number is not None else state.turn
        await controller.repo.upsert_agent_memory(
            game_id, current_player, turn, request.content
        )
        return {"status": "scratchpad_saved", "turn": str(turn)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/scratchpad", tags=["memory"])
async def read_scratchpad(
    game_id: str = "default",
    turn_number: int | None = None,
    current_player: PlayerId = Depends(get_current_player),
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """Read agent scratchpad entry for the current (or specified) turn."""
    try:
        controller = get_persistent_game_controller(session)
        state = await controller.get_game_state(game_id)
        if not state:
            raise HTTPException(status_code=404, detail="Game not found")

        turn = turn_number if turn_number is not None else state.turn
        memory = await controller.repo.get_agent_memory(game_id, current_player, turn)
        return {
            "turn": turn,
            "content": memory.scratchpad_text if memory else None,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class SeatSummary(BaseModel):
    """One seat in a game's roster, as surfaced on the games list.

    ``user_identity_id`` is null when the seat was taken via an
    MCP-minted key (agents), and populated when a signed-in human
    joined through the frontend. The games list consumer uses this to
    decide whether the viewer is seated (Resume) vs a spectator
    (Observe), and to flag agent-only games.
    """

    player_id: str
    user_identity_id: int | None


class GameSummary(BaseModel):
    """Summary of a single game for listing."""

    game_id: str
    player_slots: int
    players: list[str]
    seats: list[SeatSummary]
    creator: str | None
    turn: int
    max_turns: int
    status: str
    winner: str | None
    victory_type: str | None
    end_reason: str | None
    archived_at: str | None
    archived_reason: str | None
    created_at: str
    updated_at: str
    ended_at: str | None


class GamesListResponse(BaseModel):
    """Paginated games list response."""

    games: list[GameSummary]
    total: int
    offset: int
    limit: int


@router.get("/games", tags=["games"])
async def list_games(
    status: Literal["waiting", "active", "ended", "created"] | None = Query(
        default=None, description="Filter by game status"
    ),
    sort_by: Literal["created_at", "turn", "status"] = Query(
        default="created_at", description="Field to sort by"
    ),
    sort_order: Literal["asc", "desc"] = Query(
        default="desc", description="Sort direction"
    ),
    offset: int = Query(default=0, ge=0, description="Pagination offset"),
    limit: int = Query(default=20, ge=1, le=100, description="Page size"),
    include_archived: bool = Query(
        default=False,
        description=(
            "Include soft-archived games. Default excludes them so the list "
            "stays clean; the Archived filter chip flips this to true."
        ),
    ),
    session: AsyncSession = Depends(get_database_session),
) -> GamesListResponse:
    """
    List games with full metadata, pagination, filtering, and sorting.
    """
    try:
        controller = get_persistent_game_controller(session)
        games, total, seats_by_game = await controller.list_games_with_metadata(
            status=status,
            limit=limit,
            offset=offset,
            sort_by=sort_by,
            sort_order=sort_order,
            include_archived=include_archived,
        )
        return GamesListResponse(
            games=[
                GameSummary(
                    game_id=g.id,
                    player_slots=g.player_slots,
                    players=g.players,
                    seats=[
                        SeatSummary(
                            player_id=player_id,
                            user_identity_id=user_identity_id,
                        )
                        for player_id, user_identity_id in seats_by_game.get(g.id, [])
                    ],
                    creator=g.creator,
                    turn=g.turn,
                    max_turns=g.max_turns,
                    status=g.status,
                    winner=g.winner,
                    victory_type=g.victory_type,
                    end_reason=g.end_reason,
                    archived_at=g.archived_at.isoformat() if g.archived_at else None,
                    archived_reason=g.archived_reason,
                    created_at=g.created_at.isoformat(),
                    updated_at=g.updated_at.isoformat(),
                    ended_at=g.ended_at.isoformat() if g.ended_at else None,
                )
                for g in games
            ],
            total=total,
            offset=offset,
            limit=limit,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class CreateLobbyRequest(BaseModel):
    """Request to create a game lobby.

    The caller's ``UserIdentity`` comes from the Auth.js JWT dependency;
    ``player_id`` is the in-game display name they want for their seat in
    this specific lobby. One identity may run multiple games under
    different display names.
    """

    player_id: str = Field(
        min_length=1,
        max_length=64,
        description="In-game display name the creator wants for slot 0",
    )
    player_slots: int = Field(ge=2, le=8, description="Number of player slots (2-8)")
    map_width: int = Field(default=20, ge=10, le=100, description="Map width")
    map_height: int = Field(default=20, ge=10, le=100, description="Map height")
    seed: int = Field(default=42, description="Random seed for map generation")


class GameDetailResponse(BaseModel):
    """Full game detail including lobby configuration."""

    game_id: str
    player_slots: int
    players: list[str]
    creator: str | None
    turn: int
    max_turns: int
    map_width: int
    map_height: int
    seed: int
    status: str
    winner: str | None
    victory_type: str | None
    end_reason: str | None
    archived_at: str | None
    archived_reason: str | None
    created_at: str
    updated_at: str
    ended_at: str | None


class JoinLeaveRequest(BaseModel):
    """Request to join or leave a game."""

    player_id: str = Field(
        min_length=1,
        max_length=64,
        description="In-game display name for the joining seat",
    )


class LobbyKeyResponse(BaseModel):
    """Lobby detail + freshly minted per-game API key.

    Returned by ``POST /games`` and ``POST /games/{game_id}/join``. The
    caller stores the plaintext ``api_key`` (we only persist its hash) and
    presents it as ``Authorization: Bearer`` on all gameplay/diplomacy
    calls for this game. The key is bound to
    ``(game_id, player_id, user_identity_id)`` and expires after 24h; the
    JWT-gated renewal endpoint rotates it in-place.
    """

    game: GameDetailResponse
    api_key: str


@router.post("/games", tags=["games"], response_model=LobbyKeyResponse)
async def create_lobby(
    request: CreateLobbyRequest,
    game_id: str = Query(description="Unique game identifier"),
    session: AsyncSession = Depends(get_database_session),
    identity: UserIdentityContext = Depends(require_user_identity),
) -> LobbyKeyResponse:
    """Create a new game lobby in waiting status.

    Requires a valid Auth.js JWT (via ``require_user_identity``). Seats
    the caller in slot 0 under ``request.player_id``, mints a PlayerApiKey
    attributed to their ``UserIdentity``, and returns the key so the
    browser can authenticate subsequent gameplay/diplomacy requests.
    """
    try:
        controller = get_persistent_game_controller(session)
        await controller.create_lobby(
            game_id=game_id,
            player_slots=request.player_slots,
            map_width=request.map_width,
            map_height=request.map_height,
            seed=request.seed,
            creator=request.player_id,
        )
        # Seat the creator immediately so the lobby isn't empty.
        await controller.join_game(game_id, request.player_id)
        api_key = await create_player_key(
            session,
            game_id,
            request.player_id,
            user_identity_id=identity.user_identity_id,
        )
        await session.commit()

        game_info = await controller.get_game_info(game_id)
        if not game_info:
            raise HTTPException(
                status_code=500, detail="Failed to retrieve created game"
            )
        return LobbyKeyResponse(game=_game_detail_response(game_info), api_key=api_key)
    except HTTPException:
        raise
    except AuthError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/games/{game_id}", tags=["games"])
async def get_game_detail(
    game_id: str,
    session: AsyncSession = Depends(get_database_session),
) -> GameDetailResponse:
    """
    Get full game detail including lobby configuration, player slots, and status.
    """
    try:
        controller = get_persistent_game_controller(session)
        game_info = await controller.get_game_info(game_id)
        if not game_info:
            raise HTTPException(status_code=404, detail="Game not found")
        return _game_detail_response(game_info)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/games/{game_id}/join", tags=["games"], response_model=LobbyKeyResponse)
async def join_game(
    game_id: str,
    request: JoinLeaveRequest,
    session: AsyncSession = Depends(get_database_session),
    identity: UserIdentityContext = Depends(require_user_identity),
) -> LobbyKeyResponse:
    """Join a waiting game and receive a per-game API key.

    Requires a valid Auth.js JWT. Appends the caller's chosen
    ``player_id`` to the game, mints a PlayerApiKey attributed to their
    ``UserIdentity``, and returns it so the browser can authenticate
    subsequent gameplay/diplomacy requests.
    """
    try:
        controller = get_persistent_game_controller(session)
        await controller.join_game(game_id, request.player_id)
        api_key = await create_player_key(
            session,
            game_id,
            request.player_id,
            user_identity_id=identity.user_identity_id,
        )
        await session.commit()

        game_info = await controller.get_game_info(game_id)
        if not game_info:
            raise HTTPException(status_code=500, detail="Failed to retrieve game")
        return LobbyKeyResponse(game=_game_detail_response(game_info), api_key=api_key)
    except HTTPException:
        raise
    except AuthError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/games/{game_id}/leave", tags=["games"])
async def leave_game(
    game_id: str,
    session: AsyncSession = Depends(get_database_session),
    current_player: PlayerId = Depends(get_current_player),
) -> GameDetailResponse:
    """Leave a waiting game. Authenticated by the caller's per-game API key."""
    try:
        controller = get_persistent_game_controller(session)
        await controller.leave_game(game_id, current_player)
        game_info = await controller.get_game_info(game_id)
        if not game_info:
            raise HTTPException(status_code=500, detail="Failed to retrieve game")
        return _game_detail_response(game_info)
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/games/{game_id}/start", tags=["games"])
async def start_game(
    game_id: str,
    request: CreateGameRequest | None = None,
    session: AsyncSession = Depends(get_database_session),
    current_player: PlayerId | None = Depends(get_current_player_optional),
) -> dict[str, str]:
    """
    Start a game. Supports two flows:
    - Lobby flow: authenticated creator starts a waiting game (no request body needed)
    - Legacy flow: provides players and seed in request body to create+start
    """
    try:
        controller = get_persistent_game_controller(session)

        # Lobby flow: start a waiting game
        if current_player:
            db_game = await controller.get_game_info(game_id)
            if db_game and db_game.status == "waiting":
                await controller.start_game(game_id, current_player)
                return {"status": "game_started", "game_id": game_id}

        # Legacy flow: create + start in one step
        if request and request.players:
            await controller.create_game(game_id, request.players, request.seed)
            return {"status": "game_created", "game_id": game_id}

        raise HTTPException(
            status_code=400, detail="Invalid request: provide players or use lobby flow"
        )
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/games/{game_id}/info", tags=["games"])
async def get_game_info(
    game_id: str,
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """
    Get game metadata and status (legacy endpoint, prefer GET /games/{game_id}).
    """
    try:
        controller = get_persistent_game_controller(session)
        game_info = await controller.get_game_info(game_id)
        if not game_info:
            raise HTTPException(status_code=404, detail="Game not found")

        return {
            "game_id": game_info.id,
            "players": game_info.players,
            "turn": game_info.turn,
            "max_turns": game_info.max_turns,
            "status": game_info.status,
            "winner": game_info.winner,
            "victory_type": game_info.victory_type,
            "created_at": game_info.created_at.isoformat(),
            "updated_at": game_info.updated_at.isoformat(),
            "ended_at": game_info.ended_at.isoformat() if game_info.ended_at else None,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _game_detail_response(game: Any) -> GameDetailResponse:
    """Convert a DB game record to a GameDetailResponse."""
    return GameDetailResponse(
        game_id=game.id,
        player_slots=game.player_slots,
        players=game.players,
        creator=game.creator,
        turn=game.turn,
        max_turns=game.max_turns,
        map_width=game.map_width,
        map_height=game.map_height,
        seed=game.seed,
        status=game.status,
        winner=game.winner,
        victory_type=game.victory_type,
        end_reason=game.end_reason,
        archived_at=game.archived_at.isoformat() if game.archived_at else None,
        archived_reason=game.archived_reason,
        created_at=game.created_at.isoformat(),
        updated_at=game.updated_at.isoformat(),
        ended_at=game.ended_at.isoformat() if game.ended_at else None,
    )


# --- Turn history & replay endpoints ---


class TurnSummary(BaseModel):
    """Summary of a single turn for listing."""

    turn_number: int
    state_hash: str
    player_count: int
    completed_at: str | None


class TurnListResponse(BaseModel):
    """Paginated turn list response."""

    turns: list[TurnSummary]
    total: int
    offset: int
    limit: int


class TurnDetailResponse(BaseModel):
    """Full turn detail with actions and results."""

    turn_number: int
    player_actions: dict[str, list[dict[str, Any]]]
    action_results: dict[str, list[dict[str, Any]]]
    state_hash: str
    completed_at: str | None


class PromptLogResponse(BaseModel):
    """A single prompt log entry."""

    player_id: str
    prompt: str
    response: str
    tokens_in: int
    tokens_out: int
    latency_ms: int
    llm_provider: str | None
    llm_model: str | None


class TurnPromptsResponse(BaseModel):
    """All prompt logs for a turn."""

    turn_number: int
    prompts: list[PromptLogResponse]


@router.get("/games/{game_id}/turns", tags=["replay"])
async def list_turns(
    game_id: str,
    offset: int = Query(default=0, ge=0, description="Pagination offset"),
    limit: int = Query(default=50, ge=1, le=200, description="Page size"),
    session: AsyncSession = Depends(get_database_session),
) -> TurnListResponse:
    """List all turns for a game with pagination."""
    try:
        repo = GameRepository(session)

        game = await repo.get_game(game_id)
        if not game:
            raise HTTPException(status_code=404, detail="Game not found")

        total = await repo.count_turns(game_id)
        turns = await repo.get_turn_history_paginated(
            game_id, limit=limit, offset=offset
        )

        return TurnListResponse(
            turns=[
                TurnSummary(
                    turn_number=t.turn_number,
                    state_hash=t.state_hash,
                    player_count=len(t.player_actions),
                    completed_at=t.completed_at.isoformat() if t.completed_at else None,
                )
                for t in turns
            ],
            total=total,
            offset=offset,
            limit=limit,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/games/{game_id}/turns/{turn_number}", tags=["replay"])
async def get_turn_detail(
    game_id: str,
    turn_number: int,
    session: AsyncSession = Depends(get_database_session),
) -> TurnDetailResponse:
    """Get full turn detail including player actions and action results."""
    try:
        repo = GameRepository(session)

        game = await repo.get_game(game_id)
        if not game:
            raise HTTPException(status_code=404, detail="Game not found")

        turn = await repo.get_game_turn(game_id, turn_number)
        if not turn:
            raise HTTPException(status_code=404, detail="Turn not found")

        return TurnDetailResponse(
            turn_number=turn.turn_number,
            player_actions=turn.player_actions,
            action_results=turn.action_results,
            state_hash=turn.state_hash,
            completed_at=turn.completed_at.isoformat() if turn.completed_at else None,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/games/{game_id}/turns/{turn_number}/state", tags=["replay"])
async def get_turn_state(
    game_id: str,
    turn_number: int,
    player: str | None = Query(
        default=None, description="Player ID for fog-of-war view"
    ),
    session: AsyncSession = Depends(get_database_session),
) -> GameState:
    """
    Get game state snapshot at a specific turn.

    Without player param: returns full god-mode state from GameSnapshot.
    With player param: returns fog-of-war redacted state from TurnSnapshot.
    """
    try:
        repo = GameRepository(session)

        game = await repo.get_game(game_id)
        if not game:
            raise HTTPException(status_code=404, detail="Game not found")

        if player:
            snapshot = await repo.get_turn_snapshot(game_id, player, turn_number)
            if not snapshot:
                raise HTTPException(
                    status_code=404,
                    detail=f"No snapshot found for player '{player}' at turn {turn_number}",
                )
            return GameState.model_validate(snapshot.state_json)
        else:
            # Try god-mode snapshot first
            snapshot = await repo.get_game_snapshot_at_turn(game_id, turn_number)
            if snapshot:
                return GameState.model_validate(snapshot.complete_state)

            # Fall back to current game state if requesting the latest turn
            state = GameState.model_validate(game.state)
            if turn_number == state.turn:
                return state

            raise HTTPException(
                status_code=404,
                detail=f"No god-mode snapshot at turn {turn_number}. "
                f"Full snapshots are saved every 10 turns, plus initial and final states. "
                f"Try adding a player parameter for fog-of-war view.",
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/games/{game_id}/turns/{turn_number}/prompts", tags=["replay"])
async def get_turn_prompts(
    game_id: str,
    turn_number: int,
    session: AsyncSession = Depends(get_database_session),
) -> TurnPromptsResponse:
    """Get LLM prompt logs for a specific turn."""
    try:
        repo = GameRepository(session)

        game = await repo.get_game(game_id)
        if not game:
            raise HTTPException(status_code=404, detail="Game not found")

        logs = await repo.get_prompt_logs_for_turn(game_id, turn_number)

        return TurnPromptsResponse(
            turn_number=turn_number,
            prompts=[
                PromptLogResponse(
                    player_id=log.player_id,
                    prompt=log.prompt,
                    response=log.response,
                    tokens_in=log.tokens_in,
                    tokens_out=log.tokens_out,
                    latency_ms=log.latency_ms,
                    llm_provider=log.llm_provider,
                    llm_model=log.llm_model,
                )
                for log in logs
            ],
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- Diplomacy endpoints (Phase 1: relations foundation) ---


class DeclareWarRequest(BaseModel):
    """Queue a DECLARE_WAR action against a discovered player."""

    target_player: PlayerId


class DiplomacyRelation(BaseModel):
    """A single pairwise diplomatic-state entry visible to the viewer."""

    player_a: PlayerId
    player_b: PlayerId
    state: str


class DiplomacyEventResponse(BaseModel):
    """A public diplomatic event entry visible to the viewer."""

    id: int
    type: str
    actor: PlayerId
    counterparty: PlayerId | None
    turn: int
    payload: dict[str, str]


class DiplomacyMessageResponse(BaseModel):
    """A private message visible only to its sender and recipient."""

    id: int
    sender: PlayerId
    recipient: PlayerId
    body: str
    turn_sent: int


class TreatyClauseResponse(BaseModel):
    """A clause on a pending or active treaty.

    Serialised as a discriminated object; only the fields relevant to
    ``clause_type`` are populated per entry.
    """

    clause_type: Literal["peace", "free_text", "resource_swap", "recurring_tribute"]
    duration_turns: int | None = None
    turns_remaining: int | None = None
    text: str | None = None
    proposer_gives: ResourceBag | None = None
    recipient_gives: ResourceBag | None = None
    payer: PlayerId | None = None
    amount: ResourceBag | None = None


class TreatyProposalResponse(BaseModel):
    """A pending proposal awaiting a response (visible only to proposer/recipient)."""

    id: int
    proposer: PlayerId
    recipient: PlayerId
    clauses: list[TreatyClauseResponse]
    turn_proposed: int
    expires_on_turn: int


class TreatyResponse(BaseModel):
    """A ratified active treaty (public to all players)."""

    id: int
    parties: tuple[PlayerId, PlayerId]
    clauses: list[TreatyClauseResponse]
    turn_ratified: int


class DiplomacyStateResponse(BaseModel):
    """Viewer's redacted diplomatic slice of game state."""

    game_id: str
    player: PlayerId
    turn: int
    discovered: list[PlayerId]
    relations: list[DiplomacyRelation]
    events: list[DiplomacyEventResponse]
    messages: list[DiplomacyMessageResponse]
    pending_proposals: list[TreatyProposalResponse]
    active_treaties: list[TreatyResponse]


class SendMessageRequest(BaseModel):
    """Queue a SEND_MESSAGE action addressed to a discovered player."""

    recipient: PlayerId
    body: str = Field(
        min_length=1,
        max_length=MESSAGE_BODY_MAX_LENGTH,
        description=f"Message body (1..{MESSAGE_BODY_MAX_LENGTH} chars).",
    )


class MessageListResponse(BaseModel):
    """Inbox + outbox slice for a player, optionally filtered."""

    game_id: str
    player: PlayerId
    turn: int
    messages: list[DiplomacyMessageResponse]


@router.get("/games/{game_id}/diplomacy", tags=["diplomacy"])
async def get_diplomacy(
    game_id: str,
    session: AsyncSession = Depends(get_database_session),
    current_player: PlayerId = Depends(get_current_player),
) -> DiplomacyStateResponse:
    """Return the viewer's redacted diplomatic view: discovered players,
    visible pairwise relations, and the public events feed."""
    try:
        controller = get_persistent_game_controller(session)
        state = await controller.get_game_state(game_id)
        if not state:
            raise HTTPException(status_code=404, detail="Game not found")

        redacted = redact_state(state, current_player)
        return DiplomacyStateResponse(
            game_id=game_id,
            player=current_player,
            turn=state.turn,
            discovered=redacted.discovered.get(current_player, []),
            relations=[
                DiplomacyRelation(player_a=k[0], player_b=k[1], state=v.value)
                for k, v in redacted.diplomacy.items()
            ],
            events=[
                DiplomacyEventResponse(
                    id=e.id,
                    type=e.type.value,
                    actor=e.actor,
                    counterparty=e.counterparty,
                    turn=e.turn,
                    payload=e.payload,
                )
                for e in redacted.diplomatic_events
            ],
            messages=[
                DiplomacyMessageResponse(
                    id=m.id,
                    sender=m.sender,
                    recipient=m.recipient,
                    body=m.body,
                    turn_sent=m.turn_sent,
                )
                for m in redacted.messages
            ],
            pending_proposals=[
                TreatyProposalResponse(
                    id=p.id,
                    proposer=p.proposer,
                    recipient=p.recipient,
                    clauses=[_serialise_clause(c) for c in p.clauses],
                    turn_proposed=p.turn_proposed,
                    expires_on_turn=p.expires_on_turn,
                )
                for p in redacted.pending_proposals
            ],
            active_treaties=[
                TreatyResponse(
                    id=t.id,
                    parties=t.parties,
                    clauses=[_serialise_clause(c) for c in t.clauses],
                    turn_ratified=t.turn_ratified,
                )
                for t in redacted.active_treaties
            ],
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _serialise_clause(
    clause: PeaceClause | FreeTextClause | ResourceSwapClause | RecurringTributeClause,
) -> TreatyClauseResponse:
    """Convert a typed clause into the wire-format response."""
    if isinstance(clause, PeaceClause):
        return TreatyClauseResponse(
            clause_type="peace",
            duration_turns=clause.duration_turns,
            turns_remaining=clause.turns_remaining,
        )
    if isinstance(clause, FreeTextClause):
        return TreatyClauseResponse(clause_type="free_text", text=clause.text)
    if isinstance(clause, ResourceSwapClause):
        return TreatyClauseResponse(
            clause_type="resource_swap",
            proposer_gives=clause.proposer_gives,
            recipient_gives=clause.recipient_gives,
        )
    return TreatyClauseResponse(
        clause_type="recurring_tribute",
        payer=clause.payer,
        amount=clause.amount,
        duration_turns=clause.duration_turns,
        turns_remaining=clause.turns_remaining,
    )


def _parse_resource_bag(raw: Any, clause_label: str) -> ResourceBag:
    """Parse a resource-bag dict tolerantly. Missing fields default to 0."""
    if raw is None:
        return ResourceBag()
    if not isinstance(raw, dict):
        raise HTTPException(
            status_code=400,
            detail=f"{clause_label} resource amount must be an object",
        )
    try:
        return ResourceBag(
            food=int(raw.get("food", 0) or 0),
            wood=int(raw.get("wood", 0) or 0),
            ore=int(raw.get("ore", 0) or 0),
            crystal=int(raw.get("crystal", 0) or 0),
        )
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=400,
            detail=f"{clause_label} resource values must be integers",
        )


def _parse_clauses_from_request(
    clauses: list[dict[str, Any]],
) -> list[PeaceClause | FreeTextClause | ResourceSwapClause | RecurringTributeClause]:
    """Parse incoming clause dicts into typed ``TreatyClause`` instances.

    Raises ``HTTPException(400)`` on unknown clause type or invalid fields.
    Semantic rules (non-negative amounts, tribute payer is a party, ally
    funding pre-check) are enforced later by ``execute_propose_treaty``.
    """
    parsed: list = []
    for raw in clauses:
        ctype = raw.get("clause_type")
        if ctype == "peace":
            try:
                duration = int(raw.get("duration_turns", 0))
            except (TypeError, ValueError):
                raise HTTPException(
                    status_code=400,
                    detail="peace clause duration_turns must be an integer",
                )
            if duration <= 0 or duration > PEACE_CLAUSE_MAX_DURATION:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"peace clause duration must be 1..{PEACE_CLAUSE_MAX_DURATION}"
                    ),
                )
            parsed.append(
                PeaceClause(
                    duration_turns=duration,
                    turns_remaining=duration,
                )
            )
        elif ctype == "free_text":
            text = str(raw.get("text", ""))
            if not 1 <= len(text) <= FREE_TEXT_CLAUSE_MAX_LENGTH:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"free_text clause length must be 1..{FREE_TEXT_CLAUSE_MAX_LENGTH}"
                    ),
                )
            parsed.append(FreeTextClause(text=text))
        elif ctype == "resource_swap":
            parsed.append(
                ResourceSwapClause(
                    proposer_gives=_parse_resource_bag(
                        raw.get("proposer_gives"), "resource_swap proposer_gives"
                    ),
                    recipient_gives=_parse_resource_bag(
                        raw.get("recipient_gives"), "resource_swap recipient_gives"
                    ),
                )
            )
        elif ctype == "recurring_tribute":
            payer = raw.get("payer")
            if not isinstance(payer, str) or not payer:
                raise HTTPException(
                    status_code=400,
                    detail="recurring_tribute clause requires non-empty payer",
                )
            try:
                duration = int(raw.get("duration_turns", 0))
            except (TypeError, ValueError):
                raise HTTPException(
                    status_code=400,
                    detail="recurring_tribute duration_turns must be an integer",
                )
            if duration <= 0 or duration > PEACE_CLAUSE_MAX_DURATION:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"recurring_tribute duration must be "
                        f"1..{PEACE_CLAUSE_MAX_DURATION}"
                    ),
                )
            parsed.append(
                RecurringTributeClause(
                    payer=payer,
                    amount=_parse_resource_bag(
                        raw.get("amount"), "recurring_tribute amount"
                    ),
                    duration_turns=duration,
                    turns_remaining=duration,
                )
            )
        else:
            raise HTTPException(status_code=400, detail=f"unknown clause_type: {ctype}")
    return parsed


@router.get("/games/{game_id}/diplomacy/messages", tags=["diplomacy"])
async def list_messages(
    game_id: str,
    counterparty: PlayerId | None = Query(
        default=None, description="Filter to messages with this player"
    ),
    since_turn: int | None = Query(
        default=None, description="Only return messages with turn_sent >= this"
    ),
    session: AsyncSession = Depends(get_database_session),
    current_player: PlayerId = Depends(get_current_player),
) -> MessageListResponse:
    """Return the caller's inbox + outbox, optionally filtered."""
    try:
        controller = get_persistent_game_controller(session)
        state = await controller.get_game_state(game_id)
        if not state:
            raise HTTPException(status_code=404, detail="Game not found")

        redacted = redact_state(state, current_player)
        messages = list(redacted.messages)
        if counterparty is not None:
            messages = [
                m
                for m in messages
                if m.sender == counterparty or m.recipient == counterparty
            ]
        if since_turn is not None:
            messages = [m for m in messages if m.turn_sent >= since_turn]
        messages.sort(key=lambda m: m.id)

        return MessageListResponse(
            game_id=game_id,
            player=current_player,
            turn=state.turn,
            messages=[
                DiplomacyMessageResponse(
                    id=m.id,
                    sender=m.sender,
                    recipient=m.recipient,
                    body=m.body,
                    turn_sent=m.turn_sent,
                )
                for m in messages
            ],
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/games/{game_id}/diplomacy/messages", tags=["diplomacy"])
async def send_message_endpoint(
    game_id: str,
    request: SendMessageRequest,
    session: AsyncSession = Depends(get_database_session),
    current_player: PlayerId = Depends(get_current_player),
) -> dict[str, str]:
    """Queue a SEND_MESSAGE action for the caller on the current turn.

    Appends to any actions already submitted by the caller this turn rather
    than replacing them, so players can send messages without losing queued
    moves.
    """
    try:
        controller = get_persistent_game_controller(session)
        state = await controller.get_game_state(game_id)
        if not state:
            raise HTTPException(status_code=404, detail="Game not found")

        existing = await controller.repo.get_turn_action(
            game_id, current_player, state.turn
        )
        existing_actions: list[Action] = []
        if existing and existing.actions_json:
            from ..mcp_server.tools.gameplay import _parse_action

            raw_list = (
                existing.actions_json if isinstance(existing.actions_json, list) else []
            )
            existing_actions = [_parse_action(a) for a in raw_list]

        new_action = SendMessageAction(recipient=request.recipient, body=request.body)
        merged = existing_actions + [new_action]

        sent_so_far = sum(
            1
            for a in existing_actions
            if isinstance(a, SendMessageAction) and a.recipient is not None
        )
        if sent_so_far >= MESSAGES_PER_TURN_LIMIT:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Per-turn message limit reached "
                    f"({MESSAGES_PER_TURN_LIMIT} messages/turn)."
                ),
            )

        await controller.submit_player_actions(game_id, current_player, merged)
        return {"status": "message_queued", "recipient": request.recipient}
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


class ProposeTreatyRequest(BaseModel):
    """Queue a PROPOSE_TREATY action to a discovered player."""

    recipient: PlayerId
    clauses: list[dict[str, Any]]


class RespondToTreatyRequest(BaseModel):
    """Accept or decline a pending proposal addressed to the caller."""

    accept: bool


async def _merge_and_submit_action(
    controller: Any,
    game_id: str,
    current_player: PlayerId,
    new_action: Action,
) -> None:
    """Append ``new_action`` to the caller's existing queued actions, then submit.

    Mirrors the send-message endpoint's "don't wipe queued moves" pattern.
    """
    state = await controller.get_game_state(game_id)
    if not state:
        raise HTTPException(status_code=404, detail="Game not found")

    existing = await controller.repo.get_turn_action(
        game_id, current_player, state.turn
    )
    existing_actions: list[Action] = []
    if existing and existing.actions_json:
        from ..mcp_server.tools.gameplay import _parse_action

        raw_list = (
            existing.actions_json if isinstance(existing.actions_json, list) else []
        )
        existing_actions = [_parse_action(a) for a in raw_list]

    merged = existing_actions + [new_action]
    await controller.submit_player_actions(game_id, current_player, merged)


@router.post("/games/{game_id}/diplomacy/treaties/proposals", tags=["diplomacy"])
async def propose_treaty_endpoint(
    game_id: str,
    request: ProposeTreatyRequest,
    session: AsyncSession = Depends(get_database_session),
    current_player: PlayerId = Depends(get_current_player),
) -> dict[str, str]:
    """Queue a PROPOSE_TREATY action for the caller on the current turn."""
    try:
        if not request.clauses:
            raise HTTPException(
                status_code=400, detail="Treaty must have at least one clause."
            )
        parsed_clauses = _parse_clauses_from_request(request.clauses)
        controller = get_persistent_game_controller(session)
        action = ProposeTreatyAction(
            recipient=request.recipient, clauses=parsed_clauses
        )
        await _merge_and_submit_action(controller, game_id, current_player, action)
        return {"status": "proposal_queued", "recipient": request.recipient}
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post(
    "/games/{game_id}/diplomacy/treaties/proposals/{proposal_id}/respond",
    tags=["diplomacy"],
)
async def respond_to_treaty_endpoint(
    game_id: str,
    proposal_id: int,
    request: RespondToTreatyRequest,
    session: AsyncSession = Depends(get_database_session),
    current_player: PlayerId = Depends(get_current_player),
) -> dict[str, str]:
    """Queue a RESPOND_TO_TREATY action for the caller on the current turn."""
    try:
        controller = get_persistent_game_controller(session)
        action = RespondToTreatyAction(proposal_id=proposal_id, accept=request.accept)
        await _merge_and_submit_action(controller, game_id, current_player, action)
        return {
            "status": "response_queued",
            "proposal_id": str(proposal_id),
            "accept": str(request.accept),
        }
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete(
    "/games/{game_id}/diplomacy/treaties/proposals/{proposal_id}",
    tags=["diplomacy"],
)
async def withdraw_treaty_endpoint(
    game_id: str,
    proposal_id: int,
    session: AsyncSession = Depends(get_database_session),
    current_player: PlayerId = Depends(get_current_player),
) -> dict[str, str]:
    """Queue a WITHDRAW_TREATY action for the caller on the current turn."""
    try:
        controller = get_persistent_game_controller(session)
        action = WithdrawTreatyAction(proposal_id=proposal_id)
        await _merge_and_submit_action(controller, game_id, current_player, action)
        return {"status": "withdrawal_queued", "proposal_id": str(proposal_id)}
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/games/{game_id}/diplomacy/treaties/{treaty_id}", tags=["diplomacy"])
async def cancel_treaty_endpoint(
    game_id: str,
    treaty_id: int,
    session: AsyncSession = Depends(get_database_session),
    current_player: PlayerId = Depends(get_current_player),
) -> dict[str, str]:
    """Queue a CANCEL_TREATY action for the caller on the current turn."""
    try:
        controller = get_persistent_game_controller(session)
        action = CancelTreatyAction(treaty_id=treaty_id)
        await _merge_and_submit_action(controller, game_id, current_player, action)
        return {"status": "cancellation_queued", "treaty_id": str(treaty_id)}
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/games/{game_id}/diplomacy/declare-war", tags=["diplomacy"])
async def declare_war(
    game_id: str,
    request: DeclareWarRequest,
    session: AsyncSession = Depends(get_database_session),
    current_player: PlayerId = Depends(get_current_player),
) -> dict[str, str]:
    """Submit a DECLARE_WAR action for the caller on the current turn."""
    try:
        controller = get_persistent_game_controller(session)
        action = DeclareWarAction(target_player=request.target_player)
        await controller.submit_player_actions(game_id, current_player, [action])
        return {"status": "declaration_submitted", "target": request.target_player}
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/games/{game_id}/archive", tags=["games"])
async def archive_game_endpoint(
    game_id: str,
    session: AsyncSession = Depends(get_database_session),
    identity: UserIdentityContext = Depends(require_user_identity),
) -> GameDetailResponse:
    """Soft-archive a game owned by the signed-in caller.

    Hides the game from the default ``GET /games`` listing but preserves
    every turn snapshot and action row. Restricted to the game's creator
    (slot-0 player); other signed-in users receive 403. Archiving stamps
    ``archived_reason='manual'``; the auto-archive sweep stamps the
    stale-* reasons instead.
    """
    try:
        controller = get_persistent_game_controller(session)
        game = await controller.archive_game(
            game_id, identity.user_identity_id, reason="manual"
        )
        await session.commit()
        return _game_detail_response(game)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/games/{game_id}/unarchive", tags=["games"])
async def unarchive_game_endpoint(
    game_id: str,
    session: AsyncSession = Depends(get_database_session),
    identity: UserIdentityContext = Depends(require_user_identity),
) -> GameDetailResponse:
    """Restore a previously-archived game.

    Creator-only, same auth contract as ``/archive``. Clears
    ``archived_at`` / ``archived_reason``; the game's ``status`` is
    untouched — a stale-active game that was archived stays ``ended``
    after unarchive.
    """
    try:
        controller = get_persistent_game_controller(session)
        game = await controller.unarchive_game(game_id, identity.user_identity_id)
        await session.commit()
        return _game_detail_response(game)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/games/{game_id}/restore", tags=["games"])
async def restore_game(
    game_id: str,
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, str]:
    """
    Restore game state from database snapshot.
    """
    try:
        controller = get_persistent_game_controller(session)
        state = await controller.restore_game_state(game_id)
        if not state:
            raise HTTPException(
                status_code=404, detail="Game not found or no snapshot available"
            )

        return {
            "status": "game_restored",
            "game_id": game_id,
            "turn": str(state.turn),
            "state_hash": state.hash_state(),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
