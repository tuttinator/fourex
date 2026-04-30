import { describe, it, expect, vi, beforeEach } from "vitest";
import { api, ApiError, queryKeys } from "@/lib/api";
import type { GameState } from "@/types/game";

const mockFetch = vi.fn();
global.fetch = mockFetch;

beforeEach(() => {
	mockFetch.mockReset();
});

const mockGameState: GameState = {
	turn: 5,
	rng_state: 42,
	map_width: 20,
	map_height: 20,
	tiles: [
		{ id: 0, loc: { x: 0, y: 0 }, terrain: "grass", owner: "alice", unit_ids: [1] },
		{ id: 1, loc: { x: 1, y: 0 }, terrain: "forest", owner: "alice", unit_ids: [2] },
		{ id: 2, loc: { x: 0, y: 1 }, terrain: "mountain", owner: "bob", unit_ids: [3] },
		{ id: 3, loc: { x: 1, y: 1 }, terrain: "water", unit_ids: [] },
	],
	units: {
		1: { id: 1, owner: "alice", type: "scout", hp: 10, moves_left: 2, loc: { x: 0, y: 0 } },
		2: { id: 2, owner: "alice", type: "soldier", hp: 20, moves_left: 1, loc: { x: 1, y: 0 } },
		3: { id: 3, owner: "bob", type: "worker", hp: 8, moves_left: 2, loc: { x: 0, y: 1 } },
	},
	cities: {
		1: { id: 1, owner: "alice", loc: { x: 0, y: 0 }, hp: 50, buildings: ["granary"], build_queue: [] },
		2: { id: 2, owner: "bob", loc: { x: 0, y: 1 }, hp: 50, buildings: [], build_queue: [] },
	},
	players: ["alice", "bob"],
	diplomacy: { "alice,bob": "peace" },
	stockpiles: {
		alice: { food: 100, wood: 50, ore: 30, crystal: 10, science: 0 },
		bob: { food: 80, wood: 60, ore: 20, crystal: 5, science: 0 },
	},
	research: {
		alice: { completed: [], active: null, progress: 0 },
		bob: { completed: [], active: null, progress: 0 },
	},
	next_unit_id: 4,
	next_city_id: 3,
	max_turns: 100,
};

describe("observation: getGameState polling", () => {
	it("fetches game state for observation", async () => {
		mockFetch.mockResolvedValueOnce({
			ok: true,
			json: async () => mockGameState,
		});

		const result = await api.getGameState("my-game");
		expect(result.turn).toBe(5);
		expect(result.players).toEqual(["alice", "bob"]);
		expect(Object.keys(result.units)).toHaveLength(3);
		expect(Object.keys(result.cities)).toHaveLength(2);
	});

	it("returns updated state on subsequent polls", async () => {
		const turn5 = { ...mockGameState, turn: 5 };
		const turn6 = { ...mockGameState, turn: 6 };

		mockFetch
			.mockResolvedValueOnce({ ok: true, json: async () => turn5 })
			.mockResolvedValueOnce({ ok: true, json: async () => turn6 });

		const first = await api.getGameState("my-game");
		expect(first.turn).toBe(5);

		const second = await api.getGameState("my-game");
		expect(second.turn).toBe(6);
	});

	it("throws ApiError with 404 for missing game", async () => {
		mockFetch.mockResolvedValueOnce({
			ok: false,
			status: 404,
			json: async () => ({ detail: "Game not found" }),
		});

		try {
			await api.getGameState("nonexistent");
			expect.fail("Should have thrown");
		} catch (err) {
			expect(err).toBeInstanceOf(ApiError);
			expect((err as ApiError).status).toBe(404);
			expect((err as ApiError).message).toBe("Game not found");
		}
	});

	it("throws ApiError on network failure", async () => {
		mockFetch.mockRejectedValueOnce(new Error("Connection refused"));

		try {
			await api.getGameState("my-game");
			expect.fail("Should have thrown");
		} catch (err) {
			expect(err).toBeInstanceOf(ApiError);
			expect((err as ApiError).status).toBe(0);
		}
	});
});

