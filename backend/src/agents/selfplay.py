"""
Phase 7 self-play driver.

Drives two or more ``MCPAgent`` instances through a complete game via an
``MCPClient`` while validating that the game engine never produces an
inconsistent state. The module exposes:

- ``check_state_invariants`` — pure function over a ``GameState`` (raw,
  unredacted) that returns a list of invariant-violation messages. The
  invariants are the contract the engine is meant to maintain between
  turns, so any non-empty return is a bug.
- ``run_self_play`` — creates a game through MCP, assigns profiles to
  players, runs turns to completion (or a turn cap), validates
  invariants after each turn resolution, and returns a
  ``SelfPlayResult`` with traces, consistency errors, and the seed +
  action log for reproduction.

Design decisions:

- Consistency checks read the *raw* game state from the database via
  ``GameRepository.get_game``. The MCP layer always returns fog-of-war
  redacted state, which is the wrong view for invariant checks — we
  need to see every player's stockpile, every unit, every tile.
- Failures don't raise; they're collected in ``SelfPlayResult``. That
  lets tests assert on the full list and lets the CLI surface every
  failing invariant at once rather than just the first one.
- The seed + per-turn submitted actions are captured so a failure is
  reproducible: same seed + same action sequence = identical game.
  This is the single biggest payoff of the engine being deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..database.connection import async_session_factory
from ..database.repository import GameRepository
from ..game.models import GameState, ResourceBag, Terrain
from .agent_runtime import MCPAgent, TurnTrace
from .mcp_client import MCPClient
from .orchestrator import OrchestratedGame, create_game
from .profiles import BALANCED, AgentProfile, get_profile


@dataclass
class TurnActionLog:
    """One player's submitted actions for one turn — for reproduction."""

    turn: int
    player_id: str
    profile_name: str
    actions: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class SelfPlayResult:
    """Outcome of a self-play run, complete enough to replay on failure."""

    game_id: str
    seed: int
    players: list[str]
    profiles: dict[str, str]
    final_turn: int
    status: str
    winner: str | None
    victory_type: str | None
    scores: dict[str, int]
    traces: list[TurnTrace] = field(default_factory=list)
    action_log: list[TurnActionLog] = field(default_factory=list)
    consistency_errors: list[str] = field(default_factory=list)
    hit_turn_cap: bool = False

    @property
    def ok(self) -> bool:
        """True when no invariants fired and no tool returned an error."""
        if self.consistency_errors:
            return False
        return all(not t.errors for t in self.traces)


def check_state_invariants(state: GameState) -> list[str]:
    """Return a list of human-readable invariant violations for ``state``.

    A healthy state returns an empty list. This is the contract every
    turn-resolution must maintain, so any non-empty result from this
    function is a rules-engine bug.
    """
    errors: list[str] = []

    # 1. Stockpiles never negative.
    for player_id, pile in state.stockpiles.items():
        if not isinstance(pile, ResourceBag):
            errors.append(
                f"stockpile for {player_id!r} is not a ResourceBag: {type(pile)!r}"
            )
            continue
        for field_name in ("food", "wood", "ore", "crystal"):
            value = getattr(pile, field_name)
            if value < 0:
                errors.append(
                    f"negative {field_name} stockpile for {player_id!r}: {value}"
                )

    # 2. No unit is on an impassable (water / mountain) tile.
    tiles_by_loc = {(t.loc.x, t.loc.y): t for t in state.tiles}
    for unit_id, unit in state.units.items():
        tile = tiles_by_loc.get((unit.loc.x, unit.loc.y))
        if tile is None:
            errors.append(
                f"unit {unit_id} at ({unit.loc.x},{unit.loc.y}) has no matching tile"
            )
            continue
        if tile.terrain in (Terrain.WATER, Terrain.MOUNTAIN):
            errors.append(
                f"unit {unit_id} ({unit.type}) is on impassable {tile.terrain} "
                f"tile at ({unit.loc.x},{unit.loc.y})"
            )

    # 3. Tile.unit_ids references match real units at that location,
    #    and the stack obeys STACK_CAP.
    from ..game.models import STACK_CAP

    for tile in state.tiles:
        if len(tile.unit_ids) > STACK_CAP:
            errors.append(
                f"tile ({tile.loc.x},{tile.loc.y}) has {len(tile.unit_ids)} "
                f"units, exceeding STACK_CAP={STACK_CAP}"
            )
        for uid in tile.unit_ids:
            unit = state.units.get(uid)
            if unit is None:
                errors.append(
                    f"tile ({tile.loc.x},{tile.loc.y}) references nonexistent "
                    f"unit {uid}"
                )
                continue
            if unit.loc.x != tile.loc.x or unit.loc.y != tile.loc.y:
                errors.append(
                    f"tile ({tile.loc.x},{tile.loc.y}).unit_ids contains {uid} "
                    f"but unit is at ({unit.loc.x},{unit.loc.y})"
                )

    # 4. Tile.city_id references match a real city at that location.
    #    (A tile within a city's border owns the same city_id without being
    #    the city's own tile, so only check that the city exists — not the
    #    coordinate match.)
    for tile in state.tiles:
        if tile.city_id is None:
            continue
        if tile.city_id not in state.cities:
            errors.append(
                f"tile ({tile.loc.x},{tile.loc.y}) references nonexistent city "
                f"{tile.city_id}"
            )

    # 5. Cities have a tile under them and the tile's city_id matches.
    for city_id, city in state.cities.items():
        tile = tiles_by_loc.get((city.loc.x, city.loc.y))
        if tile is None:
            errors.append(
                f"city {city_id} at ({city.loc.x},{city.loc.y}) has no matching tile"
            )
            continue
        if tile.city_id != city_id:
            errors.append(
                f"city {city_id} at ({city.loc.x},{city.loc.y}) but tile.city_id="
                f"{tile.city_id}"
            )

    # 6. No eliminated player still owns cities or units.
    for player_id in state.eliminated_players:
        leftover_cities = [c.id for c in state.cities.values() if c.owner == player_id]
        leftover_units = [u.id for u in state.units.values() if u.owner == player_id]
        if leftover_cities:
            errors.append(
                f"eliminated player {player_id!r} still owns cities {leftover_cities}"
            )
        if leftover_units:
            errors.append(
                f"eliminated player {player_id!r} still owns units {leftover_units}"
            )

    return errors


