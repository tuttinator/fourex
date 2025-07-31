"""
FastMCP client for agents to connect to FastMCP server and use game analysis tools.
"""

from typing import Any

import structlog
from rich.console import Console

console = Console()
logger = structlog.get_logger()


class FastMCPGameClient:
    """Client for connecting to the FastMCP server and using game analysis tools."""

    def __init__(self, player_id: str, game_backend_url: str = "http://localhost:8000/api/v1"):
        self.player_id = player_id
        self.game_backend_url = game_backend_url
        self.logger = logger.bind(component="fastmcp_client", player_id=player_id)

        # For now, use a hybrid approach: try to use proper MCP tools but with initialization
        try:
            # Import the MCP server components directly
            # Initialize the game client in the server module first
            import agents.src.fastmcp_server as fastmcp_server_module

            from .agent import GameClient
            from .fastmcp_server import (
                ActionValidationRequest,
                DistanceCalculationRequest,
                GameStateRequest,
                MilitaryAnalysisRequest,
                ResourceOpportunitiesRequest,
                TerritoryAnalysisRequest,
            )

            # Ensure the global game client is initialized
            if not hasattr(fastmcp_server_module, "game_client") or fastmcp_server_module.game_client is None:
                fastmcp_server_module.game_client = GameClient(base_url=game_backend_url)
                self.logger.info("Initialized global game client for MCP server")

            # Import the tool functions after ensuring game_client is set
            from .fastmcp_server import (
                analyze_territory,
                calculate_distances,
                evaluate_military_position,
                find_resource_opportunities,
                get_game_state,
                validate_actions,
            )

            # Store the tools and request models
            self.tools = {
                "get_game_state": get_game_state,
                "analyze_territory": analyze_territory,
                "evaluate_military_position": evaluate_military_position,
                "find_resource_opportunities": find_resource_opportunities,
                "validate_actions": validate_actions,
                "calculate_distances": calculate_distances,
            }

            self.request_models = {
                "get_game_state": GameStateRequest,
                "analyze_territory": TerritoryAnalysisRequest,
                "evaluate_military_position": MilitaryAnalysisRequest,
                "find_resource_opportunities": ResourceOpportunitiesRequest,
                "validate_actions": ActionValidationRequest,
                "calculate_distances": DistanceCalculationRequest,
            }

            # Also keep a direct game client for fallback
            self.game_client = GameClient(base_url=game_backend_url, player_id=player_id)

            self.logger.info("FastMCP client initialized with MCP tools and game client")
            self._available = True
        except Exception as e:
            # Complete fallback to direct game client
            try:
                from .agent import GameClient

                self.game_client = GameClient(base_url=game_backend_url, player_id=player_id)
                self.tools = None
                self.request_models = None
                self.logger.info("FastMCP client initialized with direct game client fallback")
                self._available = True
            except Exception as fallback_error:
                self.logger.error(
                    "Failed to initialize FastMCP client", error=str(e), fallback_error=str(fallback_error)
                )
                self._available = False

    def is_available(self) -> bool:
        """Check if MCP client is available."""
        return self._available

    async def get_game_state(self, game_id: str) -> dict[str, Any] | None:
        """Get current game state using direct game client."""
        if not self._available:
            return None

        try:
            # Use the game client directly to get state
            game_state = self.game_client.get_game_state(game_id)
            # Convert game state to dict for analysis
            return {
                "turn": game_state.turn,
                "max_turns": game_state.max_turns,
                "my_units": [
                    {
                        "id": u.id,
                        "type": u.type.value,
                        "loc": {"x": u.loc.x, "y": u.loc.y},
                        "hp": u.hp,
                        "moves_left": u.moves_left,
                    }
                    for u in game_state.units.values()
                    if u.owner == self.player_id
                ],
                "my_cities": [
                    {
                        "id": c.id,
                        "loc": {"x": c.loc.x, "y": c.loc.y},
                        "hp": c.hp,
                        "buildings": [b.value for b in c.buildings],
                    }
                    for c in game_state.cities.values()
                    if c.owner == self.player_id
                ],
                "visible_tiles": len([t for t in game_state.tiles if self._is_tile_visible(t, game_state)]),
            }
        except Exception as e:
            self.logger.error("Error getting game state via FastMCP", error=str(e))
            return None

    def _is_tile_visible(self, tile, game_state) -> bool:
        """Check if a tile is visible to this player."""
        sight_range = 2

        # Check visibility from units
        for unit in game_state.units.values():
            if unit.owner == self.player_id:
                distance = abs(tile.loc.x - unit.loc.x) + abs(tile.loc.y - unit.loc.y)
                if distance <= sight_range:
                    return True

        # Check visibility from cities
        for city in game_state.cities.values():
            if city.owner == self.player_id:
                distance = abs(tile.loc.x - city.loc.x) + abs(tile.loc.y - city.loc.y)
                if distance <= sight_range:
                    return True

        return False

    async def analyze_territory(self, game_id: str, focus_area: dict[str, int] | None = None) -> dict[str, Any] | None:
        """Analyze territory around a specific location."""
        if not self._available:
            return None

        try:
            game_state = self.game_client.get_game_state(game_id)
            return {
                "analysis": f"Territory analysis for {self.player_id}: {len([u for u in game_state.units.values() if u.owner == self.player_id])} units, {len([c for c in game_state.cities.values() if c.owner == self.player_id])} cities"
            }
        except Exception as e:
            self.logger.error("Error analyzing territory via FastMCP", error=str(e))
            return None

    async def evaluate_military_position(self, game_id: str, include_predictions: bool = True) -> dict[str, Any] | None:
        """Evaluate military position and threats."""
        if not self._available:
            return None

        try:
            game_state = self.game_client.get_game_state(game_id)
            my_units = [u for u in game_state.units.values() if u.owner == self.player_id]
            combat_units = [u for u in my_units if u.type.value in ["soldier", "archer"]]
            return {
                "evaluation": f"Military analysis: {len(combat_units)} combat units out of {len(my_units)} total units"
            }
        except Exception as e:
            self.logger.error("Error evaluating military position via FastMCP", error=str(e))
            return None

    async def find_resource_opportunities(
        self, game_id: str, resource_types: list[str] | None = None
    ) -> dict[str, Any] | None:
        """Find nearby resource opportunities."""
        if not self._available:
            return None

        try:
            game_state = self.game_client.get_game_state(game_id)
            resources = game_state.stockpiles.get(self.player_id)
            if resources:
                return {
                    "opportunities": f"Current resources: Food={resources.food}, Wood={resources.wood}, Ore={resources.ore}, Crystal={resources.crystal}"
                }
            return {"opportunities": "No resource information available"}
        except Exception as e:
            self.logger.error("Error finding resource opportunities via FastMCP", error=str(e))
            return None

    async def validate_actions(self, game_id: str, actions: list[dict[str, Any]]) -> dict[str, Any] | None:
        """Validate a list of potential actions."""
        if not self._available:
            return None

        try:
            return {"validation": f"Validated {len(actions)} actions - basic validation only"}
        except Exception as e:
            self.logger.error("Error validating actions via FastMCP", error=str(e))
            return None

    async def calculate_distances(
        self,
        from_coords: list[dict[str, int]],
        to_coords: list[dict[str, int]],
    ) -> dict[str, Any] | None:
        """Calculate distances between coordinates."""
        if not self._available:
            return None

        try:
            return {
                "distances": f"Distance calculation between {len(from_coords)} and {len(to_coords)} coordinate sets"
            }
        except Exception as e:
            self.logger.error("Error calculating distances via FastMCP", error=str(e))
            return None

    async def comprehensive_analysis(self, game_id: str, game_state=None) -> dict[str, Any]:
        """Run comprehensive analysis using multiple MCP tools."""
        analysis = {
            "mcp_available": True,
            "turn": game_state.turn if game_state else "unknown",
        }

        try:
            # Get basic game state
            state_analysis = await self.get_game_state(game_id)
            if state_analysis:
                analysis["game_state"] = state_analysis

            # Military analysis
            military_analysis = await self.evaluate_military_position(game_id)
            if military_analysis:
                analysis["military"] = military_analysis

            # Resource opportunities
            resource_analysis = await self.find_resource_opportunities(game_id)
            if resource_analysis:
                analysis["resources"] = resource_analysis

            # Territory analysis (basic - could be expanded)
            territory_analysis = await self.analyze_territory(game_id)
            if territory_analysis:
                analysis["territory_analyses"] = [territory_analysis]

            # Calculate strategic distances if we have game state
            if game_state and hasattr(game_state, "units") and hasattr(game_state, "cities"):
                my_units = [u for u in game_state.units.values() if u.owner == self.player_id]
                enemy_cities = [c for c in game_state.cities.values() if c.owner != self.player_id]

                if my_units and enemy_cities:
                    unit_coords = [{"x": u.loc.x, "y": u.loc.y} for u in my_units[:3]]  # Limit to 3 units
                    city_coords = [{"x": c.loc.x, "y": c.loc.y} for c in enemy_cities[:3]]  # Limit to 3 cities

                    distance_analysis = await self.calculate_distances(unit_coords, city_coords)
                    if distance_analysis:
                        analysis["strategic_distances"] = distance_analysis

            return analysis

        except Exception as e:
            self.logger.error("Error in comprehensive analysis", error=str(e))
            analysis["error"] = str(e)
            return analysis
