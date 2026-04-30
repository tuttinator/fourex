"""Canonical rules reference payload.

Single source of truth for every game constant an agent or UI consumer
needs: unit stats, building stats, improvement stats, terrain entry
costs, combat formulas, stacking rules, queued-order cancellation
conditions, and the tech tree. The payload is pure static data built
from the engine's constants in :mod:`.models`, so REST, MCP, and the
frontend rules panel all read from one place.

Breaking changes bump ``RULES_SCHEMA_VERSION``.
"""

from __future__ import annotations

from typing import Any

from .models import (
    BARRACKS_UNIT_PRODUCTION_BONUS,
    BUILDING_PRODUCTION_COST,
    BUILDING_STATS,
    CITY_BASE_PRODUCTION_RATE,
    CITY_BASE_SCIENCE_PER_TURN,
    CITY_ELIGIBLE_TERRAIN,
    FORTIFICATION_CITY_DEFENCE_BONUS,
    IMPROVEMENT_STATS,
    LIBRARY_SCIENCE_BONUS,
    RULES_SCHEMA_VERSION,
    STACK_CAP,
    TECH_TREE,
    TEMPLE_SCIENCE_BONUS,
    TERRAIN_ENTRY_COST,
    TERRAIN_PRIMARY_RESOURCE,
    UNIT_PRODUCTION_COST,
    UNIT_STATS,
)


def build_rules_reference() -> dict[str, Any]:
    """Return the full rules reference payload.

    The shape is stable within a schema version; breaking changes bump
    ``schema_version``. Keys:

    - ``schema_version`` (int)
    - ``units`` — one entry per :class:`UnitType`
    - ``buildings`` — one entry per :class:`BuildingType`
    - ``improvements`` — one entry per :class:`ImprovementType`
    - ``terrain`` — per-tile entry cost + passability for land units
    - ``tech_tree`` — same shape as ``get_tech_tree``'s ``tech_tree`` field
    - ``combat`` — damage formulas, counter-attack, fortification
    - ``stacking`` — per-tile cap + targeting semantics
    - ``orders`` — multi-turn order cancellation conditions (forward-
      looking; wired up in Phase 5)
    - ``cities`` — production / science rates
    """
    units = {
        unit_type.value: {
            "cost": stats.cost.model_dump(),
            "production_cost": UNIT_PRODUCTION_COST[unit_type],
            "moves": stats.moves,
            "hp": stats.hp,
            "sight": stats.sight,
            "attack": stats.attack,
            "attack_range": stats.attack_range,
            "special": stats.special,
            "required_tech": stats.required_tech,
        }
        for unit_type, stats in UNIT_STATS.items()
    }

    buildings = {
        building_type.value: {
            "cost": stats.cost.model_dump(),
            "production_cost": BUILDING_PRODUCTION_COST[building_type],
            "hp": stats.hp,
            "effect": stats.effect,
            "required_tech": stats.required_tech,
        }
        for building_type, stats in BUILDING_STATS.items()
    }

    improvements = {
        imp_type.value: {
            "cost": stats.cost.model_dump(),
            "valid_terrain": [t.value for t in stats.valid_terrain],
            "required_resource": (
                stats.required_resource.value
                if stats.required_resource is not None
                else None
            ),
            "effect": stats.effect,
        }
        for imp_type, stats in IMPROVEMENT_STATS.items()
    }

    terrain = {
        terrain_type.value: {
            "entry_cost": cost,
            "passable": cost is not None,
            "city_eligible": terrain_type in CITY_ELIGIBLE_TERRAIN,
            "primary_resource": (
                resource.value
                if (resource := TERRAIN_PRIMARY_RESOURCE.get(terrain_type)) is not None
                else None
            ),
        }
        for terrain_type, cost in TERRAIN_ENTRY_COST.items()
    }

    tech_tree = {
        tech_id: {
            "id": tech.id,
            "name": tech.name,
            "cost_science": tech.cost_science,
            "requires": list(tech.requires),
            "unlocks_units": [u.value for u in tech.unlocks_units],
            "unlocks_buildings": [b.value for b in tech.unlocks_buildings],
        }
        for tech_id, tech in TECH_TREE.items()
    }

    combat = {
        "damage_formula": "max(1, attacker.attack - defender.attack // 2)",
        "counter_attack": {
            "formula": "max(1, defender.attack - attacker.attack // 2)",
            "excluded_units": ["archer"],
            "notes": "Ranged attackers (archers) receive no counter-attack.",
        },
        "city_attack": {
            "soldier_bonus_multiplier": 1.25,
            "notes": "Soldiers deal +25% damage when attacking a city.",
        },
        "city_counter_fire": {
            "requires_building": "walls",
            "damage": 2,
            "notes": "Cities with Walls return fixed counter-fire.",
        },
        "fortification": {
            "city_defence_bonus": FORTIFICATION_CITY_DEFENCE_BONUS,
            "notes": (
                "Units defending on a friendly city tile take "
                f"{int(FORTIFICATION_CITY_DEFENCE_BONUS * 100)}% less "
                "damage (rounded). Counter-attacks receive the same "
                "reduction when the counter-attacker is on a friendly "
                "city tile."
            ),
        },
        "treacherous_attack": (
            "Attacking a player at PEACE flips the relationship to WAR "
            "and emits WAR_DECLARED + TREACHEROUS_ATTACK diplomatic "
            "events; any active peace treaties are cancelled."
        ),
    }

    stacking = {
        "cap_per_tile": STACK_CAP,
        "symmetric": True,
        "notes": (
            f"Up to {STACK_CAP} units may share a tile regardless of "
            "owner. Moves onto a tile at cap are rejected. Attacks on a "
            "stacked enemy tile may use target_tile (engine picks a "
            "random defender via the game's seeded RNG) or target_id "
            "for deterministic targeting."
        ),
    }

    orders = {
        "cancellation_conditions": [
            "Any enemy unit newly inside the moving unit's sight radius.",
            (
                "The next step becomes obstructed (terrain change or "
                "stacked tile at cap)."
            ),
            "The unit took damage during the previous turn's combat.",
        ],
        "notes": (
            "Multi-turn move orders persist server-side. The engine "
            "resumes the head of each unit's order queue at the start "
            "of every turn. Cancellations emit a game event visible "
            "via get_game_state."
        ),
    }

    cities = {
        "base_production_per_turn": CITY_BASE_PRODUCTION_RATE,
        "barracks_unit_production_bonus": BARRACKS_UNIT_PRODUCTION_BONUS,
        "base_science_per_turn": CITY_BASE_SCIENCE_PER_TURN,
        "library_science_bonus": LIBRARY_SCIENCE_BONUS,
        "temple_science_bonus": TEMPLE_SCIENCE_BONUS,
    }

    return {
        "schema_version": RULES_SCHEMA_VERSION,
        "units": units,
        "buildings": buildings,
        "improvements": improvements,
        "terrain": terrain,
        "tech_tree": tech_tree,
        "combat": combat,
        "stacking": stacking,
        "orders": orders,
        "cities": cities,
    }
