#!/usr/bin/env python3
"""
Database management CLI for 4X game backend.
"""

import asyncio
import sys
import os
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from src.database.connection import init_db, drop_db, get_engine
from src.database.repository import GameRepository
from src.database.connection import get_database_session

console = Console()


async def create_tables():
    """Create all database tables."""
    try:
        console.print("[bold blue]Creating database tables...[/bold blue]")
        await init_db()
        console.print("[green]✓ Database tables created successfully[/green]")
    except Exception as e:
        console.print(f"[red]✗ Failed to create database tables: {e}[/red]")
        raise


async def drop_tables():
    """Drop all database tables."""
    try:
        console.print("[bold red]WARNING: This will delete all data![/bold red]")
        console.print("[bold red]Dropping all tables...[/bold red]")
        await drop_db()
        console.print("[yellow]✓ All tables dropped[/yellow]")
    except Exception as e:
        console.print(f"[red]✗ Failed to drop database tables: {e}[/red]")
        raise


async def reset_database():
    """Drop and recreate all database tables."""
    await drop_tables()
    await create_tables()


async def check_connection():
    """Check database connection."""
    try:
        engine = await get_engine()
        console.print("[bold blue]Checking database connection...[/bold blue]")
        
        async with engine.begin() as conn:
            result = await conn.execute("SELECT 1")
            row = result.fetchone()
            if row and row[0] == 1:
                console.print("[green]✓ Database connection successful[/green]")
            else:
                console.print("[red]✗ Database connection test failed[/red]")
                
    except Exception as e:
        console.print(f"[red]✗ Database connection failed: {e}[/red]")
        raise


async def list_games():
    """List all games in the database."""
    try:
        async for session in get_database_session():
            repo = GameRepository(session)
            games = await repo.list_games(limit=100)
            
            if not games:
                console.print("[yellow]No games found in database[/yellow]")
                return
            
            table = Table(title="Games in Database")
            table.add_column("Game ID", style="cyan")
            table.add_column("Players", style="green")
            table.add_column("Turn", style="yellow")
            table.add_column("Status", style="magenta")
            table.add_column("Created", style="blue")
            
            for game in games:
                players_str = ", ".join(game.players)
                created_str = game.created_at.strftime("%Y-%m-%d %H:%M")
                table.add_row(
                    game.id,
                    players_str,
                    str(game.turn),
                    game.status,
                    created_str
                )
            
            console.print(table)
            break
            
    except Exception as e:
        console.print(f"[red]✗ Failed to list games: {e}[/red]")
        raise


async def game_info(game_id: str):
    """Show detailed information about a specific game."""
    try:
        async for session in get_database_session():
            repo = GameRepository(session)
            game = await repo.get_game(game_id)
            
            if not game:
                console.print(f"[red]Game '{game_id}' not found[/red]")
                return
            
            # Game info panel
            info_text = f"""
[bold]Game ID:[/bold] {game.id}
[bold]Players:[/bold] {', '.join(game.players)}
[bold]Turn:[/bold] {game.turn}/{game.max_turns}
[bold]Status:[/bold] {game.status}
[bold]Seed:[/bold] {game.seed}
[bold]Map Size:[/bold] {game.map_width}x{game.map_height}
[bold]Created:[/bold] {game.created_at.strftime("%Y-%m-%d %H:%M:%S")}
[bold]Updated:[/bold] {game.updated_at.strftime("%Y-%m-%d %H:%M:%S")}
"""
            
            if game.winner:
                info_text += f"\n[bold]Winner:[/bold] {game.winner} ({game.victory_type})"
            if game.ended_at:
                info_text += f"\n[bold]Ended:[/bold] {game.ended_at.strftime("%Y-%m-%d %H:%M:%S")}"
            
            console.print(Panel(info_text, title=f"Game: {game_id}", border_style="blue"))
            
            # Turn history
            turns = await repo.get_turn_history(game_id)
            if turns:
                console.print(f"\n[bold]Turn History:[/bold] {len(turns)} turns processed")
                for i, turn in enumerate(turns[-5:]):  # Show last 5 turns
                    console.print(f"  Turn {turn.turn_number}: {turn.state_hash[:8]}... ({len(turn.player_actions)} players)")
            
            break
            
    except Exception as e:
        console.print(f"[red]✗ Failed to get game info: {e}[/red]")
        raise


async def main():
    """Main CLI function."""
    if len(sys.argv) < 2:
        console.print(Panel(
            """
[bold]Database Management Commands:[/bold]

• python manage_db.py create       - Create database tables
• python manage_db.py drop         - Drop all tables (WARNING: deletes data!)
• python manage_db.py reset        - Drop and recreate all tables
• python manage_db.py check        - Check database connection
• python manage_db.py list-games   - List all games
• python manage_db.py game-info <game_id> - Show game details

[bold]Environment Variables:[/bold]
• DATABASE_URL - PostgreSQL connection string
• SQL_DEBUG - Enable SQL query logging (true/false)
            """,
            title="4X Game Database Management",
            border_style="blue"
        ))
        return
    
    command = sys.argv[1].lower()
    
    try:
        if command == "create":
            await create_tables()
        elif command == "drop":
            await drop_tables()
        elif command == "reset":
            await reset_database()
        elif command == "check":
            await check_connection()
        elif command == "list-games":
            await list_games()
        elif command == "game-info":
            if len(sys.argv) < 3:
                console.print("[red]Please provide game ID: python manage_db.py game-info <game_id>[/red]")
                sys.exit(1)
            await game_info(sys.argv[2])
        else:
            console.print(f"[red]Unknown command: {command}[/red]")
            console.print("Available commands: create, drop, reset, check, list-games, game-info")
            sys.exit(1)
            
        console.print("[bold green]Operation completed successfully![/bold green]")
        
    except Exception as e:
        console.print(f"[bold red]Operation failed: {e}[/bold red]")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())