import { getGameApiKey } from "@/lib/game-auth";
import type {
	BuildableBuildingsResponse,
	CanFoundCityResponse,
	CreateGameRequest,
	CreateLobbyRequest,
	DiplomacyStateResponse,
	GameAction,
	GameDetailResponse,
	GamesListParams,
	GamesListResponse,
	GameState,
	InviteSlotResponse,
	JoinLobbyRequest,
	LobbyKeyResponse,
	ReconfigureSlotsRequest,
	MessageListResponse,
	MySubmissionResponse,
	QueueableTilesResponse,
	RulesReference,
	SavedMap,
	SavedMapCreateRequest,
	SavedMapSummary,
	SavedMapUpdateRequest,
	TechTreeResponse,
	TrainableUnitsResponse,
	TreatyClause,
	TurnDetailResponse,
	TurnListResponse,
	TurnPromptsResponse,
	TurnSubmissionsResponse,
	ValidAttacksResponse,
	ValidImprovementsResponse,
	ValidMovesResponse,
} from "@/types/game";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL;
if (!API_BASE_URL) {
	throw new Error(
		"NEXT_PUBLIC_API_URL is not set. It must be defined at build time — " +
			"Next.js inlines NEXT_PUBLIC_* vars into the client bundle.",
	);
}

export class ApiError extends Error {
	constructor(
		public status: number,
		message: string,
	) {
		super(message);
		this.name = "ApiError";
	}
}

// FastAPI returns pydantic validation errors as an array of objects
// (`{loc, msg, type, ...}`). Naively stringifying that yields
// `[object Object],[object Object]`, so we format each entry as
// `field: msg` to surface a useful message in toasts.
function formatErrorDetail(detail: unknown): string | null {
	if (typeof detail === "string") return detail;
	if (Array.isArray(detail)) {
		const parts = detail.map((entry) => {
			if (entry && typeof entry === "object") {
				const e = entry as { loc?: unknown[]; msg?: string };
				const field = Array.isArray(e.loc)
					? e.loc.filter((p) => p !== "body").join(".")
					: "";
				const msg = e.msg ?? JSON.stringify(entry);
				return field ? `${field}: ${msg}` : msg;
			}
			return String(entry);
		});
		return parts.join("; ");
	}
	return null;
}

interface FetchApiOptions extends RequestInit {
	/** Scope the per-game API key lookup. If omitted, no Authorization header. */
	gameId?: string | null;
}

async function fetchApi<T>(
	endpoint: string,
	options: FetchApiOptions = {},
): Promise<T> {
	const { gameId, headers: overrideHeaders, ...rest } = options;
	const url = `${API_BASE_URL}${endpoint}`;

	const defaultHeaders: Record<string, string> = {
		"Content-Type": "application/json",
	};

	if (gameId) {
		const apiKey = getGameApiKey(gameId);
		if (apiKey) {
			defaultHeaders["Authorization"] = `Bearer ${apiKey}`;
		}
	}

	const config: RequestInit = {
		...rest,
		headers: {
			...defaultHeaders,
			...overrideHeaders,
		},
	};

	try {
		const response = await fetch(url, config);

		if (!response.ok) {
			const errorData = await response
				.json()
				.catch(() => ({ message: "Unknown error" }));
			throw new ApiError(
				response.status,
				formatErrorDetail(errorData.detail) ||
					errorData.message ||
					"Request failed",
			);
		}

		const data = await response.json();
		return data;
	} catch (error) {
		if (error instanceof ApiError) {
			throw error;
		}
		throw new ApiError(
			0,
			error instanceof Error ? error.message : "Network error",
		);
	}
}

async function fetchBff<T>(path: string, init: RequestInit): Promise<T> {
	const response = await fetch(path, {
		...init,
		headers: {
			"Content-Type": "application/json",
			...(init.headers ?? {}),
		},
	});
	if (!response.ok) {
		const errorData = await response
			.json()
			.catch(() => ({ detail: "Unknown error" }));
		throw new ApiError(
			response.status,
			formatErrorDetail(errorData.detail) ||
				errorData.message ||
				"Request failed",
		);
	}
	return response.json();
}

