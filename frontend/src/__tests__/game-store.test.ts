import { describe, it, expect, beforeEach } from "vitest";
import { useGameStore, selectCurrentGameState, selectIsLive, selectTurnRange } from "@/store/game-store";
import type { GameState } from "@/types/game";

const makeGameState = (turn: number): GameState => ({
	turn,
	rng_state: 0,
	map_width: 20,
	map_height: 20,
	tiles: [],
	units: {},
	cities: {},
	players: ["player_1", "player_2"],
	diplomacy: {},
	stockpiles: {},
	research: {},
	next_unit_id: 1,
	next_city_id: 1,
	max_turns: 100,
});

beforeEach(() => {
	useGameStore.getState().reset();
});

describe("game store actions", () => {
	it("setGameId updates gameId", () => {
		useGameStore.getState().setGameId("test-game");
		expect(useGameStore.getState().gameId).toBe("test-game");
	});

	it("setGameState stores state and updates latestTurn", () => {
		const state = makeGameState(5);
		useGameStore.getState().setGameState(5, state);

		expect(useGameStore.getState().turns[5]).toEqual(state);
		expect(useGameStore.getState().latestTurn).toBe(5);
	});

	it("setGameState keeps highest latestTurn", () => {
		useGameStore.getState().setGameState(10, makeGameState(10));
		useGameStore.getState().setGameState(5, makeGameState(5));

		expect(useGameStore.getState().latestTurn).toBe(10);
	});

	it("setSelectedTurn updates selectedTurn", () => {
		useGameStore.getState().setSelectedTurn(7);
		expect(useGameStore.getState().selectedTurn).toBe(7);
	});

	it("setSelectedPlayer updates selectedPlayer", () => {
		useGameStore.getState().setSelectedPlayer("player_1");
		expect(useGameStore.getState().selectedPlayer).toBe("player_1");

		useGameStore.getState().setSelectedPlayer(null);
		expect(useGameStore.getState().selectedPlayer).toBeNull();
	});

	it("toggleFogOfWar flips the boolean", () => {
		expect(useGameStore.getState().fogOfWarEnabled).toBe(true);
		useGameStore.getState().toggleFogOfWar();
		expect(useGameStore.getState().fogOfWarEnabled).toBe(false);
		useGameStore.getState().toggleFogOfWar();
		expect(useGameStore.getState().fogOfWarEnabled).toBe(true);
	});

	it("setPrompts stores prompts by turn", () => {
		const prompts = [
			{
				player: "player_1",
				prompt: "What should I do?",
				response: "Move north",
				tokens_in: 100,
				tokens_out: 50,
				latency_ms: 200,
			},
		];
		useGameStore.getState().setPrompts(3, prompts);
		expect(useGameStore.getState().prompts[3]).toEqual(prompts);
	});

	it("setLoading and setError update state", () => {
		useGameStore.getState().setLoading(true);
		expect(useGameStore.getState().isLoading).toBe(true);

		useGameStore.getState().setError("Something went wrong");
		expect(useGameStore.getState().error).toBe("Something went wrong");
	});

	it("reset clears all state", () => {
		useGameStore.getState().setGameId("game-1");
		useGameStore.getState().setGameState(5, makeGameState(5));
		useGameStore.getState().setSelectedPlayer("player_1");

		useGameStore.getState().reset();

		const state = useGameStore.getState();
		expect(state.gameId).toBeNull();
		expect(state.turns).toEqual({});
		expect(state.selectedPlayer).toBeNull();
		expect(state.latestTurn).toBe(0);
	});
});

describe("selectors", () => {
	it("selectCurrentGameState returns state for selected turn", () => {
		const state5 = makeGameState(5);
		useGameStore.getState().setGameState(5, state5);
		useGameStore.getState().setSelectedTurn(5);

		const result = selectCurrentGameState(useGameStore.getState());
		expect(result).toEqual(state5);
	});

	it("selectCurrentGameState returns undefined for missing turn", () => {
		const result = selectCurrentGameState(useGameStore.getState());
		expect(result).toBeUndefined();
	});

	it("selectIsLive returns true when selectedTurn equals latestTurn", () => {
		useGameStore.getState().setGameState(5, makeGameState(5));
		useGameStore.getState().setSelectedTurn(5);

		expect(selectIsLive(useGameStore.getState())).toBe(true);
	});

	it("selectIsLive returns false when viewing historical turn", () => {
		useGameStore.getState().setGameState(5, makeGameState(5));
		useGameStore.getState().setSelectedTurn(3);

		expect(selectIsLive(useGameStore.getState())).toBe(false);
	});

	it("selectTurnRange returns min/max of stored turns", () => {
		useGameStore.getState().setGameState(3, makeGameState(3));
		useGameStore.getState().setGameState(7, makeGameState(7));
		useGameStore.getState().setGameState(5, makeGameState(5));

		const range = selectTurnRange(useGameStore.getState());
		expect(range).toEqual({ min: 3, max: 7 });
	});

	it("selectTurnRange returns 0,0 when no turns stored", () => {
		const range = selectTurnRange(useGameStore.getState());
		expect(range).toEqual({ min: 0, max: 0 });
	});
});
