"""
Profile-driven heuristic planner.

Phase 6 agents call this planner to turn the state + memory + analysis
output into a list of concrete, fully-parameterised action dicts that
``submit_actions`` will accept. The planner is deterministic (seeded
from the player_id and turn) so self-play games replay identically.

This is deliberately NOT the LLM planner the long-term design calls for.
An LLM planner is an obvious future replacement: it implements the same
``Plan`` protocol and returns the same action-dict list. Keeping the
heuristic planner here means the agent runtime, self-play tests, and
integration tests can all run offline — no LLM server required — which
is a hard requirement for CI.

The planner consults the profile in three ways:

- ``ranked_action_types`` decides which action to propose first for each
  candidate unit or city.
- ``action_biases`` weighting which unit type a city should train and
  which building to prioritise.
- ``thresholds`` gate whole action categories: ``military_ratio_attack``
  suppresses ATTACK below the required ratio; ``target_city_count`` /
  ``expand_city_count`` suppresses FOUND_CITY once the city count is met.

Outputs are bounded per-turn: one action per unit, one per city. Moves
are one tile at a time, which the rules engine always accepts when
terrain permits.
"""

from __future__ import annotations

import random
from typing import Any

from .profiles import AgentProfile

# Mapping from resource name to the improvement that extracts it.
_RESOURCE_IMPROVEMENT: dict[str, str] = {
    "food": "farm",
    "ore": "mine",
    "wood": "lumber_mill",
    "crystal": "crystal_extractor",
}

# Terrain types a unit can step onto. Matches the engine's
# ``TERRAIN_ENTRY_COST`` table (everything except mountain and water).
# Swamp is included — it is passable, just expensive.
_PASSABLE_TERRAINS = {"grass", "forest", "hills", "desert", "swamp"}

# Fallback building pick when profile has no strong signal. Ordered so
# granary (economic) wins ties in the balanced profile.
_BUILDING_PRIORITY: tuple[str, ...] = (
    "granary",
    "barracks",
    "walls",
    "library",
    "monument",
    "temple",
)


def _military_ratio(military: dict[str, Any] | None) -> float | None:
    """Return my_strength / enemy_strength or None if unknown."""
    if not military:
        return None
    my_strength = float(military.get("my_strength") or 0)
    enemy_strength = float(military.get("enemy_strength") or 0)
    if enemy_strength <= 0:
        # No visible enemies — treat as infinite ratio so attack gates open
        # but there's no target anyway; callers still need to find a unit.
        return float("inf") if my_strength > 0 else None
    return my_strength / enemy_strength


def _gate_attack(profile: AgentProfile, military: dict[str, Any] | None) -> bool:
    ratio_threshold = profile.thresholds.get("military_ratio_attack")
    if ratio_threshold is None:
        return False
    ratio = _military_ratio(military)
    if ratio is None:
        # Without data, fall back to letting the profile bias win: if the
        # profile already ranks ATTACK top (aggressive), don't suppress;
        # otherwise suppress, since we lack evidence of strength.
        top = profile.ranked_action_types()
        if top and top[0][0] == "ATTACK":
            return False
        return True
    return ratio < ratio_threshold


def _gate_found_city(profile: AgentProfile, my_city_count: int) -> bool:
    target = profile.thresholds.get("target_city_count")
    cap = profile.thresholds.get("expand_city_count")
    limit = target if target is not None else cap
    if limit is None:
        return False
    return my_city_count >= int(limit)


def _pick_action_type(profile: AgentProfile, candidates: tuple[str, ...]) -> str | None:
    """Return the highest-bias action type from the given candidates."""
    ranked = [(a, w) for a, w in profile.ranked_action_types() if a in candidates]
    if not ranked:
        return None
    top_type, top_weight = ranked[0]
    if top_weight <= 0:
        return None
    return top_type


