"""
REST API endpoints for game state and actions.
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.connection import get_database_session
from ..game.models import Action, CreateGameRequest, GameState, PlayerId, PromptLog
from ..game.rules import redact_state
from .persistent_game_controller import get_persistent_game_controller

router = APIRouter()
security = HTTPBearer()


def get_current_player(token: str = Depends(security)) -> PlayerId:
    """Extract player ID from Bearer token."""
    # Simple token validation - in production, use JWT
    if not token.credentials.startswith("player_"):
        raise HTTPException(status_code=401, detail="Invalid token format")

    player_id = token.credentials[7:]  # Remove "player_" prefix
    return player_id


def get_current_player_optional(
    token: str = Depends(HTTPBearer(auto_error=False)),
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

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/games", tags=["games"])
async def list_games(
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, list[str]]:
    """
    List all active games.
    """
    try:
        controller = get_persistent_game_controller(session)
        game_ids = await controller.list_games()
        return {"games": game_ids}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/games/{game_id}/start", tags=["games"])
async def start_game(
    game_id: str,
    request: CreateGameRequest,
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, str]:
    """
    Start a new game with the given players.
    """
    try:
        controller = get_persistent_game_controller(session)
        await controller.create_game(game_id, request.players, request.seed)
        return {"status": "game_created", "game_id": game_id}

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/games/{game_id}/info", tags=["games"])
async def get_game_info(
    game_id: str,
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """
    Get game metadata and status.
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

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
