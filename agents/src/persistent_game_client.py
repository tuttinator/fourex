"""
Enhanced game client with persistence support.
"""

import time
from typing import Any

import structlog
from rich.console import Console

from .agent import GameClient, GameState

console = Console()
logger = structlog.get_logger()


class PersistentGameClient(GameClient):
    """Game client with database persistence support."""

    def __init__(
        self, base_url: str = "http://localhost:8000/api/v1", player_id: str = ""
    ):
        super().__init__(base_url, player_id)
        self.logger = logger.bind(
            component="persistent_game_client", player_id=player_id
        )

    def submit_actions(
        self, game_id: str, player_id: str, actions: list[dict[str, Any]]
    ) -> bool:
        """Submit actions to persistent game controller."""
        try:
            self.logger.info(
                "Submitting actions to persistent game",
                game_id=game_id,
                player_id=player_id,
                action_count=len(actions),
            )

            response = self.session.post(
                f"{self.base_url}/actions?game_id={game_id}",
                json=actions,
                headers={"Authorization": f"Bearer player_{player_id}"},
            )

            if response.status_code == 200:
                result = response.json()
                self.logger.info("Actions submitted successfully", result=result)
                return True
            else:
                self.logger.error(
                    "Failed to submit actions",
                    status_code=response.status_code,
                    response=response.text,
                )
                return False

        except Exception as e:
            self.logger.error("Error submitting actions", error=str(e))
            return False

    def create_game(self, game_id: str, players: list[str], seed: int = 42) -> bool:
        """Create a new persistent game."""
        try:
            self.logger.info(
                "Creating persistent game", game_id=game_id, players=players, seed=seed
            )

            response = self.session.post(
                f"{self.base_url}/games/{game_id}/start",
                json={"players": players, "seed": seed},
            )

            if response.status_code == 200:
                result = response.json()
                self.logger.info("Game created successfully", result=result)
                return True
            else:
                self.logger.error(
                    "Failed to create game",
                    status_code=response.status_code,
                    response=response.text,
                )
                return False

        except Exception as e:
            self.logger.error("Error creating game", error=str(e))
            return False

    def get_game_info(self, game_id: str) -> dict[str, Any] | None:
        """Get game metadata and status."""
        try:
            response = self.session.get(f"{self.base_url}/games/{game_id}/info")

            if response.status_code == 200:
                return response.json()
            elif response.status_code == 404:
                self.logger.warning("Game not found", game_id=game_id)
                return None
            else:
                self.logger.error(
                    "Failed to get game info", status_code=response.status_code
                )
                return None

        except Exception as e:
            self.logger.error("Error getting game info", error=str(e))
            return None

    def restore_game(self, game_id: str) -> bool:
        """Restore game state from database snapshot."""
        try:
            self.logger.info("Restoring game from database", game_id=game_id)

            response = self.session.post(f"{self.base_url}/games/{game_id}/restore")

            if response.status_code == 200:
                result = response.json()
                self.logger.info("Game restored successfully", result=result)
                return True
            elif response.status_code == 404:
                self.logger.warning("Game not found for restoration", game_id=game_id)
                return False
            else:
                self.logger.error(
                    "Failed to restore game",
                    status_code=response.status_code,
                    response=response.text,
                )
                return False

        except Exception as e:
            self.logger.error("Error restoring game", error=str(e))
            return False

    def list_games(self) -> list[str]:
        """List all active games."""
        try:
            response = self.session.get(f"{self.base_url}/games")

            if response.status_code == 200:
                result = response.json()
                return result.get("games", [])
            else:
                self.logger.error(
                    "Failed to list games", status_code=response.status_code
                )
                return []

        except Exception as e:
            self.logger.error("Error listing games", error=str(e))
            return []

    def get_game_state_with_retry(
        self, game_id: str, max_retries: int = 3
    ) -> GameState | None:
        """Get game state with retry logic for persistence."""
        for attempt in range(max_retries):
            try:
                state = self.get_game_state(game_id)
                if state:
                    return state

                # If no state found, try to restore from database
                if attempt < max_retries - 1:
                    self.logger.info(
                        "Game state not found, attempting restoration",
                        game_id=game_id,
                        attempt=attempt + 1,
                    )
                    self.restore_game(game_id)
                    time.sleep(1)  # Wait a bit for restoration

            except Exception as e:
                self.logger.error(
                    "Error getting game state", error=str(e), attempt=attempt + 1
                )
                if attempt < max_retries - 1:
                    time.sleep(2**attempt)  # Exponential backoff

        return None

    def ensure_game_exists(
        self, game_id: str, players: list[str], seed: int = 42
    ) -> bool:
        """Ensure game exists, creating it if necessary."""
        try:
            # First, check if game already exists
            game_info = self.get_game_info(game_id)
            if game_info:
                self.logger.info(
                    "Game already exists",
                    game_id=game_id,
                    status=game_info.get("status"),
                )
                return True

            # Try to restore from database
            if self.restore_game(game_id):
                self.logger.info("Game restored from database", game_id=game_id)
                return True

            # Create new game
            if self.create_game(game_id, players, seed):
                self.logger.info("New game created", game_id=game_id)
                return True

            self.logger.error("Failed to ensure game exists", game_id=game_id)
            return False

        except Exception as e:
            self.logger.error(
                "Error ensuring game exists", error=str(e), game_id=game_id
            )
            return False

    def check_game_persistence(self, game_id: str) -> dict[str, Any]:
        """Check the persistence status of a game."""
        result = {
            "game_exists": False,
            "in_memory": False,
            "in_database": False,
            "can_restore": False,
            "game_info": None,
        }

        try:
            # Check if game state is accessible
            state = self.get_game_state(game_id)
            if state:
                result["in_memory"] = True
                result["game_exists"] = True

            # Check database info
            game_info = self.get_game_info(game_id)
            if game_info:
                result["in_database"] = True
                result["game_exists"] = True
                result["game_info"] = game_info

            # Check if restoration is possible
            if not result["in_memory"] and result["in_database"]:
                result["can_restore"] = True

        except Exception as e:
            self.logger.error("Error checking game persistence", error=str(e))

        return result


