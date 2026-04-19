import { describe, it, expect, vi, beforeEach } from "vitest";
import { api, ApiError, queryKeys } from "@/lib/api";

const mockFetch = vi.fn();
global.fetch = mockFetch;

beforeEach(() => {
	mockFetch.mockReset();
});

describe("api.listGames", () => {
	const mockGamesResponse = {
		games: [
			{
				game_id: "game-1",
				player_slots: 2,
				players: ["p1", "p2"],
				turn: 5,
				max_turns: 100,
				status: "active",
				winner: null,
				victory_type: null,
				created_at: "2026-04-15T00:00:00",
				updated_at: "2026-04-15T01:00:00",
				ended_at: null,
			},
			{
				game_id: "game-2",
				player_slots: 3,
				players: ["p1", "p2", "p3"],
				turn: 100,
				max_turns: 100,
				status: "ended",
				winner: "p1",
				victory_type: "score",
				created_at: "2026-04-14T00:00:00",
				updated_at: "2026-04-14T10:00:00",
				ended_at: "2026-04-14T10:00:00",
			},
		],
		total: 2,
		offset: 0,
		limit: 20,
	};

	it("returns games list with metadata from the API", async () => {
		mockFetch.mockResolvedValueOnce({
			ok: true,
			json: async () => mockGamesResponse,
		});

		const result = await api.listGames();
		expect(result.games).toHaveLength(2);
		expect(result.games[0].game_id).toBe("game-1");
		expect(result.games[0].status).toBe("active");
		expect(result.total).toBe(2);
		expect(mockFetch).toHaveBeenCalledWith(
			expect.stringContaining("/games"),
			expect.any(Object),
		);
	});

	it("sends query params for filtering", async () => {
		mockFetch.mockResolvedValueOnce({
			ok: true,
			json: async () => ({ ...mockGamesResponse, games: [mockGamesResponse.games[0]], total: 1 }),
		});

		await api.listGames({ status: "active" });
		const calledUrl = mockFetch.mock.calls[0][0] as string;
		expect(calledUrl).toContain("status=active");
	});

	it("sends query params for sorting", async () => {
		mockFetch.mockResolvedValueOnce({
			ok: true,
			json: async () => mockGamesResponse,
		});

		await api.listGames({ sort_by: "turn", sort_order: "asc" });
		const calledUrl = mockFetch.mock.calls[0][0] as string;
		expect(calledUrl).toContain("sort_by=turn");
		expect(calledUrl).toContain("sort_order=asc");
	});

	it("sends query params for pagination", async () => {
		mockFetch.mockResolvedValueOnce({
			ok: true,
			json: async () => mockGamesResponse,
		});

		await api.listGames({ offset: 20, limit: 10 });
		const calledUrl = mockFetch.mock.calls[0][0] as string;
		expect(calledUrl).toContain("offset=20");
		expect(calledUrl).toContain("limit=10");
	});

	it("throws ApiError on non-ok response", async () => {
		mockFetch.mockResolvedValueOnce({
			ok: false,
			status: 500,
			json: async () => ({ detail: "Internal server error" }),
		});

		await expect(api.listGames()).rejects.toThrow(ApiError);
	});

	it("throws ApiError on network failure", async () => {
		mockFetch.mockRejectedValueOnce(new Error("Network error"));

		await expect(api.listGames()).rejects.toThrow(ApiError);
	});
});

describe("api.getGameState", () => {
	it("fetches game state by ID", async () => {
		const mockState = {
			turn: 5,
			map_width: 20,
			map_height: 20,
			players: ["player_1", "player_2"],
			tiles: [],
			units: {},
			cities: {},
			diplomacy: {},
			stockpiles: {},
		};

		mockFetch.mockResolvedValueOnce({
			ok: true,
			json: async () => mockState,
		});

		const result = await api.getGameState("test-game");
		expect(result).toEqual(mockState);
		expect(mockFetch).toHaveBeenCalledWith(
			expect.stringContaining("/state?game_id=test-game"),
			expect.any(Object),
		);
	});

	it("returns 404 for missing game", async () => {
		mockFetch.mockResolvedValueOnce({
			ok: false,
			status: 404,
			json: async () => ({ detail: "Game not found" }),
		});

		await expect(api.getGameState("missing")).rejects.toThrow("Game not found");
	});
});

describe("api.createGame", () => {
	it("sends POST with players and seed", async () => {
		const mockResponse = { turn: 0, players: ["a", "b"] };
		mockFetch.mockResolvedValueOnce({
			ok: true,
			json: async () => mockResponse,
		});

		const result = await api.createGame("new-game", {
			players: ["a", "b"],
			seed: 42,
		});

		expect(result).toEqual(mockResponse);
		expect(mockFetch).toHaveBeenCalledWith(
			expect.stringContaining("/games/new-game/start"),
			expect.objectContaining({
				method: "POST",
				body: JSON.stringify({ players: ["a", "b"], seed: 42 }),
			}),
		);
	});
});

