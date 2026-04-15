"""
Agent memory MCP tools: write_scratchpad, read_scratchpad.
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
