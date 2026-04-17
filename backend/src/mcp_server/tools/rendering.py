"""
Map rendering MCP tools: render_map_ascii, render_map_svg, render_map_image.

All tools accept game_id + api_key, authenticate, and apply fog of war
via redact_state() before rendering.
"""

from __future__ import annotations

import base64
from typing import Any
from xml.etree.ElementTree import Element, SubElement, tostring

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from ...auth import AuthError, authenticate
from ...database.connection import async_session_factory
from ...database.repository import GameRepository
from ...game.models import GameState, PlayerId, Terrain, UnitType
from ...game.rules import redact_state

# ---------------------------------------------------------------------------
# Terrain display constants
# ---------------------------------------------------------------------------

TERRAIN_ASCII: dict[Terrain, str] = {
    Terrain.PLAINS: ".",
    Terrain.FOREST: "T",
    Terrain.MOUNTAIN: "^",
    Terrain.WATER: "~",
}

TERRAIN_SVG_COLOUR: dict[Terrain, str] = {
    Terrain.PLAINS: "#c8e6c9",
    Terrain.FOREST: "#388e3c",
    Terrain.MOUNTAIN: "#9e9e9e",
    Terrain.WATER: "#42a5f5",
}

UNIT_ASCII: dict[UnitType, str] = {
    UnitType.SCOUT: "s",
    UnitType.WORKER: "w",
    UnitType.SOLDIER: "S",
    UnitType.ARCHER: "A",
}

# Player colours for SVG rendering and ASCII labels.
PLAYER_COLOURS = [
    "#e53935",  # red
    "#1e88e5",  # blue
    "#43a047",  # green
    "#fb8c00",  # orange
    "#8e24aa",  # purple
    "#00acc1",  # teal
    "#fdd835",  # yellow
    "#6d4c41",  # brown
]

FOG_CHAR = "?"
FOG_SVG_COLOUR = "#424242"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_redacted_state(
    api_key: str,
) -> tuple[GameState, GameState, str, str] | dict[str, str]:
    """Return (full_state, redacted_state, game_id, player_id) or error dict.

    We need the full state to know the map dimensions and to mark unseen
    tiles as fog, and the redacted state to know what the player can see.
    """
    async with async_session_factory() as session:
        try:
            auth = await authenticate(session, api_key)
        except AuthError as e:
            return {"error": str(e)}

        repo = GameRepository(session)
        game = await repo.get_game(auth.game_id)
        if game is None:
            return {"error": f"Game {auth.game_id} not found."}

        full_state = GameState.model_validate(game.state)
        redacted = redact_state(full_state, auth.player_id)

    return full_state, redacted, auth.game_id, auth.player_id


def _player_colour_index(player_id: PlayerId, players: list[PlayerId]) -> int:
    """Return the colour index for a player."""
    try:
        return players.index(player_id)
    except ValueError:
        return 0


def _player_colour(player_id: PlayerId, players: list[PlayerId]) -> str:
    idx = _player_colour_index(player_id, players)
    return PLAYER_COLOURS[idx % len(PLAYER_COLOURS)]


# ---------------------------------------------------------------------------
# ASCII rendering
# ---------------------------------------------------------------------------


