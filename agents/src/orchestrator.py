import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any

import logfire
import structlog
from rich.console import Console
from rich.table import Table

from .agent import FourXAgent, GameClient
from .enhanced_logging import enhanced_logger
from .persistent_game_client import ResilientGameConnection

console = Console()

# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer(),
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()


@dataclass
class GameConfig:
    game_id: str
    players: list[str]
    personalities: dict[str, str]
    max_turns: int = 100
    turn_timeout: int = 30
    game_backend_url: str = "http://localhost:8000/api/v1"
    llm_backend_url: str = "http://localhost:1234/v1"
    llm_model: str = "qwen/qwen3-32b"
    primary_provider: str = "llm_studio"
    fallback_providers: list[str] | None = None


class GameOrchestrator:
    """Enhanced orchestrator with async support and detailed logging"""

    def __init__(self, config: GameConfig):
        self.config = config
        self.game_client = GameClient(config.game_backend_url)
        self.resilient_connection = ResilientGameConnection(config.game_backend_url)
        self.agents: dict[str, FourXAgent] = {}
        self.game_state = None
        self.game_active = False
        self.turn_logs: list[dict[str, Any]] = []
        self.logger = logger.bind(component="orchestrator", game_id=config.game_id)

        # Initialize agents
        self._initialize_agents()

    def _initialize_agents(self):
        """Initialize all agents with their personalities and enhanced clients"""
        for player_id in self.config.players:
            personality = self.config.personalities.get(player_id, "balanced")

            agent = FourXAgent(
                player_id=player_id,
                personality=personality,
                game_client=None,  # Let agent create its own with correct player_id
                llm_client=None,  # Let agent create its own enhanced client
                game_backend_url=self.config.game_backend_url,
                primary_provider=self.config.primary_provider,
                fallback_providers=self.config.fallback_providers,
            )
            self.agents[player_id] = agent

        console.print(f"[green]Initialized {len(self.agents)} agents[/green]")
        self.logger.info("Agents initialized", agent_count=len(self.agents))

    def create_game(self) -> bool:
        """Create a new game on the backend with persistence support"""
        try:
            seed = int(time.time())  # Use timestamp as seed

            # Use resilient connection to ensure game exists
            success = self.resilient_connection.connect_to_game(
                self.config.game_id, self.config.players, seed
            )

            if success:
                console.print(
                    f"[green]Game {self.config.game_id} ready (persistent)[/green]"
                )
            return True

        except Exception as e:
            console.print(f"[red]Failed to create game: {e}[/red]")
            self.logger.error("Game creation failed", error=str(e))
            return False

    def check_and_restore_game(self) -> bool:
        """Check if game can be restored from persistence"""
        try:
            console.print(
                f"[blue]Checking persistence for game {self.config.game_id}...[/blue]"
            )

            # Check current game state
            state = self.resilient_connection.get_game_state(self.config.game_id)
            if state:
                self.game_state = state
                console.print(
                    f"[green]✓ Game {self.config.game_id} restored from persistence[/green]"
                )
                console.print(
                    f"[blue]  Current turn: {state.turn}/{state.max_turns}[/blue]"
                )
                self.logger.info(
                    "Game restored from persistence",
                    turn=state.turn,
                    max_turns=state.max_turns,
                )
                return True

            console.print(
                f"[yellow]No persistent state found for game {self.config.game_id}[/yellow]"
            )
            return False

        except Exception as e:
            console.print(f"[red]Error checking game persistence: {e}[/red]")
            self.logger.error("Failed to check game persistence", error=str(e))
            return False

    @logfire.instrument("run_game")
    async def run_game(self) -> dict[str, Any]:
        """Run the complete game from start to finish with enhanced logging"""
        console.print(f"[bold blue]Starting game {self.config.game_id}[/bold blue]")

        # Start enhanced logging
        enhanced_logger.start_game_log(
            game_id=self.config.game_id,
            players=self.config.players,
            personalities=self.config.personalities,
            config=self.config.__dict__,
        )

        # Try to restore existing game first, then create if needed
        game_restored = self.check_and_restore_game()
        if not game_restored:
            if not self.create_game():
                return {"error": "Failed to create game"}

        self.game_active = True
        game_result = {}

        try:
            # Main game loop
            while self.game_active:
                turn_result = await self._play_turn()

                if not turn_result["success"]:
                    console.print(
                        f"[red]Turn failed: {turn_result.get('error', 'Unknown error')}[/red]"
                    )
                    break

                # Check if game should end
                if turn_result.get("game_ended", False):
                    self.game_active = False
                    game_result = turn_result.get("final_state", {})
                    break

                # Brief pause between turns
                await asyncio.sleep(1)

            # Get final game state
            final_state = self.resilient_connection.get_game_state(self.config.game_id)
            game_result = self._analyze_final_state(final_state)

            console.print(
                f"[green]Game completed after {final_state.turn} turns[/green]"
            )
            self._display_game_summary(game_result)

        except KeyboardInterrupt:
            console.print("[yellow]Game interrupted by user[/yellow]")
            self.game_active = False
            game_result = {"status": "interrupted"}
        except Exception as e:
            console.print(f"[red]Game error: {e}[/red]")
            game_result = {"status": "error", "error": str(e)}

        return game_result

    async def _play_turn(self) -> dict[str, Any]:
        """Play one complete turn with all agents (async)"""
        try:
            # Get current game state using resilient connection
            game_state = self.resilient_connection.get_game_state(self.config.game_id)
            if not game_state:
                self.logger.error(
                    "Failed to get game state", game_id=self.config.game_id
                )
                return {"success": False, "error": "Game state not available"}

            current_turn = game_state.turn

            # Check if game has ended
            if current_turn >= game_state.max_turns:
                # Finish enhanced logging
                enhanced_logger.finish_game_log(
                    final_turn=current_turn,
                    winner=None,  # Could determine winner here
                )
                return {"success": True, "game_ended": True, "final_state": game_state}

            console.print(
                f"\n[bold yellow]Turn {current_turn}/{game_state.max_turns}[/bold yellow]"
            )

            # Display current state
            self._display_game_state(game_state)

            # Each agent plays their turn
            turn_log = {
                "turn": current_turn,
                "player_actions": {},
                "turn_start_time": time.time(),
            }

            # Play turns sequentially (could be made concurrent if needed)
            for player_id in self.config.players:
                agent = self.agents[player_id]

                console.print(f"[cyan]{player_id}'s turn...[/cyan]")

                start_time = time.time()
                success = await agent.play_turn(self.config.game_id)
                duration = time.time() - start_time

                turn_log["player_actions"][player_id] = {
                    "success": success,
                    "duration": duration,
                    "plan": agent.turn_history[-1] if agent.turn_history else None,
                }

                if not success:
                    console.print(f"[red]{player_id} failed to play turn[/red]")
                    self.logger.warning(
                        "Player turn failed", player=player_id, turn=current_turn
                    )

            turn_log["turn_end_time"] = time.time()
            self.turn_logs.append(turn_log)

            return {"success": True, "turn": current_turn}

        except Exception as e:
            return {"success": False, "error": str(e)}

    def _display_game_state(self, game_state):
        """Display current game state summary"""
        table = Table(title="Game State Summary")
        table.add_column("Player", style="cyan")
        table.add_column("Cities", style="green")
        table.add_column("Units", style="yellow")
        table.add_column("Resources", style="magenta")

        for player_id in self.config.players:
            cities = [c for c in game_state.cities.values() if c.owner == player_id]
            units = [u for u in game_state.units.values() if u.owner == player_id]
            resources = game_state.stockpiles.get(player_id)

            if resources:
                resource_str = f"F:{resources.food} W:{resources.wood} O:{resources.ore} C:{resources.crystal}"
            else:
                resource_str = "N/A"

            table.add_row(player_id, str(len(cities)), str(len(units)), resource_str)

        console.print(table)

    def _analyze_final_state(self, final_state) -> dict[str, Any]:
        """Analyze the final game state and determine results"""
        results = {
            "turn": final_state.turn,
            "max_turns": final_state.max_turns,
            "players": {},
            "winner": None,
        }

        # Calculate scores for each player
        for player_id in self.config.players:
            cities = [c for c in final_state.cities.values() if c.owner == player_id]
            units = [u for u in final_state.units.values() if u.owner == player_id]
            resources = final_state.stockpiles.get(player_id)

            score = len(cities) * 10 + len(units) * 2
            if resources:
                score += (
                    resources.food
                    + resources.wood
                    + resources.ore
                    + resources.crystal * 2
                )

            results["players"][player_id] = {
                "cities": len(cities),
                "units": len(units),
                "resources": resources.__dict__ if resources else {},
                "score": score,
                "personality": self.config.personalities.get(player_id, "balanced"),
            }

        # Determine winner
        if results["players"]:
            winner = max(
                results["players"].keys(), key=lambda p: results["players"][p]["score"]
            )
            results["winner"] = winner

        return results

    def _display_game_summary(self, results: dict[str, Any]):
        """Display final game summary"""
        console.print("\n" + "=" * 60)
        console.print("[bold green]GAME SUMMARY[/bold green]")
        console.print("=" * 60)

        # Winner announcement
        if results.get("winner"):
            console.print(f"[bold yellow]🏆 WINNER: {results['winner']}[/bold yellow]")

        # Player results table
        table = Table(title="Final Results")
        table.add_column("Player", style="cyan")
        table.add_column("Personality", style="blue")
        table.add_column("Score", style="green")
        table.add_column("Cities", style="yellow")
        table.add_column("Units", style="red")
        table.add_column("Resources", style="magenta")

        # Sort players by score
        sorted_players = sorted(
            results["players"].items(), key=lambda x: x[1]["score"], reverse=True
        )

        for player_id, data in sorted_players:
            resources = data["resources"]
            resource_str = f"F:{resources.get('food', 0)} W:{resources.get('wood', 0)} O:{resources.get('ore', 0)} C:{resources.get('crystal', 0)}"

            table.add_row(
                player_id,
                data["personality"],
                str(data["score"]),
                str(data["cities"]),
                str(data["units"]),
                resource_str,
            )

        console.print(table)

        # Turn summary
        console.print(
            f"\n[bold]Game completed in {results['turn']}/{results['max_turns']} turns[/bold]"
        )

        # Agent performance summary
        if self.turn_logs:
            console.print("\n[bold]Agent Performance:[/bold]")
            for player_id in self.config.players:
                successful_turns = sum(
                    1
                    for log in self.turn_logs
                    if log["player_actions"].get(player_id, {}).get("success", False)
                )
                avg_duration = sum(
                    log["player_actions"].get(player_id, {}).get("duration", 0)
                    for log in self.turn_logs
                ) / len(self.turn_logs)

                console.print(
                    f"  • {player_id}: {successful_turns}/{len(self.turn_logs)} turns successful, "
                    f"avg {avg_duration:.1f}s per turn"
                )

    def save_game_log(self, filename: str):
        """Save complete game log to file"""
        log_data = {
            "config": {
                "game_id": self.config.game_id,
                "players": self.config.players,
                "personalities": self.config.personalities,
                "max_turns": self.config.max_turns,
            },
            "turn_logs": self.turn_logs,
        }

        with open(filename, "w") as f:
            json.dump(log_data, f, indent=2, default=str)

        console.print(f"[green]Game log saved to {filename}[/green]")


def create_test_game() -> GameConfig:
    """Create a test game configuration"""
    return GameConfig(
        game_id="test_game_001",
        players=["Alice", "Bob", "Charlie"],
        personalities={
            "Alice": "aggressive",
            "Bob": "defensive",
            "Charlie": "economic",
        },
        max_turns=50,
    )


async def main():
    """Main function to run a test game (async)"""
    config = create_test_game()
    orchestrator = GameOrchestrator(config)

    try:
        results = await orchestrator.run_game()

        # Save game log
        log_filename = f"game_log_{config.game_id}_{int(time.time())}.json"
        orchestrator.save_game_log(log_filename)

        console.print("\n[green]Game completed successfully![/green]")
        return results

    except Exception as e:
        console.print(f"[red]Error running game: {e}[/red]")
        logfire.log_exception("Game orchestration failed")
        return {"error": str(e)}


if __name__ == "__main__":
    asyncio.run(main())
