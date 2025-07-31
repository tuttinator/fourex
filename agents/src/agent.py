import os
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any

import logfire
import requests
import structlog
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from rich.console import Console
from rich.panel import Panel

# Load environment variables
load_dotenv()

console = Console()

# Configure Logfire based on environment variables
logfire_enabled = os.getenv("LOGFIRE_ENABLED", "false").lower() == "true"
# default to None, which will log to console if the env var is set to true
logfire_console_setting = None if os.getenv("LOGFIRE_CONSOLE_OUTPUT", "false").lower() == "true" else False

logfire.configure(
    send_to_logfire=logfire_enabled,
    console=logfire_console_setting,
    token=os.getenv("LOGFIRE_TOKEN") if logfire_enabled else None,
)

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


# Game types (matching the backend)
class Terrain(str, Enum):
    PLAINS = "plains"
    FOREST = "forest"
    MOUNTAIN = "mountain"
    WATER = "water"


class Resource(str, Enum):
    FOOD = "food"
    WOOD = "wood"
    ORE = "ore"
    CRYSTAL = "crystal"


class UnitType(str, Enum):
    SCOUT = "scout"
    WORKER = "worker"
    SOLDIER = "soldier"
    ARCHER = "archer"


class BuildingType(str, Enum):
    GRANARY = "granary"
    BARRACKS = "barracks"
    WALLS = "walls"


class ImprovementType(str, Enum):
    FARM = "farm"
    MINE = "mine"
    CRYSTAL_EXTRACTOR = "crystal_extractor"


class ActionType(str, Enum):
    MOVE = "move"
    FOUND_CITY = "found_city"
    BUILD_UNIT = "build_unit"
    BUILD_BUILDING = "build_building"
    BUILD_IMPROVEMENT = "build_improvement"
    ATTACK = "attack"
    DIPLOMACY = "diplomacy"
    RESEARCH = "research"
    PASS = "pass"


@dataclass
class Coord:
    x: int
    y: int

    def __hash__(self):
        return hash((self.x, self.y))

    def __eq__(self, other):
        if not isinstance(other, Coord):
            return False
        return self.x == other.x and self.y == other.y


@dataclass
class ResourceBag:
    food: int
    wood: int
    ore: int
    crystal: int


@dataclass
class Tile:
    id: int
    loc: Coord
    terrain: Terrain
    resource: Resource | None = None
    owner: str | None = None
    city_id: int | None = None
    unit_id: int | None = None
    improvement: ImprovementType | None = None


@dataclass
class Unit:
    id: int
    owner: str
    type: UnitType
    hp: int
    moves_left: int
    loc: Coord


@dataclass
class City:
    id: int
    owner: str
    loc: Coord
    hp: int
    buildings: list[BuildingType]


@dataclass
class GameState:
    turn: int
    rng_state: int
    map_width: int
    map_height: int
    tiles: list[Tile]
    units: dict[int, Unit]
    cities: dict[int, City]
    players: list[str]
    diplomacy: dict[str, str]
    stockpiles: dict[str, ResourceBag]
    next_unit_id: int
    next_city_id: int
    max_turns: int


# Structured output models for LLM responses
class GameAction(BaseModel):
    type: ActionType
    unit_id: int | None = None
    target_location: Coord | None = None
    unit_type: UnitType | None = None
    building_type: BuildingType | None = None
    improvement_type: ImprovementType | None = None
    target_unit_id: int | None = None
    target_player: str | None = None
    diplomacy_action: str | None = None
    reasoning: str = Field(description="Brief explanation of why this action was chosen")


class TurnPlan(BaseModel):
    actions: list[GameAction] = Field(description="List of actions to take this turn")
    strategic_analysis: str = Field(description="Analysis of current game state and strategy")
    priorities: list[str] = Field(description="Current priorities for this turn")