def render_ascii(
    full_state: GameState,
    redacted: GameState,
    player_id: PlayerId,
) -> str:
    """Build an ASCII map string from the redacted game state.

    The full state is used only for map dimensions; only redacted data
    is shown.
    """
    w, h = full_state.map_width, full_state.map_height

    # Build a set of visible coordinates for quick lookup
    visible_coords = {(t.loc.x, t.loc.y) for t in redacted.tiles}

    # Index redacted tiles, units, and cities by coordinate
    tile_map = {(t.loc.x, t.loc.y): t for t in redacted.tiles}
    unit_map: dict[tuple[int, int], Any] = {}
    for u in redacted.units.values():
        unit_map[(u.loc.x, u.loc.y)] = u
    city_map: dict[tuple[int, int], Any] = {}
    for c in redacted.cities.values():
        city_map[(c.loc.x, c.loc.y)] = c

    # Player label mapping (first letter, uppercased, with index fallback)
    player_labels: dict[str, str] = {}
    for i, pid in enumerate(full_state.players):
        label = pid[0].upper() if pid else str(i)
        # Avoid duplicates
        if label in player_labels.values():
            label = f"{label}{i}"
        player_labels[pid] = label

    lines: list[str] = []

    # Column headers
    col_header = "    " + "".join(f"{x % 10}" for x in range(w))
    lines.append(col_header)
    lines.append("    " + "-" * w)

    for y in range(h):
        row_label = f"{y:>3}|"
        row_chars: list[str] = []
        for x in range(w):
            if (x, y) not in visible_coords:
                row_chars.append(FOG_CHAR)
                continue

            # Priority: city > unit > improvement > terrain
            if (x, y) in city_map:
                city = city_map[(x, y)]
                row_chars.append("C" if city.owner == player_id else "c")
            elif (x, y) in unit_map:
                unit = unit_map[(x, y)]
                ch = UNIT_ASCII.get(unit.type, "u")
                # Own units uppercase, enemy lowercase
                row_chars.append(ch.upper() if unit.owner == player_id else ch.lower())
            elif tile_map[(x, y)].improvement is not None:
                row_chars.append("*")
            else:
                terrain = tile_map[(x, y)].terrain
                row_chars.append(TERRAIN_ASCII.get(terrain, " "))

        lines.append(row_label + "".join(row_chars))

    # Legend
    lines.append("")
    lines.append("Legend:")
    lines.append("  . plains  T forest  ^ mountain  ~ water  ? fog")
    lines.append("  C your city  c enemy city  * improvement")
    lines.append("  S soldier  A archer  s scout  w worker  (UPPER=yours)")
    lines.append(f"  Turn {full_state.turn} | You: {player_id}")

    # Resources
    stockpile = redacted.stockpiles.get(player_id)
    if stockpile:
        lines.append(
            f"  Food:{stockpile.food} Wood:{stockpile.wood} "
            f"Ore:{stockpile.ore} Crystal:{stockpile.crystal}"
        )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# SVG rendering
# ---------------------------------------------------------------------------

TILE_SIZE = 24