describe("api.createLobby", () => {
	const mockLobbyResponse = {
		game: {
			game_id: "lobby-1",
			player_slots: 4,
			players: ["alice"],
			creator: "alice",
			turn: 0,
			max_turns: 100,
			map_width: 20,
			map_height: 20,
			seed: 42,
			status: "waiting",
			winner: null,
			victory_type: null,
			created_at: "2026-04-16T00:00:00",
			updated_at: "2026-04-16T00:00:00",
			ended_at: null,
		},
		api_key: "fx_testkey",
	};

	it("POSTs to the Next.js BFF so the Auth.js JWT can be forwarded", async () => {
		mockFetch.mockResolvedValueOnce({
			ok: true,
			json: async () => mockLobbyResponse,
		});

		const result = await api.createLobby("lobby-1", {
			player_id: "alice",
			player_slots: 4,
			seed: 42,
		});

		expect(result.game.game_id).toBe("lobby-1");
		expect(result.api_key).toBe("fx_testkey");
		const calledUrl = mockFetch.mock.calls[0][0] as string;
		// Must hit the BFF route, not FastAPI directly — the client can't
		// read the HttpOnly JWT cookie to attach it itself.
		expect(calledUrl).toBe("/api/lobbies?game_id=lobby-1");
		expect(mockFetch.mock.calls[0][1]).toMatchObject({ method: "POST" });
		const body = JSON.parse(
			(mockFetch.mock.calls[0][1] as RequestInit).body as string,
		);
		expect(body.player_id).toBe("alice");
		expect(body.player_slots).toBe(4);
	});
});

describe("api.getGameDetail", () => {
	it("fetches game detail by ID", async () => {
		const mockDetail = {
			game_id: "test-game",
			player_slots: 2,
			players: ["p1"],
			creator: "p1",
			turn: 0,
			max_turns: 100,
			map_width: 20,
			map_height: 20,
			seed: 42,
			status: "waiting",
			winner: null,
			victory_type: null,
			created_at: "2026-04-16T00:00:00",
			updated_at: "2026-04-16T00:00:00",
			ended_at: null,
		};

		mockFetch.mockResolvedValueOnce({
			ok: true,
			json: async () => mockDetail,
		});

		const result = await api.getGameDetail("test-game");
		expect(result.game_id).toBe("test-game");
		expect(result.player_slots).toBe(2);
		const calledUrl = mockFetch.mock.calls[0][0] as string;
		expect(calledUrl).toContain("/games/test-game");
	});

	it("returns 404 for missing game", async () => {
		mockFetch.mockResolvedValueOnce({
			ok: false,
			status: 404,
			json: async () => ({ detail: "Game not found" }),
		});

		await expect(api.getGameDetail("missing")).rejects.toThrow("Game not found");
	});
});

describe("api.joinLobby", () => {
	const mockLobbyResponse = {
		game: {
			game_id: "g1",
			player_slots: 2,
			players: ["alice", "bob"],
			creator: "alice",
			turn: 0,
			max_turns: 100,
			map_width: 20,
			map_height: 20,
			seed: 42,
			status: "waiting",
			winner: null,
			victory_type: null,
			created_at: "2026-04-16T00:00:00",
			updated_at: "2026-04-16T00:00:00",
			ended_at: null,
		},
		api_key: "fx_bobkey",
	};

	it("POSTs to the Next.js BFF join route", async () => {
		mockFetch.mockResolvedValueOnce({
			ok: true,
			json: async () => mockLobbyResponse,
		});

		const result = await api.joinLobby("g1", { player_id: "bob" });
		expect(result.game.players).toContain("bob");
		expect(result.api_key).toBe("fx_bobkey");
		const calledUrl = mockFetch.mock.calls[0][0] as string;
		expect(calledUrl).toBe("/api/lobbies/g1/join");
		expect(mockFetch.mock.calls[0][1]).toMatchObject({ method: "POST" });
		const body = JSON.parse(
			(mockFetch.mock.calls[0][1] as RequestInit).body as string,
		);
		expect(body.player_id).toBe("bob");
	});

	it("throws on full game", async () => {
		mockFetch.mockResolvedValueOnce({
			ok: false,
			status: 400,
			json: async () => ({ detail: "Game g1 is full (2 slots)" }),
		});

		await expect(
			api.joinLobby("g1", { player_id: "charlie" }),
		).rejects.toThrow("full");
	});
});

describe("api.leaveGame", () => {
	it("sends POST to leave endpoint", async () => {
		mockFetch.mockResolvedValueOnce({
			ok: true,
			json: async () => ({ game_id: "g1", players: [], status: "waiting" }),
		});

		await api.leaveGame("g1");
		const calledUrl = mockFetch.mock.calls[0][0] as string;
		expect(calledUrl).toContain("/games/g1/leave");
		expect(mockFetch.mock.calls[0][1]).toMatchObject({ method: "POST" });
	});
});

describe("api.startGame", () => {
	it("sends POST to start endpoint", async () => {
		mockFetch.mockResolvedValueOnce({
			ok: true,
			json: async () => ({ status: "game_started", game_id: "g1" }),
		});

		const result = await api.startGame("g1");
		expect(result.status).toBe("game_started");
		const calledUrl = mockFetch.mock.calls[0][0] as string;
		expect(calledUrl).toContain("/games/g1/start");
		expect(mockFetch.mock.calls[0][1]).toMatchObject({ method: "POST" });
	});
});

describe("queryKeys", () => {
	it("generates stable keys for games list", () => {
		expect(queryKeys.games()).toEqual(["games", {}]);
		expect(queryKeys.games({ status: "active" })).toEqual([
			"games",
			{ status: "active" },
		]);
	});

	it("generates stable keys for game detail", () => {
		expect(queryKeys.gameDetail("abc")).toEqual(["game", "abc", "detail"]);
	});

	it("generates stable keys for game state in god mode", () => {
		expect(queryKeys.gameState("abc")).toEqual(["game", "abc", "state", "god"]);
	});

	it("generates stable keys for game state with player perspective", () => {
		expect(queryKeys.gameState("abc", "alice")).toEqual(["game", "abc", "state", "alice"]);
	});

	it("generates distinct keys for different perspectives", () => {
		const godKey = queryKeys.gameState("abc");
		const aliceKey = queryKeys.gameState("abc", "alice");
		const bobKey = queryKeys.gameState("abc", "bob");
		expect(godKey).not.toEqual(aliceKey);
		expect(aliceKey).not.toEqual(bobKey);
	});
});