class GameClient:
    """Client for interacting with the game backend"""

    def __init__(
        self,
        base_url: str = "http://localhost:8000/api/v1",
        player_id: str | None = None,
    ):
        self.base_url = base_url
        self.session = requests.Session()
        if player_id:
            self.session.headers.update({"Authorization": f"Bearer player_{player_id}"})

    def get_game_state(self, game_id: str) -> GameState:
        """Get current game state"""
        response = self.session.get(f"{self.base_url}/state?game_id={game_id}")
        response.raise_for_status()
        data = response.json()

        # Convert to our dataclasses
        return self._parse_game_state(data)

    def submit_actions(self, game_id: str, player_id: str, actions: list[dict[str, Any]]) -> bool:
        """Submit actions for a player"""
        response = self.session.post(f"{self.base_url}/actions?game_id={game_id}", json=actions)
        response.raise_for_status()
        return response.json().get("status") == "actions_submitted"

    def get_prompts(self, game_id: str, turn: int) -> list[dict[str, Any]]:
        """Get prompt logs for a turn"""
        response = self.session.get(f"{self.base_url}/logs/{game_id}/turn-{turn}/prompts")
        response.raise_for_status()
        return response.json()

    def _parse_game_state(self, data: dict[str, Any]) -> GameState:
        """Convert raw game state data to our dataclasses"""
        tiles = []
        for tile_data in data["tiles"]:
            tile = Tile(
                id=tile_data["id"],
                loc=Coord(tile_data["loc"]["x"], tile_data["loc"]["y"]),
                terrain=Terrain(tile_data["terrain"]),
                resource=(Resource(tile_data["resource"]) if tile_data.get("resource") else None),
                owner=tile_data.get("owner"),
                city_id=tile_data.get("city_id"),
                unit_id=tile_data.get("unit_id"),
                improvement=(ImprovementType(tile_data["improvement"]) if tile_data.get("improvement") else None),
            )
            tiles.append(tile)

        units = {}
        for unit_id, unit_data in data["units"].items():
            unit = Unit(
                id=unit_data["id"],
                owner=unit_data["owner"],
                type=UnitType(unit_data["type"]),
                hp=unit_data["hp"],
                moves_left=unit_data["moves_left"],
                loc=Coord(unit_data["loc"]["x"], unit_data["loc"]["y"]),
            )
            units[int(unit_id)] = unit

        cities = {}
        for city_id, city_data in data["cities"].items():
            city = City(
                id=city_data["id"],
                owner=city_data["owner"],
                loc=Coord(city_data["loc"]["x"], city_data["loc"]["y"]),
                hp=city_data["hp"],
                buildings=[BuildingType(b) for b in city_data["buildings"]],
            )
            cities[int(city_id)] = city

        stockpiles = {}
        for player, resources in data["stockpiles"].items():
            stockpiles[player] = ResourceBag(
                food=resources["food"],
                wood=resources["wood"],
                ore=resources["ore"],
                crystal=resources["crystal"],
            )

        return GameState(
            turn=data["turn"],
            rng_state=data["rng_state"],
            map_width=data["map_width"],
            map_height=data["map_height"],
            tiles=tiles,
            units=units,
            cities=cities,
            players=data["players"],
            diplomacy=data["diplomacy"],
            stockpiles=stockpiles,
            next_unit_id=data["next_unit_id"],
            next_city_id=data["next_city_id"],
            max_turns=data["max_turns"],
        )


