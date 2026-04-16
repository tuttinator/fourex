import { describe, it, expect, vi, beforeEach } from "vitest";
import { api, ApiError, queryKeys } from "@/lib/api";
import type { TurnListResponse, TurnDetailResponse, TurnPromptsResponse, GameState } from "@/types/game";

const mockFetch = vi.fn();
global.fetch = mockFetch;

beforeEach(() => {
	mockFetch.mockReset();
});

const mockTurnList: TurnListResponse = {
	turns: [
		{ turn_number: 1, state_hash: "abc123", player_count: 2, completed_at: "2026-04-16T00:01:00" },
		{ turn_number: 2, state_hash: "def456", player_count: 2, completed_at: "2026-04-16T00:02:00" },
		{ turn_number: 3, state_hash: "ghi789", player_count: 2, completed_at: "2026-04-16T00:03:00" },
	],
	total: 3,
	offset: 0,
	limit: 50,
};

const mockTurnDetail: TurnDetailResponse = {
	turn_number: 1,
	player_actions: {
		alice: [{ success: true, message: "Moved scout", action: { type: "move", unit_id: 1, target: { x: 1, y: 0 } } }],
		bob: [{ success: false, message: "Invalid target", action: { type: "move", unit_id: 3, target: { x: 5, y: 5 } } }],
	},
	action_results: {
		alice: [{ success: true, message: "Moved scout", action: { type: "move", unit_id: 1, target: { x: 1, y: 0 } } }],
		bob: [{ success: false, message: "Invalid target", action: { type: "move", unit_id: 3, target: { x: 5, y: 5 } } }],
	},
	state_hash: "abc123",
	completed_at: "2026-04-16T00:01:00",
};

const mockTurnPrompts: TurnPromptsResponse = {
	turn_number: 1,
	prompts: [
		{
			player_id: "alice",
			prompt: "What action should alice take?",
			response: "Move scout to (1,0)",
			tokens_in: 500,
			tokens_out: 50,
			latency_ms: 1200,
			llm_provider: "openai",
			llm_model: "gpt-4",
		},
		{
			player_id: "bob",
			prompt: "What action should bob take?",
			response: "Move worker to (5,5)",
			tokens_in: 480,
			tokens_out: 45,
			latency_ms: 900,
			llm_provider: "openai",
			llm_model: "gpt-4",
		},
	],
};

const mockGameState: GameState = {
	turn: 1,
	rng_state: 42,
	map_width: 20,
	map_height: 20,
	tiles: [
		{ id: 0, loc: { x: 0, y: 0 }, terrain: "plains", owner: "alice" },
		{ id: 1, loc: { x: 1, y: 0 }, terrain: "forest" },
	],
	units: {
		1: { id: 1, owner: "alice", type: "scout", hp: 10, moves_left: 2, loc: { x: 1, y: 0 } },
	},
	cities: {},
	players: ["alice", "bob"],
	diplomacy: {},
	stockpiles: {
		alice: { food: 100, wood: 50, ore: 30, crystal: 10 },
		bob: { food: 80, wood: 60, ore: 20, crystal: 5 },
	},
	next_unit_id: 2,
	next_city_id: 1,
	max_turns: 100,
};

describe("replay: listTurns", () => {
	it("fetches paginated turn list for a game", async () => {
		mockFetch.mockResolvedValueOnce({
			ok: true,
			json: async () => mockTurnList,
		});

		const result = await api.listTurns("my-game");
		expect(result.total).toBe(3);
		expect(result.turns).toHaveLength(3);
		expect(result.turns[0].turn_number).toBe(1);
		expect(result.turns[2].turn_number).toBe(3);
	});

	it("passes pagination params to the API", async () => {
		mockFetch.mockResolvedValueOnce({
			ok: true,
			json: async () => mockTurnList,
		});

		await api.listTurns("my-game", { offset: 10, limit: 5 });

		const [url] = mockFetch.mock.calls[0];
		expect(url).toContain("/games/my-game/turns");
		expect(url).toContain("offset=10");
		expect(url).toContain("limit=5");
	});

	it("throws ApiError on 404 for missing game", async () => {
		mockFetch.mockResolvedValueOnce({
			ok: false,
			status: 404,
			json: async () => ({ detail: "Game not found" }),
		});

		try {
			await api.listTurns("nonexistent");
			expect.fail("Should have thrown");
		} catch (err) {
			expect(err).toBeInstanceOf(ApiError);
			expect((err as ApiError).status).toBe(404);
		}
	});
});

