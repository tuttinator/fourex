#!/usr/bin/env python3
"""
Spectated agent demo: two profile-driven agents on different providers.

Runs a 2-player AI-vs-AI game end-to-end through the public MCP surface
so a signed-in researcher can drop straight into the existing
``ObservationView`` and watch it play. Fails fast if the providers the
demo advertises aren't reachable — the whole point is that the operator
finds out about a missing ``OPENAI_API_KEY`` before the orchestrator
minted a game, not mid-turn.

Provider validation is deliberately up-front: a GET to
``{LLM_STUDIO_URL}/models`` and a presence check on ``OPENAI_API_KEY``.
The actual agent turn loop still uses the deterministic heuristic
planner today — Phase 6 wires the LLM providers into turn execution.
This script already records which player is *assigned* to which
provider so the observe log stays meaningful when Phase 6 lands.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

import httpx
from rich.console import Console
from rich.panel import Panel

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from backend.src.agents import InProcessMCPClient  # noqa: E402 — after path setup
from backend.src.agents.agent_runtime import TelemetryConfig  # noqa: E402
from backend.src.agents.orchestrator import (  # noqa: E402
    MCPGameOrchestrator,
    create_game,
)
from backend.src.agents.profiles import get_profile  # noqa: E402
from backend.src.agents.telemetry import (  # noqa: E402
    ContextWindowConfig,
    TelemetryWriter,
)
from backend.src.mcp_server.server import create_mcp_server  # noqa: E402

console = Console()


DEFAULT_LLM_STUDIO_URL = "http://localhost:1234/v1"
DEFAULT_OBSERVE_BASE = "http://localhost:3000"


def _check_llm_studio(base_url: str, timeout: float = 5.0) -> tuple[bool, str]:
    """Return (reachable, message) for the configured LLM Studio endpoint."""
    try:
        response = httpx.get(f"{base_url.rstrip('/')}/models", timeout=timeout)
    except httpx.HTTPError as exc:
        return False, f"connection failed: {exc}"
    if response.status_code != 200:
        return False, f"HTTP {response.status_code} from /models"
    return True, "reachable"


def _preflight(llm_studio_url: str, openai_api_key: str | None) -> None:
    """Exit with a clear message if either provider is unconfigured.

    We intentionally do NOT call OpenAI to validate the key — that would
    cost a round-trip on every demo run. Presence of the env var is the
    contract; an invalid key will surface on the first real completion.
    """
    problems: list[str] = []

    ok, detail = _check_llm_studio(llm_studio_url)
    if not ok:
        problems.append(
            f"LLM Studio unreachable at {llm_studio_url} ({detail}).\n"
            "  Start LLM Studio locally, or set LLM_STUDIO_URL to a working endpoint."
        )

    if not openai_api_key:
        problems.append(
            "OPENAI_API_KEY is not set.\n"
            "  Export OPENAI_API_KEY before running mise run observe-demo."
        )

    if problems:
        console.print("[red]observe-demo preflight failed:[/red]")
        for p in problems:
            console.print(f"  • {p}")
        sys.exit(2)


def _build_llm_summariser(provider: str, model: str, llm_studio_url: str):
    """Return an async summariser that calls the named provider, or
    ``None`` if that provider isn't configured. Failures fall through so
    compaction can still proceed with a canned fallback."""

    async def _summarise(joined: str, first: int, last: int) -> str:
        try:
            # Lazy import so the demo shim boots without the agents/src
            # package on the Python path during unit tests.
            from agents.src.llm_providers import (  # type: ignore[import-not-found]
                LLMStudioProvider,
                OpenAIProvider,
            )
        except Exception:
            return (
                f"turns {first}-{last}: (llm provider unavailable — canned summary)"
            )

        messages = [
            {
                "role": "system",
                "content": (
                    "You are an agent summarising your own recent 4X game turns "
                    "so you can keep playing under a tight context budget. "
                    "Return 2-3 sentences naming what happened and why it matters."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Summarise your turns {first}-{last}:\n\n{joined}"
                ),
            },
        ]
        try:
            if provider == "openai":
                provider_instance = OpenAIProvider(model=model)
            else:
                provider_instance = LLMStudioProvider(
                    model=model, base_url=llm_studio_url
                )
            resp = await provider_instance.generate(messages, max_tokens=200)
            return resp.content or f"turns {first}-{last}: (empty summary)"
        except Exception as exc:  # noqa: BLE001 — degraded-but-running path
            return f"turns {first}-{last}: (summariser error: {exc})"

    return _summarise


async def _run(
    *,
    seed: int,
    max_turns: int,
    max_turn_cap: int | None,
    map_width: int,
    map_height: int,
    observe_base: str,
    llm_studio_url: str,
    llm_studio_model: str,
    openai_model: str,
    enable_telemetry: bool,
    telemetry_dir: str,
) -> None:
    player_a = "Studio"
    player_b = "OpenAI"
    players = [player_a, player_b]
    profiles = {
        player_a: get_profile("balanced"),
        player_b: get_profile("aggressive"),
    }

    mcp = create_mcp_server()
    client = InProcessMCPClient(mcp)

    console.print(
        Panel(
            "\n".join(
                [
                    f"Player A ({player_a}): LLM Studio → {llm_studio_model} @ {llm_studio_url}",
                    f"Player B ({player_b}): OpenAI → {openai_model}",
                    f"Map: {map_width}×{map_height}   Seed: {seed}   Max turns: {max_turns}",
                ]
            ),
            title="observe-demo",
            border_style="blue",
        )
    )

    game = await create_game(
        client,
        players,
        seed=seed,
        max_turns=max_turns,
        map_width=map_width,
        map_height=map_height,
    )

    lobby_url = f"{observe_base.rstrip('/')}/games/{game.game_id}"
    observe_url = f"{observe_base.rstrip('/')}/games/{game.game_id}/observe"
    console.print()
    console.print(f"[bold green]Game created:[/bold green] {game.game_id}")
    console.print(f"  Lobby:   {lobby_url}")
    console.print(f"  Observe: {observe_url}")
    console.print("[dim]Open the observe URL in a signed-in browser session.[/dim]")
    console.print()

    telemetry_map: dict[str, TelemetryConfig] = {}
    writers: list[TelemetryWriter] = []
    if enable_telemetry:
        ctx = ContextWindowConfig.from_env()
        studio_writer = TelemetryWriter(
            game_id=game.game_id, base_dir=Path(telemetry_dir) / player_a
        )
        openai_writer = TelemetryWriter(
            game_id=game.game_id, base_dir=Path(telemetry_dir) / player_b
        )
        writers.extend([studio_writer, openai_writer])
        telemetry_map[player_a] = TelemetryConfig(
            writer=studio_writer,
            provider="llm_studio",
            model=llm_studio_model,
            context=ctx,
            summariser=_build_llm_summariser(
                "llm_studio", llm_studio_model, llm_studio_url
            ),
            game_id=game.game_id,
        )
        telemetry_map[player_b] = TelemetryConfig(
            writer=openai_writer,
            provider="openai",
            model=openai_model,
            context=ctx,
            summariser=_build_llm_summariser(
                "openai", openai_model, llm_studio_url
            ),
            game_id=game.game_id,
        )
        console.print(
            f"[dim]Telemetry → {studio_writer.path} and {openai_writer.path}[/dim]"
        )

    orch = MCPGameOrchestrator(
        client, game, profiles=profiles, telemetry=telemetry_map or None
    )

    console.print("[bold]Starting turn loop…[/bold]")
    started = time.time()

    async def _run_with_progress() -> None:
        turns_printed = 0
        task = asyncio.create_task(orch.run(max_turn_cap=max_turn_cap))
        while not task.done():
            try:
                info = await client.call_tool(
                    "get_game_info", {"game_id": game.game_id}
                )
            except Exception:
                info = {}
            turn = int(info.get("turn", 0)) if isinstance(info, dict) else 0
            if turn > turns_printed:
                console.print(
                    f"  turn {turn} — status={info.get('status', '?')}"  # type: ignore[union-attr]
                )
                turns_printed = turn
            await asyncio.sleep(1.0)
        result = await task
        duration = time.time() - started
        console.print()
        console.print(
            Panel(
                "\n".join(
                    [
                        f"Final turn: {result.final_turn}",
                        f"Status: {result.status}",
                        f"Winner: {result.winner or 'none'} ({result.victory_type or '-'})",
                        f"Scores: {result.scores}",
                        f"Elapsed: {duration:.1f}s",
                    ]
                ),
                title=f"Game {result.game_id} ended",
                border_style="green",
            )
        )

    try:
        await _run_with_progress()
    finally:
        for writer in writers:
            writer.close()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run a spectated 2-player AI-vs-AI demo game. Prints the observe URL "
            "before the first turn so a signed-in researcher can watch in the browser."
        )
    )
    parser.add_argument("--seed", type=int, default=42, help="Deterministic map seed.")
    parser.add_argument(
        "--max-turns", type=int, default=60, help="Score-victory max turns."
    )
    parser.add_argument(
        "--turn-cap",
        type=int,
        default=None,
        help="Cap orchestrator iterations (independent of game max_turns).",
    )
    parser.add_argument("--map-width", type=int, default=20)
    parser.add_argument("--map-height", type=int, default=20)
    parser.add_argument(
        "--observe-base",
        default=os.environ.get("OBSERVE_BASE_URL", DEFAULT_OBSERVE_BASE),
        help="Base URL of the frontend (default http://localhost:3000).",
    )
    parser.add_argument(
        "--skip-preflight",
        action="store_true",
        help="Skip the LLM Studio / OpenAI reachability check (useful for CI).",
    )
    parser.add_argument(
        "--no-telemetry",
        action="store_true",
        help=(
            "Disable per-turn JSONL telemetry and compaction. Default: enabled. "
            "Logs land under $AGENT_TELEMETRY_DIR (default ``logs/``)."
        ),
    )
    parser.add_argument(
        "--telemetry-dir",
        default=os.environ.get("AGENT_TELEMETRY_DIR", "logs"),
        help="Directory for per-player JSONL telemetry (default ``logs/``).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)

    llm_studio_url = os.environ.get("LLM_STUDIO_URL", DEFAULT_LLM_STUDIO_URL)
    llm_studio_model = os.environ.get("LLM_STUDIO_MODEL", "qwen/qwen3-32b")
    openai_api_key = os.environ.get("OPENAI_API_KEY")
    openai_model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

    if not args.skip_preflight:
        _preflight(llm_studio_url, openai_api_key)

    asyncio.run(
        _run(
            seed=args.seed,
            max_turns=args.max_turns,
            max_turn_cap=args.turn_cap,
            map_width=args.map_width,
            map_height=args.map_height,
            observe_base=args.observe_base,
            llm_studio_url=llm_studio_url,
            llm_studio_model=llm_studio_model,
            openai_model=openai_model,
            enable_telemetry=not args.no_telemetry,
            telemetry_dir=args.telemetry_dir,
        )
    )


if __name__ == "__main__":
    main()
