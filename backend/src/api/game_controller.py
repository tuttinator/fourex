"""
Game controller for managing multiple game instances.
"""

import random
from collections import defaultdict

from ..game.models import (
    Action,
    Coord,
    GameState,
    PlayerId,
    PromptLog,
    ResourceBag,
    TurnResult,
    Unit,
    UnitType,
)
from ..game.rules import generate_map, resolve_turn


class GameController:
    """Manages multiple game instances and turn processing."""

    def __init__(self):
        self.games: dict[str, GameState] = {}
        self.pending_actions: dict[str, dict[PlayerId, list[Action]]] = defaultdict(
            dict
        )
        self.prompt_logs: dict[str, list[PromptLog]] = defaultdict(list)
        self.turn_results: dict[str, list[TurnResult]] = defaultdict(list)

    def create_game(
        self, game_id: str, players: list[PlayerId], seed: int = 42
    ) -> None:
        """Create a new game instance."""
        if game_id in self.games:
            raise ValueError(f"Game {game_id} already exists")

        if len(players) < 2 or len(players) > 8:
            raise ValueError("Games require 2-8 players")

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

        self.games[game_id] = state
        self.pending_actions[game_id] = {}

    def get_game_state(self, game_id: str) -> GameState | None:
        """Get the current state of a game."""
        return self.games.get(game_id)

    def submit_player_actions(
        self, game_id: str, player_id: PlayerId, actions: list[Action]
    ) -> None:
        """Submit actions for a player in the current turn."""
        if game_id not in self.games:
            raise ValueError(f"Game {game_id} not found")

        state = self.games[game_id]
        if player_id not in state.players:
            raise ValueError(f"Player {player_id} not in game {game_id}")

        self.pending_actions[game_id][player_id] = actions

        # Check if all players have submitted actions
        if len(self.pending_actions[game_id]) == len(state.players):
            self._process_turn(game_id)

    def log_prompt(self, game_id: str, prompt_log: PromptLog) -> None:
        """Log an LLM prompt and response for research."""
        if game_id not in self.games:
            raise ValueError(f"Game {game_id} not found")

        self.prompt_logs[game_id].append(prompt_log)

    def list_games(self) -> list[str]:
        """List all active game IDs."""
        return list(self.games.keys())

    def _process_turn(self, game_id: str) -> None:
        """Process a complete turn for all players."""
        state = self.games[game_id]
        actions = self.pending_actions[game_id].copy()

        # Resolve turn
        result = resolve_turn(state, actions)
        self.turn_results[game_id].append(result)

        # Clear pending actions for next turn
        self.pending_actions[game_id] = {}

        # Check victory conditions
        self._check_victory(game_id)

    def _check_victory(self, game_id: str) -> None:
        """Check if the game has ended and determine winner."""
        state = self.games[game_id]

        # Domination victory - only one player has cities
        players_with_cities = set()
        for city in state.cities.values():
            players_with_cities.add(city.owner)

        if len(players_with_cities) <= 1 and state.cities:
            # Game ends by domination
            winner = list(players_with_cities)[0] if players_with_cities else None
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
            print(
                f"Game {game_id} ended by turn limit, winner: {winner} with score {scores.get(winner, 0)}"
            )


# Global controller instance
_controller = GameController()


def get_game_controller() -> GameController:
    """Dependency to get the global game controller."""
    return _controller