def _tile_by_loc(state: dict[str, Any], x: int, y: int) -> dict[str, Any] | None:
    for tile in state.get("tiles", []) or []:
        loc = tile.get("loc") or {}
        if loc.get("x") == x and loc.get("y") == y:
            return tile
    return None


def _tile_for_unit(
    state: dict[str, Any], unit: dict[str, Any]
) -> dict[str, Any] | None:
    loc = unit.get("loc") or {}
    return _tile_by_loc(state, int(loc.get("x", 0)), int(loc.get("y", 0)))


def _my_stockpile(state: dict[str, Any], player_id: str) -> dict[str, int]:
    piles = state.get("stockpiles") or {}
    return piles.get(player_id) or {}


def _nearest_enemy_unit(
    state: dict[str, Any], player_id: str, unit: dict[str, Any]
) -> dict[str, Any] | None:
    my_loc = unit.get("loc") or {}
    mx, my = int(my_loc.get("x", 0)), int(my_loc.get("y", 0))
    enemies = [
        u for u in (state.get("units") or {}).values() if u.get("owner") != player_id
    ]
    if not enemies:
        return None

    def dist(other: dict[str, Any]) -> int:
        loc = other.get("loc") or {}
        return abs(int(loc.get("x", 0)) - mx) + abs(int(loc.get("y", 0)) - my)

    return min(enemies, key=dist)


def _step_toward(
    state: dict[str, Any],
    unit: dict[str, Any],
    target_x: int,
    target_y: int,
    rng: random.Random,
) -> tuple[int, int] | None:
    """Return a single-step coord toward (target_x, target_y) that is passable."""
    loc = unit.get("loc") or {}
    mx, my = int(loc.get("x", 0)), int(loc.get("y", 0))

    # Candidate steps in priority order: reduce whichever axis is larger.
    dx = 0 if target_x == mx else (1 if target_x > mx else -1)
    dy = 0 if target_y == my else (1 if target_y > my else -1)

    candidates: list[tuple[int, int]] = []
    if abs(target_x - mx) >= abs(target_y - my):
        if dx != 0:
            candidates.append((mx + dx, my))
        if dy != 0:
            candidates.append((mx, my + dy))
    else:
        if dy != 0:
            candidates.append((mx, my + dy))
        if dx != 0:
            candidates.append((mx + dx, my))

    # If we're already there or target_x/y are the same, fall through.
    extra = [(mx + sx, my + sy) for sx, sy in [(1, 0), (-1, 0), (0, 1), (0, -1)]]
    rng.shuffle(extra)
    candidates.extend(extra)

    for cx, cy in candidates:
        tile = _tile_by_loc(state, cx, cy)
        if tile is None:
            continue
        if tile.get("terrain") not in _PASSABLE_TERRAINS:
            continue
        if tile.get("unit_id") and tile.get("unit_id") != unit.get("id"):
            continue
        return (cx, cy)
    return None


def _explore_step(
    state: dict[str, Any], unit: dict[str, Any], rng: random.Random
) -> tuple[int, int] | None:
    """Pick a random passable neighbouring tile."""
    loc = unit.get("loc") or {}
    mx, my = int(loc.get("x", 0)), int(loc.get("y", 0))
    steps = [(mx + 1, my), (mx - 1, my), (mx, my + 1), (mx, my - 1)]
    rng.shuffle(steps)
    for cx, cy in steps:
        tile = _tile_by_loc(state, cx, cy)
        if tile is None:
            continue
        if tile.get("terrain") not in _PASSABLE_TERRAINS:
            continue
        if tile.get("unit_id") and tile.get("unit_id") != unit.get("id"):
            continue
        return (cx, cy)
    return None


def _improvement_for_tile(tile: dict[str, Any]) -> str | None:
    """Return the improvement type that fits this tile, or None."""
    if tile.get("improvement"):
        return None
    resource = tile.get("resource")
    terrain = tile.get("terrain")
    if resource:
        # Each resource's canonical improvement — all terrain constraints
        # are enforced by the rules engine on submit.
        return _RESOURCE_IMPROVEMENT.get(resource)
    # No resource on tile — lumber mill works on any forest tile even
    # without a wood node, and is the only improvement with no resource
    # prerequisite.
    if terrain == "forest":
        return "lumber_mill"
    return None


