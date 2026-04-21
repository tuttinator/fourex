"""Tests for Phase 8 MCP analysis tools (analyze_territory, evaluate_military_position,
find_resource_opportunities, calculate_distances)."""

from __future__ import annotations

import json
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import delete

from backend.src.database.connection import async_session_factory, init_db
from backend.src.database.models import (
    AgentMemory,
    Game,
    GameSnapshot,
    GameTurn,
    PlayerApiKey,
    TurnAction,
    TurnSnapshot,
)
from backend.src.mcp_server.server import create_mcp_server


@pytest_asyncio.fixture
async def db_session():
    """Async DB session with cleanup."""
    await init_db()
    async with async_session_factory() as session:
        yield session
        await session.rollback()
        # Clean up test data
        await session.execute(
            delete(AgentMemory).where(AgentMemory.game_id.like("game_%"))
        )
        await session.execute(
            delete(TurnAction).where(TurnAction.game_id.like("game_%"))
        )
        await session.execute(
            delete(TurnSnapshot).where(TurnSnapshot.game_id.like("game_%"))
        )
        await session.execute(delete(GameTurn).where(GameTurn.game_id.like("game_%")))
        await session.execute(
            delete(PlayerApiKey).where(PlayerApiKey.game_id.like("game_%"))
        )
        await session.execute(
            delete(GameSnapshot).where(GameSnapshot.game_id.like("game_%"))
        )
        await session.execute(delete(Game).where(Game.id.like("game_%")))
        await session.commit()


@pytest.fixture
def mcp():
    """Create an MCP server instance with all tools registered."""
    return create_mcp_server()


async def call(mcp: Any, tool: str, args: dict[str, Any]) -> dict[str, Any]:
    """Call an MCP tool and parse the JSON response."""
    result = await mcp.call_tool(tool, args)
    if isinstance(result, tuple):
        return result[1]  # type: ignore[return-value]
    return json.loads(result[0].text)  # type: ignore[union-attr]


async def create_two_player_game(mcp: Any) -> dict[str, Any]:
    """Helper: create a game with alice and bob, return game data."""
    return await call(mcp, "create_game", {"players": ["alice", "bob"]})


# ---------------------------------------------------------------------------
# analyze_territory
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_analyze_territory_returns_control(db_session, mcp):
    """analyze_territory returns territory control counts."""
    game_data = await create_two_player_game(mcp)
    api_key = game_data["api_keys"]["alice"]

    result = await call(mcp, "analyze_territory", {"api_key": api_key})

    assert "error" not in result
    assert result["player"] == "alice"
    assert "territory_control" in result
    tc = result["territory_control"]
    assert "my_tiles" in tc
    assert "neutral_tiles" in tc
    assert "enemy_tiles" in tc


@pytest.mark.asyncio
async def test_analyze_territory_returns_resources(db_session, mcp):
    """analyze_territory returns resource distribution."""
    game_data = await create_two_player_game(mcp)
    api_key = game_data["api_keys"]["alice"]

    result = await call(mcp, "analyze_territory", {"api_key": api_key})

    assert "resource_distribution" in result
    rd = result["resource_distribution"]
    for key in ("food_sites", "wood_sites", "ore_sites", "crystal_sites"):
        assert key in rd
        assert isinstance(rd[key], int)


@pytest.mark.asyncio
async def test_analyze_territory_expansion_opportunities(db_session, mcp):
    """analyze_territory returns expansion opportunities capped at 5."""
    game_data = await create_two_player_game(mcp)
    api_key = game_data["api_keys"]["alice"]

    result = await call(mcp, "analyze_territory", {"api_key": api_key})

    assert "expansion_opportunities" in result
    assert len(result["expansion_opportunities"]) <= 5
    if result["expansion_opportunities"]:
        opp = result["expansion_opportunities"][0]
        assert "location" in opp
        assert "terrain" in opp
        assert "nearby_resources" in opp


