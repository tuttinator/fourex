"""
Persistent game controller using database storage.
"""

import random
from collections import defaultdict

from sqlalchemy.ext.asyncio import AsyncSession

from ..database.models import Game as DBGame
from ..database.repository import GameRepository
from ..game.models import (
    Action,
    Coord,
    GameState,
    PlayerId,
    PromptLog,
    ResourceBag,
    Unit,
    UnitType,
)
from ..game.rules import generate_map, resolve_turn
from .websocket import broadcast_player_action, broadcast_turn_end, broadcast_turn_start


class PersistentGameController:
    """Manages multiple game instances with database persistence."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = GameRepository(session)

        # In-memory caches for performance
        self._game_cache: dict[str, GameState] = {}
        self._pending_actions: dict[str, dict[PlayerId, list[Action]]] = defaultdict(
            dict
        )

    async def create_game(
        self, game_id: str, players: list[PlayerId], seed: int = 42
    ) -> None:
        """Create a new game instance with database persistence."""
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
            state.stockpiles[player] = ResourceBag(food=50, wood=20, ore=10)

        # Add starting worker for each player
        rng = random.Random(seed)
        unit_id = 1

        for i, player in enumerate(players):
            # Find a good starting position (plains or forest, away from other players)
            attempts = 0
            while attempts < 100:  # Prevent infinite loop
                x = rng.randint(2, 17)  # Keep away from edges
                y = rng.randint(2, 17)
                coord = Coord(x=x, y=y)

                # Find the tile at this coordinate
                tile = next((t for t in tiles if t.loc == coord), None)
                if tile and tile.terrain in ["plains", "forest"]:
                    # Check if it's far enough from other players
                    too_close = False
                    for existing_unit in state.units.values():
                        if coord.distance_to(existing_unit.loc) < 5:
                            too_close = True
                            break

                    if not too_close:
                        # Create starting worker
                        worker = Unit(
                            id=unit_id,
                            owner=player,
                            type=UnitType.WORKER,
                            hp=100,
                            moves_left=2,
                            loc=coord,
                        )
                        state.units[unit_id] = worker
                        unit_id += 1
                        break

                attempts += 1

            # Fallback: if we couldn't find a good position, just place it somewhere
            if player not in [u.owner for u in state.units.values()]:
                # Find any plains/forest tile
                for tile in tiles:
                    if tile.terrain in ["plains", "forest"]:
                        worker = Unit(
                            id=unit_id,
                            owner=player,
                            type=UnitType.WORKER,
                            hp=100,
                            moves_left=2,
                            loc=tile.loc,
                        )
                        state.units[unit_id] = worker
                        unit_id += 1
                        break

        # Save to database
        await self.repo.create_game(
            game_id=game_id,
            players=players,
            seed=seed,
            map_width=20,
            map_height=20,
            max_turns=100,
        )

        # Update game state in database
        await self.repo.update_game_state(game_id, state)

        # Cache the game state
        self._game_cache[game_id] = state
        self._pending_actions[game_id] = {}

        # Create initial snapshot
        await self.repo.create_game_snapshot(
            game_id=game_id, turn_number=0, state=state, snapshot_type="initial"
        )

    async def get_game_state(self, game_id: str) -> GameState | None:
        """Get the current state of a game."""
        # Check cache first
        if game_id in self._game_cache:
            return self._game_cache[game_id]

        # Load from database
        db_game = await self.repo.get_game(game_id)
        if not db_game:
            return None

        try:
            # Convert database state to GameState model
            state = GameState.model_validate(db_game.state)

            # Cache the loaded state
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
        """Submit actions for a player in the current turn."""
        print(
            f"DEBUG: Submitting actions for {player_id} in game {game_id}, turn {await self.get_current_turn(game_id)}"
        )
        print(f"DEBUG: Actions count: {len(actions)}")

        # Ensure game exists
        state = await self.get_game_state(game_id)
        if not state:
            raise ValueError(f"Game {game_id} not found")

        if player_id not in state.players:
            raise ValueError(f"Player {player_id} not in game {game_id}")

        print(f"DEBUG: Current turn: {state.turn}, Players: {state.players}")

        # Save actions to database
        await self.repo.save_player_actions(
            game_id=game_id,
            turn_number=state.turn,
            player_id=player_id,
            actions=actions,
        )

        # Store in pending actions
        self._pending_actions[game_id][player_id] = actions

        print(
            f"DEBUG: Pending actions now: {list(self._pending_actions[game_id].keys())}"
        )
        print(
            f"DEBUG: Need {len(state.players)} players, have {len(self._pending_actions[game_id])}"
        )

        # Check if all players have submitted actions
        if len(self._pending_actions[game_id]) == len(state.players):
            print(f"DEBUG: All players submitted actions, processing turn {state.turn}")
            await self._process_turn(game_id)
        else:
            print("DEBUG: Waiting for more players to submit actions")

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

    async def get_game_info(self, game_id: str) -> DBGame | None:
        """Get game database record with metadata."""
        return await self.repo.get_game(game_id)

    async def _process_turn(self, game_id: str) -> None:
        """Process a complete turn for all players."""
        print(f"DEBUG: Processing turn for game {game_id}")
        state = await self.get_game_state(game_id)
        if not state:
            print(f"DEBUG: No game state found for {game_id}")
            return

        print(f"DEBUG: Current turn before processing: {state.turn}")
        print(f"DEBUG: Max turns: {state.max_turns}")

        # Broadcast turn start
        await broadcast_turn_start(game_id, state.turn)

        actions = self._pending_actions[game_id].copy()
        print(f"DEBUG: Processing actions: {len(actions)} players submitted actions")

        # Broadcast player actions
        for player_id, player_actions in actions.items():
            print(f"DEBUG: Player {player_id} has {len(player_actions)} actions")
            for action in player_actions:
                await broadcast_player_action(
                    game_id,
                    player_id,
                    {
                        "type": action.type,
                        "unit_id": getattr(action, "unit_id", None),
                        "target_location": getattr(action, "target_location", None),
                        "player": player_id,
                    },
                )

        # Resolve turn
        print(f"DEBUG: Calling resolve_turn with turn {state.turn}")
        result = resolve_turn(state, actions)
        print(f"DEBUG: Turn resolved, new turn is: {state.turn}")

        # Save turn result to database
        print("DEBUG: Saving turn result to database")
        await self.repo.save_turn_result(game_id, result, actions)

        # Update game state in database
        print("DEBUG: Updating game state in database")
        await self.repo.update_game_state(game_id, state)

        # Update cache
        self._game_cache[game_id] = state
        print(f"DEBUG: Updated cache with turn {state.turn}")

        # Broadcast turn end
        await broadcast_turn_end(game_id, state.turn)

        # Clear pending actions for next turn
        self._pending_actions[game_id] = {}
        print("DEBUG: Cleared pending actions for next turn")

        # Create periodic snapshots (every 10 turns)
        if state.turn % 10 == 0:
            await self.repo.create_game_snapshot(
                game_id=game_id,
                turn_number=state.turn,
                state=state,
                snapshot_type="periodic",
            )

        # Check victory conditions
        await self._check_victory(game_id)
        print(f"DEBUG: Turn processing complete for turn {state.turn}")

    async def _check_victory(self, game_id: str) -> None:
        """Check if the game has ended and determine winner."""
        state = await self.get_game_state(game_id)
        if not state:
            return

        winner = None
        victory_type = "none"

        # Domination victory - only one player has cities
        players_with_cities = set()
        for city in state.cities.values():
            players_with_cities.add(city.owner)

        if len(players_with_cities) <= 1 and state.cities:
            # Game ends by domination
            winner = list(players_with_cities)[0] if players_with_cities else None
            victory_type = "domination"
            print(f"Game {game_id} ended by domination, winner: {winner}")

        elif state.turn >= state.max_turns:
            # Game ends by turn limit - calculate scores
            scores = {}
            for player in state.players:
                score = 0
                # Cities worth 5 points each
                score += sum(
                    5 for city in state.cities.values() if city.owner == player
                )
                # Units worth 1 point each
                score += sum(1 for unit in state.units.values() if unit.owner == player)
                # Resources worth 1 point per 50
                resources = state.stockpiles.get(
                    player, state.stockpiles[list(state.stockpiles.keys())[0]]
                )
                score += (
                    resources.food + resources.wood + resources.ore + resources.crystal
                ) // 50
                scores[player] = score

            winner = max(scores, key=scores.get) if scores else None
            victory_type = "score"
            print(
                f"Game {game_id} ended by turn limit, winner: {winner} with score {scores.get(winner, 0)}"
            )

        # If game ended, update database
        if winner is not None or victory_type != "none":
            await self.repo.end_game(game_id, winner, victory_type)

            # Create final snapshot
            await self.repo.create_game_snapshot(
                game_id=game_id,
                turn_number=state.turn,
                state=state,
                snapshot_type="final",
            )

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
            self._pending_actions.pop(game_id, None)
        else:
            self._game_cache.clear()
            self._pending_actions.clear()


# Global controller instance - single controller for all sessions
_global_controller: PersistentGameController | None = None


def get_persistent_game_controller(session: AsyncSession) -> PersistentGameController:
    """Get or create a persistent game controller. Uses single global instance to share state."""
    global _global_controller

    if _global_controller is None:
        _global_controller = PersistentGameController(session)

    return _global_controller