export const api = {
	async listGames(
		params: GamesListParams = {},
	): Promise<GamesListResponse> {
		const searchParams = new URLSearchParams();
		if (params.status) searchParams.set("status", params.status);
		if (params.sort_by) searchParams.set("sort_by", params.sort_by);
		if (params.sort_order) searchParams.set("sort_order", params.sort_order);
		if (params.offset !== undefined)
			searchParams.set("offset", String(params.offset));
		if (params.limit !== undefined)
			searchParams.set("limit", String(params.limit));
		if (params.include_archived)
			searchParams.set("include_archived", "true");

		const qs = searchParams.toString();
		return fetchApi<GamesListResponse>(`/games${qs ? `?${qs}` : ""}`);
	},

	async archiveGame(gameId: string): Promise<GameDetailResponse> {
		// Routed through the Next.js BFF so the Auth.js JWT (HttpOnly cookie)
		// can be forwarded to FastAPI server-side.
		return fetchBff<GameDetailResponse>(
			`/api/lobbies/${encodeURIComponent(gameId)}/archive`,
			{ method: "POST" },
		);
	},

	async unarchiveGame(gameId: string): Promise<GameDetailResponse> {
		return fetchBff<GameDetailResponse>(
			`/api/lobbies/${encodeURIComponent(gameId)}/unarchive`,
			{ method: "POST" },
		);
	},

	async createGame(
		gameId: string,
		request: CreateGameRequest,
	): Promise<GameState> {
		return fetchApi(`/games/${gameId}/start`, {
			method: "POST",
			body: JSON.stringify(request),
		});
	},

	async createLobby(
		gameId: string,
		request: CreateLobbyRequest,
	): Promise<LobbyKeyResponse> {
		// Routed through the Next.js BFF so the Auth.js JWT (stored in an
		// HttpOnly cookie) can be forwarded to FastAPI server-side.
		return fetchBff<LobbyKeyResponse>(
			`/api/lobbies?game_id=${encodeURIComponent(gameId)}`,
			{ method: "POST", body: JSON.stringify(request) },
		);
	},

	async getGameDetail(gameId: string): Promise<GameDetailResponse> {
		// Routed through the BFF so the Auth.js JWT (HttpOnly cookie) is
		// forwarded server-side. The backend uses either the per-game
		// bearer (seated creator, attached automatically by fetchApi for
		// gameplay calls) OR the JWT (all-Agent owner) to recognise the
		// caller as the lobby's creator and surface the per-slot
		// plaintext keys + ``api_key`` echo. Spectators (no JWT) get a
		// public response.
		return fetchBff<GameDetailResponse>(
			`/api/lobbies/${encodeURIComponent(gameId)}`,
			{ method: "GET" },
		);
	},

	async joinLobby(
		gameId: string,
		request: JoinLobbyRequest,
	): Promise<LobbyKeyResponse> {
		return fetchBff<LobbyKeyResponse>(
			`/api/lobbies/${encodeURIComponent(gameId)}/join`,
			{ method: "POST", body: JSON.stringify(request) },
		);
	},

	async leaveGame(gameId: string): Promise<GameDetailResponse> {
		return fetchApi(`/games/${encodeURIComponent(gameId)}/leave`, {
			method: "POST",
			gameId,
		});
	},

	async startGame(
		gameId: string,
	): Promise<{ status: string; game_id: string }> {
		return fetchApi(`/games/${encodeURIComponent(gameId)}/start`, {
			method: "POST",
			gameId,
		});
	},

	/** Phase 3: Start an all-Agent lobby as its (unseated) owner. The
	 * owner has no per-game key in this case so the request is routed
	 * through the BFF, which forwards the Auth.js JWT server-side. */
	async startGameAsOwner(
		gameId: string,
	): Promise<{ status: string; game_id: string }> {
		return fetchBff<{ status: string; game_id: string }>(
			`/api/lobbies/${encodeURIComponent(gameId)}/start-as-owner`,
			{ method: "POST" },
		);
	},

	/** Phase 3: Mint a fresh API key for an Agent slot. Routed through
	 * the BFF so either auth path (per-game key OR JWT) is forwarded —
	 * the BFF always sends the JWT, and the backend's
	 * ``require_creator_auth`` accepts that for the all-Agent case. */
	async regenerateSlotKey(
		gameId: string,
		slotIndex: number,
	): Promise<{ slot_index: number; plaintext_key: string }> {
		return fetchBff<{ slot_index: number; plaintext_key: string }>(
			`/api/lobbies/${encodeURIComponent(gameId)}/slots/${slotIndex}/regenerate-key`,
			{ method: "POST" },
		);
	},

	/** Phase 4: replace the lobby's slot configuration. Routed through
	 * the BFF so the Auth.js JWT (HttpOnly cookie) reaches the
	 * backend's ``require_creator_auth`` for both seated-creator and
	 * all-Agent-owner cases. The backend diffs the supplied slot array
	 * against the current ``lobby_slots`` and applies the legal
	 * transitions (Human→Agent for empty slots, Agent→Human invalidates
	 * the agent's key, Agent rename re-binds the existing key). */
	async reconfigureSlots(
		gameId: string,
		request: ReconfigureSlotsRequest,
	): Promise<GameDetailResponse> {
		return fetchBff<GameDetailResponse>(
			`/api/lobbies/${encodeURIComponent(gameId)}/slots`,
			{ method: "PUT", body: JSON.stringify(request) },
		);
	},

	/** Phase 5: (re)send a Resend-delivered invite for a Human slot
	 * reservation. Routed through the BFF so the JWT (HttpOnly cookie)
	 * reaches the backend's creator-auth dependency. */
	async inviteSlot(
		gameId: string,
		slotIndex: number,
		email: string,
	): Promise<InviteSlotResponse> {
		return fetchBff<InviteSlotResponse>(
			`/api/lobbies/${encodeURIComponent(gameId)}/slots/${slotIndex}/invite`,
			{ method: "POST", body: JSON.stringify({ email }) },
		);
	},

	/** Phase 5: drop the reservation on a slot, invalidating any
	 * outstanding invite token. Returns the refreshed game detail. */
	async clearSlotInvite(
		gameId: string,
		slotIndex: number,
	): Promise<GameDetailResponse> {
		return fetchBff<GameDetailResponse>(
			`/api/lobbies/${encodeURIComponent(gameId)}/slots/${slotIndex}/invite/clear`,
			{ method: "POST" },
		);
	},

	async getGameState(gameId: string): Promise<GameState> {
		return fetchApi(`/state?game_id=${gameId}`, { gameId });
	},

	async getValidMoves(
		gameId: string,
		unitId: number,
	): Promise<ValidMovesResponse> {
		return fetchApi(
			`/games/${encodeURIComponent(gameId)}/units/${unitId}/valid-moves`,
			{ gameId },
		);
	},

	async getValidAttacks(
		gameId: string,
		unitId: number,
	): Promise<ValidAttacksResponse> {
		return fetchApi(
			`/games/${encodeURIComponent(gameId)}/units/${unitId}/valid-attacks`,
			{ gameId },
		);
	},

	async getQueueableTiles(
		gameId: string,
		unitId: number,
	): Promise<QueueableTilesResponse> {
		return fetchApi(
			`/games/${encodeURIComponent(gameId)}/units/${unitId}/queueable-tiles`,
			{ gameId },
		);
	},

	async getCanFoundCity(
		gameId: string,
		unitId: number,
	): Promise<CanFoundCityResponse> {
		return fetchApi(
			`/games/${encodeURIComponent(gameId)}/units/${unitId}/can-found-city`,
			{ gameId },
		);
	},

	async getValidImprovements(
		gameId: string,
		unitId: number,
	): Promise<ValidImprovementsResponse> {
		return fetchApi(
			`/games/${encodeURIComponent(gameId)}/units/${unitId}/valid-improvements`,
			{ gameId },
		);
	},

	async getTrainableUnits(
		gameId: string,
		cityId: number,
	): Promise<TrainableUnitsResponse> {
		return fetchApi(
			`/games/${encodeURIComponent(gameId)}/cities/${cityId}/trainable-units`,
			{ gameId },
		);
	},

	async getBuildableBuildings(
		gameId: string,
		cityId: number,
	): Promise<BuildableBuildingsResponse> {
		return fetchApi(
			`/games/${encodeURIComponent(gameId)}/cities/${cityId}/buildable-buildings`,
			{ gameId },
		);
	},

	async getTechTree(gameId: string): Promise<TechTreeResponse> {
		return fetchApi(`/games/${encodeURIComponent(gameId)}/tech-tree`, {
			gameId,
		});
	},

	async getRulesReference(): Promise<RulesReference> {
		return fetchApi(`/rules`);
	},

	async submitActions(
		gameId: string,
		actions: GameAction[],
	): Promise<{ status: string; count: string }> {
		return fetchApi(`/actions?game_id=${encodeURIComponent(gameId)}`, {
			method: "POST",
			body: JSON.stringify(actions),
			gameId,
		});
	},

	async resignGame(
		gameId: string,
	): Promise<{ status: string; count: string }> {
		return fetchApi(`/actions?game_id=${encodeURIComponent(gameId)}`, {
			method: "POST",
			body: JSON.stringify([{ type: "RESIGN" }]),
			gameId,
		});
	},

	async getMySubmission(gameId: string): Promise<MySubmissionResponse> {
		return fetchApi(
			`/games/${encodeURIComponent(gameId)}/my-submission`,
			{ gameId },
		);
	},

	async getTurnSubmissions(
		gameId: string,
	): Promise<TurnSubmissionsResponse> {
		return fetchApi(
			`/games/${encodeURIComponent(gameId)}/turn-submissions`,
			{ gameId },
		);
	},

	async getGameStateAsPlayer(
		gameId: string,
		playerId: string,
	): Promise<GameState> {
		// `as_player` asks the backend to redact the response as if the
		// caller were ``playerId`` — used by observers (e.g. an unseated
		// lobby creator) switching perspective in the spectator UI. Strictly
		// less information than the unauthenticated god-mode response, so no
		// extra auth is required.
		const qs = new URLSearchParams({
			game_id: gameId,
			as_player: playerId,
		});
		return fetchApi(`/state?${qs.toString()}`, { gameId });
	},

	async listTurns(
		gameId: string,
		params: { offset?: number; limit?: number } = {},
	): Promise<TurnListResponse> {
		const searchParams = new URLSearchParams();
		if (params.offset !== undefined)
			searchParams.set("offset", String(params.offset));
		if (params.limit !== undefined)
			searchParams.set("limit", String(params.limit));
		const qs = searchParams.toString();
		return fetchApi(
			`/games/${encodeURIComponent(gameId)}/turns${qs ? `?${qs}` : ""}`,
			{ gameId },
		);
	},

	async getTurnDetail(
		gameId: string,
		turnNumber: number,
	): Promise<TurnDetailResponse> {
		return fetchApi(
			`/games/${encodeURIComponent(gameId)}/turns/${turnNumber}`,
			{ gameId },
		);
	},

	async getTurnState(
		gameId: string,
		turnNumber: number,
		player?: string,
	): Promise<GameState> {
		const params = player ? `?player=${encodeURIComponent(player)}` : "";
		return fetchApi(
			`/games/${encodeURIComponent(gameId)}/turns/${turnNumber}/state${params}`,
			{ gameId },
		);
	},

	async getTurnPrompts(
		gameId: string,
		turnNumber: number,
	): Promise<TurnPromptsResponse> {
		return fetchApi(
			`/games/${encodeURIComponent(gameId)}/turns/${turnNumber}/prompts`,
			{ gameId },
		);
	},

	async getDiplomacy(gameId: string): Promise<DiplomacyStateResponse> {
		return fetchApi(
			`/games/${encodeURIComponent(gameId)}/diplomacy`,
			{ gameId },
		);
	},

	async declareWar(
		gameId: string,
		targetPlayer: string,
	): Promise<{ status: string; target: string }> {
		return fetchApi(
			`/games/${encodeURIComponent(gameId)}/diplomacy/declare-war`,
			{
				method: "POST",
				body: JSON.stringify({ target_player: targetPlayer }),
				gameId,
			},
		);
	},

	async listMessages(
		gameId: string,
		params: { counterparty?: string; since_turn?: number } = {},
	): Promise<MessageListResponse> {
		const searchParams = new URLSearchParams();
		if (params.counterparty)
			searchParams.set("counterparty", params.counterparty);
		if (params.since_turn !== undefined)
			searchParams.set("since_turn", String(params.since_turn));
		const qs = searchParams.toString();
		return fetchApi(
			`/games/${encodeURIComponent(gameId)}/diplomacy/messages${qs ? `?${qs}` : ""}`,
			{ gameId },
		);
	},

	async sendMessage(
		gameId: string,
		recipient: string,
		body: string,
	): Promise<{ status: string; recipient: string }> {
		return fetchApi(
			`/games/${encodeURIComponent(gameId)}/diplomacy/messages`,
			{
				method: "POST",
				body: JSON.stringify({ recipient, body }),
				gameId,
			},
		);
	},

	async proposeTreaty(
		gameId: string,
		recipient: string,
		clauses: TreatyClause[],
	): Promise<{ status: string; recipient: string }> {
		return fetchApi(
			`/games/${encodeURIComponent(gameId)}/diplomacy/treaties/proposals`,
			{
				method: "POST",
				body: JSON.stringify({ recipient, clauses }),
				gameId,
			},
		);
	},

	async respondToTreaty(
		gameId: string,
		proposalId: number,
		accept: boolean,
	): Promise<{ status: string; proposal_id: number; accept: boolean }> {
		return fetchApi(
			`/games/${encodeURIComponent(gameId)}/diplomacy/treaties/proposals/${proposalId}/respond`,
			{
				method: "POST",
				body: JSON.stringify({ accept }),
				gameId,
			},
		);
	},

	async withdrawTreaty(
		gameId: string,
		proposalId: number,
	): Promise<{ status: string; proposal_id: number }> {
		return fetchApi(
			`/games/${encodeURIComponent(gameId)}/diplomacy/treaties/proposals/${proposalId}`,
			{
				method: "DELETE",
				gameId,
			},
		);
	},

	async cancelTreaty(
		gameId: string,
		treatyId: number,
	): Promise<{ status: string; treaty_id: number }> {
		return fetchApi(
			`/games/${encodeURIComponent(gameId)}/diplomacy/treaties/${treatyId}`,
			{
				method: "DELETE",
				gameId,
			},
		);
	},

	// Phase 4 (map system overhaul): saved-map authoring + listing.
	// All four verbs are routed through the BFF so the Auth.js JWT
	// (HttpOnly cookie) reaches FastAPI server-side.
	async listSavedMaps(): Promise<SavedMapSummary[]> {
		return fetchBff<SavedMapSummary[]>("/api/maps", { method: "GET" });
	},

	async getSavedMap(id: number): Promise<SavedMap> {
		return fetchBff<SavedMap>(`/api/maps/${id}`, { method: "GET" });
	},

	async createSavedMap(request: SavedMapCreateRequest): Promise<SavedMap> {
		return fetchBff<SavedMap>("/api/maps", {
			method: "POST",
			body: JSON.stringify(request),
		});
	},

	async updateSavedMap(
		id: number,
		request: SavedMapUpdateRequest,
	): Promise<SavedMap> {
		return fetchBff<SavedMap>(`/api/maps/${id}`, {
			method: "PATCH",
			body: JSON.stringify(request),
		});
	},

	async deleteSavedMap(id: number): Promise<{ deleted: number }> {
		return fetchBff<{ deleted: number }>(`/api/maps/${id}`, {
			method: "DELETE",
		});
	},
};

