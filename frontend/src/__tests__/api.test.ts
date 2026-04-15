import { describe, it, expect, vi, beforeEach } from "vitest";
import { api, ApiError, queryKeys } from "@/lib/api";

const mockFetch = vi.fn();
global.fetch = mockFetch;

beforeEach(() => {
	mockFetch.mockReset();
});

describe("api.listGames", () => {
	it("returns game IDs from the API", async () => {
		mockFetch.mockResolvedValueOnce({
			ok: true,
			json: async () => ({ games: ["game-1", "game-2"] }),
		});

		const result = await api.listGames();
		expect(result).toEqual(["game-1", "game-2"]);
		expect(mockFetch).toHaveBeenCalledWith(
			expect.stringContaining("/games"),
			expect.any(Object),
		);
	});

	it("throws ApiError on non-ok response", async () => {
		mockFetch.mockResolvedValueOnce({
			ok: false,
			status: 500,
			json: async () => ({ detail: "Internal server error" }),
		});

		await expect(api.listGames()).rejects.toThrow(ApiError);
		await expect(api.listGames()).rejects.toThrow();
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
	it("generates stable keys", () => {
		expect(queryKeys.games).toEqual(["games"]);
		expect(queryKeys.gameState("abc")).toEqual(["game", "abc"]);
	});
});
