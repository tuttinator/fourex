"""
MCP-connected agent orchestrator.

Creates a game through MCP, spawns one ``MCPAgent`` per player, and runs
turn loops until the game ends or a turn cap is reached. No direct REST
calls anywhere — this is the reference integration point a human game
server or the self-play test suite both plug into.

Design notes:

- The orchestrator owns the ``MCPClient`` and shares it across every
  agent. This mirrors production: one MCP server, many agents.
- Turn submission is sequential. Concurrent submission would force us
  to reason about the turn-resolution race inside MCP, and the win
  wouldn't be worth it for what self-play needs.
- ``max_turn_cap`` is an independent stopper from the game's own
  ``max_turns``. Tests use it to cut a game short without changing the
  game's score-victory logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .agent_runtime import MCPAgent, TelemetryConfig, TurnTrace
from .mcp_client import MCPClient
from .profiles import BALANCED, AgentProfile, get_profile


@dataclass
class OrchestratedGame:
    """Snapshot of a freshly created orchestrator-managed game."""

    game_id: str
    players: list[str]
    api_keys: dict[str, str]
    seed: int
    max_turns: int
    map_size: dict[str, int] = field(default_factory=dict)


@dataclass
class GameRunResult:
    """Final outcome and per-turn trace for a full orchestrated run."""

    game_id: str
    players: list[str]
    final_turn: int
    status: str
    winner: str | None
    victory_type: str | None
    scores: dict[str, int]
    traces: list[TurnTrace]
    hit_turn_cap: bool = False


async def create_game(
    client: MCPClient,
    players: list[str],
    *,
    seed: int = 42,
    max_turns: int = 100,
    map_width: int = 20,
    map_height: int = 20,
    victory_conditions: list[str] | None = None,
    map_template: str | None = None,
) -> OrchestratedGame:
    """Create a new game via MCP and return the player API keys."""
    args: dict[str, Any] = {
        "players": players,
        "seed": seed,
        "max_turns": max_turns,
        "map_width": map_width,
        "map_height": map_height,
    }
    if victory_conditions is not None:
        args["victory_conditions"] = victory_conditions
    if map_template is not None:
        args["map_template"] = map_template
    resp = await client.call_tool("create_game", args)
    if "error" in resp:
        raise RuntimeError(f"create_game failed: {resp['error']}")
    return OrchestratedGame(
        game_id=str(resp["game_id"]),
        players=list(resp["players"]),
        api_keys=dict(resp["api_keys"]),
        seed=int(resp.get("seed", seed)),
        max_turns=int(resp.get("max_turns", max_turns)),
        map_size=dict(resp.get("map_size") or {}),
    )


class MCPGameOrchestrator:
    """Runs a full MCP-only game loop end-to-end."""

    def __init__(
        self,
        client: MCPClient,
        game: OrchestratedGame,
        profiles: dict[str, AgentProfile] | None = None,
        *,
        telemetry: dict[str, TelemetryConfig] | None = None,
    ):
        self._client = client
        self._game = game
        self._profiles = profiles or {p: BALANCED for p in game.players}
        self._agents: dict[str, MCPAgent] = {}
        for player in game.players:
            profile = self._profiles.get(player, BALANCED)
            self._agents[player] = MCPAgent(
                client,
                api_key=game.api_keys[player],
                profile=profile,
                player_id=player,
                telemetry=(telemetry or {}).get(player),
            )

    @property
    def game(self) -> OrchestratedGame:
        return self._game

    @property
    def agents(self) -> dict[str, MCPAgent]:
        return self._agents

    async def _game_status(self) -> dict[str, Any]:
        return await self._client.call_tool(
            "get_game_info", {"game_id": self._game.game_id}
        )

    async def run(self, *, max_turn_cap: int | None = None) -> GameRunResult:
        """Run turns until the game ends or max_turn_cap is reached."""
        traces: list[TurnTrace] = []
        hit_cap = False
        turns_taken = 0

        while True:
            info = await self._game_status()
            if "error" in info:
                raise RuntimeError(f"get_game_info failed: {info['error']}")
            status = str(info.get("status"))
            if status == "ended":
                break
            if max_turn_cap is not None and turns_taken >= max_turn_cap:
                hit_cap = True
                break

            for player in self._game.players:
                trace = await self._agents[player].play_turn()
                traces.append(trace)
                # If this submission resolved the turn, break early so we
                # re-check status before the next player tries again.
                if trace.submit_result.get("turn_resolved"):
                    break

            turns_taken += 1

        info = await self._game_status()
        return GameRunResult(
            game_id=self._game.game_id,
            players=list(self._game.players),
            final_turn=int(info.get("turn", 0)),
            status=str(info.get("status", "unknown")),
            winner=info.get("winner"),
            victory_type=info.get("victory_type"),
            scores=dict(info.get("scores") or {}),
            traces=traces,
            hit_turn_cap=hit_cap,
        )


async def run_orchestrated_game(
    client: MCPClient,
    players: list[str],
    personalities: dict[str, str] | None = None,
    *,
    seed: int = 42,
    max_turns: int = 100,
    max_turn_cap: int | None = None,
    map_width: int = 20,
    map_height: int = 20,
) -> GameRunResult:
    """End-to-end helper: create a game, wire up agents, run to completion."""
    game = await create_game(
        client,
        players,
        seed=seed,
        max_turns=max_turns,
        map_width=map_width,
        map_height=map_height,
    )
    profiles: dict[str, AgentProfile] = {}
    for player in players:
        name = (personalities or {}).get(player, "balanced")
        profiles[player] = get_profile(name)
    orch = MCPGameOrchestrator(client, game, profiles=profiles)
    return await orch.run(max_turn_cap=max_turn_cap)
