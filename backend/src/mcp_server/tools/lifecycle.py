"""
Game lifecycle MCP tools: create_game, join_game, get_game_info.
"""

import random
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from ...api.persistent_game_controller import PersistentGameController
from ...auth import AuthError, authenticate, create_player_key
from ...database.connection import async_session_factory
from ...database.repository import GameRepository
from ...game.models import GameState
from ...game.rules import (
    STARTING_STOCKPILE,
    calculate_scores,
    generate_map,
    place_starting_units,
    seed_research,
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
        map_template: str = "random",
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
            map_template: Parametric map template name (Phase 2). One of
                ``random``, ``continent``, ``islands``, ``river``,
                ``lakes``, ``archipelago``. Defaults to ``random`` for
                the legacy noise generator.

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

            # Generate map (Phase 2: registry-driven dispatch). Phase 4
            # adds the ``saved:<id>`` namespace for admin-authored maps;
            # the lobby's ``map_width`` / ``map_height`` are overridden
            # with the saved-map dimensions to match the lobby flow.
            from ...api.persistent_game_controller import (
                _saved_map_id_from_template,
                _saved_map_spawn_zones,
                _saved_map_to_tiles,
                _select_saved_spawn_subset,
            )

            saved_map_id = _saved_map_id_from_template(map_template)
            try:
                if saved_map_id is not None:
                    saved_map = await repo.get_saved_map(saved_map_id)
                    if saved_map is None:
                        return {"error": f"Saved map {saved_map_id} not found"}
                    tiles = _saved_map_to_tiles(saved_map)
                    zones = _saved_map_spawn_zones(saved_map)
                    spawn_zones = _select_saved_spawn_subset(zones, len(players), seed)
                    map_width = saved_map.width
                    map_height = saved_map.height
                else:
                    tiles, spawn_zones = generate_map(
                        map_template,
                        map_width,
                        map_height,
                        seed,
                        player_count=len(players),
                    )
            except ValueError as exc:
                return {"error": str(exc)}

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
            seed_research(state, list(players))

            # Place starting worker + scout per player
            rng = random.Random(seed)
            for idx, player in enumerate(players):
                zone = spawn_zones[idx] if idx < len(spawn_zones) else None
                place_starting_units(state, player, rng, spawn_zone=zone)

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
                map_template=map_template,
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

            # Phase 2: persist a ``lobby_slots`` array reflecting the
            # ``created``-status roster so /games/{id} surfaces a
            # consistent slot view across MCP- and frontend-born games.
            controller = PersistentGameController(session)
            from ...api.lobby_slots import derive_slots_from_players

            initial_slots = derive_slots_from_players(list(players), len(players))
            await controller.repo.update_lobby_slots(game_id, initial_slots)
            for player in players:
                await controller.link_slot_api_key(game_id, player)

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
            "Join an existing game as a new player. Accepts both legacy "
            "MCP-created games ('created' status) and lobbies created via "
            "the human frontend ('waiting' status). Returns an API key for "
            "the assigned player slot."
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

        Delegates roster mutation, starting-unit placement, and the
        ``lobby.player_joined`` WebSocket broadcast to
        ``PersistentGameController.join_game`` so the MCP and REST front
        doors traverse one code path. Per Phase 4.5, this also lets MCP
        agents join lobbies created through the human frontend (status
        ``waiting``) — previously the tool hard-coded ``created``.

        Args:
            game_id: The game to join.
            player_name: Display name for the new player.

        Returns:
            The assigned player name and API key.
        """
        async with async_session_factory() as session:
            controller = PersistentGameController(session)
            try:
                await controller.join_game(game_id, player_name)
            except ValueError as exc:
                return {"error": str(exc)}

            # Mint an API key for the new seat. ``user_identity_id`` is
            # left null — MCP callers have no Auth.js JWT to attribute
            # this key to, which is how MCP-origin keys are distinguished
            # from human-origin keys.
            key = await create_player_key(session, game_id, player_name)
            await controller.link_slot_api_key(game_id, player_name)
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

    @mcp.tool(
        name="whoami",
        description=(
            "Resolve which game and player slot a given API key controls. "
            "An agent handed only a key + game URL can call this to discover "
            "its own player_id without being told out-of-band."
        ),
        annotations=ToolAnnotations(
            title="Who Am I",
            readOnlyHint=True,
            openWorldHint=False,
        ),
        meta={"tags": ["lifecycle", "query"]},
    )
    async def whoami(api_key: str) -> dict[str, Any]:
        """Identify the player + game that ``api_key`` belongs to.

        Args:
            api_key: A per-game API key issued by ``create_game`` /
                ``join_game`` / the lobby UI.

        Returns:
            ``{game_id, player_id, slot_index}`` where ``slot_index`` is
            the player's position in the game's roster (matches the
            frontend's index-driven colour assignment). Returns
            ``{error: ...}`` if the key is missing, invalid, or expired.
        """
        async with async_session_factory() as session:
            try:
                auth = await authenticate(session, api_key)
            except AuthError as exc:
                return {"error": str(exc)}

            repo = GameRepository(session)
            game = await repo.get_game(auth.game_id)
            if game is None:
                return {"error": f"Game {auth.game_id} not found."}

            try:
                slot_index = game.players.index(auth.player_id)
            except ValueError:
                slot_index = None

        return {
            "game_id": auth.game_id,
            "player_id": auth.player_id,
            "slot_index": slot_index,
        }
