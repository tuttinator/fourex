"""
Game lifecycle MCP tools: create_game, join_game, get_game_info.
"""

import random
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from ...auth import create_player_key
from ...database.connection import async_session_factory
from ...database.repository import GameRepository
from ...game.models import GameState
from ...game.rules import (
    STARTING_STOCKPILE,
    calculate_scores,
    generate_map,
    place_starting_units,
    update_discovery,
)


def register(mcp: FastMCP) -> None:
    """Register game lifecycle tools on the MCP server."""

    @mcp.tool(
        name="create_game",
        description=(
            "Create a new 4X game. Returns the game ID and an API key for each "
            "player slot. Distribute keys to players — each key authenticates "
            "exactly one player for all subsequent tool calls."
        ),
        annotations=ToolAnnotations(
            title="Create Game",
            readOnlyHint=False,
            openWorldHint=False,
        ),
        meta={"tags": ["lifecycle", "setup"]},
    )
    async def create_game(
        players: list[str],
        seed: int = 42,
        max_turns: int = 100,
        map_width: int = 20,
        map_height: int = 20,
        victory_conditions: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a new game with the given player names.

        Args:
            players: List of player names (2–8 players).
            seed: RNG seed for deterministic map generation.
            max_turns: Maximum number of turns before score victory.
            map_width: Map width in tiles.
            map_height: Map height in tiles.
            victory_conditions: Enabled victory conditions. Defaults to all four:
                ["domination", "economic", "elimination", "score"].

        Returns:
            game_id and a mapping of player name → API key.
        """
        if len(players) < 2 or len(players) > 8:
            return {"error": "Games require 2–8 players."}

        if len(players) != len(set(players)):
            return {"error": "Player names must be unique."}

        valid_conditions = {"domination", "economic", "elimination", "score"}
        if victory_conditions is not None:
            invalid = set(victory_conditions) - valid_conditions
            if invalid:
                return {
                    "error": f"Invalid victory conditions: {invalid}. Valid: {valid_conditions}"
                }
        else:
            victory_conditions = list(valid_conditions)

        async with async_session_factory() as session:
            repo = GameRepository(session)

            # Generate a short game ID
            import secrets

            game_id = f"game_{secrets.token_hex(4)}"

            # Check uniqueness (extremely unlikely collision)
            existing = await repo.get_game(game_id)
            if existing:
                game_id = f"game_{secrets.token_hex(4)}"

            # Generate map
            tiles = generate_map(map_width, map_height, seed)

            # Build initial game state
            state = GameState(
                rng_state=seed,
                tiles=tiles,
                players=list(players),
                max_turns=max_turns,
                map_width=map_width,
                map_height=map_height,
                victory_conditions=victory_conditions,
            )

            # Initialise stockpiles
            for player in players:
                state.stockpiles[player] = STARTING_STOCKPILE.model_copy()

            # Place starting worker + scout per player
            rng = random.Random(seed)
            for player in players:
                place_starting_units(state, player, rng)

            # Seed discovered-players sets from starting visibility.
            update_discovery(state)

            # Persist game
            await repo.create_game(
                game_id=game_id,
                players=list(players),
                seed=seed,
                max_turns=max_turns,
                map_width=map_width,
                map_height=map_height,
            )
            await repo.update_game_state(game_id, state)
            await repo.create_game_snapshot(
                game_id=game_id,
                turn_number=0,
                state=state,
                snapshot_type="initial",
            )

            # Generate API keys for each player
            api_keys: dict[str, str] = {}
            for player in players:
                key = await create_player_key(session, game_id, player)
                api_keys[player] = key

            await session.commit()

        return {
            "game_id": game_id,
            "players": list(players),
            "api_keys": api_keys,
            "seed": seed,
            "max_turns": max_turns,
            "map_size": {"width": map_width, "height": map_height},
            "victory_conditions": victory_conditions,
        }

    @mcp.tool(
        name="join_game",
        description=(
            "Join an existing game as a new player. Returns an API key for "
            "the assigned player slot. The game must be in 'created' status "
            "and must have room for another player."
        ),
        annotations=ToolAnnotations(
            title="Join Game",
            readOnlyHint=False,
            openWorldHint=False,
        ),
        meta={"tags": ["lifecycle", "setup"]},
    )
    async def join_game(
        game_id: str,
        player_name: str,
    ) -> dict[str, Any]:
        """Join an existing game.

        Args:
            game_id: The game to join.
            player_name: Display name for the new player.

        Returns:
            The assigned player name and API key.
        """
        async with async_session_factory() as session:
            repo = GameRepository(session)

            game = await repo.get_game(game_id)
            if game is None:
                return {"error": f"Game {game_id} not found."}

            if game.status != "created":
                return {
                    "error": f"Game {game_id} is '{game.status}' — can only join games in 'created' status."
                }

            if player_name in game.players:
                return {"error": f"Player '{player_name}' is already in the game."}

            if len(game.players) >= 8:
                return {"error": "Game is full (max 8 players)."}

            # Add player to the game's player list
            updated_players = list(game.players) + [player_name]
            game.players = updated_players

            # Update game state to include the new player
            state = GameState.model_validate(game.state)
            state.players.append(player_name)
            state.stockpiles[player_name] = STARTING_STOCKPILE.model_copy()

            # Ensure next_unit_id doesn't collide with existing units
            if state.units:
                state.next_unit_id = max(
                    state.next_unit_id, max(state.units.keys()) + 1
                )

            # Place a starting worker + scout for the new player
            rng = random.Random(game.seed + len(updated_players))
            place_starting_units(state, player_name, rng)

            # Refresh discovered-players sets so the new player and neighbours
            # start with any mutually-visible entries already in place.
            update_discovery(state)

            await repo.update_game_state(game_id, state)

            # Generate API key
            key = await create_player_key(session, game_id, player_name)

            await session.commit()

        return {
            "game_id": game_id,
            "player": player_name,
            "api_key": key,
        }

    @mcp.tool(
        name="get_game_info",
        description=(
            "Get metadata about a game: players, current turn, status, "
            "victory info. Does not require authentication."
        ),
        annotations=ToolAnnotations(
            title="Get Game Info",
            readOnlyHint=True,
            openWorldHint=False,
        ),
        meta={"tags": ["lifecycle", "query"]},
    )
    async def get_game_info(
        game_id: str,
    ) -> dict[str, Any]:
        """Get game metadata.

        Args:
            game_id: The game to query.

        Returns:
            Game metadata including players, turn, status, and victory info.
        """
        async with async_session_factory() as session:
            repo = GameRepository(session)

            game = await repo.get_game(game_id)
            if game is None:
                return {"error": f"Game {game_id} not found."}

        info: dict[str, Any] = {
            "game_id": game.id,
            "players": game.players,
            "turn": game.turn,
            "max_turns": game.max_turns,
            "status": game.status,
            "winner": game.winner,
            "victory_type": game.victory_type,
            "created_at": game.created_at.isoformat() if game.created_at else None,
        }

        # Include victory conditions and elimination status from game state
        if game.state:
            try:
                state = GameState.model_validate(game.state)
                info["victory_conditions"] = state.victory_conditions
                info["eliminated_players"] = state.eliminated_players
                info["scores"] = calculate_scores(state)
            except Exception:
                pass

        return info
