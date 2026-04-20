export type PlayerId = string;

export type Terrain = "plains" | "forest" | "mountain" | "water";
export type Resource = "food" | "wood" | "ore" | "crystal";
export type UnitType = "scout" | "worker" | "soldier" | "archer";
export type BuildingType =
	| "granary"
	| "barracks"
	| "walls"
	| "monument"
	| "library"
	| "temple";
export type ImprovementType =
	| "farm"
	| "mine"
	| "crystal_extractor"
	| "lumber_mill";
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

// Game summary for listing
export interface GameSummary {
	game_id: string;
	player_slots: number;
	players: PlayerId[];
	turn: number;
	max_turns: number;
	status: "waiting" | "active" | "ended" | "created";
	winner: string | null;
	victory_type: string | null;
	created_at: string;
	updated_at: string;
	ended_at: string | null;
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

export interface CreateLobbyRequest {
	player_id: string;
	player_slots: number;
	map_width?: number;
	map_height?: number;
	seed?: number;
}

export interface JoinLobbyRequest {
	player_id: string;
}

export interface LobbyKeyResponse {
	game: GameDetailResponse;
	api_key: string;
}

export interface GameDetailResponse {
	game_id: string;
	player_slots: number;
	players: PlayerId[];
	creator: string | null;
	turn: number;
	max_turns: number;
	map_width: number;
	map_height: number;
	seed: number;
	status: "waiting" | "active" | "ended" | "created";
	winner: string | null;
	victory_type: string | null;
	created_at: string;
	updated_at: string;
	ended_at: string | null;
}

export interface GamesListResponse {
	games: GameSummary[];
	total: number;
	offset: number;
	limit: number;
}

export interface GamesListParams {
	status?: "waiting" | "active" | "ended" | "created";
	sort_by?: "created_at" | "turn" | "status";
	sort_order?: "asc" | "desc";
	offset?: number;
	limit?: number;
}

// Turn history & replay types
export interface TurnSummary {
	turn_number: number;
	state_hash: string;
	player_count: number;
	completed_at: string | null;
}

export interface TurnListResponse {
	turns: TurnSummary[];
	total: number;
	offset: number;
	limit: number;
}

export interface TurnDetailResponse {
	turn_number: number;
	player_actions: Record<PlayerId, ActionResult[]>;
	action_results: Record<PlayerId, ActionResult[]>;
	state_hash: string;
	completed_at: string | null;
}

export interface PromptLogEntry {
	player_id: PlayerId;
	prompt: string;
	response: string;
	tokens_in: number;
	tokens_out: number;
	latency_ms: number;
	llm_provider: string | null;
	llm_model: string | null;
}

export interface TurnPromptsResponse {
	turn_number: number;
	prompts: PromptLogEntry[];
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
	/** Unit id to draw a selection ring around (Phase 4 gameplay). */
	selectedUnitId?: number | null;
	/** City id to draw a selection ring around (Phase 5 gameplay). */
	selectedCityId?: number | null;
	/** Tiles to render a semi-transparent highlight on (move targets). */
	highlightedTiles?: Coord[];
	/** Tiles to render a red hostile-target highlight on (attack targets). */
	attackTiles?: Coord[];
}

export interface PlayerListProps {
	players: PlayerId[];
	gameState: GameState;
	selectedPlayer?: PlayerId;
	onPlayerSelect: (player: PlayerId | null) => void;
	onFogToggle: (enabled: boolean) => void;
}

export interface PromptAccordionProps {
	prompts: PromptLogEntry[];
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

// Diplomacy types (Phase 1)

export interface DiplomacyRelation {
	player_a: PlayerId;
	player_b: PlayerId;
	state: "peace" | "alliance" | "war";
}

export interface DiplomacyEvent {
	id: number;
	type: string;
	actor: PlayerId;
	counterparty: PlayerId | null;
	turn: number;
	payload: Record<string, string>;
}

export interface DiplomacyMessage {
	id: number;
	sender: PlayerId;
	recipient: PlayerId;
	body: string;
	turn_sent: number;
}

export type TreatyClauseType =
	| "peace"
	| "free_text"
	| "resource_swap"
	| "recurring_tribute";

export interface TreatyClause {
	clause_type: TreatyClauseType;
	duration_turns?: number;
	turns_remaining?: number;
	text?: string;
	proposer_gives?: ResourceBag;
	recipient_gives?: ResourceBag;
	payer?: PlayerId;
	amount?: ResourceBag;
}

export interface TreatyProposalRecord {
	id: number;
	proposer: PlayerId;
	recipient: PlayerId;
	clauses: TreatyClause[];
	turn_proposed: number;
	expires_on_turn: number;
}

export interface TreatyRecord {
	id: number;
	parties: [PlayerId, PlayerId];
	clauses: TreatyClause[];
	turn_ratified: number;
}

export interface DiplomacyStateResponse {
	game_id: string;
	player: PlayerId;
	turn: number;
	discovered: PlayerId[];
	relations: DiplomacyRelation[];
	events: DiplomacyEvent[];
	messages: DiplomacyMessage[];
	pending_proposals: TreatyProposalRecord[];
	active_treaties: TreatyRecord[];
}

export interface MessageListResponse {
	game_id: string;
	player: PlayerId;
	turn: number;
	messages: DiplomacyMessage[];
}

// Gameplay queue (Phase 4)

export interface ValidMoveTile {
	x: number;
	y: number;
	terrain: Terrain;
	distance: number;
}

export interface ValidMovesResponse {
	game_id: string;
	unit_id: number;
	moves_left: number;
	moves: ValidMoveTile[];
}

export interface MoveActionPayload {
	type: "MOVE";
	unit_id: number;
	to: Coord;
}

export interface AttackActionPayload {
	type: "ATTACK";
	attacker_id: number;
	target_id: number;
	target_type: "unit" | "city";
}

export interface FoundCityActionPayload {
	type: "FOUND_CITY";
	worker_id: number;
}

export interface BuildImprovementActionPayload {
	type: "BUILD_IMPROVEMENT";
	worker_id: number;
	improvement: ImprovementType;
}

export interface TrainUnitActionPayload {
	type: "TRAIN_UNIT";
	city_id: number;
	unit_type: UnitType;
}

export interface BuildBuildingActionPayload {
	type: "BUILD_BUILDING";
	city_id: number;
	building_type: BuildingType;
}

export type GameAction =
	| MoveActionPayload
	| AttackActionPayload
	| FoundCityActionPayload
	| BuildImprovementActionPayload
	| TrainUnitActionPayload
	| BuildBuildingActionPayload;

// Phase 5 endpoint payloads --------------------------------------------------

export interface ValidAttackTarget {
	target_type: "unit" | "city";
	target_id: number;
	x: number;
	y: number;
	distance: number;
	owner: PlayerId;
	hp: number;
	diplomatic_state: "peace" | "alliance" | "war";
}

export interface ValidAttacksResponse {
	game_id: string;
	unit_id: number;
	attack_range: number;
	attack: number;
	targets: ValidAttackTarget[];
}

export interface CanFoundCityResponse {
	game_id: string;
	unit_id: number;
	can_found: boolean;
	reason: string | null;
	cost: { food: number };
}

export interface ValidImprovement {
	improvement: ImprovementType;
	cost: ResourceBag;
	affordable: boolean;
	terrain: Terrain;
	resource: Resource | null;
}

export interface ValidImprovementsResponse {
	game_id: string;
	unit_id: number;
	tile: Coord | null;
	improvements: ValidImprovement[];
}

export interface TrainableUnit {
	unit_type: UnitType;
	cost: ResourceBag;
	affordable: boolean;
	stats: {
		hp: number;
		moves: number;
		sight: number;
		attack: number;
		attack_range: number;
	};
}

export interface TrainableUnitsResponse {
	game_id: string;
	city_id: number;
	units: TrainableUnit[];
}

export interface BuildableBuilding {
	building_type: BuildingType;
	cost: ResourceBag;
	affordable: boolean;
	already_built: boolean;
	effect: string;
}

export interface BuildableBuildingsResponse {
	game_id: string;
	city_id: number;
	buildings: BuildableBuilding[];
}

export interface QueuedAction {
	/** Client-side id for removal from the queue before submit. */
	queue_id: string;
	action: GameAction;
	/** Server-validation error returned on End Turn, if any. */
	error?: string;
}

export interface MySubmissionResponse {
	game_id: string;
	player: PlayerId;
	turn: number;
	submitted: boolean;
	actions: GameAction[];
	submitted_at?: string | null;
}

export interface TurnSubmissionsResponse {
	game_id: string;
	turn: number;
	players: PlayerId[];
	submitted_players: PlayerId[];
}

export const MESSAGE_BODY_MAX_LENGTH = 2000;
export const MESSAGES_PER_TURN_LIMIT = 5;
export const FREE_TEXT_CLAUSE_MAX_LENGTH = 500;
export const PEACE_CLAUSE_MAX_DURATION = 100;
export const TREATY_PROPOSAL_EXPIRY_TURNS = 3;
