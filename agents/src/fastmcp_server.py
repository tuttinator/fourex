#!/usr/bin/env python3
"""
FastMCP server for 4X game tools.
Provides tools for game state analysis, action validation, and strategic planning.
"""

import asyncio
import json
from typing import Any

import structlog
from fastmcp import FastMCP
from pydantic import BaseModel, Field

from .agent import GameClient

# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer(),
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()

# Initialize FastMCP server
mcp = FastMCP("4X Game Analysis Server")

# Global game client (initialized on startup)
game_client: GameClient | None = None


# Input/Output models
class GameStateRequest(BaseModel):
    game_id: str = Field(description="The ID of the game to analyze")
    player_id: str = Field(description="The player perspective for fog-of-war")


class TerritoryAnalysisRequest(BaseModel):
    game_id: str = Field(description="The ID of the game to analyze")
    player_id: str = Field(description="The player perspective for fog-of-war")
    focus_area: dict[str, int] | None = Field(
        default=None,
        description="Optional area to focus analysis on with x_min, x_max, y_min, y_max",
    )


class MilitaryAnalysisRequest(BaseModel):
    game_id: str = Field(description="The ID of the game to analyze")
    player_id: str = Field(description="The player perspective for fog-of-war")
    include_predictions: bool = Field(
        default=True, description="Include combat outcome predictions"
    )


class ResourceOpportunitiesRequest(BaseModel):
    game_id: str = Field(description="The ID of the game to analyze")
    player_id: str = Field(description="The player perspective for fog-of-war")
    resource_types: list[str] | None = Field(
        default=None,
        description="Specific resource types to look for (food, wood, ore, crystal)",
    )


class ActionValidationRequest(BaseModel):
    game_id: str = Field(description="The ID of the game to analyze")
    player_id: str = Field(description="The player perspective for fog-of-war")
    actions: list[dict[str, Any]] = Field(description="List of actions to validate")


class DistanceCalculationRequest(BaseModel):
    from_locations: list[dict[str, int]] = Field(
        description="List of starting coordinates with x and y keys"
    )
    to_locations: list[dict[str, int]] = Field(
        description="List of target coordinates with x and y keys"
    )


@mcp.tool()
async def get_game_state(request: GameStateRequest) -> str:
    """Retrieve the current game state for analysis within fog of war."""
    logger.info(
        "Getting game state", game_id=request.game_id, player_id=request.player_id
    )

    if not game_client:
        return json.dumps({"error": "Game client not initialized"})

    try:
        # Get the raw game state
        game_state = game_client.get_game_state(request.game_id)

        # Apply fog of war by filtering to only visible elements
        visible_tiles = _get_visible_tiles(game_state, request.player_id)
        visible_units = {
            uid: unit
            for uid, unit in game_state.units.items()
            if (unit.loc.x, unit.loc.y) in visible_tiles
        }
        visible_cities = {
            cid: city
            for cid, city in game_state.cities.items()
            if (city.loc.x, city.loc.y) in visible_tiles
        }

        # Create filtered state summary
        state_summary = {
            "turn": game_state.turn,
            "max_turns": game_state.max_turns,
            "map_size": {
                "width": game_state.map_width,
                "height": game_state.map_height,
            },
            "my_units": len(
                [u for u in visible_units.values() if u.owner == request.player_id]
            ),
            "visible_enemy_units": len(
                [u for u in visible_units.values() if u.owner != request.player_id]
            ),
            "my_cities": len(
                [c for c in visible_cities.values() if c.owner == request.player_id]
            ),
            "visible_enemy_cities": len(
                [c for c in visible_cities.values() if c.owner != request.player_id]
            ),
            "my_resources": game_state.stockpiles.get(
                request.player_id, {"food": 0, "wood": 0, "ore": 0, "crystal": 0}
            ),
            "visible_tiles_count": len(visible_tiles),
            "players": game_state.players,
        }

        return json.dumps(state_summary, indent=2)

    except Exception as e:
        logger.error("Error getting game state", error=str(e))
        return json.dumps({"error": f"Failed to get game state: {str(e)}"})


