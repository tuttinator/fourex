"""
Phase 6 MCP-only agent runtime.

An ``MCPAgent`` is a thin orchestrator around an ``MCPClient`` plus an
``AgentProfile``. Every turn it runs the seven-step loop the PRD
mandates:

    1. observe   -> get_game_state + is_my_turn
    2. remember  -> read_strategic_goals, read_opponent_models,
                    read_turn_notes (in profile.memory_priorities order)
    3. analyse   -> each tool in profile.tool_priorities
    4. plan      -> heuristic planner (pluggable; LLM planner is the
                    future replacement implementing the same signature)
    5. validate  -> validate_actions (drop any the rules reject)
    6. submit    -> submit_actions
    7. memorise  -> write_strategic_goals, write_opponent_model,
                    write_turn_notes

There are no direct REST calls anywhere in this class or anywhere it
touches — everything flows through ``client.call_tool``. That is the
core invariant Phase 6 delivers: any transport (stdio, HTTP, in-process)
can back an agent, and a human using Goose plays against the exact same
tools an agent does.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from .mcp_client import MCPClient
from .planner import plan_actions
from .profiles import AgentProfile, MemoryKind

# Tool-name maps keep the runtime from growing a tangle of if/elif.
_MEMORY_READ_TOOLS: dict[MemoryKind, str] = {
    MemoryKind.STRATEGIC_GOALS: "read_strategic_goals",
    MemoryKind.OPPONENT_MODELS: "read_opponent_models",
    MemoryKind.TURN_NOTES: "read_turn_notes",
}

# Analysis tools that accept only ``api_key`` (plus optional args) and can
# be auto-called during the analyse step. Utility tools like
# ``calculate_distances`` need planner-provided coordinates and must not
# be called blindly here.
_AUTO_ANALYSIS_TOOLS: frozenset[str] = frozenset(
    {
        "analyze_territory",
        "evaluate_military_position",
        "find_resource_opportunities",
    }
)


PlannerFn = Callable[
    [AgentProfile, dict[str, Any], str, dict[str, dict[str, Any]] | None, int],
    list[dict[str, Any]],
]


@dataclass
class TurnTrace:
    """Everything that happened during one ``play_turn`` call.

    Used by tests, self-play replays, and the orchestrator. Treats tool
    calls as an append-only log — every observed call lands in
    ``tool_calls`` even when it returns an error, so failures are
    diagnosable from the trace alone.
    """

    turn: int = 0
    player_id: str = ""
    profile_name: str = ""
    tool_calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    analysis_results: dict[str, dict[str, Any]] = field(default_factory=dict)
    memory_reads: dict[str, dict[str, Any]] = field(default_factory=dict)
    memory_writes: list[str] = field(default_factory=list)
    proposed_actions: list[dict[str, Any]] = field(default_factory=list)
    submitted_actions: list[dict[str, Any]] = field(default_factory=list)
    validation_results: list[dict[str, Any]] = field(default_factory=list)
    submit_result: dict[str, Any] = field(default_factory=dict)
    skipped: bool = False
    errors: list[str] = field(default_factory=list)


def _build_opponent_model(
    state: dict[str, Any], player_id: str
) -> tuple[str, dict[str, Any]] | None:
    """Summarise the most salient opponent for the memory write.

    Picks the opponent with the most visible units — that's the one
    worth remembering this turn.
    """
    units = state.get("units") or {}
    by_owner: dict[str, list[dict[str, Any]]] = {}
    for unit in units.values():
        owner = unit.get("owner")
        if not owner or owner == player_id:
            continue
        by_owner.setdefault(owner, []).append(unit)
    if not by_owner:
        return None
    opponent_id, seen = max(by_owner.items(), key=lambda kv: len(kv[1]))
    unit_types = sorted({str(u.get("type", "")) for u in seen if u.get("type")})
    return opponent_id, {
        "visible_unit_count": len(seen),
        "unit_types_seen": unit_types,
        "stance": "unknown",
    }


def _build_turn_notes(
    state: dict[str, Any],
    player_id: str,
    analysis: dict[str, dict[str, Any]],
    submitted: list[dict[str, Any]],
) -> str:
    """Short textual summary for the turn-notes memory."""
    units = state.get("units") or {}
    cities = state.get("cities") or {}
    my_units = sum(1 for u in units.values() if u.get("owner") == player_id)
    my_cities = sum(1 for c in cities.values() if c.get("owner") == player_id)
    military = analysis.get("evaluate_military_position") or {}
    assessment = military.get("assessment") or ""
    types_submitted = sorted({a.get("type", "") for a in submitted})
    parts = [
        f"Units: {my_units}; Cities: {my_cities}",
        f"Actions: {', '.join(types_submitted) or 'none'}",
    ]
    if assessment:
        parts.append(f"Military: {assessment}")
    return " | ".join(parts)[:2000]


class MCPAgent:
    """Profile-driven agent that speaks only MCP.

    Parameters
    ----------
    client:
        Any ``MCPClient`` — the in-process adapter for tests, the HTTP
        adapter for remote play.
    api_key:
        The player API key, obtained from ``create_game`` or ``join_game``.
    profile:
        Drives tool call order, memory priorities, action biases, and
        thresholds.
    planner:
        Pluggable. Defaults to the heuristic planner so agents run
        without an LLM. Swapping in an LLM planner is the Phase-7+
        work; the signature is identical.
    """

    def __init__(
        self,
        client: MCPClient,
        api_key: str,
        profile: AgentProfile,
        *,
        player_id: str | None = None,
        planner: PlannerFn | None = None,
    ):
        self._client = client
        self._api_key = api_key
        self._profile = profile
        self._player_id = player_id
        self._planner: PlannerFn = planner or plan_actions

    @property
    def profile(self) -> AgentProfile:
        return self._profile

    @property
    def player_id(self) -> str | None:
        return self._player_id

    async def _call(
        self,
        trace: TurnTrace,
        name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        trace.tool_calls.append((name, arguments))
        try:
            result = await self._client.call_tool(name, arguments)
        except Exception as exc:  # noqa: BLE001 — boundary
            msg = f"{name}: {exc}"
            trace.errors.append(msg)
            return {"error": str(exc)}
        if isinstance(result, dict) and "error" in result:
            trace.errors.append(f"{name}: {result['error']}")
        return result

    async def play_turn(self) -> TurnTrace:
        """Run one full observe→memorise loop.

        Returns the trace either way — on error, the trace records what
        we managed to do before giving up.
        """
        trace = TurnTrace(profile_name=self._profile.name)

        # 1. Observe
        is_turn = await self._call(trace, "is_my_turn", {"api_key": self._api_key})
        if "error" in is_turn:
            return trace

        turn_number = int(is_turn.get("turn") or 0)
        trace.turn = turn_number
        if not is_turn.get("waiting_for_you"):
            trace.skipped = True
            return trace

        state_resp = await self._call(
            trace, "get_game_state", {"api_key": self._api_key}
        )
        if "error" in state_resp:
            return trace

        player_id = str(state_resp.get("player") or self._player_id or "")
        self._player_id = player_id
        trace.player_id = player_id
        state = state_resp.get("state") or {}

        # 2. Remember
        for kind in self._profile.memory_priorities:
            tool = _MEMORY_READ_TOOLS[kind]
            resp = await self._call(trace, tool, {"api_key": self._api_key})
            trace.memory_reads[kind.value] = resp

        # 3. Analyse
        for tool in self._profile.tool_priorities:
            if tool not in _AUTO_ANALYSIS_TOOLS:
                # Utility tools (e.g. calculate_distances) need planner-
                # provided arguments; skip them in the auto-analyse step.
                continue
            resp = await self._call(trace, tool, {"api_key": self._api_key})
            trace.analysis_results[tool] = resp

        # 4. Plan
        proposed = self._planner(
            self._profile,
            state,
            player_id,
            trace.analysis_results,
            turn_number,
        )
        trace.proposed_actions = list(proposed)

        # 5. Validate — drop any rejected actions so we don't tank the
        # whole submission on one bad plan item.
        validated: list[dict[str, Any]] = []
        if proposed:
            validate_resp = await self._call(
                trace,
                "validate_actions",
                {"api_key": self._api_key, "actions": proposed},
            )
            results = validate_resp.get("results") or []
            trace.validation_results = list(results)
            for action, result in zip(proposed, results):
                if result.get("valid"):
                    validated.append(action)

        trace.submitted_actions = validated

        # 6. Submit — empty list is fine (passes the turn).
        submit_resp = await self._call(
            trace,
            "submit_actions",
            {"api_key": self._api_key, "actions": validated},
        )
        trace.submit_result = submit_resp

        # 7. Memorise — in priority order.
        await self._memorise(trace, state, player_id, validated)

        return trace

    async def _memorise(
        self,
        trace: TurnTrace,
        state: dict[str, Any],
        player_id: str,
        submitted: list[dict[str, Any]],
    ) -> None:
        for kind in self._profile.memory_priorities:
            payload = self._build_memory_write(
                kind, state, player_id, trace.analysis_results, submitted
            )
            if payload is None:
                continue
            tool, args = payload
            await self._call(trace, tool, args)
            trace.memory_writes.append(kind.value)

    def _build_memory_write(
        self,
        kind: MemoryKind,
        state: dict[str, Any],
        player_id: str,
        analysis: dict[str, dict[str, Any]],
        submitted: list[dict[str, Any]],
    ) -> tuple[str, dict[str, Any]] | None:
        if kind is MemoryKind.STRATEGIC_GOALS:
            goals = [
                {
                    "goal": f"profile:{self._profile.name}",
                    "priority": 1,
                    "status": "active",
                }
            ]
            return (
                "write_strategic_goals",
                {"api_key": self._api_key, "goals": goals},
            )

        if kind is MemoryKind.OPPONENT_MODELS:
            built = _build_opponent_model(state, player_id)
            if built is None:
                return None
            opponent_id, model = built
            return (
                "write_opponent_model",
                {
                    "api_key": self._api_key,
                    "opponent_id": opponent_id,
                    "model": model,
                },
            )

        if kind is MemoryKind.TURN_NOTES:
            notes = _build_turn_notes(state, player_id, analysis, submitted)
            return (
                "write_turn_notes",
                {"api_key": self._api_key, "notes": notes},
            )

        return None


async def run_agent_turn(
    client: MCPClient,
    api_key: str,
    profile: AgentProfile,
    *,
    player_id: str | None = None,
    planner: PlannerFn | None = None,
) -> TurnTrace:
    """Convenience wrapper — one-shot a single turn for this agent."""
    agent = MCPAgent(client, api_key, profile, player_id=player_id, planner=planner)
    return await agent.play_turn()


# Re-export the coroutine type so tests that import from agent_runtime
# don't need to drag in typing.Awaitable separately.
__all__ = [
    "MCPAgent",
    "TurnTrace",
    "PlannerFn",
    "run_agent_turn",
    "Awaitable",
]
