"""
Diplomacy MCP tools: declare_war, get_diplomacy_state.

Phase 1 of the diplomacy system — covers war declarations, treacherous-attack
events, the per-player discovered-players set, and the public event feed.
Later phases add messaging, treaties, and alliance mechanics.
"""

from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from ...auth import AuthError, authenticate
from ...database.connection import async_session_factory
from ...database.repository import GameRepository
from ...game.models import DeclareWarAction, GameState
from ...game.rules import redact_state


def _serialise_diplomacy(state: GameState, viewer: str) -> list[dict[str, str]]:
    """Serialise the viewer-visible diplomacy dict into a list of records."""
    return [
        {"player_a": key[0], "player_b": key[1], "state": value.value}
        for key, value in state.diplomacy.items()
    ]


def register(mcp: FastMCP) -> None:
    """Register diplomacy tools on the MCP server."""

    @mcp.tool(
        name="declare_war",
        description=(
            "Declare war on another player. The target must be a player you "
            "have previously discovered (seen at least one of their units or "
            "cities). War takes effect immediately — you can attack on the "
            "same turn you declare."
        ),
        annotations=ToolAnnotations(
            title="Declare War",
            readOnlyHint=False,
            openWorldHint=False,
        ),
        meta={"tags": ["diplomacy", "action"]},
    )
    async def declare_war(
        api_key: str,
        target_player: str,
    ) -> dict[str, Any]:
        """Queue a DECLARE_WAR action for the current turn.

        This tool adds a DeclareWarAction to the actions you will submit for
        this turn. To actually apply it, include the returned ``action`` in
        your next ``submit_actions`` call alongside any other actions.

        Args:
            api_key: Your player API key.
            target_player: The discovered player to declare war on.

        Returns:
            The action dict to include in your next submit_actions call,
            plus a validation result against current state.
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

        action = DeclareWarAction(target_player=target_player)
        return {
            "game_id": auth.game_id,
            "player": auth.player_id,
            "action": action.model_dump(mode="json"),
            "note": (
                "Include this action in your next submit_actions call to "
                "actually declare war."
            ),
        }

    @mcp.tool(
        name="get_diplomacy_state",
        description=(
            "Return the current diplomatic view for the authenticated player: "
            "discovered players, pair-wise relations (peace/alliance/war), and "
            "the public diplomatic-events feed, all filtered per visibility rules."
        ),
        annotations=ToolAnnotations(
            title="Get Diplomacy State",
            readOnlyHint=True,
            openWorldHint=False,
        ),
        meta={"tags": ["diplomacy", "query"]},
    )
    async def get_diplomacy_state(api_key: str) -> dict[str, Any]:
        """Fetch the redacted diplomatic slice of game state for the caller.

        Args:
            api_key: Your player API key.

        Returns:
            ``discovered`` (players you have ever seen), ``relations`` (each
            pairwise diplomatic state you can observe), and ``events`` (the
            public event feed filtered to entries you can see).
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
            "discovered": redacted.discovered.get(auth.player_id, []),
            "relations": _serialise_diplomacy(redacted, auth.player_id),
            "events": [e.model_dump(mode="json") for e in redacted.diplomatic_events],
        }
