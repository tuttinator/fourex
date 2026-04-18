"""
Diplomacy MCP tools: declare_war, get_diplomacy_state, send_message,
get_messages, propose_treaty, respond_to_treaty, withdraw_treaty, cancel_treaty.

Phases 1, 2, and 3 of the diplomacy system — war declarations, treacherous-
attack events, the per-player discovered-players set, the public event feed,
private bilateral messaging, and the treaty lifecycle (peace + free-text
clauses). Later phases add resource and alliance clauses.
"""

from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from ...auth import AuthError, authenticate
from ...database.connection import async_session_factory
from ...database.repository import GameRepository
from ...game.models import (
    FREE_TEXT_CLAUSE_MAX_LENGTH,
    MESSAGE_BODY_MAX_LENGTH,
    MESSAGES_PER_TURN_LIMIT,
    PEACE_CLAUSE_MAX_DURATION,
    TREATY_PROPOSAL_EXPIRY_TURNS,
    CancelTreatyAction,
    DeclareWarAction,
    FreeTextClause,
    GameState,
    PeaceClause,
    ProposeTreatyAction,
    RecurringTributeClause,
    ResourceBag,
    ResourceSwapClause,
    RespondToTreatyAction,
    SendMessageAction,
    WithdrawTreatyAction,
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
            "pending_proposals": [
                p.model_dump(mode="json") for p in redacted.pending_proposals
            ],
            "active_treaties": [
                t.model_dump(mode="json") for t in redacted.active_treaties
            ],
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

    @mcp.tool(
        name="propose_treaty",
        description=(
            "Queue a PROPOSE_TREATY action bundling one or more clauses. "
            "Supported clause types: peace (duration_turns, "
            f"1..{PEACE_CLAUSE_MAX_DURATION}); free_text (text up to "
            f"{FREE_TEXT_CLAUSE_MAX_LENGTH} chars); resource_swap "
            "(proposer_gives + recipient_gives resource bags, swapped "
            "atomically at ratification); recurring_tribute (payer, amount, "
            "duration_turns — per-turn transfer from payer to the other "
            "party). Between allies, swap/tribute clauses are pre-validated "
            "for fundability at proposal time. Proposals auto-expire after "
            f"{TREATY_PROPOSAL_EXPIRY_TURNS} turns if unanswered. Include the "
            "returned action in your next submit_actions call."
        ),
        annotations=ToolAnnotations(
            title="Propose Treaty",
            readOnlyHint=False,
            openWorldHint=False,
        ),
        meta={"tags": ["diplomacy", "action", "treaty"]},
    )
    async def propose_treaty(
        api_key: str,
        recipient: str,
        clauses: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Queue a PROPOSE_TREATY action.

        Args:
            api_key: Your player API key.
            recipient: Discovered player to propose to.
            clauses: A non-empty list of clause dicts. Each must include a
                ``clause_type`` field:

                - ``peace`` with ``duration_turns`` (int)
                - ``free_text`` with ``text`` (string)
                - ``resource_swap`` with ``proposer_gives`` and
                  ``recipient_gives`` resource-bag dicts (keys: ``food``,
                  ``wood``, ``ore``, ``crystal``; missing fields default to 0)
                - ``recurring_tribute`` with ``payer`` (player id, must be
                  one of the two parties), ``amount`` resource-bag, and
                  ``duration_turns`` (int)

        Returns:
            The action dict to submit.
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

        def _bag(raw: Any) -> ResourceBag:
            data = raw or {}
            if not isinstance(data, dict):
                raise ValueError("resource amount must be an object")
            return ResourceBag(
                food=int(data.get("food", 0) or 0),
                wood=int(data.get("wood", 0) or 0),
                ore=int(data.get("ore", 0) or 0),
                crystal=int(data.get("crystal", 0) or 0),
            )

        parsed_clauses: list = []
        for raw in clauses:
            ctype = raw.get("clause_type")
            try:
                if ctype == "peace":
                    duration = int(raw.get("duration_turns", 0))
                    parsed_clauses.append(
                        PeaceClause(
                            duration_turns=duration,
                            turns_remaining=duration,
                        )
                    )
                elif ctype == "free_text":
                    parsed_clauses.append(FreeTextClause(text=str(raw.get("text", ""))))
                elif ctype == "resource_swap":
                    parsed_clauses.append(
                        ResourceSwapClause(
                            proposer_gives=_bag(raw.get("proposer_gives")),
                            recipient_gives=_bag(raw.get("recipient_gives")),
                        )
                    )
                elif ctype == "recurring_tribute":
                    payer = raw.get("payer")
                    if not isinstance(payer, str) or not payer:
                        return {
                            "error": "recurring_tribute clause requires payer string"
                        }
                    duration = int(raw.get("duration_turns", 0))
                    parsed_clauses.append(
                        RecurringTributeClause(
                            payer=payer,
                            amount=_bag(raw.get("amount")),
                            duration_turns=duration,
                            turns_remaining=duration,
                        )
                    )
                else:
                    return {"error": f"Unknown clause_type: {ctype}"}
            except (TypeError, ValueError) as exc:
                return {"error": f"Invalid {ctype} clause: {exc}"}

        action = ProposeTreatyAction(recipient=recipient, clauses=parsed_clauses)
        return {
            "game_id": auth.game_id,
            "player": auth.player_id,
            "action": action.model_dump(mode="json"),
            "note": (
                "Include this action in your next submit_actions call to "
                "actually send the proposal."
            ),
        }

    @mcp.tool(
        name="respond_to_treaty",
        description=(
            "Queue a RESPOND_TO_TREATY action accepting or declining a "
            "pending proposal addressed to you. Include the returned action "
            "in your next submit_actions call."
        ),
        annotations=ToolAnnotations(
            title="Respond To Treaty",
            readOnlyHint=False,
            openWorldHint=False,
        ),
        meta={"tags": ["diplomacy", "action", "treaty"]},
    )
    async def respond_to_treaty(
        api_key: str,
        proposal_id: int,
        accept: bool,
    ) -> dict[str, Any]:
        """Queue a RESPOND_TO_TREATY action.

        Args:
            api_key: Your player API key.
            proposal_id: The pending proposal id to respond to.
            accept: True to accept and ratify; False to decline.

        Returns:
            The action dict to submit.
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

        action = RespondToTreatyAction(proposal_id=proposal_id, accept=accept)
        return {
            "game_id": auth.game_id,
            "player": auth.player_id,
            "action": action.model_dump(mode="json"),
            "note": (
                "Include this action in your next submit_actions call to "
                "actually respond."
            ),
        }

    @mcp.tool(
        name="withdraw_treaty",
        description=(
            "Queue a WITHDRAW_TREATY action cancelling a pending proposal "
            "you previously made (before a response). Include the returned "
            "action in your next submit_actions call."
        ),
        annotations=ToolAnnotations(
            title="Withdraw Treaty",
            readOnlyHint=False,
            openWorldHint=False,
        ),
        meta={"tags": ["diplomacy", "action", "treaty"]},
    )
    async def withdraw_treaty(
        api_key: str,
        proposal_id: int,
    ) -> dict[str, Any]:
        """Queue a WITHDRAW_TREATY action.

        Args:
            api_key: Your player API key.
            proposal_id: The proposal id to withdraw.

        Returns:
            The action dict to submit.
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

        action = WithdrawTreatyAction(proposal_id=proposal_id)
        return {
            "game_id": auth.game_id,
            "player": auth.player_id,
            "action": action.model_dump(mode="json"),
            "note": (
                "Include this action in your next submit_actions call to "
                "actually withdraw."
            ),
        }

    @mcp.tool(
        name="cancel_treaty",
        description=(
            "Queue a CANCEL_TREATY action unilaterally ending an active "
            "treaty you are a party to. If the treaty has active obligations "
            "(e.g. an unexpired peace clause), cancellation is a VIOLATION; "
            "otherwise a routine cancellation. Include the returned action "
            "in your next submit_actions call."
        ),
        annotations=ToolAnnotations(
            title="Cancel Treaty",
            readOnlyHint=False,
            openWorldHint=False,
        ),
        meta={"tags": ["diplomacy", "action", "treaty"]},
    )
    async def cancel_treaty(
        api_key: str,
        treaty_id: int,
    ) -> dict[str, Any]:
        """Queue a CANCEL_TREATY action.

        Args:
            api_key: Your player API key.
            treaty_id: The active treaty id to cancel.

        Returns:
            The action dict to submit.
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

        action = CancelTreatyAction(treaty_id=treaty_id)
        return {
            "game_id": auth.game_id,
            "player": auth.player_id,
            "action": action.model_dump(mode="json"),
            "note": (
                "Include this action in your next submit_actions call to "
                "actually cancel."
            ),
        }
