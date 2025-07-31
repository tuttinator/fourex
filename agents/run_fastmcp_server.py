#!/usr/bin/env python3
"""
Script to run the FastMCP server for 4X game tools.
Usage: python run_fastmcp_server.py [options]
"""

import argparse
import sys

from rich.console import Console

console = Console()


def main():
    """Main function to run the FastMCP server"""
    parser = argparse.ArgumentParser(description="Run 4X Game FastMCP Server")
    parser.add_argument(
        "--game-backend",
        default="http://localhost:8000/api/v1",
        help="Game backend URL",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose logging")

    args = parser.parse_args()

    console.print("[bold blue]Starting 4X Game FastMCP Server[/bold blue]")
    console.print(f"Game Backend: {args.game_backend}")

    try:
        from src.fastmcp_server import main as fastmcp_main

        # FastMCP manages its own event loop, so we call it directly
        fastmcp_main()
    except KeyboardInterrupt:
        console.print("\n[yellow]FastMCP Server stopped by user[/yellow]")
    except Exception as e:
        console.print(f"\n[red]Error running FastMCP server: {e}[/red]")
        if args.verbose:
            import traceback

            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
