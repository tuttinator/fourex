"""
REST API endpoints for game state and actions.
"""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPBearer

from ..game.models import Action, CreateGameRequest, GameState, PlayerId, PromptLog
from ..game.rules import redact_state
from .game_controller import GameController, get_game_controller

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


@router.get("/state")
async def get_game_state(
    game_id: str = "default",
    current_player: PlayerId | None = Depends(get_current_player_optional),
    controller: GameController = Depends(get_game_controller),
) -> GameState:
    """
    Get the current game state with optional fog-of-war applied for the requesting player.
    If no authentication token is provided, returns the full game state without fog-of-war.
    """
    try:
        state = controller.get_game_state(game_id)
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


@router.post("/actions")
async def submit_actions(
    actions: list[Action],
    game_id: str = "default",
    current_player: PlayerId = Depends(get_current_player),
    controller: GameController = Depends(get_game_controller),
) -> dict[str, str]:
    """
    Submit actions for the current turn.
    """
    try:
        controller.submit_player_actions(game_id, current_player, actions)
        return {"status": "actions_submitted", "count": str(len(actions))}

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/prompts")
async def submit_prompt_log(
    prompt_log: PromptLog,
    game_id: str = "default",
    current_player: PlayerId = Depends(get_current_player),
    controller: GameController = Depends(get_game_controller),
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

        controller.log_prompt(game_id, prompt_log)
        return {"status": "prompt_logged"}

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/games")
async def list_games(
    controller: GameController = Depends(get_game_controller),
) -> dict[str, list[str]]:
    """
    Kist all active games.
    """
    try:
        game_ids = controller.list_games()
        return {"games": game_ids}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/games/{game_id}/start")
async def start_game(
    game_id: str,
    request: CreateGameRequest,
    controller: GameController = Depends(get_game_controller),
) -> dict[str, str]:
    """
    Start a new game with the given players.
    """
    try:
        controller.create_game(game_id, request.players, request.seed)
        return {"status": "game_created", "game_id": game_id}

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