@mcp.tool()
async def analyze_territory(request: TerritoryAnalysisRequest) -> str:
    """Analyze territorial control and expansion opportunities."""
    logger.info(
        "Analyzing territory", game_id=request.game_id, player_id=request.player_id
    )

    if not game_client:
        return json.dumps({"error": "Game client not initialized"})

    try:
        game_state = game_client.get_game_state(request.game_id)
        visible_tiles = _get_visible_tiles(game_state, request.player_id)

        # Analyze territory control
        my_tiles = []
        neutral_tiles = []
        enemy_tiles = []
        resource_tiles = []

        for tile in game_state.tiles:
            if (tile.loc.x, tile.loc.y) not in visible_tiles:
                continue

            if tile.owner == request.player_id:
                my_tiles.append(tile)
            elif tile.owner is None:
                neutral_tiles.append(tile)
            else:
                enemy_tiles.append(tile)

            if tile.resource:
                resource_tiles.append(tile)

        # Find expansion opportunities
        expansion_opportunities = []
        for tile in neutral_tiles:
            if tile.terrain in ["plains", "forest"]:  # Good for cities
                nearby_resources = sum(
                    1
                    for rt in resource_tiles
                    if abs(rt.loc.x - tile.loc.x) + abs(rt.loc.y - tile.loc.y) <= 3
                )
                expansion_opportunities.append(
                    {
                        "location": {"x": tile.loc.x, "y": tile.loc.y},
                        "terrain": tile.terrain,
                        "nearby_resources": nearby_resources,
                        "resource": tile.resource,
                    }
                )

        analysis = {
            "territory_control": {
                "my_tiles": len(my_tiles),
                "neutral_tiles": len(neutral_tiles),
                "enemy_tiles": len(enemy_tiles),
            },
            "resource_distribution": {
                "food_sites": len([t for t in resource_tiles if t.resource == "food"]),
                "wood_sites": len([t for t in resource_tiles if t.resource == "wood"]),
                "ore_sites": len([t for t in resource_tiles if t.resource == "ore"]),
                "crystal_sites": len(
                    [t for t in resource_tiles if t.resource == "crystal"]
                ),
            },
            "expansion_opportunities": sorted(
                expansion_opportunities,
                key=lambda x: x["nearby_resources"],
                reverse=True,
            )[:5],
            "strategic_analysis": f"You control {len(my_tiles)} tiles out of {len(visible_tiles)} visible. "
            f"There are {len(expansion_opportunities)} potential expansion sites visible.",
        }

        return json.dumps(analysis, indent=2)

    except Exception as e:
        logger.error("Error analyzing territory", error=str(e))
        return json.dumps({"error": f"Failed to analyze territory: {str(e)}"})


@mcp.tool()
async def evaluate_military_position(request: MilitaryAnalysisRequest) -> str:
    """Assess military strength and strategic positioning."""
    logger.info(
        "Evaluating military position",
        game_id=request.game_id,
        player_id=request.player_id,
    )

    if not game_client:
        return json.dumps({"error": "Game client not initialized"})

    try:
        game_state = game_client.get_game_state(request.game_id)
        visible_tiles = _get_visible_tiles(game_state, request.player_id)

        # Analyze military units
        my_units = [
            u
            for u in game_state.units.values()
            if u.owner == request.player_id and (u.loc.x, u.loc.y) in visible_tiles
        ]
        enemy_units = [
            u
            for u in game_state.units.values()
            if u.owner != request.player_id and (u.loc.x, u.loc.y) in visible_tiles
        ]

        # Calculate military strength
        my_military_strength = sum(
            1 for u in my_units if u.type in ["soldier", "archer"]
        )
        enemy_military_strength = sum(
            1 for u in enemy_units if u.type in ["soldier", "archer"]
        )

        # Identify threats and opportunities
        threats = []
        opportunities = []

        for enemy_unit in enemy_units:
            if enemy_unit.type in ["soldier", "archer"]:
                # Check if enemy unit threatens our cities
                for city_id, city in game_state.cities.items():
                    if city.owner == request.player_id:
                        distance = abs(enemy_unit.loc.x - city.loc.x) + abs(
                            enemy_unit.loc.y - city.loc.y
                        )
                        if distance <= 3:  # Within threat range
                            threats.append(
                                {
                                    "type": "city_threat",
                                    "enemy_unit": enemy_unit.type,
                                    "enemy_location": {
                                        "x": enemy_unit.loc.x,
                                        "y": enemy_unit.loc.y,
                                    },
                                    "threatened_city": city_id,
                                    "distance": distance,
                                }
                            )

        # Check for vulnerable enemy units
        for enemy_unit in enemy_units:
            nearby_my_units = [
                u
                for u in my_units
                if abs(u.loc.x - enemy_unit.loc.x) + abs(u.loc.y - enemy_unit.loc.y)
                <= 2
            ]
            if len(nearby_my_units) > 1:  # We can potentially overwhelm
                opportunities.append(
                    {
                        "type": "attack_opportunity",
                        "target": enemy_unit.type,
                        "target_location": {
                            "x": enemy_unit.loc.x,
                            "y": enemy_unit.loc.y,
                        },
                        "available_attackers": len(nearby_my_units),
                    }
                )

        analysis = {
            "military_strength": {
                "my_military_units": my_military_strength,
                "visible_enemy_military": enemy_military_strength,
                "strength_ratio": my_military_strength
                / max(enemy_military_strength, 1),
            },
            "unit_breakdown": {
                "my_units": {
                    unit.type: len([u for u in my_units if u.type == unit.type])
                    for unit in my_units
                },
                "enemy_units": {
                    unit.type: len([u for u in enemy_units if u.type == unit.type])
                    for unit in enemy_units
                },
            },
            "threats": threats,
            "opportunities": opportunities,
            "strategic_assessment": _generate_military_assessment(
                my_military_strength, enemy_military_strength, threats, opportunities
            ),
        }

        return json.dumps(analysis, indent=2)

    except Exception as e:
        logger.error("Error evaluating military position", error=str(e))
        return json.dumps({"error": f"Failed to evaluate military position: {str(e)}"})


