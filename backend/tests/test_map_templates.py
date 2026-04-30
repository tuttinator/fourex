"""Phase 2 of the map system overhaul: parametric template registry tests.

Covers:

* Determinism: each template returns identical tiles + spawn-zone
  ordering for repeated calls with the same inputs.
* Spawn-zone validity: every zone is on a passable, city-eligible tile.
* Per-template guarantees: at least ``player_count`` zones for a
  reasonably sized map.
* Mountains stay resource-free across all templates (the Phase 1 bug
  fix must not regress under any new generator).
"""

from __future__ import annotations

import pytest

from backend.src.game.models import (
    CITY_ELIGIBLE_TERRAIN,
    TERRAIN_ENTRY_COST,
    Resource,
    Terrain,
)
from backend.src.game.rules import MAP_TEMPLATES, generate_map


@pytest.mark.parametrize("template", MAP_TEMPLATES)
def test_template_deterministic(template: str) -> None:
    """Same inputs reproduce the same tiles + zone ordering."""
    tiles_a, zones_a = generate_map(template, 24, 24, seed=11, player_count=4)
    tiles_b, zones_b = generate_map(template, 24, 24, seed=11, player_count=4)

    assert len(tiles_a) == len(tiles_b) == 24 * 24
    for a, b in zip(tiles_a, tiles_b, strict=True):
        assert a.loc == b.loc
        assert a.terrain == b.terrain
        assert a.resource == b.resource
    assert zones_a == zones_b


@pytest.mark.parametrize("template", MAP_TEMPLATES)
def test_template_returns_enough_spawn_zones(template: str) -> None:
    """Each template surfaces ≥ ``player_count`` zones for a 24×24 map."""
    _tiles, zones = generate_map(template, 24, 24, seed=11, player_count=4)
    assert len(zones) >= 4, (
        f"{template} returned only {len(zones)} zones for player_count=4"
    )


@pytest.mark.parametrize("template", MAP_TEMPLATES)
def test_spawn_zones_on_passable_city_eligible_terrain(template: str) -> None:
    """Spawn zones must be placeable cities (passable + city-eligible)."""
    tiles, zones = generate_map(template, 24, 24, seed=11, player_count=4)
    by_loc = {tile.loc: tile for tile in tiles}

    for zone in zones:
        tile = by_loc.get(zone)
        assert tile is not None, f"{template} returned zone off the map: {zone}"
        assert tile.terrain in CITY_ELIGIBLE_TERRAIN, (
            f"{template} zone {zone} is on non-city terrain {tile.terrain}"
        )
        assert TERRAIN_ENTRY_COST.get(tile.terrain) is not None, (
            f"{template} zone {zone} is on impassable terrain {tile.terrain}"
        )


@pytest.mark.parametrize("template", MAP_TEMPLATES)
def test_no_resources_on_mountains(template: str) -> None:
    """Phase 1 bug fix must hold under every Phase 2 template."""
    tiles, _zones = generate_map(template, 24, 24, seed=11, player_count=4)
    for tile in tiles:
        if tile.terrain == Terrain.MOUNTAIN:
            assert tile.resource is None


@pytest.mark.parametrize("template", MAP_TEMPLATES)
def test_template_spawn_zones_unique(template: str) -> None:
    """Spawn zones must not repeat the same tile."""
    _tiles, zones = generate_map(template, 24, 24, seed=11, player_count=4)
    assert len(zones) == len(set(zones))


def test_unknown_template_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown map template"):
        generate_map("not-a-real-template", 20, 20, seed=42, player_count=2)


def test_random_template_preserves_terrain_distribution() -> None:
    """The legacy noise generator should still emit every biome."""
    tiles, _zones = generate_map("random", 30, 30, seed=42, player_count=2)
    seen = {tile.terrain for tile in tiles}
    # Should hit at least 5 of the 7 biomes on a 30x30 random roll.
    assert len(seen) >= 5


def test_continent_has_water_margin() -> None:
    """The continent template surrounds the landmass with water."""
    tiles, _zones = generate_map("continent", 30, 30, seed=7, player_count=4)
    # Sample the corners; with a continent template the corners should
    # almost always be water.
    by_loc = {(tile.loc.x, tile.loc.y): tile for tile in tiles}
    corners = [(0, 0), (29, 0), (0, 29), (29, 29)]
    water_corners = sum(
        1 for c in corners if by_loc[c].terrain == Terrain.WATER
    )
    assert water_corners >= 3


def test_archipelago_is_majority_water() -> None:
    """The archipelago template emits more water than land."""
    tiles, _zones = generate_map("archipelago", 30, 30, seed=7, player_count=4)
    water = sum(1 for t in tiles if t.terrain == Terrain.WATER)
    land = len(tiles) - water
    assert water > land


def test_resources_only_on_valid_terrain() -> None:
    """Sanity-check the per-tile resource roll across every template."""
    for template in MAP_TEMPLATES:
        tiles, _zones = generate_map(template, 24, 24, seed=99, player_count=3)
        for tile in tiles:
            if tile.resource is None:
                continue
            # Mountains are guaranteed resource-free (asserted above).
            assert tile.terrain != Terrain.MOUNTAIN
            # Water never carries a resource.
            assert tile.terrain != Terrain.WATER
            if tile.resource == Resource.ORE:
                assert tile.terrain == Terrain.HILLS
            elif tile.resource == Resource.FOOD:
                assert tile.terrain == Terrain.GRASS
            elif tile.resource == Resource.WOOD:
                assert tile.terrain == Terrain.FOREST
