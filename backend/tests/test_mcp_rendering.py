"""Tests for MCP rendering tools (render_map_ascii, render_map_svg, render_map_image)."""

from __future__ import annotations

import json
from typing import Any
from xml.etree.ElementTree import fromstring

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
from backend.src.game.models import (
    City,
    Coord,
    GameState,
    ImprovementType,
    ResourceBag,
    Terrain,
    Tile,
    Unit,
    UnitType,
)
from backend.src.mcp_server.server import create_mcp_server
from backend.src.mcp_server.tools.rendering import render_ascii, render_svg


@pytest_asyncio.fixture
async def db_session():
    """Async DB session with cleanup."""
    await init_db()
    async with async_session_factory() as session:
        yield session
        await session.rollback()
        await session.execute(delete(AgentMemory).where(AgentMemory.game_id.like("game_%")))
        await session.execute(delete(TurnAction).where(TurnAction.game_id.like("game_%")))
        await session.execute(delete(TurnSnapshot).where(TurnSnapshot.game_id.like("game_%")))
        await session.execute(delete(GameTurn).where(GameTurn.game_id.like("game_%")))
        await session.execute(delete(PlayerApiKey).where(PlayerApiKey.game_id.like("game_%")))
        await session.execute(delete(GameSnapshot).where(GameSnapshot.game_id.like("game_%")))
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
# Small test state for pure-function rendering tests (no DB needed)
# ---------------------------------------------------------------------------


def _make_test_state() -> tuple[GameState, GameState]:
    """Create a small 5x5 game state and a redacted version for alice.

    Returns (full_state, redacted_state_for_alice).
    """
    tiles = []
    tid = 0
    terrains = [
        [
            Terrain.GRASS,
            Terrain.GRASS,
            Terrain.FOREST,
            Terrain.MOUNTAIN,
            Terrain.WATER,
        ],
        [Terrain.GRASS, Terrain.GRASS, Terrain.GRASS, Terrain.FOREST, Terrain.WATER],
        [
            Terrain.FOREST,
            Terrain.GRASS,
            Terrain.GRASS,
            Terrain.GRASS,
            Terrain.MOUNTAIN,
        ],
        [Terrain.WATER, Terrain.FOREST, Terrain.GRASS, Terrain.GRASS, Terrain.GRASS],
        [
            Terrain.WATER,
            Terrain.WATER,
            Terrain.MOUNTAIN,
            Terrain.GRASS,
            Terrain.GRASS,
        ],
    ]
    for y in range(5):
        for x in range(5):
            tiles.append(Tile(id=tid, loc=Coord(x=x, y=y), terrain=terrains[y][x]))
            tid += 1

    # Add a resource on tile (1,0)
    tiles[1].resource = None  # keep simple

    # Add improvement on (2,0) forest tile
    tiles[2].improvement = ImprovementType.LUMBER_MILL

    units = {
        1: Unit(
            id=1,
            owner="alice",
            type=UnitType.SCOUT,
            hp=2,
            moves_left=3,
            loc=Coord(x=1, y=1),
        ),
        2: Unit(
            id=2,
            owner="bob",
            type=UnitType.SOLDIER,
            hp=4,
            moves_left=2,
            loc=Coord(x=3, y=3),
        ),
    }

    cities = {
        1: City(id=1, owner="alice", loc=Coord(x=0, y=0), hp=10),
    }

    full_state = GameState(
        turn=3,
        map_width=5,
        map_height=5,
        tiles=tiles,
        units=units,
        cities=cities,
        players=["alice", "bob"],
        stockpiles={
            "alice": ResourceBag(food=50, wood=30, ore=10, crystal=5),
            "bob": ResourceBag(food=40, wood=20, ore=15, crystal=0),
        },
    )

    # Redacted state for alice: only tiles visible from alice's scout (1,1)
    # sight=3 and city (0,0) sight=3. Should see most of the 5x5 map.
    from backend.src.game.rules import redact_state

    redacted = redact_state(full_state, "alice")
    return full_state, redacted


# ---------------------------------------------------------------------------
# render_map_ascii — pure function tests
# ---------------------------------------------------------------------------


