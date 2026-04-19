import { getGameApiKey } from "@/lib/game-auth";
import type {
	CreateGameRequest,
	CreateLobbyRequest,
	DiplomacyStateResponse,
	GameDetailResponse,
	GamesListParams,
	GamesListResponse,
	GameState,
	JoinLobbyRequest,
	LobbyKeyResponse,
	MessageListResponse,
	TreatyClause,
	TurnDetailResponse,
	TurnListResponse,
	TurnPromptsResponse,
} from "@/types/game";

const API_BASE_URL =
	process.env.NEXT_PUBLIC_API_URL || "http://localhost:8010/api/v1";

export class ApiError extends Error {
	constructor(
		public status: number,
		message: string,
	) {
		super(message);
		this.name = "ApiError";
	}
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
				errorData.detail || errorData.message || "Request failed",
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
			errorData.detail || errorData.message || "Request failed",
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

		const qs = searchParams.toString();
		return fetchApi<GamesListResponse>(`/games${qs ? `?${qs}` : ""}`);
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
		return fetchApi(`/games/${encodeURIComponent(gameId)}`);
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

	async getGameState(gameId: string): Promise<GameState> {
		return fetchApi(`/state?game_id=${gameId}`, { gameId });
	},

	async getGameStateAsPlayer(
		gameId: string,
		// eslint-disable-next-line @typescript-eslint/no-unused-vars
		_playerId: string,
	): Promise<GameState> {
		// The legacy `player_<name>` bearer prefix has been retired. Observation
		// perspective switching now only applies fog-of-war redaction if the
		// caller holds the relevant per-game API key (i.e. they are that player).
		// Otherwise the request falls through to god-mode observation.
		return fetchApi(`/state?game_id=${gameId}`, { gameId });
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
