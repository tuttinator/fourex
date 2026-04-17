"""
Analysis MCP tools: analyze_territory, evaluate_military_position,
find_resource_opportunities, calculate_distances.

Ported from the original agents/src/fastmcp_server.py to the real MCP
server. All tools use fog-of-war-redacted state via the authenticated
player's API key.
"""

from typing import Any, cast

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from ...auth import AuthError, authenticate
from ...database.connection import async_session_factory
from ...database.repository import GameRepository
from ...game.models import GameState, Resource, Terrain, UnitType
from ...game.rules import get_valid_moves as compute_valid_moves
from ...game.rules import redact_state


def _calculate_resource_priority(resource_type: str, distance: float) -> float:
    """Calculate priority score for a resource opportunity."""
    base_priority = {
        "food": 3.0,
        "wood": 2.0,
        "ore": 2.5,
        "crystal": 4.0,
    }.get(resource_type, 1.0)

    if distance is None or distance == float("inf"):
        distance_modifier = 0.1
    else:
        distance_modifier = max(0.1, 1.0 / (1.0 + distance * 0.2))

    return round(base_priority * distance_modifier, 3)


def _generate_military_assessment(
    my_strength: int, enemy_strength: int, threats: list[Any], opportunities: list[Any]
) -> str:
    """Generate a strategic military assessment."""
    if my_strength > enemy_strength * 1.5:
        stance = "You have a strong military advantage. Consider aggressive expansion."
    elif my_strength > enemy_strength:
        stance = "You have a slight military edge. Maintain readiness while expanding."
    elif my_strength == enemy_strength:
        stance = "Military forces are balanced. Focus on positioning and economy."
    else:
        stance = "You are at a military disadvantage. Prioritise defence and unit production."

    threat_text = (
        f" {len(threats)} immediate threats detected."
        if threats
        else " No immediate threats."
    )
    opportunity_text = (
        f" {len(opportunities)} attack opportunities available."
        if opportunities
        else " No clear attack opportunities."
    )

    return stance + threat_text + opportunity_text


async def _get_redacted_state(
    api_key: str,
) -> tuple[GameState, str, str] | dict[str, str]:
    """Authenticate and return (redacted_state, game_id, player_id) or error dict."""
    async with async_session_factory() as session:
        try:
            auth = await authenticate(session, api_key)
        except AuthError as e:
            return {"error": str(e)}

        repo = GameRepository(session)
        game = await repo.get_game(auth.game_id)
        if game is None:
            return {"error": f"Game {auth.game_id} not found."}

        state = GameState.model_validate(game.state)
        redacted = redact_state(state, auth.player_id)

    return redacted, auth.game_id, auth.player_id


