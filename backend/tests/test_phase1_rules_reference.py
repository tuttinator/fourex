"""Phase 1: canonical rules reference payload.

Acceptance criteria from ``plans/gameplay-improvements.md``:

- ``GET /api/v1/rules`` returns a structured payload covering every
  category listed in the plan.
- MCP tool ``get_rules_reference`` returns the same payload, tagged
  read-only.
- Payload includes ``schema_version``.
- Engine-side constants (``UNIT_STATS``, ``BUILDING_STATS``,
  ``IMPROVEMENT_STATS``, terrain cost table) are sourced from the same
  single module the endpoint reads from.

Tests here cover: payload shape snapshot, MCP tool parity with REST,
schema version present, constant parity with models.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.src.game.models import (
    BUILDING_PRODUCTION_COST,
    BUILDING_STATS,
    FORTIFICATION_CITY_DEFENCE_BONUS,
    IMPROVEMENT_STATS,
    RULES_SCHEMA_VERSION,
    STACK_CAP,
    TECH_TREE,
    TERRAIN_ENTRY_COST,
    UNIT_PRODUCTION_COST,
    UNIT_STATS,
    BuildingType,
    ImprovementType,
    Terrain,
    UnitType,
)
from backend.src.game.rules_reference import build_rules_reference
from backend.src.main import app
from backend.src.mcp_server.server import create_mcp_server


_TOP_LEVEL_KEYS = {
    "schema_version",
    "units",
    "buildings",
    "improvements",
    "terrain",
    "tech_tree",
    "combat",
    "stacking",
    "orders",
    "cities",
}


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def mcp() -> Any:
    return create_mcp_server()


async def _mcp_call(mcp: Any, tool: str, args: dict[str, Any]) -> dict[str, Any]:
    result = await mcp.call_tool(tool, args)
    if isinstance(result, tuple):
        return result[1]  # type: ignore[return-value]
    return json.loads(result[0].text)  # type: ignore[union-attr]


def test_payload_has_every_top_level_category() -> None:
    payload = build_rules_reference()
    assert set(payload.keys()) == _TOP_LEVEL_KEYS


def test_schema_version_is_present_and_matches_constant() -> None:
    payload = build_rules_reference()
    assert payload["schema_version"] == RULES_SCHEMA_VERSION
    assert isinstance(payload["schema_version"], int)


def test_units_payload_matches_engine_constants() -> None:
    payload = build_rules_reference()
    for unit_type in UnitType:
        entry = payload["units"][unit_type.value]
        stats = UNIT_STATS[unit_type]
        assert entry["cost"] == stats.cost.model_dump()
        assert entry["production_cost"] == UNIT_PRODUCTION_COST[unit_type]
        assert entry["moves"] == stats.moves
        assert entry["hp"] == stats.hp
        assert entry["sight"] == stats.sight
        assert entry["attack"] == stats.attack
        assert entry["attack_range"] == stats.attack_range
        assert entry["special"] == stats.special
        assert entry["required_tech"] == stats.required_tech


def test_buildings_payload_matches_engine_constants() -> None:
    payload = build_rules_reference()
    for building_type in BuildingType:
        entry = payload["buildings"][building_type.value]
        stats = BUILDING_STATS[building_type]
        assert entry["cost"] == stats.cost.model_dump()
        assert entry["production_cost"] == BUILDING_PRODUCTION_COST[building_type]
        assert entry["hp"] == stats.hp
        assert entry["effect"] == stats.effect
        assert entry["required_tech"] == stats.required_tech


def test_improvements_payload_matches_engine_constants() -> None:
    payload = build_rules_reference()
    for imp_type in ImprovementType:
        entry = payload["improvements"][imp_type.value]
        stats = IMPROVEMENT_STATS[imp_type]
        assert entry["cost"] == stats.cost.model_dump()
        assert entry["valid_terrain"] == [t.value for t in stats.valid_terrain]
        expected_resource = (
            stats.required_resource.value
            if stats.required_resource is not None
            else None
        )
        assert entry["required_resource"] == expected_resource
        assert entry["effect"] == stats.effect


def test_terrain_payload_marks_impassable_as_null() -> None:
    payload = build_rules_reference()
    for terrain, cost in TERRAIN_ENTRY_COST.items():
        entry = payload["terrain"][terrain.value]
        assert entry["entry_cost"] == cost
        assert entry["passable"] == (cost is not None)

    # Mountains and water must remain impassable per the PRD.
    assert payload["terrain"][Terrain.MOUNTAIN.value]["entry_cost"] is None
    assert payload["terrain"][Terrain.MOUNTAIN.value]["passable"] is False
    assert payload["terrain"][Terrain.WATER.value]["entry_cost"] is None
    assert payload["terrain"][Terrain.WATER.value]["passable"] is False
    # Grass cost 1; forest, hills cost 2; swamp cost 3 per the PRD.
    assert payload["terrain"][Terrain.GRASS.value]["entry_cost"] == 1
    assert payload["terrain"][Terrain.FOREST.value]["entry_cost"] == 2
    assert payload["terrain"][Terrain.HILLS.value]["entry_cost"] == 2
    assert payload["terrain"][Terrain.SWAMP.value]["entry_cost"] == 3
    assert payload["terrain"][Terrain.DESERT.value]["entry_cost"] == 1

    # City eligibility surfaces in the payload.
    assert payload["terrain"][Terrain.GRASS.value]["city_eligible"] is True
    assert payload["terrain"][Terrain.HILLS.value]["city_eligible"] is True
    assert payload["terrain"][Terrain.MOUNTAIN.value]["city_eligible"] is False
    assert payload["terrain"][Terrain.SWAMP.value]["city_eligible"] is False
    assert payload["terrain"][Terrain.WATER.value]["city_eligible"] is False

    # Primary resource per terrain (mountain/water/swamp have none).
    assert payload["terrain"][Terrain.GRASS.value]["primary_resource"] == "food"
    assert payload["terrain"][Terrain.FOREST.value]["primary_resource"] == "wood"
    assert payload["terrain"][Terrain.HILLS.value]["primary_resource"] == "ore"
    assert payload["terrain"][Terrain.MOUNTAIN.value]["primary_resource"] is None
    assert payload["terrain"][Terrain.DESERT.value]["primary_resource"] == "crystal"
    assert payload["terrain"][Terrain.SWAMP.value]["primary_resource"] is None


def test_tech_tree_payload_matches_static_tree() -> None:
    payload = build_rules_reference()
    assert set(payload["tech_tree"].keys()) == set(TECH_TREE.keys())
    for tech_id, tech in TECH_TREE.items():
        entry = payload["tech_tree"][tech_id]
        assert entry["id"] == tech.id
        assert entry["name"] == tech.name
        assert entry["cost_science"] == tech.cost_science
        assert entry["requires"] == list(tech.requires)
        assert entry["unlocks_units"] == [u.value for u in tech.unlocks_units]
        assert entry["unlocks_buildings"] == [
            b.value for b in tech.unlocks_buildings
        ]


def test_stacking_payload_exposes_cap_and_symmetry() -> None:
    payload = build_rules_reference()
    assert payload["stacking"]["cap_per_tile"] == STACK_CAP
    assert payload["stacking"]["symmetric"] is True
    assert "target_tile" in payload["stacking"]["notes"]


def test_combat_payload_exposes_fortification_bonus() -> None:
    payload = build_rules_reference()
    fort = payload["combat"]["fortification"]
    assert fort["city_defence_bonus"] == FORTIFICATION_CITY_DEFENCE_BONUS
    # Damage formula exists in a machine-readable string agents can log.
    assert "attacker.attack" in payload["combat"]["damage_formula"]
    # Archer no-counter rule is documented.
    assert "archer" in payload["combat"]["counter_attack"]["excluded_units"]


def test_orders_payload_lists_all_cancellation_conditions() -> None:
    payload = build_rules_reference()
    conditions = payload["orders"]["cancellation_conditions"]
    joined = " ".join(conditions).lower()
    assert "enemy" in joined
    assert "obstruct" in joined
    assert "damage" in joined
    assert len(conditions) >= 3


def test_rest_endpoint_returns_same_payload(client: TestClient) -> None:
    resp = client.get("/api/v1/rules")
    assert resp.status_code == 200
    assert resp.json() == build_rules_reference()


def test_rest_endpoint_requires_no_authentication(client: TestClient) -> None:
    # Rules are static / public — no Authorization header needed.
    resp = client.get("/api/v1/rules")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_mcp_tool_parity_with_rest(client: TestClient, mcp: Any) -> None:
    rest_payload = client.get("/api/v1/rules").json()
    mcp_payload = await _mcp_call(mcp, "get_rules_reference", {})
    assert mcp_payload == rest_payload
    assert mcp_payload["schema_version"] == RULES_SCHEMA_VERSION
