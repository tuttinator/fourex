"""
Game state and turn flow MCP tools: get_game_state, submit_actions,
validate_actions, is_my_turn.
"""

from datetime import UTC, datetime
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from ...api.turn_resolution import (
    TURN_TIMEOUT_SECONDS,
    check_and_resolve_turn,
)
from ...api.turn_resolution import (
    parse_action as _parse_action,
)
from ...auth import AuthError, authenticate
from ...database.connection import async_session_factory
from ...database.repository import GameRepository
from ...game.models import (
    Action,
    AttackAction,
    BuildBuildingAction,
    BuildImprovementAction,
    CancelTreatyAction,
    DeclareWarAction,
    FoundCityAction,
    GameState,
    MoveAction,
    ProposeTreatyAction,
    RespondToTreatyAction,
    SendMessageAction,
    TrainUnitAction,
    WithdrawTreatyAction,
)
from ...game.rules import redact_state


def _validate_actions_against_state(
    state: GameState, player_id: str, actions: list[Action]
) -> list[dict[str, Any]]:
    """Validate actions without mutating state. Returns per-action results."""
    from copy import deepcopy

    from ...game.rules import (
        execute_attack,
        execute_build_building,
        execute_build_improvement,
        execute_cancel_treaty,
        execute_declare_war,
        execute_found_city,
        execute_move,
        execute_propose_treaty,
        execute_respond_to_treaty,
        execute_send_message,
        execute_train_unit,
        execute_withdraw_treaty,
        reset_unit_moves,
    )

    # Work on a copy so we don't mutate the real state
    test_state = deepcopy(state)
    reset_unit_moves(test_state)

    results = []
    for action in actions:
        if isinstance(action, MoveAction):
            r = execute_move(test_state, action)
        elif isinstance(action, AttackAction):
            r = execute_attack(test_state, action)
        elif isinstance(action, FoundCityAction):
            r = execute_found_city(test_state, action)
        elif isinstance(action, TrainUnitAction):
            r = execute_train_unit(test_state, action)
        elif isinstance(action, BuildImprovementAction):
            r = execute_build_improvement(test_state, action)
        elif isinstance(action, BuildBuildingAction):
            r = execute_build_building(test_state, action)
        elif isinstance(action, DeclareWarAction):
            r = execute_declare_war(test_state, player_id, action)
        elif isinstance(action, SendMessageAction):
            r = execute_send_message(test_state, player_id, action)
        elif isinstance(action, ProposeTreatyAction):
            r = execute_propose_treaty(test_state, player_id, action)
        elif isinstance(action, RespondToTreatyAction):
            r = execute_respond_to_treaty(test_state, player_id, action)
        elif isinstance(action, WithdrawTreatyAction):
            r = execute_withdraw_treaty(test_state, player_id, action)
        elif isinstance(action, CancelTreatyAction):
            r = execute_cancel_treaty(test_state, player_id, action)
        else:
            results.append(
                {"valid": False, "message": f"Unsupported action type: {action.type}"}
            )
            continue
        results.append({"valid": r.success, "message": r.message})
    return results


