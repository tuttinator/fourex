import React from "react";
import { create } from "zustand";
import { devtools, subscribeWithSelector } from "zustand/middleware";
import { api, GameWebSocket } from "@/lib/api";
import type {
	CombatEvent,
	DiplomacyEvent,
	GameInfoEvent,
	GameState,
	GameStore,
	PlayerId,
	PromptLog,
	TurnEndEvent,
	TurnStartEvent,
} from "@/types/game";

interface GameStoreActions {
	setGameId: (gameId: string) => void;
	setGameState: (turn: number, state: GameState) => void;
	setSelectedTurn: (turn: number) => void;
	setSelectedPlayer: (player: PlayerId | null) => void;
	toggleFogOfWar: () => void;
	toggleDiffMode: () => void;
	setConnectionStatus: (status: GameStore["connectionStatus"]) => void;
	setPrompts: (turn: number, prompts: PromptLog[]) => void;
	setLoading: (loading: boolean) => void;
	setError: (error: string | null) => void;

	// Actions
	connectToGame: (gameId: string) => Promise<void>;
	loadSnapshot: (turn: number) => Promise<void>;
	loadPrompts: (turn: number) => Promise<void>;
	seekToTurn: (turn: number) => Promise<void>;
	disconnect: () => void;

	// WebSocket
	ws: GameWebSocket | null;
}

export const useGameStore = create<GameStore & GameStoreActions>()(
	devtools(
		subscribeWithSelector((set, get) => ({
			// State
			gameId: null,
			turns: {},
			latestTurn: 0,
			selectedTurn: 0,
			prompts: {},
			connectionStatus: "closed",
			selectedPlayer: null,
			fogOfWarEnabled: true,
			diffMode: false,
			autoZoom: true,
			isLoading: false,
			error: null,
			ws: null,

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

			toggleDiffMode: () =>
				set((prev) => ({
					diffMode: !prev.diffMode,
				})),

			setConnectionStatus: (status) => set({ connectionStatus: status }),

			setPrompts: (turn, prompts) =>
				set((prev) => ({
					prompts: { ...prev.prompts, [turn]: prompts },
				})),

			setLoading: (loading) => set({ isLoading: loading }),

			setError: (error) => set({ error }),

			// Complex actions
			connectToGame: async (gameId: string) => {
				const state = get();

				try {
					set({ isLoading: true, error: null, gameId });

					// Get initial game state
					const gameState = await api.getGameState(gameId);
					set((prev) => ({
						turns: { ...prev.turns, [gameState.turn]: gameState },
						latestTurn: gameState.turn,
						selectedTurn: gameState.turn,
					}));

					// Set up WebSocket connection
					if (state.ws) {
						state.ws.disconnect();
					}

					const ws = new GameWebSocket(gameId);
					set({ ws });

					// WebSocket event handlers
					ws.on("connection", (status: string) => {
						console.log("WebSocket connection status:", status);
						set({ connectionStatus: status as GameStore["connectionStatus"] });
					});

					ws.on(
						"connected",
						(event: { type: string; status: string; game_id: string }) => {
							console.log("Received connected event:", event);
							// Connected event means we're successfully connected
							set({ connectionStatus: "open" });
						},
					);

					ws.on("game_info", (event: GameInfoEvent) => {
						console.log("Received game info:", event);
						// Game info means we're successfully connected (redundant but safe)
						set({ connectionStatus: "open" });
					});

					ws.on("turn_end", (event: TurnEndEvent) => {
						const { turn, game_id } = event;
						// Load the new game state
						api
							.getGameState(game_id)
							.then((newState) => {
								set((prev) => ({
									turns: { ...prev.turns, [turn]: newState },
									latestTurn: Math.max(prev.latestTurn, turn),
								}));
							})
							.catch(console.error);
					});

					ws.on("turn_start", (event: TurnStartEvent) => {
						console.log("Turn started:", event);
					});

					ws.on("diplomacy", (event: DiplomacyEvent) => {
						console.log("Diplomacy event:", event);
					});

					ws.on("combat", (event: CombatEvent) => {
						console.log("Combat event:", event);
					});

					await ws.connect();
				} catch (error) {
					const message =
						error instanceof Error
							? error.message
							: "Failed to connect to game";
					set({ error: message, connectionStatus: "error" });
					throw error;
				} finally {
					set({ isLoading: false });
				}
			},

			loadSnapshot: async (turn: number) => {
				const state = get();
				if (!state.gameId) return;

				// Return cached version if available
				if (state.turns[turn]) return;

				try {
					set({ isLoading: true });
					const snapshot = await api.getSnapshot(state.gameId, turn);
					set((prev) => ({
						turns: { ...prev.turns, [turn]: snapshot },
					}));
				} catch (error) {
					const message =
						error instanceof Error ? error.message : "Failed to load snapshot";
					set({ error: message });
					throw error;
				} finally {
					set({ isLoading: false });
				}
			},

			loadPrompts: async (turn: number) => {
				const state = get();
				if (!state.gameId) return;

				// Return cached version if available
				if (state.prompts[turn]) return;

				try {
					const prompts = await api.getPrompts(state.gameId, turn);
					set((prev) => ({
						prompts: { ...prev.prompts, [turn]: prompts },
					}));
				} catch (error) {
					console.error("Failed to load prompts:", error);
					// Don't throw for prompts as they're not critical
				}
			},

			seekToTurn: async (turn: number) => {
				const state = get();

				set({ selectedTurn: turn });

				// Load snapshot if not cached
				if (!state.turns[turn]) {
					await get().loadSnapshot(turn);
				}

				// Load prompts for the turn
				get().loadPrompts(turn);
			},

			disconnect: () => {
				const state = get();
				if (state.ws) {
					state.ws.disconnect();
				}
				set({
					ws: null,
					connectionStatus: "closed",
					gameId: null,
					turns: {},
					prompts: {},
					selectedTurn: 0,
					latestTurn: 0,
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

export const selectTurnRange = (state: GameStore) => ({
	min: Math.min(...Object.keys(state.turns).map(Number)),
	max: Math.max(...Object.keys(state.turns).map(Number)),
});

// Hook for connecting to a game with cleanup
export function useGameConnection(gameId: string | null) {
	const connectToGame = useGameStore((state) => state.connectToGame);
	const disconnect = useGameStore((state) => state.disconnect);

	React.useEffect(() => {
		if (gameId) {
			connectToGame(gameId).catch(console.error);
		}

		return () => {
			disconnect();
		};
	}, [gameId, connectToGame, disconnect]);
}
