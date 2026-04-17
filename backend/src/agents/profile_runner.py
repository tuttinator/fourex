"""
Profile-driven runner. A thin MCP-client driver that demonstrates the
AgentProfile system end-to-end without needing an LLM.

Given an AgentProfile and an MCP client, run_profile_turn executes:

    1. Observe       -> get_game_state
    2. Remember      -> read_<kind> in profile.memory_priorities order
    3. Analyse       -> each tool in profile.tool_priorities, in order
    4. Plan          -> deterministic heuristic driven by action_biases
                        and gated by thresholds
    5. Memorise      -> write_<kind> for each kind in memory_priorities

The runner returns a ProfileRunResult that records every tool call,
every memory write, and the proposed actions. This is the handle tests
use to assert that different profiles produce different behaviour.

The LLM planner and the full observe/analyse/plan/validate/submit
loop land in Phase 6. Phase 5 only proves the profile fields mechanically
influence tool call order, memory persistence, and action selection.
"""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel

from .profiles import AgentProfile, MemoryKind


class MCPCallable(Protocol):
    """Minimal async MCP-style client interface used by the runner."""

    async def call_tool(
        self, name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]: ...


class ProfileRunResult(BaseModel):
    """Full trace of a profile-driven turn, useful for tests and logs."""

    profile_name: str
    tool_calls: list[tuple[str, dict[str, Any]]] = []
    analysis_results: dict[str, dict[str, Any]] = {}
    memory_reads: dict[str, dict[str, Any]] = {}
    memory_writes: list[str] = []
    proposed_actions: list[dict[str, Any]] = []
    errors: list[str] = []


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


_UNIT_ACTION_CANDIDATES: dict[str, tuple[str, ...]] = {
    # Worker can build, found, or move.
    "worker": ("BUILD_IMPROVEMENT", "FOUND_CITY", "MOVE"),
    # Scout and combat units can move or attack.
    "scout": ("MOVE", "ATTACK"),
    "soldier": ("ATTACK", "MOVE"),
    "archer": ("ATTACK", "MOVE"),
}

_CITY_ACTION_CANDIDATES: tuple[str, ...] = ("TRAIN_UNIT", "BUILD_BUILDING")


def _applicable_actions(entity_type: str) -> tuple[str, ...]:
    if entity_type == "__city__":
        return _CITY_ACTION_CANDIDATES
    return _UNIT_ACTION_CANDIDATES.get(entity_type, ("MOVE",))


def _pick_top_action_type(
    profile: AgentProfile,
    candidates: tuple[str, ...],
) -> tuple[str, float] | None:
    ranked = [(a, w) for a, w in profile.ranked_action_types() if a in candidates]
    if not ranked:
        return None
    return ranked[0]


def _threshold_gates_attack(
    profile: AgentProfile, military: dict[str, Any] | None
) -> bool:
    """Return True if ATTACK proposals should be suppressed."""
    ratio_threshold = profile.thresholds.get("military_ratio_attack")
    if ratio_threshold is None or not military:
        return False
    my_strength = float(military.get("my_strength") or 0)
    enemy_strength = float(military.get("enemy_strength") or 0)
    if enemy_strength <= 0:
        # No enemies visible — nothing to attack, not a gate.
        return False
    return (my_strength / enemy_strength) < ratio_threshold


def _threshold_gates_found_city(profile: AgentProfile, my_city_count: int) -> bool:
    target = profile.thresholds.get("target_city_count")
    cap = profile.thresholds.get("expand_city_count")
    # target_city_count = stop founding once we hit it; expand_city_count
    # = same idea, different phrase. Both gate the same action.
    limit = target if target is not None else cap
    if limit is None:
        return False
    return my_city_count >= int(limit)