async def _load_raw_state(session: AsyncSession, game_id: str) -> GameState | None:
    repo = GameRepository(session)
    game = await repo.get_game(game_id)
    if game is None or not game.state:
        return None
    return GameState.model_validate(game.state)


async def _game_status(client: MCPClient, game_id: str) -> dict[str, Any]:
    return await client.call_tool("get_game_info", {"game_id": game_id})


async def run_self_play(
    client: MCPClient,
    players: list[str],
    *,
    profiles: dict[str, str] | None = None,
    seed: int = 42,
    max_turns: int = 100,
    max_turn_cap: int | None = 20,
    map_width: int = 12,
    map_height: int = 12,
) -> SelfPlayResult:
    """Run a complete self-play game and validate invariants after every turn.

    Returns a ``SelfPlayResult`` that is sufficient to replay the game:
    the seed plus ``action_log`` can be replayed deterministically by
    feeding the same actions to the engine.
    """
    profile_map: dict[str, AgentProfile] = {}
    profile_names: dict[str, str] = {}
    for player in players:
        name = (profiles or {}).get(player, "balanced")
        profile_map[player] = get_profile(name)
        profile_names[player] = name

    game: OrchestratedGame = await create_game(
        client,
        players,
        seed=seed,
        max_turns=max_turns,
        map_width=map_width,
        map_height=map_height,
    )

    agents: dict[str, MCPAgent] = {
        player: MCPAgent(
            client,
            api_key=game.api_keys[player],
            profile=profile_map.get(player, BALANCED),
            player_id=player,
        )
        for player in game.players
    }

    traces: list[TurnTrace] = []
    action_log: list[TurnActionLog] = []
    consistency_errors: list[str] = []
    hit_cap = False
    turns_taken = 0
    last_validated_turn = -1

    while True:
        info = await _game_status(client, game.game_id)
        if "error" in info:
            consistency_errors.append(f"get_game_info failed: {info['error']}")
            break
        if info.get("status") == "ended":
            break
        if max_turn_cap is not None and turns_taken >= max_turn_cap:
            hit_cap = True
            break

        pre_turn = int(info.get("turn", 0))
        for player in game.players:
            trace = await agents[player].play_turn()
            traces.append(trace)
            if not trace.skipped:
                action_log.append(
                    TurnActionLog(
                        turn=trace.turn,
                        player_id=trace.player_id or player,
                        profile_name=trace.profile_name,
                        actions=list(trace.submitted_actions),
                    )
                )
            if trace.submit_result.get("turn_resolved"):
                break

        # Check invariants once the turn has actually advanced, so we
        # validate the state the engine produced rather than whatever
        # intermediate shape exists mid-turn.
        post_info = await _game_status(client, game.game_id)
        current_turn = int(post_info.get("turn", pre_turn))
        if current_turn > last_validated_turn and current_turn > pre_turn:
            async with async_session_factory() as session:
                state = await _load_raw_state(session, game.game_id)
            if state is None:
                consistency_errors.append(
                    f"turn {current_turn}: could not load raw state for validation"
                )
            else:
                turn_errors = check_state_invariants(state)
                for msg in turn_errors:
                    consistency_errors.append(f"turn {current_turn}: {msg}")
            last_validated_turn = current_turn

        turns_taken += 1

    final_info = await _game_status(client, game.game_id)
    return SelfPlayResult(
        game_id=game.game_id,
        seed=game.seed,
        players=list(game.players),
        profiles=profile_names,
        final_turn=int(final_info.get("turn", 0)),
        status=str(final_info.get("status", "unknown")),
        winner=final_info.get("winner"),
        victory_type=final_info.get("victory_type"),
        scores=dict(final_info.get("scores") or {}),
        traces=traces,
        action_log=action_log,
        consistency_errors=consistency_errors,
        hit_turn_cap=hit_cap,
    )


def format_failure_report(result: SelfPlayResult) -> str:
    """Produce a human-readable reproduction report for a failed run."""
    lines = [
        f"Self-play game {result.game_id} FAILED",
        f"seed={result.seed}  players={result.players}  profiles={result.profiles}",
        f"status={result.status}  turn={result.final_turn}",
        "",
        "Consistency errors:",
    ]
    if result.consistency_errors:
        lines.extend(f"  - {e}" for e in result.consistency_errors)
    else:
        lines.append("  (none)")

    trace_errors = [(t.player_id, t.turn, t.errors) for t in result.traces if t.errors]
    if trace_errors:
        lines.append("")
        lines.append("Tool errors by trace:")
        for player_id, turn, errs in trace_errors:
            for err in errs:
                lines.append(f"  - turn {turn} player {player_id}: {err}")

    lines.append("")
    lines.append(f"Action log ({len(result.action_log)} entries):")
    for entry in result.action_log:
        lines.append(
            f"  turn {entry.turn} {entry.player_id} ({entry.profile_name}): "
            f"{entry.actions}"
        )
    return "\n".join(lines)


__all__ = [
    "SelfPlayResult",
    "TurnActionLog",
    "check_state_invariants",
    "format_failure_report",
    "run_self_play",
]
