import { create } from "zustand";
import { devtools, subscribeWithSelector } from "zustand/middleware";
import { api } from "@/lib/api";
import type {
	GameState,
	GameStore,
	PlayerId,
	PromptLog,
} from "@/types/game";

interface GameStoreActions {
	setGameId: (gameId: string) => void;
	setGameState: (turn: number, state: GameState) => void;
	setSelectedTurn: (turn: number) => void;
	setSelectedPlayer: (player: PlayerId | null) => void;
	toggleFogOfWar: () => void;
	setPrompts: (turn: number, prompts: PromptLog[]) => void;
	setLoading: (loading: boolean) => void;
	setError: (error: string | null) => void;

	// Actions
	loadGameState: (gameId: string) => Promise<void>;
	reset: () => void;
}

export const useGameStore = create<GameStore & GameStoreActions>()(
	devtools(
		subscribeWithSelector((set) => ({
			// State
			gameId: null,
			turns: {},
			latestTurn: 0,
			selectedTurn: 0,
			prompts: {},
			selectedPlayer: null,
			fogOfWarEnabled: true,
			isLoading: false,
			error: null,

			// Actions
			setGameId: (gameId) => set({ gameId }),

			setGameState: (turn, state) =>
				set((prev) => ({
					turns: { ...prev.turns, [turn]: state },
					latestTurn: Math.max(prev.latestTurn, turn),
				})),

			setSelectedTurn: (turn) => set({ selectedTurn: turn }),

			setSelectedPlayer: (player) => set({ selectedPlayer: player }),

			toggleFogOfWar: () =>
				set((prev) => ({
					fogOfWarEnabled: !prev.fogOfWarEnabled,
				})),

			setPrompts: (turn, prompts) =>
				set((prev) => ({
					prompts: { ...prev.prompts, [turn]: prompts },
				})),

			setLoading: (loading) => set({ isLoading: loading }),

			setError: (error) => set({ error }),

			loadGameState: async (gameId: string) => {
				try {
					set({ isLoading: true, error: null, gameId });

					const gameState = await api.getGameState(gameId);
					set((prev) => ({
						turns: { ...prev.turns, [gameState.turn]: gameState },
						latestTurn: gameState.turn,
						selectedTurn: gameState.turn,
					}));
				} catch (error) {
					const message =
						error instanceof Error
							? error.message
							: "Failed to load game state";
					set({ error: message });
					throw error;
				} finally {
					set({ isLoading: false });
				}
			},

			reset: () => {
				set({
					gameId: null,
					turns: {},
					prompts: {},
					selectedTurn: 0,
					latestTurn: 0,
					selectedPlayer: null,
					error: null,
				});
			},
		})),
		{ name: "game-store" },
	),
);

// Selectors for performance
export const selectCurrentGameState = (state: GameStore) =>
	state.turns[state.selectedTurn];

export const selectLatestGameState = (state: GameStore) =>
	state.turns[state.latestTurn];

export const selectCurrentPrompts = (state: GameStore) =>
	state.prompts[state.selectedTurn] || [];

export const selectIsLive = (state: GameStore) =>
	state.selectedTurn === state.latestTurn;

export const selectTurnRange = (state: GameStore) => {
	const turnKeys = Object.keys(state.turns).map(Number);
	if (turnKeys.length === 0) return { min: 0, max: 0 };
	return {
		min: Math.min(...turnKeys),
		max: Math.max(...turnKeys),
	};
};
