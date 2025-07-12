from dataclasses import dataclass
from enum import Enum
from typing import Any

import instructor
import requests
from openai import OpenAI
from pydantic import BaseModel, Field
from rich.console import Console
from rich.panel import Panel

console = Console()


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
    reasoning: str = Field(
        description="Brief explanation of why this action was chosen"
    )


class TurnPlan(BaseModel):
    actions: list[GameAction] = Field(description="List of actions to take this turn")
    strategic_analysis: str = Field(
        description="Analysis of current game state and strategy"
    )
    priorities: list[str] = Field(description="Current priorities for this turn")


class GameClient:
    """Client for interacting with the game backend"""

    def __init__(
        self,
        base_url: str = "http://localhost:8000/api/v1",
        player_id: str | None = None
    ):
        self.base_url = base_url
        self.session = requests.Session()
        if player_id:
            self.session.headers.update({
                "Authorization": f"Bearer player_{player_id}"
            })

    def get_game_state(self, game_id: str) -> GameState:
        """Get current game state"""
        response = self.session.get(f"{self.base_url}/state?game_id={game_id}")
        response.raise_for_status()
        data = response.json()

        # Convert to our dataclasses
        return self._parse_game_state(data)

    def submit_actions(
        self, game_id: str, player_id: str, actions: list[dict[str, Any]]
    ) -> bool:
        """Submit actions for a player"""
        response = self.session.post(
            f"{self.base_url}/actions?game_id={game_id}",
            json=actions
        )
        response.raise_for_status()
        return response.json().get("status") == "actions_submitted"

    def get_prompts(self, game_id: str, turn: int) -> list[dict[str, Any]]:
        """Get prompt logs for a turn"""
        response = self.session.get(
            f"{self.base_url}/logs/{game_id}/turn-{turn}/prompts"
        )
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
                resource=Resource(tile_data["resource"])
                if tile_data.get("resource")
                else None,
                owner=tile_data.get("owner"),
                city_id=tile_data.get("city_id"),
                unit_id=tile_data.get("unit_id"),
                improvement=ImprovementType(tile_data["improvement"])
                if tile_data.get("improvement")
                else None,
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


