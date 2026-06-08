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
DEFAULT_API_URL = os.getenv("PARLEY_API_URL", "https://api.parley.quest/api/v1")
_PROFILE_POOL = ("aggressive", "economic", "explorer", "balanced")
# write_turn_notes caps notes at 4,000 chars (SCRATCHPAD_MAX_CHARS); stay under.
_TURN_NOTE_MAX_CHARS = 4000
# Cap the reasoning we mirror into prompt_logs (research log; column is text).
_PROMPT_LOG_MAX_CHARS = 20000


def _default_map_templates() -> list[str | None]:
    """Default map-template pool.

    Structured, balanced templates rather than the legacy fully-randomised noise
    map (``random`` / ``None``), which produces unstructured, poorly-balanced
    starts. These three keep all players on a shared landmass (good for a
    territorial 4X) while varying the terrain: a solid continent, a continent
    with inland lakes, and a continent split by a river. The naval-heavy
    ``islands`` / ``archipelago`` templates are left out — agents handle land
    expansion far better than water crossings.
    """
    return ["continent", "lakes", "river"]


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
    # When True, agents read inbound messages and may SEND_MESSAGE each turn —
    # the active-chat condition for studying how chat skews behaviour.
    chat_enabled: bool = False
    # When True, each seat in a game gets a DISTINCT model (sampled without
    # replacement) where the endpoint pool is large enough — so a 2-player game
    # with a Qwen + a Magistral endpoint is guaranteed to be Qwen-vs-Magistral
    # rather than a random pairing that's sometimes mirror-matched.
    distinct_models: bool = False
    # Mirror each turn's reasoning into the prompt_logs table (REST POST
    # /prompts) so it shows in the replay/observe "Prompts" tab in the UI.
    log_prompts: bool = True
    api_url: str = DEFAULT_API_URL
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
    if cfg.distinct_models and len(cfg.endpoints) >= cfg.players_per_game:
        # One distinct model per seat (e.g. guarantee Qwen-vs-Magistral).
        chosen = rng.sample(cfg.endpoints, cfg.players_per_game)
    else:
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
                    # Nothing else to persist if the model produced no trace.
                    if not reasoning:
                        return
                    # Surface in-product as this seat's turn notes. Best-effort
                    # and bounded — never let it stall or break the turn loop.
                    if cfg.write_turn_notes:
                        note = f"[{model_label}] {reasoning}"[:_TURN_NOTE_MAX_CHARS]
                        try:
                            await asyncio.wait_for(
                                client.call_tool(
                                    "write_turn_notes",
                                    {"api_key": seat_key, "notes": note},
                                ),
                                timeout=cfg.turn_notes_timeout_s,
                            )
                        except Exception:  # noqa: BLE001 — best-effort
                            logger.warning(
                                "write_turn_notes failed for %s turn %s",
                                pid,
                                turn_number,
                                exc_info=True,
                            )
                    # Mirror into prompt_logs so it shows in the replay UI. Wrap
                    # the trace in <think>…</think> and follow with the actions:
                    # the replay accordion routes the think block to its
                    # REASONING section and the rest to ACTION.
                    if cfg.log_prompts:
                        action_text = json.dumps(actions) if actions else "[]  (pass)"
                        response_text = f"<think>\n{reasoning}\n</think>\n{action_text}"
                        try:
                            await _post_prompt_log(
                                cfg,
                                api_key=seat_key,
                                game_id=game.game_id,
                                player=pid,
                                turn_number=turn_number,
                                model=model_label,
                                prompt=f"turn {turn_number}",
                                response=response_text,
                                tokens_out=len(reasoning) // 4,
                            )
                        except Exception:  # noqa: BLE001 — best-effort
                            logger.warning(
                                "prompt-log POST failed for %s turn %s",
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
                    chat_enabled=cfg.chat_enabled,
                )
                for pid, ep in endpoints.items()
            }
            profiles = {pid: get_profile(name) for pid, name in profile_names.items()}
            orch = MCPGameOrchestrator(
                client,
                game,
                profiles=profiles,
                planners=planners,
                chat_enabled=cfg.chat_enabled,
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


async def _post_prompt_log(
    cfg: MatchConfig,
    *,
    api_key: str,
    game_id: str,
    player: str,
    turn_number: int,
    model: str,
    prompt: str,
    response: str,
    tokens_out: int,
) -> None:
    """Write one turn's reasoning to prompt_logs via the REST API.

    Authenticated with the seat's per-game API key (the same key works for REST
    Bearer auth); ``game_id`` must match the key. ``turn_number`` stamps the
    entry so it shows under the right turn in the replay/observe "Prompts" tab.
    Best-effort — caller swallows errors.
    """
    import httpx

    body = {
        "player": player,
        "prompt": prompt[:4000],
        "response": response[:_PROMPT_LOG_MAX_CHARS],
        "tokens_in": 0,
        "tokens_out": tokens_out,
        "latency_ms": 0,
    }
    async with httpx.AsyncClient(timeout=15.0) as http:
        resp = await http.post(
            f"{cfg.api_url}/prompts",
            params={"game_id": game_id, "turn_number": turn_number, "llm_model": model},
            headers={"Authorization": f"Bearer {api_key}"},
            json=body,
        )
        resp.raise_for_status()


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