def register(mcp: FastMCP) -> None:
    """Register game state and turn flow tools on the MCP server."""

    @mcp.tool(
        name="get_game_state",
        description=(
            "Get the current fog-of-war-redacted game state for the authenticated "
            "player. Returns only tiles, units, and cities within your sight range."
        ),
        annotations=ToolAnnotations(
            title="Get Game State",
            readOnlyHint=True,
            openWorldHint=False,
        ),
        meta={"tags": ["gameplay", "query"]},
    )
    async def get_game_state(api_key: str) -> dict[str, Any]:
        """Get your current view of the game world.

        Args:
            api_key: Your player API key (received from create_game or join_game).

        Returns:
            Fog-of-war-redacted game state including visible tiles, units,
            cities, your stockpile, and current turn number.
        """
        async with async_session_factory() as session:
            try:
                auth = await authenticate(session, api_key)
            except AuthError as e:
                return {"error": str(e)}

            repo = GameRepository(session)
            game = await repo.get_game(auth.game_id)
            if game is None:
                return {"error": f"Game {auth.game_id} not found."}

            state = GameState.model_validate(game.state)
            redacted = redact_state(state, auth.player_id)

        return {
            "game_id": auth.game_id,
            "player": auth.player_id,
            "turn": state.turn,
            "status": game.status,
            "state": redacted.model_dump(mode="json"),
        }

    @mcp.tool(
        name="submit_actions",
        description=(
            "Submit your actions for the current turn. Once all players have "
            "submitted (or the 10-minute timeout fires), the turn resolves "
            "automatically. You may only submit once per turn — resubmitting "
            "overwrites your previous submission."
        ),
        annotations=ToolAnnotations(
            title="Submit Actions",
            readOnlyHint=False,
            openWorldHint=False,
        ),
        meta={"tags": ["gameplay", "action"]},
    )
    async def submit_actions(
        api_key: str,
        actions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Submit actions for the current turn.

        Args:
            api_key: Your player API key.
            actions: List of action objects. Each must have a "type" field.
                Supported types: MOVE, ATTACK, FOUND_CITY, TRAIN_UNIT,
                BUILD_IMPROVEMENT, BUILD_BUILDING.

        Returns:
            Confirmation of submission and whether the turn resolved.
        """
        async with async_session_factory() as session:
            try:
                auth = await authenticate(session, api_key)
            except AuthError as e:
                return {"error": str(e)}

            repo = GameRepository(session)
            game = await repo.get_game(auth.game_id)
            if game is None:
                return {"error": f"Game {auth.game_id} not found."}

            if game.status == "ended":
                return {"error": "Game has ended."}

            state = GameState.model_validate(game.state)

            # Parse and validate actions
            try:
                parsed = [_parse_action(a) for a in actions]
            except (ValueError, Exception) as e:
                return {"error": f"Invalid action: {e}"}

            # Validate actions against current state
            validation = _validate_actions_against_state(state, auth.player_id, parsed)
            invalid = [v for v in validation if not v["valid"]]
            if invalid:
                return {
                    "error": "Some actions are invalid.",
                    "validation": validation,
                }

            # Activate the game on first submission
            if game.status == "created":
                from sqlalchemy import update as sa_update

                from ...database.models import Game as GameModel

                now = datetime.now(UTC).replace(tzinfo=None)
                await repo.session.execute(
                    sa_update(GameModel)
                    .where(GameModel.id == auth.game_id)
                    .values(
                        status="active",
                        turn_started_at=now,
                    )
                )

            # If turn_started_at is not set (e.g. game was already active),
            # set it now as a fallback.
            if game.turn_started_at is None:
                from sqlalchemy import update as sa_update

                from ...database.models import Game as GameModel

                now = datetime.now(UTC).replace(tzinfo=None)
                await repo.session.execute(
                    sa_update(GameModel)
                    .where(GameModel.id == auth.game_id)
                    .values(turn_started_at=now)
                )

            # Store actions (upsert — allows resubmission)
            actions_json = [a.model_dump(mode="json") for a in parsed]
            await repo.upsert_turn_action(
                game_id=auth.game_id,
                player_id=auth.player_id,
                turn_number=state.turn,
                actions_json=actions_json,
            )

            # Phase 6: fan out turn.submitted before the resolve check so
            # subscribers always see the submission frame (REST path does
            # the same in PersistentGameController.submit_player_actions).
            from ...api.websocket import broadcast_turn_submitted

            submitted = await repo.get_all_turn_actions(auth.game_id, state.turn)
            await broadcast_turn_submitted(
                game_id=auth.game_id,
                player_id=auth.player_id,
                turn=state.turn,
                submitted_players=[ta.player_id for ta in submitted],
            )

            # Check if this completes the turn
            resolve_result = await check_and_resolve_turn(repo, auth.game_id)

            await session.commit()

        result: dict[str, Any] = {
            "game_id": auth.game_id,
            "player": auth.player_id,
            "turn": state.turn,
            "actions_submitted": len(parsed),
        }

        if resolve_result:
            result["turn_resolved"] = True
            result["new_turn"] = resolve_result["new_turn"]
            if resolve_result["timed_out"]:
                result["timed_out_players"] = resolve_result["skipped_players"]
        else:
            result["turn_resolved"] = False
            result["waiting_for"] = "other players to submit"

        return result

    @mcp.tool(
        name="validate_actions",
        description=(
            "Validate proposed actions without submitting them. Returns "
            "per-action validity and error messages. Use this to check "
            "your plan before committing to it."
        ),
        annotations=ToolAnnotations(
            title="Validate Actions",
            readOnlyHint=True,
            openWorldHint=False,
        ),
        meta={"tags": ["gameplay", "validation"]},
    )
    async def validate_actions(
        api_key: str,
        actions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Dry-run validation of proposed actions.

        Args:
            api_key: Your player API key.
            actions: List of action objects to validate.

        Returns:
            Per-action validation results with valid/invalid status and messages.
        """
        async with async_session_factory() as session:
            try:
                auth = await authenticate(session, api_key)
            except AuthError as e:
                return {"error": str(e)}

            repo = GameRepository(session)
            game = await repo.get_game(auth.game_id)
            if game is None:
                return {"error": f"Game {auth.game_id} not found."}

            state = GameState.model_validate(game.state)

            try:
                parsed = [_parse_action(a) for a in actions]
            except (ValueError, Exception) as e:
                return {"error": f"Invalid action format: {e}"}

            validation = _validate_actions_against_state(state, auth.player_id, parsed)

        all_valid = all(v["valid"] for v in validation)
        return {
            "game_id": auth.game_id,
            "player": auth.player_id,
            "turn": state.turn,
            "all_valid": all_valid,
            "results": validation,
        }

    @mcp.tool(
        name="is_my_turn",
        description=(
            "Check whether the game is waiting for your action submission. "
            "Returns the current turn number, whether you have already "
            "submitted, and seconds remaining before the turn times out."
        ),
        annotations=ToolAnnotations(
            title="Is My Turn",
            readOnlyHint=True,
            openWorldHint=False,
        ),
        meta={"tags": ["gameplay", "query"]},
    )
    async def is_my_turn(api_key: str) -> dict[str, Any]:
        """Check your turn status.

        Args:
            api_key: Your player API key.

        Returns:
            Turn number, submission status, time remaining, and game status.
        """
        async with async_session_factory() as session:
            try:
                auth = await authenticate(session, api_key)
            except AuthError as e:
                return {"error": str(e)}

            repo = GameRepository(session)
            game = await repo.get_game(auth.game_id)
            if game is None:
                return {"error": f"Game {auth.game_id} not found."}

            state = GameState.model_validate(game.state)

            # Check if this player has already submitted
            existing = await repo.get_turn_action(
                auth.game_id, auth.player_id, state.turn
            )
            has_submitted = existing is not None

            # Calculate time remaining
            seconds_remaining: float | None = None
            if game.turn_started_at:
                now = datetime.now(UTC).replace(tzinfo=None)
                elapsed = (now - game.turn_started_at).total_seconds()
                seconds_remaining = max(0.0, TURN_TIMEOUT_SECONDS - elapsed)

            # Check all submissions
            all_actions = await repo.get_all_turn_actions(auth.game_id, state.turn)
            submitted_players = [ta.player_id for ta in all_actions]

            # If timeout has expired and not all submitted, try to resolve
            if (
                seconds_remaining is not None
                and seconds_remaining <= 0
                and len(submitted_players) < len(game.players)
            ):
                resolve_result = await check_and_resolve_turn(repo, auth.game_id)
                if resolve_result:
                    await session.commit()
                    # Re-fetch after resolution
                    game = await repo.get_game(auth.game_id)
                    if game is None:
                        return {"error": f"Game {auth.game_id} not found."}
                    state = GameState.model_validate(game.state)
                    return {
                        "game_id": auth.game_id,
                        "player": auth.player_id,
                        "turn": state.turn,
                        "status": game.status,
                        "waiting_for_you": True,
                        "has_submitted": False,
                        "turn_just_resolved": True,
                        "seconds_remaining": TURN_TIMEOUT_SECONDS,
                    }

        return {
            "game_id": auth.game_id,
            "player": auth.player_id,
            "turn": state.turn,
            "status": game.status,
            "waiting_for_you": not has_submitted,
            "has_submitted": has_submitted,
            "submitted_players": submitted_players,
            "total_players": len(game.players),
            "seconds_remaining": (
                round(seconds_remaining, 1) if seconds_remaining is not None else None
            ),
        }
