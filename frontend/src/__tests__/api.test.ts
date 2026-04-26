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

	it("formats pydantic validation arrays into a readable message", async () => {
		mockFetch.mockResolvedValueOnce({
			ok: false,
			status: 422,
			json: async () => ({
				detail: [
					{
						type: "less_than_equal",
						loc: ["body", "map_width"],
						msg: "Input should be less than or equal to 100",
					},
					{
						type: "less_than_equal",
						loc: ["body", "map_height"],
						msg: "Input should be less than or equal to 100",
					},
				],
			}),
		});

		await expect(api.listGames()).rejects.toThrow(
			"map_width: Input should be less than or equal to 100; " +
				"map_height: Input should be less than or equal to 100",
		);
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

describe("api.getValidMoves", () => {
	it("GETs the per-unit valid-moves endpoint with game-scoped bearer", async () => {
		localStorage.clear();
		localStorage.setItem("parley.gamekey.g1", "fx_aliceKey");
		mockFetch.mockResolvedValueOnce({
			ok: true,
			json: async () => ({
				game_id: "g1",
				unit_id: 7,
				moves_left: 2,
				moves: [
					{ x: 1, y: 0, terrain: "plains", distance: 1 },
					{ x: 0, y: 1, terrain: "forest", distance: 1 },
				],
			}),
		});

		const result = await api.getValidMoves("g1", 7);
		expect(result.moves).toHaveLength(2);
		expect(result.moves[0]).toMatchObject({ x: 1, y: 0 });

		const [calledUrl, init] = mockFetch.mock.calls[0] as [string, RequestInit];
		expect(calledUrl).toContain("/games/g1/units/7/valid-moves");
		expect(
			(init.headers as Record<string, string>).Authorization,
		).toBe("Bearer fx_aliceKey");
	});
});

describe("api.getQueueableTiles", () => {
	it("GETs the per-unit queueable-tiles endpoint with game-scoped bearer", async () => {
		localStorage.clear();
		localStorage.setItem("parley.gamekey.g1", "fx_aliceKey");
		mockFetch.mockResolvedValueOnce({
			ok: true,
			json: async () => ({
				game_id: "g1",
				unit_id: 7,
				tiles: [
					{
						x: 5,
						y: 3,
						terrain: "plains",
						cost: 5,
						distance: 5,
						path: [{ x: 1, y: 0 }],
						turns_required: 2,
					},
				],
			}),
		});

		const result = await api.getQueueableTiles("g1", 7);
		expect(result.tiles).toHaveLength(1);
		expect(result.tiles[0].turns_required).toBe(2);

		const [calledUrl] = mockFetch.mock.calls[0] as [string, RequestInit];
		expect(calledUrl).toContain("/games/g1/units/7/queueable-tiles");
	});
});

describe("api.submitActions", () => {
	it("POSTs the batch to /actions with game_id query and bearer", async () => {
		localStorage.clear();
		localStorage.setItem("parley.gamekey.g1", "fx_aliceKey");
		mockFetch.mockResolvedValueOnce({
			ok: true,
			json: async () => ({ status: "actions_submitted", count: "2" }),
		});

		const result = await api.submitActions("g1", [
			{ type: "MOVE", unit_id: 7, to: { x: 1, y: 0 } },
			{ type: "MOVE", unit_id: 8, to: { x: 2, y: 2 } },
		]);
		expect(result.count).toBe("2");

		const [calledUrl, init] = mockFetch.mock.calls[0] as [string, RequestInit];
		expect(calledUrl).toContain("/actions?game_id=g1");
		expect(init.method).toBe("POST");
		expect(
			(init.headers as Record<string, string>).Authorization,
		).toBe("Bearer fx_aliceKey");
		const body = JSON.parse(init.body as string);
		expect(body).toHaveLength(2);
		expect(body[0].type).toBe("MOVE");
	});

	it("surfaces server rejection (400) as ApiError", async () => {
		localStorage.clear();
		localStorage.setItem("parley.gamekey.g1", "fx_aliceKey");
		mockFetch.mockResolvedValueOnce({
			ok: false,
			status: 400,
			json: async () => ({ detail: "Unit 7 cannot reach (5,5)" }),
		});

		await expect(
			api.submitActions("g1", [
				{ type: "MOVE", unit_id: 7, to: { x: 5, y: 5 } },
			]),
		).rejects.toThrow("cannot reach");
	});
});

describe("api.getValidAttacks", () => {
	it("GETs the per-unit valid-attacks endpoint with game-scoped bearer", async () => {
		localStorage.clear();
		localStorage.setItem("parley.gamekey.g1", "fx_aliceKey");
		mockFetch.mockResolvedValueOnce({
			ok: true,
			json: async () => ({
				game_id: "g1",
				unit_id: 5,
				attack_range: 1,
				attack: 3,
				targets: [
					{
						target_type: "unit",
						target_id: 9,
						x: 1,
						y: 0,
						distance: 1,
						owner: "bob",
						hp: 10,
						diplomatic_state: "war",
					},
				],
			}),
		});

		const result = await api.getValidAttacks("g1", 5);
		expect(result.targets).toHaveLength(1);
		expect(result.targets[0].target_type).toBe("unit");

		const [calledUrl, init] = mockFetch.mock.calls[0] as [string, RequestInit];
		expect(calledUrl).toContain("/games/g1/units/5/valid-attacks");
		expect((init.headers as Record<string, string>).Authorization).toBe(
			"Bearer fx_aliceKey",
		);
	});
});

describe("api.getCanFoundCity", () => {
	it("GETs the can-found-city endpoint with game-scoped bearer", async () => {
		localStorage.clear();
		localStorage.setItem("parley.gamekey.g1", "fx_aliceKey");
		mockFetch.mockResolvedValueOnce({
			ok: true,
			json: async () => ({
				game_id: "g1",
				unit_id: 3,
				can_found: true,
				reason: null,
				cost: { food: 15 },
			}),
		});

		const result = await api.getCanFoundCity("g1", 3);
		expect(result.can_found).toBe(true);
		expect(result.cost.food).toBe(15);

		const [calledUrl] = mockFetch.mock.calls[0] as [string, RequestInit];
		expect(calledUrl).toContain("/games/g1/units/3/can-found-city");
	});
});

describe("api.getValidImprovements", () => {
	it("GETs the valid-improvements endpoint with game-scoped bearer", async () => {
		localStorage.clear();
		localStorage.setItem("parley.gamekey.g1", "fx_aliceKey");
		mockFetch.mockResolvedValueOnce({
			ok: true,
			json: async () => ({
				game_id: "g1",
				unit_id: 7,
				tile: { x: 2, y: 3 },
				improvements: [
					{
						improvement: "farm",
						cost: { food: 0, wood: 5, ore: 0, crystal: 0 },
						affordable: true,
						terrain: "plains",
						resource: "food",
					},
				],
			}),
		});

		const result = await api.getValidImprovements("g1", 7);
		expect(result.improvements).toHaveLength(1);
		expect(result.improvements[0].improvement).toBe("farm");

		const [calledUrl] = mockFetch.mock.calls[0] as [string, RequestInit];
		expect(calledUrl).toContain("/games/g1/units/7/valid-improvements");
	});
});

describe("api.getTrainableUnits", () => {
	it("GETs the trainable-units endpoint with game-scoped bearer", async () => {
		localStorage.clear();
		localStorage.setItem("parley.gamekey.g1", "fx_aliceKey");
		mockFetch.mockResolvedValueOnce({
			ok: true,
			json: async () => ({
				game_id: "g1",
				city_id: 2,
				units: [
					{
						unit_type: "scout",
						cost: { food: 10, wood: 5, ore: 0, crystal: 0 },
						affordable: true,
						stats: { hp: 8, moves: 3, sight: 3, attack: 1, attack_range: 1 },
					},
				],
			}),
		});

		const result = await api.getTrainableUnits("g1", 2);
		expect(result.units[0].unit_type).toBe("scout");

		const [calledUrl] = mockFetch.mock.calls[0] as [string, RequestInit];
		expect(calledUrl).toContain("/games/g1/cities/2/trainable-units");
	});
});

describe("api.getBuildableBuildings", () => {
	it("GETs the buildable-buildings endpoint with game-scoped bearer", async () => {
		localStorage.clear();
		localStorage.setItem("parley.gamekey.g1", "fx_aliceKey");
		mockFetch.mockResolvedValueOnce({
			ok: true,
			json: async () => ({
				game_id: "g1",
				city_id: 4,
				buildings: [
					{
						building_type: "granary",
						cost: { food: 0, wood: 20, ore: 0, crystal: 0 },
						affordable: true,
						already_built: false,
						effect: "+50% food output",
					},
				],
			}),
		});

		const result = await api.getBuildableBuildings("g1", 4);
		expect(result.buildings[0].building_type).toBe("granary");

		const [calledUrl] = mockFetch.mock.calls[0] as [string, RequestInit];
		expect(calledUrl).toContain("/games/g1/cities/4/buildable-buildings");
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