@mcp.tool()
async def find_resource_opportunities(request: ResourceOpportunitiesRequest) -> str:
    """Identify available resource sites and development opportunities."""
    logger.info(
        "Finding resource opportunities",
        game_id=request.game_id,
        player_id=request.player_id,
    )

    if not game_client:
        return json.dumps({"error": "Game client not initialized"})

    try:
        game_state = game_client.get_game_state(request.game_id)
        visible_tiles = _get_visible_tiles(game_state, request.player_id)

        # Find resource tiles
        resource_opportunities = []

        for tile in game_state.tiles:
            if (tile.loc.x, tile.loc.y) not in visible_tiles:
                continue

            if (
                tile.resource and not tile.improvement
            ):  # Has resource but no improvement
                # Check if we can access it (not owned by enemy)
                accessible = tile.owner is None or tile.owner == request.player_id

                if accessible:
                    # Calculate distance to nearest friendly unit/city
                    min_distance = float("inf")
                    for unit in game_state.units.values():
                        if unit.owner == request.player_id:
                            distance = abs(unit.loc.x - tile.loc.x) + abs(
                                unit.loc.y - tile.loc.y
                            )
                            min_distance = min(min_distance, distance)

                    for city in game_state.cities.values():
                        if city.owner == request.player_id:
                            distance = abs(city.loc.x - tile.loc.x) + abs(
                                city.loc.y - tile.loc.y
                            )
                            min_distance = min(min_distance, distance)

                    if (
                        request.resource_types is None
                        or tile.resource in request.resource_types
                    ):
                        resource_opportunities.append(
                            {
                                "location": {"x": tile.loc.x, "y": tile.loc.y},
                                "resource": tile.resource,
                                "terrain": tile.terrain,
                                "owner": tile.owner,
                                "distance_to_nearest_unit": (
                                    min_distance
                                    if min_distance != float("inf")
                                    else None
                                ),
                                "priority": _calculate_resource_priority(
                                    tile.resource, min_distance
                                ),
                            }
                        )

        # Sort by priority
        resource_opportunities.sort(key=lambda x: x["priority"], reverse=True)

        analysis = {
            "available_resources": len(resource_opportunities),
            "opportunities": resource_opportunities[:10],  # Top 10
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
            "strategic_advice": _generate_resource_advice(
                resource_opportunities, game_state, request.player_id
            ),
        }

        return json.dumps(analysis, indent=2)

    except Exception as e:
        logger.error("Error finding resource opportunities", error=str(e))
        return json.dumps({"error": f"Failed to find resource opportunities: {str(e)}"})


