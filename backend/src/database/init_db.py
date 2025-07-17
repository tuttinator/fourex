#!/usr/bin/env python3
"""
Database initialization script.
"""

import asyncio
import sys
from rich.console import Console
from rich.panel import Panel

from .connection import init_db, drop_db, get_engine

console = Console()


async def create_database():
    """Create all database tables."""
    try:
        console.print("[bold blue]Creating database tables...[/bold blue]")
        await init_db()
        console.print("[green]✓ Database tables created successfully[/green]")
    except Exception as e:
        console.print(f"[red]✗ Failed to create database tables: {e}[/red]")
        raise


async def reset_database():
    """Drop and recreate all database tables."""
    try:
        console.print("[bold yellow]WARNING: This will delete all data![/bold yellow]")
        console.print("[bold red]Dropping all tables...[/bold red]")
        await drop_db()
        console.print("[yellow]✓ All tables dropped[/yellow]")
        
        console.print("[bold blue]Creating database tables...[/bold blue]")
        await init_db()
        console.print("[green]✓ Database tables recreated successfully[/green]")
    except Exception as e:
        console.print(f"[red]✗ Failed to reset database: {e}[/red]")
        raise


async def check_database():
    """Check database connection and schema."""
    try:
        engine = await get_engine()
        console.print("[bold blue]Checking database connection...[/bold blue]")
        
        # Try to connect
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


async def main():
    """Main CLI function."""
    if len(sys.argv) < 2:
        console.print(Panel(
            """
[bold]Database Management Commands:[/bold]

• python -m src.database.init_db create    - Create database tables
• python -m src.database.init_db reset     - Drop and recreate all tables
• python -m src.database.init_db check     - Check database connection
            """,
            title="4X Game Database Management",
            border_style="blue"
        ))
        return
    
    command = sys.argv[1].lower()
    
    try:
        if command == "create":
            await create_database()
        elif command == "reset":
            await reset_database()
        elif command == "check":
            await check_database()
        else:
            console.print(f"[red]Unknown command: {command}[/red]")
            console.print("Available commands: create, reset, check")
            sys.exit(1)
            
        console.print("[bold green]Operation completed successfully![/bold green]")
        
    except Exception as e:
        console.print(f"[bold red]Operation failed: {e}[/bold red]")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())