describe("replay: getTurnDetail", () => {
	it("fetches action results for a specific turn", async () => {
		mockFetch.mockResolvedValueOnce({
			ok: true,
			json: async () => mockTurnDetail,
		});

		const result = await api.getTurnDetail("my-game", 1);
		expect(result.turn_number).toBe(1);
		expect(result.action_results.alice).toHaveLength(1);
		expect(result.action_results.alice[0].success).toBe(true);
		expect(result.action_results.bob[0].success).toBe(false);
	});

	it("includes state hash in the response", async () => {
		mockFetch.mockResolvedValueOnce({
			ok: true,
			json: async () => mockTurnDetail,
		});

		const result = await api.getTurnDetail("my-game", 1);
		expect(result.state_hash).toBe("abc123");
	});
});

describe("replay: getTurnState", () => {
	it("fetches god-mode state snapshot at a turn", async () => {
		mockFetch.mockResolvedValueOnce({
			ok: true,
			json: async () => mockGameState,
		});

		const result = await api.getTurnState("my-game", 1);
		expect(result.turn).toBe(1);
		expect(result.players).toEqual(["alice", "bob"]);
	});

	it("fetches player fog-of-war state at a turn", async () => {
		mockFetch.mockResolvedValueOnce({
			ok: true,
			json: async () => mockGameState,
		});

		await api.getTurnState("my-game", 1, "alice");

		const [url] = mockFetch.mock.calls[0];
		expect(url).toContain("/games/my-game/turns/1/state");
		expect(url).toContain("player=alice");
	});

	it("god-mode request does not include player param", async () => {
		mockFetch.mockResolvedValueOnce({
			ok: true,
			json: async () => mockGameState,
		});

		await api.getTurnState("my-game", 1);

		const [url] = mockFetch.mock.calls[0];
		expect(url).toContain("/games/my-game/turns/1/state");
		expect(url).not.toContain("player=");
	});

	it("returns 404 when no snapshot exists for turn", async () => {
		mockFetch.mockResolvedValueOnce({
			ok: false,
			status: 404,
			json: async () => ({
				detail: "No god-mode snapshot at turn 3. Full snapshots are saved every 10 turns.",
			}),
		});

		try {
			await api.getTurnState("my-game", 3);
			expect.fail("Should have thrown");
		} catch (err) {
			expect(err).toBeInstanceOf(ApiError);
			expect((err as ApiError).status).toBe(404);
		}
	});
});

describe("replay: getTurnPrompts", () => {
	it("fetches prompt logs for a turn", async () => {
		mockFetch.mockResolvedValueOnce({
			ok: true,
			json: async () => mockTurnPrompts,
		});

		const result = await api.getTurnPrompts("my-game", 1);
		expect(result.turn_number).toBe(1);
		expect(result.prompts).toHaveLength(2);
		expect(result.prompts[0].player_id).toBe("alice");
		expect(result.prompts[0].tokens_in).toBe(500);
		expect(result.prompts[1].llm_provider).toBe("openai");
	});

	it("returns empty prompts for turn with no LLM logs", async () => {
		mockFetch.mockResolvedValueOnce({
			ok: true,
			json: async () => ({ turn_number: 5, prompts: [] }),
		});

		const result = await api.getTurnPrompts("my-game", 5);
		expect(result.prompts).toHaveLength(0);
	});
});

describe("replay: query keys", () => {
	it("turnList key includes game ID", () => {
		const key = queryKeys.turnList("my-game");
		expect(key).toEqual(["game", "my-game", "turns"]);
	});

	it("turnDetail key includes game ID and turn number", () => {
		const key = queryKeys.turnDetail("my-game", 5);
		expect(key).toEqual(["game", "my-game", "turn", 5, "detail"]);
	});

	it("turnState key includes perspective", () => {
		const godKey = queryKeys.turnState("my-game", 5);
		const playerKey = queryKeys.turnState("my-game", 5, "alice");
		expect(godKey).toEqual(["game", "my-game", "turn", 5, "state", "god"]);
		expect(playerKey).toEqual(["game", "my-game", "turn", 5, "state", "alice"]);
	});

	it("turnPrompts key includes game ID and turn number", () => {
		const key = queryKeys.turnPrompts("my-game", 3);
		expect(key).toEqual(["game", "my-game", "turn", 3, "prompts"]);
	});

	it("different turns produce distinct keys", () => {
		const key1 = queryKeys.turnState("my-game", 1);
		const key2 = queryKeys.turnState("my-game", 2);
		expect(key1).not.toEqual(key2);
	});

	it("turnState perspective change produces distinct key", () => {
		const godKey = queryKeys.turnState("my-game", 1);
		const aliceKey = queryKeys.turnState("my-game", 1, "alice");
		const bobKey = queryKeys.turnState("my-game", 1, "bob");
		expect(godKey).not.toEqual(aliceKey);
		expect(aliceKey).not.toEqual(bobKey);
	});
});