@pytest.mark.asyncio
async def test_analyze_territory_with_focus_area(db_session, mcp):
    """analyze_territory respects focus_area filter."""
    game_data = await create_two_player_game(mcp)
    api_key = game_data["api_keys"]["alice"]

    full = await call(mcp, "analyze_territory", {"api_key": api_key})
    focused = await call(
        mcp,
        "analyze_territory",
        {
            "api_key": api_key,
            "focus_area": {"x_min": 0, "x_max": 5, "y_min": 0, "y_max": 5},
        },
    )

    assert "error" not in focused
    # Focused area should have fewer or equal tiles
    full_total = sum(full["territory_control"].values())
    focused_total = sum(focused["territory_control"].values())
    assert focused_total <= full_total


@pytest.mark.asyncio
async def test_analyze_territory_invalid_key(db_session, mcp):
    result = await call(mcp, "analyze_territory", {"api_key": "fx_bad"})
    assert "error" in result


# ---------------------------------------------------------------------------
# evaluate_military_position
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_evaluate_military_returns_strength(db_session, mcp):
    """evaluate_military_position returns strength metrics."""
    game_data = await create_two_player_game(mcp)
    api_key = game_data["api_keys"]["alice"]

    result = await call(mcp, "evaluate_military_position", {"api_key": api_key})

    assert "error" not in result
    assert result["player"] == "alice"
    assert "military_strength" in result
    ms = result["military_strength"]
    assert "my_military_units" in ms
    assert "visible_enemy_military" in ms
    assert "strength_ratio" in ms


@pytest.mark.asyncio
async def test_evaluate_military_returns_breakdown(db_session, mcp):
    """evaluate_military_position returns unit breakdown."""
    game_data = await create_two_player_game(mcp)
    api_key = game_data["api_keys"]["alice"]

    result = await call(mcp, "evaluate_military_position", {"api_key": api_key})

    assert "unit_breakdown" in result
    assert "my_units" in result["unit_breakdown"]
    assert "enemy_units" in result["unit_breakdown"]


@pytest.mark.asyncio
async def test_evaluate_military_returns_assessment(db_session, mcp):
    """evaluate_military_position returns strategic assessment."""
    game_data = await create_two_player_game(mcp)
    api_key = game_data["api_keys"]["alice"]

    result = await call(mcp, "evaluate_military_position", {"api_key": api_key})

    assert "strategic_assessment" in result
    assert isinstance(result["strategic_assessment"], str)
    assert "threats" in result
    assert "opportunities" in result


@pytest.mark.asyncio
async def test_evaluate_military_invalid_key(db_session, mcp):
    result = await call(mcp, "evaluate_military_position", {"api_key": "fx_bad"})
    assert "error" in result


# ---------------------------------------------------------------------------
# find_resource_opportunities
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_find_resources_returns_opportunities(db_session, mcp):
    """find_resource_opportunities returns available resource sites."""
    game_data = await create_two_player_game(mcp)
    api_key = game_data["api_keys"]["alice"]

    result = await call(mcp, "find_resource_opportunities", {"api_key": api_key})

    assert "error" not in result
    assert result["player"] == "alice"
    assert "available_resources" in result
    assert "opportunities" in result
    assert len(result["opportunities"]) <= 10


@pytest.mark.asyncio
async def test_find_resources_returns_summary(db_session, mcp):
    """find_resource_opportunities returns resource summary."""
    game_data = await create_two_player_game(mcp)
    api_key = game_data["api_keys"]["alice"]

    result = await call(mcp, "find_resource_opportunities", {"api_key": api_key})

    assert "resource_summary" in result
    for key in ("food", "wood", "ore", "crystal"):
        assert key in result["resource_summary"]


@pytest.mark.asyncio
async def test_find_resources_with_filter(db_session, mcp):
    """find_resource_opportunities filters by resource_types."""
    game_data = await create_two_player_game(mcp)
    api_key = game_data["api_keys"]["alice"]

    result = await call(
        mcp,
        "find_resource_opportunities",
        {"api_key": api_key, "resource_types": ["food"]},
    )

    assert "error" not in result
    # All returned opportunities should be food
    for opp in result["opportunities"]:
        assert opp["resource"] == "food"


