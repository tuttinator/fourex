#!/usr/bin/env python3
"""
Script to run AI agents playing the 4X game.
Usage: python run_agents.py [options]
"""

import argparse
import json
import os
import time

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from src.orchestrator import GameConfig, GameOrchestrator
from src.personalities import get_personality_description, list_personalities

console = Console()


def create_game_config(
    game_id: str | None = None,
    players: list[str] | None = None,
    personalities: dict[str, str] | None = None,
    max_turns: int = 100,
    game_backend: str = "http://localhost:8000/api/v1",
    llm_backend: str = "http://localhost:1234/v1",
    llm_model: str = "qwen/qwen3-32b",
) -> GameConfig:
    """Create a game configuration with defaults"""

    if game_id is None:
        game_id = f"game_{int(time.time())}"

    if players is None:
        players = ["Alice", "Bob", "Charlie"]

    if personalities is None:
        personalities = {
            "Alice": "aggressive",
            "Bob": "defensive",
            "Charlie": "economic",
        }

    return GameConfig(
        game_id=game_id,
        players=players,
        personalities=personalities,
        max_turns=max_turns,
        game_backend_url=game_backend,
        llm_backend_url=llm_backend,
        llm_model=llm_model,
    )


def interactive_setup() -> GameConfig:
    """Interactive setup for game configuration"""
    console.print("[bold blue]4X AI Agent Game Setup[/bold blue]")
    console.print()

    # Game ID
    game_id = Prompt.ask("Game ID", default=f"game_{int(time.time())}")

    # Max turns
    max_turns = int(Prompt.ask("Maximum turns", default="100"))

    # Players
    console.print("\n[bold]Player Setup[/bold]")
    num_players = int(
        Prompt.ask(
            "Number of players",
            default="3",
            choices=["2", "3", "4", "5", "6", "7", "8"],
        )
    )

    players = []
    personalities = {}

    # Show available personalities
    console.print("\n[bold]Available Personalities:[/bold]")
    available_personalities = list_personalities()
    for i, personality in enumerate(available_personalities):
        description = get_personality_description(personality)
        console.print(f"  {i + 1}. [cyan]{personality}[/cyan]: {description}")

    for i in range(num_players):
        console.print(f"\n[bold]Player {i + 1}:[/bold]")
        player_name = Prompt.ask(f"Player {i + 1} name", default=f"Player{i + 1}")

        # Personality selection
        while True:
            personality = Prompt.ask(
                f"Personality for {player_name}",
                default="balanced",
                choices=available_personalities,
            )

            if personality in available_personalities:
                break
            console.print(
                f"[red]Invalid personality. Choose from: {', '.join(available_personalities)}[/red]"
            )

        players.append(player_name)
        personalities[player_name] = personality

    # Backend configuration
    console.print("\n[bold]Backend Configuration[/bold]")
    game_backend = Prompt.ask(
        "Game backend URL", default="http://localhost:8000/api/v1"
    )
    llm_backend = Prompt.ask("LLM backend URL", default="http://localhost:1234/v1")
    llm_model = Prompt.ask("LLM model", default="qwen/qwen3-32b")

    return GameConfig(
        game_id=game_id,
        players=players,
        personalities=personalities,
        max_turns=max_turns,
        game_backend_url=game_backend,
        llm_backend_url=llm_backend,
        llm_model=llm_model,
    )


def load_config_from_file(filename: str) -> GameConfig:
    """Load game configuration from JSON file"""
    with open(filename) as f:
        data = json.load(f)

    return GameConfig(**data)


def save_config_to_file(config: GameConfig, filename: str):
    """Save game configuration to JSON file"""
    data = {
        "game_id": config.game_id,
        "players": config.players,
        "personalities": config.personalities,
        "max_turns": config.max_turns,
        "game_backend_url": config.game_backend_url,
        "llm_backend_url": config.llm_backend_url,
        "llm_model": config.llm_model,
    }

    with open(filename, "w") as f:
        json.dump(data, f, indent=2)

    console.print(f"[green]Configuration saved to {filename}[/green]")


def preset_configurations() -> dict[str, GameConfig]:
    """Predefined game configurations"""
    return {
        "quick_test": create_game_config(
            game_id="quick_test",
            players=["Alice", "Bob"],
            personalities={"Alice": "aggressive", "Bob": "defensive"},
            max_turns=30,
        ),
        "classic_3p": create_game_config(
            game_id="classic_3p",
            players=["Warrior", "Builder", "Trader"],
            personalities={
                "Warrior": "aggressive",
                "Builder": "defensive",
                "Trader": "economic",
            },
            max_turns=75,
        ),
        "personality_showcase": create_game_config(
            game_id="personality_showcase",
            players=["Conqueror", "Diplomat", "Explorer", "Economist"],
            personalities={
                "Conqueror": "aggressive",
                "Diplomat": "diplomatic",
                "Explorer": "explorer",
                "Economist": "economic",
            },
            max_turns=100,
        ),
        "advanced_strategies": create_game_config(
            game_id="advanced_strategies",
            players=["TechCorp", "Opportunist", "Balanced", "Explorer"],
            personalities={
                "TechCorp": "tech_focused",
                "Opportunist": "opportunist",
                "Balanced": "balanced",
                "Explorer": "explorer",
            },
            max_turns=120,
        ),
    }


