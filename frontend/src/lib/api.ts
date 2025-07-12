import type {
	ApiResponse,
	CreateGameRequest,
	GameInfo,
	GameListItem,
	GameListResponse,
	GameState,
	PlayerStats,
	PromptLog,
	SystemMetrics,
} from "@/types/game";

const API_BASE_URL =
	process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

class ApiError extends Error {
	constructor(
		public status: number,
		message: string,
	) {
		super(message);
		this.name = "ApiError";
	}
}

async function fetchApi<T>(
	endpoint: string,
	options: RequestInit = {},
): Promise<T> {
	const url = `${API_BASE_URL}${endpoint}`;

	const defaultHeaders = {
		"Content-Type": "application/json",
	};

	// Add auth token if available
	const token =
		typeof window !== "undefined" ? localStorage.getItem("auth_token") : null;

	if (token) {
		defaultHeaders["Authorization"] = `Bearer ${token}`;
	}

	const config: RequestInit = {
		...options,
		headers: {
			...defaultHeaders,
			...options.headers,
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

export const api = {
	// Game management
	async listGames(): Promise<string[]> {
		const response = await fetchApi<GameListResponse>("/games");
		return response.games;
	},

	async getGames(): Promise<GameListItem[]> {
		return fetchApi("/admin/games");
	},

	async createGame(
		gameId: string,
		request: CreateGameRequest,
	): Promise<ApiResponse<any>> {
		return fetchApi(`/games/${gameId}/start`, {
			method: "POST",
			body: JSON.stringify(request),
		});
	},

	async getGameState(gameId: string): Promise<GameState> {
		return fetchApi(`/state?game_id=${gameId}`);
	},

	// Snapshots and history
	async getSnapshot(gameId: string, turn: number): Promise<GameState> {
		return fetchApi(`/snapshots/${gameId}/turn-${turn}`);
	},

	async getPrompts(gameId: string, turn: number): Promise<PromptLog[]> {
		return fetchApi(`/logs/${gameId}/turn-${turn}/prompts`);
	},

	// Admin functions
	async getSystemMetrics(): Promise<SystemMetrics> {
		return fetchApi("/admin/metrics");
	},

	async getPlayerStats(): Promise<PlayerStats[]> {
		return fetchApi("/admin/players");
	},

	async gameAction(
		gameId: string,
		action: "pause" | "resume" | "stop",
	): Promise<ApiResponse<any>> {
		return fetchApi(`/admin/games/${gameId}/${action}`, {
			method: "POST",
		});
	},

	async playerAction(
		gameId: string,
		playerId: string,
		action: "kick" | "pause" | "resume",
	): Promise<ApiResponse<any>> {
		return fetchApi(`/admin/games/${gameId}/players/${playerId}/${action}`, {
			method: "POST",
		});
	},

	async fastForward(gameId: string, turns: number): Promise<ApiResponse<any>> {
		return fetchApi(`/admin/games/${gameId}/ffwd`, {
			method: "POST",
			body: JSON.stringify({ turns }),
		});
	},

	async kickPlayer(
		gameId: string,
		playerId: string,
	): Promise<ApiResponse<any>> {
		return fetchApi(`/admin/games/${gameId}/kick`, {
			method: "POST",
			body: JSON.stringify({ player_id: playerId }),
		});
	},

	async pauseGame(gameId: string): Promise<ApiResponse<any>> {
		return fetchApi(`/admin/games/${gameId}/pause`, {
			method: "POST",
		});
	},

	async resumeGame(gameId: string): Promise<ApiResponse<any>> {
		return fetchApi(`/admin/games/${gameId}/resume`, {
			method: "POST",
		});
	},
};

// WebSocket connection utility
export class GameWebSocket {
	private ws: WebSocket | null = null;
	private gameId: string;
	private callbacks: Map<string, Function[]> = new Map();
	private reconnectAttempts = 0;
	private maxReconnectAttempts = 5;

	constructor(gameId: string) {
		this.gameId = gameId;
	}

	connect(): Promise<void> {
		return new Promise((resolve, reject) => {
			const wsUrl = `${API_BASE_URL.replace("http", "ws")}/events?game_id=${this.gameId}`;
			console.log("Attempting WebSocket connection to:", wsUrl);

			try {
				this.ws = new WebSocket(wsUrl);

				this.ws.onopen = () => {
					console.log("WebSocket connected successfully");
					this.reconnectAttempts = 0;
					this.emit("connection", "open");
					resolve();
				};

				this.ws.onmessage = (event) => {
					console.log("WebSocket message received:", event.data);
					try {
						const data = JSON.parse(event.data);
						this.emit(data.type, data);
						this.emit("message", data);
					} catch (error) {
						console.error("Failed to parse WebSocket message:", error);
					}
				};

				this.ws.onclose = () => {
					console.log("WebSocket connection closed");
					this.emit("connection", "closed");
					this.attemptReconnect();
				};

				this.ws.onerror = (error) => {
					console.error("WebSocket error:", error);
					this.emit("connection", "error");
					reject(new Error("WebSocket connection failed"));
				};
			} catch (error) {
				reject(error);
			}
		});
	}

	private attemptReconnect() {
		if (this.reconnectAttempts < this.maxReconnectAttempts) {
			this.reconnectAttempts++;
			const delay = Math.min(1000 * 2 ** this.reconnectAttempts, 10000);

			setTimeout(() => {
				this.connect().catch(console.error);
			}, delay);
		}
	}

	on(event: string, callback: Function) {
		if (!this.callbacks.has(event)) {
			this.callbacks.set(event, []);
		}
		this.callbacks.get(event)!.push(callback);
	}

	off(event: string, callback: Function) {
		const callbacks = this.callbacks.get(event);
		if (callbacks) {
			const index = callbacks.indexOf(callback);
			if (index > -1) {
				callbacks.splice(index, 1);
			}
		}
	}

	private emit(event: string, data: any) {
		const callbacks = this.callbacks.get(event);
		if (callbacks) {
			callbacks.forEach((callback) => callback(data));
		}
	}

	disconnect() {
		if (this.ws) {
			this.ws.close();
			this.ws = null;
		}
		this.callbacks.clear();
	}

	get readyState() {
		return this.ws?.readyState || WebSocket.CLOSED;
	}
}

// React Query keys
export const queryKeys = {
	games: ["games"] as const,
	gameState: (gameId: string) => ["game", gameId] as const,
	snapshot: (gameId: string, turn: number) =>
		["snapshot", gameId, turn] as const,
	prompts: (gameId: string, turn: number) => ["prompts", gameId, turn] as const,
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
