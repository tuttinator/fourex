export type PlayerId = string;

export type Terrain = "plains" | "forest" | "mountain" | "water";
export type Resource = "food" | "wood" | "ore" | "crystal" | "science";
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
	science: number;
}

export type TechId = string;

export interface Tech {
	id: TechId;
	name: string;
	cost_science: number;
	requires: TechId[];
	unlocks_units: UnitType[];
	unlocks_buildings: BuildingType[];
}

export interface ResearchState {
	completed: TechId[];
	active: TechId | null;
	progress: number;
}

export interface Tile {
	id: number;
	loc: Coord;
	terrain: Terrain;
	resource?: Resource;
	owner?: PlayerId;
	city_id?: number;
	unit_ids: number[];
	improvement?: ImprovementType;
}

export interface QueuedMoveOrder {
	type: "move";
	destination: Coord;
	known_enemy_ids: number[];
}

export type QueuedOrder = QueuedMoveOrder;

export type OrderCancellationReason =
	| "enemy_sighted"
	| "obstructed"
	| "attacked"
	| "completed";

export interface OrderCancelledEvent {
	id: number;
	turn: number;
	unit_id: number;
	owner: PlayerId;
	reason: OrderCancellationReason;
	destination?: Coord | null;
}

export type UnitAutomation = "auto_improve";

export type AutomationCancellationReason =
	| "enemy_adjacent"
	| "manual_override"
	| "no_target";

export interface AutomationCancelledEvent {
	id: number;
	turn: number;
	unit_id: number;
	owner: PlayerId;
	mode: UnitAutomation;
	reason: AutomationCancellationReason;
}

export interface Unit {
	id: number;
	owner: PlayerId;
	type: UnitType;
	hp: number;
	moves_left: number;
	loc: Coord;
	/** Phase 5: server-persisted multi-turn move orders. Scrubbed for
	 * non-owners by ``redact_state``. */
	orders_queue?: QueuedOrder[];
	/** Phase 5: true if the unit took damage on the previous turn —
	 * causes queued orders to cancel with reason ``attacked``. */
	took_damage_last_turn?: boolean;
	/** Phase 6: persistent automation mode. Scrubbed to ``null`` for
	 * non-owners so observers cannot tell whether a worker is on
	 * auto-improve. */
	automation?: UnitAutomation | null;
}

export interface BuildJob {
	/** "unit" or "building" — discriminator matches the backend. */
	type: string;
	/** UnitType or BuildingType value (e.g. "scout" / "granary"). */
	target: string;
	/** Production points accrued so far. */
	progress: number;
	/** Production points required for completion. */
	total_cost: number;
}