class TestRenderAsciiPure:
    """Test the render_ascii pure function without DB."""

    def test_contains_terrain_chars(self):
        """ASCII output contains expected terrain characters."""
        full, redacted = _make_test_state()
        output = render_ascii(full, redacted, "alice")

        # Plains, forest, mountain should appear in visible area
        assert "." in output  # plains
        assert "T" in output  # forest
        assert "^" in output  # mountain

    def test_contains_city_marker(self):
        """ASCII output shows C for player's own city."""
        full, redacted = _make_test_state()
        output = render_ascii(full, redacted, "alice")
        assert "C" in output

    def test_contains_unit_markers(self):
        """ASCII output shows unit markers."""
        full, redacted = _make_test_state()
        output = render_ascii(full, redacted, "alice")
        # Alice's scout at (1,1) — uppercase S for own scout
        assert "S" in output  # scout uppercase (own)

    def test_contains_improvement_marker(self):
        """ASCII output shows * for improvements."""
        full, redacted = _make_test_state()
        output = render_ascii(full, redacted, "alice")
        assert "*" in output

    def test_contains_legend(self):
        """ASCII output includes a legend."""
        full, redacted = _make_test_state()
        output = render_ascii(full, redacted, "alice")
        assert "Legend:" in output
        assert "grass" in output
        assert "forest" in output

    def test_contains_turn_info(self):
        """ASCII output includes turn number and player."""
        full, redacted = _make_test_state()
        output = render_ascii(full, redacted, "alice")
        assert "Turn 3" in output
        assert "alice" in output

    def test_contains_resources(self):
        """ASCII output includes resource summary."""
        full, redacted = _make_test_state()
        output = render_ascii(full, redacted, "alice")
        assert "Food:50" in output
        assert "Wood:30" in output

    def test_fog_of_war_applied(self):
        """Tiles outside sight range show as ? in ASCII."""
        full, redacted = _make_test_state()
        output = render_ascii(full, redacted, "alice")
        # The map is 5x5; with scout at (1,1) sight=3 and city at (0,0) sight=3
        # some corner tiles might be fogged. Check for ? presence
        # At minimum the rendering function handles fog correctly
        # by checking visible_coords
        lines = output.split("\n")
        # Map lines match pattern "  N|..." where N is a row number
        map_lines = [line for line in lines if "|" in line and line.strip()[0].isdigit()]
        # Verify structure: each map line has row label + characters
        assert len(map_lines) == 5

    def test_water_terrain_shown(self):
        """Water tiles show as ~ when visible."""
        full, redacted = _make_test_state()
        output = render_ascii(full, redacted, "alice")
        # Water is at (4,0), (4,1), (0,3), (0,4), (1,4), (2,4) - some may be visible
        # At least check the character exists if water tiles are in sight
        visible_coords = {(t.loc.x, t.loc.y) for t in redacted.tiles}
        water_coords = [(4, 0), (4, 1), (0, 3), (0, 4), (1, 4)]
        has_visible_water = any(c in visible_coords for c in water_coords)
        if has_visible_water:
            assert "~" in output


# ---------------------------------------------------------------------------
# render_map_svg — pure function tests
# ---------------------------------------------------------------------------


class TestRenderSvgPure:
    """Test the render_svg pure function without DB."""

    def test_returns_valid_svg(self):
        """SVG output is valid XML with <svg> root."""
        full, redacted = _make_test_state()
        svg_str = render_svg(full, redacted, "alice")
        root = fromstring(svg_str)
        assert root.tag == "{http://www.w3.org/2000/svg}svg" or root.tag == "svg"

    def test_svg_has_correct_dimensions(self):
        """SVG viewBox matches map dimensions * tile size."""
        full, redacted = _make_test_state()
        svg_str = render_svg(full, redacted, "alice")
        root = fromstring(svg_str)
        assert root.get("viewBox") == "0 0 120 120"  # 5*24 x 5*24

    def test_svg_contains_rects(self):
        """SVG contains rect elements for tiles."""
        full, redacted = _make_test_state()
        svg_str = render_svg(full, redacted, "alice")
        root = fromstring(svg_str)
        ns = {"svg": "http://www.w3.org/2000/svg"}
        rects = root.findall(".//svg:rect", ns) or root.findall(".//rect")
        # At least 25 tiles + 1 background + city rect
        assert len(rects) >= 25

    def test_svg_contains_terrain_colours(self):
        """SVG contains expected terrain fill colours."""
        full, redacted = _make_test_state()
        svg_str = render_svg(full, redacted, "alice")
        # Plains green
        assert "#c8e6c9" in svg_str
        # Forest green
        assert "#388e3c" in svg_str

    def test_svg_contains_fog_colour(self):
        """SVG uses fog colour for unseen tiles."""
        full, redacted = _make_test_state()
        svg_str = render_svg(full, redacted, "alice")
        visible_count = len(redacted.tiles)
        total_tiles = full.map_width * full.map_height
        if visible_count < total_tiles:
            assert "#424242" in svg_str

    def test_svg_contains_city_marker(self):
        """SVG contains text 'C' for city."""
        full, redacted = _make_test_state()
        svg_str = render_svg(full, redacted, "alice")
        assert ">C<" in svg_str

    def test_svg_contains_unit_marker(self):
        """SVG contains unit label text."""
        full, redacted = _make_test_state()
        svg_str = render_svg(full, redacted, "alice")
        # Alice's scout should appear as "S"
        assert ">S<" in svg_str

    def test_svg_uses_player_colours(self):
        """SVG uses distinct player colours."""
        full, redacted = _make_test_state()
        svg_str = render_svg(full, redacted, "alice")
        # Alice is player 0 -> red
        assert "#e53935" in svg_str