class ResilientGameConnection:
    """Manages resilient connections to persistent games."""

    def __init__(
        self, base_url: str = "http://localhost:8000/api/v1", player_id: str = ""
    ):
        self.client = PersistentGameClient(base_url, player_id)
        self.player_id = player_id
        self.logger = logger.bind(
            component="resilient_game_connection", player_id=player_id
        )

    def connect_to_game(self, game_id: str, players: list[str], seed: int = 42) -> bool:
        """Connect to a game with full resilience."""
        try:
            console.print(f"[blue]Connecting to game {game_id}...[/blue]")

            # Check current game status
            status = self.client.check_game_persistence(game_id)
            self.logger.info("Game persistence status", status=status)

            if status["in_memory"]:
                console.print(
                    f"[green]✓ Game {game_id} is active and accessible[/green]"
                )
                return True

            if status["can_restore"]:
                console.print(
                    f"[yellow]⚠ Game {game_id} found in database, restoring...[/yellow]"
                )
                if self.client.restore_game(game_id):
                    console.print(
                        f"[green]✓ Game {game_id} restored successfully[/green]"
                    )
                    return True
                else:
                    console.print(f"[red]✗ Failed to restore game {game_id}[/red]")

            if status["in_database"]:
                console.print(f"[blue]Game {game_id} exists in database[/blue]")
                # Try to get the state directly
                state = self.client.get_game_state_with_retry(game_id)
                if state:
                    console.print(
                        "[green]✓ Successfully connected to existing game[/green]"
                    )
                    return True

            # Create new game
            console.print(f"[blue]Creating new game {game_id}...[/blue]")
            if self.client.ensure_game_exists(game_id, players, seed):
                console.print(f"[green]✓ Game {game_id} created and ready[/green]")
                return True

            console.print(f"[red]✗ Failed to connect to game {game_id}[/red]")
            return False

        except Exception as e:
            self.logger.error("Error connecting to game", error=str(e))
            console.print(f"[red]✗ Connection error: {e}[/red]")
            return False

    def get_game_state(self, game_id: str) -> GameState | None:
        """Get game state with full resilience."""
        return self.client.get_game_state_with_retry(game_id)

    def submit_actions(self, game_id: str, actions: list[dict[str, Any]]) -> bool:
        """Submit actions with resilience."""
        try:
            return self.client.submit_actions(game_id, self.player_id, actions)
        except Exception as e:
            self.logger.error("Error submitting actions", error=str(e))
            # Could add retry logic here
            return False