class EnhancedLLMClient:
    """Enhanced LLM client with multi-provider support, retry logic, and detailed logging"""

    def __init__(
        self,
        primary_provider: str = "llm_studio",
        fallback_providers: list[str] | None = None,
        base_url: str = "http://localhost:1234/v1",
        model: str = "qwen/qwen3-32b",
    ):
        # Import here to avoid circular imports
        from .llm_providers import MultiLLMClient

        self.multi_client = MultiLLMClient(primary_provider, fallback_providers)
        self.model = model
        self.logger = logger.bind(component="enhanced_llm_client")

    @logfire.instrument("generate_plan", extract_args=True)
    async def generate_plan(
        self,
        game_state: GameState,
        player_id: str,
        personality: str = "balanced",
        provider_override: str | None = None,
        mcp_analysis: dict | None = None,
        turn_history: list["TurnPlan"] | None = None,  # NEW: pass turn history
    ) -> tuple[TurnPlan, str, str, Any]:
        """Generate a turn plan using the LLM with enhanced logging, MCP analysis, and memory of previous turns"""

        # Create game state summary
        state_summary = self._create_state_summary(game_state, player_id)

        # Create system prompt based on personality
        system_prompt = self._create_system_prompt(personality)

        # Add turn history summary for memory
        history_section = ""
        if turn_history and len(turn_history) > 0:
            history_section = self._summarize_turn_history(turn_history)

        # Create user prompt with MCP analysis if available
        mcp_section = ""
        if mcp_analysis and mcp_analysis.get("mcp_available"):
            mcp_section = f"""

ADVANCED STRATEGIC ANALYSIS (via MCP tools):
Turn: {mcp_analysis.get("turn", "unknown")}

Military Assessment:
{self._format_mcp_military_analysis(mcp_analysis.get("military", {}))}

Resource Opportunities:
{self._format_mcp_resource_analysis(mcp_analysis.get("resources", {}))}

Territory Analysis:
{self._format_mcp_territory_analysis(mcp_analysis.get("territory_analyses", []))}

Strategic Distances:
{self._format_mcp_distance_analysis(mcp_analysis.get("strategic_distances", {}))}

IMPORTANT: Use this MCP analysis to make informed decisions within your fog of war.
Pay special attention to identified threats, opportunities, and strategic positioning.
"""

        user_prompt = f"""
Game State Analysis:
{state_summary}

Current Turn: {game_state.turn}/{game_state.max_turns}
{history_section}
{mcp_section}

Please analyze the current game state and provide a strategic plan for this turn.
Consider your current position, available resources, threats, and opportunities.
{"Use the MCP analysis above to guide your strategic decisions." if mcp_analysis else ""}
"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        try:
            self.logger.info(
                "Generating plan",
                player=player_id,
                turn=game_state.turn,
                personality=personality,
                provider_override=provider_override,
            )

            try:
                llm_response = await self.multi_client.generate(
                    messages=messages,
                    response_model=None,  # Fix type issue: should be None or a BaseModel instance, not a type
                    provider_override=provider_override,
                    temperature=0.7,
                    max_tokens=8000,
                )
            except Exception as e:
                self.logger.error(
                    "LLM generation failed",
                    player=player_id,
                    error=str(e),
                    error_type=type(e).__name__,
                )
                raise

            # Parse the structured response
            if llm_response.content:
                try:
                    import json

                    plan_data = json.loads(llm_response.content)
                    plan = TurnPlan(**plan_data)
                except Exception as e:
                    self.logger.warning("Failed to parse structured plan", error=str(e))
                    # Try to extract from raw content
                    plan = self._fallback_parse_plan(llm_response.content, game_state, player_id)
            else:
                raise ValueError("Empty response from LLM")

            self.logger.info(
                "Plan generated successfully",
                player=player_id,
                actions_count=len(plan.actions),
                provider=llm_response.provider,
                latency_ms=llm_response.latency_ms,
                has_thinking=getattr(llm_response, "thinking", None) is not None,
            )

            return plan, system_prompt, user_prompt, llm_response

        except Exception as e:
            self.logger.error("Failed to generate plan", player=player_id, error=str(e))
            # Remove logfire.log_exception (not a known attribute)
            # Return a default plan with empty actions (equivalent to pass)
            default_plan = TurnPlan(
                actions=[],  # Empty actions list instead of PASS action
                strategic_analysis=f"Unable to analyze game state due to LLM error: {str(e)}",
                priorities=["Survive"],
            )
            from .llm_providers import LLMResponse

            mock_response = LLMResponse(
                content=default_plan.model_dump_json(),
                latency_ms=0,
                provider="fallback",
                model="default",
            )
            return default_plan, system_prompt, user_prompt, mock_response

    def _fallback_parse_plan(self, content: str, game_state: GameState = None, player_id: str = "") -> TurnPlan:
        """Fallback parsing when structured output fails"""
        import json
        import re

        # Try to extract actions from the content
        try:
            # Look for JSON-like structure in the content
            json_match = re.search(r"\{.*\}", content, re.DOTALL)
            if json_match:
                potential_json = json_match.group()
                parsed = json.loads(potential_json)

                # Check if it has the right structure
                if isinstance(parsed, dict):
                    # Try to extract fields and fix them
                    actions = parsed.get("actions", [])
                    strategic_analysis = parsed.get("strategic_analysis", "Extracted from LLM response")
                    priorities = parsed.get("priorities", ["Survive"])

                    # Ensure actions is a list and convert any malformed actions
                    if not isinstance(actions, list):
                        actions = []

                    # Fix action types and ensure they have required fields
                    fixed_actions = []
                    for action in actions:
                        if isinstance(action, dict):
                            action_type = action.get("type", "").upper()

                            # Map common action type variations
                            if action_type in ["FOUND_CITY", "FOUNDCITY"]:
                                # If we have units, create a proper found city action
                                if game_state and player_id:
                                    my_units = [u for u in game_state.units.values() if u.owner == player_id]
                                    workers = [u for u in my_units if u.type == UnitType.WORKER]
                                    if workers:
                                        fixed_actions.append(
                                            GameAction(
                                                type=ActionType.FOUND_CITY,
                                                unit_id=workers[0].id,
                                                reasoning=action.get("reasoning", "Found city with worker"),
                                            )
                                        )
                                        continue

                            # Add other action type mappings if needed
                            # For now, skip invalid actions

                    return TurnPlan(
                        actions=fixed_actions,
                        strategic_analysis=strategic_analysis,
                        priorities=priorities if isinstance(priorities, list) else ["Survive"],
                    )
        except Exception as e:
            self.logger.warning(f"Failed to extract from content: {e}")

        # Ultimate fallback - empty actions (equivalent to pass)
        return TurnPlan(
            actions=[],
            strategic_analysis="Unable to parse LLM response properly",
            priorities=["Survive"],
        )

    def _create_state_summary(self, game_state: GameState, player_id: str) -> str:
        """Create a concise summary of the game state"""
        my_units = [u for u in game_state.units.values() if u.owner == player_id]
        my_cities = [c for c in game_state.cities.values() if c.owner == player_id]
        my_resources = game_state.stockpiles.get(player_id, ResourceBag(0, 0, 0, 0))

        # Get visible tiles based on fog of war (units and cities provide vision)
        # For now, implement a simple visibility calculation
        visible_coords = set()
        sight_range = 2

        # Add visibility around each unit
        for unit in my_units:
            for dx in range(-sight_range, sight_range + 1):
                for dy in range(-sight_range, sight_range + 1):
                    x, y = unit.loc.x + dx, unit.loc.y + dy
                    if 0 <= x < game_state.map_width and 0 <= y < game_state.map_height:
                        visible_coords.add((x, y))

        # Add visibility around each city
        for city in my_cities:
            for dx in range(-sight_range, sight_range + 1):
                for dy in range(-sight_range, sight_range + 1):
                    x, y = city.loc.x + dx, city.loc.y + dy
                    if 0 <= x < game_state.map_width and 0 <= y < game_state.map_height:
                        visible_coords.add((x, y))

        visible_tiles = [t for t in game_state.tiles if (t.loc.x, t.loc.y) in visible_coords]

        # Get visible enemy units and cities
        visible_enemy_units = [
            u for u in game_state.units.values() if u.owner != player_id and (u.loc.x, u.loc.y) in visible_coords
        ]
        visible_enemy_cities = [
            c for c in game_state.cities.values() if c.owner != player_id and (c.loc.x, c.loc.y) in visible_coords
        ]

        summary = f"""