@pytest.mark.asyncio
async def test_find_resources_priority_scoring(db_session, mcp):
    """Opportunities are sorted by priority (highest first)."""
    game_data = await create_two_player_game(mcp)
    api_key = game_data["api_keys"]["alice"]

    result = await call(mcp, "find_resource_opportunities", {"api_key": api_key})

    opps = result["opportunities"]
    if len(opps) >= 2:
        priorities = [o["priority"] for o in opps]
        assert priorities == sorted(priorities, reverse=True)


@pytest.mark.asyncio
async def test_find_resources_strategic_advice(db_session, mcp):
    """find_resource_opportunities returns strategic advice."""
    game_data = await create_two_player_game(mcp)
    api_key = game_data["api_keys"]["alice"]

    result = await call(mcp, "find_resource_opportunities", {"api_key": api_key})

    assert "strategic_advice" in result
    assert isinstance(result["strategic_advice"], str)


@pytest.mark.asyncio
async def test_find_resources_invalid_key(db_session, mcp):
    result = await call(mcp, "find_resource_opportunities", {"api_key": "fx_bad"})
    assert "error" in result


# ---------------------------------------------------------------------------
# calculate_distances
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_calculate_distances_basic(db_session, mcp):
    """calculate_distances returns correct Manhattan distances."""
    result = await call(
        mcp,
        "calculate_distances",
        {
            "from_locations": [{"x": 0, "y": 0}],
            "to_locations": [{"x": 3, "y": 4}],
        },
    )

    assert "error" not in result
    assert result["distance_matrix"][0][0]["distance"] == 7
    assert result["summary"]["min_distance"] == 7
    assert result["summary"]["max_distance"] == 7


@pytest.mark.asyncio
async def test_calculate_distances_matrix(db_session, mcp):
    """calculate_distances returns a full distance matrix."""
    result = await call(
        mcp,
        "calculate_distances",
        {
            "from_locations": [{"x": 0, "y": 0}, {"x": 5, "y": 5}],
            "to_locations": [{"x": 1, "y": 1}, {"x": 10, "y": 10}],
        },
    )

    assert len(result["distance_matrix"]) == 2
    assert len(result["distance_matrix"][0]) == 2
    assert len(result["distance_matrix"][1]) == 2

    # (0,0) -> (1,1) = 2
    assert result["distance_matrix"][0][0]["distance"] == 2
    # (0,0) -> (10,10) = 20
    assert result["distance_matrix"][0][1]["distance"] == 20
    # (5,5) -> (1,1) = 8
    assert result["distance_matrix"][1][0]["distance"] == 8
    # (5,5) -> (10,10) = 10
    assert result["distance_matrix"][1][1]["distance"] == 10


@pytest.mark.asyncio
async def test_calculate_distances_empty_input(db_session, mcp):
    """calculate_distances handles empty input."""
    result = await call(
        mcp,
        "calculate_distances",
        {"from_locations": [], "to_locations": []},
    )

    assert result["distance_matrix"] == []
    assert result["summary"]["min_distance"] == 0


@pytest.mark.asyncio
async def test_calculate_distances_summary(db_session, mcp):
    """calculate_distances returns correct summary stats."""
    result = await call(
        mcp,
        "calculate_distances",
        {
            "from_locations": [{"x": 0, "y": 0}],
            "to_locations": [{"x": 1, "y": 0}, {"x": 3, "y": 3}],
        },
    )

    assert result["summary"]["min_distance"] == 1
    assert result["summary"]["max_distance"] == 6
    assert result["summary"]["avg_distance"] == 3.5


# ---------------------------------------------------------------------------
# get_valid_moves
# ---------------------------------------------------------------------------


