"""
REST API endpoints for game state and actions.
"""

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.connection import get_database_session
from ..game.models import Action, CreateGameRequest, GameState, PlayerId, PromptLog
from ..game.rules import redact_state
from .persistent_game_controller import get_persistent_game_controller

router = APIRouter()
security = HTTPBearer()


def get_current_player(
    token: HTTPAuthorizationCredentials = Depends(security),
) -> PlayerId:
    """Extract player ID from Bearer token."""
    # Simple token validation - in production, use JWT
    if not token.credentials.startswith("player_"):
        raise HTTPException(status_code=401, detail="Invalid token format")

    player_id = token.credentials[7:]  # Remove "player_" prefix
    return player_id


def get_current_player_optional(
    token: HTTPAuthorizationCredentials | None = Depends(HTTPBearer(auto_error=False)),
) -> PlayerId | None:
    """Extract player ID from Bearer token, returning None if no token provided."""
    if not token or not token.credentials:
        return None

    if not token.credentials.startswith("player_"):
        return None

    return token.credentials[7:]  # Remove "player_" prefix


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


class GameSummary(BaseModel):
    """Summary of a single game for listing."""

    game_id: str
    player_slots: int
    players: list[str]
    turn: int
    max_turns: int
    status: str
    winner: str | None
    victory_type: str | None
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
    session: AsyncSession = Depends(get_database_session),
) -> GamesListResponse:
    """
    List games with full metadata, pagination, filtering, and sorting.
    """
    try:
        controller = get_persistent_game_controller(session)
        games, total = await controller.list_games_with_metadata(
            status=status,
            limit=limit,
            offset=offset,
            sort_by=sort_by,
            sort_order=sort_order,
        )
        return GamesListResponse(
            games=[
                GameSummary(
                    game_id=g.id,
                    player_slots=g.player_slots,
                    players=g.players,
                    turn=g.turn,
                    max_turns=g.max_turns,
                    status=g.status,
                    winner=g.winner,
                    victory_type=g.victory_type,
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
    """Request to create a game lobby."""

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
    created_at: str
    updated_at: str
    ended_at: str | None


class JoinLeaveRequest(BaseModel):
    """Request to join or leave a game."""

    player_id: str = Field(description="Player identifier")


@router.post("/games", tags=["games"])
async def create_lobby(
    request: CreateLobbyRequest,
    game_id: str = Query(description="Unique game identifier"),
    session: AsyncSession = Depends(get_database_session),
    current_player: PlayerId = Depends(get_current_player),
) -> GameDetailResponse:
    """
    Create a new game lobby in waiting status. Map is generated but the game is not started.
    """
    try:
        controller = get_persistent_game_controller(session)
        await controller.create_lobby(
            game_id=game_id,
            player_slots=request.player_slots,
            map_width=request.map_width,
            map_height=request.map_height,
            seed=request.seed,
            creator=current_player,
        )
        # Return the created game detail
        game_info = await controller.get_game_info(game_id)
        if not game_info:
            raise HTTPException(
                status_code=500, detail="Failed to retrieve created game"
            )
        return _game_detail_response(game_info)
    except HTTPException:
        raise
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


@router.post("/games/{game_id}/join", tags=["games"])
async def join_game(
    game_id: str,
    session: AsyncSession = Depends(get_database_session),
    current_player: PlayerId = Depends(get_current_player),
) -> GameDetailResponse:
    """
    Join a waiting game. The player is identified by their Bearer token.
    """
    try:
        controller = get_persistent_game_controller(session)
        await controller.join_game(game_id, current_player)
        game_info = await controller.get_game_info(game_id)
        if not game_info:
            raise HTTPException(status_code=500, detail="Failed to retrieve game")
        return _game_detail_response(game_info)
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/games/{game_id}/leave", tags=["games"])
async def leave_game(
    game_id: str,
    session: AsyncSession = Depends(get_database_session),
    current_player: PlayerId = Depends(get_current_player),
) -> GameDetailResponse:
    """
    Leave a waiting game. The player is identified by their Bearer token.
    """
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
        created_at=game.created_at.isoformat(),
        updated_at=game.updated_at.isoformat(),
        ended_at=game.ended_at.isoformat() if game.ended_at else None,
    )


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