def _pick_training_unit(profile: AgentProfile) -> str:
    """Pick which unit type a city should train this turn."""
    # Bias toward military units when ATTACK is strong, otherwise
    # workers/scouts. Scout is cheapest and useful for explorers.
    biases = profile.action_biases
    military_bias = biases.get("ATTACK", 0.0) + biases.get("TRAIN_UNIT", 0.0)
    move_bias = biases.get("MOVE", 0.0)
    improve_bias = biases.get("BUILD_IMPROVEMENT", 0.0)

    if military_bias >= move_bias and military_bias >= improve_bias:
        # Aggressive/balanced — soldiers.
        return "soldier"
    if improve_bias >= move_bias:
        # Economic — need workers to man improvements.
        return "worker"
    # Explorer-ish — scouts for sight range.
    return "scout"


def _pick_building(profile: AgentProfile, already_built: set[str]) -> str | None:
    """Pick which building to build next, honouring profile biases."""
    threat_trigger = profile.thresholds.get("threat_level_wall")
    # If the profile cares about walls under threat, and walls isn't built,
    # the aggressive profile's threshold opens that lane. Simple heuristic:
    # pick walls for aggressive when present in thresholds.
    priorities: tuple[str, ...] = _BUILDING_PRIORITY
    if threat_trigger is not None and "walls" not in already_built:
        priorities = ("walls", *tuple(b for b in _BUILDING_PRIORITY if b != "walls"))

    # Economic-leaning profiles want granaries first; the default order
    # already privileges that.
    for name in priorities:
        if name not in already_built:
            return name
    return None


def _make_unit_action(
    profile: AgentProfile,
    state: dict[str, Any],
    player_id: str,
    unit: dict[str, Any],
    suppress_attack: bool,
    suppress_found: bool,
    rng: random.Random,
) -> dict[str, Any] | None:
    unit_type = str(unit.get("type", "")).lower()
    my_tile = _tile_for_unit(state, unit)

    # Determine candidate action types for this unit.
    if unit_type == "worker":
        candidates = ("BUILD_IMPROVEMENT", "FOUND_CITY", "MOVE")
    elif unit_type == "scout":
        candidates = ("MOVE", "ATTACK")
    elif unit_type in ("soldier", "archer"):
        candidates = ("ATTACK", "MOVE")
    else:
        candidates = ("MOVE",)

    if suppress_attack:
        candidates = tuple(c for c in candidates if c != "ATTACK")
    if suppress_found:
        candidates = tuple(c for c in candidates if c != "FOUND_CITY")

    # Walk the ranked list of types and pick the first one we can
    # actually parameterise into a valid action.
    ranked = [a for a, w in profile.ranked_action_types() if a in candidates and w > 0]

    for action_type in ranked:
        if action_type == "MOVE":
            step = _explore_step(state, unit, rng)
            if step is None:
                continue
            return {
                "type": "MOVE",
                "unit_id": unit.get("id"),
                "to": {"x": step[0], "y": step[1]},
            }

        if action_type == "FOUND_CITY":
            if my_tile is None:
                continue
            if my_tile.get("terrain") not in _PASSABLE_TERRAINS:
                continue
            if my_tile.get("city_id"):
                continue
            return {
                "type": "FOUND_CITY",
                "worker_id": unit.get("id"),
            }

        if action_type == "BUILD_IMPROVEMENT":
            if my_tile is None:
                continue
            improvement = _improvement_for_tile(my_tile)
            if improvement is None:
                continue
            return {
                "type": "BUILD_IMPROVEMENT",
                "worker_id": unit.get("id"),
                "improvement": improvement,
            }

        if action_type == "ATTACK":
            enemy = _nearest_enemy_unit(state, player_id, unit)
            if enemy is None:
                continue
            # Only emit ATTACK if enemy is at an attack distance of 1 —
            # the generic ranged check belongs in the rules engine;
            # guarding it here avoids known-invalid submissions.
            my_loc = unit.get("loc") or {}
            their_loc = enemy.get("loc") or {}
            distance = abs(int(my_loc.get("x", 0)) - int(their_loc.get("x", 0))) + abs(
                int(my_loc.get("y", 0)) - int(their_loc.get("y", 0))
            )
            if distance > 2:
                # Too far even for archers — move toward instead.
                step = _step_toward(
                    state,
                    unit,
                    int(their_loc.get("x", 0)),
                    int(their_loc.get("y", 0)),
                    rng,
                )
                if step is None:
                    continue
                return {
                    "type": "MOVE",
                    "unit_id": unit.get("id"),
                    "to": {"x": step[0], "y": step[1]},
                }
            return {
                "type": "ATTACK",
                "attacker_id": unit.get("id"),
                "target_id": enemy.get("id"),
                "target_type": "unit",
            }

    return None


