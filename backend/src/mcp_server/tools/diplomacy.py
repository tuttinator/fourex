"""
Diplomacy MCP tools: declare_war, get_diplomacy_state, send_message, get_messages.

Phases 1 and 2 of the diplomacy system — war declarations, treacherous-attack
events, the per-player discovered-players set, the public event feed, and
private bilateral messaging. Later phases add treaties and alliance mechanics.
"""

from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from ...auth import AuthError, authenticate
from ...database.connection import async_session_factory
from ...database.repository import GameRepository
from ...game.models import (
    MESSAGE_BODY_MAX_LENGTH,
    MESSAGES_PER_TURN_LIMIT,
    DeclareWarAction,
    GameState,
    SendMessageAction,
)
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
            "messages": [m.model_dump(mode="json") for m in redacted.messages],
        }

    @mcp.tool(
        name="send_message",
        description=(
            "Queue a private SEND_MESSAGE action addressed to a discovered "
            f"player. Body must be 1..{MESSAGE_BODY_MAX_LENGTH} chars. Up to "
            f"{MESSAGES_PER_TURN_LIMIT} messages per sender per turn. "
            "Include the returned ``action`` in your next submit_actions call."
        ),
        annotations=ToolAnnotations(
            title="Send Message",
            readOnlyHint=False,
            openWorldHint=False,
        ),
        meta={"tags": ["diplomacy", "action"]},
    )
    async def send_message(
        api_key: str,
        recipient: str,
        body: str,
    ) -> dict[str, Any]:
        """Queue a SEND_MESSAGE action for the current turn.

        Args:
            api_key: Your player API key.
            recipient: Discovered player to message.
            body: Message text (≤2000 characters).

        Returns:
            The action dict to include in your next submit_actions call,
            alongside the rest of your turn actions.
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

        action = SendMessageAction(recipient=recipient, body=body)
        return {
            "game_id": auth.game_id,
            "player": auth.player_id,
            "action": action.model_dump(mode="json"),
            "note": (
                "Include this action in your next submit_actions call to "
                "actually send the message."
            ),
        }

    @mcp.tool(
        name="get_messages",
        description=(
            "Return the private message history visible to the authenticated "
            "player: all messages you have sent or received, optionally filtered "
            "by counterparty and/or a lower-bound turn."
        ),
        annotations=ToolAnnotations(
            title="Get Messages",
            readOnlyHint=True,
            openWorldHint=False,
        ),
        meta={"tags": ["diplomacy", "query"]},
    )
    async def get_messages(
        api_key: str,
        counterparty: str | None = None,
        since_turn: int | None = None,
    ) -> dict[str, Any]:
        """Fetch your inbox + outbox, optionally filtered.

        Args:
            api_key: Your player API key.
            counterparty: If provided, only return messages between you and
                this player.
            since_turn: If provided, only return messages with
                ``turn_sent >= since_turn``.

        Returns:
            A list of ``Message`` dicts (sender, recipient, body, turn_sent,
            id) sorted ascending by id.
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

        messages = redacted.messages
        if counterparty is not None:
            messages = [
                m
                for m in messages
                if m.sender == counterparty or m.recipient == counterparty
            ]
        if since_turn is not None:
            messages = [m for m in messages if m.turn_sent >= since_turn]

        messages_sorted = sorted(messages, key=lambda m: m.id)

        return {
            "game_id": auth.game_id,
            "player": auth.player_id,
            "turn": state.turn,
            "messages": [m.model_dump(mode="json") for m in messages_sorted],
        }