@mcp.tool()
async def validate_actions(request: ActionValidationRequest) -> str:
    """Validate a list of potential actions."""
    logger.info(
        "Validating actions",
        game_id=request.game_id,
        player_id=request.player_id,
        action_count=len(request.actions),
    )

    if not game_client:
        return json.dumps({"error": "Game client not initialized"})

    try:
        game_state = game_client.get_game_state(request.game_id)

        validation_results = []

        for i, action in enumerate(request.actions):
            result = _validate_single_action(game_state, action, request.player_id)
            result["action_index"] = i
            validation_results.append(result)

        summary = {
            "total_actions": len(request.actions),
            "valid_actions": len([r for r in validation_results if r["valid"]]),
            "invalid_actions": len([r for r in validation_results if not r["valid"]]),
            "validation_results": validation_results,
        }

        return json.dumps(summary, indent=2)

    except Exception as e:
        logger.error("Error validating actions", error=str(e))
        return json.dumps({"error": f"Failed to validate actions: {str(e)}"})


@mcp.tool()
async def calculate_distances(request: DistanceCalculationRequest) -> str:
    """Calculate distances between coordinates."""
    logger.info(
        "Calculating distances",
        from_count=len(request.from_locations),
        to_count=len(request.to_locations),
    )

    try:
        distance_matrix = []

        for i, from_loc in enumerate(request.from_locations):
            row = []
            for j, to_loc in enumerate(request.to_locations):
                # Manhattan distance
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
            distance_matrix.append(row)

        # Also provide some useful summaries
        all_distances = [d["distance"] for row in distance_matrix for d in row]

        result = {
            "distance_matrix": distance_matrix,
            "summary": {
                "min_distance": min(all_distances) if all_distances else 0,
                "max_distance": max(all_distances) if all_distances else 0,
                "avg_distance": (
                    sum(all_distances) / len(all_distances) if all_distances else 0
                ),
            },
        }

        return json.dumps(result, indent=2)

    except Exception as e:
        logger.error("Error calculating distances", error=str(e))
        return json.dumps({"error": f"Failed to calculate distances: {str(e)}"})


# Helper functions
def _get_visible_tiles(game_state, player_id: str) -> set:
    """Calculate visible tiles for a player (simple implementation)."""
    visible_tiles = set()
    sight_range = 2

    # Add visibility around units
    for unit in game_state.units.values():
        if unit.owner == player_id:
            for dx in range(-sight_range, sight_range + 1):
                for dy in range(-sight_range, sight_range + 1):
                    if abs(dx) + abs(dy) <= sight_range:
                        x = unit.loc.x + dx
                        y = unit.loc.y + dy
                        if (
                            0 <= x < game_state.map_width
                            and 0 <= y < game_state.map_height
                        ):
                            visible_tiles.add((x, y))

    # Add visibility around cities
    for city in game_state.cities.values():
        if city.owner == player_id:
            for dx in range(-sight_range, sight_range + 1):
                for dy in range(-sight_range, sight_range + 1):
                    if abs(dx) + abs(dy) <= sight_range:
                        x = city.loc.x + dx
                        y = city.loc.y + dy
                        if (
                            0 <= x < game_state.map_width
                            and 0 <= y < game_state.map_height
                        ):
                            visible_tiles.add((x, y))

    return visible_tiles


def _generate_military_assessment(
    my_strength: int, enemy_strength: int, threats: list, opportunities: list
) -> str:
    """Generate a strategic military assessment."""
    if my_strength > enemy_strength * 1.5:
        stance = "You have a strong military advantage. Consider aggressive expansion."
    elif my_strength > enemy_strength:
        stance = "You have a slight military edge. Maintain readiness while expanding."
    elif my_strength == enemy_strength:
        stance = "Military forces are balanced. Focus on positioning and economy."
    else:
        stance = "You are at a military disadvantage. Prioritize defense and unit production."

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


def _calculate_resource_priority(resource_type: str, distance: float) -> float:
    """Calculate priority score for a resource opportunity."""
    # Base priority by resource type
    base_priority = {
        "food": 3.0,  # Essential for growth
        "wood": 2.0,  # Important for early game
        "ore": 2.5,  # Important for military
        "crystal": 4.0,  # Rare and valuable
    }.get(resource_type, 1.0)

    # Distance penalty (closer is better)
    if distance is None or distance == float("inf"):
        distance_modifier = 0.1
    else:
        distance_modifier = max(0.1, 1.0 / (1.0 + distance * 0.2))

    return base_priority * distance_modifier