// React Query keys
export const queryKeys = {
	games: (params?: GamesListParams) =>
		["games", params ?? {}] as const,
	gameDetail: (gameId: string) => ["game", gameId, "detail"] as const,
	gameState: (gameId: string, perspective?: string | null) =>
		["game", gameId, "state", perspective ?? "god"] as const,
	turnList: (gameId: string) =>
		["game", gameId, "turns"] as const,
	turnDetail: (gameId: string, turnNumber: number) =>
		["game", gameId, "turn", turnNumber, "detail"] as const,
	turnState: (gameId: string, turnNumber: number, perspective?: string | null) =>
		["game", gameId, "turn", turnNumber, "state", perspective ?? "god"] as const,
	turnPrompts: (gameId: string, turnNumber: number) =>
		["game", gameId, "turn", turnNumber, "prompts"] as const,
	diplomacy: (gameId: string) => ["game", gameId, "diplomacy"] as const,
	techTree: (gameId: string) => ["game", gameId, "techTree"] as const,
	rulesReference: () => ["rulesReference"] as const,
	savedMaps: () => ["savedMaps"] as const,
	savedMap: (id: number) => ["savedMap", id] as const,
};

// Utility functions
export function getPlayerColor(playerIndex: number): string {
	return `hsl(${(playerIndex * 137.5) % 360}, 70%, 60%)`;
}

export function formatDuration(seconds: number): string {
	const minutes = Math.floor(seconds / 60);
	const remainingSeconds = seconds % 60;
	return `${minutes}:${remainingSeconds.toString().padStart(2, "0")}`;
}

export function formatTokenCount(count: number): string {
	if (count < 1000) return count.toString();
	if (count < 1000000) return `${(count / 1000).toFixed(1)}K`;
	return `${(count / 1000000).toFixed(1)}M`;
}

export function calculateDistance(
	from: { x: number; y: number },
	to: { x: number; y: number },
): number {
	return Math.abs(from.x - to.x) + Math.abs(from.y - to.y);
}

export function isValidCoordinate(
	coord: { x: number; y: number },
	mapWidth: number,
	mapHeight: number,
): boolean {
	return (
		coord.x >= 0 && coord.x < mapWidth && coord.y >= 0 && coord.y < mapHeight
	);
}