def _make_city_action(
    profile: AgentProfile,
    state: dict[str, Any],
    player_id: str,
    city: dict[str, Any],
) -> dict[str, Any] | None:
    stockpile = _my_stockpile(state, player_id)
    city_buildings = set(city.get("buildings") or [])

    ranked = [a for a, w in profile.ranked_action_types() if w > 0]

    for action_type in ranked:
        if action_type == "BUILD_BUILDING":
            building = _pick_building(profile, city_buildings)
            if building is None:
                continue
            return {
                "type": "BUILD_BUILDING",
                "city_id": city.get("id"),
                "building_type": building,
            }

        if action_type == "TRAIN_UNIT":
            # Minimum reserve check — don't drain food below 10 if we can
            # help it; the rules engine will ultimately enforce cost.
            if stockpile.get("food", 0) < 20:
                continue
            unit_type = _pick_training_unit(profile)
            return {
                "type": "TRAIN_UNIT",
                "city_id": city.get("id"),
                "unit_type": unit_type,
            }

    return None


def plan_actions(
    profile: AgentProfile,
    state: dict[str, Any],
    player_id: str,
    analysis: dict[str, dict[str, Any]] | None = None,
    turn: int = 0,
) -> list[dict[str, Any]]:
    """Produce a list of action dicts for this player's turn.

    ``state`` is the fog-of-war-redacted game state as returned by
    ``get_game_state`` (the dict under the ``state`` key). ``analysis``
    is a mapping from analysis-tool name to the dict that tool returned;
    ``evaluate_military_position`` is the only value consulted for
    threshold gating in this heuristic. The LLM planner would read more.
    """
    rng = random.Random(f"{player_id}:{turn}")

    units = state.get("units") or {}
    cities = state.get("cities") or {}
    my_units = [u for u in units.values() if u.get("owner") == player_id]
    my_cities = [c for c in cities.values() if c.get("owner") == player_id]

    military = (analysis or {}).get("evaluate_military_position")
    suppress_attack = _gate_attack(profile, military)
    suppress_found = _gate_found_city(profile, len(my_cities))

    actions: list[dict[str, Any]] = []

    # Cities first so training happens before units move — deterministic
    # order mattering only for logs.
    my_cities.sort(key=lambda c: c.get("id", 0))
    for city in my_cities:
        action = _make_city_action(profile, state, player_id, city)
        if action is not None:
            actions.append(action)

    my_units.sort(key=lambda u: u.get("id", 0))
    for unit in my_units:
        action = _make_unit_action(
            profile,
            state,
            player_id,
            unit,
            suppress_attack=suppress_attack,
            suppress_found=suppress_found,
            rng=rng,
        )
        if action is not None:
            actions.append(action)

    return actions