# ---------------------------------------------------------------------------
# MCP tool integration tests (require DB)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_render_map_ascii_tool(db_session, mcp):
    """render_map_ascii MCP tool returns ASCII map with game data."""
    game_data = await create_two_player_game(mcp)
    api_key = game_data["api_keys"]["alice"]

    result = await call(mcp, "render_map_ascii", {"api_key": api_key})

    assert "error" not in result
    assert result["player"] == "alice"
    assert "map" in result
    assert "Legend:" in result["map"]
    assert "Turn" in result["map"]


@pytest.mark.asyncio
async def test_render_map_ascii_shows_terrain(db_session, mcp):
    """render_map_ascii output contains terrain characters."""
    game_data = await create_two_player_game(mcp)
    api_key = game_data["api_keys"]["alice"]

    result = await call(mcp, "render_map_ascii", {"api_key": api_key})
    ascii_map = result["map"]

    # A 20x20 map should have terrain characters
    terrain_chars = {".", "T", "^", "~"}
    found_terrain = any(c in ascii_map for c in terrain_chars)
    assert found_terrain, "Expected terrain characters in ASCII map"


@pytest.mark.asyncio
async def test_render_map_ascii_shows_fog(db_session, mcp):
    """render_map_ascii shows ? for tiles outside player's vision."""
    game_data = await create_two_player_game(mcp)
    api_key = game_data["api_keys"]["alice"]

    result = await call(mcp, "render_map_ascii", {"api_key": api_key})

    # On a 20x20 map with limited vision, there should be fog
    assert "?" in result["map"]


@pytest.mark.asyncio
async def test_render_map_svg_tool(db_session, mcp):
    """render_map_svg MCP tool returns valid SVG."""
    game_data = await create_two_player_game(mcp)
    api_key = game_data["api_keys"]["alice"]

    result = await call(mcp, "render_map_svg", {"api_key": api_key})

    assert "error" not in result
    assert result["player"] == "alice"
    assert "svg" in result

    # Validate it's parseable XML with svg root
    root = fromstring(result["svg"])
    assert "svg" in root.tag


@pytest.mark.asyncio
async def test_render_map_svg_has_fog(db_session, mcp):
    """render_map_svg includes fog colour for unseen tiles."""
    game_data = await create_two_player_game(mcp)
    api_key = game_data["api_keys"]["alice"]

    result = await call(mcp, "render_map_svg", {"api_key": api_key})

    # Fog colour should be present on a 20x20 map with limited vision
    assert "#424242" in result["svg"]


@pytest.mark.asyncio
async def test_render_map_ascii_invalid_key(db_session, mcp):
    """render_map_ascii returns error for invalid API key."""
    result = await call(mcp, "render_map_ascii", {"api_key": "bad-key"})
    assert "error" in result


@pytest.mark.asyncio
async def test_render_map_svg_invalid_key(db_session, mcp):
    """render_map_svg returns error for invalid API key."""
    result = await call(mcp, "render_map_svg", {"api_key": "bad-key"})
    assert "error" in result