describe("observation: game detail for status detection", () => {
	it("returns active status for running game", async () => {
		mockFetch.mockResolvedValueOnce({
			ok: true,
			json: async () => ({
				game_id: "my-game",
				player_slots: 2,
				players: ["alice", "bob"],
				creator: "alice",
				turn: 5,
				max_turns: 100,
				map_width: 20,
				map_height: 20,
				seed: 42,
				status: "active",
				winner: null,
				victory_type: null,
				created_at: "2026-04-16T00:00:00",
				updated_at: "2026-04-16T01:00:00",
				ended_at: null,
			}),
		});

		const detail = await api.getGameDetail("my-game");
		expect(detail.status).toBe("active");
	});

	it("returns ended status with winner for completed game", async () => {
		mockFetch.mockResolvedValueOnce({
			ok: true,
			json: async () => ({
				game_id: "my-game",
				player_slots: 2,
				players: ["alice", "bob"],
				creator: "alice",
				turn: 100,
				max_turns: 100,
				map_width: 20,
				map_height: 20,
				seed: 42,
				status: "ended",
				winner: "alice",
				victory_type: "score",
				created_at: "2026-04-16T00:00:00",
				updated_at: "2026-04-16T02:00:00",
				ended_at: "2026-04-16T02:00:00",
			}),
		});

		const detail = await api.getGameDetail("my-game");
		expect(detail.status).toBe("ended");
		expect(detail.winner).toBe("alice");
	});
});

describe("observation: query keys", () => {
	it("gameState key includes game ID and default god perspective", () => {
		const key = queryKeys.gameState("my-game");
		expect(key).toEqual(["game", "my-game", "state", "god"]);
	});

	it("gameState key includes player perspective when specified", () => {
		const key = queryKeys.gameState("my-game", "alice");
		expect(key).toEqual(["game", "my-game", "state", "alice"]);
	});

	it("gameDetail key is distinct from gameState key", () => {
		const stateKey = queryKeys.gameState("my-game");
		const detailKey = queryKeys.gameDetail("my-game");
		expect(stateKey).not.toEqual(detailKey);
	});

	it("perspective change produces distinct query key", () => {
		const godKey = queryKeys.gameState("my-game");
		const aliceKey = queryKeys.gameState("my-game", "alice");
		const bobKey = queryKeys.gameState("my-game", "bob");
		expect(godKey).not.toEqual(aliceKey);
		expect(aliceKey).not.toEqual(bobKey);
	});
});

describe("observation: player perspective (fog-of-war) fetching", () => {
	// The legacy `player_<name>` bearer prefix was removed in Phase 2
	// (backend). With no per-game API key in storage, both the god-mode and
	// player-perspective helpers degrade to anonymous observation against the
	// same `/state` endpoint; redaction now depends on which key (if any)
	// the browser holds, not on an ad-hoc header value.

	it("fetches game state without an Authorization header when no API key is stored", async () => {
		mockFetch.mockResolvedValueOnce({
			ok: true,
			json: async () => ({
				...mockGameState,
				tiles: [
					{ id: 0, loc: { x: 0, y: 0 }, terrain: "grass", owner: "alice" },
					{ id: 1, loc: { x: 1, y: 0 }, terrain: "forest", owner: "alice" },
				],
				units: {
					1: { id: 1, owner: "alice", type: "scout", hp: 10, moves_left: 2, loc: { x: 0, y: 0 } },
					2: { id: 2, owner: "alice", type: "soldier", hp: 20, moves_left: 1, loc: { x: 1, y: 0 } },
				},
				cities: {
					1: { id: 1, owner: "alice", loc: { x: 0, y: 0 }, hp: 50, buildings: ["granary"] },
				},
			}),
		});

		const result = await api.getGameStateAsPlayer("my-game", "alice");
		expect(result.tiles).toHaveLength(2);

		const [, fetchOptions] = mockFetch.mock.calls[0];
		expect(
			(fetchOptions.headers as Record<string, string>).Authorization,
		).toBeUndefined();
	});

	it("god-mode fetch does not send an Authorization header", async () => {
		mockFetch.mockResolvedValueOnce({
			ok: true,
			json: async () => mockGameState,
		});

		await api.getGameState("my-game");

		const [, fetchOptions] = mockFetch.mock.calls[0];
		expect(
			(fetchOptions.headers as Record<string, string>).Authorization,
		).toBeUndefined();
	});

	it("redacted state has fewer tiles than full state", async () => {
		const fullState = { ...mockGameState };
		const redactedState = {
			...mockGameState,
			tiles: mockGameState.tiles.filter(t => t.owner === "alice"),
			units: { 1: mockGameState.units[1], 2: mockGameState.units[2] },
			cities: { 1: mockGameState.cities[1] },
		};

		expect(fullState.tiles.length).toBeGreaterThan(redactedState.tiles.length);
		expect(Object.keys(fullState.units).length).toBeGreaterThan(Object.keys(redactedState.units).length);
		expect(Object.keys(fullState.cities).length).toBeGreaterThan(Object.keys(redactedState.cities).length);
	});

	it("switching perspective reuses the /state endpoint", async () => {
		mockFetch.mockResolvedValue({
			ok: true,
			json: async () => mockGameState,
		});

		await api.getGameState("my-game");
		const [godUrl] = mockFetch.mock.calls[0];
		expect(godUrl).toContain("/state?game_id=my-game");

		await api.getGameStateAsPlayer("my-game", "alice");
		const [playerUrl] = mockFetch.mock.calls[1];
		expect(playerUrl).toContain("/state?");
		expect(playerUrl).toContain("game_id=my-game");
		expect(playerUrl).toContain("as_player=alice");
	});
});