def render_svg(
    full_state: GameState,
    redacted: GameState,
    player_id: PlayerId,
) -> str:
    """Build an SVG string of the visible map with fog of war."""
    w, h = full_state.map_width, full_state.map_height
    svg_w = w * TILE_SIZE
    svg_h = h * TILE_SIZE

    visible_coords = {(t.loc.x, t.loc.y) for t in redacted.tiles}
    tile_map = {(t.loc.x, t.loc.y): t for t in redacted.tiles}
    unit_map: dict[tuple[int, int], Any] = {}
    for u in redacted.units.values():
        unit_map[(u.loc.x, u.loc.y)] = u
    city_map: dict[tuple[int, int], Any] = {}
    for c in redacted.cities.values():
        city_map[(c.loc.x, c.loc.y)] = c

    svg = Element(
        "svg",
        xmlns="http://www.w3.org/2000/svg",
        width=str(svg_w),
        height=str(svg_h),
        viewBox=f"0 0 {svg_w} {svg_h}",
    )

    # Background
    SubElement(svg, "rect", width=str(svg_w), height=str(svg_h), fill="#212121")

    for y in range(h):
        for x in range(w):
            px = x * TILE_SIZE
            py = y * TILE_SIZE

            if (x, y) not in visible_coords:
                SubElement(
                    svg,
                    "rect",
                    x=str(px),
                    y=str(py),
                    width=str(TILE_SIZE),
                    height=str(TILE_SIZE),
                    fill=FOG_SVG_COLOUR,
                    stroke="#333",
                )
                continue

            tile = tile_map[(x, y)]
            fill = TERRAIN_SVG_COLOUR.get(tile.terrain, "#555")
            SubElement(
                svg,
                "rect",
                x=str(px),
                y=str(py),
                width=str(TILE_SIZE),
                height=str(TILE_SIZE),
                fill=fill,
                stroke="#555",
            )

            # Improvement marker
            if tile.improvement is not None:
                SubElement(
                    svg,
                    "circle",
                    cx=str(px + TILE_SIZE // 2),
                    cy=str(py + TILE_SIZE // 2),
                    r=str(TILE_SIZE // 6),
                    fill="#ffeb3b",
                    opacity="0.7",
                )

            # City marker
            if (x, y) in city_map:
                city = city_map[(x, y)]
                colour = _player_colour(city.owner, full_state.players)
                SubElement(
                    svg,
                    "rect",
                    x=str(px + 2),
                    y=str(py + 2),
                    width=str(TILE_SIZE - 4),
                    height=str(TILE_SIZE - 4),
                    fill=colour,
                    stroke="white",
                )
                text = SubElement(
                    svg,
                    "text",
                    x=str(px + TILE_SIZE // 2),
                    y=str(py + TILE_SIZE // 2 + 4),
                )
                text.set("text-anchor", "middle")
                text.set("font-size", "10")
                text.set("fill", "white")
                text.text = "C"

            # Unit marker
            elif (x, y) in unit_map:
                unit = unit_map[(x, y)]
                colour = _player_colour(unit.owner, full_state.players)
                SubElement(
                    svg,
                    "circle",
                    cx=str(px + TILE_SIZE // 2),
                    cy=str(py + TILE_SIZE // 2),
                    r=str(TILE_SIZE // 3),
                    fill=colour,
                )
                label = UNIT_ASCII.get(unit.type, "u").upper()
                text = SubElement(
                    svg,
                    "text",
                    x=str(px + TILE_SIZE // 2),
                    y=str(py + TILE_SIZE // 2 + 3),
                )
                text.set("text-anchor", "middle")
                text.set("font-size", "9")
                text.set("fill", "white")
                text.text = label

    return tostring(svg, encoding="unicode")


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register(mcp: FastMCP) -> None:
    """Register map rendering tools on the MCP server."""

    @mcp.tool(
        name="render_map_ascii",
        description=(
            "Render the game map as ASCII text with fog of war applied. "
            "Returns a text grid with terrain characters, unit/city markers, "
            "a legend, and resource summary. Ideal for terminal-based clients."
        ),
        annotations=ToolAnnotations(
            title="Render Map (ASCII)",
            readOnlyHint=True,
            openWorldHint=False,
        ),
        meta={"tags": ["rendering", "map"]},
    )
    async def render_map_ascii(api_key: str) -> dict[str, Any]:
        """Render the game map as ASCII text.

        Args:
            api_key: Your player API key.

        Returns:
            ASCII map string with legend and resource summary.
        """
        result = await _get_redacted_state(api_key)
        if isinstance(result, dict):
            return result
        full_state, redacted, game_id, player_id = result

        ascii_map = render_ascii(full_state, redacted, player_id)
        return {
            "game_id": game_id,
            "player": player_id,
            "turn": full_state.turn,
            "map": ascii_map,
        }

    @mcp.tool(
        name="render_map_svg",
        description=(
            "Render the game map as SVG with fog of war applied. "
            "Returns an SVG string with coloured terrain tiles, unit and city "
            "markers, and fog-of-war masking. Suitable for clients that can "
            "render SVG."
        ),
        annotations=ToolAnnotations(
            title="Render Map (SVG)",
            readOnlyHint=True,
            openWorldHint=False,
        ),
        meta={"tags": ["rendering", "map"]},
    )
    async def render_map_svg(api_key: str) -> dict[str, Any]:
        """Render the game map as SVG.

        Args:
            api_key: Your player API key.

        Returns:
            SVG string of the game map.
        """
        result = await _get_redacted_state(api_key)
        if isinstance(result, dict):
            return result
        full_state, redacted, game_id, player_id = result

        svg_str = render_svg(full_state, redacted, player_id)
        return {
            "game_id": game_id,
            "player": player_id,
            "turn": full_state.turn,
            "svg": svg_str,
        }

    @mcp.tool(
        name="render_map_image",
        description=(
            "Render the game map as a PNG image (base64-encoded) with fog of "
            "war applied. Generates an SVG internally and converts to PNG via "
            "cairosvg. Returns the base64 data string."
        ),
        annotations=ToolAnnotations(
            title="Render Map (PNG Image)",
            readOnlyHint=True,
            openWorldHint=False,
        ),
        meta={"tags": ["rendering", "map"]},
    )
    async def render_map_image(
        api_key: str,
        scale: int = 2,
    ) -> dict[str, Any]:
        """Render the game map as a base64-encoded PNG image.

        Args:
            api_key: Your player API key.
            scale: Resolution multiplier (default 2 for retina).

        Returns:
            Base64-encoded PNG data.
        """
        result = await _get_redacted_state(api_key)
        if isinstance(result, dict):
            return result
        full_state, redacted, game_id, player_id = result

        svg_str = render_svg(full_state, redacted, player_id)

        try:
            import cairosvg
        except ImportError:
            return {
                "error": (
                    "cairosvg is not installed. Install it with: " "uv add cairosvg"
                )
            }

        png_bytes = cairosvg.svg2png(
            bytestring=svg_str.encode("utf-8"),
            scale=scale,
        )
        if not isinstance(png_bytes, bytes):
            return {"error": "Failed to render map image."}

        b64 = base64.b64encode(png_bytes).decode("ascii")

        return {
            "game_id": game_id,
            "player": player_id,
            "turn": full_state.turn,
            "format": "png",
            "scale": scale,
            "image_base64": b64,
        }