def _generate_resource_advice(opportunities: list, game_state, player_id: str) -> str:
    """Generate strategic advice about resource development."""
    if not opportunities:
        return "No visible resource opportunities. Explore more areas."

    my_resources = game_state.stockpiles.get(player_id, {})
    food = my_resources.get("food", 0)
    wood = my_resources.get("wood", 0)

    advice = []

    if food < 20:
        food_ops = [o for o in opportunities if o["resource"] == "food"]
        if food_ops:
            advice.append(
                f"Low food ({food}). Priority: develop food site at ({food_ops[0]['location']['x']},{food_ops[0]['location']['y']})."
            )

    if wood < 10:
        wood_ops = [o for o in opportunities if o["resource"] == "wood"]
        if wood_ops:
            advice.append(
                f"Low wood ({wood}). Consider wood site at ({wood_ops[0]['location']['x']},{wood_ops[0]['location']['y']})."
            )

    crystal_ops = [o for o in opportunities if o["resource"] == "crystal"]
    if crystal_ops:
        advice.append(
            f"Crystal available at ({crystal_ops[0]['location']['x']},{crystal_ops[0]['location']['y']}) - high priority."
        )

    return (
        " ".join(advice) if advice else "Resource levels adequate. Focus on expansion."
    )


def _validate_single_action(
    game_state, action: dict[str, Any], player_id: str
) -> dict[str, Any]:
    """Validate a single action."""
    try:
        action_type = action.get("type")

        if action_type == "MOVE":
            unit_id = action.get("unit_id")
            target = action.get("target_location", {})

            if not unit_id or not target:
                return {"valid": False, "reason": "Missing unit_id or target_location"}

            unit = game_state.units.get(unit_id)
            if not unit:
                return {"valid": False, "reason": f"Unit {unit_id} not found"}

            if unit.owner != player_id:
                return {
                    "valid": False,
                    "reason": "Cannot move unit not owned by player",
                }

            # Check if target is valid (basic validation)
            target_x, target_y = target.get("x"), target.get("y")
            if target_x is None or target_y is None:
                return {"valid": False, "reason": "Invalid target coordinates"}

            if not (
                0 <= target_x < game_state.map_width
                and 0 <= target_y < game_state.map_height
            ):
                return {"valid": False, "reason": "Target coordinates out of bounds"}

            return {"valid": True, "reason": "Valid move action"}

        elif action_type == "FOUND_CITY":
            worker_id = action.get("unit_id")

            if not worker_id:
                return {"valid": False, "reason": "Missing worker unit_id"}

            unit = game_state.units.get(worker_id)
            if not unit:
                return {"valid": False, "reason": f"Worker {worker_id} not found"}

            if unit.owner != player_id:
                return {"valid": False, "reason": "Cannot use unit not owned by player"}

            if unit.type != "worker":
                return {"valid": False, "reason": "Only workers can found cities"}

            return {"valid": True, "reason": "Valid city founding action"}

        elif action_type == "TRAIN_UNIT":
            city_id = action.get("city_id")
            unit_type = action.get("unit_type")

            if not city_id or not unit_type:
                return {"valid": False, "reason": "Missing city_id or unit_type"}

            city = game_state.cities.get(city_id)
            if not city:
                return {"valid": False, "reason": f"City {city_id} not found"}

            if city.owner != player_id:
                return {
                    "valid": False,
                    "reason": "Cannot train units in city not owned by player",
                }

            return {"valid": True, "reason": "Valid unit training action"}

        else:
            return {"valid": False, "reason": f"Unknown action type: {action_type}"}

    except Exception as e:
        return {"valid": False, "reason": f"Validation error: {str(e)}"}


async def main():
    """Main function to run the FastMCP server."""
    global game_client

    # Initialize game client
    game_backend_url = "http://localhost:8000/api/v1"
    game_client = GameClient(base_url=game_backend_url)

    logger.info("Starting FastMCP server for 4X game tools")

    # Run the MCP server
    await mcp.run()


if __name__ == "__main__":
    asyncio.run(main())
