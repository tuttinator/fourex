"""
CLI tool for testing game mechanics.
"""

import argparse
import random

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .models import (
    Coord,
    FoundCityAction,
    GameState,
    MoveAction,
    PlayerId,
    ResourceBag,
    TrainUnitAction,
    UnitType,
)
from .rules import generate_map, resolve_turn


def create_test_game(players: list[PlayerId], seed: int) -> GameState:
    """Create a test game with initial setup."""
    console = Console()

    # Generate map
    tiles = generate_map(20, 20, seed)

    # Create game state
    state = GameState(
        rng_state=seed,
        tiles=tiles,
        players=players.copy(),
    )

    # Initialize player stockpiles with starting resources
    for player in players:
        state.stockpiles[player] = ResourceBag(food=100, wood=50, ore=30, crystal=5)

    # Place starting units for each player
    rng = random.Random(seed + 1000)
    for i, player in enumerate(players):
        # Find a suitable starting location
        attempts = 0
        while attempts < 100:
            x = rng.randint(2, 17)
            y = rng.randint(2, 17)
            loc = Coord(x=x, y=y)
            tile = state.get_tile(loc)

            if tile and tile.terrain.value in ["plains", "forest"] and not tile.unit_id:
                # Place a worker
                from .models import Unit

                worker = Unit(
                    id=state.next_unit_id,
                    owner=player,
                    type=UnitType.WORKER,
                    hp=2,
                    moves_left=2,
                    loc=loc,
                )
                state.units[worker.id] = worker
                state.next_unit_id += 1
                tile.unit_id = worker.id

                console.print(f"Placed starting worker for {player} at ({x}, {y})")
                break
            attempts += 1

    return state


def print_game_state(state: GameState, console: Console) -> None:
    """Print a summary of the current game state."""

    # Game info panel
    game_info = f"Turn: {state.turn} | Players: {len(state.players)} | Cities: {len(state.cities)} | Units: {len(state.units)}"
    console.print(Panel(game_info, title="Game Status"))

    # Player resources table
    table = Table(title="Player Resources")
    table.add_column("Player", style="cyan")
    table.add_column("Food", style="green")
    table.add_column("Wood", style="yellow")
    table.add_column("Ore", style="red")
    table.add_column("Crystal", style="magenta")
    table.add_column("Cities", style="blue")
    table.add_column("Units", style="white")

    for player in state.players:
        resources = state.stockpiles.get(player, ResourceBag())
        city_count = sum(1 for city in state.cities.values() if city.owner == player)
        unit_count = sum(1 for unit in state.units.values() if unit.owner == player)

        table.add_row(
            player,
            str(resources.food),
            str(resources.wood),
            str(resources.ore),
            str(resources.crystal),
            str(city_count),
            str(unit_count),
        )

    console.print(table)


def simulate_player_actions(state: GameState, player: PlayerId) -> list:
    """Generate some basic AI actions for testing."""
    actions = []

    # Simple AI: try to found cities with workers, train units in cities
    player_units = [unit for unit in state.units.values() if unit.owner == player]
    player_cities = [city for city in state.cities.values() if city.owner == player]

    for unit in player_units:
        if unit.type == UnitType.WORKER and unit.moves_left > 0:
            # Try to found a city if we don't have one yet
            if not player_cities:
                tile = state.get_tile(unit.loc)
                if (
                    tile
                    and not tile.city_id
                    and tile.terrain.value in ["plains", "forest"]
                ):
                    actions.append(FoundCityAction(worker_id=unit.id))
                    continue

            # Otherwise move randomly
            possible_moves = []
            for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
                new_x = (unit.loc.x + dx) % state.map_width
                new_y = (unit.loc.y + dy) % state.map_height
                new_loc = Coord(x=new_x, y=new_y)
                target_tile = state.get_tile(new_loc)
                if (
                    target_tile
                    and not target_tile.unit_id
                    and target_tile.terrain.value in ["plains", "forest"]
                ):
                    possible_moves.append(new_loc)

            if possible_moves:
                target = random.choice(possible_moves)
                actions.append(MoveAction(unit_id=unit.id, to=target))

    # Train units in cities occasionally
    for city in player_cities:
        if random.random() < 0.3:  # 30% chance to train a unit
            city_tile = state.get_tile(city.loc)
            if city_tile and not city_tile.unit_id:  # City tile is free
                unit_types = [UnitType.SCOUT, UnitType.WORKER, UnitType.SOLDIER]
                unit_type = random.choice(unit_types)
                actions.append(TrainUnitAction(city_id=city.id, unit_type=unit_type))

    return actions


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(description="4X Game Test CLI")
    parser.add_argument("--players", type=int, default=4, help="Number of players")
    parser.add_argument(
        "--turns", type=int, default=10, help="Number of turns to simulate"
    )
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")

    args = parser.parse_args()

    console = Console()

    # Create players
    players = [f"player_{i + 1}" for i in range(args.players)]

    console.print(f"[bold green]Starting 4X Game Test[/bold green]")
    console.print(f"Players: {args.players} | Turns: {args.turns} | Seed: {args.seed}")
    console.print()

    # Create game
    state = create_test_game(players, args.seed)

    # Store initial hash for determinism check
    initial_hash = state.hash_state()
    console.print(f"Initial state hash: {initial_hash}")
    console.print()

    # Run simulation
    for turn in range(args.turns):
        console.print(f"[bold yellow]Turn {turn + 1}[/bold yellow]")

        if args.verbose:
            print_game_state(state, console)

        # Generate actions for each player
        all_actions = {}
        for player in players:
            actions = simulate_player_actions(state, player)
            all_actions[player] = actions

            if args.verbose and actions:
                console.print(f"{player}: {len(actions)} actions")

        # Resolve turn
        result = resolve_turn(state, all_actions)

        if args.verbose:
            console.print(f"Turn resolved, new hash: {result.state_hash}")
            console.print()

        # Check for game end conditions
        if state.turn >= state.max_turns:
            console.print("[bold red]Game ended: Maximum turns reached[/bold red]")
            break

        players_with_cities = set(city.owner for city in state.cities.values())
        if len(players_with_cities) <= 1 and state.cities:
            winner = list(players_with_cities)[0] if players_with_cities else "None"
            console.print(
                f"[bold red]Game ended: Domination victory by {winner}[/bold red]"
            )
            break

    # Final state
    console.print("[bold green]Final Game State[/bold green]")
    print_game_state(state, console)

    # Calculate final scores
    console.print("\n[bold blue]Final Scores[/bold blue]")
    scores = {}
    for player in players:
        score = 0
        score += sum(5 for city in state.cities.values() if city.owner == player)
        score += sum(1 for unit in state.units.values() if unit.owner == player)
        resources = state.stockpiles.get(player, ResourceBag())
        score += (
            resources.food + resources.wood + resources.ore + resources.crystal
        ) // 50
        scores[player] = score
        console.print(f"{player}: {score} points")

    if scores:
        winner = max(scores, key=scores.get)
        console.print(
            f"\n[bold green]Winner: {winner} with {scores[winner]} points![/bold green]"
        )

    # Test determinism by running again with same seed
    console.print(f"\n[bold cyan]Testing Determinism[/bold cyan]")
    test_state = create_test_game(players, args.seed)
    test_hash = test_state.hash_state()

    if test_hash == initial_hash:
        console.print(
            "[green]✓ Determinism test passed - same seed produces same initial state[/green]"
        )
    else:
        console.print("[red]✗ Determinism test failed - different initial states[/red]")
        console.print(f"Original: {initial_hash}")
        console.print(f"Test:     {test_hash}")


if __name__ == "__main__":
    main()