def main():
    parser = argparse.ArgumentParser(
        description="Run AI agents playing 4X strategy game"
    )
    parser.add_argument("--config", "-c", help="Load configuration from JSON file")
    parser.add_argument(
        "--preset",
        "-p",
        help="Use preset configuration",
        choices=[
            "quick_test",
            "classic_3p",
            "personality_showcase",
            "advanced_strategies",
        ],
    )
    parser.add_argument(
        "--interactive", "-i", action="store_true", help="Interactive setup"
    )
    parser.add_argument("--game-id", help="Game ID")
    parser.add_argument("--players", nargs="+", help="Player names")
    parser.add_argument("--personalities", nargs="+", help="Player personalities")
    parser.add_argument("--max-turns", type=int, default=100, help="Maximum turns")
    parser.add_argument(
        "--game-backend",
        default="http://localhost:8000/api/v1",
        help="Game backend URL",
    )
    parser.add_argument(
        "--llm-backend", default="http://localhost:1234/v1", help="LLM backend URL"
    )
    parser.add_argument("--llm-model", default="qwen/qwen3-32b", help="LLM model")
    parser.add_argument("--save-config", help="Save configuration to file")
    parser.add_argument(
        "--list-personalities", action="store_true", help="List available personalities"
    )
    parser.add_argument(
        "--list-presets", action="store_true", help="List available presets"
    )

    args = parser.parse_args()

    # List personalities
    if args.list_personalities:
        console.print("[bold]Available Personalities:[/bold]")
        for personality in list_personalities():
            description = get_personality_description(personality)
            console.print(f"  • [cyan]{personality}[/cyan]: {description}")
        return

    # List presets
    if args.list_presets:
        console.print("[bold]Available Presets:[/bold]")
        presets = preset_configurations()
        for name, config in presets.items():
            console.print(
                f"  • [cyan]{name}[/cyan]: {len(config.players)} players, {config.max_turns} turns"
            )
            for player, personality in config.personalities.items():
                console.print(f"    - {player}: {personality}")
        return

    # Load or create configuration
    if args.config:
        config = load_config_from_file(args.config)
    elif args.preset:
        presets = preset_configurations()
        if args.preset not in presets:
            console.print(f"[red]Unknown preset: {args.preset}[/red]")
            return
        config = presets[args.preset]
    elif args.interactive:
        config = interactive_setup()
    else:
        # Create from command line args
        players = args.players or ["Alice", "Bob", "Charlie"]
        personalities = {}

        if args.personalities:
            if len(args.personalities) != len(players):
                console.print(
                    f"[red]Number of personalities ({len(args.personalities)}) must match number of players ({len(players)})[/red]"
                )
                return
            for player, personality in zip(players, args.personalities):
                personalities[player] = personality
        else:
            default_personalities = [
                "aggressive",
                "defensive",
                "economic",
                "balanced",
                "explorer",
                "diplomatic",
                "tech_focused",
                "opportunist",
            ]
            for i, player in enumerate(players):
                personalities[player] = default_personalities[
                    i % len(default_personalities)
                ]

        config = create_game_config(
            game_id=args.game_id,
            players=players,
            personalities=personalities,
            max_turns=args.max_turns,
            game_backend=args.game_backend,
            llm_backend=args.llm_backend,
            llm_model=args.llm_model,
        )

    # Save configuration if requested
    if args.save_config:
        save_config_to_file(config, args.save_config)

    # Display configuration
    console.print(
        Panel(
            f"""
[bold]Game Configuration:[/bold]
Game ID: {config.game_id}
Players: {", ".join(config.players)}
Max Turns: {config.max_turns}
Game Backend: {config.game_backend_url}
LLM Backend: {config.llm_backend_url}
LLM Model: {config.llm_model}

[bold]Player Personalities:[/bold]
{chr(10).join([f"• {player}: {personality}" for player, personality in config.personalities.items()])}
""",
            title="4X AI Game",
            border_style="blue",
        )
    )

    # Confirm before starting
    if not Confirm.ask("Start the game?", default=True):
        console.print("[yellow]Game cancelled.[/yellow]")
        return

    # Run the game
    try:
        orchestrator = GameOrchestrator(config)
        results = orchestrator.run_game()

        # Save game log
        log_filename = f"logs/game_log_{config.game_id}_{int(time.time())}.json"
        os.makedirs("logs", exist_ok=True)
        orchestrator.save_game_log(log_filename)

        console.print(f"\n[green]Game completed successfully![/green]")
        console.print(f"[blue]Game log saved to: {log_filename}[/blue]")

        return results

    except KeyboardInterrupt:
        console.print("\n[yellow]Game interrupted by user.[/yellow]")
    except Exception as e:
        console.print(f"\n[red]Error running game: {e}[/red]")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    main()
