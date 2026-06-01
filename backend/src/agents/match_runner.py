"""Autonomous match runner — plays LLM-vs-LLM games against the LIVE server.

Connects to the live Parley MCP server, repeatedly creates agent-vs-agent
games (varying which model holds each seat, plus profile/seed/map), runs each
to completion with the LLM planner, and records who won. This is what grows
the public "games played" / "agents in the field" counts.

Resilience and cost control are first-class:

- Each game runs on its own MCP session; one game crashing never kills the loop.
- ``concurrency`` bounds simultaneous games; ``max_games`` bounds the total.
- ``per_game_timeout_s`` stops a wedged game; ``max_turn_cap`` bounds turns.
- A ``kill_switch_path`` file, if present, stops the loop after in-flight games.
- Each model endpoint carries a ``max_tokens`` budget enforced by the planner.

Run locally::

    uv run python -m backend.src.agents.run_live_matches --max-games 5

…or wrap :func:`run_forever` in a Modal scheduled/long-lived function.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .llm_planner import ReasoningSink, make_llm_planner
from .mcp_client import OfficialStreamableHTTPMCPClient
from .orchestrator import MCPGameOrchestrator, create_game
from .profiles import get_profile

logger = logging.getLogger(__name__)

DEFAULT_MCP_URL = os.getenv("PARLEY_MCP_URL", "https://mcp.parley.quest/")
_PROFILE_POOL = ("aggressive", "economic", "explorer", "balanced")
# write_turn_notes caps notes at 4,000 chars (SCRATCHPAD_MAX_CHARS); stay under.
_TURN_NOTE_MAX_CHARS = 4000


def _default_map_templates() -> list[str | None]:
    """Default map-template pool — ``None`` means the server's default map."""
    return [None]


@dataclass(frozen=True)
class ModelEndpoint:
    """A Modal-hosted vLLM model the runner can seat into a game."""

    label: str
    base_url: str
    model: str
    api_key: str = "not-needed"
    max_tokens: int = 1024
    timeout_s: float = 45.0


@dataclass
class MatchConfig:
    """Configuration for an autonomous run."""

    endpoints: list[ModelEndpoint]
    mcp_url: str = DEFAULT_MCP_URL
    players_per_game: int = 2
    max_turns: int = 60
    max_turn_cap: int | None = 60
    map_templates: list[str | None] = field(default_factory=_default_map_templates)
    concurrency: int = 2
    max_games: int = 10
    per_game_timeout_s: float = 1800.0
    kill_switch_path: str | None = None
    results_path: str | None = "logs/match_results.jsonl"
    reasoning_path: str | None = "logs/reasoning.jsonl"
    # Mirror each turn's reasoning into the game's turn notes (visible in-product
    # via the API / live site). Best-effort and bounded by turn_notes_timeout_s.
    write_turn_notes: bool = True
    turn_notes_timeout_s: float = 15.0
    schedule_seed: int = 12345


@dataclass
class GameOutcome:
    """Result of a single autonomous game."""

    game_id: str | None
    seats: dict[str, str]  # player_id -> model label
    winner: str | None
    winner_model: str | None
    final_turn: int
    status: str
    error: str | None = None


def _seat_assignment(
    cfg: MatchConfig, rng: random.Random, index: int
) -> tuple[list[str], dict[str, ModelEndpoint], dict[str, str]]:
    """Pick players, their model endpoints, and their profiles for one game.

    Player ids are unique within the game and encode the seat + model so the
    results log (and the live UI) make the matchup legible.
    """
    chosen = [rng.choice(cfg.endpoints) for _ in range(cfg.players_per_game)]
    players: list[str] = []
    endpoints: dict[str, ModelEndpoint] = {}
    profiles: dict[str, str] = {}
    for slot, ep in enumerate(chosen):
        pid = f"{ep.label}-s{slot}-g{index}"
        players.append(pid)
        endpoints[pid] = ep
        profiles[pid] = rng.choice(_PROFILE_POOL)
    return players, endpoints, profiles


