#!/usr/bin/env python3
"""
CLI entry point for running profile-driven MCP agents.

This is a thin shim on top of ``backend.src.agents.orchestrator``. The
full agent runtime lives in the backend package; this file only handles
argument parsing and console output. Everything else — game creation,
turn execution, action submission, memory — flows through the MCP
server in-process.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

# Make the repo root importable (the ``backend.src`` package lives there).
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from backend.src.agents import (  # noqa: E402 — after path setup
    InProcessMCPClient,
    list_profiles,
    run_orchestrated_game,
)
from backend.src.mcp_server.server import create_mcp_server  # noqa: E402

console = Console()


_PRESETS: dict[str, dict[str, object]] = {
    "quick_test": {
        "players": ["Alice", "Bob"],
        "personalities": {"Alice": "aggressive", "Bob": "economic"},
        "max_turns": 30,
    },
    "classic_3p": {
        "players": ["Warrior", "Builder", "Trader"],
        "personalities": {
            "Warrior": "aggressive",
            "Builder": "balanced",
            "Trader": "economic",
        },
        "max_turns": 75,
    },
    "personality_showcase": {
        "players": ["Conqueror", "Economist", "Explorer", "Adaptive"],
        "personalities": {
            "Conqueror": "aggressive",
            "Economist": "economic",
            "Explorer": "explorer",
            "Adaptive": "balanced",
        },
        "max_turns": 100,
    },
}


async def _run(
    players: list[str],
    personalities: dict[str, str],
    max_turns: int,
    max_turn_cap: int | None,
) -> None:
    mcp = create_mcp_server()
    client = InProcessMCPClient(mcp)

    console.print(
        Panel(
            "\n".join(
                [
                    f"Players: {', '.join(players)}",
                    f"Profiles: {personalities}",
                    f"Max turns: {max_turns}",
                    f"Turn cap: {max_turn_cap if max_turn_cap else 'none'}",
                ]
            ),
            title="MCP agent game",
            border_style="blue",
        )
    )

    started = time.time()
    result = await run_orchestrated_game(
        client,
        players,
        personalities=personalities,
        max_turns=max_turns,
        max_turn_cap=max_turn_cap,
    )
    duration = time.time() - started

    table = Table(title=f"Final scores — game {result.game_id}")
    table.add_column("Player", style="cyan")
    table.add_column("Profile", style="magenta")
    table.add_column("Score", justify="right", style="green")
    for player in players:
        table.add_row(
            player,
            personalities.get(player, "balanced"),
            str(result.scores.get(player, 0)),
        )
    console.print(table)

    console.print(
        "\n".join(
            [
                f"Turns played: {result.final_turn}",
                f"Status: {result.status}",
                f"Winner: {result.winner or 'none'} ({result.victory_type or '-'})",
                f"Elapsed: {duration:.1f}s",
            ]
        )
    )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run profile-driven MCP agents in an in-process 4X game."
    )
    parser.add_argument(
        "--preset",
        choices=sorted(_PRESETS.keys()),
        help="Use a preset player/profile combination.",
    )
    parser.add_argument(
        "--players",
        nargs="+",
        help="Player names (2–8).",
    )
    parser.add_argument(
        "--personalities",
        nargs="+",
        help="Profile per player, matched by position.",
    )
    parser.add_argument(
        "--max-turns",
        type=int,
        default=50,
        help="Game max_turns (score victory trigger).",
    )
    parser.add_argument(
        "--turn-cap",
        type=int,
        default=None,
        help="Cap orchestrator iterations (independent of game max_turns).",
    )
    parser.add_argument(
        "--list-profiles",
        action="store_true",
        help="List available profile names and exit.",
    )
    parser.add_argument(
        "--auto-confirm",
        action="store_true",
        help="Accepted for backwards compatibility; this runner is non-interactive.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)

    if args.list_profiles:
        for name in list_profiles():
            console.print(f"• {name}")
        return

    if args.preset:
        preset = _PRESETS[args.preset]
        players = list(preset["players"])  # type: ignore[arg-type]
        personalities = dict(preset["personalities"])  # type: ignore[arg-type]
        max_turns = int(preset.get("max_turns", args.max_turns))  # type: ignore[arg-type]
    else:
        players = args.players or ["Alice", "Bob"]
        if args.personalities:
            if len(args.personalities) != len(players):
                console.print(
                    "[red]Number of --personalities must match --players[/red]"
                )
                sys.exit(2)
            personalities = dict(zip(players, args.personalities))
        else:
            personalities = {p: "balanced" for p in players}
        max_turns = args.max_turns

    asyncio.run(_run(players, personalities, max_turns, args.turn_cap))


if __name__ == "__main__":
    main()