Player: {player_id}
Resources: Food={my_resources.food}, Wood={my_resources.wood}, Ore={my_resources.ore}, Crystal={my_resources.crystal}
Units: {len(my_units)} ({", ".join([f"{u.type.value}@({u.loc.x},{u.loc.y})" for u in my_units])})
Cities: {len(my_cities)} ({", ".join([f"City@({c.loc.x},{c.loc.y})" for c in my_cities])})

Map Size: {game_state.map_width}x{game_state.map_height}
Visible Area: {len(visible_tiles)} tiles (sight range: {sight_range})
Other Players: {[p for p in game_state.players if p != player_id]}

Visible Enemy Units: {len(visible_enemy_units)} ({", ".join([
    f"{u.type.value}@({u.loc.x},{u.loc.y})" for u in visible_enemy_units
])})
Visible Enemy Cities: {len(visible_enemy_cities)} ({", ".join([
    f"City@({c.loc.x},{c.loc.y})" for c in visible_enemy_cities
])})

Key Terrain Features (visible):
- Plains: {len([t for t in visible_tiles if t.terrain == Terrain.PLAINS])}
- Forest: {len([t for t in visible_tiles if t.terrain == Terrain.FOREST])}
- Mountains: {len([t for t in visible_tiles if t.terrain == Terrain.MOUNTAIN])}
- Water: {len([t for t in visible_tiles if t.terrain == Terrain.WATER])}