def _propose_actions(
    profile: AgentProfile,
    state: dict[str, Any],
    player_id: str,
    military: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    units = state.get("units") or {}
    cities = state.get("cities") or {}
    my_units = [u for u in units.values() if u.get("owner") == player_id]
    my_cities = [c for c in cities.values() if c.get("owner") == player_id]

    suppress_attack = _threshold_gates_attack(profile, military)
    suppress_found = _threshold_gates_found_city(profile, len(my_cities))

    proposals: list[dict[str, Any]] = []

    for unit in my_units:
        unit_type = str(unit.get("type", "")).lower()
        candidates = _applicable_actions(unit_type)
        if suppress_attack:
            candidates = tuple(c for c in candidates if c != "ATTACK")
        if suppress_found:
            candidates = tuple(c for c in candidates if c != "FOUND_CITY")
        pick = _pick_top_action_type(profile, candidates)
        if pick is None:
            continue
        action_type, weight = pick
        proposals.append(
            {
                "type": action_type,
                "unit_id": unit.get("id"),
                "unit_type": unit_type,
                "weight": weight,
            }
        )

    for city in my_cities:
        pick = _pick_top_action_type(profile, _CITY_ACTION_CANDIDATES)
        if pick is None:
            continue
        action_type, weight = pick
        proposals.append(
            {
                "type": action_type,
                "city_id": city.get("id"),
                "weight": weight,
            }
        )

    proposals.sort(key=lambda p: (-float(p["weight"]), str(p["type"])))
    return proposals


_MEMORY_READ_TOOLS: dict[MemoryKind, str] = {
    MemoryKind.STRATEGIC_GOALS: "read_strategic_goals",
    MemoryKind.OPPONENT_MODELS: "read_opponent_models",
    MemoryKind.TURN_NOTES: "read_turn_notes",
}


def _memory_write_payload(
    kind: MemoryKind,
    api_key: str,
    state: dict[str, Any],
    player_id: str,
    analysis: dict[str, dict[str, Any]],
    profile: AgentProfile,
) -> tuple[str, dict[str, Any]] | None:
    """Build (tool_name, arguments) for writing a given memory kind.

    Returns None if the profile has no meaningful content to record for
    that kind on this turn.
    """
    if kind is MemoryKind.STRATEGIC_GOALS:
        goals: list[dict[str, Any]] = [
            {
                "goal": f"profile:{profile.name}",
                "priority": 1,
                "status": "active",
            }
        ]
        return (
            "write_strategic_goals",
            {"api_key": api_key, "goals": goals},
        )

    if kind is MemoryKind.OPPONENT_MODELS:
        units = state.get("units") or {}
        enemies = [u for u in units.values() if u.get("owner") != player_id]
        # Opponent_id is the opponent's player_id. Skip if we can't see any.
        if not enemies:
            return None
        # Record the first enemy we see — just enough to prove the wire-up.
        first = enemies[0]
        opponent_id = first.get("owner")
        if not opponent_id:
            return None
        model = {
            "stance": "unknown",
            "last_seen_unit_type": first.get("type"),
            "visible_unit_count": len(enemies),
        }
        return (
            "write_opponent_model",
            {
                "api_key": api_key,
                "opponent_id": opponent_id,
                "model": model,
            },
        )

    if kind is MemoryKind.TURN_NOTES:
        military = analysis.get("evaluate_military_position") or {}
        assessment = military.get("assessment") or (
            f"Profile {profile.name} turn summary."
        )
        return (
            "write_turn_notes",
            {"api_key": api_key, "notes": str(assessment)[:2000]},
        )

    return None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def run_profile_turn(
    client: MCPCallable,
    api_key: str,
    profile: AgentProfile,
    *,
    player_id: str,
) -> ProfileRunResult:
    """Run one profile-driven turn against an MCP client.

    Does not call submit_actions. It produces a ranked list of
    proposed actions based on the profile, writes memory according to
    memory_priorities, and returns the full trace.

    This is a demonstration harness for Phase 5, not the final agent
    runtime. Phase 6 will add the LLM plan/validate/submit steps.
    """
    result = ProfileRunResult(profile_name=profile.name)

    async def call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result.tool_calls.append((name, arguments))
        try:
            return await client.call_tool(name, arguments)
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"{name}: {exc}")
            return {"error": str(exc)}

    # 1. Observe
    state_resp = await call("get_game_state", {"api_key": api_key})
    if "error" in state_resp:
        return result
    state = state_resp.get("state") or state_resp

    # 2. Remember — read in priority order.
    for kind in profile.memory_priorities:
        tool_name = _MEMORY_READ_TOOLS[kind]
        read_resp = await call(tool_name, {"api_key": api_key})
        result.memory_reads[kind.value] = read_resp

    # 3. Analyse — call each analysis tool in priority order.
    for tool_name in profile.tool_priorities:
        analysis_resp = await call(tool_name, {"api_key": api_key})
        result.analysis_results[tool_name] = analysis_resp

    # 4. Plan — bias- and threshold-driven proposals.
    military = result.analysis_results.get("evaluate_military_position")
    result.proposed_actions = _propose_actions(profile, state, player_id, military)

    # 5. Memorise — write in the same priority order.
    for kind in profile.memory_priorities:
        payload = _memory_write_payload(
            kind, api_key, state, player_id, result.analysis_results, profile
        )
        if payload is None:
            continue
        tool_name, args = payload
        await call(tool_name, args)
        result.memory_writes.append(kind.value)

    return result
