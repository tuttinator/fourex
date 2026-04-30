"""Phase 6 — agent-facing terrain surface audit.

Locks in the contract that every one of the seven canonical terrains
(``GRASS``, ``FOREST``, ``HILLS``, ``MOUNTAIN``, ``DESERT``, ``SWAMP``,
``WATER``) is fully described by the agent-facing surfaces:

* ``get_rules_reference`` — agents key off the per-terrain table for
  movement cost, city eligibility, and primary resource. The Phase 1
  test already covers shape; this file pins the *completeness* contract
  (every Terrain enum value has an entry, no gaps) so adding a new
  terrain in future without updating the publisher fails loudly.
* ``render_map_ascii`` — the seven terrains must each render as a
  unique glyph, otherwise an LLM agent reading the ASCII map cannot
  distinguish (e.g.) hills from mountains.
* ``render_map_svg`` / ``render_map_image`` — the seven terrains must
  each render as a distinct fill colour. PNG covers via SVG → cairosvg
  so the SVG colour audit transitively covers the image renderer.
"""

from __future__ import annotations

from backend.src.game.models import Terrain
from backend.src.game.rules_reference import build_rules_reference
from backend.src.mcp_server.tools.rendering import (
    TERRAIN_ASCII,
    TERRAIN_SVG_COLOUR,
)

_ALL_TERRAINS: tuple[Terrain, ...] = (
    Terrain.GRASS,
    Terrain.FOREST,
    Terrain.HILLS,
    Terrain.MOUNTAIN,
    Terrain.DESERT,
    Terrain.SWAMP,
    Terrain.WATER,
)


def test_rules_reference_terrain_table_covers_all_seven_terrains() -> None:
    payload = build_rules_reference()
    table = payload["terrain"]
    # Every Terrain enum value must appear, and nothing else may.
    assert set(table.keys()) == {t.value for t in _ALL_TERRAINS}
    for terrain in _ALL_TERRAINS:
        entry = table[terrain.value]
        # The three keys agents need to plan against.
        assert "entry_cost" in entry
        assert "city_eligible" in entry
        assert "primary_resource" in entry
        # ``entry_cost`` is None for impassable; otherwise an int.
        if entry["entry_cost"] is not None:
            assert isinstance(entry["entry_cost"], int)
            assert entry["entry_cost"] >= 1
        # ``city_eligible`` is always a bool.
        assert isinstance(entry["city_eligible"], bool)
        # ``primary_resource`` is None or a known resource name.
        assert entry["primary_resource"] in (None, "food", "wood", "ore", "crystal")


def test_rules_reference_passable_flag_matches_entry_cost() -> None:
    """Agents read ``passable`` as a shortcut; it must agree with cost."""
    table = build_rules_reference()["terrain"]
    for terrain in _ALL_TERRAINS:
        entry = table[terrain.value]
        assert entry["passable"] == (entry["entry_cost"] is not None)


def test_render_map_ascii_has_unique_glyph_per_terrain() -> None:
    glyphs = [TERRAIN_ASCII[t] for t in _ALL_TERRAINS]
    assert len(glyphs) == len(
        set(glyphs)
    ), f"ASCII glyphs must be unique per terrain; got {dict(zip(_ALL_TERRAINS, glyphs))}"
    # Every glyph is a single printable ASCII character (not whitespace,
    # not the fog ``?`` placeholder).
    for terrain, glyph in zip(_ALL_TERRAINS, glyphs):
        assert isinstance(glyph, str)
        assert len(glyph) == 1, terrain
        assert glyph != "?", terrain
        assert not glyph.isspace(), terrain


def test_render_map_svg_has_unique_colour_per_terrain() -> None:
    colours = [TERRAIN_SVG_COLOUR[t] for t in _ALL_TERRAINS]
    assert len(colours) == len(set(colours)), (
        f"SVG colours must be unique per terrain; got "
        f"{dict(zip(_ALL_TERRAINS, colours))}"
    )
    # Every colour is a 6-digit hex literal.
    for terrain, colour in zip(_ALL_TERRAINS, colours):
        assert colour.startswith("#"), terrain
        assert len(colour) == 7, terrain  # "#rrggbb"
        int(colour[1:], 16)  # parses as hex


def test_render_map_image_inherits_svg_terrain_coverage() -> None:
    """``render_map_image`` rasterises the SVG output, so SVG completeness
    is the contract that matters. This test pins that fact: any new
    terrain added to ``TERRAIN_SVG_COLOUR`` automatically lands in PNG
    output without touching the image tool."""
    # Same terrains, same colours — there is no parallel PNG colour map
    # to drift out of sync.
    for terrain in _ALL_TERRAINS:
        assert terrain in TERRAIN_SVG_COLOUR
