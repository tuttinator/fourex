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

describe("queryKeys", () => {
	it("generates stable keys for games list", () => {
		expect(queryKeys.games()).toEqual(["games", {}]);
		expect(queryKeys.games({ status: "active" })).toEqual([
			"games",
			{ status: "active" },
		]);
	});

	it("generates stable keys for game state", () => {
		expect(queryKeys.gameState("abc")).toEqual(["game", "abc"]);
	});
});
