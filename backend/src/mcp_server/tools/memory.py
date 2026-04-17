"""
Agent memory MCP tools: write_scratchpad, read_scratchpad, and the
structured memory family (strategic goals, opponent models, turn notes).
"""

from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from ...auth import AuthError, authenticate
from ...database.connection import async_session_factory
from ...database.repository import GameRepository
from ...game.models import GameState

# Maximum scratchpad length, enforced on write.
SCRATCHPAD_MAX_CHARS = 4000

# Default lookback window for read_turn_notes.
DEFAULT_TURN_NOTES_LOOKBACK = 5


def register(mcp: FastMCP) -> None:
    """Register agent memory tools on the MCP server."""

    @mcp.tool(
        name="write_scratchpad",
        description=(
            "Write free-form text to your private scratchpad for the current "
            "turn. Use this to record observations, intentions, and evolving "
            "strategy. Writing to the same turn overwrites the previous entry. "
            "Hard-capped at 4,000 characters."
        ),
        annotations=ToolAnnotations(
            title="Write Scratchpad",
            readOnlyHint=False,
            openWorldHint=False,
        ),
        meta={"tags": ["memory"]},
    )
    async def write_scratchpad(
        api_key: str,
        text: str,
    ) -> dict[str, Any]:
        """Write to your scratchpad for the current turn.

        Args:
            api_key: Your player API key (received from create_game or join_game).
            text: Free-form text to store. Maximum 4,000 characters. Writing
                again on the same turn overwrites the previous entry.

        Returns:
            Confirmation with game_id, player, turn, and character count.
        """
        if len(text) > SCRATCHPAD_MAX_CHARS:
            return {
                "error": (
                    f"Scratchpad text exceeds the {SCRATCHPAD_MAX_CHARS}-character "
                    f"limit (got {len(text)} characters)."
                ),
            }

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

            await repo.upsert_agent_memory(
                game_id=auth.game_id,
                player_id=auth.player_id,
                turn_number=state.turn,
                scratchpad_text=text,
            )

            await session.commit()

        return {
            "game_id": auth.game_id,
            "player": auth.player_id,
            "turn": state.turn,
            "characters": len(text),
        }

    @mcp.tool(
        name="read_scratchpad",
        description=(
            "Read your private scratchpad. Returns the current turn's entry "
            "by default, or a specific past turn if turn_number is provided. "
            "Only your own scratchpad is accessible."
        ),
        annotations=ToolAnnotations(
            title="Read Scratchpad",
            readOnlyHint=True,
            openWorldHint=False,
        ),
        meta={"tags": ["memory"]},
    )
    async def read_scratchpad(
        api_key: str,
        turn_number: int | None = None,
    ) -> dict[str, Any]:
        """Read your scratchpad for the current or a past turn.

        Args:
            api_key: Your player API key.
            turn_number: Optional turn number to read. Defaults to the
                current turn.

        Returns:
            Scratchpad text, turn number, and character count — or an
            empty result if no entry exists for that turn.
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
            target_turn = turn_number if turn_number is not None else state.turn

            if target_turn < 0 or target_turn > state.turn:
                return {
                    "error": (
                        f"Invalid turn number {target_turn}. "
                        f"Current turn is {state.turn}."
                    ),
                }

            memory = await repo.get_agent_memory(
                auth.game_id, auth.player_id, target_turn
            )

        if memory is None:
            return {
                "game_id": auth.game_id,
                "player": auth.player_id,
                "turn": target_turn,
                "text": None,
                "characters": 0,
            }

        return {
            "game_id": auth.game_id,
            "player": auth.player_id,
            "turn": target_turn,
            "text": memory.scratchpad_text,
            "characters": len(memory.scratchpad_text),
        }

    # ------------------------------------------------------------------
    # Strategic goals
    # ------------------------------------------------------------------

    @mcp.tool(
        name="write_strategic_goals",
        description=(
            "Persist your strategic goals for the current turn. Goals are a list "
            "of objects (typically with fields like goal, priority, status, "
            "since_turn). The list replaces any goals previously written on this "
            "turn. Memory is scoped to this game only."
        ),
        annotations=ToolAnnotations(
            title="Write Strategic Goals",
            readOnlyHint=False,
            openWorldHint=False,
        ),
        meta={"tags": ["memory"]},
    )
    async def write_strategic_goals(
        api_key: str,
        goals: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Write the player's strategic goals for the current turn.

        Args:
            api_key: Your player API key.
            goals: A list of goal objects. The caller chooses the shape, but
                fields like {"goal", "priority", "status", "since_turn"} are
                recommended.

        Returns:
            Confirmation with game_id, player, turn and goal count.
        """
        if not isinstance(goals, list):
            return {"error": "goals must be a list of objects."}

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

            await repo.merge_agent_memory_structured(
                game_id=auth.game_id,
                player_id=auth.player_id,
                turn_number=state.turn,
                patch={"strategic_goals": goals},
            )
            await session.commit()

        return {
            "game_id": auth.game_id,
            "player": auth.player_id,
            "turn": state.turn,
            "goal_count": len(goals),
        }

    @mcp.tool(
        name="read_strategic_goals",
        description=(
            "Read your most recent strategic goals. Returns the goals written "
            "on the latest turn that had any (not necessarily the current turn). "
            "Only your own goals are accessible."
        ),
        annotations=ToolAnnotations(
            title="Read Strategic Goals",
            readOnlyHint=True,
            openWorldHint=False,
        ),
        meta={"tags": ["memory"]},
    )
    async def read_strategic_goals(api_key: str) -> dict[str, Any]:
        """Read the player's latest strategic goals across all turns.

        Args:
            api_key: Your player API key.

        Returns:
            The most recent non-empty goals list, the turn it was written on,
            and an empty list if no goals have been written.
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

            memories = await repo.get_player_agent_memories(
                auth.game_id, auth.player_id
            )

        latest_goals: list[dict[str, Any]] = []
        latest_turn: int | None = None
        for mem in reversed(memories):
            data = mem.structured_data or {}
            goals = data.get("strategic_goals")
            if goals:
                latest_goals = list(goals)
                latest_turn = mem.turn_number
                break

        return {
            "game_id": auth.game_id,
            "player": auth.player_id,
            "turn": latest_turn,
            "goals": latest_goals,
        }

    # ------------------------------------------------------------------
    # Opponent models
    # ------------------------------------------------------------------

    @mcp.tool(
        name="write_opponent_model",
        description=(
            "Record observations about a specific opponent for the current turn. "
            "Model is a free-form object (stance, unit count, threat level, last "
            "known positions, etc.). Overwrites any prior entry for that opponent "
            "on this turn. Other opponents' models are preserved."
        ),
        annotations=ToolAnnotations(
            title="Write Opponent Model",
            readOnlyHint=False,
            openWorldHint=False,
        ),
        meta={"tags": ["memory"]},
    )
    async def write_opponent_model(
        api_key: str,
        opponent_id: str,
        model: dict[str, Any],
    ) -> dict[str, Any]:
        """Persist a per-opponent observation for the current turn.

        Args:
            api_key: Your player API key.
            opponent_id: The opponent's player_id.
            model: Free-form dict of observations for that opponent.

        Returns:
            Confirmation with game_id, player, turn and opponent_id.
        """
        if not isinstance(model, dict):
            return {"error": "model must be an object."}
        if not opponent_id:
            return {"error": "opponent_id is required."}

        async with async_session_factory() as session:
            try:
                auth = await authenticate(session, api_key)
            except AuthError as e:
                return {"error": str(e)}

            if opponent_id == auth.player_id:
                return {"error": "Cannot record an opponent model about yourself."}

            repo = GameRepository(session)
            game = await repo.get_game(auth.game_id)
            if game is None:
                return {"error": f"Game {auth.game_id} not found."}

            if game.status == "ended":
                return {"error": "Game has ended."}

            state = GameState.model_validate(game.state)

            existing = await repo.get_agent_memory(
                auth.game_id, auth.player_id, state.turn
            )
            existing_models: dict[str, Any] = {}
            if existing and existing.structured_data:
                existing_models = dict(
                    existing.structured_data.get("opponent_models") or {}
                )
            existing_models[opponent_id] = model

            await repo.merge_agent_memory_structured(
                game_id=auth.game_id,
                player_id=auth.player_id,
                turn_number=state.turn,
                patch={"opponent_models": existing_models},
            )
            await session.commit()

        return {
            "game_id": auth.game_id,
            "player": auth.player_id,
            "turn": state.turn,
            "opponent_id": opponent_id,
        }

    @mcp.tool(
        name="read_opponent_models",
        description=(
            "Read your latest model for each opponent. For each opponent, the "
            "most recently written model across all turns is returned, along "
            "with the turn it was written on. Only your own memory is accessible."
        ),
        annotations=ToolAnnotations(
            title="Read Opponent Models",
            readOnlyHint=True,
            openWorldHint=False,
        ),
        meta={"tags": ["memory"]},
    )
    async def read_opponent_models(api_key: str) -> dict[str, Any]:
        """Return the latest model for every observed opponent.

        Args:
            api_key: Your player API key.

        Returns:
            A mapping of opponent_id -> {"model": ..., "turn": ...} for each
            opponent the player has ever recorded. Empty if none recorded.
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

            memories = await repo.get_player_agent_memories(
                auth.game_id, auth.player_id
            )

        latest: dict[str, dict[str, Any]] = {}
        for mem in memories:
            data = mem.structured_data or {}
            models = data.get("opponent_models") or {}
            for opponent_id, model in models.items():
                latest[opponent_id] = {"model": model, "turn": mem.turn_number}

        return {
            "game_id": auth.game_id,
            "player": auth.player_id,
            "opponents": latest,
        }

    # ------------------------------------------------------------------
    # Turn notes
    # ------------------------------------------------------------------

    @mcp.tool(
        name="write_turn_notes",
        description=(
            "Record freeform notes for the current turn. Overwrites any existing "
            "notes for this turn. Unlike the scratchpad, turn notes are designed "
            "to be read back across many turns with configurable lookback."
        ),
        annotations=ToolAnnotations(
            title="Write Turn Notes",
            readOnlyHint=False,
            openWorldHint=False,
        ),
        meta={"tags": ["memory"]},
    )
    async def write_turn_notes(
        api_key: str,
        notes: str,
    ) -> dict[str, Any]:
        """Write freeform notes for the current turn.

        Args:
            api_key: Your player API key.
            notes: Free-form string. Capped at 4,000 characters to match the
                scratchpad budget.

        Returns:
            Confirmation with game_id, player, turn and character count.
        """
        if not isinstance(notes, str):
            return {"error": "notes must be a string."}
        if len(notes) > SCRATCHPAD_MAX_CHARS:
            return {
                "error": (
                    f"Turn notes exceed the {SCRATCHPAD_MAX_CHARS}-character "
                    f"limit (got {len(notes)} characters)."
                ),
            }

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

            await repo.merge_agent_memory_structured(
                game_id=auth.game_id,
                player_id=auth.player_id,
                turn_number=state.turn,
                patch={"turn_notes": notes},
            )
            await session.commit()

        return {
            "game_id": auth.game_id,
            "player": auth.player_id,
            "turn": state.turn,
            "characters": len(notes),
        }

    @mcp.tool(
        name="read_turn_notes",
        description=(
            "Read your turn notes from recent turns, newest first. The lookback "
            "argument controls how many of the most recent notes to return "
            "(default 5). Only your own notes are accessible."
        ),
        annotations=ToolAnnotations(
            title="Read Turn Notes",
            readOnlyHint=True,
            openWorldHint=False,
        ),
        meta={"tags": ["memory"]},
    )
    async def read_turn_notes(
        api_key: str,
        lookback: int | None = None,
    ) -> dict[str, Any]:
        """Read recent turn notes in descending turn order.

        Args:
            api_key: Your player API key.
            lookback: Maximum number of entries to return. Defaults to 5.
                Must be a positive integer.

        Returns:
            A list of {turn_number, notes} entries, newest first.
        """
        if lookback is None:
            lookback = DEFAULT_TURN_NOTES_LOOKBACK
        if lookback <= 0:
            return {"error": "lookback must be a positive integer."}

        async with async_session_factory() as session:
            try:
                auth = await authenticate(session, api_key)
            except AuthError as e:
                return {"error": str(e)}

            repo = GameRepository(session)
            game = await repo.get_game(auth.game_id)
            if game is None:
                return {"error": f"Game {auth.game_id} not found."}

            memories = await repo.get_player_agent_memories(
                auth.game_id, auth.player_id
            )

        entries: list[dict[str, Any]] = []
        for mem in reversed(memories):
            data = mem.structured_data or {}
            notes = data.get("turn_notes")
            if notes is None:
                continue
            entries.append({"turn_number": mem.turn_number, "notes": notes})
            if len(entries) >= lookback:
                break

        return {
            "game_id": auth.game_id,
            "player": auth.player_id,
            "lookback": lookback,
            "entries": entries,
        }