export interface City {
	id: number;
	owner: PlayerId;
	loc: Coord;
	hp: number;
	buildings: BuildingType[];
	/** Ordered production queue (Phase 4). Index 0 is the active job;
	 * remaining entries wait. Only the owner sees their own queue —
	 * redact_state returns an empty array for other viewers. */
	build_queue: BuildJob[];
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
	research: Record<PlayerId, ResearchState>;
	next_unit_id: number;
	next_city_id: number;
	max_turns: number;
	/** Phase 5: owner-scoped queued-order cancellation events. Redacted
	 * per-viewer so only the order owner sees events for their units. */
	order_events?: OrderCancelledEvent[];
	next_order_event_id?: number;
	/** Phase 6: owner-scoped automation-cancellation events. Same
	 * owner-scoped redaction as order_events. */
	automation_events?: AutomationCancelledEvent[];
	next_automation_event_id?: number;
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

/** One seat on a game's roster as exposed by /games. The backend includes
 * the seat's ``user_identity_id`` so the frontend can tell Resume apart
 * from Observe and flag agent-only games — MCP-minted keys leave
 * ``user_identity_id`` null, human-minted (Auth.js) keys carry the id. */
export interface SeatSummary {
	player_id: string;
	user_identity_id: number | null;
}

export interface GameSummary {
	game_id: string;
	player_slots: number;
	players: PlayerId[];
	/** Ordered seat roster with per-seat identity attribution. May be absent
	 * on older API responses; callers should treat ``undefined`` as "no seat
	 * metadata available" rather than an empty roster. */
	seats?: SeatSummary[];
	/** slot-0 player_id — used for the creator-only archive button. */
	creator?: string | null;
	turn: number;
	max_turns: number;
	status: "waiting" | "active" | "ended" | "created";
	winner: string | null;
	victory_type: string | null;
	end_reason?: string | null;
	/** Phase 4: soft-archive state. ``archived_at`` is ISO-8601 when set. */
	archived_at?: string | null;
	archived_reason?: "manual" | "stale_waiting" | "stale_active" | null;
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

/** Phase 3: per-slot configuration sent on POST /games. ``type``
 * selects Human / Agent. ``name`` is required for Agent slots and
 * matches the seated creator for the creator's Human slot; left null
 * for open Human slots. ``reserved_email`` is forward-compat with
 * Phase 5 invites and persisted but not yet acted on. */
export interface SlotConfigRequest {
	type: "human" | "agent";
	name?: string | null;
	reserved_email?: string | null;
}

export interface CreateLobbyRequest {
	player_id: string;
	player_slots: number;
	map_width?: number;
	map_height?: number;
	seed?: number;
	/** Phase 3: false → owner-only / all-Agent game; the creator is
	 * not seated in any slot and has no per-game API key. */
	creator_seated?: boolean;
	/** Phase 3: explicit per-slot type/name. Length must equal
	 * ``player_slots``. Omit for the legacy all-Human, creator-in-slot-0
	 * behaviour. */
	slots?: SlotConfigRequest[];
}

export interface JoinLobbyRequest {
	player_id: string;
}

export interface LobbyKeyResponse {
	game: GameDetailResponse;
	/** Phase 3: null when the creator opted out of taking a slot
	 * (all-Agent games). The owner authorises subsequent Start /
	 * regenerate-key actions via their Auth.js JWT in that case. */
	api_key: string | null;
}

/** Phase 2 lobby redesign: per-slot configuration surfaced on the
 * detail response. Every slot in Phase 2 is ``type: "human"`` with
 * ``name`` carrying the seated player id (or null for empty slots);
 * Agent slots and reserved Human slots land in Phase 3. ``slots``
 * is always an ordered list of length ``player_slots`` so the UI can
 * render the seat array directly without imputation. */
export interface SlotSummary {
	slot_index: number;
	type: "human" | "agent";
	name: string | null;
	reserved_email: string | null;
	player_api_key_id: number | null;
	/** Phase 3: plaintext API key for an Agent slot, surfaced only
	 * to the creator while ``status === "waiting"``. Cleared when the
	 * game starts; absent (null) for non-creators and Human slots. */
	plaintext_key?: string | null;
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
	end_reason?: string | null;
	archived_at?: string | null;
	archived_reason?: "manual" | "stale_waiting" | "stale_active" | null;
	created_at: string;
	updated_at: string;
	ended_at: string | null;
	/**
	 * Phase 1 lobby redesign: when the caller of GET /games/{id} is the
	 * game's creator AND the game is still ``waiting``, the backend echoes
	 * the bearer token back here so the lobby UI can render a copy-button
	 * affordance for the human to hand to an MCP agent. Absent for any
	 * other caller and absent the moment the game flips to ``active``.
	 */
	api_key?: string | null;
	/**
	 * Phase 2 lobby redesign: per-slot configuration. Defaults to an
	 * empty array on responses that predate the field; the lobby page
	 * falls back to the legacy ``players``-derived rendering in that
	 * case. Always length ``player_slots`` once Phase 2 is deployed.
	 */
	slots?: SlotSummary[];
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
	/** Phase 4: include soft-archived games in the response. Default is false. */
	include_archived?: boolean;
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
	/**
	 * Click handler for a map tile. The optional ``screen`` parameter
	 * carries the pointer's viewport coordinates so callers can anchor
	 * a floating UI (e.g. the stacked-tile selector) next to the click.
	 */
	onTileClick?: (tile: Tile, screen?: { x: number; y: number }) => void;
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
	/**
	 * Per-destination server-computed path for the selected unit. Keyed
	 * by ``"x,y"`` so the map can draw a connected path preview when the
	 * player hovers a reachable tile.
	 */
	movePathsByTile?: Record<string, Coord[]>;
	/** Tiles to render a red hostile-target highlight on (attack targets). */
	attackTiles?: Coord[];
	/** Phase 5 queued-order destinations (tiles beyond this turn's budget). */
	queueableTiles?: Coord[];
	/** Paths keyed by ``"x,y"`` for queueable destinations. */
	queueablePathsByTile?: Record<string, Coord[]>;
	/** Active queued path for the selected unit (destination first in
	 * tuple order), rendered as a persistent preview so the player can
	 * see where a queued unit is heading. */
	queuedOrderPath?: Coord[] | null;
	/** Active queued destination for the selected unit. */
	queuedOrderDestination?: Coord | null;
	/** Phase 7: when set, the map recentres on this tile. Wrapped in a
	 * fresh object reference each time the cycler fires so repeated
	 * requests to focus the same tile still trigger a recentre. */
	focusTile?: Coord | null;
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
	cost: number;
	path: Coord[];
	/** Alias of ``cost`` kept for backwards compatibility with Phase 4 callers. */
	distance: number;
}

export interface ValidMovesResponse {
	game_id: string;
	unit_id: number;
	moves_left: number;
	moves: ValidMoveTile[];
}

export interface QueueableTile {
	x: number;
	y: number;
	terrain: Terrain;
	cost: number;
	path: Coord[];
	distance: number;
	/** Minimum turns required at the unit's max move speed. */
	turns_required: number;
}

export interface QueueableTilesResponse {
	game_id: string;
	unit_id: number;
	tiles: QueueableTile[];
}

export interface MoveActionPayload {
	type: "MOVE";
	unit_id: number;
	to: Coord;
}

export interface AttackActionPayload {
	type: "ATTACK";
	attacker_id: number;
	/** Deterministic target by id — supply exactly one of target_id or target_tile. */
	target_id?: number;
	/** Tile-based target; server picks a defender via seeded RNG. Phase 3. */
	target_tile?: Coord;
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

export interface SendMessageActionPayload {
	type: "SEND_MESSAGE";
	recipient: PlayerId;
	body: string;
}

export interface ProposeTreatyActionPayload {
	type: "PROPOSE_TREATY";
	recipient: PlayerId;
	clauses: TreatyClause[];
}

export interface RespondToTreatyActionPayload {
	type: "RESPOND_TO_TREATY";
	proposal_id: number;
	accept: boolean;
}

export interface WithdrawTreatyActionPayload {
	type: "WITHDRAW_TREATY";
	proposal_id: number;
}

export interface CancelTreatyActionPayload {
	type: "CANCEL_TREATY";
	treaty_id: number;
}

export interface DeclareWarActionPayload {
	type: "DECLARE_WAR";
	target_player: PlayerId;
}

export interface SetCityProductionActionPayload {
	type: "SET_CITY_PRODUCTION";
	city_id: number;
	unit_type?: UnitType;
	building_type?: BuildingType;
}

export interface CancelCityProductionActionPayload {
	type: "CANCEL_CITY_PRODUCTION";
	city_id: number;
	queue_index: number;
}

export interface ReorderCityQueueActionPayload {
	type: "REORDER_CITY_QUEUE";
	city_id: number;
	new_order: number[];
}

export interface SetActiveResearchActionPayload {
	type: "SET_ACTIVE_RESEARCH";
	/** Tech id to make active. ``null`` clears the active slot and
	 * freezes accumulated progress. */
	tech_id: TechId | null;
}

export interface QueueOrderActionPayload {
	type: "QUEUE_ORDER";
	unit_id: number;
	destination: Coord;
}

export interface CancelOrderActionPayload {
	type: "CANCEL_ORDER";
	unit_id: number;
}

export interface SetAutomationActionPayload {
	type: "SET_AUTOMATION";
	unit_id: number;
	mode: UnitAutomation;
}

export interface ClearAutomationActionPayload {
	type: "CLEAR_AUTOMATION";
	unit_id: number;
}

export interface ResignActionPayload {
	type: "RESIGN";
}

export type GameAction =
	| MoveActionPayload
	| AttackActionPayload
	| FoundCityActionPayload
	| BuildImprovementActionPayload
	| TrainUnitActionPayload
	| BuildBuildingActionPayload
	| SendMessageActionPayload
	| ProposeTreatyActionPayload
	| RespondToTreatyActionPayload
	| WithdrawTreatyActionPayload
	| CancelTreatyActionPayload
	| DeclareWarActionPayload
	| SetCityProductionActionPayload
	| CancelCityProductionActionPayload
	| ReorderCityQueueActionPayload
	| SetActiveResearchActionPayload
	| QueueOrderActionPayload
	| CancelOrderActionPayload
	| SetAutomationActionPayload
	| ClearAutomationActionPayload
	| ResignActionPayload;

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
	/** Phase 6: the unit is gated on ``required_tech`` and the owning
	 * player has not completed that tech yet. UI should render locked
	 * entries greyed with a "Requires: <name>" tooltip rather than
	 * hiding them. */
	locked: boolean;
	/** Phase 6: tech id gating this unit, or null if always-available. */
	required_tech: TechId | null;
	/** Phase 6: display name for ``required_tech`` (e.g. "Archery"). */
	required_tech_name: string | null;
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
	/** Phase 6: same semantics as ``TrainableUnit.locked``. */
	locked: boolean;
	required_tech: TechId | null;
	required_tech_name: string | null;
}

export interface BuildableBuildingsResponse {
	game_id: string;
	city_id: number;
	buildings: BuildableBuilding[];
}

/** Phase 6 tech-tree endpoint response. Mirrors the MCP ``get_tech_tree``
 * shape so either front door can drive the same panel. */
export interface TechTreeResponse {
	game_id: string;
	player: PlayerId;
	tech_tree: Record<TechId, Tech>;
	research: ResearchState;
}

/** Phase 1 rules reference payload — single source of truth for every
 * game constant an agent or UI consumer needs. Mirrors the REST
 * ``GET /api/v1/rules`` and the MCP ``get_rules_reference`` tool. */
export interface RulesReferenceUnit {
	cost: ResourceBag;
	production_cost: number;
	moves: number;
	hp: number;
	sight: number;
	attack: number;
	attack_range: number;
	special: string;
	required_tech: TechId | null;
}

export interface RulesReferenceBuilding {
	cost: ResourceBag;
	production_cost: number;
	hp: number;
	effect: string;
	required_tech: TechId | null;
}

export interface RulesReferenceImprovement {
	cost: ResourceBag;
	valid_terrain: Terrain[];
	required_resource: Resource | null;
	effect: string;
}

export interface RulesReferenceTerrain {
	entry_cost: number | null;
	passable: boolean;
}

export interface RulesReferenceCombat {
	damage_formula: string;
	counter_attack: {
		formula: string;
		excluded_units: UnitType[];
		notes: string;
	};
	city_attack: {
		soldier_bonus_multiplier: number;
		notes: string;
	};
	city_counter_fire: {
		requires_building: BuildingType;
		damage: number;
		notes: string;
	};
	fortification: {
		city_defence_bonus: number;
		notes: string;
	};
	treacherous_attack: string;
}

export interface RulesReferenceStacking {
	cap_per_tile: number;
	symmetric: boolean;
	notes: string;
}

export interface RulesReferenceOrders {
	cancellation_conditions: string[];
	notes: string;
}

export interface RulesReferenceCities {
	base_production_per_turn: number;
	barracks_unit_production_bonus: number;
	base_science_per_turn: number;
	library_science_bonus: number;
	temple_science_bonus: number;
}

export interface RulesReference {
	schema_version: number;
	units: Record<UnitType, RulesReferenceUnit>;
	buildings: Record<BuildingType, RulesReferenceBuilding>;
	improvements: Record<ImprovementType, RulesReferenceImprovement>;
	terrain: Record<Terrain, RulesReferenceTerrain>;
	tech_tree: Record<TechId, Tech>;
	combat: RulesReferenceCombat;
	stacking: RulesReferenceStacking;
	orders: RulesReferenceOrders;
	cities: RulesReferenceCities;
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
