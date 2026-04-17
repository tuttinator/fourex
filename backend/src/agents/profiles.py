"""
Structured agent profiles. Phase 5 of the autonomous-agents overhaul.

An AgentProfile replaces the prompt-only personality system in
agents/src/personalities.py. Behaviour differences between agents are
expressed mechanically via tool call order, memory priorities,
action biases, and numeric thresholds — not just differently worded
prompts over the same logic.

Profiles are stored in code, not the database. They are consumed by
the profile-driven runner (see profile_runner.py) and will be consumed
by the full agent rewrite in Phase 6.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class MemoryKind(str, Enum):
    """Kinds of structured memory an agent can prioritise."""

    STRATEGIC_GOALS = "strategic_goals"
    OPPONENT_MODELS = "opponent_models"
    TURN_NOTES = "turn_notes"


# Known MCP analysis tools the runner may call. Kept as strings (not an
# enum) so new tools can be referenced in profiles without touching this
# module — unknown tool names are simply passed through to the MCP client.
KNOWN_ANALYSIS_TOOLS: tuple[str, ...] = (
    "analyze_territory",
    "evaluate_military_position",
    "find_resource_opportunities",
    "calculate_distances",
)

# Action types recognised in biases. Matches the discriminated union in
# backend/src/game/models.py (plus "PASS" for a no-op turn).
KNOWN_ACTION_TYPES: frozenset[str] = frozenset(
    {
        "MOVE",
        "ATTACK",
        "FOUND_CITY",
        "TRAIN_UNIT",
        "BUILD_IMPROVEMENT",
        "BUILD_BUILDING",
        "PASS",
    }
)


class AgentProfile(BaseModel):
    """Structured agent profile. Frozen once built."""

    model_config = ConfigDict(frozen=True)

    name: str
    description: str
    system_prompt: str = Field(..., max_length=2000)

    tool_priorities: tuple[str, ...] = Field(default_factory=tuple)
    memory_priorities: tuple[MemoryKind, ...] = Field(default_factory=tuple)
    action_biases: dict[str, float] = Field(default_factory=dict)
    thresholds: dict[str, float] = Field(default_factory=dict)

    @field_validator("action_biases")
    @classmethod
    def _validate_action_biases(cls, v: dict[str, float]) -> dict[str, float]:
        unknown = set(v.keys()) - KNOWN_ACTION_TYPES
        if unknown:
            raise ValueError(
                f"Unknown action types in action_biases: {sorted(unknown)}. "
                f"Expected one of: {sorted(KNOWN_ACTION_TYPES)}"
            )
        for action, weight in v.items():
            if weight < 0:
                raise ValueError(
                    f"action_biases[{action!r}] must be >= 0 (got {weight})"
                )
        return v

    @field_validator("memory_priorities")
    @classmethod
    def _no_duplicate_memory_priorities(
        cls, v: tuple[MemoryKind, ...]
    ) -> tuple[MemoryKind, ...]:
        if len(v) != len(set(v)):
            raise ValueError("memory_priorities must not contain duplicates")
        return v

    @field_validator("tool_priorities")
    @classmethod
    def _no_duplicate_tools(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        if len(v) != len(set(v)):
            raise ValueError("tool_priorities must not contain duplicates")
        return v

    def ranked_action_types(self) -> list[tuple[str, float]]:
        """Return action types ordered by descending bias weight.

        Ties are broken alphabetically by action name for determinism.
        Actions with zero weight are included — the runner may still
        consider them as fallbacks, the ordering just ensures they lose
        to any positive-weight option.
        """
        return sorted(self.action_biases.items(), key=lambda kv: (-kv[1], kv[0]))


AGGRESSIVE = AgentProfile(
    name="aggressive",
    description=(
        "Military-first. Reads opponent models before anything else, "
        "attacks when it has a strength advantage, expands through "
        "conquest rather than settlement."
    ),
    system_prompt=(
        "You are an aggressive military commander. Prioritise offensive "
        "action when you hold a military advantage, and produce fighting "
        "units rather than workers when resources are tight. Use memory "
        "to track opponent positions and strength; revisit strategic "
        "goals each turn so you commit to multi-turn offensives."
    ),
    tool_priorities=(
        "evaluate_military_position",
        "analyze_territory",
        "find_resource_opportunities",
        "calculate_distances",
    ),
    memory_priorities=(
        MemoryKind.OPPONENT_MODELS,
        MemoryKind.STRATEGIC_GOALS,
        MemoryKind.TURN_NOTES,
    ),
    action_biases={
        "ATTACK": 3.0,
        "TRAIN_UNIT": 2.5,
        "MOVE": 2.0,
        "FOUND_CITY": 1.2,
        "BUILD_BUILDING": 1.0,
        "BUILD_IMPROVEMENT": 0.5,
        "PASS": 0.0,
    },
    thresholds={
        # Attack only when my military strength exceeds the enemy's by
        # at least this ratio.
        "military_ratio_attack": 1.3,
        # Build walls when threat level meets or exceeds this.
        "threat_level_wall": 0.7,
    },
)


ECONOMIC = AgentProfile(
    name="economic",
    description=(
        "Resource-first. Builds improvements and economic buildings to "
        "maximise throughput; avoids combat unless it is threatened."
    ),
    system_prompt=(
        "You are an economic strategist. Build improvements on every "
        "resource tile you control, keep a steady food and wood "
        "surplus, and favour granaries and libraries. Only produce "
        "military when threat level is high. Track your production "
        "rate in strategic goals and turn notes."
    ),
    tool_priorities=(
        "find_resource_opportunities",
        "analyze_territory",
        "evaluate_military_position",
        "calculate_distances",
    ),
    memory_priorities=(
        MemoryKind.STRATEGIC_GOALS,
        MemoryKind.TURN_NOTES,
        MemoryKind.OPPONENT_MODELS,
    ),
    action_biases={
        "BUILD_IMPROVEMENT": 3.0,
        "BUILD_BUILDING": 2.5,
        "FOUND_CITY": 2.0,
        "TRAIN_UNIT": 1.0,
        "MOVE": 1.0,
        "ATTACK": 0.2,
        "PASS": 0.0,
    },
    thresholds={
        # Only expand past this city count if food surplus holds.
        "expand_city_count": 5,
        # Keep at least this much food in stockpile before training.
        "min_food_reserve": 20,
    },
)


EXPLORER = AgentProfile(
    name="explorer",
    description=(
        "Map-first. Moves scouts aggressively, founds cities near fresh "
        "resource sites, and invests minimal military until the map is "
        "substantially revealed."
    ),
    system_prompt=(
        "You are a bold explorer. Keep scouts moving into fog every "
        "turn, and found new cities near valuable resources as soon as "
        "they are discovered. Your memory should track the frontier — "
        "which tiles are still fogged and which resources are claimed."
    ),
    tool_priorities=(
        "analyze_territory",
        "find_resource_opportunities",
        "calculate_distances",
        "evaluate_military_position",
    ),
    memory_priorities=(
        MemoryKind.TURN_NOTES,
        MemoryKind.STRATEGIC_GOALS,
        MemoryKind.OPPONENT_MODELS,
    ),
    action_biases={
        "MOVE": 3.0,
        "FOUND_CITY": 2.5,
        "TRAIN_UNIT": 1.8,
        "BUILD_IMPROVEMENT": 1.5,
        "BUILD_BUILDING": 0.8,
        "ATTACK": 0.3,
        "PASS": 0.0,
    },
    thresholds={
        # Keep founding cities until we have at least this many.
        "target_city_count": 4,
        # Number of scouts to maintain per city.
        "scouts_per_city": 1.0,
    },
)


BALANCED = AgentProfile(
    name="balanced",
    description=(
        "Adaptive. No single bias dominates; responds to the strongest "
        "signal in the current analysis output."
    ),
    system_prompt=(
        "You are an adaptive strategist. Weigh military, economic, and "
        "exploration signals each turn and act on whichever looks "
        "strongest. Maintain goals across turns but revise them when "
        "the situation changes."
    ),
    tool_priorities=(
        "analyze_territory",
        "evaluate_military_position",
        "find_resource_opportunities",
        "calculate_distances",
    ),
    memory_priorities=(
        MemoryKind.STRATEGIC_GOALS,
        MemoryKind.OPPONENT_MODELS,
        MemoryKind.TURN_NOTES,
    ),
    action_biases={
        "MOVE": 1.5,
        "BUILD_IMPROVEMENT": 1.5,
        "TRAIN_UNIT": 1.3,
        "BUILD_BUILDING": 1.3,
        "FOUND_CITY": 1.2,
        "ATTACK": 1.0,
        "PASS": 0.0,
    },
    thresholds={
        "military_ratio_attack": 1.8,
        "expand_city_count": 4,
    },
)


PROFILES: dict[str, AgentProfile] = {
    AGGRESSIVE.name: AGGRESSIVE,
    ECONOMIC.name: ECONOMIC,
    EXPLORER.name: EXPLORER,
    BALANCED.name: BALANCED,
}


def get_profile(name: str) -> AgentProfile:
    """Look up a reference profile by name; defaults to balanced."""
    return PROFILES.get(name, BALANCED)


def list_profiles() -> list[str]:
    """Return the reference profile names."""
    return list(PROFILES.keys())