async def _get_my_unit_id(mcp: Any, api_key: str) -> int:
    state = await call(mcp, "get_game_state", {"api_key": api_key})
    player = state["player"]
    for unit_id_str, unit in state["state"]["units"].items():
        if unit["owner"] == player:
            return int(unit_id_str)
    raise AssertionError("no unit found for player")


@pytest.mark.asyncio
async def test_get_valid_moves_returns_metadata(db_session, mcp):
    """get_valid_moves returns unit metadata alongside valid_tiles."""
    game_data = await create_two_player_game(mcp)
    api_key = game_data["api_keys"]["alice"]
    unit_id = await _get_my_unit_id(mcp, api_key)

    result = await call(
        mcp, "get_valid_moves", {"api_key": api_key, "unit_id": unit_id}
    )

    assert "error" not in result
    assert result["player"] == "alice"
    assert result["unit_id"] == unit_id
    assert result["unit_type"] == "worker"
    assert "current_position" in result
    assert "moves_left" in result
    assert "valid_tiles" in result
    assert isinstance(result["valid_tiles"], list)


@pytest.mark.asyncio
async def test_get_valid_moves_tiles_within_range(db_session, mcp):
    """Every returned tile is within the unit's movement range and passable."""
    game_data = await create_two_player_game(mcp)
    api_key = game_data["api_keys"]["alice"]
    unit_id = await _get_my_unit_id(mcp, api_key)

    result = await call(
        mcp, "get_valid_moves", {"api_key": api_key, "unit_id": unit_id}
    )

    moves_left = result["moves_left"]
    for tile in result["valid_tiles"]:
        assert 1 <= tile["distance"] <= moves_left
        assert tile["terrain"] not in ("water", "mountain")
        assert "x" in tile and "y" in tile
        assert "has_resource" in tile
        assert "has_improvement" in tile
        # Phase 2 gameplay-improvements: cost + path accompany every tile.
        assert tile["cost"] == tile["distance"]
        assert isinstance(tile["path"], list)
        assert len(tile["path"]) >= 1
        end = tile["path"][-1]
        assert end["x"] == tile["x"] and end["y"] == tile["y"]


@pytest.mark.asyncio
async def test_get_valid_moves_enemy_unit_rejected(db_session, mcp):
    """Requesting valid moves for an enemy unit returns an error."""
    game_data = await create_two_player_game(mcp)
    alice_key = game_data["api_keys"]["alice"]
    bob_key = game_data["api_keys"]["bob"]

    # Bob's unit ID
    bob_unit_id = await _get_my_unit_id(mcp, bob_key)

    result = await call(
        mcp, "get_valid_moves", {"api_key": alice_key, "unit_id": bob_unit_id}
    )

    assert "error" in result


@pytest.mark.asyncio
async def test_get_valid_moves_invalid_unit_id(db_session, mcp):
    """Non-existent unit id returns an error."""
    game_data = await create_two_player_game(mcp)
    api_key = game_data["api_keys"]["alice"]

    result = await call(
        mcp, "get_valid_moves", {"api_key": api_key, "unit_id": 99999}
    )

    assert "error" in result


@pytest.mark.asyncio
async def test_get_valid_moves_invalid_key(db_session, mcp):
    """Bad API key returns an error."""
    result = await call(
        mcp, "get_valid_moves", {"api_key": "fx_bad", "unit_id": 1}
    )
    assert "error" in result


# ---------------------------------------------------------------------------
# Cross-tool integration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_analysis_tools_fog_of_war(db_session, mcp):
    """Different players see different analysis results (fog-of-war)."""
    game_data = await create_two_player_game(mcp)
    alice_key = game_data["api_keys"]["alice"]
    bob_key = game_data["api_keys"]["bob"]

    alice_territory = await call(mcp, "analyze_territory", {"api_key": alice_key})
    bob_territory = await call(mcp, "analyze_territory", {"api_key": bob_key})

    assert alice_territory["player"] == "alice"
    assert bob_territory["player"] == "bob"
    # Both should have valid results
    assert "error" not in alice_territory
    assert "error" not in bob_territory