class LLMClient:
    """Client for interacting with LLM Studio"""

    def __init__(
        self, base_url: str = "http://localhost:1234/v1", model: str = "qwen/qwen3-32b"
    ):
        self.client = instructor.from_openai(
            OpenAI(base_url=base_url, api_key="not-needed"),
            mode=instructor.Mode.MD_JSON,
        )
        self.model = model

    def generate_plan(
        self, game_state: GameState, player_id: str, personality: str = "balanced"
    ) -> TurnPlan:
        """Generate a turn plan using the LLM"""

        # Create game state summary
        state_summary = self._create_state_summary(game_state, player_id)

        # Create system prompt based on personality
        system_prompt = self._create_system_prompt(personality)

        # Create user prompt
        user_prompt = f"""
Game State Analysis:
{state_summary}

Current Turn: {game_state.turn}/{game_state.max_turns}

Please analyze the current game state and provide a strategic plan for this turn.
Consider your current position, available resources, threats, and opportunities.
"""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_model=TurnPlan,
                temperature=0.7,
                max_tokens=2000,
            )
            return response
        except Exception as e:
            console.print(f"[red]Error generating plan: {e}[/red]")
            # Return a default plan with pass action
            return TurnPlan(
                actions=[
                    GameAction(
                        type=ActionType.PASS, reasoning="Failed to generate plan"
                    )
                ],
                strategic_analysis="Unable to analyze game state due to LLM error",
                priorities=["Survive"],
            )

    def _create_state_summary(self, game_state: GameState, player_id: str) -> str:
        """Create a concise summary of the game state"""
        my_units = [u for u in game_state.units.values() if u.owner == player_id]
        my_cities = [c for c in game_state.cities.values() if c.owner == player_id]
        my_resources = game_state.stockpiles.get(player_id, ResourceBag(0, 0, 0, 0))

        # Get visible tiles (simplified - in real game would consider fog of war)
        visible_tiles = game_state.tiles

        summary = f"""
Player: {player_id}
Resources: Food={my_resources.food}, Wood={my_resources.wood}, Ore={my_resources.ore}, Crystal={my_resources.crystal}
Units: {len(my_units)} ({", ".join([f"{u.type.value}@({u.loc.x},{u.loc.y})" for u in my_units])})
Cities: {len(my_cities)} ({", ".join([f"City@({c.loc.x},{c.loc.y})" for c in my_cities])})

Map Size: {game_state.map_width}x{game_state.map_height}
Other Players: {[p for p in game_state.players if p != player_id]}

Key Terrain Features:
- Plains: {len([t for t in visible_tiles if t.terrain == Terrain.PLAINS])}
- Forest: {len([t for t in visible_tiles if t.terrain == Terrain.FOREST])}
- Mountains: {len([t for t in visible_tiles if t.terrain == Terrain.MOUNTAIN])}
- Water: {len([t for t in visible_tiles if t.terrain == Terrain.WATER])}

Resources on Map:
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


class FourXAgent:
    """Main agent class for playing 4X games"""

    def __init__(
        self,
        player_id: str,
        personality: str = "balanced",
        game_client: GameClient | None = None,
        llm_client: LLMClient | None = None,
        game_backend_url: str = "http://localhost:8000/api/v1",
    ):
        self.player_id = player_id
        self.personality = personality
        self.game_client = game_client or GameClient(
            base_url=game_backend_url, player_id=player_id
        )
        self.llm_client = llm_client or LLMClient()
        self.turn_history: list[TurnPlan] = []

        console.print(
            f"[green]Agent {player_id} initialized with {personality} personality[/green]"
        )

    def play_turn(self, game_id: str) -> bool:
        """Play a single turn"""
        try:
            # Get current game state
            game_state = self.game_client.get_game_state(game_id)

            # Check if it's our turn or if game is over
            if game_state.turn >= game_state.max_turns:
                console.print(f"[yellow]Game {game_id} has ended[/yellow]")
                return False

            # Generate turn plan
            console.print(
                f"[blue]Turn {game_state.turn}: {self.player_id} is planning...[/blue]"
            )
            plan = self.llm_client.generate_plan(
                game_state, self.player_id, self.personality
            )

            # Display plan
            self._display_plan(plan)

            # Convert actions to API format
            api_actions = self._convert_actions_to_api(plan.actions)

            # Submit actions
            success = self.game_client.submit_actions(
                game_id, self.player_id, api_actions
            )

            if success:
                console.print("[green]Actions submitted successfully[/green]")
                self.turn_history.append(plan)
            else:
                console.print("[red]Failed to submit actions[/red]")

            return success

        except Exception as e:
            console.print(f"[red]Error playing turn: {e}[/red]")
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

    def _convert_actions_to_api(
        self, actions: list[GameAction]
    ) -> list[dict[str, Any]]:
        """Convert structured actions to API format"""
        api_actions = []

        for action in actions:
            if action.type == ActionType.MOVE:
                api_action = {
                    "type": "MOVE",
                    "unit_id": action.unit_id,
                    "to": {
                        "x": action.target_location.x,
                        "y": action.target_location.y,
                    },
                }
            elif action.type == ActionType.ATTACK:
                api_action = {
                    "type": "ATTACK",
                    "attacker_id": action.unit_id,
                    "target_id": action.target_unit_id,
                    "target_type": "unit",  # Default to unit, could be improved
                }
            elif action.type == ActionType.BUILD_IMPROVEMENT:
                api_action = {
                    "type": "BUILD_IMPROVEMENT",
                    "worker_id": action.unit_id,
                    "improvement": action.improvement_type.value,
                }
            elif action.type == ActionType.FOUND_CITY:
                api_action = {
                    "type": "FOUND_CITY",
                    "worker_id": action.unit_id or 1,  # Default worker ID
                }
            elif action.type == ActionType.TRAIN_UNIT:
                api_action = {
                    "type": "TRAIN_UNIT",
                    "city_id": action.unit_id,  # Reusing unit_id field for city_id
                    "unit_type": action.unit_type.value,
                }
            elif action.type == ActionType.BUILD_BUILDING:
                api_action = {
                    "type": "BUILD_BUILDING",
                    "city_id": action.unit_id,  # Reusing unit_id field for city_id
                    "building_type": action.building_type.value,
                }
            else:
                # Fallback to old format for unknown action types
                api_action = {"type": action.type.value}
                if action.unit_id is not None:
                    api_action["unit_id"] = action.unit_id
                if action.target_location is not None:
                    api_action["target_location"] = {
                        "x": action.target_location.x,
                        "y": action.target_location.y,
                    }

            api_actions.append(api_action)

        return api_actions


if __name__ == "__main__":
    # Test the agent
    agent = FourXAgent("test_player", "balanced")
    console.print("Agent initialized successfully!")