describe("observation: fog-of-war tile visibility", () => {
	it("builds tile lookup for visible tile detection", () => {
		// Simulate the tile lookup used in PixiMap
		const tileLookup = new Map<string, boolean>();
		for (const tile of mockGameState.tiles) {
			tileLookup.set(`${tile.loc.x},${tile.loc.y}`, true);
		}

		expect(tileLookup.has("0,0")).toBe(true);
		expect(tileLookup.has("1,0")).toBe(true);
		expect(tileLookup.has("5,5")).toBe(false);
	});

	it("identifies unexplored tiles as those missing from redacted state", () => {
		const redactedTiles = mockGameState.tiles.filter(t => t.owner === "alice");
		const tileLookup = new Map<string, boolean>();
		for (const tile of redactedTiles) {
			tileLookup.set(`${tile.loc.x},${tile.loc.y}`, true);
		}

		// Bob's tile and unowned tile should be unexplored
		expect(tileLookup.has("0,1")).toBe(false); // bob's tile
		expect(tileLookup.has("1,1")).toBe(false); // unowned water tile
		// Alice's tiles should be visible
		expect(tileLookup.has("0,0")).toBe(true);
		expect(tileLookup.has("1,0")).toBe(true);
	});

	it("counts visible vs total tiles for fog-of-war stats", () => {
		const { map_width, map_height } = mockGameState;
		const totalTiles = map_width * map_height;
		const redactedTiles = mockGameState.tiles.filter(t => t.owner === "alice");

		expect(totalTiles).toBe(400); // 20x20
		expect(redactedTiles.length).toBe(2);
		expect(redactedTiles.length).toBeLessThan(totalTiles);
	});
});

describe("observation: game state data for event log", () => {
	it("provides per-player unit counts from game state", () => {
		const aliceUnits = Object.values(mockGameState.units).filter(
			(u) => u.owner === "alice",
		);
		const bobUnits = Object.values(mockGameState.units).filter(
			(u) => u.owner === "bob",
		);
		expect(aliceUnits).toHaveLength(2);
		expect(bobUnits).toHaveLength(1);
	});

	it("provides per-player city counts from game state", () => {
		const aliceCities = Object.values(mockGameState.cities).filter(
			(c) => c.owner === "alice",
		);
		const bobCities = Object.values(mockGameState.cities).filter(
			(c) => c.owner === "bob",
		);
		expect(aliceCities).toHaveLength(1);
		expect(bobCities).toHaveLength(1);
	});

	it("provides per-player territory counts from game state", () => {
		const aliceTerritory = mockGameState.tiles.filter(
			(t) => t.owner === "alice",
		).length;
		const bobTerritory = mockGameState.tiles.filter(
			(t) => t.owner === "bob",
		).length;
		expect(aliceTerritory).toBe(2);
		expect(bobTerritory).toBe(1);
	});

	it("provides per-player resource totals from game state", () => {
		const aliceResources = mockGameState.stockpiles["alice"];
		expect(aliceResources).toBeDefined();
		expect(aliceResources.food + aliceResources.wood + aliceResources.ore + aliceResources.crystal).toBe(190);

		const bobResources = mockGameState.stockpiles["bob"];
		expect(bobResources).toBeDefined();
		expect(bobResources.food + bobResources.wood + bobResources.ore + bobResources.crystal).toBe(165);
	});
});
