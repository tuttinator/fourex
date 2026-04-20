"""
Persistent game controller using database storage.
"""

import random

from sqlalchemy.ext.asyncio import AsyncSession

from ..database.models import Game as DBGame
from ..database.repository import GameRepository
from ..game.models import (
    Action,
    GameState,
    PlayerId,
    PromptLog,
)
from ..game.rules import (
    STARTING_STOCKPILE,
    generate_map,
    place_starting_units,
    update_discovery,
)
from .turn_resolution import check_and_resolve_turn
from .websocket import (
    broadcast_lobby_player_joined,
    broadcast_lobby_player_left,
    broadcast_lobby_started,
    broadcast_turn_submitted,
)


class PersistentGameController:
    """Manages multiple game instances with database persistence."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = GameRepository(session)

        # In-memory cache of authoritative GameState, keyed by game_id.
        # Turn submissions are no longer held in memory — they live in the
        # ``turn_actions`` table and are consulted by
        # ``turn_resolution.check_and_resolve_turn``.
        self._game_cache: dict[str, GameState] = {}

    async def create_lobby(
        self,
        game_id: str,
        player_slots: int,
        map_width: int,
        map_height: int,
        seed: int,
        creator: str,
    ) -> None:
        """Create a game lobby in waiting status. Map is generated but no units are placed."""
        if player_slots < 2 or player_slots > 8:
            raise ValueError("Games require 2-8 player slots")

        existing_game = await self.repo.get_game(game_id)
        if existing_game:
            raise ValueError(f"Game {game_id} already exists")

        # Generate map at creation time
        tiles = generate_map(map_width, map_height, seed)

        # Create game state with no players yet (they join via /join)
        state = GameState(
            rng_state=seed,
            tiles=tiles,
            players=[],
            map_width=map_width,
            map_height=map_height,
            max_turns=100,
        )

        # Save to database with waiting status
        await self.repo.create_game(
            game_id=game_id,
            players=[],
            seed=seed,
            map_width=map_width,
            map_height=map_height,
            max_turns=100,
            player_slots=player_slots,
            creator=creator,
            status="waiting",
        )

        # Update game state in database
        await self.repo.update_game_state(game_id, state)

        # Cache the game state
        self._game_cache[game_id] = state

    async def join_game(self, game_id: str, player_id: str) -> None:
        """A player joins a joinable game.

        Accepts both ``waiting`` lobbies (created via the frontend's
        ``create_lobby`` path) and ``created`` games (the legacy MCP
        ``create_game`` path, where starting units were placed for every
        initial player at creation time). Phase 4.5 unifies the two front
        doors: the MCP ``join_game`` tool now delegates here so roster
        mutation, starting-unit placement for ``created`` games, and the
        ``lobby.player_joined`` broadcast all share one implementation.

        ``waiting`` games: only the roster changes — unit placement is
        deferred to ``start_game`` so the creator can finalise the slate
        before play begins.

        ``created`` games: legacy MCP semantics — the new player gets
        stockpiles and a worker+scout pair seeded immediately, since the
        game has no separate "start" transition.
        """
        db_game = await self.repo.get_game(game_id)
        if not db_game:
            raise ValueError(f"Game {game_id} not found")

        if db_game.status not in ("waiting", "created"):
            raise ValueError(
                f"Game {game_id} is '{db_game.status}' — only 'waiting' or "
                f"'created' games can be joined"
            )

        players = list(db_game.players)
        if player_id in players:
            raise ValueError(f"Player {player_id} is already in the game")

        # Legacy MCP-created games don't set a meaningful ``player_slots``
        # (the repo default is 2) and instead cap at the engine-wide
        # 8-player maximum. Waiting lobbies enforce the creator's chosen
        # slate size.
        max_slots = db_game.player_slots if db_game.status == "waiting" else 8
        if len(players) >= max_slots:
            raise ValueError(f"Game {game_id} is full ({max_slots} slots)")

        players.append(player_id)
        await self.repo.update_game_players(game_id, players)

        if db_game.status == "created":
            state = await self.get_game_state(game_id)
            if state is None:
                raise ValueError(f"Game state for {game_id} not found")

            state.players = list(players)
            state.stockpiles[player_id] = STARTING_STOCKPILE.model_copy()

            # Avoid colliding with pre-placed unit ids from the original
            # create_game roster.
            if state.units:
                state.next_unit_id = max(
                    state.next_unit_id, max(state.units.keys()) + 1
                )

            rng = random.Random(db_game.seed + len(players))
            place_starting_units(state, player_id, rng)
            update_discovery(state)

            await self.repo.update_game_state(game_id, state)
            self._game_cache[game_id] = state
        else:
            # Update cached state for waiting lobbies (no state mutation
            # beyond the roster).
            if game_id in self._game_cache:
                self._game_cache[game_id].players = players

        await broadcast_lobby_player_joined(game_id, player_id, players)

    async def leave_game(self, game_id: str, player_id: str) -> None:
        """A player leaves a waiting game."""
        db_game = await self.repo.get_game(game_id)
        if not db_game:
            raise ValueError(f"Game {game_id} not found")

        if db_game.status != "waiting":
            raise ValueError(f"Game {game_id} is not in waiting status")

        players = list(db_game.players)
        if player_id not in players:
            raise ValueError(f"Player {player_id} is not in the game")

        players.remove(player_id)
        await self.repo.update_game_players(game_id, players)

        # Update cached state if present
        if game_id in self._game_cache:
            self._game_cache[game_id].players = players

        await broadcast_lobby_player_left(game_id, player_id, players)

    async def start_game(self, game_id: str, creator: str) -> None:
        """Creator starts a waiting game. Validates slots are full, places units, transitions to active."""
        db_game = await self.repo.get_game(game_id)
        if not db_game:
            raise ValueError(f"Game {game_id} not found")

        if db_game.status != "waiting":
            raise ValueError(f"Game {game_id} is not in waiting status")

        if db_game.creator != creator:
            raise ValueError("Only the game creator can start the game")

        players = list(db_game.players)
        if len(players) != db_game.player_slots:
            raise ValueError(
                f"All {db_game.player_slots} slots must be filled before starting "
                f"(currently {len(players)})"
            )

        # Load the game state (map was generated at lobby creation)
        state = await self.get_game_state(game_id)
        if not state:
            raise ValueError(f"Game state for {game_id} not found")

        # Lobbies are created with an empty roster in the state snapshot;
        # the authoritative roster lives on the DB row and is only synced
        # into state.players here, at start.
        state.players = list(players)

        # Initialize player stockpiles
        for player in players:
            state.stockpiles[player] = STARTING_STOCKPILE.model_copy()

        # Place starting units
        self._place_starting_units(state, players, db_game.seed)

        # Seed discovered-players sets from starting visibility.
        update_discovery(state)

        # Transition to active
        await self.repo.update_game_status(game_id, "active")
        await self.repo.update_game_state(game_id, state)

        # Cache
        self._game_cache[game_id] = state

        # Create initial snapshot
        await self.repo.create_game_snapshot(
            game_id=game_id, turn_number=0, state=state, snapshot_type="initial"
        )

        # Notify every subscribed client that the lobby has gone live.
        await broadcast_lobby_started(game_id)

    @staticmethod
    def _place_starting_units(
        state: GameState, players: list[PlayerId], seed: int
    ) -> None:
        """Place a starting worker + scout per player on suitable terrain."""
        rng = random.Random(seed)
        for player in players:
            place_starting_units(state, player, rng)

    async def create_game(
        self, game_id: str, players: list[PlayerId], seed: int = 42
    ) -> None:
        """Create a new game instance with database persistence (legacy: immediate start)."""
        if len(players) < 2 or len(players) > 8:
            raise ValueError("Games require 2-8 players")

        # Check if game already exists
        existing_game = await self.repo.get_game(game_id)
        if existing_game:
            raise ValueError(f"Game {game_id} already exists")

        # Generate map
        tiles = generate_map(20, 20, seed)

        # Create initial game state
        state = GameState(
            rng_state=seed,
            tiles=tiles,
            players=players.copy(),
        )

        # Initialize player stockpiles
        for player in players:
            state.stockpiles[player] = STARTING_STOCKPILE.model_copy()

        # Place starting units
        self._place_starting_units(state, players, seed)

        # Seed discovered-players sets from starting visibility.
        update_discovery(state)

        # Save to database
        await self.repo.create_game(
            game_id=game_id,
            players=players,
            seed=seed,
            map_width=20,
            map_height=20,
            max_turns=100,
            player_slots=len(players),
        )

        # Update game state in database
        await self.repo.update_game_state(game_id, state)

        # Cache the game state
        self._game_cache[game_id] = state

        # Create initial snapshot
        await self.repo.create_game_snapshot(
            game_id=game_id, turn_number=0, state=state, snapshot_type="initial"
        )

    async def get_game_state(self, game_id: str) -> GameState | None:
        """Get the current state of a game.

        Always loads from the DB. The controller used to hold an in-memory
        ``_game_cache`` but the MCP submit path writes to the DB with a
        separate session, so the REST controller's cache could go stale
        across turn advances — submissions would then upsert against a
        stale ``state.turn`` and silently overwrite the wrong row. The
        cache is kept as a write-through mirror only; reads bypass it.
        """
        db_game = await self.repo.get_game(game_id)
        if not db_game:
            return None

        try:
            state = GameState.model_validate(db_game.state)
            self._game_cache[game_id] = state
            return state
        except Exception as e:
            print(f"Error loading game state for {game_id}: {e}")
            return None

    async def load_game_from_database(self, game_id: str) -> GameState | None:
        """Explicitly load game from database, bypassing cache."""
        db_game = await self.repo.get_game(game_id)
        if not db_game:
            return None

        try:
            state = GameState.model_validate(db_game.state)
            self._game_cache[game_id] = state
            return state
        except Exception as e:
            print(f"Error loading game state for {game_id}: {e}")
            return None

    async def submit_player_actions(
        self, game_id: str, player_id: PlayerId, actions: list[Action]
    ) -> None:
        """Submit actions for a player in the current turn.

        Writes to the ``turn_actions`` table (upsert — resubmitting
        overwrites) and then delegates to
        ``turn_resolution.check_and_resolve_turn``, which is the single
        source of truth shared with the MCP ``submit_actions`` tool.
        """
        state = await self.get_game_state(game_id)
        if not state:
            raise ValueError(f"Game {game_id} not found")

        if player_id not in state.players:
            raise ValueError(f"Player {player_id} not in game {game_id}")

        actions_json = [a.model_dump(mode="json") for a in actions]
        await self.repo.upsert_turn_action(
            game_id=game_id,
            player_id=player_id,
            turn_number=state.turn,
            actions_json=actions_json,
        )

        # Phase 6: fan out turn.submitted so other players' UIs can flip
        # this seat from "deciding" to "submitted". Emitted before the
        # resolve check so subscribers always see the submission frame
        # whether or not this was the last seat (turn.resolved follows).
        submitted = await self.repo.get_all_turn_actions(game_id, state.turn)
        await broadcast_turn_submitted(
            game_id=game_id,
            player_id=player_id,
            turn=state.turn,
            submitted_players=[ta.player_id for ta in submitted],
        )

        await check_and_resolve_turn(self.repo, game_id)

        # Refresh the cache — the turn may have advanced.
        refreshed = await self.load_game_from_database(game_id)
        if refreshed is not None:
            self._game_cache[game_id] = refreshed

    async def log_prompt(self, game_id: str, prompt_log: PromptLog) -> None:
        """Log an LLM prompt and response for research."""
        db_game = await self.repo.get_game(game_id)
        if not db_game:
            raise ValueError(f"Game {game_id} not found")

        await self.repo.save_prompt_log(game_id, prompt_log)

    async def log_enhanced_prompt(
        self,
        game_id: str,
        player_id: str,
        prompt: str,
        response: str,
        tokens_in: int,
        tokens_out: int,
        latency_ms: int,
        turn_number: int | None = None,
        llm_provider: str | None = None,
        llm_model: str | None = None,
        thinking_tokens: str | None = None,
    ) -> None:
        """Log enhanced LLM prompt with additional context."""
        await self.repo.save_enhanced_prompt_log(
            game_id=game_id,
            player_id=player_id,
            prompt=prompt,
            response=response,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=latency_ms,
            turn_number=turn_number,
            llm_provider=llm_provider,
            llm_model=llm_model,
            thinking_tokens=thinking_tokens,
        )

    async def list_games(self, status: str | None = None) -> list[str]:
        """List all active game IDs."""
        games = await self.repo.list_games(status=status)
        return [game.id for game in games]

    async def list_games_with_metadata(
        self,
        status: str | None = None,
        limit: int = 20,
        offset: int = 0,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> tuple[list[DBGame], int]:
        """List games with full metadata and total count."""
        games = await self.repo.list_games(
            status=status,
            limit=limit,
            offset=offset,
            sort_by=sort_by,
            sort_order=sort_order,
        )
        total = await self.repo.count_games(status=status)
        return games, total

    async def get_game_info(self, game_id: str) -> DBGame | None:
        """Get game database record with metadata."""
        return await self.repo.get_game(game_id)

    async def restore_game_state(self, game_id: str) -> GameState | None:
        """Restore game state from database snapshot if needed."""
        snapshot_state = await self.repo.restore_game_from_snapshot(game_id)
        if snapshot_state:
            self._game_cache[game_id] = snapshot_state
            return snapshot_state

        # Fallback to regular database load
        return await self.load_game_from_database(game_id)

    async def get_current_turn(self, game_id: str) -> int:
        """Get the current turn number for a game."""
        state = await self.get_game_state(game_id)
        return state.turn if state else 0

    def clear_cache(self, game_id: str | None = None) -> None:
        """Clear game state cache."""
        if game_id:
            self._game_cache.pop(game_id, None)
        else:
            self._game_cache.clear()


# Global controller instance - single controller for all sessions
_global_controller: PersistentGameController | None = None


def get_persistent_game_controller(session: AsyncSession) -> PersistentGameController:
    """Get or create a persistent game controller. Uses single global instance to share state."""
    global _global_controller

    if _global_controller is None:
        _global_controller = PersistentGameController(session)
    else:
        # Rebind the controller to the current request session while preserving
        # cached game state and pending actions across requests.
        _global_controller.session = session
        _global_controller.repo = GameRepository(session)

    return _global_controller
