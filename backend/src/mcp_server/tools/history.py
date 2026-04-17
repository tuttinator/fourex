"""
Turn history and state snapshot MCP tools: get_turn_history, get_turn_snapshot.
"""

from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from ...auth import AuthError, authenticate
from ...database.connection import async_session_factory
from ...database.repository import GameRepository
from ...game.models import GameState


def register(mcp: FastMCP) -> None:
    """Register turn history and snapshot tools on the MCP server."""

    @mcp.tool(
        name="get_turn_history",
        description=(
            "Get a summary of the actions you submitted on past turns. "
            "Returns a list of entries, each with the turn number and the "
            "actions you submitted. Only your own actions are visible."
        ),
        annotations=ToolAnnotations(
            title="Get Turn History",
            readOnlyHint=True,
            openWorldHint=False,
        ),
        meta={"tags": ["history", "query"]},
    )
    async def get_turn_history(api_key: str) -> dict[str, Any]:
        """Get your action history across all past turns.

        Args:
            api_key: Your player API key (received from create_game or join_game).

        Returns:
            List of {turn_number, actions} entries for every turn where you
            submitted actions, ordered by turn number.
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

            turn_actions = await repo.get_player_turn_actions(
                auth.game_id, auth.player_id
            )

        history = [
            {
                "turn_number": ta.turn_number,
                "actions": ta.actions_json if ta.actions_json else [],
            }
            for ta in turn_actions
        ]

        return {
            "game_id": auth.game_id,
            "player": auth.player_id,
            "total_turns": len(history),
            "history": history,
        }

    @mcp.tool(
        name="get_turn_snapshot",
        description=(
            "Get the fog-of-war-redacted game state snapshot for a specific "
            "past turn. Snapshots are saved automatically when a turn resolves. "
            "Only your own view is available — you cannot see what other players saw."
        ),
        annotations=ToolAnnotations(
            title="Get Turn Snapshot",
            readOnlyHint=True,
            openWorldHint=False,
        ),
        meta={"tags": ["history", "query"]},
    )
    async def get_turn_snapshot(
        api_key: str,
        turn_number: int,
    ) -> dict[str, Any]:
        """Get your fog-of-war-redacted game state for a past turn.

        Args:
            api_key: Your player API key.
            turn_number: The turn number to retrieve. Must be a turn that
                has already resolved (i.e. less than the current turn).

        Returns:
            The fog-of-war-redacted game state as it appeared to you at the
            end of the specified turn, or an error if the turn hasn't happened.
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

            if turn_number < 0:
                return {
                    "error": (
                        f"Invalid turn number {turn_number}. "
                        "Turn number must be non-negative."
                    ),
                }

            if turn_number >= state.turn:
                return {
                    "error": (
                        f"Turn {turn_number} has not resolved yet. "
                        f"Current turn is {state.turn}. "
                        "Snapshots are only available for completed turns."
                    ),
                }

            snapshot = await repo.get_turn_snapshot(
                auth.game_id, auth.player_id, turn_number
            )

        if snapshot is None:
            return {
                "error": (
                    f"No snapshot found for turn {turn_number}. "
                    "This may happen if the turn resolved before snapshots "
                    "were implemented."
                ),
            }

        return {
            "game_id": auth.game_id,
            "player": auth.player_id,
            "turn_number": turn_number,
            "state": snapshot.state_json,
        }
