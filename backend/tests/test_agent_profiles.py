"""Tests for the Phase 5 structured agent profile system."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from backend.src.agents.profile_runner import (
    ProfileRunResult,
    run_profile_turn,
)
from backend.src.agents.profiles import (
    AGGRESSIVE,
    BALANCED,
    ECONOMIC,
    EXPLORER,
    PROFILES,
    AgentProfile,
    MemoryKind,
    get_profile,
    list_profiles,
)

# ---------------------------------------------------------------------------
# AgentProfile model
# ---------------------------------------------------------------------------


def test_reference_profiles_registered():
    names = list_profiles()
    assert set(names) == {"aggressive", "economic", "explorer", "balanced"}
    for name in names:
        p = PROFILES[name]
        assert p.name == name
        assert p.description
        assert p.system_prompt
        assert p.tool_priorities, f"{name} has no tool priorities"
        assert p.memory_priorities, f"{name} has no memory priorities"
        assert p.action_biases, f"{name} has no action biases"


def test_get_profile_falls_back_to_balanced():
    assert get_profile("aggressive") is AGGRESSIVE
    assert get_profile("does-not-exist") is BALANCED


def test_profile_is_frozen():
    with pytest.raises(ValidationError):
        AGGRESSIVE.model_copy(update={"name": "mutated"}).name  # ok
        # Direct mutation should fail because the model is frozen.
        AGGRESSIVE.name = "mutated"  # type: ignore[misc]


def test_action_biases_reject_unknown_types():
    with pytest.raises(ValidationError):
        AgentProfile(
            name="bad",
            description="",
            system_prompt="x",
            action_biases={"FLY": 1.0},
        )


def test_action_biases_reject_negative_weights():
    with pytest.raises(ValidationError):
        AgentProfile(
            name="bad",
            description="",
            system_prompt="x",
            action_biases={"ATTACK": -1.0},
        )


def test_duplicate_memory_priorities_rejected():
    with pytest.raises(ValidationError):
        AgentProfile(
            name="bad",
            description="",
            system_prompt="x",
            memory_priorities=(
                MemoryKind.STRATEGIC_GOALS,
                MemoryKind.STRATEGIC_GOALS,
            ),
        )


def test_duplicate_tool_priorities_rejected():
    with pytest.raises(ValidationError):
        AgentProfile(
            name="bad",
            description="",
            system_prompt="x",
            tool_priorities=("analyze_territory", "analyze_territory"),
        )


def test_ranked_action_types_orders_by_descending_weight():
    ranked = AGGRESSIVE.ranked_action_types()
    # Top must be ATTACK for the aggressive profile.
    assert ranked[0][0] == "ATTACK"
    # Result is sorted descending.
    weights = [w for _, w in ranked]
    assert weights == sorted(weights, reverse=True)


def test_reference_profiles_have_distinct_top_priorities():
    """Different profiles must produce different tool call orderings."""
    tops = {name: p.tool_priorities[0] for name, p in PROFILES.items()}
    assert tops["aggressive"] == "evaluate_military_position"
    assert tops["economic"] == "find_resource_opportunities"
    assert tops["explorer"] == "analyze_territory"
    assert tops["balanced"] == "analyze_territory"


def test_reference_profiles_have_distinct_top_actions():
    tops = {name: p.ranked_action_types()[0][0] for name, p in PROFILES.items()}
    assert tops["aggressive"] == "ATTACK"
    assert tops["economic"] == "BUILD_IMPROVEMENT"
    assert tops["explorer"] == "MOVE"
    # Balanced has a spread; whatever wins is fine, just not "PASS".
    assert tops["balanced"] != "PASS"


def test_reference_profiles_have_distinct_memory_priorities():
    # Aggressive starts with opponent models; economic with goals;
    # explorer with turn notes. This is mechanical — tests that the
    # profiles are not just reworded prompts.
    assert AGGRESSIVE.memory_priorities[0] is MemoryKind.OPPONENT_MODELS
    assert ECONOMIC.memory_priorities[0] is MemoryKind.STRATEGIC_GOALS
    assert EXPLORER.memory_priorities[0] is MemoryKind.TURN_NOTES


# ---------------------------------------------------------------------------
# Profile-driven runner
# ---------------------------------------------------------------------------


class FakeMCPClient:
    """Records every call and returns scripted responses keyed by tool name."""

    def __init__(self, responses: dict[str, dict[str, Any]] | None = None):
        self._responses = responses or {}
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((name, arguments))
        return self._responses.get(name, {})


def _state_with(player_id: str = "p1") -> dict[str, Any]:
    """A small game-state-shaped dict good enough for the runner."""
    return {
        "units": {
            "1": {"id": 1, "type": "worker", "owner": player_id},
            "2": {"id": 2, "type": "soldier", "owner": player_id},
            "3": {"id": 3, "type": "scout", "owner": "p2"},
        },
        "cities": {
            "10": {"id": 10, "owner": player_id},
        },
    }


@pytest.mark.asyncio
async def test_runner_calls_tools_in_profile_tool_priority_order():
    client = FakeMCPClient(
        responses={
            "get_game_state": _state_with(),
            # Give the attack gate something to chew on.
            "evaluate_military_position": {
                "my_strength": 10,
                "enemy_strength": 3,
            },
        }
    )

    result = await run_profile_turn(
        client, api_key="k", profile=AGGRESSIVE, player_id="p1"
    )

    analysis_call_order = [
        name for name, _ in result.tool_calls if name in AGGRESSIVE.tool_priorities
    ]
    assert analysis_call_order == list(AGGRESSIVE.tool_priorities)


@pytest.mark.asyncio
async def test_runner_reads_memory_in_priority_order():
    client = FakeMCPClient(responses={"get_game_state": _state_with()})
    result = await run_profile_turn(
        client, api_key="k", profile=ECONOMIC, player_id="p1"
    )

    expected_reads = [
        "read_strategic_goals",
        "read_turn_notes",
        "read_opponent_models",
    ]
    read_calls = [name for name, _ in result.tool_calls if name.startswith("read_")]
    assert read_calls == expected_reads


@pytest.mark.asyncio
async def test_runner_writes_memory_in_priority_order():
    client = FakeMCPClient(responses={"get_game_state": _state_with()})
    result = await run_profile_turn(
        client, api_key="k", profile=AGGRESSIVE, player_id="p1"
    )

    # Aggressive writes in the order: opponent_models, strategic_goals, turn_notes.
    assert result.memory_writes == [
        MemoryKind.OPPONENT_MODELS.value,
        MemoryKind.STRATEGIC_GOALS.value,
        MemoryKind.TURN_NOTES.value,
    ]


@pytest.mark.asyncio
async def test_aggressive_proposes_attack_when_military_ratio_exceeds_threshold():
    client = FakeMCPClient(
        responses={
            "get_game_state": _state_with(),
            "evaluate_military_position": {
                "my_strength": 10,
                "enemy_strength": 3,
            },
        }
    )
    result = await run_profile_turn(
        client, api_key="k", profile=AGGRESSIVE, player_id="p1"
    )

    combat_proposals = [
        p for p in result.proposed_actions if p.get("unit_type") == "soldier"
    ]
    assert combat_proposals, "soldier should have a proposal"
    assert combat_proposals[0]["type"] == "ATTACK"


@pytest.mark.asyncio
async def test_aggressive_suppresses_attack_when_below_threshold():
    client = FakeMCPClient(
        responses={
            "get_game_state": _state_with(),
            "evaluate_military_position": {
                "my_strength": 1,
                "enemy_strength": 10,
            },
        }
    )
    result = await run_profile_turn(
        client, api_key="k", profile=AGGRESSIVE, player_id="p1"
    )

    combat_proposals = [
        p for p in result.proposed_actions if p.get("unit_type") == "soldier"
    ]
    assert combat_proposals, "soldier should still have a proposal"
    # With ATTACK gated, MOVE is the only remaining candidate.
    assert combat_proposals[0]["type"] == "MOVE"


@pytest.mark.asyncio
async def test_economic_proposes_build_improvement_for_worker():
    client = FakeMCPClient(responses={"get_game_state": _state_with()})
    result = await run_profile_turn(
        client, api_key="k", profile=ECONOMIC, player_id="p1"
    )

    worker_proposals = [
        p for p in result.proposed_actions if p.get("unit_type") == "worker"
    ]
    assert worker_proposals[0]["type"] == "BUILD_IMPROVEMENT"


@pytest.mark.asyncio
async def test_explorer_proposes_move_for_worker():
    client = FakeMCPClient(responses={"get_game_state": _state_with()})
    result = await run_profile_turn(
        client, api_key="k", profile=EXPLORER, player_id="p1"
    )

    worker_proposals = [
        p for p in result.proposed_actions if p.get("unit_type") == "worker"
    ]
    # MOVE is ranked highest for workers in the explorer profile, even
    # though the profile also biases FOUND_CITY highly.
    assert worker_proposals[0]["type"] in {"MOVE", "FOUND_CITY"}
    assert worker_proposals[0]["type"] != "BUILD_IMPROVEMENT"


@pytest.mark.asyncio
async def test_city_proposals_respect_profile_bias():
    client = FakeMCPClient(responses={"get_game_state": _state_with()})

    agg = await run_profile_turn(
        client, api_key="k", profile=AGGRESSIVE, player_id="p1"
    )
    eco = await run_profile_turn(client, api_key="k", profile=ECONOMIC, player_id="p1")

    agg_city = next(p for p in agg.proposed_actions if "city_id" in p)
    eco_city = next(p for p in eco.proposed_actions if "city_id" in p)

    assert agg_city["type"] == "TRAIN_UNIT"
    assert eco_city["type"] == "BUILD_BUILDING"


@pytest.mark.asyncio
async def test_opponent_model_write_skipped_when_no_enemies_visible():
    state: dict[str, Any] = {
        "units": {"1": {"id": 1, "type": "worker", "owner": "p1"}},
        "cities": {},
    }
    client = FakeMCPClient(responses={"get_game_state": state})
    result = await run_profile_turn(
        client, api_key="k", profile=AGGRESSIVE, player_id="p1"
    )

    # opponent_models kind is in memory_priorities but is skipped
    # because there are no visible enemies to model.
    assert MemoryKind.OPPONENT_MODELS.value not in result.memory_writes
    # Strategic goals and turn notes are still written.
    assert MemoryKind.STRATEGIC_GOALS.value in result.memory_writes
    assert MemoryKind.TURN_NOTES.value in result.memory_writes


@pytest.mark.asyncio
async def test_runner_returns_trace_even_when_state_call_fails():
    client = FakeMCPClient(responses={"get_game_state": {"error": "boom"}})
    result = await run_profile_turn(
        client, api_key="k", profile=BALANCED, player_id="p1"
    )
    assert isinstance(result, ProfileRunResult)
    assert result.proposed_actions == []
    # We still recorded the one call we made before giving up.
    assert result.tool_calls[0][0] == "get_game_state"