async def run_one_game(cfg: MatchConfig, rng_seed: int, index: int) -> GameOutcome:
    """Create and play one LLM-vs-LLM game to completion on the live server."""
    rng = random.Random(rng_seed)
    players, endpoints, profile_names = _seat_assignment(cfg, rng, index)
    seats = {pid: ep.label for pid, ep in endpoints.items()}
    game_seed = rng.randint(1, 2**31 - 1)
    map_template = rng.choice(cfg.map_templates)

    try:
        async with OfficialStreamableHTTPMCPClient(cfg.mcp_url) as client:
            game = await create_game(
                client,
                players,
                seed=game_seed,
                max_turns=cfg.max_turns,
                map_template=map_template,
            )

            def _make_sink(pid: str, model_label: str, seat_key: str) -> ReasoningSink:
                async def _sink(
                    player_id: str,
                    turn_number: int,
                    reasoning: str,
                    raw: str,
                    actions: list[dict],
                ) -> None:
                    # Durable, full-fidelity log.
                    _record_reasoning(
                        cfg,
                        {
                            "game_id": game.game_id,
                            "player_id": pid,
                            "model": model_label,
                            "profile": profile_names.get(pid),
                            "turn": turn_number,
                            "reasoning": reasoning,
                            "actions": actions,
                        },
                    )
                    # Also surface it in-product as this seat's turn notes, so
                    # the reasoning shows up on the live game. Best-effort and
                    # bounded — never let it stall or break the turn loop.
                    if not (cfg.write_turn_notes and reasoning):
                        return
                    note = f"[{model_label}] {reasoning}"[:_TURN_NOTE_MAX_CHARS]
                    try:
                        await asyncio.wait_for(
                            client.call_tool(
                                "write_turn_notes",
                                {"api_key": seat_key, "notes": note},
                            ),
                            timeout=cfg.turn_notes_timeout_s,
                        )
                    except Exception:  # noqa: BLE001 — best-effort persistence
                        logger.warning(
                            "write_turn_notes failed for %s turn %s",
                            pid,
                            turn_number,
                            exc_info=True,
                        )

                return _sink

            planners = {
                pid: make_llm_planner(
                    base_url=ep.base_url,
                    model=ep.model,
                    api_key=ep.api_key,
                    max_tokens=ep.max_tokens,
                    timeout_s=ep.timeout_s,
                    enable_thinking=True,
                    on_reasoning=_make_sink(pid, ep.label, game.api_keys[pid]),
                )
                for pid, ep in endpoints.items()
            }
            profiles = {pid: get_profile(name) for pid, name in profile_names.items()}
            orch = MCPGameOrchestrator(
                client, game, profiles=profiles, planners=planners
            )
            result = await asyncio.wait_for(
                orch.run(max_turn_cap=cfg.max_turn_cap),
                timeout=cfg.per_game_timeout_s,
            )
            winner = result.winner
            outcome = GameOutcome(
                game_id=game.game_id,
                seats=seats,
                winner=winner,
                winner_model=seats.get(winner) if winner else None,
                final_turn=result.final_turn,
                status=result.status,
            )
            logger.info(
                "game %s done: status=%s winner=%s (%s) turn=%s",
                game.game_id,
                outcome.status,
                outcome.winner,
                outcome.winner_model,
                outcome.final_turn,
            )
            return outcome
    except Exception as exc:  # noqa: BLE001 — one game must never kill the loop
        logger.exception("game #%s failed", index)
        return GameOutcome(
            game_id=None,
            seats=seats,
            winner=None,
            winner_model=None,
            final_turn=0,
            status="error",
            error=str(exc),
        )


def _record(cfg: MatchConfig, outcome: GameOutcome) -> None:
    if not cfg.results_path:
        return
    path = Path(cfg.results_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(outcome.__dict__) + "\n")


def _record_reasoning(cfg: MatchConfig, record: dict) -> None:
    """Append one turn's reasoning trace to the reasoning log.

    Every seat reasons and we keep every trace, so this is the durable store of
    *why* each model made its moves. Best-effort: never raise into the turn loop.
    """
    if not cfg.reasoning_path:
        return
    path = Path(cfg.reasoning_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")


def _kill_switch_tripped(cfg: MatchConfig) -> bool:
    return bool(cfg.kill_switch_path and Path(cfg.kill_switch_path).exists())


async def run_forever(cfg: MatchConfig) -> list[GameOutcome]:
    """Run up to ``cfg.max_games`` games, ``cfg.concurrency`` at a time."""
    if not cfg.endpoints:
        raise ValueError("MatchConfig.endpoints is empty — nothing to play")

    sem = asyncio.Semaphore(cfg.concurrency)
    outcomes: list[GameOutcome] = []
    sched = random.Random(cfg.schedule_seed)

    async def _guarded(index: int) -> None:
        async with sem:
            if _kill_switch_tripped(cfg):
                logger.warning("kill switch present — skipping game #%s", index)
                return
            outcome = await run_one_game(cfg, sched.randint(1, 2**31 - 1), index)
            outcomes.append(outcome)
            _record(cfg, outcome)

    tasks = [asyncio.create_task(_guarded(i)) for i in range(cfg.max_games)]
    await asyncio.gather(*tasks)

    wins: Counter[str] = Counter(
        o.winner_model for o in outcomes if o.winner_model is not None
    )
    completed = sum(1 for o in outcomes if o.status == "ended")
    errored = sum(1 for o in outcomes if o.status == "error")
    logger.info(
        "run complete: %s games, %s ended, %s errored, win matrix=%s",
        len(outcomes),
        completed,
        errored,
        dict(wins),
    )
    return outcomes
