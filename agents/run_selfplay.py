#!/usr/bin/env python3
"""
CLI entry point for self-play testing.

Runs N profiled agents through a bounded game via the in-process MCP
client, validates state invariants after every turn, and prints a
reproduction report if anything fails. Exit code is non-zero when the
run is not ``ok`` — which makes this safe to wire up as a CI smoke
check.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Make the repo root importable.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from backend.src.agents import (  # noqa: E402
    InProcessMCPClient,
    format_failure_report,
    list_profiles,
    run_self_play,
)
from backend.src.mcp_server.server import create_mcp_server  # noqa: E402


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run a self-play game with profiled MCP agents and validate "
            "state invariants after every turn."
        )
    )
    parser.add_argument(
        "--players",
        nargs="+",
        default=["alice", "bob"],
        help="Player names (2–8). Default: alice bob.",
    )
    parser.add_argument(
        "--profiles",
        nargs="+",
        default=None,
        help=(
            "Profile per player, matched by position. Defaults to balanced "
            f"for every slot. Available: {', '.join(list_profiles())}."
        ),
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--max-turns",
        type=int,
        default=50,
        help="Game max_turns (score victory trigger).",
    )
    parser.add_argument(
        "--turn-cap",
        type=int,
        default=20,
        help="Cap orchestrator iterations (independent of game max_turns).",
    )
    parser.add_argument("--map-width", type=int, default=12)
    parser.add_argument("--map-height", type=int, default=12)
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print the full reproduction report even on success.",
    )
    return parser.parse_args(argv)


async def _run(args: argparse.Namespace) -> int:
    profiles: dict[str, str] = {}
    if args.profiles:
        if len(args.profiles) != len(args.players):
            print("error: --profiles length must match --players", file=sys.stderr)
            return 2
        profiles = dict(zip(args.players, args.profiles))

    mcp = create_mcp_server()
    client = InProcessMCPClient(mcp)

    result = await run_self_play(
        client,
        args.players,
        profiles=profiles or None,
        seed=args.seed,
        max_turns=args.max_turns,
        max_turn_cap=args.turn_cap,
        map_width=args.map_width,
        map_height=args.map_height,
    )

    header = [
        f"game_id={result.game_id}",
        f"seed={result.seed}",
        f"players={result.players}",
        f"profiles={result.profiles}",
        f"final_turn={result.final_turn}",
        f"status={result.status}",
        f"winner={result.winner} ({result.victory_type})",
        f"scores={result.scores}",
        f"ok={result.ok}",
    ]
    print("\n".join(header))

    if not result.ok:
        print()
        print(format_failure_report(result))
        return 1
    if args.verbose:
        print()
        print(format_failure_report(result))
    return 0


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    sys.exit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