Resources on Map (visible):
- Food: {len([t for t in visible_tiles if t.resource == Resource.FOOD])}
- Wood: {len([t for t in visible_tiles if t.resource == Resource.WOOD])}
- Ore: {len([t for t in visible_tiles if t.resource == Resource.ORE])}
- Crystal: {len([t for t in visible_tiles if t.resource == Resource.CRYSTAL])}
"""
        return summary

    def _create_system_prompt(self, personality: str) -> str:
        """Create system prompt based on agent personality"""
        from .personalities import get_personality_prompt

        base_prompt = """You are an AI agent playing a 4X strategy game (Explore, Expand, Exploit, Exterminate).
You need to make strategic decisions each turn to build your civilization and compete with other players.

Game Rules:
- Units can move, attack, found cities, build improvements
- Cities can build units and buildings
- Resources are needed for construction and unit maintenance
- Combat is deterministic based on unit types and terrain
- Diplomacy affects relationships with other players

Available Actions:
- MOVE: Move a unit to adjacent tile
- FOUND_CITY: Worker founds a city
- BUILD_UNIT: City builds a unit
- BUILD_BUILDING: City builds a building
- BUILD_IMPROVEMENT: Worker builds improvement on tile
- ATTACK: Unit attacks another unit
- DIPLOMACY: Change diplomatic stance
- PASS: Do nothing

Your responses must be in JSON format with structured actions and reasoning.