def register(mcp: FastMCP) -> None:
    """Register analysis tools on the MCP server."""

    @mcp.tool(
        name="analyze_territory",
        description=(
            "Analyse territorial control and expansion opportunities. "
            "Returns tile counts (owned, neutral, enemy), resource distribution, "
            "and the top expansion sites ranked by nearby resource count. "
            "All data is fog-of-war-redacted to your sight range."
        ),
        annotations=ToolAnnotations(
            title="Analyse Territory",
            readOnlyHint=True,
            openWorldHint=False,
        ),
        meta={"tags": ["analysis", "strategy"]},
    )
    async def analyze_territory(
        api_key: str,
        focus_area: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        """Analyse territorial control and find expansion opportunities.

        Args:
            api_key: Your player API key.
            focus_area: Optional bounding box to focus analysis on.
                Keys: x_min, x_max, y_min, y_max.

        Returns:
            Territory control summary, resource distribution, and top
            expansion opportunities.
        """
        result = await _get_redacted_state(api_key)
        if isinstance(result, dict):
            return result
        state, game_id, player_id = result

        tiles = state.tiles
        if focus_area:
            x_min = focus_area.get("x_min", 0)
            x_max = focus_area.get("x_max", state.map_width)
            y_min = focus_area.get("y_min", 0)
            y_max = focus_area.get("y_max", state.map_height)
            tiles = [
                t
                for t in tiles
                if x_min <= t.loc.x <= x_max and y_min <= t.loc.y <= y_max
            ]

        my_tiles = []
        neutral_tiles = []
        enemy_tiles = []
        resource_tiles = []

        for tile in tiles:
            if tile.owner == player_id:
                my_tiles.append(tile)
            elif tile.owner is None:
                neutral_tiles.append(tile)
            else:
                enemy_tiles.append(tile)

            if tile.resource:
                resource_tiles.append(tile)

        # Find expansion opportunities on neutral plains/forest tiles
        expansion_opportunities = []
        for tile in neutral_tiles:
            if tile.terrain in (Terrain.PLAINS, Terrain.FOREST):
                nearby_resources = sum(
                    1
                    for rt in resource_tiles
                    if abs(rt.loc.x - tile.loc.x) + abs(rt.loc.y - tile.loc.y) <= 3
                )
                expansion_opportunities.append(
                    {
                        "location": {"x": tile.loc.x, "y": tile.loc.y},
                        "terrain": tile.terrain.value,
                        "nearby_resources": nearby_resources,
                        "resource": tile.resource.value if tile.resource else None,
                    }
                )

        expansion_opportunities.sort(
            key=lambda x: int(x["nearby_resources"]),
            reverse=True,
        )

        return {
            "game_id": game_id,
            "player": player_id,
            "territory_control": {
                "my_tiles": len(my_tiles),
                "neutral_tiles": len(neutral_tiles),
                "enemy_tiles": len(enemy_tiles),
            },
            "resource_distribution": {
                "food_sites": len(
                    [t for t in resource_tiles if t.resource == Resource.FOOD]
                ),
                "wood_sites": len(
                    [t for t in resource_tiles if t.resource == Resource.WOOD]
                ),
                "ore_sites": len(
                    [t for t in resource_tiles if t.resource == Resource.ORE]
                ),
                "crystal_sites": len(
                    [t for t in resource_tiles if t.resource == Resource.CRYSTAL]
                ),
            },
            "expansion_opportunities": expansion_opportunities[:5],
            "strategic_analysis": (
                f"You control {len(my_tiles)} tiles out of {len(tiles)} visible. "
                f"There are {len(expansion_opportunities)} potential expansion sites visible."
            ),
        }

    @mcp.tool(
        name="evaluate_military_position",
        description=(
            "Assess military strength and strategic positioning. "
            "Returns unit counts, strength ratio, nearby threats to your "
            "cities, and attack opportunities where you outnumber the enemy. "
            "All data is fog-of-war-redacted."
        ),
        annotations=ToolAnnotations(
            title="Evaluate Military Position",
            readOnlyHint=True,
            openWorldHint=False,
        ),
        meta={"tags": ["analysis", "strategy"]},
    )
    async def evaluate_military_position(
        api_key: str,
        include_predictions: bool = True,
    ) -> dict[str, Any]:
        """Assess military strength and strategic positioning.

        Args:
            api_key: Your player API key.
            include_predictions: Include combat outcome predictions
                (default True).

        Returns:
            Military strength comparison, threats, attack opportunities,
            and strategic assessment.
        """
        result = await _get_redacted_state(api_key)
        if isinstance(result, dict):
            return result
        state, game_id, player_id = result

        my_units = [u for u in state.units.values() if u.owner == player_id]
        enemy_units = [u for u in state.units.values() if u.owner != player_id]

        military_types = {UnitType.SOLDIER, UnitType.ARCHER}
        my_military_strength = sum(1 for u in my_units if u.type in military_types)
        enemy_military_strength = sum(
            1 for u in enemy_units if u.type in military_types
        )

        # Identify threats: enemy military units within range 3 of our cities
        threats = []
        for enemy_unit in enemy_units:
            if enemy_unit.type in military_types:
                for city in state.cities.values():
                    if city.owner == player_id:
                        distance = enemy_unit.loc.distance_to(city.loc)
                        if distance <= 3:
                            threats.append(
                                {
                                    "type": "city_threat",
                                    "enemy_unit": enemy_unit.type.value,
                                    "enemy_location": {
                                        "x": enemy_unit.loc.x,
                                        "y": enemy_unit.loc.y,
                                    },
                                    "threatened_city": city.id,
                                    "distance": distance,
                                }
                            )

        # Identify attack opportunities: enemy units near 2+ of our units
        opportunities = []
        for enemy_unit in enemy_units:
            nearby_my_units = [
                u for u in my_units if u.loc.distance_to(enemy_unit.loc) <= 2
            ]
            if len(nearby_my_units) > 1:
                opportunities.append(
                    {
                        "type": "attack_opportunity",
                        "target": enemy_unit.type.value,
                        "target_location": {
                            "x": enemy_unit.loc.x,
                            "y": enemy_unit.loc.y,
                        },
                        "available_attackers": len(nearby_my_units),
                    }
                )

        # Build unit breakdown
        my_breakdown: dict[str, int] = {}
        for u in my_units:
            my_breakdown[u.type.value] = my_breakdown.get(u.type.value, 0) + 1
        enemy_breakdown: dict[str, int] = {}
        for u in enemy_units:
            enemy_breakdown[u.type.value] = enemy_breakdown.get(u.type.value, 0) + 1

        return {
            "game_id": game_id,
            "player": player_id,
            "military_strength": {
                "my_military_units": my_military_strength,
                "visible_enemy_military": enemy_military_strength,
                "strength_ratio": round(
                    my_military_strength / max(enemy_military_strength, 1), 2
                ),
            },
            "unit_breakdown": {
                "my_units": my_breakdown,
                "enemy_units": enemy_breakdown,
            },
            "threats": threats,
            "opportunities": opportunities,
            "strategic_assessment": _generate_military_assessment(
                my_military_strength, enemy_military_strength, threats, opportunities
            ),
        }

    @mcp.tool(
        name="find_resource_opportunities",
        description=(
            "Identify available resource sites and development opportunities. "
            "Returns unimproved, accessible resource tiles ranked by priority "
            "(crystal > food > ore > wood, adjusted for distance). "
            "All data is fog-of-war-redacted."
        ),
        annotations=ToolAnnotations(
            title="Find Resource Opportunities",
            readOnlyHint=True,
            openWorldHint=False,
        ),
        meta={"tags": ["analysis", "strategy"]},
    )
    async def find_resource_opportunities(
        api_key: str,
        resource_types: list[str] | None = None,
    ) -> dict[str, Any]:
        """Identify available resource sites and development opportunities.

        Args:
            api_key: Your player API key.
            resource_types: Optional filter for specific resource types
                (food, wood, ore, crystal).

        Returns:
            Top 10 resource opportunities ranked by priority, resource
            summary counts, and strategic advice.
        """
        result = await _get_redacted_state(api_key)
        if isinstance(result, dict):
            return result
        state, game_id, player_id = result

        resource_opportunities = []

        for tile in state.tiles:
            if not tile.resource or tile.improvement:
                continue

            # Only accessible tiles (unowned or owned by us)
            if tile.owner is not None and tile.owner != player_id:
                continue

            # Calculate distance to nearest friendly unit/city
            min_distance = float("inf")
            for unit in state.units.values():
                if unit.owner == player_id:
                    distance = unit.loc.distance_to(tile.loc)
                    min_distance = min(min_distance, distance)

            for city in state.cities.values():
                if city.owner == player_id:
                    distance = city.loc.distance_to(tile.loc)
                    min_distance = min(min_distance, distance)

            resource_name = tile.resource.value
            if resource_types and resource_name not in resource_types:
                continue

            resource_opportunities.append(
                {
                    "location": {"x": tile.loc.x, "y": tile.loc.y},
                    "resource": resource_name,
                    "terrain": tile.terrain.value,
                    "owner": tile.owner,
                    "distance_to_nearest_unit": (
                        min_distance if min_distance != float("inf") else None
                    ),
                    "priority": _calculate_resource_priority(
                        resource_name, min_distance
                    ),
                }
            )

        resource_opportunities.sort(
            key=lambda x: float(x["priority"]),
            reverse=True,
        )

        # Strategic advice
        stockpile = state.stockpiles.get(player_id)
        advice_parts: list[str] = []
        if stockpile:
            if stockpile.food < 20:
                food_ops = [
                    o for o in resource_opportunities if o["resource"] == "food"
                ]
                if food_ops:
                    food_loc = cast(dict[str, Any], food_ops[0]["location"])
                    advice_parts.append(
                        f"Low food ({stockpile.food}). Priority: develop food "
                        f"site at ({food_loc['x']},{food_loc['y']})."
                    )
            if stockpile.wood < 10:
                wood_ops = [
                    o for o in resource_opportunities if o["resource"] == "wood"
                ]
                if wood_ops:
                    wood_loc = cast(dict[str, Any], wood_ops[0]["location"])
                    advice_parts.append(
                        f"Low wood ({stockpile.wood}). Consider wood site at "
                        f"({wood_loc['x']},{wood_loc['y']})."
                    )
            crystal_ops = [
                o for o in resource_opportunities if o["resource"] == "crystal"
            ]
            if crystal_ops:
                crys_loc = cast(dict[str, Any], crystal_ops[0]["location"])
                advice_parts.append(
                    f"Crystal available at ({crys_loc['x']},{crys_loc['y']}) - high priority."
                )

        strategic_advice = (
            " ".join(advice_parts)
            if advice_parts
            else "Resource levels adequate. Focus on expansion."
        )

        return {
            "game_id": game_id,
            "player": player_id,
            "available_resources": len(resource_opportunities),
            "opportunities": resource_opportunities[:10],
            "resource_summary": {
                "food": len(
                    [r for r in resource_opportunities if r["resource"] == "food"]
                ),
                "wood": len(
                    [r for r in resource_opportunities if r["resource"] == "wood"]
                ),
                "ore": len(
                    [r for r in resource_opportunities if r["resource"] == "ore"]
                ),
                "crystal": len(
                    [r for r in resource_opportunities if r["resource"] == "crystal"]
                ),
            },
            "strategic_advice": strategic_advice,
        }

    @mcp.tool(
        name="get_valid_moves",
        description=(
            "List every tile a specific unit can legally move to this turn. "
            "Filtered by movement range, passable terrain, unoccupied tiles, "
            "and your fog-of-war vision. Use this to avoid wasting a turn on "
            "a rejected MOVE action."
        ),
        annotations=ToolAnnotations(
            title="Get Valid Moves",
            readOnlyHint=True,
            openWorldHint=False,
        ),
        meta={"tags": ["analysis", "utility"]},
    )
    async def get_valid_moves(
        api_key: str,
        unit_id: int,
    ) -> dict[str, Any]:
        """Return legal move destinations for one of your units.

        Args:
            api_key: Your player API key.
            unit_id: The ID of a unit you own and can see.

        Returns:
            Unit metadata (``unit_id``, ``unit_type``, ``current_position``,
            ``moves_left``) and a ``valid_tiles`` list. Each tile entry has
            ``x``, ``y``, ``terrain``, ``has_resource``, ``resource_type``,
            ``has_improvement``, ``owner``, and ``distance``.
        """
        result = await _get_redacted_state(api_key)
        if isinstance(result, dict):
            return result
        state, game_id, player_id = result

        unit = state.units.get(unit_id)
        if unit is None:
            return {"error": f"Unit {unit_id} is not visible or does not exist."}
        if unit.owner != player_id:
            return {"error": f"Unit {unit_id} is not owned by {player_id}."}

        visible_coords = {tile.loc for tile in state.tiles}
        valid_tiles = compute_valid_moves(state, unit_id, visible_coords)

        return {
            "game_id": game_id,
            "player": player_id,
            "unit_id": unit.id,
            "unit_type": unit.type.value,
            "current_position": {"x": unit.loc.x, "y": unit.loc.y},
            "moves_left": unit.moves_left,
            "valid_tiles": valid_tiles,
        }

    @mcp.tool(
        name="calculate_distances",
        description=(
            "Calculate Manhattan distances between two sets of map coordinates. "
            "Returns a full distance matrix plus min/max/average summary. "
            "Does not require authentication."
        ),
        annotations=ToolAnnotations(
            title="Calculate Distances",
            readOnlyHint=True,
            openWorldHint=False,
        ),
        meta={"tags": ["analysis", "utility"]},
    )
    async def calculate_distances(
        from_locations: list[dict[str, int]],
        to_locations: list[dict[str, int]],
    ) -> dict[str, Any]:
        """Calculate Manhattan distances between coordinate sets.

        Args:
            from_locations: List of starting coordinates, each with x and y.
            to_locations: List of target coordinates, each with x and y.

        Returns:
            Full distance matrix and summary statistics.
        """
        if not from_locations or not to_locations:
            return {
                "distance_matrix": [],
                "summary": {"min_distance": 0, "max_distance": 0, "avg_distance": 0},
            }

        distance_matrix = []
        all_distances: list[int] = []

        for i, from_loc in enumerate(from_locations):
            row = []
            for j, to_loc in enumerate(to_locations):
                distance = abs(from_loc["x"] - to_loc["x"]) + abs(
                    from_loc["y"] - to_loc["y"]
                )
                row.append(
                    {
                        "from_index": i,
                        "to_index": j,
                        "from_location": from_loc,
                        "to_location": to_loc,
                        "distance": distance,
                    }
                )
                all_distances.append(distance)
            distance_matrix.append(row)

        return {
            "distance_matrix": distance_matrix,
            "summary": {
                "min_distance": min(all_distances),
                "max_distance": max(all_distances),
                "avg_distance": round(sum(all_distances) / len(all_distances), 2),
            },
        }
