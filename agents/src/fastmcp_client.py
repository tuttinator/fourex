"""
FastMCP client for agents to connect to FastMCP server and use game analysis tools.
"""

import json
from typing import Any

import structlog
from rich.console import Console

console = Console()
logger = structlog.get_logger()


class FastMCPGameClient:
    """Client for connecting to the FastMCP server and using game analysis tools."""

    def __init__(
        self, 
        player_id: str, 
        game_backend_url: str = "http://localhost:8000/api/v1"
    ):
        self.player_id = player_id
        self.game_backend_url = game_backend_url
        self.logger = logger.bind(component="fastmcp_client", player_id=player_id)

        # For now, we'll import the FastMCP server directly
        # In production, this would connect via actual MCP protocol
        try:
            from .fastmcp_server import (
                get_game_state,
                analyze_territory,
                evaluate_military_position,
                find_resource_opportunities,
                validate_actions,
                calculate_distances,
                GameStateRequest,
                TerritoryAnalysisRequest,
                MilitaryAnalysisRequest,
                ResourceOpportunitiesRequest,
                ActionValidationRequest,
                DistanceCalculationRequest
            )
            
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
            
            self.logger.info("FastMCP client initialized with direct server connection")
            self._available = True
        except Exception as e:
            self.logger.error("Failed to initialize FastMCP client", error=str(e))
            self._available = False

    def is_available(self) -> bool:
        """Check if MCP client is available."""
        return self._available

    async def get_game_state(self, game_id: str) -> dict[str, Any] | None:
        """Get current game state using MCP tool."""
        if not self._available:
            return None

        try:
            request = self.request_models["get_game_state"](
                game_id=game_id,
                player_id=self.player_id
            )
            result = await self.tools["get_game_state"](request)
            return json.loads(result) if result else None
        except Exception as e:
            self.logger.error("Error getting game state via FastMCP", error=str(e))
            return None

    async def analyze_territory(
        self, 
        game_id: str, 
        focus_area: dict[str, int] | None = None
    ) -> dict[str, Any] | None:
        """Analyze territory around a specific location."""
        if not self._available:
            return None

        try:
            request = self.request_models["analyze_territory"](
                game_id=game_id,
                player_id=self.player_id,
                focus_area=focus_area
            )
            result = await self.tools["analyze_territory"](request)
            return json.loads(result) if result else None
        except Exception as e:
            self.logger.error("Error analyzing territory via FastMCP", error=str(e))
            return None

    async def evaluate_military_position(
        self, game_id: str, include_predictions: bool = True
    ) -> dict[str, Any] | None:
        """Evaluate military position and threats."""
        if not self._available:
            return None

        try:
            request = self.request_models["evaluate_military_position"](
                game_id=game_id,
                player_id=self.player_id,
                include_predictions=include_predictions
            )
            result = await self.tools["evaluate_military_position"](request)
            return json.loads(result) if result else None
        except Exception as e:
            self.logger.error(
                "Error evaluating military position via FastMCP", error=str(e)
            )
            return None

    async def find_resource_opportunities(
        self, 
        game_id: str,
        resource_types: list[str] | None = None
    ) -> dict[str, Any] | None:
        """Find nearby resource opportunities."""
        if not self._available:
            return None

        try:
            request = self.request_models["find_resource_opportunities"](
                game_id=game_id,
                player_id=self.player_id,
                resource_types=resource_types
            )
            result = await self.tools["find_resource_opportunities"](request)
            return json.loads(result) if result else None
        except Exception as e:
            self.logger.error(
                "Error finding resource opportunities via FastMCP", error=str(e)
            )
            return None

    async def validate_actions(
        self, game_id: str, actions: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        """Validate a list of potential actions."""
        if not self._available:
            return None

        try:
            request = self.request_models["validate_actions"](
                game_id=game_id,
                player_id=self.player_id,
                actions=actions
            )
            result = await self.tools["validate_actions"](request)
            return json.loads(result) if result else None
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
            request = self.request_models["calculate_distances"](
                from_locations=from_coords,
                to_locations=to_coords
            )
            result = await self.tools["calculate_distances"](request)
            return json.loads(result) if result else None
        except Exception as e:
            self.logger.error("Error calculating distances via FastMCP", error=str(e))
            return None

    async def comprehensive_analysis(
        self, game_id: str, game_state=None
    ) -> dict[str, Any]:
        """Run comprehensive analysis using multiple MCP tools."""
        analysis = {
            "mcp_available": True,
            "turn": game_state.turn if game_state else "unknown"
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
            if game_state and hasattr(game_state, 'units') and hasattr(game_state, 'cities'):
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