"""

        personality_prompt = get_personality_prompt(personality)
        return base_prompt + "\n" + personality_prompt

    def _format_mcp_military_analysis(self, military_data: dict) -> str:
        """Format MCP military analysis for prompt."""
        if not military_data:
            return "No military analysis available"

        if isinstance(military_data, dict) and "evaluation" in military_data:
            return military_data["evaluation"]
        elif isinstance(military_data, str):
            return military_data
        else:
            return f"Military data: {military_data}"

    def _format_mcp_resource_analysis(self, resource_data: dict) -> str:
        """Format MCP resource analysis for prompt."""
        if not resource_data:
            return "No resource opportunities identified"

        if isinstance(resource_data, dict) and "opportunities" in resource_data:
            return resource_data["opportunities"]
        elif isinstance(resource_data, str):
            return resource_data
        else:
            return f"Resource data: {resource_data}"

    def _format_mcp_territory_analysis(self, territory_analyses: list) -> str:
        """Format MCP territory analyses for prompt."""
        if not territory_analyses:
            return "No territory analysis available"

        formatted = []
        for i, analysis in enumerate(territory_analyses):
            location = analysis.get("location", {})
            unit_id = analysis.get("unit_id")
            city_id = analysis.get("city_id")

            header = f"Area {i + 1}"
            if unit_id:
                header += f" (Unit {unit_id})"
            elif city_id:
                header += f" (City {city_id})"

            if location:
                header += f" at ({location.get('x', '?')},{location.get('y', '?')})"

            if isinstance(analysis.get("analysis"), str):
                content = analysis["analysis"]
            else:
                content = str(analysis)

            formatted.append(f"{header}: {content}")

        return "\n".join(formatted)

    def _format_mcp_distance_analysis(self, distance_data: dict) -> str:
        """Format MCP distance analysis for prompt."""
        if not distance_data:
            return "No distance analysis available"

        if isinstance(distance_data, dict) and "distances" in distance_data:
            return distance_data["distances"]
        elif isinstance(distance_data, str):
            return distance_data
        else:
            return f"Distance data: {distance_data}"

    def _summarize_turn_history(self, turn_history: list["TurnPlan"]) -> str:
        """Summarize previous turn(s) for agent memory in the prompt."""
        # Only include the last 1-2 turns for brevity
        if not turn_history:
            return ""
        lines = ["Previous Turn(s) Summary:"]
        for i, plan in enumerate(turn_history[-2:]):
            lines.append(f"Turn {-2 + i + len(turn_history)}:")
            lines.append(f"  Strategic Analysis: {plan.strategic_analysis}")
            lines.append(f"  Priorities: {', '.join(plan.priorities)}")
            for action in plan.actions:
                lines.append(f"    - {action.type.value}: {action.reasoning}")
        return "\n" + "\n".join(lines) + "\n"


class FourXAgent:
    """Enhanced agent class with retry logic, multi-LLM support, and detailed logging"""

    def __init__(
        self,
        player_id: str,
        personality: str = "balanced",
        game_client: GameClient | None = None,
        llm_client: EnhancedLLMClient | None = None,
        game_backend_url: str = "http://localhost:8000/api/v1",
        primary_provider: str = "llm_studio",
        fallback_providers: list[str] | None = None,
        use_persistent_client: bool = True,
    ):
        from .persistent_game_client import ResilientGameConnection

        self.player_id = player_id
        self.personality = personality

        # Use resilient connection if requested, otherwise fall back to basic client
        if use_persistent_client and game_client is None:
            self.resilient_connection = ResilientGameConnection(base_url=game_backend_url, player_id=player_id)
            self.game_client = self.resilient_connection.client
        else:
            self.game_client = game_client or GameClient(base_url=game_backend_url, player_id=player_id)
            self.resilient_connection = None

        self.llm_client = llm_client or EnhancedLLMClient(
            primary_provider=primary_provider,
            fallback_providers=fallback_providers or ["openai"],
        )

        # Initialize FastMCP client for advanced game analysis
        from .fastmcp_client import FastMCPGameClient

        self.mcp_client = FastMCPGameClient(player_id, game_backend_url)

        self.turn_history: list[TurnPlan] = []
        self.logger = logger.bind(component="agent", player_id=player_id)

        console.print(f"[green]Agent {player_id} initialized with {personality} personality[/green]")

        self.logger.info(
            "Agent initialized",
            personality=personality,
            primary_provider=primary_provider,
            fallback_providers=fallback_providers,
        )

    async def play_turn(self, game_id: str, provider_override: str | None = None) -> bool:
        """Play a single turn with manual retry logic and enhanced error handling."""
        max_attempts = 3

        for attempt in range(max_attempts):
            try:
                result = await self._play_turn_attempt(game_id, provider_override, attempt)
                return result
            except Exception as e:
                self.logger.error(
                    "Turn attempt failed",
                    attempt=attempt + 1,
                    max_attempts=max_attempts,
                    error=str(e),
                )

                if attempt == max_attempts - 1:
                    # Final attempt failed
                    console.print(f"[red]All {max_attempts} turn attempts failed for {self.player_id}[/red]")
                    return False

                # Wait before retry
                time.sleep(2**attempt)  # Exponential backoff

        return False

    @logfire.instrument("play_turn_attempt", extract_args=True)
    async def _play_turn_attempt(
        self, game_id: str, provider_override: str | None = None, retry_count: int = 0
    ) -> bool:
        """Single attempt to play a turn with enhanced error handling and logging"""
        start_time = time.time()
        error_message = None
        game_state = None
        system_prompt = ""
        user_prompt = ""
        llm_response = None
        plan = None
        api_actions = []
        game_state_summary = {}

        try:
            # Get current game state
            game_state = self.game_client.get_game_state(game_id)

            # Check if it's our turn or if game is over
            if game_state.turn >= game_state.max_turns:
                console.print(f"[yellow]Game {game_id} has ended[/yellow]")
                return False

            # Create game state summary for logging
            game_state_summary = {
                "turn": game_state.turn,
                "max_turns": game_state.max_turns,
                "my_units": len([u for u in game_state.units.values() if u.owner == self.player_id]),
                "my_cities": len([c for c in game_state.cities.values() if c.owner == self.player_id]),
                "my_resources": (
                    game_state.stockpiles.get(self.player_id).__dict__
                    if game_state.stockpiles.get(self.player_id)
                    else {}
                ),
            }

            # Generate turn plan with MCP analysis
            console.print(f"[blue]Turn {game_state.turn}: {self.player_id} is planning...[/blue]")

            # Run MCP analysis first if available
            mcp_analysis = None
            if self.mcp_client.is_available():
                console.print(f"[cyan]Running MCP analysis for {self.player_id}...[/cyan]")
                mcp_analysis = await self.mcp_client.comprehensive_analysis(game_id, game_state)
                self.logger.info(
                    "MCP analysis completed",
                    military_available="military" in mcp_analysis,
                    resources_available="resources" in mcp_analysis,
                    territory_count=len(mcp_analysis.get("territory_analyses", [])),
                )

            (
                plan,
                system_prompt,
                user_prompt,
                llm_response,
            ) = await self.llm_client.generate_plan(
                game_state,
                self.player_id,
                self.personality,
                provider_override,
                mcp_analysis,
                turn_history=self.turn_history,  # Pass turn history for memory
            )

            # Display plan
            self._display_plan(plan)

            # Convert actions to API format with game state for ID resolution
            api_actions = self._convert_actions_to_api(plan.actions, game_state)

            # Log the converted actions for debugging
            self.logger.info(
                "Converted actions",
                player=self.player_id,
                turn=game_state.turn,
                original_count=len(plan.actions),
                api_count=len(api_actions),
                api_actions=api_actions,
            )

            # Submit actions with retry logic
            max_retries = 3
            success = False

            for attempt in range(max_retries):
                try:
                    if self.resilient_connection:
                        success = self.resilient_connection.submit_actions(game_id, api_actions)
                    else:
                        success = self.game_client.submit_actions(game_id, self.player_id, api_actions)

                    if success:
                        break
                    else:
                        self.logger.warning(
                            "Action submission failed",
                            attempt=attempt + 1,
                            max_retries=max_retries,
                        )

                except Exception as e:
                    self.logger.error(
                        "Error during action submission",
                        attempt=attempt + 1,
                        error=str(e),
                    )

                # Wait before retry (except on last attempt)
                if attempt < max_retries - 1:
                    time.sleep(1)

            duration_ms = int((time.time() - start_time) * 1000)

            if success:
                console.print("[green]Actions submitted successfully[/green]")
                self.turn_history.append(plan)

                self.logger.info(
                    "Turn completed successfully",
                    turn=game_state.turn,
                    duration_ms=duration_ms,
                    actions_count=len(api_actions),
                    provider=llm_response.provider,
                    tokens_in=llm_response.tokens_in,
                    tokens_out=llm_response.tokens_out,
                )
            else:
                console.print("[red]Failed to submit actions[/red]")
                error_message = "Failed to submit actions to game backend"

                self.logger.error(
                    "Turn failed - action submission failed",
                    turn=game_state.turn,
                    duration_ms=duration_ms,
                )

            # Enhanced logging
            from .enhanced_logging import enhanced_logger

            enhanced_logger.log_turn(
                turn_number=game_state.turn,
                player_id=self.player_id,
                game_id=game_id,
                success=success,
                duration_ms=duration_ms,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                llm_response=llm_response,
                strategic_analysis=plan.strategic_analysis,
                priorities=plan.priorities,
                actions=[action.model_dump() for action in plan.actions],
                submitted_actions=api_actions,
                game_state_summary=game_state_summary,
                error_message=error_message,
                retry_count=retry_count,
            )

            return success

        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            error_message = str(e)

            console.print(f"[red]Error playing turn: {e}[/red]")
            self.logger.error(
                "Turn failed with exception",
                turn=game_state.turn if game_state else "unknown",
                duration_ms=duration_ms,
                error=error_message,
            )

            logfire.exception("Agent turn failed")

            # Log the failed turn
            from .enhanced_logging import enhanced_logger

            enhanced_logger.log_turn(
                turn_number=game_state.turn if game_state else 0,
                player_id=self.player_id,
                game_id=game_id,
                success=False,
                duration_ms=duration_ms,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                llm_response=llm_response,
                strategic_analysis=plan.strategic_analysis if plan else "",
                priorities=plan.priorities if plan else [],
                actions=([action.model_dump() for action in plan.actions] if plan else []),
                submitted_actions=api_actions,
                game_state_summary=game_state_summary,
                error_message=error_message,
                retry_count=retry_count,
            )

            return False

    def _display_plan(self, plan: TurnPlan):
        """Display the turn plan in a nice format"""
        panel = Panel(
            f"[bold]Strategic Analysis:[/bold]\n{plan.strategic_analysis}\n\n"
            + "[bold]Priorities:[/bold]\n"
            + "\n".join([f"• {p}" for p in plan.priorities])
            + "\n\n"
            + f"[bold]Actions ({len(plan.actions)}):[/bold]\n"
            + "\n".join([f"• {a.type.value}: {a.reasoning}" for a in plan.actions]),
            title=f"Turn Plan - {self.player_id}",
            border_style="blue",
        )
        console.print(panel)

    def _convert_actions_to_api(self, actions: list[GameAction], game_state: GameState = None) -> list[dict[str, Any]]:
        """Convert structured actions to API format with automatic unit ID resolution"""
        api_actions = []

        # If there are no actions or only PASS actions, return empty list
        non_pass_actions = [action for action in actions if action.type != ActionType.PASS]
        if not non_pass_actions:
            return []  # Empty list means "pass turn" to the backend

        # Get my units and cities for ID resolution
        my_units = []
        my_cities = []
        if game_state:
            my_units = [u for u in game_state.units.values() if u.owner == self.player_id]
            my_cities = [c for c in game_state.cities.values() if c.owner == self.player_id]

        for action in non_pass_actions:  # Only process non-pass actions
            try:
                if action.type == ActionType.MOVE:
                    unit_id = action.unit_id
                    if unit_id is None and my_units:
                        # Use first available unit
                        unit_id = my_units[0].id

                    api_action = {
                        "type": "MOVE",
                        "unit_id": unit_id,
                        "to": {
                            "x": action.target_location.x,
                            "y": action.target_location.y,
                        },
                    }

                elif action.type == ActionType.ATTACK:
                    unit_id = action.unit_id
                    if unit_id is None and my_units:
                        # Use first unit with attack capability
                        combat_units = [u for u in my_units if u.type in [UnitType.SOLDIER, UnitType.ARCHER]]
                        unit_id = combat_units[0].id if combat_units else my_units[0].id

                    api_action = {
                        "type": "ATTACK",
                        "attacker_id": unit_id,
                        "target_id": action.target_unit_id,
                        "target_type": "unit",
                    }

                elif action.type == ActionType.BUILD_IMPROVEMENT:
                    worker_id = action.unit_id
                    if worker_id is None and my_units:
                        # Use first worker unit
                        workers = [u for u in my_units if u.type == UnitType.WORKER]
                        worker_id = workers[0].id if workers else my_units[0].id

                    api_action = {
                        "type": "BUILD_IMPROVEMENT",
                        "worker_id": worker_id,
                        "improvement": (action.improvement_type.value if action.improvement_type is not None else None),
                    }

                elif action.type == ActionType.FOUND_CITY:
                    worker_id = action.unit_id
                    if worker_id is None and my_units:
                        # Use first worker unit
                        workers = [u for u in my_units if u.type == UnitType.WORKER]
                        worker_id = workers[0].id if workers else my_units[0].id

                    api_action = {
                        "type": "FOUND_CITY",
                        "worker_id": worker_id,
                    }

                elif action.type == ActionType.BUILD_UNIT:
                    city_id = action.unit_id  # Reusing unit_id field for city_id
                    if city_id is None and my_cities:
                        # Use first available city
                        city_id = my_cities[0].id

                    api_action = {
                        "type": "TRAIN_UNIT",
                        "city_id": city_id,
                        "unit_type": (action.unit_type.value if action.unit_type is not None else None),
                    }

                elif action.type == ActionType.BUILD_BUILDING:
                    city_id = action.unit_id  # Reusing unit_id field for city_id
                    if city_id is None and my_cities:
                        # Use first available city
                        city_id = my_cities[0].id

                    api_action = {
                        "type": "BUILD_BUILDING",
                        "city_id": city_id,
                        "building_type": (action.building_type.value if action.building_type is not None else None),
                    }

                else:
                    # Skip unknown action types (including PASS, DIPLOMACY, RESEARCH)
                    self.logger.warning(f"Skipping unsupported action type: {action.type}")
                    continue

                api_actions.append(api_action)

            except Exception as e:
                self.logger.warning(f"Failed to convert action {action.type}: {e}")
                # Skip invalid actions rather than failing completely
                continue

        return api_actions


if __name__ == "__main__":
    # Test the agent
    agent = FourXAgent("test_player", "balanced")
    console.print("Agent initialized successfully!")
