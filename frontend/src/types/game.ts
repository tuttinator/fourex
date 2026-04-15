export type PlayerId = string;

export type Terrain = "plains" | "forest" | "mountain" | "water";
export type Resource = "food" | "wood" | "ore" | "crystal";
export type UnitType = "scout" | "worker" | "soldier" | "archer";
export type BuildingType = "granary" | "barracks" | "walls";
export type ImprovementType = "farm" | "mine" | "crystal_extractor";
export type DiplomaticState = "peace" | "alliance" | "war";

export interface Coord {
	x: number;
	y: number;
}

export interface ResourceBag {
	food: number;
	wood: number;
	ore: number;
	crystal: number;
}

export interface Tile {
	id: number;
	loc: Coord;
	terrain: Terrain;
	resource?: Resource;
	owner?: PlayerId;
	city_id?: number;
	unit_id?: number;
	improvement?: ImprovementType;
}

export interface Unit {
	id: number;
	owner: PlayerId;
	type: UnitType;
	hp: number;
	moves_left: number;
	loc: Coord;
}

export interface City {
	id: number;
	owner: PlayerId;
	loc: Coord;
	hp: number;
	buildings: BuildingType[];
}

export interface GameState {
	turn: number;
	rng_state: number;
	map_width: number;
	map_height: number;
	tiles: Tile[];
	units: Record<number, Unit>;
	cities: Record<number, City>;
	players: PlayerId[];
	diplomacy: Record<string, DiplomaticState>;
	stockpiles: Record<PlayerId, ResourceBag>;
	next_unit_id: number;
	next_city_id: number;
	max_turns: number;
}

export interface PromptLog {
	player: PlayerId;
	prompt: string;
	response: string;
	tokens_in: number;
	tokens_out: number;
	latency_ms: number;
}

export interface ActionResult {
	success: boolean;
	message: string;
	action: unknown;
}

export interface TurnResult {
	turn: number;
	player_actions: Record<PlayerId, ActionResult[]>;
	state_hash: string;
}

// Game list for lobby
export interface GameInfo {
	id: string;
	turn: number;
	players: PlayerId[];
	status: "active" | "finished";
	created_at: string;
	winner?: PlayerId;
}

// API responses
export interface ApiResponse<T> {
	data?: T;
	error?: string;
	message?: string;
}

export interface CreateGameRequest {
	players: PlayerId[];
	seed?: number;
}

export interface GameListResponse {
	games: string[];
}

// Frontend-specific types
export interface GameStore {
	gameId: string | null;
	turns: Record<number, GameState>;
	latestTurn: number;
	selectedTurn: number;
	prompts: Record<number, PromptLog[]>;
	selectedPlayer: PlayerId | null;
	fogOfWarEnabled: boolean;
	isLoading: boolean;
	error: string | null;
}

export interface MapViewport {
	x: number;
	y: number;
	scale: number;
}

export interface HoverInfo {
	tile?: Tile;
	unit?: Unit;
	city?: City;
	position: { x: number; y: number };
}

// Component props
export interface MapCanvasProps {
	gameState: GameState;
	selectedPlayer?: PlayerId;
	fogOfWarEnabled?: boolean;
	onTileClick?: (tile: Tile) => void;
	onUnitClick?: (unit: Unit) => void;
	onCityClick?: (city: City) => void;
	viewport?: MapViewport;
	onViewportChange?: (viewport: MapViewport) => void;
}

export interface PlayerListProps {
	players: PlayerId[];
	gameState: GameState;
	selectedPlayer?: PlayerId;
	onPlayerSelect: (player: PlayerId | null) => void;
	onFogToggle: (enabled: boolean) => void;
}

export interface PromptAccordionProps {
	prompts: PromptLog[];
	players: PlayerId[];
	selectedTurn: number;
}

export const UNIT_COLORS: Record<UnitType, string> = {
	scout: "#22c55e",
	worker: "#3b82f6",
	soldier: "#ef4444",
	archer: "#a855f7",
};

export const TERRAIN_COLORS: Record<Terrain, string> = {
	plains: "#8fbc8f",
	forest: "#228b22",
	mountain: "#696969",
	water: "#4682b4",
};

export const PLAYER_COLORS: Record<number, string> = {
	0: "#ff6b6b",
	1: "#4ecdc4",
	2: "#45b7d1",
	3: "#96ceb4",
	4: "#ffeaa7",
	5: "#dda0dd",
	6: "#98d8c8",
	7: "#f7dc6f",
};
